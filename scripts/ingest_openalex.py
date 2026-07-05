from __future__ import annotations

import argparse
import urllib.parse
import urllib.request
from typing import Any

from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    TODAY,
    append_candidate_sources,
    dedupe_queries,
    fetch_or_warn,
    filter_new_sources,
    filter_relevant_sources,
    load_research_queries,
    slugify,
)


BASE_URL = "https://api.openalex.org/works"


def inverted_index_to_text(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, offsets in index.items():
        for offset in offsets:
            positions.append((offset, word))
    return " ".join(word for _, word in sorted(positions))


def fetch(query: str, limit: int, mailto: str | None = None) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "per-page": str(limit),
        "filter": "type:article|book|report",
        "sort": "publication_year:desc",
    }
    if mailto:
        params["mailto"] = mailto
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = __import__("json").load(response)
    return list(payload.get("results", []))


def convert(work: dict[str, Any]) -> dict[str, Any]:
    title = work.get("display_name") or "Untitled OpenAlex work"
    # The API serializes missing values as explicit nulls, so every nested
    # access guards against None — one null authorship must not abort the run.
    authors = [
        name
        for authorship in (work.get("authorships") or [])
        if (name := ((authorship or {}).get("author") or {}).get("display_name"))
    ]
    host = (work.get("primary_location") or {}).get("source") or {}
    doi = work.get("doi")
    if isinstance(doi, str) and doi.startswith("https://doi.org/"):
        doi = doi.removeprefix("https://doi.org/")
    work_type = work.get("type") or "article"
    source_type = "book" if work_type == "book" else "peer_reviewed_article"
    if work_type == "report":
        source_type = "policy_report"
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": authors,
        "year": work.get("publication_year") or None,
        "doi": doi,
        "url": work.get("id") or work.get("doi") or "",
        "openalex_id": work.get("id"),
        "semantic_scholar_id": None,
        "eric_id": None,
        "publisher": host.get("display_name") or "OpenAlex",
        "source_type": source_type,
        "license": ((work.get("primary_location") or {}).get("license")),
        "abstract": inverted_index_to_text(work.get("abstract_inverted_index")),
        "topics": ["education"],
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate source metadata from OpenAlex.")
    parser.add_argument(
        "--query",
        action="append",
        help="A search query (repeatable). Omit to use config/research_queries.json "
        "or the RESEARCH_QUERIES override.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--output", default="data/sources/candidates-openalex.json")
    parser.add_argument("--mailto", default=None)
    parser.add_argument("--min-relevance", type=float, default=RELEVANCE_THRESHOLD)
    args = parser.parse_args()

    queries = dedupe_queries(args.query) if args.query else load_research_queries()
    works: list[dict[str, Any]] = []
    for query in queries:
        works.extend(fetch_or_warn("OpenAlex", lambda q=query: fetch(q, args.limit, args.mailto)))
    candidates = [convert(work) for work in works]
    relevant = filter_relevant_sources(candidates, args.min_relevance)
    new_records = filter_new_sources(relevant)
    appended = append_candidate_sources(ROOT / args.output, new_records)
    print(
        f"Appended {len(appended)} new OpenAlex candidates to {args.output} "
        f"from {len(queries)} quer{'y' if len(queries) == 1 else 'ies'} "
        f"({len(candidates) - len(relevant)} filtered as irrelevant)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
