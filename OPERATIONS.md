# Operations Runbook

How to run the Future Skills Evidence Graph in ongoing operation: produce
candidates, review them, verify quality, and improve the pipeline over time.

The automation only ever produces **candidates**. Publishing active skills always
requires human review through pull requests. Nothing here changes that.

> Bringing the project into live operation for the first time? Work through
> [docs/go-live-checkliste.md](docs/go-live-checkliste.md) — the configuration and
> first-cycle acceptance steps that this runbook assumes are already in place.

## Components

| Stage | Script / Workflow | Notes |
| --- | --- | --- |
| Import (5 sources) | `ingest_openalex / crossref / semantic_scholar / arxiv / eric .py` | Each degrades gracefully on outage (`fetch_or_warn`) |
| Relevance filter | `common.filter_relevant_sources` | Topic match required; off-scope filter; threshold 0.3; tags `audience` and runs the educator lane (`is_educator_audience`) alongside the learner gate |
| Claim extraction | `extract_claims.py` | Verbatim finding sentence + text anchor; skips methodology |
| Clustering | `cluster_claims.py` | Proposes candidate skills for uncovered topics |
| Review | `promote_candidate.py {claim,skill,reject,reject-source,promote-source,attach-claim,reopen}` | Promotes to reviewed/active; `reject-source` harvests a negative label; `reopen` flips a rejected record back to candidate |
| Scoring | `score_evidence.py` | Recomputed automatically on promotion; drift-guarded by validation |
| Validation | `validate_data.py` | Schema + cross-refs + score drift |
| Dashboard | `build_site.py` + `deploy-pages.yml` | Auto-deploys on push to `main` |
| Pipeline | `research-pipeline.yml` | Cron Monday 05:17 UTC + manual dispatch |
| Manual report intake | `ingest-from-issue.yml` (issue) · `ingest-reports.yml` (dispatch) · `parse_ingest_issue.py` · dashboard `site/einreichen.html` | Off-cycle; same LLM importer + candidate PR; needs `ANTHROPIC_API_KEY` + `AI_MODEL` |
| Web-search discovery | `ingest-websearch.yml` (dispatch) · `ingest_websearch.py` · `data/source_domains.json` | Off-cycle; query → candidate web sources; keyless (DuckDuckGo/`ddgs`); open search, tiered trust |

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
`test`, `eval`, `eval-model`, `eval-educator`, `eval-prefill`,
`eval-prefill-record`, `build`, `recall-probe`, `recall-ingest`, `triage`,
`train`).

In GitHub settings:
- Secret `SEMANTIC_SCHOLAR_API_KEY` (without it that source returns HTTP 429 and
  is skipped every run) and variable `OPENALEX_MAILTO`.
- Pages source = "GitHub Actions".

## Weekly operating cycle

1. **Run** — the cron runs Mondays automatically. Manual: GitHub → Actions →
   "Research candidate import" → Run workflow. (The API token cannot trigger
   `workflow_dispatch` — 403 — so use the UI or the cron.)
2. **CI** — confirm `validate` is green on the opened `research/candidates` PR.
3. **Review** each candidate. To work the standing backlog without hand-joining
   claims to their sources, generate a worksheet first:
   ```bash
   make triage   # writes eval/candidate_triage.json (gitignored, read-only)
   ```
   It lists every open candidate claim with its verbatim statement, matched
   topics, the source(s) it rests on, any `assist` pre-fill suggestions, and the
   exact `promote_candidate.py` commands to choose between. It promotes nothing;
   run those commands yourself:
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
   # Re-open a record rejected under an earlier scope (rejected → candidate):
   python scripts/promote_candidate.py reopen <claim-id|source-id>
   ```
   Use `reject-source` / `promote-source` on every reviewed source — together
   they build the negative and positive labels the trained classifier needs.
   `attach-claim` requires the claim and its sources to be reviewed first, so the
   active-skill evidence path stays intact. `reopen` is the inverse of `reject` /
   `reject-source`: it flips a record back to `candidate` so it can be reviewed
   again when the scope changes (e.g. the educator lane brings a previously
   off-scope teacher/educator study into scope), and for a source it drops the
   stale `irrelevant` label its rejection harvested so a later `promote-source`
   records the corrected positive.
4. **Merge** the candidate PR.
5. **Deploy** happens automatically on push to `main` (`deploy-pages.yml`).

## Manual report intake (off-cycle)

Besides the weekly cron, a human can submit an API-less report (OECD / WEF /
UNESCO) on demand. All three entry points run the **same** LLM importer
(`ingest_reports.py`) and write into the **same** `research/candidates` PR —
every source and claim stays `candidate`, behind the same verbatim guard, until
reviewed.

1. **Dashboard dropzone (easiest, mobile).** The "Bericht einreichen" page
   (`site/einreichen.html`, linked from the dashboard topbar). Drag-and-drop or
   pick a PDF / text file, or paste text; a dropped PDF is read **in-browser**
   (`pdf.js`). On submit it opens a **pre-filled issue** — it holds no token, so
   the human confirms on GitHub where auth lives. Long extracted text falls back
   to the clipboard; a bare PDF URL is read server-side.
2. **Issue form.** New issue → "Bericht einreichen"
   (`.github/ISSUE_TEMPLATE/ingest-report.yml`): a URL plus pasted text, an
   attached PDF, or a direct PDF URL. The form auto-applies the `ingest` label.
3. **Workflow dispatch.** Actions → "Import report candidate (manual)"
   (`ingest-reports.yml`) with a report path / URL or a manifest — the original
   path; it expects the plaintext to already be in the repo.

`ingest-from-issue.yml` fires on every `ingest`-labelled issue, resolves the
input (`parse_ingest_issue.py`, resolution order *pasted text → attached PDF →
PDF from the URL*, 25 MB download cap), runs the importer, clusters, validates,
updates the candidate PR, and comments the result — or the human-readable reason
it found no text — back on the issue. It needs the `ANTHROPIC_API_KEY` secret and
`AI_MODEL` variable, like the dispatch path; with no provider it is a no-op. From
there, review the new candidates exactly as in the weekly cycle. Full mechanics
and the security model: [docs/report-import.md](docs/report-import.md).

**URL is optional.** When a submitter gives no source URL,
`scripts/resolve_source_url.py` resolves one *document → Crossref → OpenAlex →
SearXNG → DuckDuckGo → (optional) Google*, only accepting a catalogue hit above a
title-similarity threshold and within ±1 year; otherwise the workflow uses the
issue URL as a flagged placeholder for the reviewer to correct. The resolved URL
is named in the issue comment and stays a candidate. The two open-web tiers are
open-source and keyless: **DuckDuckGo** (the `ddgs` library, runs out of the box)
and **SearXNG** (a self-hosted instance via the `SEARXNG_URL` variable). Their
hits are restricted to the in-code `CREDIBLE_DOMAINS` allowlist unless
`RESOLVE_OPEN_WEB=1`. Google is now only an optional last fallback
(`GOOGLE_SEARCH_API_KEY` secret + `GOOGLE_SEARCH_CX`). Verify any of these with the
**Resolve URL check** workflow (it prints each tier's result).

To verify the resolver (and the Google credentials) without an LLM call or a
candidate PR, run the **Resolve URL check** workflow (Actions →
`resolve-url-check.yml`, `workflow_dispatch`) with a report title: it prints each
tier's result and whether Google is configured.

## Web-search discovery (off-cycle, opt-in)

`scripts/ingest_websearch.py` is the grey-literature discovery lane: a topic
query → candidate web sources the keyless catalogues (OpenAlex / Crossref /
ERIC) never surface. It reuses the URL resolver's open-web backends, tried in
order and aggregated (deduped by URL):

1. **SearXNG** — self-hosted, keyless metasearch (opt-in via `SEARXNG_URL`);
2. **DuckDuckGo** — the keyless, open-source `ddgs` library (runs out of the box);
3. **Google** — optional last fallback (`GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX`).

It is a **no-op** only when no backend is available (no `ddgs`, no `SEARXNG_URL`,
no Google secret).

The strategy is **open search, tiered trust**. The search queries the open web —
nothing relevant is filtered out — and each hit's host is then labelled against
`data/source_domains.json`:

- **trusted** (OECD, UNESCO, EDK, KMK, ERIC, …) and **watch** (foundations,
  NGOs, ed-media) rise in the triage worksheet;
- everything unlisted is **open**: still kept as a candidate, but marked and
  pushed down with a rank penalty so a reviewer works the curated end first.

The tier list is kept a superset of `resolve_source_url.CREDIBLE_DOMAINS` (the URL
resolver's allowlist), guarded by a test, so a credible publisher never lands in
`open`. The tier is a *label only* — it steers `triage_candidates.py` ordering and
lives in `assist.provenance`; it never enters `evidence_score` (which keeps its
reproducibility guarantee), and every hit stays `source_type: web_resource`
(weight 0.25), `status: candidate`. Claims are **not** minted here — they keep
flowing through the verbatim guard in `extract_claims.py` / `ingest_reports.py`.
Edit the tier list only through a pull request.

Two entry points, both writing into the same `research/candidates` PR:

1. **Workflow dispatch.** Actions → "Discover web candidates (manual)"
   (`ingest-websearch.yml`) with a query (or a manifest of queries). It installs
   `ddgs`, so DuckDuckGo runs keyless with no setup; `SEARXNG_URL` / Google are
   picked up if configured.
2. **Local.**
   ```powershell
   pip install ddgs   # keyless DuckDuckGo tier; SearXNG/Google optional
   # one query (or repeat --query; or --manifest queries.json)
   python scripts/ingest_websearch.py --query "AI literacy curriculum primary school"
   ```

New candidates land in `data/sources/candidates-websearch.json`; review them
exactly as in the weekly cycle. Trusted hits sort to the top of the worksheet,
`open` hits to the bottom with a `domain_tier` marker.

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
EMBEDDING_PROVIDER=st python scripts/eval_relevance.py --compare-embedding     # st anchors vs heuristic
EMBEDDING_PROVIDER=local python scripts/eval_relevance.py --compare-embedding  # hashing anchors vs heuristic
```

The `st` provider is the real semantic embedding (sentence-transformers
`all-MiniLM-L6-v2`); it replays committed vectors from `tests/fixtures/embeddings/`
offline, and only imports the package to embed a text not yet cached. `local` is the
dependency-free hashing embedding. The current honest verdict (87-example set):
heuristic F1 0.92, `st` anchors F1 0.76, `local` anchors F1 0.65 — neither beats the
heuristic, so it stays the active default (see
[docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md)).

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
- **Embedding anchors beat heuristic** (`--compare-embedding` says so) →
  `EMBEDDING_PROVIDER=st python scripts/build_relevance_anchors.py` (re-embed the
  changed labels, refreshing `tests/fixtures/embeddings/`), commit
  `models/relevance_anchors.json` **and** the new fixtures, set
  `RELEVANCE_CLASSIFIER=embedding` plus `EMBEDDING_PROVIDER=st` in the workflow env.
  Until then the heuristic stays the default.

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
python scripts/eval_claim_prefill.py --write-fixtures # replay '_recorded' into the cache
```

During review, `promote_candidate.py` prints any suggestion and
`--accept-suggestions` adopts the non-null values as starting points. This never
weakens the gate: fields the model left null stay placeholders and still block
promotion, a reviewed claim still needs a `--supports`/`--contradicts` skill
link, and every explicit flag overrides the suggestion.

### What the CI gate actually measures (regression, not live accuracy)

The golden set `eval/claim_prefill_labeled.json` (~50 examples, broad topics, age
bands 4–18, and deliberately hard `outcome`/`evidence_strength` cases) carries two
things per example: the hand-curated `gold` review fields, and `_recorded` — the
**model output last captured** for that prompt. `--write-fixtures` replays
`_recorded` into `tests/fixtures/ai/`, and the offline run (CI default) reads its
suggestions only from those fixtures (`AI_PROVIDER=cache`).

So the CI gate is a **regression against the recorded outputs**: it is fully
offline and deterministic (a cache miss is a failure, not a network call) and it
catches drift between what we froze and the labels — it does **not** call the
model and is **not** a live-accuracy number. `_recorded` is intentionally allowed
to diverge from `gold` on the harder cases (e.g. an over-confident
`evidence_strength`), so the frozen number stays honest rather than a saturated
1.00. The current regression sits at overall precision ≈0.95 / recall ≈0.94,
`evidence_strength` precision ≈0.84 — comfortably above the
`--min-precision 0.8 / --min-recall 0.8 / --min-evidence-strength-precision 0.7`
gate, which is unchanged.

### Re-recording — where live accuracy is measured

Live accuracy is measured only when you re-record against the real model:

```bash
make eval-prefill-record        # AI_PROVIDER=anthropic python scripts/eval_claim_prefill.py --record-live
# needs ANTHROPIC_API_KEY; AI_MODEL overrides the model (default claude-opus-4-8)
```

`--record-live` calls the live model once per golden example, **overwrites**
each `_recorded` (and its fixture in `tests/fixtures/ai/`) with the fresh output,
then prints the field metrics — now scoring the *live* suggestions against
`gold`. That printed number is the honest live-accuracy snapshot; the JSON edit
keeps `_recorded` and the fixtures in lock-step (a failed/refused call leaves
that example's prior recording untouched). Commit the refreshed
`eval/claim_prefill_labeled.json` **and** the changed `tests/fixtures/ai/`
together — that moves the regression baseline forward to the latest live
behaviour and is the moment a new live-accuracy figure is recorded. Re-record
after a prompt change (`PREFILL_PROMPT_VERSION`), a model bump (`AI_MODEL`), or
when growing the golden set; then re-run `make eval-prefill` to confirm the gate
still passes offline.

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
are now **labeled in `eval/relevance_labeled.json`** (`origin: hard_case`) so the
measured numbers are honest: they drop the heuristic from a saturated 1.00 to
precision 0.86 / recall 1.00. Neither the trained model nor the embedding anchors
(local hashing or the real semantic `st`) beats the heuristic on these yet — they
are candidates for a classifier once the harvested label set grows.

### Improvement applied: automated educator lane

Educator-competence evidence (in-service teacher PD, educators' digital/AI
competence, AI literacy in teacher education) is exactly the "teacher studies the
learner gate drops as adult" class that used to require **manual re-opening** of a
filtered source. The educator lane (`is_educator_audience`, run inside
`filter_relevant_sources`) now keeps it automatically and tags it
`audience: "educator"`, while its higher-education and teacher-tool-use guards keep
the lane precise (pure teacher tool-use stays the learner-lane FP class above). It
is measured against its **own** set, `eval/relevance_educator.json` (separate from
the learner labels so it never perturbs the heuristic baseline or the classifier
training inputs): **precision 1.00 / recall 1.00** on the real educator-strand
positives plus educator-shaped guard negatives. Run `make eval-educator`; the
learner floor is unchanged (P 0.86 / R 1.00). See
[docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md).

**Educator strand deepened (preservice-teacher cases).** Two preservice/future-
teacher studies the learner gate had rejected as adult — "Fostering AI Literacy …
among Preservice Teachers" and "Investigation of Digital Competencies and AI
Literacy of Special Education Students" (pre-service teachers) — were re-opened
with the new `reopen` subcommand (which also dropped their stale harvested
negatives), reviewed, and folded in with `attach-claim`. Each active educator
skill now rests on two supporting claims: `skill-educator-ai-pedagogy` (0.46 →
0.50) and `skill-educator-digital-competence` (0.55 → 0.54, a correct dip — a
second low-strength claim below the prior mean). Both studies are also added to
`eval/relevance_educator.json` (the Investigation case exercises the
higher-education guard's preservice exemption).

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
| 2026-06-24 (first live cron) | 18 | ~0.40 | 3 | 0.20 | 44 | First scheduled run merged via PR #71; Semantic Scholar key now live (+12 candidates). Low extraction yield: off-scope audiences (older adults, social workers, experts) + definitional/non-finding sentences. Promoted: K-12 media-literacy policy → digital-media-literacy, secondary-school AI-literacy review → ai-literacy, children's AI mental models → ai-foundational-concepts |
