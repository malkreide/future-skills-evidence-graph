"""Turn the standing candidate backlog into a human review worksheet.

The importers and clustering only ever produce ``candidate`` records; promoting
or rejecting one is always a human decision made through
``scripts/promote_candidate.py`` (see OPERATIONS.md). Between cycles those
candidates accumulate in ``data/claims/candidates-*.json`` and
``data/sources/candidates-*.json``. This routine surfaces the open backlog as a
single, ordered worksheet so a reviewer can work through it without hand-joining
claims to their sources.

It writes nothing into ``data/`` and promotes nothing — it only reads the
committed candidate records and emits a gitignored worksheet plus the exact
``promote_candidate.py`` commands a reviewer would run for each item:

    python scripts/triage_candidates.py            # write eval/candidate_triage.json

For each open candidate claim the worksheet lists its verbatim statement, matched
topics, the source(s) it rests on (and whether each source is still a candidate),
any LLM pre-fill ``assist`` suggestions (P1, when present), and a ``decision``
field the reviewer fills in. The output is deterministic (stable ordering) so the
worksheet only changes when the backlog does.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from common import ROOT, load_records, write_json

WORKSHEET_PATH = ROOT / "eval" / "candidate_triage.json"


def _index_sources() -> dict[str, dict[str, Any]]:
    """Map source id -> source record, for joining claims to their sources."""
    return {src["id"]: src for src in load_records("sources") if "id" in src}


def _claim_row(claim: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_ids = list(claim.get("source_ids", []))
    source_rows = []
    for sid in source_ids:
        src = sources.get(sid)
        source_rows.append(
            {
                "source_id": sid,
                "title": (src or {}).get("title", "") if src else "",
                "status": (src or {}).get("status", "missing"),
                # Which relevance lane the filter tagged the source (absence ->
                # learner), so a reviewer can route educator-competence evidence
                # to an educator skill instead of re-opening it by hand.
                "audience": (src or {}).get("audience", "learner") if src else "learner",
            }
        )
    assist = claim.get("assist", {}).get("suggestions") if isinstance(claim.get("assist"), dict) else None
    return {
        "claim_id": claim["id"],
        "topics": sorted({t for t in claim.get("topics", [])} | _claim_topics(claim)),
        "statement": claim.get("statement", ""),
        "sources": source_rows,
        "assist_suggestions": assist,
        "review_commands": _review_commands(claim, source_rows),
        "decision": None,  # reviewer fills: "promote" | "reject" | "skip"
    }


def _claim_topics(claim: dict[str, Any]) -> set[str]:
    """Best-effort topic hints from the auto-extraction context line."""
    context = claim.get("context", "") or ""
    marker = "matched topics:"
    if marker in context:
        tail = context.split(marker, 1)[1]
        tail = tail.split(".", 1)[0]
        return {t.strip() for t in tail.split(",") if t.strip()}
    return set()


def _review_commands(claim: dict[str, Any], source_rows: list[dict[str, Any]]) -> list[str]:
    """The exact promote_candidate.py commands a reviewer would choose between."""
    claim_id = claim["id"]
    commands = [
        "# in-scope source -> reviewed + POSITIVE relevance label (run per source first):",
        *[f"python scripts/promote_candidate.py promote-source {row['source_id']}" for row in source_rows],
        "# good claim -> reviewed (fill the real review fields, link a skill):",
        (
            f"python scripts/promote_candidate.py claim {claim_id} "
            '--context "..." --age-range "<min>-<max>" --outcome "..." '
            "--evidence-type empirical_study --evidence-strength low --supports <skill-id>"
        ),
        "# OR unusable claim -> rejected:",
        f"python scripts/promote_candidate.py reject {claim_id}",
        "# OR off-scope source -> rejected + NEGATIVE relevance label:",
        *[f"python scripts/promote_candidate.py reject-source {row['source_id']}" for row in source_rows],
    ]
    return commands


def build_worksheet() -> dict[str, Any]:
    sources = _index_sources()
    open_claims = sorted(
        (c for c in load_records("claims") if c.get("status") == "candidate"),
        key=lambda c: c["id"],
    )
    rows = [_claim_row(claim, sources) for claim in open_claims]

    referenced = {row["source_id"] for claim in rows for row in claim["sources"]}
    orphan_sources = sorted(
        (
            {"source_id": src["id"], "title": src.get("title", "")}
            for src in sources.values()
            if src.get("status") == "candidate" and src["id"] not in referenced
        ),
        key=lambda s: s["source_id"],
    )

    return {
        "_README": (
            "Candidate backlog review worksheet (gitignored, regenerated each run). "
            "Work top to bottom: for each claim run one of its review_commands, then "
            "set 'decision' to promote/reject/skip for your own tracking. This file "
            "is a worksheet only — promotion happens through promote_candidate.py, "
            "which re-validates the repository. See OPERATIONS.md."
        ),
        "open_candidate_claims": rows,
        "orphan_candidate_sources": orphan_sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a review worksheet for the open candidate backlog.")
    parser.add_argument("--output", default=str(WORKSHEET_PATH.relative_to(ROOT)))
    args = parser.parse_args()

    worksheet = build_worksheet()
    write_json(ROOT / args.output, worksheet)

    claims = worksheet["open_candidate_claims"]
    orphans = worksheet["orphan_candidate_sources"]
    by_topic: dict[str, int] = {}
    for claim in claims:
        for topic in claim["topics"] or ["(untagged)"]:
            by_topic[topic] = by_topic.get(topic, 0) + 1
    print(f"Wrote {len(claims)} open candidate claim(s) and {len(orphans)} orphan candidate source(s) to {args.output}.")
    if by_topic:
        print("Claims by topic: " + ", ".join(f"{k}={v}" for k, v in sorted(by_topic.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
