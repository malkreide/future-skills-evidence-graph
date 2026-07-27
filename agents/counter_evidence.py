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

    # dry run against one skill, writes nothing
    python agents/counter_evidence.py --skill skill-systems-thinking --dry-run

    # real run: emits candidate claims for review
    AI_PROVIDER=anthropic python agents/counter_evidence.py \\
        --skill skill-systems-thinking --output data/claims/candidates-counter.json
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
import ingest_openalex  # noqa: E402
from common import (  # noqa: E402
    TODAY,
    append_unique_records,
    claim_statement_key,
    fetch_or_warn,
    load_records,
    normalize_title,
    slugify,
)

# --- Hard limits ------------------------------------------------------------
#
# Module constants, NOT prompt instructions. A bound the model is asked to
# respect is not a bound. The graph's own judgement ("enough found") is the last
# filter, never the first -- an agent whose only stopping rule is its own
# opinion is an unbounded cost.
MAX_ROUNDS = 3
MAX_QUERIES = 6
MAX_BARREN_ROUNDS = 2  # consecutive rounds with nothing new -> stop
RESULTS_PER_QUERY = 10

PROMPT_VERSION = "counter-evidence-v1"

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
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}

ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["contradicts", "quote", "reason"],
    "properties": {
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

Propose up to 3 short search queries likely to surface studies that FAIL to \
find an effect for this skill, or find a negative one. Effective phrasings name \
the null result itself — "no significant difference", "failed to replicate", \
"effects did not persist", "null results", "no measurable effect" — combined \
with the topic and a school-age context. Do not simply restate the skill name.

Response schema:
{{"queries": [string]}}'''

ASSESS_PROMPT = '''System: You judge whether a study abstract provides evidence AGAINST \
a skill claim. You invent nothing. Respond only as JSON following the given schema.

User:
Skill: {name}
Definition: {definition}

Abstract:
"""{abstract}"""

Does this abstract report evidence AGAINST the skill — a null result, no \
measurable effect, a failed replication, an effect that did not persist, or a \
harm?

Judge strictly. A study reporting a SMALLER positive effect is NOT contradicting \
evidence; only an absent, reversed or non-persisting effect is. When the \
abstract is merely unrelated, answer false.

If and only if contradicts is true, set quote to the VERBATIM sentence from the \
abstract that carries the negative finding — copied exactly, not paraphrased. \
If no such sentence exists verbatim, answer false.

Response schema:
{{"contradicts": boolean, "quote": string|null, "reason": string|null}}'''


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
        proposed = [
            f"{topic} no significant difference school",
            f"{topic} null results replication students",
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


def search_and_assess(state: State) -> dict[str, Any]:
    """Run this round's queries and keep only verbatim-quotable contradictions."""
    skill = state["skill"]
    round_queries = list(state["pending_queries"])
    seen = list(state["seen_titles"])
    findings = list(state["findings"])
    examined = 0

    for query in round_queries:
        works = fetch_or_warn(
            f"openalex counter-evidence ({query})",
            lambda q=query: ingest_openalex.fetch(q, RESULTS_PER_QUERY),
        )
        for work in works:
            source = ingest_openalex.convert(work)
            title_key = normalize_title(str(source.get("title") or ""))
            abstract = str(source.get("abstract") or "").strip()
            if not title_key or title_key in seen or len(abstract) < 80:
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
            if not isinstance(verdict, dict) or not verdict.get("contradicts"):
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
        "rounds": state["rounds"] + 1,
        "barren_rounds": 0 if new_count else state["barren_rounds"] + 1,
        "log": state["log"]
        + [
            {
                "step": "search_and_assess",
                "queries": round_queries,
                "examined": examined,
                "new_findings": new_count,
            }
        ],
    }


def should_continue(state: State) -> str:
    """Hard limits first, judgement last."""
    if state.get("exhausted"):
        return "stop"
    if state["rounds"] >= MAX_ROUNDS:
        return "stop"
    if len(state["queries_used"]) >= MAX_QUERIES:
        return "stop"
    if state["barren_rounds"] >= MAX_BARREN_ROUNDS:
        return "stop"
    return "continue"


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
        "rounds": 0,
        "barren_rounds": 0,
        "exhausted": False,
        "log": [],
    }


def run(skill: dict[str, Any]) -> State:
    """Run the graph for *skill* and return its final state."""
    return build_graph().invoke(initial_state(skill))


# --- Output -----------------------------------------------------------------


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
                "id": slugify(f"{source_id.removeprefix('src-')} counter {skill_id}", "claim"),
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


def write_run_log(state: State) -> Path:
    """Persist the decision trail so a reviewer can audit an unrepeatable run."""
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    skill_id = str(state["skill"].get("id"))
    path = RUN_LOG_DIR / f"{TODAY}-{skill_id}.json"
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
        "stopped_because": should_continue(state),
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
        "--dry-run", action="store_true", help="Report findings without writing any claim."
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

    claims = to_candidate_claims(state)
    if not claims:
        print("No candidate claims written.")
        return 0

    if args.dry_run:
        print(f"\n--dry-run: would write {len(claims)} candidate claim(s):")
        for claim in claims:
            print(f"  - {claim['id']}: {claim['statement'][:100]}…")
        return 0

    # Appending through the shared helper keeps dedup, id-collision handling and
    # the no-empty-file rule identical to every importer.
    added = append_unique_records(
        ROOT / args.output, claims, lambda claim: [claim_statement_key(claim)]
    )
    print(f"\nWrote {len(added)} new candidate claim(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
