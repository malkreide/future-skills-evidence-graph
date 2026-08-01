from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from common import TODAY, run_importer, slugify


BASE_URL = "https://api.openalex.org/works"

# NOTE: this REPLACES OpenAlex's relevance ranking. `search` would order by how
# well a work matches; with this sort the API returns "everything matching any
# query term, newest first" instead. Named here rather than inlined so
# probe_openalex_ranking.py measures the ordering the importer actually sends —
# a copied literal there would keep reporting on this value after someone
# changed it. Whether the trade is right is an open question; see that probe.
SEARCH_SORT = "publication_year:desc"


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
        "sort": SEARCH_SORT,
    }
    if mailto:
        params["mailto"] = mailto
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
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
    return run_importer(
        "OpenAlex",
        fetch,
        convert,
        "data/sources/candidates-openalex.json",
        configure_parser=lambda parser: parser.add_argument(
            "--mailto", default=None, help="Polite contact email for the OpenAlex API."
        ),
        fetch_kwargs=lambda args: {"mailto": args.mailto},
    )


if __name__ == "__main__":
    raise SystemExit(main())
