"""Re-apply the current relevance heuristic to the standing candidate backlog.

The relevance filter only runs at INGEST time, but its vocabulary grows
reactively (every observed false positive adds an off-scope term, every recall
leak adds a topic keyword — see OPERATIONS.md). Candidates that slipped in
under an older vocabulary therefore linger in ``data/`` even though the
current heuristic would drop them on arrival: the reviewed MENA-immigrant
case is the documented example (ingested, later hand-rejected, and only then
covered by new off-scope terms).

This routine closes that loop. It re-runs the CURRENT heuristic over every
open candidate source and writes a gitignored worksheet of the ones the
filter would no longer accept, each with its drop reason and the exact
``reject-source`` command. Like the triage worksheet it writes nothing into
``data/`` and rejects nothing — the decision stays with the reviewer, who may
well keep a flagged source (a drop reason is a hint, not a verdict):

    python scripts/refilter_candidates.py     # write eval/candidate_refilter.json

Run it after every vocabulary change (OPERATIONS.md lists it next to the
false-positive/false-negative triggers). The output is deterministic, so the
worksheet only changes when the backlog or the vocabulary does.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    is_adult_audience,
    is_educator_audience,
    is_off_scope,
    is_teacher_tooluse,
    load_records,
    score_relevance,
    write_json,
)

WORKSHEET_PATH = ROOT / "eval" / "candidate_refilter.json"


def drop_reason(source: dict[str, Any]) -> str | None:
    """Why the CURRENT heuristic would drop *source*, or None if it keeps it.

    Mirrors heuristic_keep's rule order (including the educator-lane rescue)
    so every flagged row explains itself the way the live filter would decide.
    """
    score, topics = score_relevance(source)
    if not topics:
        return "no_topic"
    if score < RELEVANCE_THRESHOLD:
        return "below_threshold"
    if is_off_scope(source):
        return "off_scope"
    if is_teacher_tooluse(source):
        return "teacher_tooluse"
    if is_adult_audience(source) and not is_educator_audience(source):
        return "adult_audience"
    return None


def build_worksheet() -> dict[str, Any]:
    flagged: list[dict[str, Any]] = []
    open_candidates = 0
    for source in load_records("sources"):
        if source.get("status") != "candidate":
            continue
        open_candidates += 1
        reason = drop_reason(source)
        if reason is None:
            continue
        flagged.append(
            {
                "source_id": source.get("id", ""),
                "title": source.get("title", ""),
                "year": source.get("year"),
                "reason": reason,
                "command": f"python scripts/promote_candidate.py reject-source {source.get('id', '')}",
            }
        )
    flagged.sort(key=lambda row: (row["reason"], row["source_id"]))
    return {
        "_README": (
            "Open candidate sources the CURRENT relevance heuristic would drop, "
            "re-checked against today's vocabulary (see drop 'reason'). This file "
            "is a worksheet only — nothing was rejected. Review each row: run its "
            "command to reject (harvests a negative label via reject-source), or "
            "keep the candidate if the flag is wrong (and consider adding it to "
            "eval/relevance_labeled.json as a positive). See OPERATIONS.md."
        ),
        "open_candidate_sources": open_candidates,
        "flagged": flagged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-check open candidate sources against the current relevance heuristic."
    )
    parser.add_argument("--output", default=str(WORKSHEET_PATH.relative_to(ROOT)))
    args = parser.parse_args()

    worksheet = build_worksheet()
    write_json(ROOT / args.output, worksheet)

    flagged = worksheet["flagged"]
    by_reason: dict[str, int] = {}
    for row in flagged:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
    print(
        f"Checked {worksheet['open_candidate_sources']} open candidate source(s); "
        f"{len(flagged)} would be dropped by the current heuristic -> {args.output}."
    )
    if by_reason:
        print("Drop reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
