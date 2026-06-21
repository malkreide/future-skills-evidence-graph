# Operations Runbook

How to run the Future Skills Evidence Graph in ongoing operation: produce
candidates, review them, verify quality, and improve the pipeline over time.

The automation only ever produces **candidates**. Publishing active skills always
requires human review through pull requests. Nothing here changes that.

## Components

| Stage | Script / Workflow | Notes |
| --- | --- | --- |
| Import (5 sources) | `ingest_openalex / crossref / semantic_scholar / arxiv / eric .py` | Each degrades gracefully on outage (`fetch_or_warn`) |
| Relevance filter | `common.filter_relevant_sources` | Topic match required; off-scope filter; threshold 0.3 |
| Claim extraction | `extract_claims.py` | Verbatim finding sentence + text anchor; skips methodology |
| Clustering | `cluster_claims.py` | Proposes candidate skills for uncovered topics |
| Review | `promote_candidate.py {claim,skill,reject,reject-source}` | Promotes to reviewed/active; `reject-source` harvests a negative label |
| Scoring | `score_evidence.py` | Recomputed automatically on promotion; drift-guarded by validation |
| Validation | `validate_data.py` | Schema + cross-refs + score drift |
| Dashboard | `build_site.py` + `deploy-pages.yml` | Auto-deploys on push to `main` |
| Pipeline | `research-pipeline.yml` | Cron Monday 05:17 UTC + manual dispatch |

## One-time setup

```bash
pip install -r requirements-dev.txt
python scripts/validate_data.py                  # → "Validation passed."
python -m unittest discover -s tests             # → OK
python scripts/build_site.py                     # → "Built public/"
python scripts/eval_relevance.py                 # baseline metrics
python scripts/eval_relevance.py --compare-model # heuristic vs model verdict
```

Common steps are also wrapped as `make` targets (`make install`, `validate`,
`test`, `eval`, `eval-model`, `build`, `recall-probe`, `recall-ingest`, `train`).

In GitHub settings:
- Secret `SEMANTIC_SCHOLAR_API_KEY` (without it that source returns HTTP 429 and
  is skipped every run) and variable `OPENALEX_MAILTO`.
- Pages source = "GitHub Actions".

## Weekly operating cycle

1. **Run** — the cron runs Mondays automatically. Manual: GitHub → Actions →
   "Research candidate import" → Run workflow. (The API token cannot trigger
   `workflow_dispatch` — 403 — so use the UI or the cron.)
2. **CI** — confirm `validate` is green on the opened `research/candidates` PR.
3. **Review** each candidate:
   ```bash
   # Good claim → reviewed:
   python scripts/promote_candidate.py claim <claim-id> \
     --context "..." --age-range "12-18" --outcome "..." \
     --evidence-type systematic_review --evidence-strength moderate \
     --supports <skill-id>
   # Unusable claim → rejected:
   python scripts/promote_candidate.py reject <claim-id>
   # Off-scope source → off-scope + harvests a NEGATIVE relevance label:
   python scripts/promote_candidate.py reject-source <source-id>
   # In-scope source → reviewed + harvests a POSITIVE relevance label:
   python scripts/promote_candidate.py promote-source <source-id>
   # Fold a reviewed claim into a skill's evidence (recomputes the score):
   python scripts/promote_candidate.py attach-claim <skill-id> --claim <claim-id>
   ```
   Use `reject-source` / `promote-source` on every reviewed source — together
   they build the negative and positive labels the trained classifier needs.
   `attach-claim` requires the claim and its sources to be reviewed first, so the
   active-skill evidence path stays intact.
4. **Merge** the candidate PR.
5. **Deploy** happens automatically on push to `main` (`deploy-pages.yml`).

## Verification tests — every cycle

Measure these four; they reflect real quality, not just the (small, possibly
overfit) eval set:

1. **Live precision** — of the sources the filter accepted, the fraction you
   judged truly in-scope during review. This is precision on fresh data; if it
   sits well below the eval-set number, the off-scope list is overfit to the
   labeled set.
2. **Promote rate** — promoted claims / total candidate claims.
3. **Recall probe** — the filter drops below-threshold, off-scope and
   adult-audience sources silently, and the harvest only labels what passed, so
   the rejected region never reaches the eval set or the model. Once per cycle,
   surface a sample of the dropped sources for labeling:
   ```bash
   make recall-probe        # writes eval/recall_probe.json (a worksheet, gitignored)
   # set each row's "relevant": true (a recall leak) or false (correctly dropped)
   make recall-ingest       # folds the decided labels into eval/relevance_labeled.json
   ```
   This is the deliberate counter to the harvest's selection bias: it feeds the
   eval set (and future model training) negatives AND missed positives from the
   region the filter discards. Any row labeled `true` is a recall leak (usually a
   missing topic keyword); fix the vocabulary and re-measure.
4. **Harvest growth** —
   ```bash
   python -c "import json;print(len(json.load(open('eval/relevance_harvested.json'))['examples']))"
   ```

## Improvement tests — periodic (e.g. monthly)

```bash
python scripts/eval_relevance.py --include-harvested  # metrics incl. harvested labels
python scripts/eval_relevance.py --compare-model      # model vs heuristic (held-out CV)
```

Triggers → actions:
- **False positive seen** → `reject-source`; add the domain to `OFF_SCOPE_KEYWORDS`
  (`scripts/common.py`); add the example as a negative to
  `eval/relevance_labeled.json`; re-measure with `eval_relevance.py`.
- **False negative seen** (recall probe) → add the missing keyword to
  `TOPIC_KEYWORDS`; re-measure.
- **Grow the eval set** with fresh examples not used to tune the filter, to keep
  the precision estimate honest.
- **Model beats heuristic** (`--compare-model` says so) → `train_relevance.py`,
  commit `models/relevance_model.json`, set `RELEVANCE_CLASSIFIER=model` in the
  workflow env. Until then the heuristic stays the default (gating is built in).

## Optional AI claim pre-fill (P1)

Off by default (`AI_PROVIDER=none`): extraction is byte-identical to the LLM-free
pipeline. When a provider is configured (`AI_PROVIDER=anthropic`, model from
`AI_MODEL`, default `claude-opus-4-8`), `extract_claims.py` additionally asks the
LLM to *suggest* the manual review fields (`context`, `outcome`, `age_range`,
`evidence_strength`). The suggestion is stored **only** under
`claim["assist"]["suggestions"]` with provenance; the real fields keep their
placeholders and `statement`/`text_anchor` stay verbatim.

```bash
python scripts/eval_claim_prefill.py                 # offline field metrics (fixtures)
python scripts/eval_claim_prefill.py --min-precision 0.8 --min-recall 0.8  # CI gate
python scripts/eval_claim_prefill.py --write-fixtures # (re)record fixtures from the golden set
```

During review, `promote_candidate.py` prints any suggestion and
`--accept-suggestions` adopts the non-null values as starting points. This never
weakens the gate: fields the model left null stay placeholders and still block
promotion, a reviewed claim still needs a `--supports`/`--contradicts` skill
link, and every explicit flag overrides the suggestion. CI runs fully offline
against committed fixtures (`tests/fixtures/ai/`); a cache miss is a failure, not
a network call.

## Guardrails

- Review and merge the `research/candidates` PR promptly so candidates do not
  pile up across weeks in one PR.
- Retrain the model only with the fixed seed; commit the artifact and the CV
  verdict together.
- Score drift is auto-handled: `promote_candidate.py` recomputes scores and
  `validate_data.py` blocks drift.

## Baseline (first dry run)

First full live dry run, query "AI literacy education children future skills",
limit 20 per source:

- **Filter throughput:** 26 sources accepted (OpenAlex 6, ERIC 19, arXiv 1;
  Crossref 0 all filtered; Semantic Scholar 0 — rate-limited).
- **Live precision (fresh data): ~0.58** (≈15/26 in scope), well below the
  eval-set 1.00 — the eval-set figure is optimistic.
- **Promote rate: ~0.23** (≈6/26 promotable finding claims).
- **Dominant false-positive class:** adult / higher-education audience
  ("AI Literacy for the Workforce", "...in Higher Education", "College Students'
  AI Literacy", "Preservice Teachers"). The keyword filter had no age/audience
  gate, so "AI literacy" matched regardless of who the learner was.

### Improvement applied: audience/age gate

`is_adult_audience` (`HIGHER_ED_KEYWORDS` present, no `SCHOOL_AGE_KEYWORDS`) now
drops adult/post-secondary papers even when they name the skill in the title. A
re-run of the same query showed accepted sources **26 → 15** and live precision
**~0.58 → ~0.73**, with the higher-ed/workforce class removed. Curated eval set
stays precision 1.00 / recall 1.00 (now 73 examples, incl. the audience cases).

### Improvement applied: physical-education & language-pedagogy off-scope terms

Added `physical education / physical activity / physical fitness` and
`eap / efl / esl` to `OFF_SCOPE_KEYWORDS`. A re-run dropped accepted sources
**15 → 13** and lifted live precision **~0.73 → ~0.85**. Eval set grew to 81
examples (still precision 1.00 / recall 1.00; model still does not beat the
heuristic on held-out CV).

**Remaining fresh-data false-positive classes** (harder, not yet addressed):
teacher tool-use (teachers are a legitimate audience, so a blanket teacher gate
would cost recall), and disaster/health papers that name a school-age audience
and a topic in the title (off-scope title-anchor exemption keeps them). These
are candidates for the trained model once the harvested label set grows.

### First evidence folded into the graph

The two reviewed claims from the first live run (PR #22) were folded into their
skills with `attach-claim`, completing the source→claim→skill path: the GenAI
systematic-review claim into `skill-critical-thinking` (0.57 → 0.61) and
`skill-ai-literacy` (0.79 → 0.78, a correct dip — moderate evidence below a high
mean at saturated breadth), the metaverse-ethics claim into
`skill-ethical-technology-judgment` (0.72, unchanged). Their sources were
reviewed first with `promote-source`, which seeded the harvested label set with
its first two positive labels.

## Cycle log

Record each cycle so trends are visible.

| Date | Accepted | Live precision | Promoted | Promote rate | Harvest size | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| (dry run) | 26 | ~0.58 | — | ~0.23 | 0 | Adult/higher-ed FPs dominate |
| (audience gate) | 15 | ~0.73 | — | — | 0 | Higher-ed/workforce removed; PE/EAP/teacher FPs remain |
| (PE + language off-scope) | 13 | ~0.85 | — | — | 0 | PE/EFL removed; teacher tool-use + disaster/health FPs remain |
