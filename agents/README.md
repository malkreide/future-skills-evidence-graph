# Agent lane (optional, isolated)

Everything here is **outside** the deterministic core pipeline and can be deleted
without the core noticing. The rationale, the isolation contract and the
activation/decommission rule live in
[docs/gegenevidenz-lane.md](../docs/gegenevidenz-lane.md).

## What is in here

- `counter_evidence.py` — agentic search for evidence that *contradicts* an
  active skill. The catalogue holds 146 claims with exactly one contradiction:
  the importers search *for* future-skills topics and the extractor prefers a
  finding sentence, so every stage leans the same way. This lane is the
  counter-check.
- `runs/` — one JSON decision trail per run, **committed on purpose**. A run is
  not repeatable the way the core is, so it has to be inspectable: which queries
  were asked, how many sources were examined, why the graph stopped.

## Running it

```bash
pip install -r ../requirements-agents.txt      # NOT installed by the core
python counter_evidence.py --skill skill-systems-thinking --dry-run
```

Without LangGraph installed the lane exits with a one-line instruction rather
than a traceback — reaching that message is the expected first experience, since
the core deliberately does not install it.

## The rules this lane lives under

| | |
| --- | --- |
| Dependency direction | `agents/` may import `scripts/`; `scripts/` may **never** import `agents/` |
| Model access | only through `scripts/ai_provider.py` — never a `langchain-*` binding |
| Output | `status: candidate` only; promotion stays a human decision |
| Text anchors | a claim's statement must appear **verbatim** in the abstract, or it is discarded |
| Search sources | OpenAlex → Semantic Scholar → ERIC, first usable wins; Crossref excluded (carries no abstracts) |
| Trigger | `workflow_dispatch` only, never scheduled |
| Limits | `MAX_ROUNDS` / `MAX_QUERIES` are code constants, not prompt instructions |

`tests/test_agent_isolation.py` enforces these and runs in the normal suite,
which installs no LangGraph — that is the proof the core does not need it.
