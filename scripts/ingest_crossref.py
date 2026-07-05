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


BASE_URL = "https://api.crossref.org/works"


def fetch(query: str, rows: int) -> list[dict[str, Any]]:
    params = {"query.bibliographic": query, "rows": str(rows), "sort": "published", "order": "desc"}
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = __import__("json").load(response)
    return list(payload.get("message", {}).get("items", []))


def _year(item: dict[str, Any]) -> int | None:
    parts = (item.get("published-print") or item.get("published-online") or item.get("issued") or {}).get(
        "date-parts", []
    )
    if parts and parts[0] and parts[0][0]:
        return int(parts[0][0])
    # None, not 0: a zero year used to fail source_is_valid_candidate and the
    # candidate vanished silently; None is allowed until promote-source.
    return None


def _authors(item: dict[str, Any]) -> list[str]:
    authors = []
    for author in item.get("author", []):
        parts = [author.get("given"), author.get("family")]
        name = " ".join(part for part in parts if part)
        if name:
            authors.append(name)
    return authors


def convert(item: dict[str, Any]) -> dict[str, Any]:
    title = (item.get("title") or ["Untitled Crossref work"])[0]
    doi = item.get("DOI")
    source_type = "peer_reviewed_article"
    if item.get("type") in {"book", "book-chapter", "monograph"}:
        source_type = "book"
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": _authors(item),
        "year": _year(item),
        "doi": doi,
        "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        "openalex_id": None,
        "semantic_scholar_id": None,
        "eric_id": None,
        "publisher": item.get("publisher") or "Crossref",
        "source_type": source_type,
        "license": None,
        # Crossref's abstract field is JATS XML and only sparsely populated, so
        # it is not ingested. KNOWN CONSEQUENCE: Crossref sources contribute
        # metadata only and NEVER yield automatic claims — extract_claims
        # requires an abstract (no claim without a verbatim text anchor). A
        # reviewer authors claims for a Crossref source by hand when it merits
        # them. Documented in OPERATIONS.md (components table).
        "abstract": None,
        "topics": ["education"],
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate source metadata from Crossref.")
    parser.add_argument(
        "--query",
        action="append",
        help="A search query (repeatable). Omit to use config/research_queries.json "
        "or the RESEARCH_QUERIES override.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--output", default="data/sources/candidates-crossref.json")
    parser.add_argument("--min-relevance", type=float, default=RELEVANCE_THRESHOLD)
    args = parser.parse_args()

    queries = dedupe_queries(args.query) if args.query else load_research_queries()
    items: list[dict[str, Any]] = []
    for query in queries:
        items.extend(fetch_or_warn("Crossref", lambda q=query: fetch(q, args.limit)))
    candidates = [convert(item) for item in items]
    relevant = filter_relevant_sources(candidates, args.min_relevance)
    new_records = filter_new_sources(relevant)
    appended = append_candidate_sources(ROOT / args.output, new_records)
    print(
        f"Appended {len(appended)} new Crossref candidates to {args.output} "
        f"from {len(queries)} quer{'y' if len(queries) == 1 else 'ies'} "
        f"({len(candidates) - len(relevant)} filtered as irrelevant)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
