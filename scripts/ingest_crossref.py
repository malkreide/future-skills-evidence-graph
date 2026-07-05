from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from common import TODAY, run_importer, slugify


BASE_URL = "https://api.crossref.org/works"


def fetch(query: str, rows: int) -> list[dict[str, Any]]:
    params = {"query.bibliographic": query, "rows": str(rows), "sort": "published", "order": "desc"}
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
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
    # Explicit nulls appear in live payloads; a null author entry must not
    # abort the run.
    for author in item.get("author") or []:
        parts = [(author or {}).get("given"), (author or {}).get("family")]
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
    return run_importer("Crossref", fetch, convert, "data/sources/candidates-crossref.json")


if __name__ == "__main__":
    raise SystemExit(main())
