"""Tests for the review funnel shipped in index.json (scripts/review_funnel.py).

The funnel is the dashboard's answer to "how much of this has a person
actually checked?". Its numbers are only worth showing if the stages
partition the records exactly -- a record counted twice or not at all would
make the backlog or the rejection rate read wrong without any error.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import load_records  # noqa: E402
from review_funnel import review_funnel  # noqa: E402


def source(source_id: str, status: str) -> dict:
    return {"id": source_id, "status": status}


def claim(claim_id: str, status: str, source_ids: list[str]) -> dict:
    return {"id": claim_id, "status": status, "source_ids": source_ids}


def skill(skill_id: str, status: str, supporting: list[str], contradicting: list[str] | None = None) -> dict:
    return {
        "id": skill_id,
        "status": status,
        "supporting_claim_ids": supporting,
        "contradicting_claim_ids": contradicting or [],
    }


class FunnelStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [
            source("s-used", "reviewed"),
            source("s-only-rejected-claim", "reviewed"),
            source("s-rejected", "rejected"),
            source("s-open", "candidate"),
            source("s-behind-deprecated", "reviewed"),
            source("s-contra", "reviewed"),
        ]
        self.claims = [
            claim("c-used", "reviewed", ["s-used"]),
            claim("c-rejected", "rejected", ["s-only-rejected-claim"]),
            claim("c-open", "candidate", ["s-open"]),
            claim("c-deprecated-only", "reviewed", ["s-behind-deprecated"]),
            claim("c-contra", "reviewed", ["s-contra"]),
        ]
        self.skills = [
            skill("k-active", "active", ["c-used"], ["c-contra"]),
            skill("k-old", "deprecated", ["c-deprecated-only"]),
            skill("k-new", "candidate", ["c-open"]),
        ]
        self.funnel = review_funnel(self.sources, self.claims, self.skills)

    def test_rejected_and_open_are_counted_apart(self) -> None:
        # The whole point of the funnel: a rejection is a decision, an open
        # candidate is not. Merging them would hide either the backlog or the
        # filter.
        claims = self.funnel["claims"]
        self.assertEqual(claims["rejected"], 1)
        self.assertEqual(claims["open"], 1)
        self.assertEqual(claims["decided"], 4)
        sources = self.funnel["sources"]
        self.assertEqual(sources["rejected"], 1)
        self.assertEqual(sources["open"], 1)
        self.assertEqual(sources["decided"], 5)

    def test_only_active_skills_carry_claims_into_the_catalog(self) -> None:
        # c-deprecated-only is reviewed but backs only a deprecated skill; it
        # is accepted, not in the catalogue.
        self.assertEqual(self.funnel["claims"]["accepted"], 3)
        self.assertEqual(self.funnel["claims"]["in_catalog"], 2)

    def test_contradicting_claims_count_as_in_catalog(self) -> None:
        # Counter-evidence lowers a score, so it is part of what the
        # catalogue rests on, not an extra.
        funnel = review_funnel(
            self.sources, self.claims, [skill("k-active", "active", ["c-used"])]
        )
        self.assertEqual(funnel["claims"]["in_catalog"], 1)
        self.assertEqual(self.funnel["claims"]["in_catalog"], 2)

    def test_a_source_reaches_the_catalog_only_through_an_accepted_claim(self) -> None:
        # s-only-rejected-claim is itself reviewed, but its only claim was
        # rejected; s-open sits behind a candidate claim of a candidate skill.
        self.assertEqual(self.funnel["sources"]["accepted"], 4)
        self.assertEqual(self.funnel["sources"]["in_catalog"], 2)

    def test_a_candidate_claim_listed_on_an_active_skill_is_not_in_catalog(self) -> None:
        # validate_data.py forbids this state; the funnel must still not count
        # an unreviewed claim as vouched for if it ever slips through.
        # The candidate claim cites a REVIEWED source, so only the claim's own
        # status can keep that source out of the catalogue count.
        claims = [*self.claims, claim("c-open-on-reviewed", "candidate", ["s-used"])]
        funnel = review_funnel(
            self.sources, claims, [skill("k-active", "active", ["c-open-on-reviewed"])]
        )
        self.assertEqual(funnel["claims"]["in_catalog"], 0)
        self.assertEqual(funnel["sources"]["in_catalog"], 0)

    def test_skill_statuses_are_counted(self) -> None:
        self.assertEqual(self.funnel["skills"], {"active": 1, "candidate": 1, "deprecated": 1})

    def test_an_unknown_status_fails_loudly(self) -> None:
        # Dropping it would make captured != open + decided without a word.
        with self.assertRaisesRegex(ValueError, "unknown status 'archived'"):
            review_funnel([source("s-x", "archived")], [], [])
        with self.assertRaisesRegex(ValueError, "unknown status 'retired'"):
            review_funnel([], [], [skill("k-x", "retired", [])])


class FunnelOnCatalogTests(unittest.TestCase):
    def test_stages_partition_the_shipped_records(self) -> None:
        import build_site

        funnel = build_site.build_index()["review_funnel"]
        for kind in ("sources", "claims"):
            with self.subTest(kind):
                stages = funnel[kind]
                self.assertEqual(stages["captured"], len(load_records(kind)))
                self.assertEqual(stages["captured"], stages["open"] + stages["decided"])
                self.assertEqual(stages["decided"], stages["accepted"] + stages["rejected"])
                self.assertLessEqual(stages["in_catalog"], stages["accepted"])
        self.assertEqual(sum(funnel["skills"].values()), len(load_records("skills")))

    def test_the_dashboard_reads_the_funnel(self) -> None:
        # Shipping the counts without rendering them is dead weight in the
        # one file every visitor downloads whole.
        app_js = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"payload\.review_funnel\b", app_js), "app.js never reads review_funnel")
        self.assertTrue(re.search(r'id="reviewFunnel"', index_html), "no #reviewFunnel in index.html")


if __name__ == "__main__":
    unittest.main()
