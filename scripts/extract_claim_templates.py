from __future__ import annotations

import argparse
from pathlib import Path

from common import ROOT, TODAY, load_json, slugify, write_json


def template_for_source(source: dict[str, object]) -> dict[str, object]:
    source_id = str(source.get("id", "unknown-source"))
    title = str(source.get("title", "Untitled source"))
    return {
        "id": slugify(f"{source_id}-review-needed", "claim"),
        "statement": f"Candidate claim requires human review before use: {title}",
        "source_ids": [source_id],
        "text_anchor": "TODO: add section, page, paragraph, or abstract sentence anchor",
        "context": "TODO: describe education context",
        "age_range": "TODO",
        "outcome": "TODO: describe learner outcome",
        "evidence_type": "conceptual_review",
        "evidence_strength": "low",
        "supports_skill_ids": [],
        "contradicts_skill_ids": [],
        "extraction_method": "template_only_no_llm",
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create conservative claim-review templates from candidate sources.")
    parser.add_argument("--sources", required=True, help="Path to a JSON array of source records.")
    parser.add_argument("--output", default="data/claims/candidates-templates.json")
    args = parser.parse_args()

    sources = load_json(ROOT / args.sources)
    if not isinstance(sources, list):
        raise SystemExit("Source file must contain a JSON array.")
    claims = [template_for_source(source) for source in sources]
    write_json(ROOT / args.output, claims)
    print(f"Wrote {len(claims)} candidate claim templates to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

