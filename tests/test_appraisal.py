"""Invariants of the multi-dimensional evidence appraisal.

The numbered invariants are the properties the conflated
``evidence_strength`` could not hold. They are written as the smallest
appraisal that exhibits the property, so a failure names the rule rather
than a data file.
"""

from __future__ import annotations

import json
import re
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


class ClaimTypeTests(unittest.TestCase):
    """The design ladder only applies to claims that assert a cause."""

    def test_a_definitional_claim_is_not_judged_by_the_design_ladder(self) -> None:
        # "DigComp includes information literacy" needs no control group.
        # Asking whether it randomised is a category error, and answering
        # very_low would report a category error as a finding.
        record = base(
            claim_type="definitional",
            study_design="consensus_framework",
            effect_direction="not_applicable",
            directness="direct",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(record)[0], "moderate")
        # The same document behind a CAUSAL claim gets the ladder.
        causal = dict(record, claim_type="causal_effect", effect_direction="positive")
        self.assertEqual(ap.derive_certainty(causal)[0], "low")

    def test_the_fit_path_rests_on_directness(self) -> None:
        record = base(
            claim_type="descriptive",
            study_design="qualitative",
            effect_direction="not_applicable",
            claim_supported_by_source="supported",
        )
        for directness, expected in (
            ("direct", "moderate"),
            ("partially_direct", "low"),
            ("indirect", "very_low"),
            (None, None),
        ):
            with self.subTest(directness=directness):
                self.assertEqual(
                    ap.derive_certainty(dict(record, directness=directness))[0], expected
                )

    def test_directness_is_not_charged_twice_on_the_fit_path(self) -> None:
        # It sets the baseline there; applying the downgrade as well would
        # take the same concern off the score a second time.
        record = base(
            claim_type="descriptive",
            study_design="descriptive",
            directness="partially_direct",
            effect_direction="not_applicable",
            claim_supported_by_source="supported",
        )
        level, reasons = ap.derive_certainty(record)
        self.assertEqual(level, "low")
        self.assertFalse(any("partially direct" in reason for reason in reasons))

    def test_a_historical_control_is_irrelevant_to_a_non_effect_claim(self) -> None:
        record = base(
            claim_type="descriptive",
            study_design="descriptive",
            comparator="historical_control",
            directness="direct",
            effect_direction="not_applicable",
            claim_supported_by_source="supported",
        )
        self.assertEqual(ap.derive_certainty(record)[0], "moderate")

    def test_downgrades_that_still_apply_on_the_fit_path(self) -> None:
        record = base(
            claim_type="descriptive",
            study_design="qualitative",
            directness="direct",
            effect_direction="not_applicable",
            claim_supported_by_source="supported",
        )
        for field, value in (
            ("precision", "imprecise"),
            ("risk_of_bias", "high"),
            ("consistency", "inconsistent"),
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    ap.derive_certainty(dict(record, **{field: value}))[0], "low"
                )
        self.assertEqual(
            ap.derive_certainty(
                dict(record, claim_supported_by_source="partially_supported")
            )[0],
            "low",
        )

    def test_an_unset_claim_type_keeps_the_causal_reading(self) -> None:
        # Backward compatibility: an appraisal written before claim_type
        # existed must not silently change level.
        record = base(
            study_design="uncontrolled_pre_post",
            directness="direct",
            claim_supported_by_source="supported",
        )
        self.assertIsNone(record["claim_type"])
        self.assertEqual(ap.derive_certainty(record)[0], "very_low")


class MethodVersionTests(unittest.TestCase):
    def test_a_recorded_certainty_must_name_its_rule_version(self) -> None:
        problems = ap.validate_appraisal({"evidence_certainty": "moderate"})
        self.assertTrue(any("appraisal_method" in problem for problem in problems))
        self.assertEqual(
            ap.validate_appraisal(
                {"evidence_certainty": "moderate", "appraisal_method": "1.1.0"}
            ),
            [],
        )

    def test_an_unrated_appraisal_needs_no_version(self) -> None:
        self.assertEqual(ap.validate_appraisal(ap.normalized({})), [])

    def test_every_stored_appraisal_carries_a_version(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from common import load_records

        appraised = [c for c in load_records("claims") if c.get("appraisal")]
        self.assertGreaterEqual(len(appraised), 59)
        for claim in appraised:
            with self.subTest(claim["id"]):
                self.assertTrue(claim["appraisal"].get("appraisal_method"), claim["id"])


class CatalogueAppraisalTests(unittest.TestCase):
    """Properties of the 59 appraised catalogue claims."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from common import load_records

        cls.claims = [c for c in load_records("claims") if c.get("appraisal")]
        cls.sources = {s["id"]: s for s in load_records("sources")}

    def test_every_appraisal_validates_and_holds_the_guardrails(self) -> None:
        for claim in self.claims:
            with self.subTest(claim["id"]):
                self.assertEqual(ap.validate_appraisal(claim["appraisal"]), [])
                self.assertEqual(ap.certainty_conflicts(claim["appraisal"]), [])

    def test_no_catalogue_claim_is_marked_synthetic(self) -> None:
        for claim in self.claims:
            with self.subTest(claim["id"]):
                self.assertEqual(
                    claim["appraisal"]["source_provenance"], "verified_real_source"
                )

    def test_bibliography_is_transcribed_not_typed(self) -> None:
        # Every bibliographic value must be findable in the stored source
        # record. A DOI that appears here and nowhere else was invented.
        for claim in self.claims:
            source = self.sources[claim["source_ids"][0]]
            block = claim["appraisal"]
            with self.subTest(claim["id"]):
                self.assertEqual(block["doi"], source.get("doi"))
                self.assertEqual(block["url"], source.get("url"))
                self.assertEqual(block["title"], source.get("title"))
                self.assertEqual(block["year"], source.get("year"))
                if block["authors"]:
                    self.assertEqual(block["authors"], ", ".join(source["authors"]))

    def test_explicit_ages_appear_in_the_claim_or_its_source(self) -> None:
        for claim in self.claims:
            explicit = claim["appraisal"]["age_range_explicit"]
            if explicit is None:
                continue
            haystack = " ".join(
                [
                    claim["statement"],
                    claim.get("context") or "",
                    self.sources[claim["source_ids"][0]].get("abstract") or "",
                ]
            )
            with self.subTest(claim["id"]):
                for bound in explicit.split("-"):
                    self.assertIn(bound, haystack, claim["id"])

    def test_the_legacy_age_field_is_not_copied_into_the_explicit_one(self) -> None:
        # Four reviewed claims carry the literal string "Lehrende" in
        # age_range -- an audience, not an age, which the string-typed
        # schema never caught. Nothing like that may reach the new field.
        #
        # Note what is NOT asserted: that the two fields differ. Two claims
        # legitimately agree, because their source does state the ages the
        # legacy label guessed at. The rule is that the new field is a
        # numeric band that came from the text, not that it disagrees.
        non_numeric = [c for c in self.claims if not re.match(
            r"^\d{1,2}-\d{1,2}$", str(c.get("age_range", ""))
        )]
        self.assertTrue(non_numeric, "expected the legacy audience labels to still exist")
        for claim in non_numeric:
            with self.subTest(claim["id"]):
                self.assertIsNone(claim["appraisal"]["age_range_explicit"])
        for claim in self.claims:
            explicit = claim["appraisal"]["age_range_explicit"]
            if explicit is not None:
                with self.subTest(claim["id"]):
                    self.assertRegex(explicit, r"^\d{1,2}-\d{1,2}$")

    def test_source_type_and_study_design_are_allowed_to_disagree(self) -> None:
        # The separation is only worth having if it actually separates.
        # One catalogue source is filed as a systematic_review and
        # describes a survey; the appraisal records the survey.
        mismatched = [
            c
            for c in self.claims
            if self.sources[c["source_ids"][0]]["source_type"] == "systematic_review"
            and c["appraisal"]["study_design"] not in ("systematic_review", "meta_analysis")
        ]
        self.assertTrue(mismatched)


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
        self.assertEqual(
            ap.validate_appraisal(
                dict(record, evidence_certainty="unverifiable",
                     appraisal_method=ap.APPRAISAL_VERSION)
            ),
            [],
        )
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


class CatalogWorksheetTests(unittest.TestCase):
    """The worksheet over the claims that actually drive the dashboard."""

    def setUp(self) -> None:
        self.worksheet = ea.build_worksheet("catalog")

    def test_it_covers_every_appraised_claim(self) -> None:
        keys = {item["key"] for item in self.worksheet["labels"]}
        self.assertEqual(keys, set(ea.primary_labels("catalog")))
        self.assertGreaterEqual(len(keys), 59)

    def test_it_withholds_the_review_written_fields(self) -> None:
        # `context` and `text_anchor` are written during review and name
        # the design outright -- "single-group study", "Systematic review
        # synthesis". Handing either to a second rater hands them one of
        # the answers, and the agreement would measure transcription.
        for item in self.worksheet["labels"]:
            with self.subTest(item["key"]):
                self.assertNotIn("context", item)
                self.assertNotIn("text_anchor", item)
                self.assertNotIn("appraisal", item)
                for field in ea.SECOND_RATER_FIELDS["catalog"]:
                    self.assertIsNone(item[field])

    def test_it_carries_the_source_abstract_a_rater_needs(self) -> None:
        for item in self.worksheet["labels"]:
            with self.subTest(item["key"]):
                self.assertTrue(item["statement"])
                self.assertTrue(item["abstract"])
                self.assertTrue(item["source_type"])

    def test_it_rates_the_legacy_scale_but_not_the_legacy_age_field(self) -> None:
        # evidence_strength is rated so one pass can answer whether the
        # successor scale is MORE reproducible. age_range is not: four
        # reviewed claims hold "Lehrende" in it, and reproducing a defect
        # measures nothing.
        self.assertIn("evidence_strength", ea.SECOND_RATER_FIELDS["catalog"])
        self.assertNotIn("age_range", ea.SECOND_RATER_FIELDS["catalog"])

    def test_a_completed_pass_scores_against_the_stored_appraisals(self) -> None:
        import tempfile

        primary = ea.primary_labels("catalog")
        for item in self.worksheet["labels"]:
            for field in ea.SECOND_RATER_FIELDS["catalog"]:
                item[field] = primary[item["key"]].get(field)
        self.worksheet["protocol"].update(rater="t", labeled_at="2026-08-10", blind=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(self.worksheet), encoding="utf-8")
            comparisons = ea.second_rater_comparisons(path)
        self.assertEqual(len(comparisons), len(ea.SECOND_RATER_FIELDS["catalog"]))
        for comparison in comparisons:
            with self.subTest(comparison.field):
                self.assertEqual(comparison.agreement, 1.0)
                self.assertTrue(comparison.gate_ready())


class NarrowedWorksheetTests(unittest.TestCase):
    """A pass may ask for fewer fields without that reading as disagreement."""

    def _completed(self, fields):
        worksheet = ea.build_worksheet("catalog", fields)
        primary = ea.primary_labels("catalog")
        for item in worksheet["labels"]:
            for field in worksheet["protocol"]["rated_fields"]:
                item[field] = primary[item["key"]].get(field)
        worksheet["protocol"].update(rater="t", labeled_at="2026-08-10", blind=True)
        return worksheet

    def test_a_narrowed_pass_is_scored_on_what_it_asked(self) -> None:
        # Before protocol.rated_fields existed, filling in two fields and
        # leaving six blank produced six fields at agreement 0.000 -- work
        # nobody was asked for, reported as disagreement.
        import tempfile

        worksheet = self._completed(["evidence_certainty", "claim_type"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            comparisons = ea.second_rater_comparisons(path)
        self.assertEqual(
            [c.field for c in comparisons], ["evidence_certainty", "claim_type"]
        )
        for comparison in comparisons:
            with self.subTest(comparison.field):
                self.assertEqual(comparison.agreement, 1.0)

    def test_the_worksheet_asks_only_for_the_narrowed_fields(self) -> None:
        worksheet = ea.build_worksheet("catalog", ["evidence_certainty"])
        self.assertEqual(worksheet["protocol"]["rated_fields"], ["evidence_certainty"])
        for item in worksheet["labels"]:
            with self.subTest(item["key"]):
                self.assertIn("evidence_certainty", item)
                self.assertNotIn("study_design", item)

    def test_the_rubric_narrows_with_the_fields(self) -> None:
        narrowed = ea.build_worksheet("catalog", ["evidence_certainty", "claim_type"])
        blocks = {key for key in narrowed if key.startswith("rubrik_")}
        self.assertIn("rubrik_claim_type", blocks)
        self.assertNotIn("rubrik_study_design", blocks)
        # The legacy block only appears when a legacy field is rated.
        self.assertNotIn("rubrik_legacy_felder", blocks)
        self.assertIn(
            "rubrik_legacy_felder",
            ea.build_worksheet("catalog", ["evidence_certainty", "evidence_strength"]),
        )

    def test_every_rated_field_has_a_rubric_and_every_rubric_a_field(self) -> None:
        blocks = set(ea._prefill_rubric())
        mapped = {key for keys in ea.RUBRIC_FOR_FIELD.values() for key in keys}
        self.assertEqual(blocks, mapped)
        for set_name in ("claim_prefill", "catalog"):
            for field in ea.SECOND_RATER_FIELDS[set_name]:
                with self.subTest(set_name=set_name, field=field):
                    self.assertIn(field, ea.RUBRIC_FOR_FIELD)

    def test_an_unknown_field_is_rejected_with_the_alternatives(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            ea.build_worksheet("catalog", ["evidence_certainty", "nonsense"])
        message = str(caught.exception)
        self.assertIn("nonsense", message)
        self.assertIn("evidence_certainty", message)

    def test_a_worksheet_without_the_declaration_still_scores_fully(self) -> None:
        # Worksheets generated before protocol.rated_fields existed must
        # keep working, and must be read as asking for everything.
        import tempfile

        worksheet = self._completed(None)
        del worksheet["protocol"]["rated_fields"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            comparisons = ea.second_rater_comparisons(path)
        self.assertEqual(
            [c.field for c in comparisons], ea.SECOND_RATER_FIELDS["catalog"]
        )


class WorkedExampleExposureTests(unittest.TestCase):
    """The methodology document teaches with named cases -- and gives them away."""

    def test_the_eval_set_is_substantially_exposed(self) -> None:
        named = ea.documented_examples("claim_prefill")
        total = len(ea.primary_labels("claim_prefill"))
        self.assertGreaterEqual(len(named), 15)
        # And what is left is below the size a floor needs, which is the
        # whole reason this has to be reported rather than noticed later.
        self.assertLess(total - len(named), ea.MIN_N_FOR_GATE)

    def test_detection_follows_the_document(self) -> None:
        # Derived, not maintained by hand: an example added to or removed
        # from the document changes the count without anyone updating a
        # list that would otherwise quietly go stale.
        import tempfile
        from pathlib import Path as _Path

        original = ea.ANCHOR_DOC
        try:
            with tempfile.TemporaryDirectory() as tmp:
                doc = _Path(tmp) / "anker.md"
                doc.write_text("nennt niemanden\n", encoding="utf-8")
                ea.ANCHOR_DOC = doc
                self.assertEqual(ea.documented_examples("claim_prefill"), set())
                doc.write_text("Katalogfall: `prefill-adult-mooc`\n", encoding="utf-8")
                self.assertEqual(
                    ea.documented_examples("claim_prefill"), {"prefill-adult-mooc"}
                )
        finally:
            ea.ANCHOR_DOC = original

    def test_the_report_separates_exposed_from_clean(self) -> None:
        import tempfile

        worksheet = ea.build_worksheet("claim_prefill")
        primary = ea.primary_labels("claim_prefill")
        named = ea.documented_examples("claim_prefill")
        for item in worksheet["labels"]:
            for field in worksheet["protocol"]["rated_fields"]:
                item[field] = primary[item["key"]].get(field)
            # Disagree only where the document did NOT give the answer.
            if item["key"] not in named:
                item["claim_type"] = "unknown"
        worksheet["protocol"].update(rater="t", labeled_at="2026-08-14", blind=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            comparison = next(
                c for c in ea.second_rater_comparisons(path) if c.field == "claim_type"
            )
        report = "\n".join(comparison.report())
        self.assertIn("worked examples:", report)
        self.assertIn(f"agreement on the named items:   {len(named)}/{len(named)}", report)
        self.assertIn("agreement on the rest:", report)
        self.assertIn("cannot carry a floor", report)

    def test_a_set_with_no_named_examples_says_nothing(self) -> None:
        # The catalogue is not taught through named cases, so the block
        # must not appear there and add noise.
        self.assertEqual(ea.documented_examples("catalog"), set())
        comparison = ea.Comparison(
            name="t",
            field="evidence_certainty",
            pairs=[("low", "low")] * 5,
            independent=True,
            provenance="x",
            documented=[False] * 5,
        )
        self.assertNotIn("worked examples", "\n".join(comparison.report()))


class SupportAnchorTests(unittest.TestCase):
    """The anchor sharpened after it measured kappa 0.039."""

    def test_the_rubric_is_read_from_the_document(self) -> None:
        # Four places describe this field -- the module, the worksheet
        # rubric, the extractor prompt and the methodology document. Only
        # one may define it, or they drift.
        rubric = ea.support_rubric()
        self.assertEqual(set(rubric), set(ap.CLAIM_SUPPORT_VALUES))
        doc = ea.ANCHOR_DOC.read_text(encoding="utf-8")
        for value, definition in rubric.items():
            with self.subTest(value):
                self.assertGreater(len(definition), 30)
                self.assertIn(definition, doc)
        # And the worksheet must actually carry THOSE definitions. Checking
        # support_rubric() alone would pass even if build_worksheet wrote
        # its own copy, which is the drift this is meant to prevent.
        block = dict(ea.build_worksheet("catalog")["rubrik_claim_supported_by_source"])
        block.pop("_hinweis", None)
        self.assertEqual(block, rubric)

    def test_brevity_is_ruled_out_as_a_reason(self) -> None:
        # The exact wording that produced 21 systematic disagreements:
        # cannot_determine used to mean "not decidable from what is here",
        # which made a one-line abstract a legitimate reason.
        rubric = ea.support_rubric()
        self.assertNotIn("Aus dem Vorliegenden nicht entscheidbar", rubric["cannot_determine"])
        self.assertIn("gar nicht", rubric["cannot_determine"])
        worksheet = ea.build_worksheet("catalog")
        hint = worksheet["rubrik_claim_supported_by_source"]["_hinweis"]
        self.assertIn("KUERZE IST KEIN GRUND", hint)
        # And it points at the fields that DO answer that question, so the
        # concern is not charged twice.
        self.assertIn("source_verified", hint)
        self.assertIn("directness", hint)

    def test_the_prompt_carries_the_same_sharpening(self) -> None:
        prompt = ec.appraisal_prompt("ABSTRACT", "CLAIM")
        self.assertIn("BREVITY IS NOT A REASON", prompt)
        self.assertIn("IN SUBSTANCE", prompt)
        self.assertEqual(ec.APPRAISAL_PROMPT_VERSION, "claim-appraisal-v2")

    def test_the_version_was_bumped_and_stamped(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from common import load_records

        self.assertEqual(ap.APPRAISAL_VERSION, "1.2.0")
        for claim in load_records("claims"):
            if claim.get("appraisal"):
                with self.subTest(claim["id"]):
                    self.assertEqual(
                        claim["appraisal"]["appraisal_method"], ap.APPRAISAL_VERSION
                    )

    def test_a_measured_pass_records_the_rules_it_measured(self) -> None:
        # kappa 0.039 describes the anchor as it read in 1.1.0. Without
        # this stamp the number would later be read as describing the
        # sharpened one.
        for path in ea.completed_passes():
            protocol = json.loads(path.read_text(encoding="utf-8"))["protocol"]
            with self.subTest(path.name):
                self.assertTrue(protocol.get("appraisal_method_at_rating"))
        worksheet = ea.build_worksheet("catalog")
        self.assertEqual(
            worksheet["protocol"]["appraisal_method_at_rating"], ap.APPRAISAL_VERSION
        )

    def test_the_rules_version_reaches_the_report(self) -> None:
        for path in ea.completed_passes():
            for comparison in ea.second_rater_comparisons(path):
                with self.subTest(path.name, field=comparison.field):
                    self.assertIn("appraisal rules", comparison.provenance)

    def test_no_stored_judgement_changed(self) -> None:
        # The sharpening changed which of two readings the anchor
        # licenses, not the derivation. Every recorded value must still
        # validate and still hold the guardrails.
        sys.path.insert(0, str(ROOT / "scripts"))
        from common import load_records

        supported = 0
        for claim in load_records("claims"):
            block = claim.get("appraisal")
            if not block:
                continue
            with self.subTest(claim["id"]):
                self.assertEqual(ap.validate_appraisal(block), [])
                self.assertEqual(ap.certainty_conflicts(block), [])
            supported += block["claim_supported_by_source"] == "supported"
        self.assertEqual(supported, 57)


class CalibrationTests(unittest.TestCase):
    """A calibration round must not be mistakable for a baseline."""

    KEYS = ["prefill-handwriting-tablet", "prefill-adult-mooc", "prefill-policy-ai-ethics"]

    def _round(self, keys=None, fields=None):
        worksheet = ea.build_worksheet("claim_prefill", fields, keys or self.KEYS)
        primary = ea.primary_labels("claim_prefill")
        for item in worksheet["labels"]:
            for field in worksheet["protocol"]["rated_fields"]:
                item[field] = primary[item["key"]].get(field)
        worksheet["protocol"].update(rater="k", labeled_at="2026-08-10", blind=True)
        return worksheet

    def _score(self, worksheet):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "k.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            return ea.second_rater_comparisons(path)

    def test_only_narrows_the_items(self) -> None:
        worksheet = ea.build_worksheet("claim_prefill", None, self.KEYS)
        self.assertEqual(
            [item["key"] for item in worksheet["labels"]], self.KEYS
        )

    def test_a_calibration_round_is_never_a_baseline(self) -> None:
        # Perfect agreement on a hand-picked subset is not a ceiling: the
        # items were chosen to span the rubric, and they get discussed.
        for comparison in self._score(self._round()):
            with self.subTest(comparison.field):
                self.assertEqual(comparison.agreement, 1.0)
                self.assertTrue(comparison.independent)
                self.assertFalse(comparison.gate_ready())
                self.assertIn("calibration round", "\n".join(comparison.report()))

    def test_the_mark_blocks_the_gate_on_its_own(self) -> None:
        # A three-item round fails gate_ready() on size alone, so the test
        # above cannot tell "blocked because it is calibration" from
        # "blocked because it is small". This one can: same sample, well
        # over the size threshold, differing only in the mark.
        pairs = [("low", "low")] * 30 + [("moderate", "moderate")] * 30
        measured = ea.Comparison("t", "evidence_certainty", pairs, True, "x")
        calibration = ea.Comparison(
            "t", "evidence_certainty", pairs, True, "x", calibration=True
        )
        self.assertGreater(measured.n, ea.MIN_N_FOR_GATE)
        self.assertTrue(measured.gate_ready())
        self.assertFalse(calibration.gate_ready())

    def test_a_full_pass_is_not_marked_as_calibration(self) -> None:
        worksheet = ea.build_worksheet("claim_prefill")
        self.assertNotIn("calibration_subset", worksheet["protocol"])

    def test_an_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            ea.build_worksheet("claim_prefill", None, ["prefill-adult-mooc", "nope"])
        self.assertIn("nope", str(caught.exception))

    def test_explain_shows_both_answers_and_the_stored_reasoning(self) -> None:
        import tempfile

        worksheet = self._round()
        # Introduce one disagreement so the marker is exercised.
        worksheet["labels"][0]["evidence_certainty"] = "strong"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "k.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            report = "\n".join(ea.explain_report(path))
        self.assertIn("DISAGREE", report)
        self.assertIn("agree]", report)
        self.assertIn("<-- differs", report)
        # The reasoning is the point: without it a calibration round is a
        # list of differences with nobody in the room to ask why.
        self.assertIn("baseline", report)
        self.assertIn("why the stored evidence_certainty is", report)

    def test_explain_is_not_part_of_scoring(self) -> None:
        # Seeing the stored reasoning is exactly what must not happen
        # before a measured pass, so it takes a separate command.
        report = "\n".join(c.report()[0] for c in self._score(self._round()))
        self.assertNotIn("why the stored", report)

    def test_the_excluded_pairs_are_named_by_value(self) -> None:
        # The note used to say "e.g. 'unverifiable'" whatever had actually
        # been set aside -- telling the reader the wrong reason for a
        # number they cannot see.
        comparison = ea.Comparison(
            name="t",
            field="evidence_certainty",
            pairs=[("low", "low"), (None, None), ("unverifiable", "low")],
            independent=True,
            provenance="test",
        )
        report = "\n".join(comparison.report())
        self.assertIn("2 pair(s) excluded, holding null, unverifiable", report)


class CompletedPassTests(unittest.TestCase):
    """The measured baseline stored in eval/."""

    def test_the_default_report_picks_up_completed_passes(self) -> None:
        # Without this the summary kept printing "no comparison is usable
        # as a baseline yet" after a baseline had been measured and
        # committed -- the one sentence somebody would quote, saying the
        # opposite of the truth.
        paths = ea.completed_passes()
        self.assertTrue(paths, "expected a completed second-rater pass in eval/")
        for path in paths:
            with self.subTest(path.name):
                self.assertTrue(path.name.endswith("_second_rater_completed.json"))

    def test_blank_templates_are_never_swept_up(self) -> None:
        names = {path.name for path in ea.completed_passes()}
        self.assertNotIn("catalog_second_rater.json", names)
        self.assertNotIn("claim_prefill_second_rater.json", names)

    def test_the_stored_pass_declares_its_rater_and_date(self) -> None:
        for path in ea.completed_passes():
            protocol = json.loads(path.read_text(encoding="utf-8"))["protocol"]
            with self.subTest(path.name):
                self.assertTrue(protocol.get("rater"), "rater must be named")
                self.assertTrue(protocol.get("labeled_at"), "labeled_at must be set")

    def test_a_caveat_lives_in_notes_not_in_the_rater_name(self) -> None:
        # The summary prints the rater once per field; a paragraph there
        # buries the numbers it is meant to qualify.
        import tempfile

        worksheet = ea.build_worksheet("catalog")
        primary = ea.primary_labels("catalog")
        for item in worksheet["labels"]:
            for field in worksheet["protocol"]["rated_fields"]:
                item[field] = primary[item["key"]].get(field)
        worksheet["protocol"].update(
            rater="kurz", labeled_at="2026-08-14", blind=True, notes="ein langer Vorbehalt"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            path.write_text(json.dumps(worksheet), encoding="utf-8")
            comparison = ea.second_rater_comparisons(path)[0]
        self.assertIn("second rater kurz,", comparison.provenance)
        self.assertIn("note: ein langer Vorbehalt", comparison.provenance)

    def test_the_measured_pass_scores_as_a_baseline(self) -> None:
        for path in ea.completed_passes():
            for comparison in ea.second_rater_comparisons(path):
                with self.subTest(path=path.name, field=comparison.field):
                    self.assertGreaterEqual(comparison.n, ea.MIN_N_FOR_GATE)
                    self.assertTrue(comparison.gate_ready())


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
