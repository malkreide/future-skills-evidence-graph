"""The probe must compare orderings, and nothing else.

Its only job is to answer whether `sort=publication_year:desc` changes which
papers come back. That answer is worthless if the probe varies anything besides
the ordering, or if it drifts away from the sort the importer actually sends.
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

import ingest_openalex  # noqa: E402
import probe_openalex_ranking as probe  # noqa: E402


class ProbeIsolatesTheOrderingTest(unittest.TestCase):
    def captured_params(self) -> list[dict[str, str]]:
        """Every request the probe would send for one comparison."""
        seen: list[dict[str, str]] = []

        def fake_fetch(query, limit, sort, mailto):
            params = {"search": query, "per-page": str(limit)}
            if sort:
                params["sort"] = sort
            seen.append(params)
            return [f"Paper {sort or 'relevance'} {i}" for i in range(limit)]

        with mock.patch.object(probe, "fetch_raw", side_effect=fake_fetch):
            probe.compare("a query", 3, None)
        return seen

    def test_only_the_sort_differs_between_the_two_requests(self) -> None:
        first, second = self.captured_params()

        self.assertEqual(first["search"], second["search"])
        self.assertEqual(first["per-page"], second["per-page"])
        self.assertIn("sort", first)
        self.assertNotIn("sort", second)

    def test_the_probe_compares_date_sorting_against_the_importer(self) -> None:
        """One side is the ordering we left; the other is whatever ships now."""
        first, _ = self.captured_params()
        self.assertEqual(first["sort"], probe.LEGACY_SORT)
        self.assertEqual(probe.LEGACY_SORT, "publication_year:desc")

    def test_the_importer_no_longer_sorts_at_all(self) -> None:
        """The whole point: `search` must be free to rank by relevance.

        Measured across four queries at ten results: date-sorting and relevance
        ranking shared zero works. A regression here produces plausible-looking
        results and no error, so it needs a test rather than a reviewer's eye.
        """
        self.assertIsNone(ingest_openalex.SEARCH_SORT)

    def test_recency_survives_as_a_filter(self) -> None:
        """Removing the sort must not silently drop the intent behind it."""
        captured: dict[str, str] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"results": []}'

        def fake_urlopen(url, timeout=None):
            captured["url"] = url
            return FakeResponse()

        with mock.patch.object(ingest_openalex.urllib.request, "urlopen", fake_urlopen), \
             mock.patch.object(ingest_openalex.json, "load", lambda _: {"results": []}):
            ingest_openalex.fetch("q", 5)

        self.assertNotIn("sort=", captured["url"], "no ordering may override relevance")
        self.assertIn(
            f"publication_year%3A%3E{ingest_openalex.earliest_publication_year() - 1}",
            captured["url"],
            "recency must still constrain the candidate set, just not its order",
        )


class ProbeOverlapTest(unittest.TestCase):
    def test_identical_result_sets_report_full_overlap(self) -> None:
        with mock.patch.object(probe, "fetch_raw", side_effect=lambda *a: ["A", "B"]):
            result = probe.compare("q", 2, None)

        self.assertEqual(result["overlap"], 2)
        self.assertEqual(result["overlap_share"], 1.0)

    def test_disjoint_result_sets_report_none(self) -> None:
        answers = iter([["A", "B"], ["C", "D"]])
        with mock.patch.object(probe, "fetch_raw", side_effect=lambda *a: next(answers)):
            result = probe.compare("q", 2, None)

        self.assertEqual(result["overlap"], 0)
        self.assertEqual(result["overlap_share"], 0.0)

    def test_blank_titles_are_not_counted_as_a_shared_result(self) -> None:
        """Missing display_names would otherwise inflate the overlap to 'agree'."""
        answers = iter([["", "A"], ["", "B"]])
        with mock.patch.object(probe, "fetch_raw", side_effect=lambda *a: next(answers)):
            result = probe.compare("q", 2, None)

        self.assertEqual(result["overlap"], 0)


if __name__ == "__main__":
    unittest.main()
