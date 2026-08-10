"""Tests for the label-reproducibility measurement (scripts/eval_agreement.py).

The script exists to tell a real baseline from a comfortable one, so the
properties that matter are the ones that keep it from flattering itself:

- a comparison whose two sides are not independent is never offered as a
  baseline, however perfectly the labels agree;
- a worksheet leaks neither the primary label nor its rationale, because
  a rater who sees the answer is not a second opinion;
- a non-blind worksheet is reported as non-independent rather than
  silently counted;
- an underpowered sample is named as such, using the same one-flip
  standard OPERATIONS.md applies to its own thresholds;
- Cohen's kappa is reported as undefined, not as 1.0, when the sample
  used a single category.

Nothing here touches the network.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_agreement as ea  # noqa: E402


class AgreementMathTests(unittest.TestCase):
    def test_kappa_is_undefined_when_only_one_category_was_used(self) -> None:
        # Ten identical judgments look like perfect agreement, but chance
        # agreement is also 1.0, so kappa says nothing. Reporting 1.0 here
        # would turn an unusable sample into a headline number.
        self.assertIsNone(ea.cohens_kappa([(True, True)] * 10))
        # With both categories present it is defined again.
        self.assertIsNotNone(ea.cohens_kappa([(True, True)] * 5 + [(False, False)] * 5))

    def test_kappa_discounts_agreement_that_chance_explains(self) -> None:
        skewed = [(True, True)] * 9 + [(True, False)]
        balanced = [(True, True)] * 5 + [(False, False)] * 4 + [(True, False)]
        # Same 0.9 raw agreement, but on the skewed sample almost all of it
        # is explained by both sides defaulting to the same label.
        self.assertLess(ea.cohens_kappa(skewed), ea.cohens_kappa(balanced))

    def test_wilson_interval_does_not_collapse_at_a_perfect_score(self) -> None:
        low, high = ea.wilson_interval(16, 16)
        self.assertEqual(high, 1.0)
        # A normal approximation would give [1.0, 1.0] and imply certainty
        # that 16 observations cannot support.
        self.assertLess(low, 0.9)
        self.assertGreater(low, 0.5)
        # More evidence must narrow it.
        self.assertGreater(ea.wilson_interval(160, 160)[0], low)


class BaselineVerdictTests(unittest.TestCase):
    def _comparison(self, n: int, independent: bool) -> ea.Comparison:
        pairs = [(True, True)] * (n // 2) + [(False, False)] * (n - n // 2)
        return ea.Comparison("t", "relevant", pairs, independent, "test")

    def test_perfect_agreement_is_not_a_baseline_when_provenance_is_unverified(self) -> None:
        rigged = self._comparison(200, independent=False)
        self.assertEqual(rigged.agreement, 1.0)
        self.assertFalse(rigged.gate_ready())
        self.assertIn("PROVENANCE UNVERIFIED", "\n".join(rigged.report()))

    def test_underpowered_sample_is_named_with_the_missing_count(self) -> None:
        small = self._comparison(30, independent=True)
        self.assertFalse(small.gate_ready())
        report = "\n".join(small.report())
        self.assertIn("underpowered", report)
        self.assertIn(f"{ea.MIN_N_FOR_GATE - 30} more", report)

    def test_independent_and_powered_sample_is_usable(self) -> None:
        big = self._comparison(ea.MIN_N_FOR_GATE, independent=True)
        self.assertTrue(big.gate_ready())
        self.assertIn("usable as a baseline", "\n".join(big.report()))

    def test_one_flip_threshold_matches_the_operations_standard(self) -> None:
        # OPERATIONS.md gates abstention because one flip moves it by 0.025
        # and refuses to gate link precision at 0.071. MIN_N_FOR_GATE has to
        # be the sample size where a flip reaches that same 0.025.
        self.assertLessEqual(1 / ea.MIN_N_FOR_GATE, ea.MAX_ONE_FLIP_FOR_GATE)
        self.assertGreater(1 / (ea.MIN_N_FOR_GATE - 1), ea.MAX_ONE_FLIP_FOR_GATE)


class WorksheetTests(unittest.TestCase):
    def test_worksheet_withholds_the_primary_label_and_its_rationale(self) -> None:
        for set_name, answer_keys in (
            ("relevance", ("relevant", "note")),
            ("claim_prefill", ("gold",)),
        ):
            with self.subTest(set_name):
                worksheet = ea.build_worksheet(set_name)
                items = worksheet["labels"]
                self.assertGreater(len(items), 0)
                for item in items:
                    for field in ea.SECOND_RATER_FIELDS[set_name]:
                        # The field to fill in exists but is empty.
                        self.assertIsNone(item[field])
                    for leaked in answer_keys:
                        if leaked in ea.SECOND_RATER_FIELDS[set_name]:
                            continue
                        self.assertNotIn(leaked, item)

    def test_worksheet_carries_the_inputs_a_rater_needs(self) -> None:
        relevance = ea.build_worksheet("relevance")["labels"][0]
        self.assertTrue(relevance["title"])
        self.assertTrue(relevance["abstract"])
        prefill = ea.build_worksheet("claim_prefill")["labels"][0]
        self.assertTrue(prefill["statement"])
        self.assertTrue(prefill["source_type"])

    def test_the_rubric_is_read_from_the_methodology_doc(self) -> None:
        # Restating the anchors in code would let the worksheet drift from the
        # document. Two raters on two rulebooks disagree in a way that looks
        # like rater variance and is not.
        rubric = ea.anchor_rubric()
        self.assertEqual(set(rubric), set(ea.appraisal.CERTAINTY_VALUES))
        doc = ea.ANCHOR_DOC.read_text(encoding="utf-8")
        for level, definition in rubric.items():
            self.assertGreater(len(definition), 40, level)
            self.assertIn(definition, doc, level)

    def test_a_prefill_worksheet_carries_the_rubric(self) -> None:
        worksheet = ea.build_worksheet("claim_prefill")
        self.assertEqual(
            set(worksheet["rubrik_evidence_certainty"]), set(ea.appraisal.CERTAINTY_VALUES)
        )
        self.assertIn("rubrik_age_range_explicit", worksheet)
        # The relevance worksheet judges a boolean and needs no certainty rubric.
        self.assertNotIn("rubrik_evidence_certainty", ea.build_worksheet("relevance"))

    def test_an_unreadable_rubric_stops_the_worksheet(self) -> None:
        # Shipping a worksheet with a silently empty rubric is worse than
        # shipping none: the rater would invent their own scale.
        import tempfile
        from pathlib import Path as _Path

        original = ea.ANCHOR_DOC
        try:
            with tempfile.TemporaryDirectory() as tmp:
                empty = _Path(tmp) / "anker.md"
                empty.write_text("## Anker: `evidence_certainty`\nkeine Tabelle\n", encoding="utf-8")
                ea.ANCHOR_DOC = empty
                with self.assertRaises(SystemExit):
                    ea.anchor_rubric()
                with self.assertRaises(SystemExit):
                    ea.build_worksheet("claim_prefill")
        finally:
            ea.ANCHOR_DOC = original

    def test_worksheet_keys_match_the_primary_labels(self) -> None:
        # A key mismatch would silently compare nothing and report n=0 as
        # if the rater had skipped every item.
        for set_name in ea.SECOND_RATER_FIELDS:
            with self.subTest(set_name):
                keys = {item["key"] for item in ea.build_worksheet(set_name)["labels"]}
                self.assertEqual(keys, set(ea.primary_labels(set_name)))


class SecondRaterScoringTests(unittest.TestCase):
    def _write(self, tmp: Path, blind: bool, flips: int) -> Path:
        worksheet = ea.build_worksheet("claim_prefill")
        gold = ea.primary_labels("claim_prefill")
        rotate = {"low": "moderate", "moderate": "strong", "strong": "low"}
        for index, item in enumerate(worksheet["labels"]):
            for field in ea.SECOND_RATER_FIELDS["claim_prefill"]:
                item[field] = gold[item["key"]].get(field)
            answer = gold[item["key"]]["evidence_strength"]
            item["evidence_strength"] = rotate[answer] if index < flips else answer
        worksheet["protocol"].update(rater="tester", labeled_at="2026-08-09", blind=blind)
        path = tmp / "second_rater.json"
        path.write_text(json.dumps(worksheet), encoding="utf-8")
        return path

    def test_disagreements_are_counted(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), blind=True, flips=5)
            strength = next(
                comparison
                for comparison in ea.second_rater_comparisons(path)
                if comparison.field == "evidence_strength"
            )
            self.assertEqual(strength.n, 50)
            self.assertEqual(strength.agreements, 45)
            self.assertTrue(strength.gate_ready())

    def test_a_non_blind_pass_is_not_treated_as_independent(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), blind=False, flips=0)
            for comparison in ea.second_rater_comparisons(path):
                self.assertEqual(comparison.agreement, 1.0)
                # Perfect agreement, and still not a baseline: the rater
                # could see the answer.
                self.assertFalse(comparison.gate_ready())

    def test_unknown_source_set_is_rejected(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"protocol": {"source_set": "nope"}}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                ea.second_rater_comparisons(path)


class RepositoryStateTests(unittest.TestCase):
    def test_the_relevance_overlap_is_reported_as_unverified(self) -> None:
        # The only comparison computable today. It agrees perfectly and must
        # still not count: see docs/eval-baseline.md for the provenance
        # evidence. If a genuinely independent second pass ever replaces it,
        # this test is the place that has to be revisited deliberately.
        overlap = ea.relevance_overlap()
        self.assertGreater(overlap.n, 0)
        self.assertFalse(overlap.independent)
        self.assertFalse(overlap.gate_ready())
        # The verdict has to name provenance, not sample size. Asserting only
        # that gate_ready() is False would pass on the 16 items even if the
        # independence check were removed, since they are underpowered anyway
        # -- the assertion would hold for the wrong reason.
        report = "\n".join(overlap.report())
        self.assertIn("PROVENANCE UNVERIFIED", report)
        self.assertNotIn("underpowered", report)


if __name__ == "__main__":
    unittest.main()
