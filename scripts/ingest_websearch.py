"""Discovery web-search importer: a topic query -> candidate web sources.

Unlike resolve_source_url.py — which searches for *one* URL of an already-known
title — this importer searches the opposite direction: a topic query (e.g. "AI
literacy curriculum primary school") -> a handful of *new* candidate sources the
keyless catalogues (OpenAlex, Crossref, ERIC) never surface. It is the
grey-literature discovery lane for the future-skills evidence graph and reuses
the URL resolver's open-web search backends.

The strategy is **open search, tiered trust**, configured in
``data/source_domains.json``:

- The search itself is NOT restricted to an allowlist — it queries the open web,
  so nothing relevant is missed (good recall, the same property recall_probe.py
  measures).
- Each hit's host is then mapped to a trust tier (``trusted`` / ``watch`` /
  ``open``). The tier is a *label*, not a filter: it steers the triage worksheet
  ordering (trusted first, open last and clearly marked) and is recorded in
  provenance. It deliberately does NOT enter evidence_score — score_evidence.py
  keeps its reproducibility guarantee, and every web hit stays source_type
  ``web_resource`` (weight 0.25), the lowest tier.

Search backends, mirroring resolve_source_url.py and tried in order (results
aggregated, deduped by URL):

1. **SearXNG** — a self-hosted, open-source metasearch instance (opt-in via
   ``SEARXNG_URL``, no key).
2. **DuckDuckGo** — the keyless, open-source ``ddgs`` library (runs out of the
   box; a no-op if the library is absent).
3. **Google Programmable Search** — optional last fallback, only when
   ``GOOGLE_SEARCH_API_KEY`` and ``GOOGLE_SEARCH_CX`` are set.

Like every importer here it is candidate-only and human-reviewed: each result
becomes a ``status='candidate'`` source, deduped repo-wide, never auto-activated.
Claims are NOT minted here — they keep flowing through extract_claims.py /
ingest_reports.py from a source's full text, so the verbatim hallucination guard
is untouched.

Off by default and graceful: with no search backend available (no ``ddgs``, no
``SEARXNG_URL``, no Google secret) the importer is a no-op (writes nothing), and
any network failure just yields no results for that query. ``ddgs`` is the only
non-stdlib dependency, imported lazily and optional.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

from common import (
    ROOT,
    TODAY,
    append_candidate_sources,
    filter_new_sources,
    filter_relevant_sources,
    load_json,
    slugify,
)

# Reuse the URL resolver's open-web plumbing: the graceful HTTP-JSON helper, the
# lazy DuckDuckGo-availability probe. Imported by name so tests can patch
# ``ingest_websearch._http_json`` / ``ingest_websearch._ddgs_available``.
from resolve_source_url import _ddgs_available, _http_json

DEFAULT_DOMAINS_PATH = ROOT / "data" / "source_domains.json"
DEFAULT_OUTPUT = "data/sources/candidates-websearch.json"

# Results requested per backend per query (Google Programmable Search caps at 10).
MAX_RESULTS_PER_QUERY = 10

# Only accept a 4-digit year that is plausible for a publication; a web resource
# often carries no clear date, so when none is found we fall back to the current
# year and mark it provisional in provenance for the reviewer to confirm.
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def load_domain_tiers(path: Path | None = None) -> dict[str, Any]:
    """Load the curated domain->tier config, or a permissive empty default.

    A missing or malformed file degrades to "everything is open" rather than
    aborting the importer, so a typo in the config never blocks discovery — it
    only drops the trust labels until the config is fixed.
    """
    path = path or DEFAULT_DOMAINS_PATH
    try:
        data = load_json(path)
    except (OSError, ValueError):
        return {"tiers": {}, "open": {"rank_penalty": 0.0}}
    if not isinstance(data, dict):
        return {"tiers": {}, "open": {"rank_penalty": 0.0}}
    return data


def registrable_host(url: str) -> str:
    """The bare lowercase host of *url* without a leading ``www.`` (or "")."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def host_tier(url: str, config: dict[str, Any]) -> tuple[str, float]:
    """Map *url*'s host to its ``(tier_name, rank_delta)``.

    A host matches a tier domain when it equals the domain or is a subdomain of
    it (suffix match), so ``read.oecd.org`` matches ``oecd.org``. The first tier
    in config order that matches wins; an unmatched host is ``open`` and carries
    the configured ``rank_penalty`` as a negative delta. The delta is stored on
    the candidate so the triage worksheet can rank without re-reading the config.
    """
    host = registrable_host(url)
    tiers = config.get("tiers", {}) if isinstance(config.get("tiers"), dict) else {}
    if host:
        for tier_name, tier in tiers.items():
            if not isinstance(tier, dict):
                continue
            for domain in tier.get("domains", []):
                domain = str(domain).lower().removeprefix("www.")
                if host == domain or host.endswith(f".{domain}"):
                    return tier_name, float(tier.get("rank_boost", 0.0))
    penalty = 0.0
    open_cfg = config.get("open")
    if isinstance(open_cfg, dict):
        penalty = float(open_cfg.get("rank_penalty", 0.0))
    return "open", -penalty


def _result(title: Any, link: Any, snippet: Any) -> dict[str, str] | None:
    """Normalize one backend hit to ``{title, link, snippet}``, or None if thin."""
    if not link or not title:
        return None
    return {"title": str(title), "link": str(link), "snippet": str(snippet or "")}


def searxng_search(query: str, num: int) -> list[dict[str, str]]:
    """Open-web search via a self-hosted SearXNG instance (opt-in ``SEARXNG_URL``).

    Keyless and open-source. A no-op (``[]``) unless ``SEARXNG_URL`` is set, and
    ``[]`` on any network/parse failure (``_http_json`` never raises).
    """
    base = os.environ.get("SEARXNG_URL")
    if not base:
        return []
    params = urllib.parse.urlencode({"q": query, "format": "json", "language": "en"})
    data = _http_json(f"{base.rstrip('/')}/search?{params}")
    if not isinstance(data, dict):
        return []
    results: list[dict[str, str]] = []
    for hit in (data.get("results") or [])[:num]:
        result = _result(hit.get("title") or hit.get("name"), hit.get("url") or hit.get("href"),
                         hit.get("content") or hit.get("snippet"))
        if result:
            results.append(result)
    return results


def duckduckgo_search(query: str, num: int) -> list[dict[str, str]]:
    """Open-web search via the keyless, open-source ``ddgs`` library.

    A no-op (``[]``) when the optional library is absent or the request fails, so
    the tier stays graceful and runs out of the box wherever ``ddgs`` is present.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # older package name
        except ImportError:
            return []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=num))
    except Exception:  # noqa: BLE001 - any client/network error → no results
        return []
    results: list[dict[str, str]] = []
    for hit in hits:
        result = _result(hit.get("title") or hit.get("name"),
                         hit.get("href") or hit.get("url") or hit.get("link"),
                         hit.get("body") or hit.get("snippet"))
        if result:
            results.append(result)
    return results


def google_search(query: str, num: int) -> list[dict[str, str]]:
    """Open-web search via Google Programmable Search (optional last fallback).

    A no-op (``[]``) unless both ``GOOGLE_SEARCH_API_KEY`` and ``GOOGLE_SEARCH_CX``
    are set, and ``[]`` on any network/parse failure. Caps *num* to the API's
    per-request maximum.
    """
    key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")
    if not key or not cx:
        return []
    num = max(1, min(num, MAX_RESULTS_PER_QUERY))
    params = urllib.parse.urlencode({"key": key, "cx": cx, "q": query, "num": str(num)})
    data = _http_json(f"https://www.googleapis.com/customsearch/v1?{params}")
    if not isinstance(data, dict):
        return []
    results: list[dict[str, str]] = []
    for item in data.get("items") or []:
        result = _result(item.get("title"), item.get("link"), item.get("snippet"))
        if result:
            results.append(result)
    return results


def search_backends_available() -> bool:
    """Whether any search backend can run (SearXNG configured, ddgs present, or Google)."""
    return bool(
        os.environ.get("SEARXNG_URL")
        or _ddgs_available()
        or (os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX"))
    )


def search_results(query: str, num: int) -> list[dict[str, str]]:
    """Open-web search for *query* across all available backends.

    Aggregates SearXNG + DuckDuckGo + Google results (resolver order: open-source
    and keyless first, paid Google last) and dedupes by URL — so the same page
    surfaced by two engines counts once. Returns ``[]`` when no backend is
    available or all fail. Backends are resolved by name at call time so each
    stays independently patchable.
    """
    num = max(1, num)
    aggregated: list[dict[str, str]] = []
    seen: set[str] = set()
    for backend in (searxng_search, duckduckgo_search, google_search):
        for result in backend(query, num):
            key = result["link"].strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            aggregated.append(result)
    return aggregated


def detect_year(*texts: str) -> tuple[int, bool]:
    """Return ``(year, provisional)`` from the first plausible 4-digit year found.

    Scans the given texts (title, snippet, url) in order; the most recent year
    among the matches is preferred. When none is found, falls back to the current
    year with ``provisional=True`` so the reviewer knows to confirm or correct it.
    """
    years = [int(m) for text in texts for m in _YEAR_RE.findall(text or "")]
    if years:
        return max(years), False
    return date.today().year, True


def build_source(result: dict[str, str], query: str, config: dict[str, Any]) -> dict[str, Any]:
    """Build a candidate ``web_resource`` source from one search result.

    relevance_score / topics / audience are filled provisionally here and set
    authoritatively by filter_relevant_sources. The trust tier and the
    originating query live under the non-binding ``assist.provenance`` block
    (no schema change), where the tier's numeric ``rank_delta`` lets the triage
    worksheet order results without re-reading the domain config.
    """
    title = result["title"].strip()
    url = result["link"].strip()
    snippet = result.get("snippet", "").strip()
    tier_name, rank_delta = host_tier(url, config)
    year, provisional = detect_year(title, snippet, url)
    provenance: dict[str, Any] = {
        "via": "websearch",
        "domain_tier": tier_name,
        "rank_delta": round(rank_delta, 3),
        "query": query,
        "created_at": TODAY,
    }
    if provisional:
        provenance["year_provisional"] = True
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": [],
        "year": year,
        "doi": None,
        "url": url,
        "openalex_id": None,
        "semantic_scholar_id": None,
        "eric_id": None,
        "publisher": registrable_host(url) or "web",
        "source_type": "web_resource",
        "license": None,
        "abstract": snippet or None,
        "topics": [],
        "relevance_score": 0.0,
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
        "assist": {"provenance": provenance},
    }


def import_query(
    query: str, num: int, config: dict[str, Any], output_path: Path
) -> tuple[int, int, int]:
    """Run one query end-to-end, returning ``(appended, relevant, found)`` counts.

    Mirrors ingest_reports.import_job: build sources, drop irrelevant/off-scope
    with filter_relevant_sources, dedupe repo-wide with filter_new_sources, then
    append. Each append re-reads the candidate file, so a later query in the same
    run sees an earlier query's appends.
    """
    found = search_results(query, num)
    sources = [build_source(result, query, config) for result in found]
    relevant = filter_relevant_sources(sources)
    new_sources = filter_new_sources(relevant)
    appended = append_candidate_sources(output_path, new_sources)
    return len(appended), len(relevant), len(found)


def load_queries(args: argparse.Namespace) -> list[str]:
    """Resolve the query list from --query (repeatable) or a --manifest file."""
    queries: list[str] = []
    if args.manifest:
        entries = load_json(ROOT / args.manifest)
        if not isinstance(entries, list):
            raise ValueError(f"{args.manifest} must contain a JSON array of query strings")
        queries.extend(str(entry).strip() for entry in entries if str(entry).strip())
    queries.extend(q.strip() for q in (args.query or []) if q.strip())
    if not queries:
        raise ValueError("provide at least one --query, or a --manifest of queries")
    # De-dupe while preserving order so a repeated query runs once.
    seen: set[str] = set()
    return [q for q in queries if not (q in seen or seen.add(q))]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover candidate web sources for a topic query (open search, tiered trust)."
    )
    parser.add_argument(
        "--query", action="append", help="A search query (repeatable)."
    )
    parser.add_argument(
        "--manifest", help="JSON array of query strings to run in one batch."
    )
    parser.add_argument(
        "--num", type=int, default=MAX_RESULTS_PER_QUERY,
        help=f"Results per query (max {MAX_RESULTS_PER_QUERY}).",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--domains", default=str(DEFAULT_DOMAINS_PATH.relative_to(ROOT)),
        help="Path to the domain->tier config.",
    )
    args = parser.parse_args()

    # Off by default: a no-op with a clear message when no backend is available,
    # exactly like the project's other opt-in network features.
    if not search_backends_available():
        print(
            "Web search off (no backend: install ddgs, set SEARXNG_URL, "
            "or set GOOGLE_SEARCH_API_KEY / GOOGLE_SEARCH_CX); imported no candidates."
        )
        return 0

    try:
        queries = load_queries(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    config = load_domain_tiers(ROOT / args.domains)
    output_path = ROOT / args.output
    total_appended = total_relevant = total_found = 0
    for query in queries:
        appended, relevant, found = import_query(query, args.num, config, output_path)
        total_appended += appended
        total_relevant += relevant
        total_found += found

    print(
        f"Searched {len(queries)} query/queries: {total_found} hit(s), "
        f"{total_relevant} in-scope, appended {total_appended} candidate source(s) to {args.output} "
        f"({total_relevant - total_appended} already known)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
