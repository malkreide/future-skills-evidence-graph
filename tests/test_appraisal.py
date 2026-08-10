"""Invariants of the multi-dimensional evidence appraisal.

The numbered invariants are the properties the conflated
``evidence_strength`` could not hold. They are written as the smallest
appraisal that exhibits the property, so a failure names the rule rather
than a data file.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import appraisal as ap  # noqa: E402
import eval_agreement as ea  # noqa: E402
import extract_claims as ec  # noqa: E402
import score_evidence as se  # noqa: E402


def base(**overrides):
    """An appraisal with everything unknown, plus *overrides*."""
    record = ap.normalized({})
    record.update(overrides)
    return record


class CertaintyDerivationTests(unittest.TestCase):
    def test_invariant_1_a_null_finding_can_be_moderate(self) -> None:
        # The case the old scale could not express: a clean trial that
        # found no difference is evidence ABOUT the null, not weak
        # evidence. Identical to the positive-effect trial below.
        null_finding = base(
            study_design="rct",
            effect_direction="null",
            effect_magnitude="null",
            comparator="active_control",
            precision="adequate",
            directness="direct",
            claim_supported_by_source="supported",
        )
        level, _ = ap.derive_certainty(null_finding)
        self.assertEqual(level, "moderate")

        positive = dict(null_finding, effect_direction="positive", effect_magnitude="large")
        self.assertEqual(ap.derive_certainty(positive)[0], level)

    def test_invariant_2_a_systematic_review_is_not_automatically_strong(self) -> None:
        review = base(study_design="systematic_review", claim_supported_by_source="supported")
        self.assertEqual(ap.derive_certainty(review)[0], "moderate")
        # And a reviewer may not simply overrule that without recording
        # the consistency and bias evidence that would justify it.
        self.assertTrue(ap.certainty_conflicts(dict(review, evidence_certainty="strong")))

    def test_invariant_3_pre_post_is_not_treated_like_an_rct(self) -> None:
        rct = base(study_design="rct", claim_supported_by_source="supported")
        pre_post = base(
            study_design="uncontrolled_pre_post",
            comparator="none",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(rct)[0], "moderate")
        self.assertEqual(ap.derive_certainty(pre_post)[0], "very_low")
        self.assertNotEqual(ap.derive_certainty(rct)[0], ap.derive_certainty(pre_post)[0])

    def test_invariant_4_missing_information_yields_unknown(self) -> None:
        level, reasons = ap.derive_certainty(base(study_design="unknown"))
        self.assertIsNone(level)
        self.assertTrue(any("baseline" in reason for reason in reasons))
        # And nothing invents a bias assessment out of a design name.
        self.assertIsNone(base(study_design="systematic_review")["risk_of_bias"])

    def test_invariant_9_a_null_direction_never_lowers_certainty(self) -> None:
        for design in ("rct", "quasi_experimental", "systematic_review"):
            with self.subTest(design=design):
                record = base(study_design=design, claim_supported_by_source="supported")
                for direction in ap.EFFECT_DIRECTION_VALUES:
                    self.assertEqual(
                        ap.derive_certainty(dict(record, effect_direction=direction))[0],
                        ap.derive_certainty(record)[0],
                        direction,
                    )

    def test_invariant_10_self_report_is_judged_through_directness(self) -> None:
        # A claim that says "reported higher confidence" is directly
        # supported by a self-report measure; one that says "improved
        # competence" is not, and only the second is downgraded.
        honest = base(
            study_design="rct",
            outcome_type="self_report",
            directness="direct",
            claim_supported_by_source="supported",
        )
        overreaching = dict(honest, directness="partially_direct")
        self.assertEqual(ap.derive_certainty(honest)[0], "moderate")
        self.assertEqual(ap.derive_certainty(overreaching)[0], "low")

    def test_invariant_11_high_heterogeneity_lowers_a_review(self) -> None:
        review = base(
            study_design="meta_analysis",
            replication="systematic_synthesis",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(review)[0], "moderate")
        self.assertEqual(
            ap.derive_certainty(dict(review, heterogeneity="high"))[0], "low"
        )
        self.assertEqual(
            ap.derive_certainty(dict(review, consistency="inconsistent"))[0], "low"
        )

    def test_inconsistency_is_counted_once(self) -> None:
        # Reporting both high heterogeneity and inconsistent findings
        # describes one problem twice; punishing it twice would penalise
        # the review for disclosing more.
        review = base(
            study_design="meta_analysis",
            heterogeneity="high",
            consistency="inconsistent",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(review)[0], "low")

    def test_invariant_12_an_overreaching_claim_can_be_flagged(self) -> None:
        record = base(study_design="rct", claim_supported_by_source="partially_supported")
        level, reasons = ap.derive_certainty(record)
        self.assertEqual(level, "low")
        self.assertTrue(any("partially supports" in reason for reason in reasons))
        not_supported = base(
            study_design="rct", claim_supported_by_source="not_supported"
        )
        self.assertEqual(ap.derive_certainty(not_supported)[0], "very_low")
        self.assertTrue(
            ap.certainty_conflicts(dict(not_supported, evidence_certainty="moderate"))
        )

    def test_cannot_determine_support_yields_unknown(self) -> None:
        record = base(study_design="rct", claim_supported_by_source="cannot_determine")
        self.assertIsNone(ap.derive_certainty(record)[0])

    def test_historical_control_is_downgraded(self) -> None:
        record = base(
            study_design="quasi_experimental",
            comparator="historical_control",
            claim_supported_by_source="supported",
        )
        level, reasons = ap.derive_certainty(record)
        self.assertEqual(level, "very_low")
        self.assertTrue(any("historical" in reason for reason in reasons))

    def test_replication_upgrades_only_when_clean(self) -> None:
        clean = base(
            study_design="systematic_review",
            replication="systematic_synthesis",
            consistency="consistent",
            risk_of_bias="low",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(clean)[0], "strong")
        # Replication under high bias is replication of the bias.
        self.assertEqual(
            ap.derive_certainty(dict(clean, risk_of_bias="high"))[0], "low"
        )
        # And unrecorded bias blocks the upgrade without downgrading --
        # the case that separates "the downgrade happened to block it"
        # from "the upgrade actually requires low bias".
        for bias in ("some_concerns", "unknown", None):
            with self.subTest(risk_of_bias=bias):
                self.assertEqual(
                    ap.derive_certainty(dict(clean, risk_of_bias=bias))[0], "moderate"
                )

    def test_source_type_never_reaches_the_derivation(self) -> None:
        # The rule the old prompt broke. source_type is not even a field
        # of the appraisal, and adding one must not change an answer.
        record = base(study_design="quasi_experimental", claim_supported_by_source="supported")
        expected = ap.derive_certainty(record)[0]
        for source_type in ("systematic_review", "web_resource", "peer_reviewed_article"):
            with self.subTest(source_type=source_type):
                polluted = dict(record, source_type=source_type)
                self.assertEqual(ap.derive_certainty(polluted)[0], expected)
        self.assertNotIn("source_type", ap.APPRAISAL_FIELDS)

    def test_sample_size_never_reaches_the_derivation(self) -> None:
        # "n > 200 therefore precise" is the arithmetic the module refuses
        # to do; precision is its own recorded judgement.
        record = base(study_design="rct", claim_supported_by_source="supported")
        for size in (None, 12, 5000):
            with self.subTest(size=size):
                self.assertEqual(
                    ap.derive_certainty(dict(record, sample_size=size))[0], "moderate"
                )

    def test_derivation_always_explains_itself(self) -> None:
        for record in (
            base(study_design="rct"),
            base(study_design="unknown"),
            base(source_provenance="unverified_source", source_verified="false"),
        ):
            with self.subTest(record=record["study_design"]):
                self.assertTrue(ap.derive_certainty(record)[1])


class UnverifiableTests(unittest.TestCase):
    def test_invariant_7_unverifiable_is_a_rating_not_a_missing_value(self) -> None:
        record = base(
            source_provenance="unverified_source",
            source_verified="false",
            study_design="rct",
        )
        self.assertEqual(ap.derive_certainty(record)[0], "unverifiable")
        self.assertIn("unverifiable", ap.CERTAINTY_VALUES)
        # It is a permitted value, so validation accepts it...
        self.assertEqual(ap.validate_appraisal(dict(record, evidence_certainty="unverifiable")), [])
        # ...but it is not a rung on the ordinal ladder.
        self.assertNotIn("unverifiable", ap.ORDERED_CERTAINTY)

    def test_unverifiable_beats_a_recorded_level(self) -> None:
        record = base(
            source_provenance="unverified_source",
            source_verified="false",
            study_design="rct",
            evidence_certainty="moderate",
        )
        self.assertTrue(ap.certainty_conflicts(record))

    def test_a_synthetic_case_is_appraised_on_its_described_design(self) -> None:
        # Synthetic cases exist to exercise the logic; refusing to
        # appraise them would make the golden set untestable. The
        # provenance marker is what keeps them distinguishable.
        record = base(
            source_provenance="synthetic_eval_case",
            source_verified="false",
            study_design="rct",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(record)[0], "moderate")

    def test_unverifiable_makes_a_claim_unscoreable(self) -> None:
        sources = {"src-x": {"id": "src-x", "source_type": "peer_reviewed_article"}}
        claim = {
            "id": "claim-x",
            "source_ids": ["src-x"],
            "evidence_strength": "strong",
            "appraisal": {"evidence_certainty": "unverifiable"},
        }
        self.assertIsNone(se.claim_score(claim, sources))
        self.assertIn("unverifiable", se.claim_score_problem(claim, sources))
        # very_low, by contrast, is weak evidence and still scores.
        weak = dict(claim, appraisal={"evidence_certainty": "very_low"})
        self.assertIsNotNone(se.claim_score(weak, sources))


class AgeTests(unittest.TestCase):
    def test_invariant_5_a_school_stage_produces_no_explicit_age(self) -> None:
        # No function can forbid this -- a source may legitimately state
        # both "11th grade" and "aged 16 to 17" -- so the invariant is a
        # property of the DATA, and that is where it has to be asserted.
        # Every golden case that names a stage carries either no explicit
        # band at all, or one whose numbers stand in the abstract.
        examples = json.loads(
            (ROOT / "eval" / "claim_prefill_labeled.json").read_text(encoding="utf-8")
        )["examples"]
        staged = [e for e in examples if e["gold_appraisal"]["grade_or_stage"]]
        self.assertGreaterEqual(len(staged), 30)
        for example in staged:
            with self.subTest(example["id"]):
                explicit = example["gold_appraisal"]["age_range_explicit"]
                if explicit is None:
                    continue
                for bound in explicit.split("-"):
                    self.assertIn(bound, example["abstract"], example["id"])
        # And the stage itself is preserved rather than thrown away, so a
        # later, jurisdiction-aware step still has something to work from.
        self.assertTrue(any(e["gold_appraisal"]["grade_or_stage"] == "11th grade"
                            for e in staged))

    def test_invariant_6_reported_ages_are_carried_through(self) -> None:
        record = base(age_range_explicit="22-55")
        self.assertEqual(ap.validate_appraisal(record), [])
        self.assertEqual(record["age_range_explicit"], "22-55")

    def test_an_inferred_band_needs_its_basis(self) -> None:
        problems = ap.validate_appraisal(base(age_range_inferred="16-17"))
        self.assertTrue(any("age_inference_basis" in problem for problem in problems))
        self.assertEqual(
            ap.validate_appraisal(
                base(age_range_inferred="16-17", age_inference_basis="US 11th grade")
            ),
            [],
        )

    def test_malformed_and_reversed_bands_are_rejected(self) -> None:
        self.assertTrue(ap.validate_appraisal(base(age_range_explicit="upper secondary")))
        self.assertTrue(ap.validate_appraisal(base(age_range_explicit="17-11")))

    def test_the_golden_set_records_only_reported_ages(self) -> None:
        # The finding that motivated the split: of 43 legacy age labels,
        # none named an age the abstract states, and the two abstracts
        # that DO state ages carried null.
        examples = json.loads(
            (ROOT / "eval" / "claim_prefill_labeled.json").read_text(encoding="utf-8")
        )["examples"]
        for example in examples:
            explicit = example["gold_appraisal"]["age_range_explicit"]
            if explicit is None:
                continue
            low, high = explicit.split("-")
            self.assertIn(low, example["abstract"], example["id"])
            self.assertIn(high, example["abstract"], example["id"])


class ValidationTests(unittest.TestCase):
    def test_unknown_enum_values_are_rejected_by_name(self) -> None:
        problems = ap.validate_appraisal({"study_design": "randomized-ish"})
        self.assertEqual(len(problems), 1)
        self.assertIn("randomized-ish", problems[0])
        self.assertIn("systematic_review", problems[0])

    def test_unknown_fields_are_rejected(self) -> None:
        problems = ap.validate_appraisal({"evidence_quality": "strong"})
        self.assertTrue(any("unknown appraisal field" in problem for problem in problems))

    def test_scalar_types_are_checked(self) -> None:
        self.assertTrue(ap.validate_appraisal({"sample_size": "about 200"}))
        self.assertTrue(ap.validate_appraisal({"sample_size": True}))
        self.assertEqual(ap.validate_appraisal({"sample_size": 200}), [])

    def test_null_is_always_permitted(self) -> None:
        self.assertEqual(ap.validate_appraisal(ap.normalized({})), [])

    def test_the_claim_schema_matches_the_vocabulary(self) -> None:
        # Generated from the same source, so a new enum value can never be
        # accepted by one and rejected by the other.
        schema = json.loads(
            (ROOT / "schemas" / "claim.schema.json").read_text(encoding="utf-8")
        )
        stored = dict(schema["properties"]["appraisal"])
        stored.pop("description", None)
        self.assertEqual(stored, ap.json_schema())


class MigrationTests(unittest.TestCase):
    def test_a_legacy_strength_is_not_reinterpreted_as_certainty(self) -> None:
        for strength in ap.LEGACY_STRENGTH_VALUES:
            with self.subTest(strength=strength):
                migrated = ap.migrate_legacy({"evidence_strength": strength})
                self.assertIsNone(migrated["evidence_certainty"])

    def test_a_legacy_age_range_becomes_neither_explicit_nor_inferred(self) -> None:
        # The specific laundering this migration exists to prevent: a band
        # estimated from "middle school" must not resurface as a reported
        # age.
        migrated = ap.migrate_legacy({"age_range": "11-14"})
        self.assertIsNone(migrated["age_range_explicit"])
        self.assertIsNone(migrated["age_range_inferred"])
        report = ap.migration_report({"id": "claim-x", "age_range": "11-14"})
        self.assertIn("unrecorded origin", report["not_migrated"]["age_range"])

    def test_a_legacy_claim_still_scores_exactly_as_before(self) -> None:
        sources = {"src-x": {"id": "src-x", "source_type": "peer_reviewed_article"}}
        claim = {"id": "claim-x", "source_ids": ["src-x"], "evidence_strength": "moderate"}
        self.assertEqual(
            se.claim_score(claim, sources),
            round(0.8 * se.SOURCE_COMPONENT_WEIGHT + 0.7 * se.CLAIM_COMPONENT_WEIGHT, 3),
        )

    def test_an_appraised_claim_scores_on_its_certainty(self) -> None:
        # Legacy value and certainty deliberately disagree: the appraisal
        # must win, or the fallback would be a silent override.
        claim = {
            "id": "claim-x",
            "source_ids": ["src-x"],
            "evidence_strength": "strong",
            "appraisal": {"evidence_certainty": "very_low"},
        }
        self.assertEqual(se.claim_strength_weight(claim), se.CERTAINTY_WEIGHTS["very_low"])
        self.assertNotEqual(se.claim_strength_weight(claim), se.CLAIM_WEIGHTS["strong"])


class GoldenSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (ROOT / "eval" / "claim_prefill_labeled.json").read_text(encoding="utf-8")
        )
        self.examples = self.payload["examples"]

    def test_invariant_8_every_case_is_marked_synthetic(self) -> None:
        for example in self.examples:
            with self.subTest(example["id"]):
                block = example["gold_appraisal"]
                self.assertEqual(block["source_provenance"], "synthetic_eval_case")
                self.assertEqual(block["source_verified"], "false")

    def test_no_bibliographic_field_was_invented(self) -> None:
        # Nothing in this file is a real publication, so any author,
        # journal, DOI or URL in it would be fabricated.
        for example in self.examples:
            for field in ap.BIBLIOGRAPHIC_FIELDS:
                with self.subTest(example=example["id"], field=field):
                    self.assertIsNone(example["gold_appraisal"][field])

    def test_every_appraisal_validates_and_holds_the_guardrails(self) -> None:
        for example in self.examples:
            with self.subTest(example["id"]):
                block = example["gold_appraisal"]
                self.assertEqual(ap.validate_appraisal(block), [])
                self.assertEqual(ap.certainty_conflicts(block), [])

    def test_the_recorded_certainty_matches_the_documented_rules(self) -> None:
        # Not independent evidence -- the rules were written against these
        # cases. It is a consistency check: an edit to either side that
        # silently desynchronises them fails here.
        for example in self.examples:
            with self.subTest(example["id"]):
                block = example["gold_appraisal"]
                self.assertEqual(
                    ap.derive_certainty(block)[0], block["evidence_certainty"]
                )

    def test_the_legacy_layer_is_still_intact(self) -> None:
        # The CI gates measure `_recorded` against `gold`. Re-labelling
        # gold without re-recording would fail them for a reason that has
        # nothing to do with the model, so the successor model lives
        # beside it rather than on top of it.
        for example in self.examples:
            with self.subTest(example["id"]):
                self.assertIn("evidence_strength", example["gold"])
                self.assertIn(
                    example["gold"]["evidence_strength"], ap.LEGACY_STRENGTH_VALUES
                )

    def test_the_synthetic_marker_keeps_such_cases_out_of_production(self) -> None:
        import validate_data

        errors: list[str] = []
        validate_data._check_appraisals(
            [{"id": "claim-x", "appraisal": {"source_provenance": "synthetic_eval_case"}}],
            errors,
        )
        self.assertTrue(any("never in the production catalogue" in e for e in errors))


class AppraisalPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = ec.appraisal_prompt("ABSTRACT", "CLAIM")

    def test_it_forbids_deriving_quality_from_the_publication_type(self) -> None:
        self.assertIn("publication type does not decide this", self.prompt)

    def test_it_states_that_a_null_finding_is_not_weak(self) -> None:
        self.assertIn("must not lower your certainty rating", self.prompt)

    def test_it_forbids_inferring_an_age_from_a_school_stage(self) -> None:
        self.assertIn("A school stage is not an age", self.prompt)

    def test_it_forbids_inventing_a_bias_assessment(self) -> None:
        self.assertIn('risk_of_bias "unknown", NOT "low"', self.prompt)

    def test_its_schema_is_generated_from_the_vocabulary(self) -> None:
        schema = ec.appraisal_output_schema()
        self.assertEqual(
            schema["properties"]["evidence_certainty"]["enum"],
            [*ap.CERTAINTY_VALUES, None],
        )
        self.assertEqual(
            schema["properties"]["study_design"]["enum"],
            [*ap.STUDY_DESIGN_VALUES, None],
        )

    def test_it_asks_for_no_bibliographic_field(self) -> None:
        # A model cannot verify a DOI, and one that invents one is worse
        # than one that leaves it empty.
        for field in ap.BIBLIOGRAPHIC_FIELDS:
            self.assertNotIn(field, ec.APPRAISAL_SUGGESTION_FIELDS)

    def test_the_legacy_prefill_prompt_is_marked_as_such(self) -> None:
        source = (ROOT / "scripts" / "extract_claims.py").read_text(encoding="utf-8")
        marker = source.index("PREFILL_PROMPT_VERSION =")
        self.assertIn("LEGACY as of the appraisal model", source[:marker])


class WeightedKappaTests(unittest.TestCase):
    scale = ap.ORDERED_CERTAINTY

    def test_perfect_agreement_is_one(self) -> None:
        pairs = [("low", "low"), ("strong", "strong"), ("moderate", "moderate")]
        self.assertAlmostEqual(ea.weighted_kappa(pairs, self.scale), 1.0)

    def test_a_near_miss_beats_a_far_miss(self) -> None:
        near = [("moderate", "strong")] * 5 + [("low", "low")] * 5
        far = [("very_low", "strong")] * 5 + [("low", "low")] * 5
        self.assertGreater(
            ea.weighted_kappa(near, self.scale), ea.weighted_kappa(far, self.scale)
        )
        # Unweighted kappa cannot tell them apart -- which is why the
        # weighted one is reported for the ordinal field.
        self.assertAlmostEqual(ea.cohens_kappa(near), ea.cohens_kappa(far))

    def test_a_single_category_is_undefined_not_perfect(self) -> None:
        self.assertIsNone(ea.weighted_kappa([("low", "low")] * 8, self.scale))

    def test_off_scale_values_are_excluded_and_counted(self) -> None:
        comparison = ea.Comparison(
            name="t",
            field="evidence_certainty",
            pairs=[("low", "low"), ("unverifiable", "low"), ("strong", "moderate")],
            independent=True,
            provenance="test",
        )
        usable, excluded = comparison.ordinal_pairs()
        self.assertEqual(excluded, 1)
        self.assertEqual(len(usable), 2)
        report = "\n".join(comparison.report())
        self.assertIn("1 pair(s) excluded", report)
        # But it still counts as a rating everywhere else.
        self.assertEqual(comparison.n, 3)

    def test_an_untouched_worksheet_measures_nothing(self) -> None:
        # The failure this protocol must never produce: null means both
        # "not judged" and "judged, answer is nothing". If the second
        # reading were applied everywhere, a worksheet nobody filled in
        # would agree with every null primary label and report itself as
        # a baseline.
        import tempfile

        worksheet = ea.build_worksheet("claim_prefill")
        worksheet["protocol"].update(rater="nobody", labeled_at="2026-08-10", blind=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            for comparison in ea.second_rater_comparisons(path):
                with self.subTest(comparison.field):
                    self.assertEqual(comparison.n, 0)
                    self.assertEqual(comparison.skipped, len(worksheet["labels"]))
                    self.assertFalse(comparison.gate_ready())

    def test_a_null_inside_a_worked_item_is_an_answer(self) -> None:
        # The other half of the same rule: 48 of 50 abstracts state no
        # age, so "no explicit age" is the answer on almost every item.
        # Reading those as skips would leave age_range_explicit with a
        # sample of two.
        import tempfile

        worksheet = ea.build_worksheet("claim_prefill")
        primary = ea.primary_labels("claim_prefill")
        for item in worksheet["labels"]:
            for field in ea.SECOND_RATER_FIELDS["claim_prefill"]:
                item[field] = primary[item["key"]].get(field)
        worksheet["protocol"].update(rater="tester", labeled_at="2026-08-10", blind=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "full.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            ages = next(
                c for c in ea.second_rater_comparisons(path)
                if c.field == "age_range_explicit"
            )
            self.assertEqual(ages.n, len(worksheet["labels"]))
            self.assertEqual(ages.skipped, 0)

    def test_skipped_items_are_reported_not_hidden(self) -> None:
        comparison = ea.Comparison(
            name="t",
            field="evidence_certainty",
            pairs=[("low", "low")],
            independent=True,
            provenance="test",
            skipped=49,
        )
        self.assertIn("skipped (null on either side): 49", "\n".join(comparison.report()))


class WorksheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worksheet = ea.build_worksheet("claim_prefill")

    def test_it_rates_the_fields_that_need_a_judgement(self) -> None:
        for field in ("evidence_certainty", "claim_supported_by_source", "study_design",
                      "effect_direction", "age_range_explicit"):
            self.assertIn(field, self.worksheet["labels"][0], field)

    def test_it_does_not_ask_a_rater_to_transcribe_bibliography(self) -> None:
        for field in ap.BIBLIOGRAPHIC_FIELDS:
            self.assertNotIn(field, ea.SECOND_RATER_APPRAISAL_FIELDS, field)

    def test_it_carries_the_five_certainty_anchors(self) -> None:
        self.assertEqual(
            set(self.worksheet["rubrik_evidence_certainty"]), set(ap.CERTAINTY_VALUES)
        )

    def test_it_no_longer_tells_raters_to_convert_a_stage_into_ages(self) -> None:
        # The instruction this replaces read "Nennt der Text nur eine
        # Schulstufe, die uebliche Spanne dieser Stufe verwenden" -- which
        # is how 43 of 50 legacy age labels came to state ages nobody had
        # reported.
        rubric = json.dumps(self.worksheet, ensure_ascii=False)
        self.assertNotIn("übliche Spanne dieser Stufe", rubric)
        self.assertIn("Eine Schulstufe ist KEINE Altersangabe", rubric)

    def test_it_holds_no_answers(self) -> None:
        for item in self.worksheet["labels"]:
            for field in ea.SECOND_RATER_FIELDS["claim_prefill"]:
                self.assertIsNone(item[field], (item["key"], field))
            self.assertNotIn("gold", item)
            self.assertNotIn("gold_appraisal", item)


if __name__ == "__main__":
    unittest.main()
