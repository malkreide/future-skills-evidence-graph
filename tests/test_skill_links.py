"""Tests for the optional skill-link suggestion (scripts/extract_claims.py).

A claim only becomes 'reviewed' once it links a skill, so this suggestion sits
close to a decision that shapes the evidence graph. What must hold:

- with AI off the path is completely inert (no skill file read, no assist key),
  so the LLM-free pipeline stays byte-identical;
- a hallucinated or stale skill id never reaches an assist block;
- the suggestion is advisory — the real link fields stay empty;
- only ACTIVE skills are offered, and the prompt renders reproducibly.

Every model call is mocked; nothing here touches the network.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jsonschema import Draft202012Validator  # noqa: E402

import ai_provider  # noqa: E402
import extract_claims as ec  # noqa: E402

CATALOGUE = [
    {
        "id": "skill-ai-literacy",
        "name": "AI Literacy",
        "definition": "Understanding and critically using AI systems.",
        "audience": "learner",
    },
    {
        "id": "skill-data-literacy",
        "name": "Data Literacy",
        "definition": "Reading, interpreting and questioning data.",
        "audience": "learner",
    },
]

ABSTRACT = "A classroom study of AI literacy lessons in primary schools."
STATEMENT = "We find that AI literacy lessons improve critical evaluation of outputs."
TOPICS = ["ai literacy"]


def complete_returning(payload):
    """Patch ai_provider.complete to return *payload*, with AI switched on."""
    return mock.patch.multiple(
        ai_provider,
        complete=mock.Mock(return_value=payload),
        ai_provider=mock.Mock(return_value="cache"),
    )


class SkillLinkSuggestionTest(unittest.TestCase):
    def test_off_by_default_is_fully_inert(self) -> None:
        """AI off must not even read the skill catalogue."""
        with mock.patch.object(ai_provider, "ai_provider", return_value="none"), \
                mock.patch.object(ec, "skill_catalogue") as catalogue:
            self.assertIsNone(ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS))
            catalogue.assert_not_called()

    def test_known_ids_are_kept(self) -> None:
        payload = {"supports_skill_ids": ["skill-ai-literacy"], "contradicts_skill_ids": []}
        with complete_returning(payload):
            links = ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        self.assertEqual(links, {"supports_skill_ids": ["skill-ai-literacy"],
                                 "contradicts_skill_ids": []})

    def test_hallucinated_id_is_dropped(self) -> None:
        """An id outside the catalogue must never reach a reviewer."""
        payload = {
            "supports_skill_ids": ["skill-ai-literacy", "skill-does-not-exist"],
            "contradicts_skill_ids": ["skill-invented"],
        }
        with complete_returning(payload):
            links = ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        self.assertEqual(links["supports_skill_ids"], ["skill-ai-literacy"])
        self.assertEqual(links["contradicts_skill_ids"], [])

    def test_only_hallucinated_ids_yields_no_suggestion(self) -> None:
        payload = {"supports_skill_ids": ["skill-invented"], "contradicts_skill_ids": []}
        with complete_returning(payload):
            self.assertIsNone(ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE))

    def test_duplicate_ids_are_collapsed(self) -> None:
        payload = {
            "supports_skill_ids": ["skill-ai-literacy", "skill-ai-literacy"],
            "contradicts_skill_ids": [],
        }
        with complete_returning(payload):
            links = ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        self.assertEqual(links["supports_skill_ids"], ["skill-ai-literacy"])

    def test_malformed_response_is_survivable(self) -> None:
        for payload in (None, "not a dict", {"supports_skill_ids": "nope"}, {}):
            with self.subTest(payload=payload), complete_returning(payload):
                self.assertIsNone(
                    ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
                )

    def test_contradicting_link_is_carried_through(self) -> None:
        """Contradicting evidence is what score_evidence.py penalises; keep it."""
        payload = {
            "supports_skill_ids": [],
            "contradicts_skill_ids": ["skill-data-literacy"],
        }
        with complete_returning(payload):
            links = ec.suggest_skill_links(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        self.assertEqual(links["contradicts_skill_ids"], ["skill-data-literacy"])


class SkillCataloguePromptTest(unittest.TestCase):
    def test_prompt_lists_every_permitted_id(self) -> None:
        prompt = ec.skill_link_prompt(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        for entry in CATALOGUE:
            self.assertIn(entry["id"], prompt)

    def test_prompt_is_reproducible(self) -> None:
        """A stable prompt is what makes the fixture cache replayable."""
        first = ec.skill_link_prompt(ABSTRACT, STATEMENT, TOPICS, CATALOGUE)
        second = ec.skill_link_prompt(ABSTRACT, STATEMENT, TOPICS, list(reversed(CATALOGUE)))
        self.assertNotEqual(first, second, "catalogue order is rendered verbatim")
        self.assertEqual(first, ec.skill_link_prompt(ABSTRACT, STATEMENT, TOPICS, CATALOGUE))

    def test_catalogue_offers_only_active_skills(self) -> None:
        catalogue = ec.skill_catalogue(refresh=True)
        self.assertTrue(catalogue, "the repository should ship active skills")
        active = {
            skill["id"]
            for skill in ec.load_records("skills")
            if skill.get("status") == "active"
        }
        self.assertEqual({entry["id"] for entry in catalogue}, active)

    def test_catalogue_is_sorted_for_a_stable_hash(self) -> None:
        catalogue = ec.skill_catalogue(refresh=True)
        self.assertEqual([e["id"] for e in catalogue], sorted(e["id"] for e in catalogue))


class AssistBlockShapeTest(unittest.TestCase):
    """The assist block a reviewer reads must stay schema-valid and advisory."""

    def validator(self) -> Draft202012Validator:
        schema = json.loads((ROOT / "schemas" / "claim.schema.json").read_text())
        return Draft202012Validator(schema)

    def test_skill_links_block_validates(self) -> None:
        block = {
            "supports_skill_ids": ["skill-ai-literacy"],
            "contradicts_skill_ids": [],
            "provenance": {
                "model": "claude-opus-4-8",
                "prompt_version": ec.SKILL_LINK_PROMPT_VERSION,
                "created_at": "2026-01-01",
            },
        }
        claim = {
            "id": "claim-example",
            "statement": "A finding sentence long enough to pass.",
            "source_ids": ["src-example"],
            "text_anchor": 'abstract, sentence 1: "A finding sentence long enough to pass."',
            "context": "ctx",
            "age_range": "6-12",
            "outcome": "out",
            "evidence_type": "empirical_study",
            "evidence_strength": "low",
            "supports_skill_ids": [],
            "contradicts_skill_ids": [],
            "status": "candidate",
            "created_at": "2026-01-01",
            "assist": {"skill_links": block},
        }
        self.assertEqual(list(self.validator().iter_errors(claim)), [])

    def test_suggestion_does_not_populate_the_real_link_fields(self) -> None:
        """Advisory means advisory: promotion still needs an explicit --supports."""
        source = {
            "id": "src-example",
            "source_type": "journal_article",
            "abstract": (
                "We studied AI literacy lessons in primary classrooms. "
                "We find that structured lessons improve pupils' critical evaluation "
                "of machine-generated outputs across the reviewed schools."
            ),
        }
        payload = {"supports_skill_ids": ["skill-ai-literacy"], "contradicts_skill_ids": []}
        with mock.patch.object(ai_provider, "ai_provider", return_value="cache"), \
                mock.patch.object(ai_provider, "complete", return_value=payload), \
                mock.patch.object(ec, "suggest_claim_fields", return_value=None), \
                mock.patch.object(ec, "skill_catalogue", return_value=CATALOGUE):
            claims = ec.claims_from_source(source)
        self.assertTrue(claims, "the abstract should yield a candidate claim")
        claim = claims[0]
        self.assertEqual(claim["supports_skill_ids"], [])
        self.assertEqual(claim["contradicts_skill_ids"], [])
        self.assertEqual(
            claim["assist"]["skill_links"]["supports_skill_ids"], ["skill-ai-literacy"]
        )


class GoldenSetGovernanceTest(unittest.TestCase):
    """An unreviewed golden set must never be able to gate CI."""

    def payload(self) -> dict:
        return json.loads((ROOT / "eval" / "skill_link_labeled.json").read_text())

    def test_gate_is_refused_while_unreviewed(self) -> None:
        import eval_skill_links as esl

        payload = self.payload()
        self.assertFalse(esl.is_reviewed(payload))
        with mock.patch.object(sys, "argv", ["eval_skill_links.py", "--min-precision", "0.8"]):
            self.assertEqual(esl.main(), 1)

    def test_report_without_a_gate_still_runs(self) -> None:
        import eval_skill_links as esl

        with mock.patch.object(sys, "argv", ["eval_skill_links.py"]):
            self.assertEqual(esl.main(), 0)

    def test_every_gold_id_exists_in_the_catalogue(self) -> None:
        """A gold label pointing at a non-existent skill would be unreachable."""
        known = {entry["id"] for entry in ec.skill_catalogue(refresh=True)}
        for example in self.payload()["examples"]:
            for name in ec.SKILL_LINK_FIELDS:
                for identifier in example["gold"].get(name, []):
                    with self.subTest(example=example["id"], skill=identifier):
                        self.assertIn(identifier, known)

    def test_examples_match_the_prefill_golden_set(self) -> None:
        """Inputs are referenced by id, so the two sets must stay aligned."""
        prefill = json.loads((ROOT / "eval" / "claim_prefill_labeled.json").read_text())
        self.assertEqual(
            [e["id"] for e in self.payload()["examples"]],
            [e["id"] for e in prefill["examples"]],
        )


if __name__ == "__main__":
    unittest.main()
