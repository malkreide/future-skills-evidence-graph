from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator  # noqa: E402

from cluster_claims import cluster_candidate_skills  # noqa: E402
from common import (  # noqa: E402
    append_candidate_sources,
    filter_new_claims,
    filter_new_sources,
    filter_relevant_sources,
    load_json,
    load_records,
    normalize_title,
    score_relevance,
    write_json,
)
from extract_claims import (  # noqa: E402
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    OUTCOME_PLACEHOLDER,
    claim_from_source,
)
from promote_candidate import claim_review_errors, skill_activation_errors  # noqa: E402
from score_evidence import reviewed_claim_scores, skill_score  # noqa: E402
from validate_data import validate_repository  # noqa: E402


class DataIntegrityTests(unittest.TestCase):
    def test_repository_validates(self) -> None:
        self.assertEqual(validate_repository(), [])

    def test_active_skills_have_reviewed_evidence_path(self) -> None:
        claims = {claim["id"]: claim for claim in load_records("claims")}
        sources = {source["id"]: source for source in load_records("sources")}
        for skill in load_records("skills"):
            if skill["status"] != "active":
                continue
            self.assertGreater(len(skill["supporting_claim_ids"]), 0, skill["id"])
            referenced = skill["supporting_claim_ids"] + skill.get("contradicting_claim_ids", [])
            for claim_id in referenced:
                claim = claims[claim_id]
                self.assertEqual(claim["status"], "reviewed", claim_id)
                for source_id in claim["source_ids"]:
                    self.assertIn(source_id, sources)
                    self.assertEqual(sources[source_id]["status"], "reviewed", source_id)

    def test_skill_score_rewards_breadth_and_penalizes_contradictions(self) -> None:
        claim_scores = {"c1": 0.8, "c2": 0.8, "c3": 0.6}
        narrow = {"supporting_claim_ids": ["c1"]}
        broad = {"supporting_claim_ids": ["c1", "c2"]}
        contradicted = {"supporting_claim_ids": ["c1"], "contradicting_claim_ids": ["c3"]}
        unsupported = {"supporting_claim_ids": []}
        self.assertGreater(skill_score(broad, claim_scores), skill_score(narrow, claim_scores))
        self.assertGreater(skill_score(narrow, claim_scores), skill_score(contradicted, claim_scores))
        self.assertEqual(skill_score(unsupported, claim_scores), 0.0)
        self.assertEqual(skill_score(broad, claim_scores), skill_score(broad, claim_scores))

    def test_scoring_excludes_unreviewed_claims(self) -> None:
        sources = {"src-1": {"id": "src-1", "source_type": "systematic_review"}}
        claims = [
            {"id": "c-reviewed", "status": "reviewed", "evidence_strength": "strong", "source_ids": ["src-1"]},
            {"id": "c-candidate", "status": "candidate", "evidence_strength": "strong", "source_ids": ["src-1"]},
            {"id": "c-rejected", "status": "rejected", "evidence_strength": "strong", "source_ids": ["src-1"]},
        ]
        scores = reviewed_claim_scores(claims, sources)
        self.assertEqual(set(scores), {"c-reviewed"})

        clean = {"supporting_claim_ids": ["c-reviewed"]}
        inflated = {"supporting_claim_ids": ["c-reviewed", "c-candidate", "c-rejected"]}
        self.assertEqual(skill_score(inflated, scores), skill_score(clean, scores))

        contradicted = {
            "supporting_claim_ids": ["c-reviewed"],
            "contradicting_claim_ids": ["c-candidate"],
        }
        self.assertEqual(skill_score(contradicted, scores), skill_score(clean, scores))

    def test_relevance_scoring_separates_scope_from_noise(self) -> None:
        relevant = {
            "title": "AI literacy and critical thinking for children in primary school",
            "abstract": "We study how students develop competence with artificial intelligence.",
        }
        irrelevant = {
            "title": "Lattice simulations of quantum chromodynamics",
            "abstract": "We present improved gauge field configurations.",
        }
        relevant_score, relevant_topics = score_relevance(relevant)
        irrelevant_score, irrelevant_topics = score_relevance(irrelevant)
        self.assertGreaterEqual(relevant_score, 0.3)
        self.assertIn("ai literacy", relevant_topics)
        self.assertIn("critical thinking", relevant_topics)
        self.assertLess(irrelevant_score, 0.3)
        self.assertEqual(irrelevant_topics, [])

        kept = filter_relevant_sources([dict(relevant), dict(irrelevant)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title"], relevant["title"])
        self.assertEqual(kept[0]["relevance_score"], relevant_score)
        self.assertEqual(kept[0]["topics"], relevant_topics)

    def test_filter_new_sources_avoids_id_collisions(self) -> None:
        existing_id = load_records("sources")[0]["id"]
        candidates = [
            {
                "id": existing_id,
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            {
                "id": existing_id,
                "title": "A unique candidate title beta",
                "url": "https://example.test/beta",
                "year": 2026,
            },
        ]
        kept = filter_new_sources(candidates)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0]["id"], f"{existing_id}-2")
        self.assertEqual(kept[1]["id"], f"{existing_id}-3")

    def test_append_candidate_sources_preserves_earlier_batches(self) -> None:
        week_one = [
            {
                "id": "src-alpha",
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            {
                "id": "src-beta",
                "title": "A unique candidate title beta",
                "url": "https://example.test/beta",
                "year": 2026,
            },
        ]
        week_two = [
            # Duplicate of an existing record: must not be appended again.
            {
                "id": "src-alpha-dup",
                "title": "A unique candidate title alpha",
                "url": "https://example.test/alpha",
                "year": 2026,
            },
            # Id collision with an existing record: must get a suffix.
            {
                "id": "src-beta",
                "title": "A unique candidate title gamma",
                "url": "https://example.test/gamma",
                "year": 2026,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates-test.json"
            write_json(path, week_one)
            appended = append_candidate_sources(path, week_two)
            self.assertEqual(len(appended), 1)
            self.assertEqual(appended[0]["id"], "src-beta-2")
            stored = load_json(path)
            self.assertEqual(
                [record["id"] for record in stored],
                ["src-alpha", "src-beta", "src-beta-2"],
            )

    def test_append_candidate_sources_skips_empty_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "candidates-empty.json"
            self.assertEqual(append_candidate_sources(missing, []), [])
            self.assertFalse(missing.exists())

            existing = Path(tmp) / "candidates-existing.json"
            records = [
                {
                    "id": "src-alpha",
                    "title": "A unique candidate title alpha",
                    "url": "https://example.test/alpha",
                    "year": 2026,
                }
            ]
            write_json(existing, records)
            before = existing.stat().st_mtime_ns
            self.assertEqual(append_candidate_sources(existing, []), [])
            self.assertEqual(existing.stat().st_mtime_ns, before)
            self.assertEqual(load_json(existing), records)

    def test_claim_extraction_uses_verbatim_text_anchor(self) -> None:
        source = {
            "id": "src-test-ai-literacy",
            "source_type": "systematic_review",
            "status": "candidate",
            "abstract": (
                "Background remarks describing the structure of this paper come first. "
                "We find that AI literacy instruction improves critical thinking among "
                "primary school students. Short note."
            ),
        }
        claim = claim_from_source(source)
        self.assertIsNotNone(claim)
        self.assertEqual(
            claim["statement"],
            "We find that AI literacy instruction improves critical thinking among "
            "primary school students.",
        )
        self.assertIn('sentence 2: "We find that AI literacy', claim["text_anchor"])
        self.assertEqual(claim["source_ids"], ["src-test-ai-literacy"])
        self.assertEqual(claim["evidence_type"], "systematic_review")
        self.assertEqual(claim["evidence_strength"], "low")
        self.assertEqual(claim["status"], "candidate")
        schema = load_json(ROOT / "schemas" / "claim.schema.json")
        Draft202012Validator(schema).validate(claim)

        self.assertIsNone(claim_from_source({"id": "src-x", "abstract": None}))
        self.assertIsNone(
            claim_from_source(
                {
                    "id": "src-x",
                    "abstract": "Lattice quantum chromodynamics simulations with improved gauge actions.",
                }
            )
        )

    def test_filter_new_claims_drops_known_statements(self) -> None:
        existing = load_records("claims")[0]
        duplicate = {
            "id": "claim-duplicate-statement",
            "statement": existing["statement"],
        }
        colliding = {
            "id": existing["id"],
            "statement": "A genuinely new candidate claim statement about creativity.",
        }
        kept = filter_new_claims([duplicate, colliding])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], f"{existing['id']}-2")

    def test_clustering_proposes_skills_only_for_uncovered_topics(self) -> None:
        claims = [
            {
                "id": "claim-a",
                "status": "candidate",
                "statement": "Creativity training fosters creative thinking in students.",
            },
            {
                "id": "claim-b",
                "status": "candidate",
                "statement": "Creative problem solving practice benefits pupils in classrooms.",
            },
            {
                "id": "claim-c",
                "status": "reviewed",
                "statement": "Creativity also appears in reviewed claims about schools.",
            },
        ]
        proposals, hints = cluster_candidate_skills(claims, [], min_claims=2)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["id"], "skill-creativity")
        self.assertEqual(proposals[0]["status"], "candidate")
        self.assertEqual(proposals[0]["evidence_score"], 0.0)
        self.assertEqual(proposals[0]["supporting_claim_ids"], ["claim-a", "claim-b"])
        schema = load_json(ROOT / "schemas" / "skill.schema.json")
        Draft202012Validator(schema).validate(proposals[0])
        self.assertEqual(hints, [])

        existing_skill = {"id": "skill-creative-problem-solving", "topics": ["creativity"]}
        proposals, hints = cluster_candidate_skills(claims, [existing_skill], min_claims=2)
        self.assertEqual(proposals, [])
        self.assertEqual(
            hints,
            [("creativity", "skill-creative-problem-solving", ["claim-a", "claim-b"])],
        )

    def test_claim_review_gate_blocks_placeholders_and_dangling_refs(self) -> None:
        extracted = claim_from_source(
            {
                "id": "src-gate",
                "source_type": "empirical_study",
                "status": "candidate",
                "abstract": "AI literacy instruction improves critical thinking for primary school students here.",
            }
        )
        # As extracted: placeholders for context/age/outcome, no skill link.
        errors = claim_review_errors(extracted, skill_ids=set(), source_ids={"src-gate"})
        joined = " | ".join(errors)
        self.assertIn("context", joined)
        self.assertIn("age_range", joined)
        self.assertIn("outcome", joined)
        self.assertIn("link at least one skill", joined)

        # Reviewer fills the fields but points at a skill and source that do not exist.
        extracted.update(
            context="K-12 classroom study",
            age_range="6-12",
            outcome="Learners critique AI outputs",
            supports_skill_ids=["skill-missing"],
        )
        errors = claim_review_errors(extracted, skill_ids=set(), source_ids=set())
        self.assertEqual(
            sorted(errors),
            ["references missing skill skill-missing", "references missing source src-gate"],
        )

        # Everything resolvable -> no errors.
        self.assertEqual(
            claim_review_errors(extracted, skill_ids={"skill-missing"}, source_ids={"src-gate"}),
            [],
        )

    def test_skill_activation_gate_requires_definition_and_reviewed_claims(self) -> None:
        candidate = {
            "definition": "Candidate skill clustered from 2 candidate claims about ethics. "
            "Definition requires human review.",
            "supporting_claim_ids": ["claim-x"],
            "contradicting_claim_ids": [],
        }
        claims = {"claim-x": {"id": "claim-x", "status": "candidate"}}
        errors = skill_activation_errors(candidate, claims)
        joined = " | ".join(errors)
        self.assertIn("definition still holds a placeholder", joined)
        self.assertIn("claim-x is candidate", joined)

        candidate["definition"] = "Ability to reason about the ethics of technology use."
        claims["claim-x"]["status"] = "reviewed"
        self.assertEqual(skill_activation_errors(candidate, claims), [])

        # An empty supporting set is rejected even with a real definition.
        self.assertIn(
            "needs at least one supporting claim",
            " | ".join(skill_activation_errors({"definition": "Real definition text here.",
                                                 "supporting_claim_ids": []}, claims)),
        )

    def test_extracted_claim_fields_are_recognized_as_placeholders(self) -> None:
        # Guards against the generators and the review gate drifting apart.
        claim = claim_from_source(
            {
                "id": "src-drift",
                "source_type": "systematic_review",
                "status": "candidate",
                "abstract": "Digital literacy education supports media literacy for adolescent learners in schools.",
            }
        )
        self.assertTrue(claim["context"].endswith(CONTEXT_PLACEHOLDER_SUFFIX))
        self.assertEqual(claim["age_range"], AGE_RANGE_PLACEHOLDER)
        self.assertEqual(claim["outcome"], OUTCOME_PLACEHOLDER)
        errors = claim_review_errors(claim, skill_ids=set(), source_ids={"src-drift"})
        self.assertTrue(any("context" in error for error in errors))
        self.assertTrue(any("age_range" in error for error in errors))
        self.assertTrue(any("outcome" in error for error in errors))

    def test_normalize_title_is_deduplication_friendly(self) -> None:
        self.assertEqual(
            normalize_title("AI Literacy: Future-Skills in Education!"),
            normalize_title("ai literacy future skills in education"),
        )

    def test_lehrplan21_mappings_have_coverage_metadata(self) -> None:
        all_skills = load_records("skills")
        skills = {skill["id"] for skill in all_skills}
        active_skills = {skill["id"] for skill in all_skills if skill["status"] == "active"}
        mappings = [
            mapping
            for mapping in load_records("frameworks")
            if mapping.get("framework_group") == "Lehrplan 21"
        ]
        mapped_skills = {mapping["skill_id"] for mapping in mappings}
        self.assertLessEqual(
            active_skills,
            mapped_skills,
            f"active skills without Lehrplan 21 mapping: {sorted(active_skills - mapped_skills)}",
        )
        for mapping in mappings:
            self.assertIn(mapping["skill_id"], skills)
            self.assertGreaterEqual(mapping["coverage_score"], 0)
            self.assertLessEqual(mapping["coverage_score"], 3)
            self.assertIn(mapping["coverage_label"], {"gut abgedeckt", "teilweise", "Zukunftsluecke"})
            self.assertTrue(mapping["cycles"])
            self.assertTrue(mapping["evidence_path"])


if __name__ == "__main__":
    unittest.main()
