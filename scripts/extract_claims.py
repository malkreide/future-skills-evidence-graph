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
from common import (
    AGE_SCALE,
    ROOT,
    TODAY,
    append_unique_records,
    claim_statement_key,
    filter_new_claims,
    load_json,
    normalize_title,
    score_relevance,
    slugify,
)


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE_LENGTH = 40

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
PREFILL_PROMPT_VERSION = "claim-prefill-v2"

# Strict JSON Schema for the suggestion (enforced via output_config.format). It
# mirrors Anhang A: every field is optional content (null when the abstract does
# not support it); evidence_strength uses the {low, moderate, high} vocabulary.
PREFILL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["age_range", "outcome", "context", "evidence_strength"],
    "properties": {
        "age_range": {"type": ["string", "null"]},
        "outcome": {"type": ["string", "null"]},
        "context": {"type": ["string", "null"]},
        "evidence_strength": {"enum": ["low", "moderate", "high", None]},
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
age. Clip ranges beyond {age_scale} to {age_scale}; pure adult samples => null.
- outcome: one sentence, in English, stating which learning outcome/effect is \
reported (neutral, without exaggeration), or null.
- context: one sentence, in English, on the setting (country, school level, \
type of intervention), or null.
- evidence_strength: one of {{low, moderate, high}}, estimated conservatively \
from study type and sample; when in doubt, low.

Response schema:
{{"age_range": string|null, "outcome": string|null, "context": string|null, \
 "evidence_strength": "low"|"moderate"|"high"}}'''


def prefill_prompt(abstract: str, statement: str, topics: list[str]) -> str:
    """Render the versioned claim pre-fill prompt for *abstract*/*statement*/*topics*."""
    return PREFILL_PROMPT_TEMPLATE.format(
        abstract=abstract.strip(),
        statement=statement.strip(),
        topics=", ".join(topics) if topics else "—",
        age_scale=AGE_SCALE,
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


def best_claim_sentence(abstract: str) -> tuple[int, str, list[str]] | None:
    """Pick the best claim sentence as (index, sentence, topics).

    Among sentences that match a topic and meet MIN_SENTENCE_LENGTH, a finding
    sentence is preferred over a neutral one (see FINDING_CUES); within a tier
    the highest relevance score wins and the earliest sentence breaks ties.
    Pure methodology/structure sentences (tier -1, e.g. "we used interviews",
    "this paper introduces a six-step design") are never emitted as claims:
    they are not evidence statements, so such a source yields no claim and a
    reviewer can author one by hand if the paper merits it. Sentences without
    a topic match are likewise never picked.
    """
    best: tuple[tuple[int, float, int], int, str, list[str]] | None = None
    for index, raw in enumerate(SENTENCE_SPLIT.split(abstract)):
        sentence = " ".join(raw.split())
        if len(sentence) < MIN_SENTENCE_LENGTH:
            continue
        score, topics = score_relevance({"title": sentence})
        if not topics:
            continue
        tier = sentence_tier(sentence)
        if tier < 0:
            continue
        key = (tier, score, -index)
        if best is None or key > best[0]:
            best = (key, index, sentence, topics)
    if best is None:
        return None
    return best[1], best[2], best[3]


def claim_from_source(source: dict[str, Any]) -> dict[str, Any] | None:
    abstract = source.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    picked = best_claim_sentence(abstract)
    if picked is None:
        return None
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
    extracted = [claim for claim in map(claim_from_source, candidates) if claim]
    new_claims = filter_new_claims(extracted)
    appended = append_unique_records(
        ROOT / args.output, new_claims, lambda claim: [claim_statement_key(claim)]
    )
    print(
        f"Appended {len(appended)} new candidate claims to {args.output} "
        f"({len(candidates) - len(extracted)} candidate sources without an extractable claim)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
