"""Tests for scripts/ingest_websearch.py (discovery web search, tiered trust).

No real network: every backend call is patched or injected. These lock in the
contract the discovery lane relies on — open search across keyless backends
(SearXNG + DuckDuckGo, with optional Google), tiered trust as a label (never a
filter), every hit a candidate web_resource, and a no-op when no backend exists.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

import ingest_websearch as iws  # noqa: E402
from common import filter_relevant_sources, load_json  # noqa: E402
from resolve_source_url import CREDIBLE_DOMAINS  # noqa: E402

CONFIG = {
    "tiers": {
        "trusted": {"rank_boost": 0.15, "domains": ["oecd.org", "eric.ed.gov"]},
        "watch": {"rank_boost": 0.0, "domains": ["edutopia.org"]},
    },
    "open": {"rank_penalty": 0.2},
}

GOOGLE_ENV = {"GOOGLE_SEARCH_API_KEY": "k", "GOOGLE_SEARCH_CX": "c"}


def _fake_ddgs(hits):
    """Build a stand-in ``ddgs`` module whose DDGS().text() yields *hits*."""
    module = types.ModuleType("ddgs")

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, max_results):
            return list(hits)

    module.DDGS = FakeDDGS
    return module


class HostTierTests(unittest.TestCase):
    def test_exact_and_subdomain_match_trusted(self):
        self.assertEqual(iws.host_tier("https://www.oecd.org/x", CONFIG), ("trusted", 0.15))
        self.assertEqual(iws.host_tier("https://read.oecd.org/x", CONFIG), ("trusted", 0.15))
        self.assertEqual(iws.host_tier("https://eric.ed.gov/?id=1", CONFIG), ("trusted", 0.15))

    def test_watch_tier_zero_delta(self):
        self.assertEqual(iws.host_tier("https://www.edutopia.org/a", CONFIG), ("watch", 0.0))

    def test_unlisted_host_is_open_with_penalty(self):
        self.assertEqual(iws.host_tier("https://random-blog.example/a", CONFIG), ("open", -0.2))

    def test_sibling_domain_is_not_a_suffix_match(self):
        self.assertEqual(iws.host_tier("https://notoecd.org/x", CONFIG)[0], "open")


class DetectYearTests(unittest.TestCase):
    def test_picks_most_recent_plausible_year(self):
        self.assertEqual(iws.detect_year("AI in schools 2019", "updated 2023"), (2023, False))

    def test_falls_back_to_current_year_provisional(self):
        year, provisional = iws.detect_year("AI literacy curriculum", "no date here")
        self.assertTrue(provisional)
        self.assertGreaterEqual(year, 2024)


class BackendTests(unittest.TestCase):
    def test_searxng_maps_and_is_noop_without_url(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(iws.searxng_search("q", 10), [])
        payload = {"results": [
            {"title": "AI literacy", "url": "https://oecd.org/a", "content": "snippet"},
            {"url": "https://x.org/b"},  # no title -> dropped
        ]}
        with mock.patch.dict("os.environ", {"SEARXNG_URL": "https://searx.example"}), \
                mock.patch.object(iws, "_http_json", return_value=payload):
            results = iws.searxng_search("q", 10)
        self.assertEqual(results, [{"title": "AI literacy", "link": "https://oecd.org/a", "snippet": "snippet"}])

    def test_google_maps_and_is_noop_without_secret(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(iws.google_search("q", 10), [])
        payload = {"items": [{"title": "T", "link": "https://oecd.org/a", "snippet": "s"}]}
        with mock.patch.dict("os.environ", GOOGLE_ENV), \
                mock.patch.object(iws, "_http_json", return_value=payload):
            self.assertEqual(iws.google_search("q", 10),
                             [{"title": "T", "link": "https://oecd.org/a", "snippet": "s"}])

    def test_duckduckgo_uses_ddgs_library(self):
        hits = [{"title": "AI literacy", "href": "https://oecd.org/a", "body": "snippet"}]
        with mock.patch.dict(sys.modules, {"ddgs": _fake_ddgs(hits)}):
            results = iws.duckduckgo_search("q", 5)
        self.assertEqual(results, [{"title": "AI literacy", "link": "https://oecd.org/a", "snippet": "snippet"}])

    def test_duckduckgo_noop_without_library(self):
        # Force the import to fail regardless of whether ddgs is installed.
        with mock.patch.dict(sys.modules, {"ddgs": None, "duckduckgo_search": None}):
            self.assertEqual(iws.duckduckgo_search("q", 5), [])


class SearchResultsTests(unittest.TestCase):
    def test_no_backend_is_noop(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(iws, "_ddgs_available", return_value=False):
            self.assertFalse(iws.search_backends_available())
            self.assertEqual(iws.search_results("q", 10), [])

    def test_aggregates_and_dedupes_by_url_across_backends(self):
        with mock.patch.object(iws, "searxng_search",
                               return_value=[{"title": "A", "link": "https://oecd.org/a", "snippet": ""}]), \
                mock.patch.object(iws, "duckduckgo_search",
                                  return_value=[{"title": "A2", "link": "https://OECD.org/a", "snippet": ""},
                                                {"title": "B", "link": "https://x.org/b", "snippet": ""}]), \
                mock.patch.object(iws, "google_search", return_value=[]):
            results = iws.search_results("q", 10)
        # oecd.org/a appears in two backends (case-differing) -> deduped to one.
        self.assertEqual([r["link"] for r in results], ["https://oecd.org/a", "https://x.org/b"])


class BuildSourceTests(unittest.TestCase):
    def test_candidate_web_resource_with_tier_provenance(self):
        result = {
            "title": "AI literacy curriculum for primary school students 2023",
            "link": "https://www.oecd.org/education/ai-literacy",
            "snippet": "A framework for teaching AI literacy to school children.",
        }
        source = iws.build_source(result, "ai literacy curriculum", CONFIG)
        self.assertEqual(source["source_type"], "web_resource")
        self.assertEqual(source["status"], "candidate")
        self.assertEqual(source["year"], 2023)
        self.assertEqual(source["publisher"], "oecd.org")
        prov = source["assist"]["provenance"]
        self.assertEqual(prov["via"], "websearch")
        self.assertEqual(prov["domain_tier"], "trusted")
        self.assertEqual(prov["rank_delta"], 0.15)
        self.assertEqual(prov["query"], "ai literacy curriculum")
        self.assertNotIn("year_provisional", prov)

    def test_open_hit_marks_provisional_year(self):
        result = {"title": "Some AI literacy blog post for classrooms", "link": "https://blog.example/x", "snippet": ""}
        source = iws.build_source(result, "q", CONFIG)
        self.assertEqual(source["assist"]["provenance"]["domain_tier"], "open")
        self.assertTrue(source["assist"]["provenance"]["year_provisional"])


class ImportQueryTests(unittest.TestCase):
    def test_relevant_hits_become_candidates_irrelevant_dropped(self):
        hits = [
            {"title": "AI literacy curriculum for school students",
             "link": "https://oecd.org/ai", "snippet": "teaching AI literacy in the classroom"},
            {"title": "North Sea marine biology survey",
             "link": "https://blog.example/fish", "snippet": "fish populations"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidates-websearch.json"
            with mock.patch.object(iws, "search_results", return_value=hits), \
                    mock.patch("common.load_records", return_value=[]):
                appended, relevant, found = iws.import_query("ai literacy", 10, CONFIG, out)
            self.assertEqual(found, 2)
            self.assertEqual(relevant, 1)  # marine biology filtered as off-scope
            self.assertEqual(appended, 1)
            written = load_json(out)
            self.assertEqual(written[0]["assist"]["provenance"]["domain_tier"], "trusted")

    def test_candidate_validates_against_source_schema(self):
        schema = load_json(ROOT / "schemas" / "source.schema.json")
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        result = {"title": "AI literacy curriculum for primary school students",
                  "link": "https://www.oecd.org/education/ai", "snippet": "teaching AI literacy to children"}
        source = iws.build_source(result, "q", CONFIG)
        # filter_relevant_sources fills topics/relevance_score/audience authoritatively.
        [enriched] = filter_relevant_sources([source])
        errors = sorted(validator.iter_errors(enriched), key=lambda e: list(e.absolute_path))
        self.assertEqual(errors, [], msg="; ".join(e.message for e in errors))


class LoadQueriesTests(unittest.TestCase):
    def test_dedupes_preserving_order(self):
        args = mock.Mock(query=["a", "b", "a"], manifest=None)
        self.assertEqual(iws.load_queries(args), ["a", "b"])

    def test_no_queries_raises(self):
        args = mock.Mock(query=None, manifest=None)
        with self.assertRaises(ValueError):
            iws.load_queries(args)


class DomainConfigTests(unittest.TestCase):
    def test_shipped_config_loads_and_tiers_are_disjoint(self):
        config = iws.load_domain_tiers()
        trusted = set(config["tiers"]["trusted"]["domains"])
        watch = set(config["tiers"]["watch"]["domains"])
        self.assertTrue(trusted and watch)
        self.assertEqual(trusted & watch, set(), "a domain must not sit in two tiers")

    def test_trusted_plus_watch_covers_credible_domains(self):
        # Keep the discovery tiers a superset of the URL resolver's allowlist, so a
        # publisher credible enough to resolve a URL never lands in 'open' here.
        config = iws.load_domain_tiers()
        listed = set(config["tiers"]["trusted"]["domains"]) | set(config["tiers"]["watch"]["domains"])
        missing = CREDIBLE_DOMAINS - listed
        self.assertEqual(missing, set(), f"CREDIBLE_DOMAINS not tiered: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
