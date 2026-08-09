"""Tests for the score contextualisation (scripts/score_context.py).

The composite evidence_score multiplies evidence quality per claim by a
breadth factor, so one number answers two questions at once. What must
hold for the contextualisation to be worth trusting:

- the decomposition explains the score it sits next to, exactly (a part
  that drifts from the total is worse than no part at all);
- a peer group too small to rank yields a stated reason, not a rank;
- candidate skills, whose 0.0 scores are placeholders, never enter a peer
  group and drag its median down;
- the plain-language note fires on real divergence and stays quiet
  otherwise;
- contextualising changes no score.
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

from common import load_records  # noqa: E402
from score_context import (  # noqa: E402
    MIN_PEER_GROUP,
    quality_vs_breadth_note,
    score_contexts,
)
from score_evidence import reviewed_claim_scores, score_breakdown, skill_score  # noqa: E402


def _skill(skill_id, claims, *, status="active", audience="learner", score=0.0, contra=()):
    return {
        "id": skill_id,
        "status": status,
        "audience": audience,
        "evidence_score": score,
        "supporting_claim_ids": list(claims),
        "contradicting_claim_ids": list(contra),
    }


class BreakdownTests(unittest.TestCase):
    def test_the_parts_reproduce_the_total_they_explain(self) -> None:
        # Swept across claim counts 1..8 because the breadth factor takes a
        # different value at each one (0.75, 0.80, ... 1.00) and saturates at 6.
        # A single count would leave most of those values untested -- and a
        # coarser rounding of the factor would still pass on the ones that
        # happen to be short decimals.
        for count in range(1, 9):
            for quality in (0.333, 0.5, 0.777, 0.828):
                with self.subTest(count=count, quality=quality):
                    scores = {f"c{i}": quality for i in range(count)}
                    scores["contra"] = 0.5
                    skill = _skill("s", list(scores)[:count], contra=["contra"])
                    parts = score_breakdown(skill, scores)
                    rebuilt = round(
                        max(
                            0.0,
                            min(
                                1.0,
                                parts["claim_quality"] * parts["breadth_factor"]
                                - parts["contradiction_penalty"],
                            ),
                        ),
                        2,
                    )
                    self.assertEqual(rebuilt, parts["evidence_score"])
                    self.assertEqual(parts["evidence_score"], skill_score(skill, scores))

    def test_every_active_skill_in_the_catalogue_is_explained_by_its_parts(self) -> None:
        # The guarantee that matters in production: what the dashboard prints
        # next to a stored score actually adds up to that stored score.
        sources = {source["id"]: source for source in load_records("sources")}
        scores = reviewed_claim_scores(load_records("claims"), sources)
        active = [skill for skill in load_records("skills") if skill["status"] == "active"]
        self.assertGreater(len(active), 0)
        for skill in active:
            parts = score_breakdown(skill, scores)
            self.assertEqual(parts["evidence_score"], skill["evidence_score"], skill["id"])
            self.assertEqual(parts["supporting_claims"], len(skill["supporting_claim_ids"]))

    def test_a_skill_without_reviewed_claims_has_no_parts_to_show(self) -> None:
        parts = score_breakdown(_skill("s", []), {})
        self.assertIsNone(parts["claim_quality"])
        self.assertIsNone(parts["breadth_factor"])
        self.assertEqual(parts["evidence_score"], 0.0)


class PeerGroupTests(unittest.TestCase):
    def _group(self, size, audience="learner"):
        # Ids carry the audience so two groups in one call cannot collide --
        # score_contexts is keyed by skill id, and duplicates would overwrite.
        prefix = "s" if audience == "learner" else "e"
        return [
            _skill(f"{prefix}{i}", ["c"], audience=audience, score=round(0.5 + i / 100, 2))
            for i in range(size)
        ]

    def test_a_group_below_the_minimum_gets_a_reason_instead_of_a_rank(self) -> None:
        skills = self._group(MIN_PEER_GROUP - 1)
        contexts = score_contexts(skills, {"c": 0.7})
        for context in contexts.values():
            self.assertIsNone(context["rank"])
            self.assertIn("Rangangabe", context["rank_note"])
        # One more member and ranking becomes meaningful.
        bigger = score_contexts(self._group(MIN_PEER_GROUP), {"c": 0.7})
        self.assertTrue(all(context["rank"] for context in bigger.values()))

    def test_tied_scores_share_a_rank(self) -> None:
        skills = [_skill(f"s{i}", ["c"], score=0.7) for i in range(MIN_PEER_GROUP)]
        skills[0]["evidence_score"] = 0.9
        contexts = score_contexts(skills, {"c": 0.7})
        self.assertEqual(contexts["s0"]["rank"], 1)
        # Everyone else is tied on 0.7 and must share rank 2 rather than being
        # ordered by position in the file.
        self.assertEqual({contexts[f"s{i}"]["rank"] for i in range(1, MIN_PEER_GROUP)}, {2})

    def test_candidates_do_not_enter_the_peer_group(self) -> None:
        # cluster_claims.py creates candidates at evidence_score 0.0. Counting
        # them would drag the median toward zero and flatter every active skill.
        active = [_skill(f"a{i}", ["c"], score=0.7) for i in range(MIN_PEER_GROUP)]
        candidates = [_skill(f"c{i}", [], status="candidate") for i in range(20)]
        contexts = score_contexts(active + candidates, {"c": 0.7})
        self.assertEqual(contexts["a0"]["peer_group_size"], MIN_PEER_GROUP)
        self.assertEqual(contexts["a0"]["peer_group_median"], 0.7)
        self.assertIsNone(contexts["c0"]["rank"])
        self.assertIn("aktive", contexts["c0"]["rank_note"])

    def test_learner_and_educator_are_separate_groups(self) -> None:
        skills = self._group(MIN_PEER_GROUP) + self._group(2, audience="educator")
        contexts = score_contexts(skills, {"c": 0.7})
        self.assertEqual(contexts["s0"]["peer_group"], "learner")
        self.assertEqual(contexts["s0"]["peer_group_size"], MIN_PEER_GROUP)
        # The educator group keeps its own (too small) size rather than being
        # pooled into one global ranking.
        educator = [c for c in contexts.values() if c["peer_group"] == "educator"]
        self.assertTrue(educator)
        self.assertEqual(educator[0]["peer_group_size"], 2)

    def test_a_skill_without_an_audience_field_counts_as_learner(self) -> None:
        skill = {
            "id": "s",
            "status": "active",
            "evidence_score": 0.7,
            "supporting_claim_ids": ["c"],
        }
        self.assertEqual(score_contexts([skill], {"c": 0.7})["s"]["peer_group"], "learner")


class NoteTests(unittest.TestCase):
    def test_note_fires_when_strong_evidence_is_held_down_by_a_short_path(self) -> None:
        note = quality_vs_breadth_note({"claim_quality": 0.83, "supporting_claims": 2})
        self.assertIsNotNone(note)
        self.assertIn("dünne Beleglage", note)

    def test_note_fires_when_a_broad_path_carries_weak_claims(self) -> None:
        note = quality_vs_breadth_note({"claim_quality": 0.64, "supporting_claims": 6})
        self.assertIsNotNone(note)
        # At six claims the breadth factor is exactly 1.0, so the score is the
        # claim quality undamped. The note must say that rather than claim the
        # score rests on quantity -- true under method 1.0.0, overstated since
        # 1.1.0 narrowed the factor to 0.875..1.00.
        self.assertIn("nicht durch eine dünne Beleglage gedämpft", note)
        self.assertNotIn("ruht", note)

    def test_note_stays_quiet_when_quality_and_breadth_agree(self) -> None:
        # Wallpaper is not context: a note on every skill would stop being read.
        self.assertIsNone(quality_vs_breadth_note({"claim_quality": 0.72, "supporting_claims": 5}))
        self.assertIsNone(quality_vs_breadth_note({"claim_quality": 0.80, "supporting_claims": 8}))
        self.assertIsNone(quality_vs_breadth_note({"claim_quality": None, "supporting_claims": 0}))


class BuildIntegrationTests(unittest.TestCase):
    def test_context_ships_in_the_index_without_changing_any_score(self) -> None:
        import build_site

        index = build_site.build_index()
        stored = {skill["id"]: skill["evidence_score"] for skill in load_records("skills")}
        for skill in index["skills"]:
            self.assertIn("score_context", skill)
            context = skill["score_context"]
            self.assertIn("note", context)
            self.assertEqual(context["evidence_score"], stored[skill["id"]], skill["id"])
            self.assertEqual(skill["evidence_score"], stored[skill["id"]], skill["id"])

    def test_context_is_not_written_back_into_the_versioned_records(self) -> None:
        # Derived values belong in the build output; a second stored copy is a
        # second thing that can drift from the formula.
        for path in (ROOT / "data" / "skills").glob("*.json"):
            for skill in json.loads(path.read_text(encoding="utf-8")):
                self.assertNotIn("score_context", skill, f"{path.name}:{skill['id']}")


if __name__ == "__main__":
    unittest.main()
