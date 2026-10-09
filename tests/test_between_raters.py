"""Comparing several second raters with each other, not only with the stored labels.

The question this answers is the one --second-rater cannot: when people
disagree with the stored appraisal, is the stored reading the outlier, or
does the rubric fail to settle the case for anyone? Each test pins one part
of the answer the report gives, and the Fleiss kappa underneath it is
checked against the published example rather than against a number worked
out here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import eval_agreement as ea  # noqa: E402

CALIBRATION = ROOT / "eval" / "claim_prefill_calibration.json"


class FleissKappaTests(unittest.TestCase):
    def test_the_published_example(self) -> None:
        # Fleiss (1971), as reproduced in most references: 10 items, 14
        # raters, 5 categories, kappa 0.210. An external value, so the
        # test cannot simply encode the implementation's own arithmetic.
        table = [
            [0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0],
            [2, 2, 8, 1, 1], [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2],
            [6, 5, 2, 1, 0], [0, 2, 2, 3, 7],
        ]
        ratings = [
            [category for category, count in enumerate(row) for _ in range(count)]
            for row in table
        ]
        self.assertAlmostEqual(ea.fleiss_kappa(ratings), 0.210, places=3)

    def test_perfect_agreement_over_several_categories_is_one(self) -> None:
        self.assertEqual(ea.fleiss_kappa([["a", "a", "a"], ["b", "b", "b"]]), 1.0)

    def test_a_single_category_is_undefined_not_perfect(self) -> None:
        self.assertIsNone(ea.fleiss_kappa([["a", "a"], ["a", "a"]]))

    def test_null_is_a_category(self) -> None:
        # Inside a worked item, "no answer is possible" is a judgement --
        # the same rule the pairwise report follows.
        self.assertEqual(ea.fleiss_kappa([[None, None], ["a", "a"]]), 1.0)

    def test_ragged_or_empty_input_is_undefined(self) -> None:
        self.assertIsNone(ea.fleiss_kappa([]))
        self.assertIsNone(ea.fleiss_kappa([["a", "a"], ["a"]]))
        self.assertIsNone(ea.fleiss_kappa([["a"], ["b"]]))


class _Passes(unittest.TestCase):
    """Three completed calibration passes that copy the stored labels."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.primary = ea.primary_by_rater_key("claim_prefill")
        self.keys = [
            item["key"] for item in json.loads(CALIBRATION.read_text("utf-8"))["labels"]
        ]
        self.real = {ea.rater_key("claim_prefill", k): k for k in ea.primary_labels("claim_prefill")}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sheet(self, rater: str, **protocol) -> dict:
        sheet = json.loads(CALIBRATION.read_text("utf-8"))
        for item in sheet["labels"]:
            for field in sheet["protocol"]["rated_fields"]:
                item[field] = self.primary[item["key"]].get(field)
        sheet["protocol"].update({"rater": rater, "labeled_at": "2026-10-15", "blind": True, **protocol})
        return sheet

    def item(self, sheet: dict, index: int) -> dict:
        return {i["key"]: i for i in sheet["labels"]}[self.keys[index]]

    def write(self, *sheets: dict) -> list[Path]:
        paths = []
        for n, sheet in enumerate(sheets):
            path = self.tmp / f"pass{n}.json"
            path.write_text(json.dumps(sheet), encoding="utf-8")
            paths.append(path)
        return paths

    def report(self, *sheets: dict) -> str:
        return "\n".join(ea.between_raters_report(self.write(*sheets)))

    def section(self, text: str, field: str) -> str:
        start = text.index(f"## {field}  ")
        return text[start : text.index("\n## ", start + 1)]


class SortingTests(_Passes):
    def test_a_stored_outlier_is_named_as_such(self) -> None:
        # All three second raters agree with each other and not with the
        # stored label: the stored reading is the odd one out.
        sheets = [self.sheet(n) for n in ("A", "B", "C")]
        for sheet in sheets:
            self.item(sheet, 1)["evidence_certainty"] = "very_low"
        part = self.section(self.report(*sheets), "evidence_certainty")
        self.assertIn("1 where only the stored label differs, 0 where the second raters split", part)
        outlier = part[part.index("only the stored label differs (") :]
        self.assertIn(self.real[self.keys[1]], outlier)

    def test_a_split_among_second_raters_is_named_as_such(self) -> None:
        # One agrees with the stored label, two do not, and those two do
        # not agree either: nobody's reading settles it.
        sheets = [self.sheet(n) for n in ("A", "B", "C")]
        self.item(sheets[1], 2)["claim_type"] = "association"
        self.item(sheets[2], 2)["claim_type"] = "descriptive"
        part = self.section(self.report(*sheets), "claim_type")
        self.assertIn("0 where only the stored label differs, 1 where the second raters split", part)
        split = part[part.index("second raters split (") :]
        self.assertIn(self.real[self.keys[2]], split)
        self.assertIn("B=association", split)
        self.assertIn("C=descriptive", split)

    def test_a_majority_against_the_stored_label_is_still_a_split(self) -> None:
        # Two of three second raters agree with each other, the third sides
        # with the stored label. The second raters do not agree among
        # themselves, so this is a split, not a stored outlier -- calling
        # it an outlier would blame the stored reading for what is really
        # a case the rubric leaves open.
        sheets = [self.sheet(n) for n in ("A", "B", "C")]
        for sheet in sheets[:2]:
            self.item(sheet, 5)["effect_direction"] = "mixed"
        part = self.section(self.report(*sheets), "effect_direction")
        self.assertIn("0 where only the stored label differs, 1 where the second raters split", part)

    def test_two_raters_against_the_stored_label_are_an_outlier_not_a_split(self) -> None:
        # The boundary: two second raters, same answer, both differ from
        # the stored one. That is the outlier case even with two only.
        sheets = [self.sheet(n) for n in ("A", "B")]
        for sheet in sheets:
            self.item(sheet, 3)["study_design"] = "other"
        part = self.section(self.report(*sheets), "study_design")
        self.assertIn("1 where only the stored label differs, 0 where the second raters split", part)

    def test_unanimous_items_are_counted_not_listed(self) -> None:
        part = self.section(self.report(self.sheet("A"), self.sheet("B")), "claim_type")
        self.assertIn("10 unanimous, 0 where only the stored label differs, 0 where", part)
        self.assertNotIn("prefill-", part)


class GroupStatisticTests(_Passes):
    def test_fleiss_is_reported_with_and_without_the_stored_label(self) -> None:
        # Second raters in perfect agreement, stored label off on one item:
        # the two kappas must differ, which is the whole point of showing both.
        sheets = [self.sheet(n) for n in ("A", "B", "C")]
        for sheet in sheets:
            self.item(sheet, 1)["evidence_certainty"] = "very_low"
        part = self.section(self.report(*sheets), "evidence_certainty")
        self.assertIn("fleiss' kappa, second raters only (3): 1.000", part)
        everyone = part.split("fleiss' kappa, all 4 raters:")[1].split("\n")[0].strip()
        self.assertLess(float(everyone), 1.0)

    def test_every_pair_is_compared_including_the_stored_label(self) -> None:
        part = self.section(self.report(*[self.sheet(n) for n in ("A", "B", "C")]), "claim_type")
        pairs = [line for line in part.splitlines() if " ~ " in line]
        self.assertEqual(len(pairs), 6)  # 4 raters -> 6 pairs
        self.assertTrue(any(line.strip().startswith("A ~ B") for line in pairs))
        self.assertTrue(any(line.strip().startswith(f"{ea.PRIMARY_NAME} ~ C") for line in pairs))

    def test_the_summary_separates_among_from_against(self) -> None:
        sheets = [self.sheet(n) for n in ("A", "B")]
        for sheet in sheets:
            self.item(sheet, 1)["evidence_certainty"] = "very_low"
        text = self.report(*sheets)
        summary = text[text.index("## Summary") :]
        self.assertIn(
            "- evidence_certainty: second raters among themselves 1.000, "
            "against the stored label 0.900",
            summary,
        )


class InputTests(_Passes):
    def test_old_and_new_keys_meet_on_the_same_case(self) -> None:
        # A pass from before opaque keys carries real IDs; a new one carries
        # hashes. Matching on the raw key would find no common item.
        old = self.sheet("A")
        for item in old["labels"]:
            item["key"] = self.real[item["key"]]
        text = self.report(old, self.sheet("B"))
        self.assertIn("items rated by all: 10", text)

    def test_an_item_one_rater_left_untouched_is_dropped_for_all(self) -> None:
        sheets = [self.sheet("A"), self.sheet("B")]
        for field in sheets[1]["protocol"]["rated_fields"]:
            self.item(sheets[1], 4)[field] = None
        text = self.report(*sheets)
        self.assertIn("items rated by all: 9   (dropped 1 that at least one rater left untouched)", text)

    def test_a_single_pass_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            ea.between_raters_report(self.write(self.sheet("A")))

    def test_the_same_file_twice_is_refused(self) -> None:
        path = self.write(self.sheet("A"))[0]
        with self.assertRaises(SystemExit) as caught:
            ea.between_raters_report([path, path])
        self.assertIn("same file twice", str(caught.exception))

    def test_passes_from_different_sets_are_refused(self) -> None:
        other = ea.build_worksheet("catalog")
        other["protocol"].update(rater="X", labeled_at="2026-10-15", blind=True)
        with self.assertRaises(SystemExit) as caught:
            ea.between_raters_report(self.write(self.sheet("A"), other))
        self.assertIn("different sets", str(caught.exception))

    def test_a_pass_that_was_not_blind_is_flagged(self) -> None:
        text = self.report(self.sheet("A"), self.sheet("B", blind=False))
        self.assertIn("NOT INDEPENDENT: B declared blind=false", text)

    def test_different_rules_versions_are_flagged(self) -> None:
        text = self.report(
            self.sheet("A"), self.sheet("B", appraisal_method_at_rating="1.2.0")
        )
        self.assertIn("different rules versions", text)

    def test_the_same_name_twice_is_flagged_as_self_consistency(self) -> None:
        text = self.report(self.sheet("A"), self.sheet("A"))
        self.assertIn("self-consistency", text)

    def test_a_calibration_round_says_it_is_no_baseline(self) -> None:
        self.assertIn("not a baseline", self.report(self.sheet("A"), self.sheet("B")))


if __name__ == "__main__":
    unittest.main()
