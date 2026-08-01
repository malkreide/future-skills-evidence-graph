from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from common import TODAY, run_importer, slugify


BASE_URL = "https://api.openalex.org/works"

# Results are ranked by RELEVANCE — OpenAlex's default for `search` — and recency
# is a FILTER instead.
#
# This used to be `sort=publication_year:desc`, which replaced the relevance
# ranking outright: the API then returned "everything matching any query term,
# newest first". probe_openalex_ranking.py measured what that cost, and the
# answer was total. Across four queries, ten results each, the two orderings
# shared **zero** works:
#
#   query                                          overlap
#   artificial intelligence literacy primary school   0/10
#   critical thinking curriculum secondary education  0/10
#
# For the first, sorting by date returned "Doing Game Design in Theatre" and
# "Distributed Leadership Applied"; ranking by relevance returned "Artificial
# intelligence literacy education in primary schools: a review". Curated
# importer queries were hit exactly as hard as the agent lane's — the relevance
# filter downstream could only ever pick from what this function handed it.
#
# The sort was not pointless, though: a catalogue about FUTURE skills wants
# recent work. That intent survives as a filter, which constrains the candidate
# set without touching the ordering — "the best matches among recent work"
# rather than "the newest among any match".
SEARCH_SORT: str | None = None

# How far back the filter reaches. Wide enough that a field's formative papers
# are still reachable, narrow enough to keep the catalogue current. Relative to
# TODAY rather than a fixed date, or it silently ages into meaninglessness.
RECENCY_YEARS = 8


def inverted_index_to_text(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, offsets in index.items():
        for offset in offsets:
            positions.append((offset, word))
    return " ".join(word for _, word in sorted(positions))


def earliest_publication_year() -> int:
    """First year the recency filter still admits, counted back from TODAY."""
    return int(TODAY[:4]) - RECENCY_YEARS


def fetch(query: str, limit: int, mailto: str | None = None) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "per-page": str(limit),
        # Recency as a filter, not as an ordering — see SEARCH_SORT above.
        "filter": (
            f"type:article|book|report,publication_year:>{earliest_publication_year() - 1}"
        ),
    }
    if SEARCH_SORT:
        params["sort"] = SEARCH_SORT
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
