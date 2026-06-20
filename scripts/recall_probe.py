"""Surface the rejected region of the relevance filter for human labeling.

The relevance filter drops below-threshold, off-scope and adult-audience sources
silently, and the auto-harvest only ever labels candidates that PASSED the
filter. That selection bias means the trained classifier (and the eval set)
never see the rejected region, so they cannot learn or measure where the filter
wrongly drops a relevant source. This routine closes that gap.

Probe mode (default) fetches live candidates with the gate open, keeps the ones
the filter would REJECT, annotates why, samples a handful, and writes a labeling
worksheet. A human fills in each `relevant` field (true/false). Ingest mode reads
the filled worksheet and folds the decided labels into the curated eval set.

    python scripts/recall_probe.py                         # write a worksheet
    python scripts/recall_probe.py --ingest eval/recall_probe.json   # fold labels back

Run it on a regular cadence (see OPERATIONS.md) so rejected-region labels keep
flowing into eval/relevance_labeled.json alongside the passing-region harvest.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from typing import Any, Callable

import ingest_arxiv
import ingest_crossref
import ingest_eric
import ingest_openalex
import ingest_semantic_scholar
from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    fetch_or_warn,
    is_adult_audience,
    is_off_scope,
    load_json,
    normalize_title,
    score_relevance,
    write_json,
)
from eval_relevance import EVAL_PATH, load_harvested_examples


DEFAULT_QUERY = "AI literacy education children future skills"
WORKSHEET_PATH = ROOT / "eval" / "recall_probe.json"


def _sources(query: str, limit: int) -> dict[str, Callable[[], list[dict[str, Any]]]]:
    """Map source name -> a no-arg fetch+convert callable (raw, unfiltered)."""
    mailto = os.getenv("OPENALEX_MAILTO")
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {
        "OpenAlex": lambda: [ingest_openalex.convert(w) for w in ingest_openalex.fetch(query, limit, mailto)],
        "Crossref": lambda: [ingest_crossref.convert(i) for i in ingest_crossref.fetch(query, limit)],
        "Semantic Scholar": lambda: [
            ingest_semantic_scholar.convert(p) for p in ingest_semantic_scholar.fetch(query, limit, api_key)
        ],
        "arXiv": lambda: [ingest_arxiv.convert(e) for e in ingest_arxiv.fetch(query, limit)],
        "ERIC": lambda: [ingest_eric.convert(d) for d in ingest_eric.fetch(query, limit)],
    }


def rejection_reason(source: dict[str, Any]) -> str | None:
    """Why the heuristic would reject *source*, or None if it would be kept.

    Mirrors heuristic_keep's order so the worksheet explains each drop.
    """
    score, topics = score_relevance(source)
    if not topics:
        return "no_topic"
    if score < RELEVANCE_THRESHOLD:
        return "below_threshold"
    if is_off_scope(source):
        return "off_scope"
    if is_adult_audience(source):
        return "adult_audience"
    return None


def _known_titles() -> set[str]:
    """Normalized titles already labeled (curated + harvested), to skip."""
    curated = load_json(EVAL_PATH).get("examples", [])
    known = {normalize_title(str(ex.get("title", ""))) for ex in curated}
    known |= {normalize_title(str(ex.get("title", ""))) for ex in load_harvested_examples()}
    return known


def build_worksheet(query: str, limit: int, sample: int, seed: int) -> list[dict[str, Any]]:
    known = _known_titles()
    seen: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for name, fetch in _sources(query, limit).items():
        for source in fetch_or_warn(name, fetch):
            key = normalize_title(str(source.get("title") or ""))
            if not key or key in known or key in seen:
                continue
            reason = rejection_reason(source)
            if reason is None:
                continue  # the filter would keep it; not part of the rejected region
            seen.add(key)
            rejected.append(
                {
                    "title": source.get("title") or "",
                    "abstract": source.get("abstract") or "",
                    "source": name,
                    "reason": reason,
                    "relevant": None,  # the reviewer fills this in: true / false
                }
            )
    random.Random(seed).shuffle(rejected)
    return rejected[:sample]


def ingest_worksheet(path: str) -> int:
    """Fold decided worksheet rows (relevant true/false) into the curated set."""
    worksheet = load_json(ROOT / path)
    rows = worksheet.get("examples", worksheet) if isinstance(worksheet, dict) else worksheet
    doc = load_json(EVAL_PATH)
    existing = {normalize_title(str(ex.get("title", ""))) for ex in doc["examples"]}
    added = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("relevant"), bool):
            continue  # undecided rows are skipped
        key = normalize_title(str(row.get("title", "")))
        if not key or key in existing:
            continue
        doc["examples"].append(
            {
                "title": row["title"],
                "abstract": row.get("abstract", ""),
                "relevant": row["relevant"],
                "origin": "recall_probe",
                "note": f"Rejected-region sample ({row.get('reason', 'unknown')}); labeled during recall probe.",
            }
        )
        existing.add(key)
        added += 1
    if added:
        write_json(EVAL_PATH, doc)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample the relevance filter's rejected region for labeling.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--limit", type=int, default=25, help="Fetch size per source.")
    parser.add_argument("--sample", type=int, default=15, help="Rejected items to surface.")
    parser.add_argument("--seed", type=int, default=0, help="Sampling seed for reproducibility.")
    parser.add_argument("--output", default=str(WORKSHEET_PATH.relative_to(ROOT)))
    parser.add_argument(
        "--ingest",
        metavar="WORKSHEET",
        help="Fold a filled worksheet's decided labels into eval/relevance_labeled.json.",
    )
    args = parser.parse_args()

    if args.ingest:
        added = ingest_worksheet(args.ingest)
        print(f"Folded {added} labeled example(s) into {EVAL_PATH.relative_to(ROOT)}.")
        return 0

    rows = build_worksheet(args.query, args.limit, args.sample, args.seed)
    worksheet = {
        "_README": (
            "Rejected-region labeling worksheet. For each row set 'relevant' to true "
            "(the filter wrongly dropped an in-scope source = recall leak) or false "
            "(correctly dropped). Then run: python scripts/recall_probe.py --ingest "
            f"{args.output}"
        ),
        "examples": rows,
    }
    write_json(ROOT / args.output, worksheet)
    by_reason: dict[str, int] = {}
    for row in rows:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
    print(f"Wrote {len(rows)} rejected-region samples to {args.output} for labeling.")
    if by_reason:
        print("By reason: " + ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
