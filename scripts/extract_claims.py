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
from typing import Any

from common import (
    ROOT,
    TODAY,
    append_unique_records,
    claim_statement_key,
    filter_new_claims,
    load_json,
    score_relevance,
    slugify,
)


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE_LENGTH = 40

EVIDENCE_TYPE_BY_SOURCE_TYPE = {
    "systematic_review": "systematic_review",
    "peer_reviewed_article": "empirical_study",
    "working_paper": "empirical_study",
    "dataset": "empirical_study",
    "framework": "framework_synthesis",
    "policy_report": "policy_synthesis",
}
DEFAULT_EVIDENCE_TYPE = "conceptual_review"


def best_claim_sentence(abstract: str) -> tuple[int, str, list[str]] | None:
    """Pick the most relevant abstract sentence as (index, sentence, topics).

    Sentences are scored with the same vocabulary the importers use for
    relevance filtering; ties keep the earliest sentence. Sentences without
    a topic match or shorter than MIN_SENTENCE_LENGTH are never picked.
    """
    best: tuple[float, int, str, list[str]] | None = None
    for index, raw in enumerate(SENTENCE_SPLIT.split(abstract)):
        sentence = " ".join(raw.split())
        if len(sentence) < MIN_SENTENCE_LENGTH:
            continue
        score, topics = score_relevance({"title": sentence})
        if not topics:
            continue
        if best is None or score > best[0]:
            best = (score, index, sentence, topics)
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
    return {
        "id": slugify(f"{source_id.removeprefix('src-')} abstract s{index + 1}", "claim"),
        "statement": sentence,
        "source_ids": [source_id],
        "text_anchor": f'abstract, sentence {index + 1}: "{sentence}"',
        "context": f"Auto-extracted candidate; matched topics: {', '.join(topics)}. Verify during review.",
        "age_range": "unspecified",
        "outcome": "Not extracted automatically; describe during review.",
        "evidence_type": EVIDENCE_TYPE_BY_SOURCE_TYPE.get(
            str(source.get("source_type")), DEFAULT_EVIDENCE_TYPE
        ),
        "evidence_strength": "low",
        "supports_skill_ids": [],
        "contradicts_skill_ids": [],
        "extraction_method": "keyword_sentence_extraction_no_llm",
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


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
