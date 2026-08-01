"""Measure what date-sorting costs OpenAlex result relevance.

`ingest_openalex.fetch` used to pass `sort=publication_year:desc` alongside
`search`. The `search` parameter ranks by relevance; that `sort` REPLACED the
ordering, so the API returned "everything matching any query term, newest first"
rather than "what matches best" -- invisible as long as nobody compared the two.

The counter-evidence lane made it visible: three runs examined 147 sources and
proposed nothing, and the rejection log showed 60-80% of those sources were
about other subjects entirely. Narrowing the queries made it WORSE, which is the
signature of a ranking that never considered the query in the first place.

This probe measured it: across four queries at ten results each, the two
orderings shared ZERO works. The importer now ranks by relevance and expresses
recency as a filter instead.

The probe stays because the comparison is worth repeating -- it is the only
thing that would notice a regression back to date-sorting, which produces
plausible-looking results and no error at all.

    python scripts/probe_openalex_ranking.py                # both query styles
    python scripts/probe_openalex_ranking.py --limit 20

Why it exists as a script and not a one-off: OpenAlex rate-limits hard from
shared addresses (HTTP 429), so this usually has to run somewhere else than a
developer sandbox -- and a measurement worth acting on is worth repeating.

Read the overlap first. A LOW overlap means the sort is choosing a materially
different set of papers than relevance would, and every consumer of
`ingest_openalex.fetch` is affected -- including the weekly pipeline, not only
the agent lane. A HIGH overlap means the sort is harmless and the lane's
off-topic problem lies elsewhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import ingest_openalex
from common import env_or_none

# The ordering the importer used until the probe measured it. Kept here, not in
# ingest_openalex, because the importer no longer has any business knowing it --
# but a comparison needs something to compare AGAINST, and a regression that
# reintroduced date-sorting would otherwise look like a clean run.
LEGACY_SORT = "publication_year:desc"

# One query in the shape the agent lane produces, one in the shape the curated
# importers use. They are listed together on purpose: the ordering is shared, so
# a verdict that only looks at the lane would miss what it does to the core.
PROBE_QUERIES = (
    ("lane", "self-regulated learning intervention meta-analysis"),
    ("lane", "metacognitive strategy training academic achievement"),
    ("importer", "artificial intelligence literacy primary school"),
    ("importer", "critical thinking curriculum secondary education"),
)


def fetch_raw(query: str, limit: int, sort: str | None, mailto: str | None) -> list[str]:
    """Titles for *query*, ordered by *sort* — or by relevance when sort is None."""
    params: dict[str, str] = {
        "search": query,
        "per-page": str(limit),
        # Mirror the importer's filter exactly -- including its recency window,
        # or the comparison measures two things at once.
        "filter": (
            "type:article|book|report,"
            f"publication_year:>{ingest_openalex.earliest_publication_year() - 1}"
        ),
    }
    if sort:
        params["sort"] = sort
    if mailto:
        params["mailto"] = mailto
    url = f"{ingest_openalex.BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    return [str(work.get("display_name") or "") for work in payload.get("results", [])]


def compare(query: str, limit: int, mailto: str | None) -> dict[str, Any]:
    dated = fetch_raw(query, limit, LEGACY_SORT, mailto)
    ranked = fetch_raw(query, limit, ingest_openalex.SEARCH_SORT, mailto)
    shared = {t for t in dated if t} & {t for t in ranked if t}
    return {
        "query": query,
        "dated": dated,
        "ranked": ranked,
        "overlap": len(shared),
        "overlap_share": len(shared) / limit if limit else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="results per query (default 10)")
    parser.add_argument("--query", action="append", help="probe this query instead of the defaults")
    args = parser.parse_args()

    mailto = env_or_none("OPENALEX_MAILTO")
    if not mailto:
        print(
            "Note: no OPENALEX_MAILTO — the polite pool is off and HTTP 429 is likely.",
            file=sys.stderr,
        )

    queries = [("custom", q) for q in args.query] if args.query else list(PROBE_QUERIES)
    results: list[dict[str, Any]] = []
    for kind, query in queries:
        try:
            result = compare(query, args.limit, mailto)
        except urllib.error.HTTPError as exc:
            print(f"FAIL: {query!r} — HTTP {exc.code}. Rate limited?", file=sys.stderr)
            return 1
        except OSError as exc:  # network down, DNS, timeout
            print(f"FAIL: {query!r} — {exc}", file=sys.stderr)
            return 1
        result["kind"] = kind
        results.append(result)

    print(f"OpenAlex ordering probe — {args.limit} results per query\n")
    print("  kind      overlap  query")
    for result in results:
        print(
            f"  {result['kind']:<9} {result['overlap']:>2}/{args.limit}"
            f"    {result['query']}"
        )

    total = sum(r["overlap"] for r in results)
    possible = args.limit * len(results)
    print(f"\nOverall overlap: {total}/{possible} = {total / possible:.0%}\n")
    print(
        "A LOW overlap means sort=publication_year:desc returns a materially\n"
        "different set than relevance ranking would — and every caller of\n"
        "ingest_openalex.fetch is affected, the weekly pipeline included.\n"
        "A HIGH overlap means the sort is harmless here and the counter-evidence\n"
        "lane's off-topic rate has another cause.\n"
    )

    for result in results:
        print(f"--- {result['query']}")
        print("  by date (what the importer sees today):")
        for title in result["dated"]:
            print(f"    - {title[:88]}")
        print("  by relevance:")
        for title in result["ranked"]:
            print(f"    - {title[:88]}")
        print()

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
