"""Tests for scripts/ingest_websearch.py (discovery web search, tiered trust).

No real network: every Google call is patched. These lock in the contract the
discovery lane relies on — search is open but trust is tiered, the tier is a
label (never a filter), every hit is a candidate web_resource, and the importer
is a no-op when the search secret is absent.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

import ingest_websearch as iws  # noqa: E402
from common import load_json  # noqa: E402

CONFIG = {
    "tiers": {
        "trusted": {"rank_boost": 0.15, "domains": ["oecd.org", "eric.ed.gov"]},
        "watch": {"rank_boost": 0.0, "domains": ["edutopia.org"]},
    },
    "open": {"rank_penalty": 0.2},
}

SECRET_ENV = {"GOOGLE_SEARCH_API_KEY": "k", "GOOGLE_SEARCH_CX": "c"}


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
        # notoecd.org must not match oecd.org -> stays open.
        self.assertEqual(iws.host_tier("https://notoecd.org/x", CONFIG)[0], "open")


class DetectYearTests(unittest.TestCase):
    def test_picks_most_recent_plausible_year(self):
        self.assertEqual(iws.detect_year("AI in schools 2019", "updated 2023"), (2023, False))

    def test_falls_back_to_current_year_provisional(self):
        year, provisional = iws.detect_year("AI literacy curriculum", "no date here")
        self.assertTrue(provisional)
        self.assertGreaterEqual(year, 2024)


class SearchResultsTests(unittest.TestCase):
    def test_no_secret_is_noop(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(iws.search_results("ai literacy", 10), [])

    def test_maps_items_and_skips_incomplete(self):
        payload = {"items": [
            {"title": "AI literacy in schools", "link": "https://oecd.org/a", "snippet": "s"},
            {"link": "https://x.org/b"},  # no title -> dropped
        ]}
        with mock.patch.dict("os.environ", SECRET_ENV), \
                mock.patch.object(iws, "_http_json", return_value=payload):
            results = iws.search_results("ai literacy", 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["link"], "https://oecd.org/a")


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
        payload = {"items": [
            {"title": "AI literacy curriculum for school students",
             "link": "https://oecd.org/ai", "snippet": "teaching AI literacy in the classroom"},
            {"title": "North Sea marine biology survey",
             "link": "https://blog.example/fish", "snippet": "fish populations"},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidates-websearch.json"
            with mock.patch.dict("os.environ", SECRET_ENV), \
                    mock.patch.object(iws, "_http_json", return_value=payload), \
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
        from common import filter_relevant_sources
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


if __name__ == "__main__":
    unittest.main()
