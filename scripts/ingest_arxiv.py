from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Any
from xml.etree import ElementTree

from common import TODAY, run_importer, slugify


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
    year = int(published[:4]) if published[:4].isdigit() else None
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
    return run_importer("arXiv", fetch, convert, "data/sources/candidates-arxiv.json")


if __name__ == "__main__":
    raise SystemExit(main())
