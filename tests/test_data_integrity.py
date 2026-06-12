from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import filter_relevant_sources, load_records, normalize_title, score_relevance  # noqa: E402
from score_evidence import skill_score  # noqa: E402
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
            for claim_id in skill["supporting_claim_ids"]:
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
