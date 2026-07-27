"""Tests for the multi-provider completion path (scripts/ai_provider.py).

The provider layer is the one place where an outside service can reach into an
otherwise deterministic pipeline, so the invariants worth pinning are about
containment, not about any single vendor:

- **`none` stays inert.** The default imports nothing and returns None.
- **Backward-compatible cache keys.** Anthropic keeps its historic key shape, so
  the 50 committed fixtures stay valid; every other provider is namespaced and
  cannot collide with it or with each other.
- **Each adapter attaches the schema its own way.** That difference is the whole
  reason there is no shared abstraction, so it is asserted per provider.
- **No provider can abort the pipeline.** A missing SDK, a network error, a
  refusal or malformed output must all degrade to None with a warning.

Every SDK is faked; nothing here opens a socket or needs a key.
"""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import os  # noqa: E402

import ai_provider  # noqa: E402
import eval_claim_prefill as ecp_module  # noqa: E402

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}
RESPONSE = {"answer": "yes"}


def env(**values: str):
    """Patch only the AI_* environment, leaving the rest of os.environ alone."""
    return mock.patch.dict("os.environ", values, clear=False)


class DefaultOffTest(unittest.TestCase):
    def test_none_returns_nothing_and_calls_no_adapter(self) -> None:
        with env(AI_PROVIDER="none"), \
                mock.patch.dict(ai_provider._COMPLETION_ADAPTERS, {}, clear=True):
            self.assertIsNone(ai_provider.complete("prompt", schema=SCHEMA))

    def test_unset_provider_defaults_to_none(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ai_provider.ai_provider(), "none")
            self.assertIsNone(ai_provider.complete("prompt"))


class CacheKeyTest(unittest.TestCase):
    """Namespacing must be additive: anthropic keys cannot change."""

    def key(self, provider: str) -> dict:
        return ai_provider.request_payload(
            kind="complete", model="m", prompt="p", schema=SCHEMA, provider=provider
        )

    def test_anthropic_keeps_the_historic_shape(self) -> None:
        self.assertEqual(
            self.key("anthropic"),
            {"kind": "complete", "model": "m", "prompt": "p", "schema": SCHEMA},
        )

    def test_other_providers_are_namespaced(self) -> None:
        for provider in ("openai", "ollama"):
            with self.subTest(provider=provider):
                self.assertEqual(self.key(provider).get("provider"), provider)

    def test_same_model_on_two_providers_does_not_collide(self) -> None:
        """The collision this namespacing exists to prevent."""
        hashes = {
            ai_provider._request_hash(self.key(provider))
            for provider in ("anthropic", "openai", "ollama")
        }
        self.assertEqual(len(hashes), 3)

    def test_cache_mode_replays_the_named_provider(self) -> None:
        with env(AI_PROVIDER="cache", AI_CACHE_PROVIDER="openai"), \
                mock.patch.object(ai_provider, "cache_read", return_value=RESPONSE) as read:
            self.assertEqual(ai_provider.complete("p", schema=SCHEMA), RESPONSE)
        self.assertEqual(read.call_args.args[0].get("provider"), "openai")

    def test_cache_mode_defaults_to_anthropic(self) -> None:
        with env(AI_PROVIDER="cache"), mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(ai_provider.cache_provider(), "anthropic")


class AnthropicAdapterTest(unittest.TestCase):
    def fake_sdk(self, *, text: str | None = None, stop_reason: str | None = None):
        captured: dict = {}

        def create(**kwargs):
            captured.update(kwargs)
            block = types.SimpleNamespace(type="text", text=text)
            return types.SimpleNamespace(content=[block], stop_reason=stop_reason)

        client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        module = types.SimpleNamespace(Anthropic=lambda: client)
        return module, captured

    def test_schema_rides_in_output_config(self) -> None:
        module, captured = self.fake_sdk(text=json.dumps(RESPONSE))
        with mock.patch.dict(sys.modules, {"anthropic": module}):
            result = ai_provider._anthropic_complete("m", "p", SCHEMA)
        self.assertEqual(result, RESPONSE)
        self.assertEqual(captured["output_config"]["format"]["schema"], SCHEMA)
        # effort='low' is how determinism is requested here; temperature is rejected.
        self.assertEqual(captured["output_config"]["effort"], "low")
        self.assertNotIn("temperature", captured)

    def test_refusal_yields_none(self) -> None:
        module, _ = self.fake_sdk(text="{}", stop_reason="refusal")
        with mock.patch.dict(sys.modules, {"anthropic": module}), \
                redirect_stderr(io.StringIO()):
            self.assertIsNone(ai_provider._anthropic_complete("m", "p", SCHEMA))


class OpenAIAdapterTest(unittest.TestCase):
    def fake_sdk(self, *, content: str | None = None, finish_reason: str = "stop"):
        captured: dict = {}

        def create(**kwargs):
            captured.update(kwargs)
            choice = types.SimpleNamespace(
                message=types.SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
            return types.SimpleNamespace(choices=[choice])

        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
        )
        module = types.SimpleNamespace(OpenAI=lambda: client)
        return module, captured

    def test_schema_rides_in_response_format(self) -> None:
        module, captured = self.fake_sdk(content=json.dumps(RESPONSE))
        with mock.patch.dict(sys.modules, {"openai": module}):
            result = ai_provider._openai_complete("gpt-x", "p", SCHEMA)
        self.assertEqual(result, RESPONSE)
        envelope = captured["response_format"]["json_schema"]
        self.assertEqual(envelope["schema"], SCHEMA)
        self.assertTrue(envelope["strict"], "strict mode is what enforces the schema")
        # OpenAI takes determinism as temperature=0, which Opus 4.8 rejects --
        # exactly the difference a shared abstraction would have to hide.
        self.assertEqual(captured["temperature"], 0)

    def test_content_filter_yields_none(self) -> None:
        module, _ = self.fake_sdk(content="{}", finish_reason="content_filter")
        with mock.patch.dict(sys.modules, {"openai": module}), redirect_stderr(io.StringIO()):
            self.assertIsNone(ai_provider._openai_complete("gpt-x", "p", SCHEMA))


class OllamaAdapterTest(unittest.TestCase):
    """The keyless local provider — stdlib HTTP, no package."""

    def fake_urlopen(self, payload: dict):
        captured: dict = {}

        class Response:
            def read(self):
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

        return urlopen, captured

    def test_schema_is_passed_as_format(self) -> None:
        urlopen, captured = self.fake_urlopen({"response": json.dumps(RESPONSE)})
        with mock.patch("urllib.request.urlopen", urlopen):
            result = ai_provider._ollama_complete("llama3", "p", SCHEMA)
        self.assertEqual(result, RESPONSE)
        self.assertEqual(captured["body"]["format"], SCHEMA)
        self.assertEqual(captured["body"]["options"]["temperature"], 0)
        self.assertFalse(captured["body"]["stream"])

    def test_host_is_configurable(self) -> None:
        urlopen, captured = self.fake_urlopen({"response": json.dumps(RESPONSE)})
        with env(OLLAMA_HOST="http://box:1234/"), mock.patch("urllib.request.urlopen", urlopen):
            ai_provider._ollama_complete("llama3", "p", SCHEMA)
        self.assertEqual(captured["url"], "http://box:1234/api/generate")

    def test_a_timeout_is_always_set(self) -> None:
        """A hung local server must not stall an importer forever."""
        urlopen, captured = self.fake_urlopen({"response": json.dumps(RESPONSE)})
        with mock.patch("urllib.request.urlopen", urlopen):
            ai_provider._ollama_complete("llama3", "p", SCHEMA)
        self.assertEqual(captured["timeout"], ai_provider.OLLAMA_TIMEOUT_SECONDS)


class GracefulDegradationTest(unittest.TestCase):
    """No provider failure may propagate into the pipeline."""

    def test_adapter_exception_becomes_none(self) -> None:
        def boom(*args):
            raise RuntimeError("network down")

        with env(AI_PROVIDER="openai"), \
                mock.patch.dict(ai_provider._COMPLETION_ADAPTERS, {"openai": boom}), \
                redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(ai_provider.complete("p", schema=SCHEMA))
        self.assertIn("network down", err.getvalue())

    def test_missing_sdk_becomes_none(self) -> None:
        """An uninstalled optional package is a warning, not a crash."""
        with env(AI_PROVIDER="openai"), \
                mock.patch.dict(sys.modules, {"openai": None}), \
                redirect_stderr(io.StringIO()):
            self.assertIsNone(ai_provider.complete("p", schema=SCHEMA))

    def test_malformed_json_becomes_none(self) -> None:
        with redirect_stderr(io.StringIO()):
            self.assertIsNone(ai_provider._parse_json_object("not json", "openai"))
            self.assertIsNone(ai_provider._parse_json_object("[1, 2]", "openai"))
            self.assertIsNone(ai_provider._parse_json_object(None, "openai"))

    def test_unknown_provider_warns_and_returns_none(self) -> None:
        with env(AI_PROVIDER="gemini"), redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(ai_provider.complete("p", schema=SCHEMA))
        self.assertIn("Unknown AI_PROVIDER", err.getvalue())

    def test_a_successful_live_call_is_cached_for_replay(self) -> None:
        with env(AI_PROVIDER="openai"), \
                mock.patch.dict(
                    ai_provider._COMPLETION_ADAPTERS, {"openai": lambda *a: RESPONSE}), \
                mock.patch.object(ai_provider, "cache_write") as write:
            self.assertEqual(ai_provider.complete("p", schema=SCHEMA), RESPONSE)
        write.assert_called_once()
        self.assertEqual(write.call_args.args[0].get("provider"), "openai")


if __name__ == "__main__":
    unittest.main()


class ActivationRuleTest(unittest.TestCase):
    """The rule that decides whether a challenger provider replaces the incumbent.

    This is the whole point of supporting several providers: the choice is
    measured, not assumed. The rule must resist the two ways a comparison
    flatters a challenger — noise on a 50-example set, and an average that hides
    a collapse in one field.
    """

    def result(self, gated: float, age: float, strength: float) -> dict:
        import compare_providers as cp  # noqa: F401 - imported for its module state

        def metric(precision: float):
            fm = ecp_module.FieldMetrics("f")
            fm.matches, fm.predicted, fm.gold = int(precision * 100), 100, 100
            return fm

        return {
            "gated": metric(gated),
            "metrics": {"age_range": metric(age), "evidence_strength": metric(strength)},
            "model": "m",
        }

    def verdict(self, incumbent: dict, challenger: dict) -> str:
        import compare_providers as cp

        return cp._verdict(incumbent, challenger, "openai")

    def test_a_tie_keeps_the_incumbent(self) -> None:
        base = self.result(0.87, 0.94, 0.82)
        self.assertIn("Keep anthropic", self.verdict(base, self.result(0.87, 0.94, 0.82)))

    def test_a_noise_sized_win_keeps_the_incumbent(self) -> None:
        """+0.01 on 50 examples is not evidence of anything."""
        base = self.result(0.87, 0.94, 0.82)
        self.assertIn("Keep anthropic", self.verdict(base, self.result(0.88, 0.95, 0.83)))

    def test_a_clear_win_is_a_candidate(self) -> None:
        base = self.result(0.87, 0.94, 0.82)
        self.assertIn("Candidate for activation", self.verdict(base, self.result(0.95, 0.98, 0.92)))

    def test_a_win_hiding_a_per_field_collapse_is_refused(self) -> None:
        """Higher on average, much worse on age_range — not an activation."""
        base = self.result(0.87, 0.94, 0.82)
        challenger = self.result(0.95, 0.70, 0.99)
        verdict = self.verdict(base, challenger)
        self.assertIn("regresses on age_range", verdict)
        self.assertNotIn("Candidate for activation", verdict)

    def test_a_loss_keeps_the_incumbent(self) -> None:
        base = self.result(0.87, 0.94, 0.82)
        self.assertIn("Keep anthropic", self.verdict(base, self.result(0.60, 0.70, 0.55)))


class ComparisonSafetyTest(unittest.TestCase):
    def test_scoring_never_uses_a_live_provider(self) -> None:
        """A comparison must not be able to spend money or vary per run."""
        import compare_providers as cp

        seen = {}
        def fake_evaluate(examples, embeddings=None):
            seen["provider"] = os.environ.get("AI_PROVIDER")
            seen["cache_provider"] = os.environ.get("AI_CACHE_PROVIDER")
            return {name: ecp_module.FieldMetrics(name) for name in ecp_module.PREFILL_SUGGESTION_FIELDS}

        with env(AI_PROVIDER="anthropic"), mock.patch.object(cp, "evaluate", fake_evaluate):
            cp.score_provider("openai", "gpt-4o", [], None)
        self.assertEqual(seen["provider"], "cache")
        self.assertEqual(seen["cache_provider"], "openai")

    def test_environment_is_restored_after_scoring(self) -> None:
        import compare_providers as cp

        with env(AI_PROVIDER="anthropic", AI_MODEL="claude-opus-4-8"), \
                mock.patch.object(cp, "evaluate", lambda *a, **k: {
                    name: ecp_module.FieldMetrics(name)
                    for name in ecp_module.PREFILL_SUGGESTION_FIELDS}):
            cp.score_provider("openai", "gpt-4o", [], None)
            self.assertEqual(os.environ["AI_PROVIDER"], "anthropic")
            self.assertEqual(os.environ["AI_MODEL"], "claude-opus-4-8")

    def test_a_provider_without_fixtures_reports_none(self) -> None:
        """Zero predictions must not print as a hollow 1.00 precision."""
        import compare_providers as cp

        with mock.patch.object(cp, "evaluate", lambda *a, **k: {
                name: ecp_module.FieldMetrics(name)
                for name in ecp_module.PREFILL_SUGGESTION_FIELDS}):
            self.assertIsNone(cp.score_provider("ollama", "llama3.1", [], None))

    def test_model_override_parsing(self) -> None:
        import compare_providers as cp

        self.assertEqual(cp.parse_model_overrides(["openai=gpt-4o"])["openai"], "gpt-4o")
        with self.assertRaises(SystemExit):
            cp.parse_model_overrides(["gemini=x"])
        with self.assertRaises(SystemExit):
            cp.parse_model_overrides(["openai="])
