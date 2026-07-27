"""Tests for the claim pre-fill scorers (scripts/eval_claim_prefill.py).

The eval harness decides whether a reviewer can trust an AI suggestion, so the
ruler itself needs to be pinned down. These tests lock in three things:

- the semantic scorer accepts a faithful paraphrase and still rejects an
  unrelated sentence (the property token overlap could not deliver);
- it degrades to the lexical scorer whenever embeddings are unavailable or do
  not cover a text, so a missing provider never fails the run;
- the committed embedding fixtures actually cover the golden set, which is what
  keeps CI offline and deterministic.

No model is ever loaded: the semantic cases use hand-built vectors, and the
fixture-coverage test only reads the committed cache.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_provider  # noqa: E402
import common  # noqa: E402
import eval_claim_prefill as ecp  # noqa: E402


def unit(vector: list[float]) -> list[float]:
    """L2-normalize, matching what ai_provider.embed returns."""
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


# A paraphrase pair (cosine ~0.99) and an unrelated one (cosine 0.0), so the
# threshold is exercised from both sides without touching a real model.
PARAPHRASE_A = unit([1.0, 0.0, 0.0])
PARAPHRASE_B = unit([0.99, 0.14, 0.0])
UNRELATED = unit([0.0, 0.0, 1.0])


class SemanticTextScoringTest(unittest.TestCase):
    def test_paraphrase_counts_as_agreement(self) -> None:
        embeddings = {"gold text": PARAPHRASE_A, "model text": PARAPHRASE_B}
        self.assertTrue(
            ecp._values_match("outcome", "gold text", "model text", embeddings)
        )

    def test_unrelated_text_is_still_rejected(self) -> None:
        """The scorer must separate meaning, not just wave every sentence through."""
        embeddings = {"gold text": PARAPHRASE_A, "model text": UNRELATED}
        self.assertFalse(
            ecp._values_match("outcome", "gold text", "model text", embeddings)
        )

    def test_threshold_is_the_decision_boundary(self) -> None:
        above = ecp.SEMANTIC_MATCH_THRESHOLD + 0.02
        below = ecp.SEMANTIC_MATCH_THRESHOLD - 0.02
        for similarity, expected in ((above, True), (below, False)):
            with self.subTest(similarity=similarity):
                # Build a second unit vector at exactly the wanted cosine to [1,0].
                embeddings = {
                    "a": unit([1.0, 0.0]),
                    "b": [similarity, math.sqrt(max(0.0, 1 - similarity**2))],
                }
                self.assertIs(
                    ecp._texts_match_semantically("a", "b", embeddings), expected
                )

    def test_uncovered_text_falls_back_to_lexical(self) -> None:
        """A text with no vector must not silently score as a mismatch."""
        embeddings = {"gold text": PARAPHRASE_A}  # 'model text' deliberately absent
        self.assertIsNone(
            ecp._texts_match_semantically("gold text", "model text", embeddings)
        )
        # Identical strings still agree, because _values_match drops to Jaccard.
        self.assertTrue(
            ecp._values_match("outcome", "same words here", "same words here", embeddings)
        )

    def test_structured_fields_ignore_embeddings(self) -> None:
        """age_range/evidence_strength keep their own matchers regardless."""
        embeddings = {"low": PARAPHRASE_A, "high": PARAPHRASE_B}
        self.assertFalse(
            ecp._values_match("evidence_strength", "low", "high", embeddings)
        )
        self.assertTrue(ecp._values_match("age_range", "6-12", "6-12", embeddings))


class EmbeddingAvailabilityTest(unittest.TestCase):
    def test_no_provider_yields_no_embeddings(self) -> None:
        """Without a provider the harness reports None and uses the lexical scorer."""
        examples = ecp.load_examples()
        with mock.patch.object(ai_provider, "embed", return_value=None):
            self.assertIsNone(ecp.load_embeddings(examples))

    def test_short_batch_is_refused_rather_than_misaligned(self) -> None:
        """A partial embed() result would pair texts with the wrong vectors."""
        examples = ecp.load_examples()
        with mock.patch.object(ai_provider, "embed", return_value=[PARAPHRASE_A]):
            self.assertIsNone(ecp.load_embeddings(examples))


class EvidenceStrengthVocabularyTest(unittest.TestCase):
    """One vocabulary, everywhere.

    The prompts used to ask for {low, moderate, high} while the data model
    accepted {low, moderate, strong}, so the strongest suggestion named a value
    the schema does not know. These tests pin every spelling to the schema.
    """

    def schema_values(self) -> list[str]:
        schema = ecp.load_json(ROOT / "schemas" / "claim.schema.json")
        return schema["properties"]["evidence_strength"]["enum"]

    def test_constant_matches_the_claim_schema(self) -> None:
        self.assertEqual(list(common.EVIDENCE_STRENGTH_VALUES), self.schema_values())

    def test_prefill_schema_offers_exactly_those_values_plus_null(self) -> None:
        enum = ecp.PREFILL_OUTPUT_SCHEMA["properties"]["evidence_strength"]["enum"]
        self.assertEqual(enum, [*self.schema_values(), None])

    def test_prompt_never_names_a_value_the_data_model_rejects(self) -> None:
        prompt = ecp.prefill_prompt("An abstract.", "A finding sentence.", ["ai literacy"])
        self.assertIn("strong", prompt)
        # 'high' must not appear as a strength option any more. It may only
        # survive inside unrelated words ('high-ability'), so check word-bounded.
        self.assertNotRegex(prompt, r"\bhigh\b")

    def test_golden_set_uses_the_schema_vocabulary(self) -> None:
        allowed = set(self.schema_values()) | {None}
        for example in ecp.load_examples():
            for key in ("gold", "_recorded"):
                value = (example.get(key) or {}).get("evidence_strength")
                with self.subTest(example=example["id"], field=key):
                    self.assertIn(value, allowed)


class EmbeddingFixtureCoverageTest(unittest.TestCase):
    """CI stays offline only while every golden text has a committed vector."""

    def test_every_golden_text_has_a_committed_vector(self) -> None:
        examples = ecp.load_examples()
        model = ai_provider.ST_DEFAULT_MODEL
        missing = [
            text
            for text in ecp._text_values(examples)
            if ai_provider.embed_cache_read(model, text) is None
        ]
        self.assertEqual(
            missing,
            [],
            f"{len(missing)} golden text(s) lack an embedding fixture for {model}; "
            "re-run 'make eval-prefill' with EMBEDDING_PROVIDER=st and commit "
            "tests/fixtures/embeddings/.",
        )


if __name__ == "__main__":
    unittest.main()
