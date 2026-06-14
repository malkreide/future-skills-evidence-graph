from __future__ import annotations

import argparse
import os
import urllib.parse
import urllib.request
from typing import Any

from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    TODAY,
    append_candidate_sources,
    fetch_or_warn,
    filter_new_sources,
    filter_relevant_sources,
    slugify,
)


BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,authors,abstract,url,externalIds,venue,publicationTypes,isOpenAccess,openAccessPdf"


def fetch(query: str, limit: int, api_key: str | None = None) -> list[dict[str, Any]]:
    params = {"query": query, "limit": str(limit), "fields": FIELDS}
    request = urllib.request.Request(f"{BASE_URL}?{urllib.parse.urlencode(params)}")
    if api_key:
        request.add_header("x-api-key", api_key)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = __import__("json").load(response)
    return list(payload.get("data", []))


def convert(paper: dict[str, Any]) -> dict[str, Any]:
    title = paper.get("title") or "Untitled Semantic Scholar paper"
    external = paper.get("externalIds") or {}
    doi = external.get("DOI")
    publication_types = paper.get("publicationTypes") or []
    source_type = "peer_reviewed_article"
    if any(kind.lower() == "review" for kind in publication_types if isinstance(kind, str)):
        source_type = "systematic_review"
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": [author.get("name") for author in paper.get("authors", []) if author.get("name")],
        "year": paper.get("year") or 0,
        "doi": doi,
        "url": paper.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "openalex_id": None,
        "semantic_scholar_id": paper.get("paperId"),
        "eric_id": external.get("ERIC"),
        "publisher": paper.get("venue") or "Semantic Scholar",
        "source_type": source_type,
        "license": None,
        "abstract": paper.get("abstract"),
        "topics": ["education"],
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate source metadata from Semantic Scholar.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--output", default="data/sources/candidates-semantic-scholar.json")
    parser.add_argument("--min-relevance", type=float, default=RELEVANCE_THRESHOLD)
    args = parser.parse_args()

    papers = fetch_or_warn(
        "Semantic Scholar",
        lambda: fetch(args.query, args.limit, os.getenv("SEMANTIC_SCHOLAR_API_KEY")),
    )
    candidates = [convert(paper) for paper in papers]
    relevant = filter_relevant_sources(candidates, args.min_relevance)
    new_records = filter_new_sources(relevant)
    appended = append_candidate_sources(ROOT / args.output, new_records)
    print(
        f"Appended {len(appended)} new Semantic Scholar candidates to {args.output} "
        f"({len(candidates) - len(relevant)} filtered as irrelevant)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
