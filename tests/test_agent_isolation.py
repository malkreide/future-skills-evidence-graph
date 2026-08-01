"""The isolation contract for the counter-evidence agent lane.

docs/gegenevidenz-lane.md promises the lane can be deleted without the core
noticing. A promise in prose decays; these tests are the enforcement:

- `scripts/` must never import from `agents/` — the dependency runs one way, so
  the core keeps working (and keeps passing CI) with `agents/` absent entirely;
- LangGraph must not leak into `requirements-dev.txt`, because the regular CI
  installs only that file — which is what proves the core does not need it;
- the agent must never import a `langchain-*` provider binding, because routing
  every model call through `ai_provider` is what preserves fixture replay and
  lets the lane inherit the core's providers;
- the lane must emit candidates only, and never write an active record.

These run in the normal suite and need neither LangGraph nor a network.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
AGENTS_DIR = ROOT / "agents"


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by *path*, from its AST (nothing executed)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


class DependencyDirectionTest(unittest.TestCase):
    """agents/ may use scripts/. scripts/ may never use agents/."""

    def agent_module_names(self) -> set[str]:
        return {path.stem for path in AGENTS_DIR.glob("*.py")} | {"agents"}

    def test_no_core_script_imports_an_agent_module(self) -> None:
        forbidden = self.agent_module_names()
        offenders = []
        for path in sorted(SCRIPTS_DIR.glob("*.py")):
            leaked = imported_modules(path) & forbidden
            if leaked:
                offenders.append(f"{path.name} imports {sorted(leaked)}")
        self.assertEqual(
            offenders,
            [],
            "scripts/ must not depend on agents/ — the lane has to stay deletable:\n"
            + "\n".join(offenders),
        )

    def test_core_test_suite_does_not_require_langgraph(self) -> None:
        """CI installs requirements-dev.txt only; nothing there may need langgraph."""
        for path in sorted(SCRIPTS_DIR.glob("*.py")):
            with self.subTest(script=path.name):
                self.assertNotIn("langgraph", imported_modules(path))

    def test_core_still_imports_with_agents_removed(self) -> None:
        """Simulate a deleted lane: importing the core must not notice."""
        removed = {name for name in sys.modules if name.startswith("counter_evidence")}
        for name in removed:
            sys.modules.pop(name, None)
        import importlib

        for module in ("common", "ai_provider", "extract_claims", "validate_data"):
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))


class RequirementsSeparationTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_langgraph_is_not_in_the_core_requirements(self) -> None:
        core = [
            line.strip()
            for line in self.read("requirements-dev.txt").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertNotIn("langgraph", " ".join(core).lower())

    def test_agent_requirements_exist_and_are_pinned(self) -> None:
        lines = [
            line.strip()
            for line in self.read("requirements-agents.txt").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(lines, "requirements-agents.txt should pin the lane's deps")
        for line in lines:
            with self.subTest(requirement=line):
                # Same supply-chain rule as requirements-dev.txt: exact pins only.
                self.assertIn("==", line)


class NoProviderBindingTest(unittest.TestCase):
    """LangGraph is a state machine here, not an LLM client."""

    def test_agent_uses_ai_provider_and_no_langchain_binding(self) -> None:
        for path in sorted(AGENTS_DIR.glob("*.py")):
            with self.subTest(agent=path.name):
                imports = imported_modules(path)
                self.assertIn(
                    "ai_provider",
                    imports,
                    "model calls must route through ai_provider, or fixture replay breaks",
                )
                leaked = {name for name in imports if name.startswith("langchain")}
                self.assertEqual(
                    leaked,
                    set(),
                    f"{path.name} imports {sorted(leaked)}; a provider binding would "
                    "bypass the fixture cache and re-introduce the dependency tree the "
                    "project deliberately avoids",
                )

    def test_agent_requirements_carry_no_langchain_integration_package(self) -> None:
        text = (ROOT / "requirements-agents.txt").read_text(encoding="utf-8")
        active = [
            line.strip().lower()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in active:
            with self.subTest(requirement=line):
                self.assertFalse(
                    line.startswith("langchain"),
                    "the lane needs no langchain integration package",
                )


class CandidatesOnlyTest(unittest.TestCase):
    """The lane proposes; a human promotes. Nothing it emits may be active."""

    def agent_source(self) -> str:
        return (AGENTS_DIR / "counter_evidence.py").read_text(encoding="utf-8")

    def test_emitted_claims_are_candidates(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))
        import counter_evidence as ce

        state = ce.initial_state(
            {"id": "skill-x", "name": "X", "definition": "d", "status": "active"}
        )
        state["findings"] = [
            {
                "source": {"id": "src-x", "title": "t", "abstract": "a"},
                "quote": "No significant difference was observed.",
                "reason": "null result",
            }
        ]
        claim = ce.to_candidate_claims(state)[0]
        self.assertEqual(claim["status"], "candidate")
        self.assertIsNone(claim["reviewed_at"])
        self.assertEqual(claim["evidence_strength"], "low")
        # The contradiction is recorded; the supporting side stays untouched.
        self.assertEqual(claim["contradicts_skill_ids"], ["skill-x"])
        self.assertEqual(claim["supports_skill_ids"], [])
        # And the statement is the verbatim quote, with an anchor naming it.
        self.assertEqual(claim["statement"], "No significant difference was observed.")
        self.assertIn(claim["statement"], claim["text_anchor"])

    def test_only_active_skills_are_challenged(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        import counter_evidence as ce

        self.assertIsNone(ce.active_skill("skill-does-not-exist"))

    def test_query_budget_holds_against_an_overeager_model(self) -> None:
        """A bound the model is merely asked to respect is not a bound.

        Checked by behaviour, not by grepping the prompt: hand propose_queries a
        model that returns far more queries than the budget and assert the code
        truncates it.
        """
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))
        import ai_provider
        import counter_evidence as ce

        flood = {"queries": [f"query {index}" for index in range(50)]}
        state = ce.initial_state({"id": "s", "name": "N", "definition": "d"})
        with mock.patch.object(ai_provider, "ai_provider", return_value="cache"), \
                mock.patch.object(ai_provider, "complete", return_value=flood):
            result = ce.propose_queries(state)
        self.assertLessEqual(len(result["queries_used"]), ce.MAX_QUERIES)

    def test_a_query_is_never_repeated(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))
        import ai_provider
        import counter_evidence as ce

        state = ce.initial_state({"id": "s", "name": "N", "definition": "d"})
        state["queries_used"] = ["already tried"]
        with mock.patch.object(ai_provider, "ai_provider", return_value="cache"), \
                mock.patch.object(
                    ai_provider, "complete",
                    return_value={"queries": ["already tried", "already tried"]}):
            result = ce.propose_queries(state)
        self.assertEqual(result["pending_queries"], [])
        self.assertEqual(result["queries_used"], ["already tried"])

    def test_the_graph_stops_at_every_hard_limit(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        import counter_evidence as ce

        base = ce.initial_state({"id": "s", "name": "N", "definition": "d"})
        self.assertEqual(ce.should_continue(base), "continue")
        for field, value in (
            ("rounds", ce.MAX_ROUNDS),
            ("barren_rounds", ce.MAX_BARREN_ROUNDS),
            ("exhausted", True),
        ):
            with self.subTest(limit=field):
                state = dict(base)
                state[field] = value
                self.assertEqual(ce.should_continue(state), "stop")
        exhausted_budget = dict(base)
        exhausted_budget["queries_used"] = ["q"] * ce.MAX_QUERIES
        self.assertEqual(ce.should_continue(exhausted_budget), "stop")

    def test_a_non_verbatim_quote_is_discarded(self) -> None:
        """No claim without a verifiable text anchor — the rule holds here too."""
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))
        import ai_provider
        import counter_evidence as ce
        import ingest_openalex

        abstract = "The programme produced no measurable change in transfer performance."
        state = ce.initial_state({"id": "s", "name": "N", "definition": "d"})
        state["pending_queries"] = ["q"]
        paraphrase = {
            "contradicts": True,
            "quote": "There was no measurable change.",  # plausible, NOT verbatim
            "reason": "null result",
        }
        with mock.patch.object(ai_provider, "ai_provider", return_value="cache"), \
                mock.patch.object(ai_provider, "complete", return_value=paraphrase), \
                mock.patch.object(ingest_openalex, "fetch", lambda *a, **k: [{"id": "W"}]), \
                mock.patch.object(
                    ingest_openalex, "convert",
                    lambda w: {"id": "src-x", "title": "T", "abstract": abstract}), \
                redirect_stderr(io.StringIO()):
            result = ce.search_and_assess(state)
        self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()


class SourcePersistenceTest(unittest.TestCase):
    """A claim must never cite a source that exists nowhere.

    The lane originally wrote only claims. Every claim cited a freshly
    discovered OpenAlex work whose source record was never persisted, so
    validate_data.py failed with "references missing source" and
    promote_candidate.py refused the candidate. Sources therefore land BEFORE
    the claims that cite them, and these tests pin that ordering plus the two
    id subtleties that make it correct.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "candidates-counter.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def state_with(self, *sources: dict) -> dict:
        import counter_evidence as ce

        state = ce.initial_state({"id": "skill-x", "name": "X", "definition": "d"})
        state["findings"] = [
            {"source": source, "quote": f"No effect {index}.", "reason": "null"}
            for index, source in enumerate(sources)
        ]
        return state

    def source(self, source_id: str, title: str) -> dict:
        # url/openalex_id derive from the TITLE, not the id: two records may share
        # an id while being genuinely different sources, and that is exactly the
        # collision case this suite has to reach.
        slug = title.lower().replace(" ", "-")
        return {
            "id": source_id, "title": title, "abstract": "a", "authors": [], "year": 2024,
            "doi": None, "url": f"http://example.org/{slug}", "openalex_id": slug,
            "semantic_scholar_id": None, "eric_id": None, "publisher": "P",
            "source_type": "peer_reviewed_article", "license": None, "topics": ["education"],
            "status": "candidate", "created_at": "2026-01-01", "reviewed_at": None,
        }

    def test_every_claim_cites_a_persisted_source(self) -> None:
        import counter_evidence as ce

        state = self.state_with(self.source("src-alpha", "Alpha study"))
        appended, reused = ce.persist_sources(state, self.path)
        self.assertEqual((appended, reused), (1, 0))

        stored = {record["id"] for record in json.loads(self.path.read_text())}
        for claim in ce.to_candidate_claims(state):
            with self.subTest(claim=claim["id"]):
                self.assertTrue(set(claim["source_ids"]) <= stored)

    def test_sources_are_written_as_candidates(self) -> None:
        import counter_evidence as ce

        state = self.state_with(self.source("src-alpha", "Alpha study"))
        ce.persist_sources(state, self.path)
        for record in json.loads(self.path.read_text()):
            self.assertEqual(record["status"], "candidate")

    def test_an_id_collision_is_reflected_in_the_claim(self) -> None:
        """append_unique_records renames on collision; the claim must follow."""
        import counter_evidence as ce

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([self.source("src-alpha", "A different paper")]))

        state = self.state_with(self.source("src-alpha", "Alpha study"))
        ce.persist_sources(state, self.path)

        stored = {record["id"] for record in json.loads(self.path.read_text())}
        claim = ce.to_candidate_claims(state)[0]
        self.assertNotEqual(claim["source_ids"], ["src-alpha"], "the id should have been renamed")
        self.assertTrue(set(claim["source_ids"]) <= stored)

    def test_no_findings_writes_no_file(self) -> None:
        import counter_evidence as ce

        state = self.state_with()
        self.assertEqual(ce.persist_sources(state, self.path), (0, 0))
        self.assertFalse(self.path.exists(), "an empty run must not create a noise file")


class StopReasonTest(unittest.TestCase):
    """The run log must name WHICH limit ended the run.

    should_continue returns only "stop"/"continue" because that is all the graph
    edge needs — but a reviewer judging a barren run cannot tell "no
    counter-evidence exists" from "the budget ran out too early" from that word.
    """

    def test_each_limit_has_its_own_reason(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        import counter_evidence as ce

        base = ce.initial_state({"id": "s", "name": "N", "definition": "d"})
        self.assertIsNone(ce.stop_reason(base))

        cases = {
            "exhausted": ("exhausted", True),
            "rounds": ("rounds", ce.MAX_ROUNDS),
            "barren": ("barren_rounds", ce.MAX_BARREN_ROUNDS),
        }
        reasons = set()
        for label, (field, value) in cases.items():
            state = dict(base)
            state[field] = value
            reason = ce.stop_reason(state)
            with self.subTest(limit=label):
                self.assertIsNotNone(reason)
                self.assertEqual(ce.should_continue(state), "stop")
            reasons.add(reason)

        budget = dict(base)
        budget["queries_used"] = ["q"] * ce.MAX_QUERIES
        reasons.add(ce.stop_reason(budget))

        self.assertEqual(len(reasons), 4, f"reasons must be distinguishable, got {reasons}")


class SearchFallbackTest(unittest.TestCase):
    """The lane must survive one search backend being down.

    A real run showed why: OpenAlex answered HTTP 429, the run examined zero
    sources, and nothing distinguished "the literature is silent" from "the one
    source we ask was throttled". The chain tries backends in order until one
    returns hits this lane can actually judge.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        sys.path.insert(0, str(SCRIPTS_DIR))

    def backend(self, name: str):
        import counter_evidence as ce

        return dict(ce.SEARCH_BACKENDS)[name]

    def with_backends(self, **behaviour):
        """Patch each named backend's fetch; a callable may raise to simulate an outage."""
        import counter_evidence as ce

        patches = []
        for name, works in behaviour.items():
            module = dict(ce.SEARCH_BACKENDS)[name]
            fetch = works if callable(works) else (lambda *a, w=works, **k: w)
            patches.append(mock.patch.object(module, "fetch", fetch))
            patches.append(
                mock.patch.object(module, "convert", lambda w: w)  # already source-shaped
            )
        return patches

    def source(self, title: str, abstract: str) -> dict:
        return {"id": f"src-{title}", "title": title, "abstract": abstract}

    LONG = "A study of twelve schools reporting no significant difference on the transfer task."

    def run_search(self, patches, query: str = "q"):
        import counter_evidence as ce

        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            with redirect_stderr(io.StringIO()):
                return ce.search_query(query)

    def test_first_healthy_backend_wins(self) -> None:
        patches = self.with_backends(openalex=[self.source("a", self.LONG)])
        sources, backend = self.run_search(patches)
        self.assertEqual(backend, "openalex")
        self.assertEqual(len(sources), 1)

    def test_an_outage_falls_through_to_the_next(self) -> None:
        """HTTP 429 is exactly the case that motivated this chain."""
        def throttled(*args, **kwargs):
            raise OSError("HTTP Error 429: Too Many Requests")

        patches = self.with_backends(
            openalex=throttled, semantic_scholar=[self.source("b", self.LONG)]
        )
        sources, backend = self.run_search(patches)
        self.assertEqual(backend, "semantic_scholar")
        self.assertEqual(len(sources), 1)

    def test_hits_without_abstracts_also_fall_through(self) -> None:
        """Ten abstract-less hits are as useless here as an outage."""
        patches = self.with_backends(
            openalex=[self.source("c", ""), self.source("d", "too short")],
            semantic_scholar=[self.source("e", self.LONG)],
        )
        sources, backend = self.run_search(patches)
        self.assertEqual(backend, "semantic_scholar")

    def test_all_backends_down_yields_nothing_not_a_crash(self) -> None:
        def down(*args, **kwargs):
            raise OSError("unreachable")

        patches = self.with_backends(openalex=down, semantic_scholar=down, eric=down)
        sources, backend = self.run_search(patches)
        self.assertEqual(sources, [])
        self.assertIsNone(backend)

    def test_crossref_is_not_a_backend(self) -> None:
        """It hard-codes abstract=None, so it could never contribute a claim.

        Including it would lengthen the chain with a link that always yields
        nothing — redundancy in appearance only.
        """
        import counter_evidence as ce

        self.assertNotIn("crossref", dict(ce.SEARCH_BACKENDS))

    def test_every_backend_can_actually_supply_abstracts(self) -> None:
        """Guards the rule the crossref exclusion follows from."""
        import counter_evidence as ce

        for name, module in ce.SEARCH_BACKENDS:
            with self.subTest(backend=name):
                source = inspect.getsource(module.convert)
                self.assertNotIn(
                    '"abstract": None',
                    source,
                    f"{name} cannot supply abstracts, so it cannot serve this lane",
                )


class SchemaApiCompatibilityTest(unittest.TestCase):
    """Every JSON Schema handed to ai_provider must be one the endpoint accepts.

    AST-only, so this runs in the core suite with langgraph uninstalled -- the
    same reason DependencyDirectionTest parses instead of imports.
    """

    # Observed, not guessed. The first live workflow run of the counter-evidence
    # lane failed twice with HTTP 400:
    #   output_config.format.schema: For 'array' type, property 'maxItems' is
    #   not supported
    # Only keywords seen rejected belong in here; this is a record of a real
    # failure, not a speculative allow-list.
    UNSUPPORTED_KEYWORDS = ("maxItems",)

    def schema_sources(self) -> list[Path]:
        return sorted(AGENTS_DIR.glob("*.py")) + sorted(SCRIPTS_DIR.glob("*.py"))

    def test_no_schema_uses_a_keyword_the_endpoint_rejects(self) -> None:
        for path in self.schema_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for key in node.keys:
                    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                        continue
                    with self.subTest(file=path.name, line=key.lineno):
                        self.assertNotIn(
                            key.value,
                            self.UNSUPPORTED_KEYWORDS,
                            f"{path.name}:{key.lineno} uses {key.value!r}, which the "
                            "structured-output endpoint rejects with HTTP 400. The call "
                            "then degrades to None and the caller silently falls back, "
                            "so this never surfaces as a failure at runtime. Enforce the "
                            "bound in code instead.",
                        )


class QueryBudgetCouplingTest(unittest.TestCase):
    """MAX_QUERIES only bites while MAX_ROUNDS leaves room to spend it.

    The query prompt asks for up to QUERIES_PER_ROUND queries, so a run can
    never issue more than MAX_ROUNDS * QUERIES_PER_ROUND. Set MAX_ROUNDS too
    low and the round limit quietly becomes the real budget: raising
    MAX_QUERIES then changes nothing, and the run log still blames
    'round_limit' for a run that was actually cut off by arithmetic.
    """

    QUERIES_PER_ROUND = 3

    def test_the_round_limit_leaves_room_for_the_whole_query_budget(self) -> None:
        sys.path.insert(0, str(AGENTS_DIR))
        import counter_evidence as ce

        reachable = ce.MAX_ROUNDS * self.QUERIES_PER_ROUND
        self.assertGreaterEqual(
            reachable,
            ce.MAX_QUERIES,
            f"MAX_ROUNDS={ce.MAX_ROUNDS} caps a run at {reachable} queries, below "
            f"MAX_QUERIES={ce.MAX_QUERIES}: the query budget can never be reached, "
            "so raising it has no effect.",
        )

    def test_the_prompt_still_asks_for_that_many_queries(self) -> None:
        """Guards the constant above: the coupling is only real while this holds."""
        sys.path.insert(0, str(AGENTS_DIR))
        import counter_evidence as ce

        self.assertIn(
            f"up to {self.QUERIES_PER_ROUND} short search queries",
            ce.QUERY_PROMPT,
            "the per-round query count changed; QUERIES_PER_ROUND here must follow",
        )
