"""Agentic search for evidence that CONTRADICTS an active skill.

Why this exists: the catalogue holds 146 claims, of which exactly one carries
`contradicts_skill_ids`. `score_evidence.py` can penalise contradiction, but
nothing ever looks for it — the importers search *for* future-skills topics and
the extractor prefers a finding sentence, which in abstracts is overwhelmingly
positive. Every stage leans the same way, so `evidence_score` is a confidence
number without a counter-check. See docs/gegenevidenz-lane.md.

Why this one task is agentic while the core pipeline is not: the query is not
known in advance. "Where does the literature contradict systems thinking for
10-12 year olds?" is answered through phrasings like *no significant
difference*, *failed to replicate*, *effects did not persist* — and which one
works only shows after seeing the previous round. Iterative, stateful, with a
branch and a stopping rule: the shape LangGraph is built for. The core pipeline
has the opposite shape and stays framework-free.

Isolation (docs/gegenevidenz-lane.md), enforced by tests/test_agent_isolation.py:
this module may import from scripts/, but scripts/ must never import from here.

Determinism: every LLM call goes through ``ai_provider.complete``, never through
a langchain provider binding. A recorded run replays exactly under
``AI_PROVIDER=cache``, LangGraph stays a pure state machine, and the lane
inherits anthropic/openai/ollama without a single integration package.

    # dry run: writes no claim and no source, but DOES write a run log (that is
    # the point of it), and a live provider still fills its fixture cache
    python agents/counter_evidence.py --skill skill-systems-thinking --dry-run

    # real run: emits candidate sources AND the claims citing them, for review
    AI_PROVIDER=anthropic python agents/counter_evidence.py \\
        --skill skill-systems-thinking

Sources are persisted before the claims that cite them. A claim referencing a
source that exists nowhere fails validate_data.py ("references missing source")
and is refused by promote_candidate.py, so the ordering is load-bearing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TypedDict

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_provider  # noqa: E402
import ingest_eric  # noqa: E402
import ingest_openalex  # noqa: E402
import ingest_semantic_scholar  # noqa: E402
from common import (  # noqa: E402
    TODAY,
    append_candidate_sources,
    append_unique_records,
    claim_statement_key,
    env_or_none,
    fetch_or_warn,
    load_json,
    load_records,
    normalize_title,
    slugify,
    source_title_key,
)

# --- Hard limits ------------------------------------------------------------
#
# Module constants, NOT prompt instructions. A bound the model is asked to
# respect is not a bound. The graph's own judgement ("enough found") is the last
# filter, never the first -- an agent whose only stopping rule is its own
# opinion is an unbounded cost.
# These two are COUPLED: the query prompt asks for up to 3 queries per round, so
# a run can never spend more than MAX_ROUNDS * 3 queries. Keep MAX_ROUNDS above
# MAX_QUERIES / 3, or the round limit silently becomes the real budget and
# raising MAX_QUERIES changes nothing. Sized so 'query_budget' is what stops a
# PRODUCTIVE run -- a barren one is still cut short by MAX_BARREN_ROUNDS long
# before either ceiling.
#
# Raised from 3/6 after the first clean run: it examined 55 sources and yielded
# a single proposal, and precision over one proposal can only be 0.0 or 1.0.
# The activation rule needs a resolvable rate, not a coin flip.
MAX_ROUNDS = 5
MAX_QUERIES = 12
MAX_BARREN_ROUNDS = 2  # consecutive rounds with nothing new -> stop
RESULTS_PER_QUERY = 10

# Shorter than this, an "abstract" cannot carry a finding worth judging.
MIN_ABSTRACT_LENGTH = 80

# Search backends, tried in this order until one returns usable hits.
#
# The lane originally queried OpenAlex alone, and a real run showed why that is
# fragile: OpenAlex answered HTTP 429 and the run examined zero sources, with no
# way to tell "the literature is silent" from "the one source was throttled".
#
# CROSSREF IS DELIBERATELY ABSENT. This lane can only judge a source that has an
# abstract — without one there is nothing to assess and no verbatim sentence to
# anchor a claim on — and `ingest_crossref.convert` hard-codes `abstract: None`
# (Crossref exposes abstracts as sparsely-populated JATS XML). Adding it would
# lengthen the chain with a link that can never carry anything, which reads as
# redundancy while providing none.
#
# ERIC takes that slot instead: it carries abstracts and is education-specific,
# so it is the closest match to what this catalogue is about.
SEARCH_BACKENDS = (
    ("openalex", ingest_openalex),
    ("semantic_scholar", ingest_semantic_scholar),
    ("eric", ingest_eric),
)

# v2 narrowed what counts as a contradiction; v1 had accepted anything that
# sounded negative about the skill's subject area. v3 fixes what that revealed:
# v2 proposed nothing across three runs, and the rejection log showed why -- the
# assessor was correct every time, and 60% of what it was given was off-topic.
# The bottleneck was RETRIEVAL, not judgement. v3 rebuilds the query strategy
# around that (see QUERY_PROMPT) and splits relevance out of the verdict so the
# two failures can never again share one outcome.
#
# The version is part of the cache key and of every claim's extraction_method,
# so findings from different generations never silently mix in a measurement.
# It covers BOTH prompts: changing either one changes what a run measures.
PROMPT_VERSION = "counter-evidence-v3"

# Where a run's decision trail is written. A reviewer must be able to see which
# queries were asked, what they returned, and why the graph stopped -- the agent
# is not reproducible the way the core is, so it has to be inspectable instead.
RUN_LOG_DIR = ROOT / "agents" / "runs"


class State(TypedDict):
    """Graph state. Plain data, so a run can be serialised into the log."""

    skill: dict[str, Any]
    # Queries this round should run; propose_queries fills it, search_and_assess
    # drains it. Explicit hand-off beats recomputing "which are new" from history.
    pending_queries: list[str]
    queries_used: list[str]
    seen_titles: list[str]
    findings: list[dict[str, Any]]
    # Why each examined source did NOT become a finding. Without this a run that
    # proposes nothing is unreadable: "the assessor is too strict" and "the
    # abstracts held nothing quotable" look identical, and for a lane hunting
    # contradictions that is the expensive confusion — an empty run reads like
    # the catalogue being right.
    rejected: list[dict[str, Any]]
    rounds: int
    barren_rounds: int
    # Set when a round had no query left to run — the generator has stopped
    # producing anything new, so further rounds would spin without searching.
    exhausted: bool
    log: list[dict[str, Any]]


QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["queries"],
    # No 'maxItems' here, deliberately. Anthropic's structured-output endpoint
    # rejects it -- "output_config.format.schema: For 'array' type, property
    # 'maxItems' is not supported" (HTTP 400), observed on the first workflow
    # run of this lane. Every such 400 makes complete() return None, and the
    # lane then falls back to its fixed seed queries: the run still produces
    # findings, so the failure is silent unless someone reads the warnings.
    # The cap belongs in code anyway -- propose_queries() truncates against
    # MAX_QUERIES, which a schema hint could not enforce.
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
    },
}

ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "contradicts", "quote", "reason"],
    "properties": {
        # Asked BEFORE the contradiction question, because the two failures mean
        # opposite things. A v2 run rejected 47 of 47 sources as
        # "not_contradicting" -- which read like a strict assessor or an empty
        # literature, when in fact 60% of them were about incarceration stigma,
        # parenting attitudes and cigar warning labels. The assessor was right
        # every time; the SEARCH was missing. One outcome cannot carry both
        # meanings, so relevance is now its own answer and the off-topic share
        # becomes the direct measure of search quality.
        "relevant": {"type": "boolean"},
        # A null result / no measurable effect / a harm counts; a merely weaker
        # positive effect does NOT, or every study becomes contradicting.
        "contradicts": {"type": "boolean"},
        # Must be verbatim from the abstract: the project's no-claim-without-a-
        # text-anchor rule applies here exactly as it does to every importer.
        "quote": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
}

QUERY_PROMPT = '''System: You design literature search queries that look for evidence \
AGAINST an educational claim. You are not looking for support. Respond only as \
JSON following the given schema.

User:
Skill: {name}
Definition: {definition}

Queries already tried (do not repeat them):
{tried}

Findings so far: {found_count}

Propose up to 3 short search queries.

These go to a bibliographic FULL-TEXT search, which treats a query as a bag of \
words and ranks by how many match. That has a consequence worth stating plainly, \
because the obvious strategy fails on it: stringing negations together — \
"no significant difference", "null results", "effects did not persist" — does \
NOT find null results. Words like *no*, *significant*, *difference*, *results* \
and *students* match almost anything, they outnumber the terms that carry the \
topic, and the search returns unrelated literature. Measured: a run built that \
way returned studies on incarceration stigma, parenting attitudes and cigar \
warning labels, and 60% of everything it examined was off-topic.

So: make the query narrow on the SUBJECT, and let the assessor do the filtering \
for null results — it is strict enough, and it never sees what the search fails \
to return.

- Lead with the skill's own terminology, and the population or setting it \
  applies to. These are the words that must match.
- At most ONE further term, and only where it concentrates where null results \
  get reported: "meta-analysis", "systematic review", "randomized controlled \
  trial", "replication". These name study TYPES, not outcomes.
- Never more than one negation word in a query. Prefer none.
- Vary the angle between queries — a sub-construct, a different age band, a \
  neighbouring intervention. Do not simply restate the skill name.

Response schema:
{{"queries": [string]}}'''

ASSESS_PROMPT = '''System: You judge whether a study abstract provides evidence AGAINST \
a skill claim. You invent nothing. Respond only as JSON following the given schema.

User:
Skill: {name}
Definition: {definition}

Abstract:
"""{abstract}"""

FIRST: is this abstract about this skill at all? Set relevant to false when the \
study concerns a different subject entirely — a search returns whatever matched \
its words, and much of it has nothing to do with the skill. Judge relevance by \
subject matter alone, not by whether the finding is positive or negative. When \
relevant is false, set contradicts to false, quote to null, and say in one \
clause what the study is actually about.

THEN, only if it is relevant: the claim under test is that this skill MATTERS — \
that developing it leads to better outcomes. Evidence against it is a MEASURED \
RESULT showing that it does not.

Answer contradicts false unless all three hold:

1. The study MEASURED something. A position paper, a legal or ethical analysis, \
a survey of what teachers or students believe, or the description of a design \
is not a measurement, however critical its tone.
2. What was measured is an OUTCOME of engaging with the skill — a training, an \
intervention, a program, a deliberate exposure. How well some population happens \
to perform is not that.
3. The result is absent, reversed, or did not persist. A smaller positive effect \
is still a positive effect.

Two traps, both observed in real runs of this lane:

- **"People are bad at this" is not evidence against the skill.** That students \
fall for misinformation, or cannot distinguish AI-written from human-written \
text, shows the skill is SCARCE — which argues FOR its importance, not against \
its value. Only a study where teaching or practising the skill failed to help \
counts here.
- **A null result about the wrong quantity does not count.** A population's mean \
measured against a hypothetical mean, or an absence of differences BETWEEN \
groups, says nothing about whether the skill works.

If and only if contradicts is true, set quote to the VERBATIM sentence from the \
abstract that STATES THAT FINDING — copied exactly, not paraphrased. The \
sentence must carry the result itself, not the study's aim, method or framing: \
if your reason names a finding the quoted sentence does not contain, you have \
picked the wrong sentence. If no such sentence exists verbatim, answer false.

Response schema:
{{"relevant": boolean, "contradicts": boolean, "quote": string|null, \
"reason": string|null}}'''


def active_skill(skill_id: str) -> dict[str, Any] | None:
    """The active skill with *skill_id*, or None.

    Only ACTIVE skills are targets: a candidate skill is itself unreviewed, and
    hunting for contradictions of unreviewed evidence is noise.
    """
    for skill in load_records("skills"):
        if skill.get("id") == skill_id and skill.get("status") == "active":
            return skill
    return None


# --- Graph nodes ------------------------------------------------------------


def propose_queries(state: State) -> dict[str, Any]:
    """Ask for search queries aimed at null results; fall back to a fixed set."""
    skill = state["skill"]
    prompt = QUERY_PROMPT.format(
        name=skill.get("name", ""),
        definition=skill.get("definition", ""),
        tried="\n".join(f"- {q}" for q in state["queries_used"]) or "(none yet)",
        found_count=len(state["findings"]),
    )
    result = ai_provider.complete(prompt, schema=QUERY_SCHEMA)
    proposed = [str(q).strip() for q in (result or {}).get("queries", []) if str(q).strip()]

    if not proposed:
        # With AI off or unavailable the lane still does something useful rather
        # than nothing: a deterministic phrasing over the skill name. Same
        # graceful-degradation rule as every importer.
        topic = skill.get("name", "")
        # Same rule the prompt explains: name the subject, add a study TYPE that
        # concentrates null reporting, and leave the null-filtering to the
        # assessor. Stacking negations here would reproduce the retrieval failure
        # these two exist to survive.
        proposed = [
            f"{topic} meta-analysis",
            f"{topic} randomized controlled trial school",
        ]

    # Never repeat a query, and never exceed the total budget — the limit is
    # enforced here in code, not asked for in the prompt.
    fresh: list[str] = []
    for query in proposed:
        if query in state["queries_used"] or query in fresh:
            continue
        if len(state["queries_used"]) + len(fresh) >= MAX_QUERIES:
            break
        fresh.append(query)
    return {
        "pending_queries": fresh,
        "queries_used": state["queries_used"] + fresh,
        "log": state["log"] + [{"step": "propose_queries", "queries": fresh}],
    }


def usable_sources(works: list[dict[str, Any]], convert: Any) -> list[dict[str, Any]]:
    """Convert search hits and keep only those this lane can actually judge.

    "Usable" means carrying an abstract long enough to hold a finding: without
    one there is nothing to assess and no verbatim sentence to anchor a claim on.
    """
    sources = []
    for work in works:
        source = convert(work)
        if len(str(source.get("abstract") or "").strip()) >= MIN_ABSTRACT_LENGTH:
            sources.append(source)
    return sources


def search_query(query: str) -> tuple[list[dict[str, Any]], str | None]:
    """First backend that returns something usable wins. Returns (sources, backend).

    A fallback chain rather than a union of all backends: every source examined
    costs one model call, so querying three backends per query would roughly
    triple the run's cost for redundancy that is only needed when one is down.
    The chain moves on when a backend errors (`fetch_or_warn` swallows it into
    an empty list) *and* when it returns hits none of which carry an abstract —
    ten abstract-less hits are as useless here as an outage.
    """
    for name, module in SEARCH_BACKENDS:
        works = fetch_or_warn(
            f"{name} counter-evidence ({query})",
            lambda m=module: _fetch_from(m, query),
        )
        sources = usable_sources(works, module.convert)
        if sources:
            return sources, name
    return [], None


def _fetch_from(module: Any, query: str) -> list[dict[str, Any]]:
    """Call one backend's fetch, passing the optional credentials it accepts."""
    if module is ingest_semantic_scholar:
        # Without the key this source rate-limits hard (HTTP 429); with it the
        # fallback chain actually has a second working link.
        return module.fetch(query, RESULTS_PER_QUERY, env_or_none("SEMANTIC_SCHOLAR_API_KEY"))
    if module is ingest_openalex:
        # A contact address raises OpenAlex's rate limit — the polite pool.
        return module.fetch(query, RESULTS_PER_QUERY, env_or_none("OPENALEX_MAILTO"))
    return module.fetch(query, RESULTS_PER_QUERY)


def search_and_assess(state: State) -> dict[str, Any]:
    """Run this round's queries and keep only verbatim-quotable contradictions."""
    skill = state["skill"]
    round_queries = list(state["pending_queries"])
    seen = list(state["seen_titles"])
    findings = list(state["findings"])
    rejected = list(state["rejected"])
    examined = 0
    backends_used: list[str] = []

    def reject(source: dict[str, Any], outcome: str, reason: Any = None) -> None:
        rejected.append(
            {
                "source_title": source.get("title"),
                "outcome": outcome,
                # The model may volunteer a reason on a negative verdict; the
                # schema allows it and the prompt does not forbid it. It was
                # simply discarded before. Often null -- that absence is itself
                # readable, and capturing it needs no prompt change, so v2 stays
                # the same assessor it was when it was measured.
                "reason": reason,
            }
        )

    for query in round_queries:
        sources, backend = search_query(query)
        if backend and backend not in backends_used:
            backends_used.append(backend)
        for source in sources:
            title_key = normalize_title(str(source.get("title") or ""))
            abstract = str(source.get("abstract") or "").strip()
            if not title_key or title_key in seen:
                continue
            seen.append(title_key)
            examined += 1

            verdict = ai_provider.complete(
                ASSESS_PROMPT.format(
                    name=skill.get("name", ""),
                    definition=skill.get("definition", ""),
                    abstract=abstract,
                ),
                schema=ASSESS_SCHEMA,
            )
            # Three distinct ways not to become a finding, and they mean opposite
            # things about a barren run: a dead provider is not a judgement, a
            # negative verdict is the assessor working, and a rejected anchor is
            # the assessor finding something it could not quote.
            if not isinstance(verdict, dict):
                reject(source, "no_verdict")
                continue
            if not verdict.get("relevant"):
                reject(source, "off_topic", verdict.get("reason"))
                continue
            if not verdict.get("contradicts"):
                reject(source, "on_topic_no_contradiction", verdict.get("reason"))
                continue
            quote = str(verdict.get("quote") or "").strip()
            # No claim without a verifiable text anchor: the quote must occur
            # verbatim in the abstract, or the finding is discarded outright.
            if not quote or quote not in abstract:
                print(
                    f"Warning: discarding a contradiction for {source.get('id')} — "
                    "the quote is not verbatim in the abstract.",
                    file=sys.stderr,
                )
                reject(source, "quote_not_verbatim", verdict.get("reason"))
                continue
            findings.append({"source": source, "quote": quote, "reason": verdict.get("reason")})

    new_count = len(findings) - len(state["findings"])
    return {
        "pending_queries": [],
        # An empty round means propose_queries had nothing new left. Spending
        # further rounds on that would spin without searching anything.
        "exhausted": not round_queries,
        "seen_titles": seen,
        "findings": findings,
        "rejected": rejected,
        "rounds": state["rounds"] + 1,
        "barren_rounds": 0 if new_count else state["barren_rounds"] + 1,
        "log": state["log"]
        + [
            {
                "step": "search_and_assess",
                "queries": round_queries,
                # Which backend actually answered. A run that fell through to a
                # fallback looks identical in the counts otherwise, and a
                # reviewer judging a thin harvest should see that OpenAlex was
                # down rather than conclude the literature is silent.
                "backends": backends_used,
                "examined": examined,
                "new_findings": new_count,
            }
        ],
    }


def should_continue(state: State) -> str:
    """Hard limits first, judgement last. The graph edge only needs stop/continue."""
    return "continue" if stop_reason(state) is None else "stop"


def stop_reason(state: State) -> str | None:
    """WHICH limit ended the run, or None while it may continue.

    Kept separate from should_continue because the graph edge only needs
    "stop"/"continue", while the run log needs the actual reason: a reviewer
    judging whether a barren search means "no counter-evidence exists" or "the
    budget ran out too early" cannot tell those apart from the word "stop".
    """
    if state.get("exhausted"):
        return "no_new_queries"
    if state["rounds"] >= MAX_ROUNDS:
        return "round_limit"
    if len(state["queries_used"]) >= MAX_QUERIES:
        return "query_budget"
    if state["barren_rounds"] >= MAX_BARREN_ROUNDS:
        return "no_new_findings"
    return None


def build_graph():
    """Compile the LangGraph state machine (lazy import: agents-only dependency).

    The import is deliberately late and its failure deliberately explained: the
    core installs only requirements-dev.txt, so reaching this line without
    LangGraph is the expected first experience, not a bug.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised by running without the dep
        raise SystemExit(
            f"This lane needs LangGraph, which the core deliberately does not install ({exc}).\n"
            "  pip install -r requirements-agents.txt\n"
            "See docs/gegenevidenz-lane.md for why it is kept separate."
        ) from exc

    graph = StateGraph(State)
    graph.add_node("propose_queries", propose_queries)
    graph.add_node("search_and_assess", search_and_assess)
    graph.set_entry_point("propose_queries")
    graph.add_edge("propose_queries", "search_and_assess")
    graph.add_conditional_edges(
        "search_and_assess",
        should_continue,
        {"continue": "propose_queries", "stop": END},
    )
    return graph.compile()


def initial_state(skill: dict[str, Any]) -> State:
    return {
        "skill": skill,
        "pending_queries": [],
        "queries_used": [],
        "seen_titles": [],
        "findings": [],
        "rejected": [],
        "rounds": 0,
        "barren_rounds": 0,
        "exhausted": False,
        "log": [],
    }


def run(skill: dict[str, Any]) -> State:
    """Run the graph for *skill* and return its final state."""
    return build_graph().invoke(initial_state(skill))


# --- Output -----------------------------------------------------------------


def persist_sources(state: State, path: Path) -> tuple[int, int]:
    """Write the discovered sources as candidates and pin each claim's source id.

    Without this the lane emits claims pointing at sources that exist nowhere:
    ``validate_data.py`` fails with "references missing source" and
    ``promote_candidate.py`` refuses the candidate for the same reason. Sources
    must therefore land BEFORE the claims that cite them.

    Two id subtleties, both handled here rather than hoped away:

    - ``append_unique_records`` renames a record in place on an id collision
      (``src-foo`` -> ``src-foo-2``). Because it mutates the same dict the
      findings hold, building the claims *after* this call picks up the final id.
    - A source already in the repository is skipped, and the skipped dict keeps
      the id this run computed — which may differ from the stored one. For those
      the stored id is looked up by title key and written back, so the claim
      cites the record that actually exists.

    Returns (appended, reused).
    """
    sources = [finding["source"] for finding in state["findings"]]
    if not sources:
        return 0, 0

    appended = append_candidate_sources(path, sources)
    appended_ids = {id(record) for record in appended}

    # Resolve every skipped source to the id under which it is actually stored.
    # The target file comes FIRST and wins: a source skipped as a duplicate was
    # most likely matched against a record in that very file, and load_records
    # only sees data/sources/ — which need not be where --source-output points.
    stored: dict[str, Any] = {}
    for record in load_records("sources"):
        stored.setdefault(source_title_key(record), record.get("id"))
    if path.exists():
        for record in load_json(path):
            stored[source_title_key(record)] = record.get("id")
    reused = 0
    for source in sources:
        if id(source) in appended_ids:
            continue
        existing_id = stored.get(source_title_key(source))
        if existing_id and existing_id != source.get("id"):
            source["id"] = existing_id
        reused += 1
    return len(appended), reused


def to_candidate_claims(state: State) -> list[dict[str, Any]]:
    """Turn findings into candidate claims — candidates only, never active.

    Shaped exactly like an importer's output: verbatim statement, a text anchor
    naming the exact quote, placeholders for the human review fields, and
    `contradicts_skill_ids` pointing at the (active) skill this argues against.
    """
    skill_id = str(state["skill"].get("id"))
    claims: list[dict[str, Any]] = []
    for finding in state["findings"]:
        source = finding["source"]
        source_id = str(source.get("id", "unknown-source"))
        claims.append(
            {
                "id": claim_id_for(source, skill_id),
                "statement": finding["quote"],
                "source_ids": [source_id],
                "text_anchor": f'abstract, verbatim: "{finding["quote"]}"',
                "context": f"Counter-evidence candidate for {skill_id}. REVIEW REQUIRED.",
                "age_range": "TODO",
                "outcome": "TODO",
                "evidence_type": "empirical_study",
                "evidence_strength": "low",
                "supports_skill_ids": [],
                "contradicts_skill_ids": [skill_id],
                "extraction_method": f"counter_evidence_agent_{PROMPT_VERSION}",
                "status": "candidate",
                "created_at": TODAY,
                "reviewed_at": None,
            }
        )
    return claims


def claim_id_for(source: dict[str, Any], skill_id: str) -> str:
    """The id a candidate claim from *source* would carry.

    One definition, two callers: build_claims mints the real claim, and the run
    log names it so a reviewer reading a dry run can find the claim a later real
    run would create. Two copies of this formula would drift, and the log would
    then point at an id that never exists.
    """
    source_id = str(source.get("id", "unknown-source"))
    return slugify(f"{source_id.removeprefix('src-')} counter {skill_id}", "claim")


def write_run_log(state: State) -> Path:
    """Persist the decision trail so a reviewer can audit an unrepeatable run."""
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    skill_id = str(state["skill"].get("id"))
    # The PROMPT_VERSION belongs in the NAME, not only in the payload. Without it
    # a v2 run silently overwrote the v1 log for the same skill on the same day --
    # and the activation rule requires three runs sharing a version, so the very
    # thing that distinguishes two measurements was the thing the filename lost.
    # Two runs of the same skill under the same version on the same day still
    # collapse, and that is correct: those are re-measurements, and the newer one
    # is the truth. Only versions must never merge.
    path = RUN_LOG_DIR / f"{TODAY}-{skill_id}-{PROMPT_VERSION}.json"
    payload = {
        "skill_id": skill_id,
        "prompt_version": PROMPT_VERSION,
        "model": ai_provider.ai_model(),
        "provider": ai_provider.ai_provider(),
        "created_at": TODAY,
        "rounds": state["rounds"],
        "queries_used": state["queries_used"],
        "sources_examined": len(state["seen_titles"]),
        "findings": len(state["findings"]),
        # The findings THEMSELVES, not just how many. Precision -- the number the
        # activation rule turns on -- is a reviewer's judgement over each proposed
        # contradiction, so a log carrying only a count cannot support the one
        # decision it exists for. 'reason' matters most: a quote can read like a
        # positive result while the assessor saw a null in a clause the quote cut
        # off, and only the reason distinguishes that from a false positive.
        # On a dry run this is the ONLY record of them; the candidate claims are
        # never written.
        "proposed": [
            {
                "claim_id": claim_id_for(finding["source"], skill_id),
                "source_id": finding["source"].get("id"),
                "source_title": finding["source"].get("title"),
                "source_url": finding["source"].get("url"),
                "quote": finding["quote"],
                "reason": finding["reason"],
            }
            for finding in state["findings"]
        ],
        # The other side of the ledger. 'proposed' alone cannot explain a run that
        # proposed nothing, and the four outcomes mean different things:
        #   no_verdict                 the provider failed — not a judgement
        #   off_topic                  the SEARCH missed; the assessor was right
        #   on_topic_no_contradiction  the assessor read a relevant study, said no
        #   quote_not_verbatim         it said yes but could not anchor it
        # Only the third is evidence about the literature. A run dominated by
        # off_topic says the retrieval is broken, which reads identically at the
        # top level -- zero findings -- and demands the opposite repair. That
        # conflation is why the split exists: v2 logged 47 of 47 as one outcome,
        # and 60% of those were simply other subjects.
        "rejected": len(state["rejected"]),
        "rejected_by_outcome": {
            outcome: sum(1 for r in state["rejected"] if r["outcome"] == outcome)
            for outcome in sorted({r["outcome"] for r in state["rejected"]})
        },
        "not_proposed": state["rejected"],
        # The specific limit, not the word "stop": a reviewer must be able to
        # tell "no counter-evidence exists" from "the budget ran out too early".
        "stopped_because": stop_reason(state) or "still_running",
        "log": state["log"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search for evidence contradicting an active skill (candidates only)."
    )
    parser.add_argument("--skill", required=True, help="Active skill id to challenge.")
    parser.add_argument(
        "--output",
        default="data/claims/candidates-counter.json",
        help="Where to append candidate counter-claims.",
    )
    parser.add_argument(
        "--source-output",
        default="data/sources/candidates-counter.json",
        help="Where to append the discovered candidate sources the claims cite.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write no claim and no source. The run log is still written (it is the "
        "point of a dry run), and a live provider still fills its fixture cache.",
    )
    args = parser.parse_args()

    skill = active_skill(args.skill)
    if skill is None:
        print(
            f"FAIL: {args.skill!r} is not an active skill. Only active skills are "
            "challenged; a candidate skill is itself unreviewed.",
            file=sys.stderr,
        )
        return 1

    state = run(skill)
    log_path = write_run_log(state)

    print(
        f"{skill.get('name')}: {len(state['findings'])} contradiction(s) from "
        f"{len(state['seen_titles'])} source(s) over {state['rounds']} round(s).\n"
        f"Queries: {', '.join(state['queries_used']) or '(none)'}\n"
        f"Run log: {log_path.relative_to(ROOT)}"
    )

    if not state["findings"]:
        print("No contradictions found; nothing to write.")
        return 0

    if args.dry_run:
        # Claims are built for display only. Nothing is persisted, so the ids
        # shown are provisional — a real run may renumber them on collision.
        print(f"\n--dry-run: would write {len(state['findings'])} candidate claim(s):")
        for claim in to_candidate_claims(state):
            print(f"  - {claim['id']}: {claim['statement'][:100]}…")
        return 0

    # Sources FIRST: a claim citing a source that exists nowhere fails
    # validate_data.py and is refused by promote_candidate.py. persist_sources
    # also pins each finding's source id to the one actually stored, so the
    # claims built next cite a record that exists.
    appended, reused = persist_sources(state, ROOT / args.source_output)
    print(f"\nSources: {appended} new, {reused} already known ({args.source_output}).")

    # Appending through the shared helper keeps dedup, id-collision handling and
    # the no-empty-file rule identical to every importer.
    added = append_unique_records(
        ROOT / args.output, to_candidate_claims(state), lambda claim: [claim_statement_key(claim)]
    )
    print(f"Wrote {len(added)} new candidate claim(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
