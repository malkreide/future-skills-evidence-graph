from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from common import TODAY, run_importer, slugify


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
        "year": int(year) if isinstance(year, (int, str)) and str(year).isdigit() else None,
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
    return run_importer("ERIC", fetch, convert, "data/sources/candidates-eric.json")


if __name__ == "__main__":
    raise SystemExit(main())
