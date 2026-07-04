from __future__ import annotations

import argparse
import urllib.parse
import urllib.request
from typing import Any
from xml.etree import ElementTree

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


BASE_URL = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def fetch(query: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "search_query": f"all:{query}",
        "max_results": str(limit),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        root = ElementTree.fromstring(response.read())
    return list(root.findall(f"{ATOM}entry"))


def _text(node: Any, tag: str) -> str:
    found = node.find(tag)
    return " ".join(found.text.split()) if found is not None and found.text else ""


def _html_url(entry: Any) -> str:
    for link in entry.findall(f"{ATOM}link"):
        if link.get("rel") == "alternate" and link.get("type") == "text/html":
            return link.get("href") or ""
    return _text(entry, f"{ATOM}id")


def convert(entry: Any) -> dict[str, Any]:
    title = _text(entry, f"{ATOM}title") or "Untitled arXiv work"
    published = _text(entry, f"{ATOM}published")
    year = int(published[:4]) if published[:4].isdigit() else 0
    authors = [
        " ".join(name.text.split())
        for author in entry.findall(f"{ATOM}author")
        for name in [author.find(f"{ATOM}name")]
        if name is not None and name.text
    ]
    doi = _text(entry, f"{ARXIV}doi") or None
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": _html_url(entry),
        "openalex_id": None,
        "semantic_scholar_id": None,
        "eric_id": None,
        # arXiv hosts preprints; treat them as working papers unless reviewed.
        "publisher": "arXiv",
        "source_type": "working_paper",
        "license": None,
        "abstract": _text(entry, f"{ATOM}summary") or None,
        "topics": ["education"],
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate source metadata from arXiv.")
    parser.add_argument(
        "--query",
        action="append",
        help="A search query (repeatable). Omit to use config/research_queries.json "
        "or the RESEARCH_QUERIES override.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--output", default="data/sources/candidates-arxiv.json")
    parser.add_argument("--min-relevance", type=float, default=RELEVANCE_THRESHOLD)
    args = parser.parse_args()

    queries = dedupe_queries(args.query) if args.query else load_research_queries()
    entries: list[dict[str, Any]] = []
    for query in queries:
        entries.extend(fetch_or_warn("arXiv", lambda q=query: fetch(q, args.limit)))
    candidates = [convert(entry) for entry in entries]
    relevant = filter_relevant_sources(candidates, args.min_relevance)
    new_records = filter_new_sources(relevant)
    appended = append_candidate_sources(ROOT / args.output, new_records)
    print(
        f"Appended {len(appended)} new arXiv candidates to {args.output} "
        f"from {len(queries)} quer{'y' if len(queries) == 1 else 'ies'} "
        f"({len(candidates) - len(relevant)} filtered as irrelevant)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
