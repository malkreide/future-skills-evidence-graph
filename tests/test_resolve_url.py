"""Tests for scripts/resolve_source_url.py (Option B URL resolution).

No real network: every HTTP call is patched. These lock in the contract the
ingest-from-issue workflow relies on — a catalogue hit is only adopted above the
title-similarity threshold and within the year window, and resolution degrades
document → Crossref → OpenAlex → optional Google.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import resolve_source_url as rsu  # noqa: E402


class FindInTextTests(unittest.TestCase):
    def test_doi_wins(self):
        text = "Report. DOI: 10.1787/abc-123-en and a link https://example.org/x."
        self.assertEqual(rsu.find_in_text(text), "https://doi.org/10.1787/abc-123-en")

    def test_publisher_host_preferred(self):
        text = "See https://snf.ch/impressum and https://www.nfp77.ch/de/synthese here."
        self.assertEqual(rsu.find_in_text(text, "NFP77"), "https://www.nfp77.ch/de/synthese")

    def test_assets_ignored_and_none(self):
        self.assertIsNone(rsu.find_in_text("only https://x.org/logo.png here"))
        self.assertIsNone(rsu.find_in_text("no links at all"))


class TitleHelpersTests(unittest.TestCase):
    def test_guess_title_picks_cover_line(self):
        text = "NFP 77\nKI-Kompetenz und Bildung im digitalen Wandel\n1 Vorwort .... 4\n"
        self.assertEqual(rsu.guess_title(text), "KI-Kompetenz und Bildung im digitalen Wandel")

    def test_similarity_order_invariant(self):
        a = "AI literacy in primary education"
        b = "Primary education and AI literacy"
        self.assertGreaterEqual(rsu.title_similarity(a, b), 0.7)
        self.assertLess(rsu.title_similarity(a, "Marine biology of the North Sea"), 0.3)


class CatalogueTests(unittest.TestCase):
    CROSSREF = {
        "message": {
            "items": [
                {"title": ["Unrelated marine biology study"], "DOI": "10.2/x",
                 "issued": {"date-parts": [[2019]]}},
                {"title": ["AI literacy in primary education: a review"], "DOI": "10.1/ai",
                 "issued": {"date-parts": [[2023]]}},
            ]
        }
    }

    def test_crossref_best_above_threshold(self):
        with mock.patch.object(rsu, "_http_json", return_value=self.CROSSREF):
            hit = rsu.crossref_best("AI literacy in primary education a review", 2023)
        self.assertEqual(hit[0], "https://doi.org/10.1/ai")

    def test_crossref_year_mismatch_rejected(self):
        with mock.patch.object(rsu, "_http_json", return_value=self.CROSSREF):
            self.assertIsNone(
                rsu.crossref_best("AI literacy in primary education a review", 2010)
            )

    def test_crossref_low_similarity_rejected(self):
        with mock.patch.object(rsu, "_http_json", return_value=self.CROSSREF):
            self.assertIsNone(rsu.crossref_best("Completely different subject entirely", None))


class ResolveUrlTests(unittest.TestCase):
    def test_document_short_circuits(self):
        # A DOI in the text wins without any network call.
        with mock.patch.object(rsu, "_http_json", side_effect=AssertionError("no network")):
            result = rsu.resolve_url("finding ... DOI 10.1787/inline-doi-here ... end")
        self.assertEqual(result, {"url": "https://doi.org/10.1787/inline-doi-here", "via": "document"})

    def test_falls_through_to_openalex(self):
        oa = {"results": [{"display_name": "AI literacy in schools",
                           "doi": "https://doi.org/10.9/oa", "publication_year": 2022}]}
        with mock.patch.object(rsu, "crossref_best", return_value=None), mock.patch.object(
            rsu, "_http_json", return_value=oa
        ):
            result = rsu.resolve_url("no link here", title="AI literacy in schools", year=2022)
        self.assertEqual(result["via"], "openalex")
        self.assertEqual(result["url"], "https://doi.org/10.9/oa")

    def test_google_gated_by_env(self):
        # Without keys the Google tier is a no-op → overall None when catalogues miss.
        with mock.patch.object(rsu, "crossref_best", return_value=None), mock.patch.object(
            rsu, "openalex_best", return_value=None
        ), mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(rsu.resolve_url("no link", title="Some grey literature report"))

    def test_google_used_when_configured(self):
        with mock.patch.object(rsu, "crossref_best", return_value=None), mock.patch.object(
            rsu, "openalex_best", return_value=None
        ), mock.patch.dict(
            "os.environ", {"GOOGLE_SEARCH_API_KEY": "k", "GOOGLE_SEARCH_CX": "c"}, clear=True
        ), mock.patch.object(
            rsu, "_http_json", return_value={"items": [{"link": "https://oecd.org/report"}]}
        ):
            result = rsu.resolve_url("no link", title="Some grey literature report")
        self.assertEqual(result, {"url": "https://oecd.org/report", "via": "google"})


if __name__ == "__main__":
    unittest.main()
