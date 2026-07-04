from __future__ import annotations

import argparse
import json
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


BASE_URL = "https://api.ies.ed.gov/eric/"
FIELDS = "id,title,author,description,publicationdateyear,url,peerreviewed,publicationtype,source"


def fetch(query: str, rows: int) -> list[dict[str, Any]]:
    params = {"search": query, "format": "json", "rows": str(rows), "fields": FIELDS}
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    return list(payload.get("response", {}).get("docs", []))


def _source_type(doc: dict[str, Any]) -> str:
    # ERIC publicationtype is a list mixing a document type ("Journal Articles",
    # "Books") with content descriptors ("Reports - Research", "Information
    # Analyses"). The document type decides the source_type, so it is checked
    # before the descriptors: an EJ journal article tagged "Reports - Research"
    # is a peer-reviewed article, not a policy report.
    types = [str(kind).lower() for kind in doc.get("publicationtype", [])]
    if any("book" in kind for kind in types):
        return "book"
    if any("journal articles" in kind for kind in types):
        return "peer_reviewed_article"
    if any("information analyses" in kind for kind in types):
        return "conceptual_review"
    if any("report" in kind for kind in types):
        return "policy_report"
    if doc.get("peerreviewed") == "T":
        return "peer_reviewed_article"
    return "conceptual_review"


def convert(doc: dict[str, Any]) -> dict[str, Any]:
    title = doc.get("title") or "Untitled ERIC record"
    eric_id = doc.get("id")
    year = doc.get("publicationdateyear")
    authors = doc.get("author")
    if isinstance(authors, str):
        authors = [authors]
    url = doc.get("url") or (f"https://eric.ed.gov/?id={eric_id}" if eric_id else "")
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": list(authors or []),
        "year": int(year) if isinstance(year, (int, str)) and str(year).isdigit() else 0,
        "doi": None,
        "url": url,
        "openalex_id": None,
        "semantic_scholar_id": None,
        "eric_id": eric_id,
        "publisher": doc.get("source") or "ERIC",
        "source_type": _source_type(doc),
        "license": None,
        "abstract": doc.get("description") or None,
        "topics": ["education"],
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate source metadata from ERIC.")
    parser.add_argument(
        "--query",
        action="append",
        help="A search query (repeatable). Omit to use config/research_queries.json "
        "or the RESEARCH_QUERIES override.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--output", default="data/sources/candidates-eric.json")
    parser.add_argument("--min-relevance", type=float, default=RELEVANCE_THRESHOLD)
    args = parser.parse_args()

    queries = dedupe_queries(args.query) if args.query else load_research_queries()
    docs: list[dict[str, Any]] = []
    for query in queries:
        docs.extend(fetch_or_warn("ERIC", lambda q=query: fetch(q, args.limit)))
    candidates = [convert(doc) for doc in docs]
    relevant = filter_relevant_sources(candidates, args.min_relevance)
    new_records = filter_new_sources(relevant)
    appended = append_candidate_sources(ROOT / args.output, new_records)
    print(
        f"Appended {len(appended)} new ERIC candidates to {args.output} "
        f"from {len(queries)} quer{'y' if len(queries) == 1 else 'ies'} "
        f"({len(candidates) - len(relevant)} filtered as irrelevant)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
