from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from common import TODAY, run_importer, slugify


BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,authors,abstract,url,externalIds,venue,publicationTypes,isOpenAccess,openAccessPdf"


def fetch(query: str, limit: int, api_key: str | None = None) -> list[dict[str, Any]]:
    params = {"query": query, "limit": str(limit), "fields": FIELDS}
    request = urllib.request.Request(f"{BASE_URL}?{urllib.parse.urlencode(params)}")
    if api_key:
        request.add_header("x-api-key", api_key)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
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
        # Explicit nulls appear in live payloads; a null author entry must not
        # abort the run.
        "authors": [
            name
            for author in (paper.get("authors") or [])
            if (name := (author or {}).get("name"))
        ],
        "year": paper.get("year") or None,
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
    return run_importer(
        "Semantic Scholar",
        fetch,
        convert,
        "data/sources/candidates-semantic-scholar.json",
        fetch_kwargs=lambda args: {"api_key": os.getenv("SEMANTIC_SCHOLAR_API_KEY")},
    )


if __name__ == "__main__":
    raise SystemExit(main())
