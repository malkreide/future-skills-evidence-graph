"""Resolve a source's canonical URL from a report's text and metadata.

Option B of the title->URL sketch: the server-side counterpart to the dashboard
dropzone's in-browser lookup (`site/assets/submit.js`). It runs inside the
`ingest-from-issue` workflow so the issue form's URL field can be **optional** —
when a submitter gives no URL, this resolves one from the report itself.

Resolution order (first hit wins), each step degrading gracefully to the next:

1. **In the document** — a DOI or URL printed in the report text (cover page,
   footer, "available at ..."). Deterministic, no network.
2. **Crossref** — title -> best bibliographic match (keyless).
3. **OpenAlex** — title -> best work (keyless).
4. **SearXNG** — open-web search via a self-hosted, open-source metasearch
   instance (opt-in via `SEARXNG_URL`, no key).
5. **DuckDuckGo** — open-web search via the open-source `ddgs` library (no key,
   no hosting); for the grey literature the keyless catalogues miss.
6. **Google Programmable Search** — optional last fallback, only when
   `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX` are set.

A catalogue hit is only accepted above a title-similarity threshold and, when a
year is known, within ±1 year; the open-web tiers additionally restrict hits to a
curated allowlist of credible publishers (`CREDIBLE_DOMAINS`) unless
`RESOLVE_OPEN_WEB=1`. Every network call fails silent (returns None) so a flaky
service just falls through. The `ddgs` library is imported lazily and is the only
non-stdlib dependency (optional — absent it the DuckDuckGo tier is a no-op).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Title-match acceptance, mirrored from the client (Sørensen-Dice ≥ 0.7).
TITLE_MATCH_THRESHOLD = 0.7
HTTP_TIMEOUT = 20

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>)\]]+", re.I)
_URL_RE = re.compile(r"https?://[^\s\"<>)\]]+", re.I)
_ASSET_RE = re.compile(r"\.(png|jpe?g|gif|svg|css|js|woff2?)$", re.I)


def _strip(value: str) -> str:
    """Drop trailing punctuation a URL/DOI often picks up in running text."""
    return re.sub(r"[).,;:\]]+$", "", value)


def _registrable_host(url: str) -> str:
    """Lower-case host of *url* without a leading ``www.`` (``""`` on failure)."""
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


# Curated allowlist of credible international publishers (registrable domains).
# It replaces the Google Programmable Search Engine's 50-domain restriction in
# code: the open-web search tiers (SearXNG / DuckDuckGo) only accept a hit whose
# host is on this list, unless RESOLVE_OPEN_WEB=1 opens it to the whole web.
CREDIBLE_DOMAINS = frozenset({
    "oecd.org", "oecd-ilibrary.org", "oecd.ai", "weforum.org", "unesco.org",
    "unesdoc.unesco.org", "iiep.unesco.org", "un.org", "undp.org", "unicef.org",
    "unicef-irc.org", "ilo.org", "worldbank.org", "openknowledge.worldbank.org",
    "imf.org", "europa.eu", "op.europa.eu", "education.ec.europa.eu",
    "cedefop.europa.eu", "etf.europa.eu", "joint-research-centre.ec.europa.eu",
    "coe.int", "eua.eu", "iea.nl", "ets.org", "act.org", "brookings.edu",
    "rand.org", "mckinsey.com", "bcg.com", "pewresearch.org", "nesta.org.uk",
    "nuffieldfoundation.org", "gatesfoundation.org", "hewlett.org",
    "carnegiefoundation.org", "hundred.org", "iza.org", "bertelsmann-stiftung.de",
    "iadb.org", "adb.org", "afdb.org", "hai.stanford.edu", "nber.org",
    "worldskills.org", "educationendowmentfoundation.org.uk",
    "learningpolicyinstitute.org", "rti.org", "britishcouncil.org",
    "globalpartnership.org",
})


def _host_allowed(url: str) -> bool:
    """True when *url*'s host is (a subdomain of) a CREDIBLE_DOMAINS entry."""
    host = _registrable_host(url)
    return bool(host) and any(
        host == domain or host.endswith(f".{domain}") for domain in CREDIBLE_DOMAINS
    )


def find_in_text(text: str, publisher: str | None = None) -> str | None:
    """Return a DOI/URL printed in *text*, or None (deterministic, no network).

    Mirrors the dashboard's ``detectSourceUrl``: a DOI wins; otherwise the URL
    whose host matches the publisher, then the most frequent host, then the first.
    """
    if not text:
        return None
    hay = f"{text[:20000]}\n{text[-8000:]}"
    doi = _DOI_RE.search(hay)
    if doi:
        return f"https://doi.org/{_strip(doi.group(0))}"
    urls = [_strip(u) for u in _URL_RE.findall(hay)]
    urls = [u for u in urls if not _ASSET_RE.search(u)]
    if not urls:
        return None

    pub = (publisher or "").strip().lower()
    if pub:
        for url in urls:
            host = _registrable_host(url)
            if host and (pub in host or host.split(".")[0] in pub):
                return url
    freq: dict[str, int] = {}
    for url in urls:
        host = _registrable_host(url)
        if host:
            freq[host] = freq.get(host, 0) + 1
    top_host = max(freq, key=lambda h: freq[h]) if freq else ""
    for url in urls:
        if _registrable_host(url) == top_host:
            return url
    return urls[0]


# guess_title scans only the first non-empty lines (the cover); a fixed window so
# a long document never pulls a "title" out of its body.
_TITLE_SCAN_LINES = 25


def guess_title(text: str) -> str:
    """Best title guess from cover text: longest titleish line near the top.

    Skips table-of-contents lines (dot leaders, leading page numbers) and lines
    that are mostly non-letters. Mirrors the client's ``guessTitle``.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    best = ""
    for line in lines[:_TITLE_SCAN_LINES]:
        if len(line) < 15 or len(line) > 200:
            continue
        if re.search(r"\.{4,}|^\d+(\s|\.|$)", line):
            continue
        letters = len(re.findall(r"[A-Za-zÄÖÜäöüß]", line))
        if letters < len(line) * 0.5:
            continue
        if len(line) > len(best):
            best = line
    return best


def title_similarity(a: str, b: str) -> float:
    """Sørensen-Dice over word sets; robust to word order. Mirrors the client."""
    tokens_a = set(re.findall(r"[a-z0-9äöüß]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9äöüß]+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    shared = len(tokens_a & tokens_b)
    return (2 * shared) / (len(tokens_a) + len(tokens_b))


def _http_json(url: str) -> Any | None:
    """GET *url* as JSON, or None on any failure (graceful, no raise)."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "future-skills-evidence-graph-url-resolver",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.load(response)
    except Exception:  # noqa: BLE001 - any network/parse error → fall through
        return None


def _best_by_title(
    candidates: list[tuple[str, str, int | None]], query: str, year: int | None
) -> tuple[str, str] | None:
    """Pick the best (url, title) from (url, title, year) candidates, or None.

    Accepts only above the similarity threshold and, when *year* is given, within
    ±1 year. Among the survivors the highest similarity (small bonus for an exact
    year) wins.
    """
    best: tuple[str, str] | None = None
    best_score = 0.0
    for url, cand_title, cand_year in candidates:
        if not url:
            continue
        similarity = title_similarity(query, cand_title)
        if similarity < TITLE_MATCH_THRESHOLD:
            continue
        if year and cand_year and abs(cand_year - year) > 1:
            continue
        score = similarity + (0.1 if year and cand_year == year else 0.0)
        if score > best_score:
            best, best_score = (url, cand_title), score
    return best


def crossref_best(title: str, year: int | None) -> tuple[str, str] | None:
    """Title -> best Crossref match as (url, matched_title), or None."""
    params = urllib.parse.urlencode(
        {"query.bibliographic": title, "rows": "4", "select": "title,DOI,issued,URL"}
    )
    data = _http_json(f"https://api.crossref.org/works?{params}")
    if not data:
        return None
    candidates: list[tuple[str, str, int | None]] = []
    for item in data.get("message", {}).get("items", []):
        cand_title = (item.get("title") or [""])[0]
        parts = (
            item.get("issued", {}).get("date-parts")
            or item.get("published-print", {}).get("date-parts")
            or [[None]]
        )
        cand_year = parts[0][0] if parts and parts[0] else None
        url = f"https://doi.org/{item['DOI']}" if item.get("DOI") else item.get("URL")
        candidates.append((url or "", cand_title, cand_year))
    return _best_by_title(candidates, title, year)


def openalex_best(title: str, year: int | None) -> tuple[str, str] | None:
    """Title -> best OpenAlex work as (url, matched_title), or None."""
    params = urllib.parse.urlencode({"search": title, "per_page": "4"})
    data = _http_json(f"https://api.openalex.org/works?{params}")
    if not data:
        return None
    candidates: list[tuple[str, str, int | None]] = []
    for work in data.get("results", []):
        cand_title = work.get("display_name") or ""
        landing = (work.get("primary_location") or {}).get("landing_page_url")
        url = work.get("doi") or landing or work.get("id")
        candidates.append((url or "", cand_title, work.get("publication_year")))
    return _best_by_title(candidates, title, year)


def google_best(title: str) -> str | None:
    """Title -> first Google Programmable Search hit, or None.

    Opt-in and the only tier needing a secret: a no-op unless both
    ``GOOGLE_SEARCH_API_KEY`` and ``GOOGLE_SEARCH_CX`` are set. For grey
    literature the keyless catalogues miss; the human still confirms the URL.
    """
    key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")
    if not key or not cx:
        return None
    params = urllib.parse.urlencode({"key": key, "cx": cx, "q": title, "num": "1"})
    data = _http_json(f"https://www.googleapis.com/customsearch/v1?{params}")
    if not data:
        return None
    items = data.get("items") or []
    return items[0].get("link") if items else None


def _result_url(result: dict[str, Any]) -> str:
    """URL field of a web result, across SearXNG (``url``) and ddgs (``href``)."""
    return result.get("url") or result.get("href") or result.get("link") or ""


def _best_web_result(
    results: list[dict[str, Any]], title: str
) -> tuple[str, str] | None:
    """Pick the best (url, title) from open-web *results*, or None.

    A hit must clear the title-similarity threshold and, unless ``RESOLVE_OPEN_WEB
    =1``, sit on a CREDIBLE_DOMAINS host — so the open-web tiers stay as
    source-credible as the old Google Programmable Search restriction.
    """
    open_web = os.environ.get("RESOLVE_OPEN_WEB") == "1"
    best: tuple[str, str] | None = None
    best_score = 0.0
    for result in results:
        url = _result_url(result)
        if not url or (not open_web and not _host_allowed(url)):
            continue
        cand_title = result.get("title") or result.get("name") or ""
        similarity = title_similarity(title, cand_title)
        if similarity >= TITLE_MATCH_THRESHOLD and similarity > best_score:
            best, best_score = (url, cand_title), similarity
    return best


def searxng_best(title: str) -> tuple[str, str] | None:
    """Title -> best SearXNG hit, or None (opt-in via ``SEARXNG_URL``).

    SearXNG is a self-hosted, fully open-source metasearch engine with a JSON
    API and no key. A no-op unless ``SEARXNG_URL`` points at an instance.
    """
    base = os.environ.get("SEARXNG_URL")
    if not base:
        return None
    params = urllib.parse.urlencode({"q": title, "format": "json", "language": "en"})
    data = _http_json(f"{base.rstrip('/')}/search?{params}")
    if not data:
        return None
    return _best_web_result(data.get("results", []), title)


def _ddgs_available() -> bool:
    """True when the optional DuckDuckGo library can be imported."""
    try:
        import ddgs  # noqa: F401
        return True
    except ImportError:
        try:
            import duckduckgo_search  # noqa: F401
            return True
        except ImportError:
            return False


def duckduckgo_best(title: str) -> tuple[str, str] | None:
    """Title -> best DuckDuckGo hit via the open-source ``ddgs`` library, or None.

    Keyless and host-free, so it runs anywhere. A no-op (returns None) when the
    optional library is absent or the request fails, keeping the tier graceful.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # older package name
        except ImportError:
            return None
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(title, max_results=6))
    except Exception:  # noqa: BLE001 - any client/network error → no hit
        return None
    return _best_web_result(results, title)


def resolve_url(
    text: str,
    title: str | None = None,
    year: int | None = None,
    publisher: str | None = None,
) -> dict[str, str] | None:
    """Resolve a source URL from *text*/metadata, or None.

    Order: ``document`` (no network) -> ``crossref`` -> ``openalex`` (keyless
    catalogues) -> ``searxng`` -> ``duckduckgo`` (open-source open web, filtered
    to CREDIBLE_DOMAINS) -> ``google`` (optional last fallback). Returns
    ``{"url", "via"}`` (plus ``"match"`` for a matched title), or None.
    """
    in_document = find_in_text(text, publisher)
    if in_document:
        return {"url": in_document, "via": "document"}

    query = (title or guess_title(text)).strip()
    if len(query) < 8:
        return None
    for finder, via in ((crossref_best, "crossref"), (openalex_best, "openalex")):
        hit = finder(query, year)
        if hit:
            return {"url": hit[0], "via": via, "match": hit[1]}
    for finder, via in ((searxng_best, "searxng"), (duckduckgo_best, "duckduckgo")):
        hit = finder(query)
        if hit:
            return {"url": hit[0], "via": via, "match": hit[1]}
    google = google_best(query)
    if google:
        return {"url": google, "via": "google"}
    return None


def _google_diagnostic(title: str) -> str:
    """Raw Google call for the smoke test: report HTTP status / error / counts.

    Diagnostic only — unlike ``google_best`` (which fails silent in production)
    this surfaces *why* Google returned nothing: an HTTP 403 (Custom Search API
    not enabled or key restricted), 429 (daily quota), or a genuine 0-results.
    The API key is never printed (only the URL carries it, and the URL is not
    logged).
    """
    key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")
    if not (key and cx):
        return "nicht konfiguriert"
    params = urllib.parse.urlencode({"key": key, "cx": cx, "q": title, "num": "1"})
    request = urllib.request.Request(
        f"https://www.googleapis.com/customsearch/v1?{params}",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            data = json.load(response)
        total = data.get("searchInformation", {}).get("totalResults", "?")
        items = data.get("items") or []
        first = items[0].get("link") if items else "—"
        return f"HTTP 200 · totalResults={total} · erster Treffer={first}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = ""
        try:
            message = json.loads(body).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = body[:200]
        return f"HTTP {exc.code}: {message}"
    except Exception as exc:  # noqa: BLE001 - report any transport error verbatim
        return f"Fehler: {exc}"


def _diagnose(title: str, year: int | None, publisher: str | None) -> int:
    """Print a per-tier resolution diagnostic for *title*; used by the smoke test.

    Runs each tier independently so the output shows exactly which one produced a
    URL — and whether the Google tier is configured at all (a missing or
    misnamed ``GOOGLE_SEARCH_API_KEY`` / ``GOOGLE_SEARCH_CX`` shows as "not
    configured"). Makes no LLM call and writes nothing.
    """
    google_configured = bool(
        os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX")
    )
    print(f"Titel: {title!r}  (Jahr: {year or '-'}, Herausgeber: {publisher or '-'})")

    crossref = crossref_best(title, year)
    print(f"  Crossref : {crossref[0] if crossref else '— kein Treffer'}")
    openalex = openalex_best(title, year)
    print(f"  OpenAlex : {openalex[0] if openalex else '— kein Treffer'}")

    scope = "offenes Web" if os.environ.get("RESOLVE_OPEN_WEB") == "1" else "nur Allowlist-Domains"
    if os.environ.get("SEARXNG_URL"):
        searxng = searxng_best(title)
        print(f"  SearXNG  : {searxng[0] if searxng else '— kein Treffer'}  ({scope})")
    else:
        print("  SearXNG  : übersprungen — SEARXNG_URL nicht gesetzt")
    if not _ddgs_available():
        print("  DuckDuckGo : übersprungen — Bibliothek 'ddgs' nicht installiert")
    else:
        ddg = duckduckgo_best(title)
        if ddg:
            print(f"  DuckDuckGo : {ddg[0]}  ({scope})")
        else:
            print(
                "  DuckDuckGo : — kein Treffer (DuckDuckGo ist gelegentlich "
                f"raten-limitiert; ggf. erneut versuchen)  ({scope})"
            )

    if google_configured:
        google = google_best(title)
        print(f"  Google   : {google or '— kein Treffer'}  (konfiguriert)")
        # When configured but empty, surface the raw API status so a 403/429 vs a
        # true 0-results is distinguishable.
        if not google:
            print(f"  Google-Diagnose : {_google_diagnostic(title)}")
    else:
        print("  Google   : übersprungen — GOOGLE_SEARCH_API_KEY / GOOGLE_SEARCH_CX nicht gesetzt")

    resolved = resolve_url("", title=title, year=year, publisher=publisher)
    if resolved:
        print(f"=> aufgelöst via {resolved['via']}: {resolved['url']}")
    else:
        print("=> keine URL aufgelöst")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Diagnose source-URL resolution for a title (per-tier smoke test)."
    )
    parser.add_argument("--title", required=True, help="Report title to resolve.")
    parser.add_argument("--year", type=int, default=None, help="Publication year (optional).")
    parser.add_argument("--publisher", default=None, help="Publisher (optional).")
    args = parser.parse_args()
    return _diagnose(args.title.strip(), args.year, args.publisher)


if __name__ == "__main__":
    raise SystemExit(main())
