"""Tests for the search-allowlist evidence audit (scripts/audit_domains.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_domains as ad  # noqa: E402
from resolve_source_url import CREDIBLE_DOMAINS  # noqa: E402


def _source(url, status, sid="s", title="t"):
    return {"id": sid, "title": title, "url": url, "status": status}


# A minimal tier config: one watch domain, an open penalty. Mirrors the real
# data/source_domains.json shape without depending on its exact contents.
CONFIG = {
    "tiers": {"watch": {"rank_boost": 0.0, "domains": ["watched.org"]}},
    "open": {"rank_penalty": 0.2},
}


class LedgerTests(unittest.TestCase):
    def test_aggregates_decisions_per_host_ignoring_www(self):
        # www. is stripped so the bare host and its www. form share one tally;
        # other subdomains stay distinct (matching host_tier's suffix semantics).
        sources = [
            _source("https://example.org/a", "reviewed"),
            _source("https://www.example.org/b", "rejected"),
            _source("https://example.org/c", "candidate"),
        ]
        ledger = ad.domain_ledger(sources)
        self.assertEqual(ledger["example.org"]["accepted"], 1)
        self.assertEqual(ledger["example.org"]["rejected"], 1)
        self.assertEqual(ledger["example.org"]["candidate"], 1)

    def test_skips_sources_without_a_url(self):
        self.assertEqual(ad.domain_ledger([_source("", "reviewed")]), {})


class ProposalTests(unittest.TestCase):
    def test_repeatedly_accepted_open_host_is_a_promotion_candidate(self):
        sources = [
            _source("https://good-pub.org/1", "reviewed", "a"),
            _source("https://good-pub.org/2", "reviewed", "b"),
            _source("https://good-pub.org/3", "reviewed", "c"),
        ]
        sheet = ad.build_worksheet(sources, CONFIG)
        hosts = [r["host"] for r in sheet["promotion_candidates"]]
        self.assertIn("good-pub.org", hosts)
        self.assertEqual(sheet["review_candidates"], [])

    def test_one_accept_is_below_threshold(self):
        sources = [_source("https://thin.org/1", "reviewed")]
        sheet = ad.build_worksheet(sources, CONFIG)
        self.assertEqual(sheet["promotion_candidates"], [])

    def test_low_accept_rate_is_not_promoted(self):
        # 2 accepts but a 0.4 rate (2 of 5 decided) is below the 0.6 floor.
        sources = [
            _source(f"https://mixed.org/{i}", "reviewed", f"a{i}") for i in range(2)
        ] + [_source(f"https://mixed.org/r{i}", "rejected", f"r{i}") for i in range(3)]
        sheet = ad.build_worksheet(sources, CONFIG)
        self.assertEqual(sheet["promotion_candidates"], [])

    def test_doi_resolver_is_infrastructure_never_promoted(self):
        # doi.org is a link resolver, not a publisher — even with many accepts.
        sources = [_source(f"https://doi.org/10.x/{i}", "reviewed", f"d{i}") for i in range(5)]
        sheet = ad.build_worksheet(sources, CONFIG)
        self.assertEqual(sheet["promotion_candidates"], [])
        row = next(r for r in sheet["domain_ledger"] if r["host"] == "doi.org")
        self.assertTrue(row["infrastructure"])

    def test_all_rejected_tiered_host_is_a_review_candidate(self):
        sources = [
            _source("https://watched.org/1", "rejected", "a"),
            _source("https://watched.org/2", "rejected", "b"),
        ]
        sheet = ad.build_worksheet(sources, CONFIG)
        hosts = [r["host"] for r in sheet["review_candidates"]]
        self.assertIn("watched.org", hosts)

    def test_tiered_host_with_an_accept_is_not_reviewed(self):
        sources = [
            _source("https://watched.org/1", "rejected", "a"),
            _source("https://watched.org/2", "rejected", "b"),
            _source("https://watched.org/3", "reviewed", "c"),
        ]
        sheet = ad.build_worksheet(sources, CONFIG)
        self.assertEqual(sheet["review_candidates"], [])


class InvariantTests(unittest.TestCase):
    def test_reports_credible_domains_missing_from_tiers(self):
        sheet = ad.build_worksheet([], {"tiers": {}, "open": {}})
        # With an empty tier config every credible domain is "not tiered".
        self.assertEqual(set(sheet["invariant_credible_not_tiered"]), set(CREDIBLE_DOMAINS))

    def test_shipped_config_has_no_drift(self):
        # The real config tiers every CREDIBLE_DOMAINS host (also guarded in
        # test_ingest_websearch); the audit must agree.
        config = ad.load_domain_tiers()
        sheet = ad.build_worksheet([], config)
        self.assertEqual(sheet["invariant_credible_not_tiered"], [])


if __name__ == "__main__":
    unittest.main()
