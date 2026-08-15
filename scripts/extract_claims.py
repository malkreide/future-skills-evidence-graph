"""Extract candidate claims from candidate source abstracts.

Implements pipeline steps 3 and 4 of MASTER_PROMPT.md deterministically and
without an LLM: the claim statement is a verbatim sentence from the source
abstract, selected with the shared topic/audience keyword vocabulary, and the
text anchor records the exact sentence position and quote so reviewers can
verify the evidence path. Sources without an abstract yield no claim — no
claim without a text anchor. Everything stays in candidate status until a
human review fills in context, age range, outcome, and evidence strength.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any

import ai_provider
import appraisal
from common import (
    AGE_SCALE,
    EVIDENCE_STRENGTH_LIST,
    EVIDENCE_STRENGTH_VALUES,
    ROOT,
    TODAY,
    append_unique_records,
    claim_statement_key,
    filter_new_claims,
    load_json,
    load_records,
    normalize_title,
    score_relevance,
    slugify,
)


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE_LENGTH = 40

# Up to this many finding sentences per abstract become separate candidate
# claims. One abstract often reports several independent findings, and skill
# scoring explicitly rewards breadth — extracting only the single best sentence
# threw that evidence away. Kept small so review effort stays bounded.
MAX_CLAIMS_PER_SOURCE = 3

# Abbreviations whose trailing period must NOT end a sentence. Without this,
# "schools (e.g. primary schools). Results show ..." split after "e.g." and the
# text anchor pointed at the wrong sentence number. Matched case-insensitively;
# the German set covers the bilingual vocabulary's sources.
_ABBREVIATIONS = (
    "e.g.", "i.e.", "et al.", "cf.", "vs.", "approx.", "ca.", "resp.",
    "no.", "vol.", "fig.", "figs.", "ed.", "eds.", "pp.", "p.", "st.",
    "dr.", "prof.", "u.s.", "u.k.",
    "z. b.", "z.b.", "u. a.", "u.a.", "d. h.", "d.h.", "bzw.", "bspw.",
    "inkl.", "evtl.", "ggf.", "sog.", "usw.", "etc.",
)
# The lookbehind keeps the match anchored to a token start, so "p." never
# swallows the genuine sentence end of "develop." or "st." that of "first.".
_ABBREVIATION_PATTERN = re.compile(
    "(?<![a-zA-Z])(" + "|".join(re.escape(abbr) for abbr in _ABBREVIATIONS) + ")",
    re.IGNORECASE,
)
_DOT_SENTINEL = "\x00"


def split_sentences(text: str) -> list[str]:
    """Split *text* into sentences without breaking after known abbreviations.

    The abbreviation periods are masked before the boundary split and restored
    afterwards, so the returned sentences stay verbatim substrings (modulo the
    whitespace collapse the caller applies).
    """
    masked = _ABBREVIATION_PATTERN.sub(
        lambda match: match.group(0).replace(".", _DOT_SENTINEL), text
    )
    return [part.replace(_DOT_SENTINEL, ".") for part in SENTENCE_SPLIT.split(masked)]

# Cues that mark a sentence as reporting a finding/conclusion (preferred) or as
# describing methodology/structure/aims (avoided). Among the topic-matching
# sentences, a finding sentence is chosen over a neutral one, and a neutral one
# over a method sentence, so extraction surfaces results rather than "we used
# interviews" or "this paper introduces a six-step design". Heuristic and
# LLM-free; matched as whole phrases against the normalized sentence.
FINDING_CUES = (
    "we find", "we found", "findings", "results show", "results suggest",
    "results indicate", "results reveal", "study shows", "study suggests",
    "study finds", "demonstrates that", "evidence suggests", "evidence shows",
    "we show", "we demonstrate", "indicates that", "suggests that",
    "reveals that", "identifies", "improves", "improved", "improvements",
    "enhances", "enhanced", "associated with", "effective", "significant",
    "concludes", "led to", "resulted in", "fosters", "promotes",
)
METHOD_CUES = (
    "we used", "were used", "we conducted", "we collected", "data were collected",
    "data was collected", "participants were", "we administered", "we interviewed",
    "interviews were", "questionnaire", "sample of", "we recruited",
    "this paper introduces", "this paper presents", "this article presents",
    "this article describes", "this paper proposes", "introduces a", "presents a",
    "we propose", "we present", "is organized", "is structured", "employs",
    "this study examines", "this study explores", "this study aims", "the aim of",
    "in this paper", "this chapter", "to explore", "to investigate", "to examine",
    "case study", "we describe",
)

EVIDENCE_TYPE_BY_SOURCE_TYPE = {
    "systematic_review": "systematic_review",
    "peer_reviewed_article": "empirical_study",
    "working_paper": "empirical_study",
    "dataset": "empirical_study",
    "framework": "framework_synthesis",
    "policy_report": "policy_synthesis",
}
DEFAULT_EVIDENCE_TYPE = "conceptual_review"

# Placeholder values written for fields a human reviewer must complete before
# a claim can be promoted to reviewed. promote_candidate.py imports these so
# the review gate stays in sync with what extraction actually leaves behind.
AGE_RANGE_PLACEHOLDER = "unspecified"
OUTCOME_PLACEHOLDER = "Not extracted automatically; describe during review."
CONTEXT_PLACEHOLDER_SUFFIX = "Verify during review."

# --- Optional LLM claim pre-fill (P1) -------------------------------------
#
# When (and only when) an AI provider is configured (AI_PROVIDER != none) the
# extractor additionally asks the LLM to *suggest* the otherwise-manual review
# fields (context, outcome, age_range, evidence_strength). The suggestion is
# stored under claim["assist"] as a NON-binding proposal; the real fields keep
# their placeholders and statement/text_anchor stay verbatim. With the provider
# off this whole path is inert and the output is byte-identical to before.

# Versioned so every stored suggestion carries its prompt version in provenance.
# v2: prompt rewritten in English so the free-text outcome/context suggestions are
# produced in English, matching the English review-field corpus and the English
# gold set in eval/claim_prefill_labeled.json. (The German v1 prompt made the live
# model answer in German, which scored near-zero against the English gold.)
# v3: de-bias the two structured fields against the gold calibration — drop the
# "estimated conservatively / when in doubt low" wording that pushed the live
# model one strength notch low, and tell it not to pad the age band to the scale
# ceiling (the live model over-extended upper ages to 18).
# v4: the first English live run showed evidence_strength still one notch below
# gold, so pin an explicit study-type rubric (RCT / systematic review / meta-
# analysis => high; controlled or multi-site => moderate; single small or
# uncontrolled => low) that matches how the gold set was labeled.
# v5: tried mapping a named school stage to a typical age band to lift age_range
# recall. The live run showed this backfired -- the model produced broad stage
# bands (primary => 6-12) where the gold has the study's narrower band (10-12),
# so recall did not move and age_range PRECISION fell 0.94 -> 0.82.
# v6: revert to v4's age wording (abstain when no explicit age). Recall is no
# longer hard-gated (precision is the reviewer-trust metric; see
# eval_claim_prefill.py and OPERATIONS "Re-recording"), so safe abstention no
# longer costs, and keeping the band precise matters more.
# v7: two changes, neither of them about age.
#   (a) The strength vocabulary was WRONG. The prompt and its schema asked for
#       {low, moderate, high}, but the claim schema and promote_candidate.py
#       only accept {low, moderate, strong} -- so the top suggestion named a
#       value a reviewer could not actually enter. Both now render from
#       common.EVIDENCE_STRENGTH_VALUES, the single vocabulary.
#   (b) evidence_strength never abstained (50/50 proposed on the golden set): a
#       model that always guesses a strength is exactly the reviewer-trust risk
#       the gate exists to catch. The prompt now names null as the right answer
#       when the abstract does not reveal the study type.
# age_range wording is deliberately untouched: of its 8 recall misses, none name
# an age in the abstract ("across grade levels", "across school ages", "two
# primary cohorts"), so recovering them means inferring a band from a stage name
# -- which is what v5 did, and it cost precision 0.94 -> 0.82.
#
# LEGACY as of the appraisal model (scripts/appraisal.py). Two things in this
# prompt are now known to be wrong, and both are below in v7's own words:
#
#   - "a randomised controlled trial, systematic review or meta-analysis =>
#     strong" derives evidence quality from the publication type. A systematic
#     review of weak, heterogeneous primary studies is not strong evidence.
#   - evidence_strength itself conflates design, quantity and effect direction,
#     which is why a null finding could not be rated as anything but weak.
#
# The prompt is nonetheless FROZEN, and deliberately so. The provider cache
# keys a fixture on the full prompt text (ai_provider.request_payload), so
# editing one character invalidates all 50 committed fixtures under
# tests/fixtures/ai/ and sends the offline eval live -- CI would go red for a
# reason that has nothing to do with the model. Replacing it therefore requires
# a recording run: see APPRAISAL_PROMPT_VERSION below for the successor prompt
# and OPERATIONS.md "Re-recording" for the procedure.
PREFILL_PROMPT_VERSION = "claim-prefill-v7"

# Strict JSON Schema for the suggestion (enforced via output_config.format). It
# mirrors Anhang A: every field is optional content (null when the abstract does
# not support it); evidence_strength uses the claim schema's vocabulary, so the
# model can never propose a value promote_candidate.py would refuse.
PREFILL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["age_range", "outcome", "context", "evidence_strength"],
    "properties": {
        "age_range": {"type": ["string", "null"]},
        "outcome": {"type": ["string", "null"]},
        "context": {"type": ["string", "null"]},
        "evidence_strength": {"enum": [*EVIDENCE_STRENGTH_VALUES, None]},
    },
}

PREFILL_SUGGESTION_FIELDS = ("age_range", "outcome", "context", "evidence_strength")

# In-feature prompt, version 1 (docs/ki-weiterentwicklung-plan.md, Anhang A).
# System and user turn are concatenated into the single prompt the provider
# takes; the response shape is constrained by PREFILL_OUTPUT_SCHEMA, not prefill.
PREFILL_PROMPT_TEMPLATE = '''System: You extract structured evidence metadata from the abstract of an \
educational-research study. Invent nothing. If the abstract does not support a \
value, return null for that field. Respond only as JSON following the given \
schema, and write every free-text field in English.

User:
Abstract:
"""{abstract}"""

Already-extracted verbatim finding sentence (DO NOT change):
"""{statement}"""

Detected topics: {topics}

Provide suggestions for this claim's review fields:
- age_range: The actually reported age range of the studied learners as \
"min-max" on the {age_scale} scale — early childhood and kindergarten \
(Lehrplan 21 cycle 1) explicitly included —, or null if the abstract names no \
age. Report the band the study actually concerns; do not pad it to the scale \
ends. Clip ranges beyond {age_scale} to {age_scale}; pure adult samples => null.
- outcome: one sentence, in English, stating which learning outcome/effect is \
reported (neutral, without exaggeration), or null.
- context: one sentence, in English, on the setting (country, school level, \
type of intervention), or null.
- evidence_strength: one of {{{strength_values}}}, judged from study type and \
sample: a randomised controlled trial, systematic review or meta-analysis => \
strong; a controlled, quasi-experimental or multi-site study => moderate; a \
single small, uncontrolled, descriptive or design/working-paper study => low. \
Return null if the abstract does not reveal the study type or sample — guessing \
a strength misleads the reviewer, abstaining does not.

Response schema:
{{"age_range": string|null, "outcome": string|null, "context": string|null, \
 "evidence_strength": {strength_schema}|null}}'''


# --- Appraisal suggestion (successor to the pre-fill strength field) -------
#
# v1. Separately versioned and NOT wired into the default extraction path:
# turning it on would add a second live call per claim and change the
# byte-identical-with-provider-off guarantee. It is called explicitly, and
# what it produces is a suggestion under claim["assist"] like every other.
#
# Three things this prompt does that claim-prefill-v7 does not:
#   (a) It asks for the study DESIGN as described, and states outright that the
#       publication type does not determine the answer.
#   (b) It separates certainty from direction and magnitude, and says in as
#       many words that a null finding is a finding.
#   (c) It asks whether the source supports the claim AS WORDED, which is the
#       check no metadata field can stand in for.
#
# v2: the claim_supported_by_source wording let "the abstract is too short to
# tell" count as cannot_determine. The first measured second-rater pass put
# that field at kappa 0.039 -- chance -- with 21 systematic disagreements on
# frameworks and policy reports. The question is now stated as substantive,
# and brevity is ruled out explicitly. See docs/evidenz-bewertung-anker.md.
APPRAISAL_PROMPT_VERSION = "claim-appraisal-v3"

# The rated subset. The model is not asked for bibliographic fields: it cannot
# verify them, and a model that invents a DOI is worse than one that leaves it
# empty.
APPRAISAL_SUGGESTION_FIELDS = (
    "study_design",
    "comparator",
    "outcome_type",
    "effect_direction",
    "effect_magnitude",
    "follow_up",
    "risk_of_bias",
    "directness",
    "replication",
    "consistency",
    "heterogeneity",
    "precision",
    "claim_supported_by_source",
    "evidence_certainty",
    "age_range_explicit",
    "grade_or_stage",
    "sample_size",
)


def appraisal_output_schema() -> dict[str, Any]:
    """Strict JSON Schema for the appraisal suggestion.

    Generated from scripts/appraisal.py rather than written out, so the
    model can never be offered a value validate_appraisal() would reject
    -- the same guarantee PREFILL_OUTPUT_SCHEMA gets from
    EVIDENCE_STRENGTH_VALUES, applied to eighteen vocabularies instead of
    one.
    """
    full = appraisal.json_schema()["properties"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(APPRAISAL_SUGGESTION_FIELDS),
        "properties": {field: full[field] for field in APPRAISAL_SUGGESTION_FIELDS},
    }


APPRAISAL_PROMPT_TEMPLATE = '''System: You appraise the evidence behind one claim taken from a study \
abstract. Invent nothing. If the abstract does not state something, answer \
"unknown" (or null) -- never the value that is merely typical for that kind of \
study. Respond only as JSON following the given schema.

User:
Abstract:
"""{abstract}"""

The claim being appraised (do NOT assume it is correct -- it is what you are \
checking):
"""{statement}"""

Appraise it on these dimensions:

- study_design: the design the abstract DESCRIBES, from {study_designs}. The \
publication type does not decide this and must not be used as a shortcut: a \
paper published as a systematic review still gets the design its text \
describes. Note that {overlapping} appear in BOTH the source_type and the \
study_design vocabularies and mean different things there -- never copy the \
source_type across. As a DESIGN, "policy_report" means the document reports \
no method of its own; a policy report that describes a literature review, a \
survey and case studies has THAT as its design. If the abstract names no \
design, answer "unknown".
- comparator, outcome_type, follow_up, replication, sample_size: as reported, \
otherwise the unclear/unknown value or null. Do not infer a comparison group \
that is not mentioned.
- effect_direction: {effect_directions}. This is the direction of a MEASURED \
effect, not the tone of the finding. "null" means no difference was found -- a \
legitimate scientific result, not a weak one, and it must not lower your \
certainty rating. Use "not_applicable" when no effect was estimated at all: \
"positive attitudes toward the tool" describes attitudes and measures no \
effect. But when the source does report outcomes, give their direction even if \
the claim is worded descriptively.
- effect_magnitude / risk_of_bias / consistency / heterogeneity / precision: \
only when the abstract discusses them. An abstract that never mentions a \
risk-of-bias assessment gets risk_of_bias "unknown", NOT "low".
- directness: does the population, intervention, comparison and outcome \
actually match what the claim asserts? A self-reported outcome behind a claim \
about measured competence is at best partially_direct.
- claim_supported_by_source: {claim_support}. This asks ONLY whether the \
source asserts, IN SUBSTANCE, what the claim asserts -- independent of how \
good the source is and of how long the abstract is. A claim stated more \
causally than an uncontrolled design allows, or generalised past the sample \
studied, is partially_supported at best. BREVITY IS NOT A REASON for \
cannot_determine: a one-line abstract that covers the claim in substance is \
"supported". Reserve cannot_determine for an abstract that does not address \
the claim's subject at all, or contradicts itself. Whether the source can be \
located is source_verified; whether its population and outcome fit the claim \
is directness -- do not charge either of them here a second time.
- evidence_certainty: {certainty_values}. The question is: how certain can we \
be, from this evidence, that THIS claim holds? Not how large the effect is, \
not how positive it is, not how respected the venue is. Use "unverifiable" \
only when the source itself cannot be identified. Answer null if the abstract \
does not say enough.
- age_range_explicit: ages EXPLICITLY stated in the text, as "min-max" \
(e.g. "22-55"). A school stage is not an age: "11th-grade students" or \
"upper secondary" gives null here, because the same stage name covers \
different years in different countries. Put the stage in grade_or_stage \
instead, worded as the text words it.'''


def appraisal_prompt(abstract: str, statement: str) -> str:
    """Render the versioned appraisal prompt for *abstract*/*statement*."""
    return APPRAISAL_PROMPT_TEMPLATE.format(
        abstract=abstract.strip(),
        statement=statement.strip(),
        study_designs=", ".join(appraisal.STUDY_DESIGN_VALUES),
        effect_directions=", ".join(appraisal.EFFECT_DIRECTION_VALUES),
        claim_support=", ".join(appraisal.CLAIM_SUPPORT_VALUES),
        overlapping=", ".join(sorted(appraisal.OVERLAPPING_VOCABULARY)),
        certainty_values=", ".join(appraisal.CERTAINTY_VALUES),
    )


def suggest_appraisal(abstract: str, statement: str) -> dict[str, Any] | None:
    """Ask the configured provider for an appraisal suggestion.

    Returns None when no provider is configured or the response does not
    validate -- a rejected suggestion is dropped rather than repaired,
    the same rule the pre-fill path follows.
    """
    result = ai_provider.complete(
        appraisal_prompt(abstract, statement), schema=appraisal_output_schema()
    )
    if not isinstance(result, dict):
        return None
    suggestion = {field: result.get(field) for field in APPRAISAL_SUGGESTION_FIELDS}
    if appraisal.validate_appraisal(suggestion):
        return None
    return suggestion


def prefill_prompt(abstract: str, statement: str, topics: list[str]) -> str:
    """Render the versioned claim pre-fill prompt for *abstract*/*statement*/*topics*."""
    return PREFILL_PROMPT_TEMPLATE.format(
        abstract=abstract.strip(),
        statement=statement.strip(),
        topics=", ".join(topics) if topics else "—",
        age_scale=AGE_SCALE,
        strength_values=EVIDENCE_STRENGTH_LIST,
        strength_schema="|".join(f'"{value}"' for value in EVIDENCE_STRENGTH_VALUES),
    )


def suggest_claim_fields(
    abstract: str, statement: str, topics: list[str]
) -> dict[str, Any] | None:
    """Suggest the manual review fields for a claim, or None when unavailable.

    Calls ``ai_provider.complete`` with the versioned prompt (Anhang A) and a
    strict JSON Schema (``output_config.format``); determinism comes from
    ``effort='low'`` with NO temperature. Returns a mapping of the four review
    fields (``age_range``, ``outcome``, ``context``, ``evidence_strength``), each
    a string or None. Returns None entirely when the provider is ``none``, on a
    refusal, on any failure, or when the model proposes nothing — so a missing
    suggestion is always indistinguishable from AI being off.
    """
    # Off by default: skip even building the prompt so the path is fully inert.
    if ai_provider.ai_provider() == "none":
        return None
    prompt = prefill_prompt(abstract, statement, topics)
    result = ai_provider.complete(prompt, schema=PREFILL_OUTPUT_SCHEMA)
    if not isinstance(result, dict):
        return None
    fields = {field: result.get(field) for field in PREFILL_SUGGESTION_FIELDS}
    # Nothing useful proposed (all null) is treated as "no suggestion" so we do
    # not attach an empty assist block.
    if all(value is None for value in fields.values()):
        return None
    return fields


# --- Optional skill-link suggestion (P1, separate call) --------------------
#
# A claim only becomes `reviewed` once it links at least one skill, so that
# lookup is the last purely manual step left in the review loop. This suggests
# the link the same non-binding way the field pre-fill suggests review fields.
#
# Deliberately a SECOND call with its own prompt version rather than a fifth
# field on the pre-fill prompt:
#   - it needs the skill catalogue as context, which would bloat every pre-fill
#     prompt and could shift the four calibrated fields;
#   - a shared prompt means one shared version, so the two could never be
#     re-recorded or calibrated independently;
#   - keeping the pre-fill prompt untouched keeps its 50 fixtures (and its
#     measured numbers) valid.
SKILL_LINK_PROMPT_VERSION = "skill-link-v1"

# Only ACTIVE skills are offered. A candidate skill is itself unreviewed, and
# pointing new evidence at unreviewed evidence is how a catalogue drifts.
SKILL_LINK_STATUS = "active"

# Definitions are truncated in the prompt: enough to disambiguate two skills,
# short enough that 16 of them stay a small prompt.
SKILL_DEFINITION_BUDGET = 240

SKILL_LINK_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["supports_skill_ids", "contradicts_skill_ids"],
    "properties": {
        "supports_skill_ids": {"type": "array", "items": {"type": "string"}},
        "contradicts_skill_ids": {"type": "array", "items": {"type": "string"}},
    },
}

SKILL_LINK_FIELDS = ("supports_skill_ids", "contradicts_skill_ids")

SKILL_LINK_PROMPT_TEMPLATE = '''System: You link an evidence claim from educational research to the skills \
it concerns, choosing ONLY from a fixed catalogue. You invent nothing: if no \
catalogue entry fits, return empty lists. Precision matters far more than \
coverage — a reviewer can add a missing link in seconds, but a wrong link \
quietly attaches evidence to the wrong skill. Respond only as JSON following \
the given schema.

User:
Claim statement:
"""{statement}"""

Source abstract for context:
"""{abstract}"""

Detected topics: {topics}

Skill catalogue (the ONLY permitted ids):
{catalogue}

Return:
- supports_skill_ids: ids whose skill this claim provides EVIDENCE FOR. Only \
include an id when the claim is really about that skill, not merely adjacent to \
it. Usually zero or one; more than two is almost always wrong.
- contradicts_skill_ids: ids whose skill this claim provides evidence AGAINST \
(a null result, no measurable effect, or a harm). Empty for the normal case of \
a supporting finding.

Response schema:
{{"supports_skill_ids": [string], "contradicts_skill_ids": [string]}}'''


_skill_catalogue_cache: list[dict[str, str]] | None = None


def skill_catalogue(*, refresh: bool = False) -> list[dict[str, str]]:
    """Active skills a claim may be linked to: id, name, short definition.

    Memoized: one extraction run builds many claims against the same catalogue,
    so re-reading data/skills/ per claim would be pure waste. Only ever called
    behind the provider check, so an LLM-free run touches no skill file at all.
    """
    global _skill_catalogue_cache
    if _skill_catalogue_cache is not None and not refresh:
        return _skill_catalogue_cache
    catalogue: list[dict[str, str]] = []
    for skill in load_records("skills"):
        if skill.get("status") != SKILL_LINK_STATUS:
            continue
        definition = str(skill.get("definition") or "").strip()
        if len(definition) > SKILL_DEFINITION_BUDGET:
            definition = definition[:SKILL_DEFINITION_BUDGET].rstrip() + "…"
        catalogue.append(
            {
                "id": str(skill.get("id") or ""),
                "name": str(skill.get("name") or ""),
                "definition": definition,
                "audience": str(skill.get("audience") or "learner"),
            }
        )
    _skill_catalogue_cache = sorted(catalogue, key=lambda entry: entry["id"])
    return _skill_catalogue_cache


def render_catalogue(catalogue: list[dict[str, str]]) -> str:
    """One line per skill, stable order, so the prompt hashes reproducibly."""
    return "\n".join(
        f"- {entry['id']} ({entry['audience']}) — {entry['name']}: {entry['definition']}"
        for entry in catalogue
    )


def skill_link_prompt(
    abstract: str, statement: str, topics: list[str], catalogue: list[dict[str, str]]
) -> str:
    """Render the versioned skill-link prompt."""
    return SKILL_LINK_PROMPT_TEMPLATE.format(
        abstract=abstract.strip(),
        statement=statement.strip(),
        topics=", ".join(topics) if topics else "—",
        catalogue=render_catalogue(catalogue),
    )


def suggest_skill_links(
    abstract: str,
    statement: str,
    topics: list[str],
    catalogue: list[dict[str, str]] | None = None,
) -> dict[str, list[str]] | None:
    """Suggest supporting/contradicting skill links, or None when unavailable.

    Every returned id is checked against the catalogue, so a hallucinated or
    stale id is dropped rather than written into an assist block a reviewer
    might trust. Returns None when the provider is off, on any failure, or when
    nothing survives the check — indistinguishable from AI being off.
    """
    if ai_provider.ai_provider() == "none":
        return None
    if catalogue is None:
        catalogue = skill_catalogue()
    if not catalogue:
        return None

    prompt = skill_link_prompt(abstract, statement, topics, catalogue)
    result = ai_provider.complete(prompt, schema=SKILL_LINK_OUTPUT_SCHEMA)
    if not isinstance(result, dict):
        return None

    known = {entry["id"] for entry in catalogue}
    links: dict[str, list[str]] = {}
    for field in SKILL_LINK_FIELDS:
        proposed = result.get(field)
        if not isinstance(proposed, list):
            proposed = []
        kept, dropped = [], []
        for value in proposed:
            identifier = str(value).strip()
            # Dedupe while preserving order, and never keep an unknown id.
            if identifier in known and identifier not in kept:
                kept.append(identifier)
            elif identifier not in known:
                dropped.append(identifier)
        if dropped:
            print(
                f"Warning: skill-link suggestion named {len(dropped)} unknown skill id(s) "
                f"({', '.join(sorted(set(dropped)))}); dropped.",
                file=sys.stderr,
            )
        links[field] = kept

    if not any(links.values()):
        return None
    return links


def _has_cue(normalized: str, cues: tuple[str, ...]) -> bool:
    padded = f" {normalized} "
    return any(f" {cue} " in padded for cue in cues)


def sentence_tier(sentence: str) -> int:
    """Rank a sentence: +1 finding, -1 methodology/structure, 0 otherwise."""
    normalized = normalize_title(sentence)
    finding = _has_cue(normalized, FINDING_CUES)
    method = _has_cue(normalized, METHOD_CUES)
    if finding and not method:
        return 1
    if method and not finding:
        return -1
    return 0


def top_claim_sentences(
    abstract: str, limit: int = MAX_CLAIMS_PER_SOURCE
) -> list[tuple[int, str, list[str]]]:
    """Rank claim sentences, best first, as up to *limit* (index, sentence, topics).

    Among sentences that match a topic and meet MIN_SENTENCE_LENGTH, a finding
    sentence is preferred over a neutral one (see FINDING_CUES); within a tier
    the highest relevance score wins and the earliest sentence breaks ties.
    Pure methodology/structure sentences (tier -1, e.g. "we used interviews",
    "this paper introduces a six-step design") are never emitted as claims:
    they are not evidence statements, so such a source yields no claim and a
    reviewer can author one by hand if the paper merits it. Sentences without
    a topic match are likewise never picked. An abstract reporting several
    independent findings yields several candidate claims (skill scoring rewards
    breadth), each with its own verbatim text anchor.
    """
    ranked: list[tuple[tuple[int, float, int], int, str, list[str]]] = []
    for index, raw in enumerate(split_sentences(abstract)):
        sentence = " ".join(raw.split())
        if len(sentence) < MIN_SENTENCE_LENGTH:
            continue
        score, topics = score_relevance({"title": sentence})
        if not topics:
            continue
        tier = sentence_tier(sentence)
        if tier < 0:
            continue
        ranked.append(((tier, score, -index), index, sentence, topics))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return [(index, sentence, topics) for _, index, sentence, topics in ranked[:limit]]


def best_claim_sentence(abstract: str) -> tuple[int, str, list[str]] | None:
    """Pick the single best claim sentence (the head of top_claim_sentences)."""
    picked = top_claim_sentences(abstract, limit=1)
    return picked[0] if picked else None


def claims_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    """All candidate claims for *source*, best finding first (may be empty)."""
    abstract = source.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return []
    return [
        claim
        for picked in top_claim_sentences(abstract)
        if (claim := _build_claim(source, abstract, picked)) is not None
    ]


def claim_from_source(source: dict[str, Any]) -> dict[str, Any] | None:
    """The single best candidate claim for *source*, or None."""
    claims = claims_from_source(source)
    return claims[0] if claims else None


def _build_claim(
    source: dict[str, Any], abstract: str, picked: tuple[int, str, list[str]]
) -> dict[str, Any] | None:
    index, sentence, topics = picked
    source_id = str(source.get("id", "unknown-source"))
    claim: dict[str, Any] = {
        "id": slugify(f"{source_id.removeprefix('src-')} abstract s{index + 1}", "claim"),
        "statement": sentence,
        "source_ids": [source_id],
        "text_anchor": f'abstract, sentence {index + 1}: "{sentence}"',
        "context": f"Auto-extracted candidate; matched topics: {', '.join(topics)}. {CONTEXT_PLACEHOLDER_SUFFIX}",
        "age_range": AGE_RANGE_PLACEHOLDER,
        "outcome": OUTCOME_PLACEHOLDER,
        "evidence_type": EVIDENCE_TYPE_BY_SOURCE_TYPE.get(
            str(source.get("source_type")), DEFAULT_EVIDENCE_TYPE
        ),
        "evidence_strength": "low",
        "supports_skill_ids": [],
        "contradicts_skill_ids": [],
        "extraction_method": "finding_sentence_extraction_no_llm",
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }
    # Opt-in LLM pre-fill: attach the suggestion ONLY under "assist". The real
    # fields above keep their placeholders, and statement/text_anchor stay
    # verbatim. With AI_PROVIDER=none this returns None and nothing is added,
    # so the output is byte-identical to the LLM-free pipeline.
    suggestion = suggest_claim_fields(abstract, sentence, topics)
    if suggestion is not None:
        claim["assist"] = {
            "suggestions": [suggestion],
            "provenance": ai_provider.ai_provenance(PREFILL_PROMPT_VERSION),
        }
    # The skill link is a second, independently versioned call, so it carries its
    # own provenance and can be absent even when the field suggestion is present.
    # Like every assist output it is non-binding: supports_skill_ids above stays
    # empty and a reviewer still has to pass --supports to promote the claim.
    links = suggest_skill_links(abstract, sentence, topics)
    if links is not None:
        claim.setdefault("assist", {})["skill_links"] = {
            **links,
            "provenance": ai_provider.ai_provenance(SKILL_LINK_PROMPT_VERSION),
        }
    return claim


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract candidate claims with verbatim text anchors from candidate source abstracts."
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Source JSON files (default: data/sources/candidates-*.json).",
    )
    parser.add_argument("--output", default="data/claims/candidates-extracted.json")
    args = parser.parse_args()

    if args.sources:
        paths = [ROOT / source for source in args.sources]
    else:
        paths = sorted((ROOT / "data" / "sources").glob("candidates-*.json"))
    sources: list[dict[str, Any]] = []
    for path in paths:
        # An importer that fetched nothing writes no file, so a missing path
        # is normal here and must not abort extraction of the other sources.
        if not path.exists():
            print(f"Note: {path} does not exist; skipping.", file=sys.stderr)
            continue
        payload = load_json(path)
        if not isinstance(payload, list):
            raise SystemExit(f"{path} must contain a JSON array")
        sources.extend(record for record in payload if isinstance(record, dict))

    candidates = [source for source in sources if source.get("status") == "candidate"]
    extracted: list[dict[str, Any]] = []
    sources_without_claim = 0
    for source in candidates:
        claims = claims_from_source(source)
        if not claims:
            sources_without_claim += 1
        extracted.extend(claims)
    new_claims = filter_new_claims(extracted)
    appended = append_unique_records(
        ROOT / args.output, new_claims, lambda claim: [claim_statement_key(claim)]
    )
    print(
        f"Appended {len(appended)} new candidate claims to {args.output} "
        f"({sources_without_claim} candidate sources without an extractable claim)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
