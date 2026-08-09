# Operations Runbook

How to run the Future Skills Evidence Graph in ongoing operation: produce
candidates, review them, verify quality, and improve the pipeline over time.

The automation only ever produces **candidates**. Publishing active skills always
requires human review through pull requests. Nothing here changes that.

> Bringing the project into live operation for the first time? Work through
> [docs/go-live-checkliste.md](docs/go-live-checkliste.md) — the configuration and
> first-cycle acceptance steps that this runbook assumes are already in place.

## Components

> **OpenAlex ranked by date, not relevance, until 2026-08-01.** `fetch` sent
> `sort=publication_year:desc` alongside `search`, which replaces the relevance
> ranking: the API returned "everything matching any query term, newest first".
> Measured across four queries at ten results each, date-ordering and relevance
> ordering shared **zero** works. Recency is now a filter and relevance decides
> the order. See "What the date sort cost" below for what it did to the
> catalogue, and `scripts/probe_openalex_ranking.py` for the measurement.

| Stage | Script / Workflow | Notes |
| --- | --- | --- |
| Import (5 sources) | `ingest_openalex / crossref / semantic_scholar / arxiv / eric .py` | One shared pipeline (`common.run_importer`; per source only `fetch`/`convert` differ). Each degrades gracefully on outage (`fetch_or_warn`); single page of `--limit` (25) results per query — no pagination. Crossref ingests no abstracts (JATS-only, sparse), so its sources never yield automatic claims — metadata only |
| Relevance filter | `common.filter_relevant_sources` | Topic match required; off-scope filter; threshold 0.3; tags `audience` and runs the educator lane (`is_educator_audience`) alongside the learner gate; vocabulary is multilingual (English, German, French, Italian — all Swiss school languages, incl. LP21/PER/Piano-di-studio stage terms) |
| Claim extraction | `extract_claims.py` | Verbatim finding sentences + text anchors (up to 3 per abstract — breadth feeds the skill score); skips methodology; abbreviation-safe sentence split |
| Clustering | `cluster_claims.py` | Proposes candidate skills for uncovered topics |
| Review | `promote_candidate.py {claim,skill,reject,reject-source,promote-source,attach-claim,reopen}` | Promotes to reviewed/active; `reject-source` harvests a negative label; `reopen` flips a rejected record back to candidate |
| Review per PR-Kommentar | `review-command.yml` · `run_review_command.py` | Browser-only review: maintainer slash-commands on the candidate PR run the same `promote_candidate.py` (all gates unchanged); commits back to the PR branch |
| Scoring | `score_evidence.py` | Recomputed automatically on promotion; drift-guarded by validation |
| Validation | `validate_data.py` | Schema + cross-refs + score drift |
| Dashboard | `build_site.py` + `deploy-pages.yml` | Auto-deploys on push to `main` |
| Pipeline | `research-pipeline.yml` | Cron Monday 05:17 UTC + manual dispatch |
| Manual report intake | `ingest-from-issue.yml` (issue) · `ingest-reports.yml` (dispatch) · `parse_ingest_issue.py` · dashboard `site/einreichen.html` | Off-cycle; same LLM importer + candidate PR; needs `ANTHROPIC_API_KEY` + `AI_MODEL` |
| Web-search discovery | `ingest-websearch.yml` (dispatch) · `ingest_websearch.py` · `data/source_domains.json` | Off-cycle; query → candidate web sources; keyless (DuckDuckGo/`ddgs`); open search, tiered trust |
| Allowlist audit | `audit_domains.py` (`make audit-domains`) | Read-only; mines the review ledger for evidence-backed promotions/reviews of the trust tiers + `CREDIBLE_DOMAINS`; see [docs/allowlist-pflegen.md](docs/allowlist-pflegen.md) |

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
   # In-scope source → reviewed + harvests a POSITIVE relevance label
   # (--year <yyyy> is required when the candidate arrived without a year):
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

### Review from the browser (no local setup)

Every command in step 3 can also be run **as a comment on the candidate pull
request** — for reviewers without a local clone/Python. Comment one command per
line, either in slash form or copied verbatim from the triage worksheet:

```text
/promote-source src-abc --year 2024
/claim clm-xyz --context "..." --age-range "12-18" --outcome "..." --evidence-type systematic_review --evidence-strength moderate --supports skill-ai-literacy
python scripts/promote_candidate.py reject clm-uvw
```

`review-command.yml` runs them through the **same** `promote_candidate.py` —
placeholder blockade, reviewed-evidence invariant, score recompute and
re-validation all apply unchanged — commits the result to the PR branch and
comments the per-command outcome back. Guardrails: only
owner/member/collaborator comments run anything, the body is never shell-
interpolated (env + argv allow-list), and fork or closed PRs are refused. The
merge decision (step 4) stays a human click either way.

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
4. **Telegram bot (optional).** A message to the configured bot — a direct PDF
   link, an attached PDF, or pasted report text — is translated by the polling
   `telegram-intake.yml` workflow into the SAME issue-form intake (entry
   point 2), so it flows through the identical import and review path. The bot
   also mirrors pipeline results, new issues, and failures into the chat.
   Setup, security model (chat allowlist = LLM-budget control), and limits:
   [docs/telegram-integration.md](docs/telegram-integration.md).

`ingest-from-issue.yml` fires on every `ingest`-labelled issue **from a repo
owner/member/collaborator**; external submissions wait (with an explanatory
comment) until a maintainer adds the `ingest-approved` label, so strangers
cannot spend LLM budget unreviewed. It resolves the
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

Keep that allowlist evidence-based with `make audit-domains`: it mines the
reviewer's promote/reject ledger and proposes which `open` publishers have earned
a tier (and a `CREDIBLE_DOMAINS` slot) and which tiered domains only yield
rejects. Read-only — every change still lands through a PR. Full method in
[docs/allowlist-pflegen.md](docs/allowlist-pflegen.md).

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
dependency-free hashing embedding. The current honest verdict (122-example set,
including the German, French and Italian cases): heuristic F1 1.00, model F1
0.68, `st` anchors F1 0.76, `local` anchors F1 0.69 — none beats the heuristic,
so it stays the active default (see
[docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md)).

Triggers → actions:
- **False positive seen** → `reject-source`; add the domain to `OFF_SCOPE_KEYWORDS`
  (`scripts/common.py`); add the example as a negative to
  `eval/relevance_labeled.json`; re-measure with `eval_relevance.py`.
- **False negative seen** (recall probe) → add the missing keyword to
  `TOPIC_KEYWORDS`; re-measure.
- **After any vocabulary change** → `make refilter`: re-checks the OPEN
  candidate backlog against the new vocabulary and lists the candidates the
  current heuristic would drop (with drop reason + ready `reject-source`
  command, `eval/candidate_refilter.json`). The filter only runs at ingest
  time, so without this pass stale candidates linger that today's filter
  would refuse. Read-only — the reviewer decides each row.
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

> **Offene Messungen.** Dieser Pre-Fill ist seit 2026-08-01 live gemessen — zwei
> Läufe, Zahlen unter „Re-recording" weiter unten. **Zwei** KI-Fähigkeiten sind
> weiterhin gebaut, aber ungemessen: der Skill-Link-Vorschlag und die
> Gegenevidenz-Lane. Die Schritt-für-Schritt-Anleitung dafür steht in
> [docs/naechste-schritte.md](docs/naechste-schritte.md).


Off by default (`AI_PROVIDER=none`): extraction is byte-identical to the LLM-free
pipeline. When a provider is configured (`AI_PROVIDER=anthropic`, model from
`AI_MODEL`, default `claude-opus-4-8`), `extract_claims.py` additionally asks the
LLM to *suggest* the manual review fields (`context`, `outcome`, `age_range`,
`evidence_strength`). The suggestion is stored **only** under
`claim["assist"]["suggestions"]` with provenance; the real fields keep their
placeholders and `statement`/`text_anchor` stay verbatim.

```bash
python scripts/eval_claim_prefill.py                 # offline field metrics (fixtures)
python scripts/eval_claim_prefill.py --min-precision 0.8 \
  --min-evidence-strength-precision 0.7 --min-age-range-precision 0.8   # CI gate
python scripts/eval_claim_prefill.py --write-fixtures # replay '_recorded' into the cache
python scripts/eval_claim_prefill.py --lexical-text-scoring  # pre-semantic baseline
```

During review, `promote_candidate.py` prints any suggestion and
`--accept-suggestions` adopts the non-null values as starting points. This never
weakens the gate: fields the model left null stay placeholders and still block
promotion, a reviewed claim still needs a `--supports`/`--contradicts` skill
link, and every explicit flag overrides the suggestion.

## What the date sort cost (audit, 2026-08-01)

`ingest_openalex.fetch` ranked by publication date instead of relevance from the
start until 2026-08-01. Before deciding what to do about the sources already
collected that way, here is what the catalogue actually holds.

**How much of it came through OpenAlex**

| origin | sources | candidate | rejected | reviewed | rejection rate |
| --- | --- | --- | --- | --- | --- |
| ERIC | 304 | 283 | 7 | 14 | 2% |
| Semantic Scholar | 234 | 216 | 2 | 16 | 1% |
| **OpenAlex** | **120** | 82 | **26** | 12 | **22%** |
| manual / other | 52 | 1 | 20 | 31 | — |

**What it contributes**

| | OpenAlex share |
| --- | --- |
| sources | 17% (120 of 710) |
| claim citations | 13% (190 of 1432) |
| citations in **reviewed** claims | **8%** (5 of 59) |

**Reading.** OpenAlex sources were rejected at roughly **ten times** the rate of
the other automated origins, and they thin out further at every stage where a
human looks: 17% of sources, 13% of citations, 8% of what reviewers accepted.
That is the signature of an importer delivering poorly matched material — and it
is also the reason the damage stayed contained. The relevance filter and the
reviewers caught most of it; the reviewed core of the catalogue rests
predominantly on manually curated sources (61% of citations in reviewed claims).

**No purge is warranted.** The 12 reviewed OpenAlex sources passed human
judgement and stand on their own merits regardless of how they were found. The
82 candidates never entered the catalogue. Deleting records because of how they
were retrieved would discard work a reviewer already did.

**What was lost is invisible in the data: recall, not precision.** The papers
this importer *should* have returned and did not leave no trace — there is no
record of a missing source. That loss cannot be audited after the fact, only
stopped going forward. It also means the OpenAlex share above understates the
harm: the question is not how much bad material got in, but how much good
material never appeared.

### Choosing a provider (and why there is no framework here)

`AI_PROVIDER` accepts `none` (default) | `anthropic` | `openai` | `ollama` |
`cache`. Each live provider has its own ~40-line adapter in `ai_provider.py`
rather than a shared abstraction, because the one thing they genuinely differ on
is exactly what an abstraction would have to hide — how a JSON Schema is
attached to the request:

| provider | schema goes in | determinism | package |
| --- | --- | --- | --- |
| `anthropic` | `output_config.format` | `effort="low"` (temperature is rejected) | `anthropic` |
| `openai` | `response_format.json_schema` (`strict`) | `temperature=0` | `openai` |
| `ollama` | `format` (the schema itself) | `options.temperature=0` | **none** — stdlib HTTP |

`ollama` is deliberately package-free: it talks to a local server over `urllib`,
so the keyless option a contributor without an API budget can run costs
`requirements-dev.txt` nothing. Adding a provider is one adapter plus one
registry entry, and changes nothing for the others. That is the concrete reason
this project does not need an LLM framework to serve several providers.

**Cache keys are namespaced by the answering provider.** The key used to be
`{kind, model, prompt, schema}`, so two providers serving the same model id
would have collided and silently replayed each other's answers. Anthropic keeps
the historic key shape — changing it would invalidate the 50 committed fixtures
for no benefit — and every other provider is namespaced by name. `cache` mode
replays `AI_CACHE_PROVIDER`'s recordings (default `anthropic`).

**Which provider to use is a measurement, not a preference.**

```bash
make compare-providers          # offline, one column per provider
AI_PROVIDER=openai python scripts/compare_providers.py \
  --record openai --model openai=gpt-4o     # record a challenger, then compare
```

The comparison always scores through `cache` mode, so it can never spend money
or vary between runs; recording is a separate, explicit step.

**Activation rule.** A provider replaces `anthropic` only when it beats it on
`GATED` precision (the micro-average of `age_range` + `evidence_strength`) by
more than **0.02** — smaller than that is noise on a 50-example set — *and* does
not lose more than **0.05** on either structured field individually, because an
average can hide a collapse in one field. Ties go to the incumbent: switching
costs a re-record of every fixture. A provider that merely matches is still
worth knowing about — it means the pipeline is not vendor-locked — but it is not
a reason to switch. `tests/test_ai_providers.py` pins this rule, including the
two ways a comparison flatters a challenger.

Today only `anthropic` has recordings, so the table shows one column and says
so. That is the expected state until someone records a challenger.

### Optional skill-link suggestion (separate call)

A claim only becomes `reviewed` once it links at least one skill, which is the
last purely manual lookup in the review loop. With a provider configured,
`extract_claims.py` makes a **second, independently versioned call**
(`skill-link-v1`) proposing `supports_skill_ids` / `contradicts_skill_ids`, and
stores it under `claim["assist"]["skill_links"]` with its own provenance.

It is a separate call rather than a fifth pre-fill field on purpose: it needs
the skill catalogue as context (which would bloat every pre-fill prompt and
could shift the four calibrated fields), a shared prompt would mean a shared
version that could never be re-recorded independently, and keeping the pre-fill
prompt untouched keeps its 50 fixtures and measured numbers valid.

Guardrails:

- **Only active skills are offered.** A candidate skill is itself unreviewed,
  and pointing new evidence at unreviewed evidence is how a catalogue drifts.
- **Unknown ids are dropped, with a warning.** Every proposed id is checked
  against the catalogue, so a hallucinated or stale id never reaches an assist
  block a reviewer might trust.
- **Advisory, like every assist output.** The real `supports_skill_ids` stays
  empty; promotion still requires an explicit `--supports` / `--contradicts`.
- **Inert when off.** With `AI_PROVIDER=none` the catalogue is not even read.

```bash
make eval-skill-links           # offline report (fixtures)
make eval-skill-links-record    # live measurement; needs ANTHROPIC_API_KEY
```

**The golden set was proposed, then curated — and the harness enforced the
order.** The gold links in `eval/skill_link_labeled.json` were proposed by an
agent; project governance puts editorial judgement with a person. While its
`_status` was `proposed-unreviewed`, `eval_skill_links.py` printed its numbers
but **exited non-zero on any `--min-*` flag**, so no CI gate could rest on labels
nobody had checked. A reviewer went through them on 2026-07-31 and set `_status`
to `reviewed`, dropping `prefill-spaced-retrieval` — leaving **10 links and 40
empty**. That refusal still guards any future golden set; the mechanism is
tested against a synthetic unreviewed copy so it survives the release.

Read the `abstain` column first. 40 of the 50 examples map to no catalogue skill
— an empty gold link is a real label, not a gap — so that column is where an
over-eager model shows up before precision does.

#### Measured baseline — `skill-link-v1`, `claude-opus-4-8`, 2026-08-01

| field | P | R | F1 | abstain | TP/FP/FN |
| --- | --- | --- | --- | --- | --- |
| `supports_skill_ids` | 0.71 | 0.91 | 0.80 | **0.93** | 10/4/1 |
| `contradicts_skill_ids` | 1.00 | 1.00 | 1.00 | 1.00 | 0/0/0 |

**The model does not flood.** It leaves 37 of the 40 empty-gold examples empty,
which was the failure mode this feature had to clear before it could be gated at
all.

**The three that slipped share one confusion.** `prefill-adult-mooc` and
`prefill-spaced-retrieval` both drew `skill-self-regulated-learning` where gold
is empty — and `spaced-retrieval` is *exactly* the link the human reviewer
removed. The model independently reproduces the agent's original proposal, so
the reviewer's boundary is precisely the one it cannot see: effectiveness of a
*prescribed* learning technique is a memory outcome, not evidence about a
learner's self-regulation. The third (`prefill-adult-digital-literacy`) is the
same rule from the other side — topical proximity without a measured outcome.
Recall's single miss is the second link on the one two-link example; when a link
genuinely exists, the model finds it.

**`contradicts_skill_ids` is empty, not perfect.** 0/0/0: no golden example
carries a contradiction and the model proposed none. A 1.00 over an empty set
measures nothing — and that gap is what the counter-evidence lane exists for.

**Why abstention carries the gate and precision only a tripwire.** The
denominators are small and unequal, which decides what can hold a floor:

| metric | denominator | one flip moves it by |
| --- | --- | --- |
| abstention | 40 empty-gold examples | 0.025 |
| precision | 14 link instances | 0.071 |
| recall | 11 gold links | 0.091 |

So `--min-abstention 0.85` (measured 0.93, ~3 failures of headroom) is a real
floor, and it is also the number that governs review load. `--min-precision 0.6`
(measured 0.71) is deliberately loose: it is a **tripwire for a broken prompt**
that starts linking everything, not a claim that 0.71 is a defended level — one
extra false positive is worth 0.07 here, against 0.02 on the pre-fill set.
Recall is left ungated for the same reason.

**A second recording produced byte-identical output.** Same 50 live calls, same
link sets, no diff in `_recorded` *or* in the raw responses under
`tests/fixtures/ai/` — the run ended with "Live baseline unchanged; nothing to
commit". The five disagreements repeated exactly, so the
`self-regulated-learning` confusion above is not merely reproducible but
deterministic on this prompt.

Two draws that agree do not measure a variance; they only bound it below the gap
between two draws. But they do change what the margin is *for*. On the pre-fill
set part of every threshold's headroom is spent absorbing run-to-run noise of
about one example. Here there is no noise to absorb, so the whole margin is
available for real change — a prompt edit, a new skill in the catalogue, a model
bump. That is the case the gate is meant to catch, and it is why the thresholds
are not tightened toward the measured values: a deterministic score is not a
stable one, it is one whose instability lives entirely in the inputs.

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
1.00. The current regression sits at GATED precision 0.85 / recall 0.76,
`evidence_strength` precision 0.80 and `age_range` precision 0.91 — above the
gate `validate.yml` actually runs, which is unchanged:
`--min-precision 0.8 --min-evidence-strength-precision 0.7
--min-age-range-precision 0.8 --min-outcome-precision 0.75
--min-context-precision 0.85`. (Recall is reported but **not** gated;
`--min-recall` exists and is deliberately left unset, because abstention lowers
recall by design — see the abstention note below.)

One subtlety worth stating plainly: **immediately after a re-record these
regression numbers *are* the live-accuracy numbers**, because `_recorded` was
just overwritten with live output. The two only start to drift apart when `gold`
is edited afterwards, or when the prompt changes without a re-record. The
regression/live distinction is therefore about *what a later CI run measures* —
frozen output, never the model — not a claim that the two figures differ at the
moment of recording.

### Re-recording — where live accuracy is measured

#### Measured baseline — v7, `claude-opus-4-8`, 2026-08-01

The v7 fixtures were originally *migrated* from the v6 recordings
(`high` → `strong`) rather than recorded, which left the two substantive v7
changes unmeasured. They have since been recorded live **twice**, via the
`eval-prefill-record` workflow:

| field | run 1 | run 2 | abstain (both) |
| --- | --- | --- | --- |
| `age_range` | 0.89 | **0.91** | 7 |
| `outcome` | 0.87 | **0.87** | 4 |
| `context` | 0.98 | **0.96** | 0 |
| `evidence_strength` | 0.78 | **0.80** | 0 |
| GATED (age+strength) | 0.82 | **0.85** | 7 |

Run 2 is what is committed. Precision figures, `outcome`/`context` scored
semantically.

**Run-to-run spread is about one example.** Every field moved by at most 0.02–0.03,
and one example out of 50 is worth 0.02. That is the number to reason with when
setting a gate: the current thresholds sit at least one example below the worse
of the two runs, which is meant to be tight — a future run that trips a gate is a
signal worth reading, not noise to absorb by lowering it.

**Two findings that justify a v8.** Both hold in *both* runs as aggregate
patterns, so neither is sampling noise — though individual examples do move
between runs (`prefill-mindset-intervention` went `low` → `strong` against the
same `moderate` gold), which is exactly why the claims below are about the shape
of the errors and not about single items. Counts are from the committed run:

1. **`evidence_strength` abstained 0/50, in both runs.** The v7 permission to
   answer "not determinable" does not fire for the one field it was written for.
   It is also the weakest field (0.78 / 0.80) — but of its 10 disagreements *all*
   are adjacent steps (`low`↔`moderate`, `moderate`↔`strong`), never
   `low`↔`strong`, and they land on both sides of `gold` (6 above, 4 below). So
   this is boundary placement on a 3-level ordinal scale, **not** a systematic
   tendency to overrate evidence — which is the failure mode this catalogue would
   actually have to worry about. Exact-match scoring charges an adjacent step the
   same as a total miss, which makes 0.80 read worse than the behaviour is.
2. **`age_range` is systematically too wide.** All disagreements err in the same
   direction — the model proposes the broader band (`12-18` for `14-18`, `6-12`
   for `9-12`, `11-18` for `13-17`; run 1 additionally `12-18` for `12-15`).
   Unlike (1) this *is* directional, and directional error is what a prompt can
   fix. A related single case in `outcome`: where `gold` is null, the model wrote
   "…but measures no learning outcomes" — it recognised the absence and filled
   the field anyway.

A v8 addressing (1) and (2) now has a measured baseline to be compared against.
Do not change the prompt and the golden set in the same step.

> **Re-recording locally** needs one extra step the workflow does for you: the
> fresh `outcome`/`context` texts have no embedding vectors, so run
> `make eval-prefill` once with `sentence-transformers` installed to mint them,
> and commit `eval/claim_prefill_labeled.json`, `tests/fixtures/ai/` **and**
> `tests/fixtures/embeddings/` together. Leaving the vectors behind does not fail
> loudly by itself: the scorer degrades to lexical and the semantic gate is built
> to *skip* rather than fail, so CI would pass while enforcing nothing.
> `EmbeddingFixtureCoverageTest` is what catches it — in `make test`, and in the
> record workflow before it opens a pull request.

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

**What is gated, and how each field is scored.** All four fields carry a
precision floor. `age_range` and `evidence_strength` are the two **structured**
fields and make up the `GATED (age+strength)` overall line. `outcome`/`context`
are free-text suggestions and are gated **conditionally** — only while the
semantic scorer is available; the report still tags them `(advisory)` because
they never enter that overall line. See "The decision" below.

### How the free-text fields are scored (semantic, fixture-backed)

`outcome`/`context` used to be scored by Jaccard token overlap, which measured
the wrong thing: the model states the same finding as the gold label in
different words, and the lexical scorer counted that as a miss. Measured, that
put `outcome` at **P 0.11** — a scorer artifact, not a model failure.

They are now scored by **cosine similarity over the project's own fixture-backed
embeddings** (`ai_provider.embed`, `EMBEDDING_PROVIDER=st`), which measures
agreement instead of vocabulary:

| field | lexical (old) | semantic (now) |
| --- | --- | --- |
| `outcome` | P 0.11 | **P 0.85** |
| `context` | P 0.44 | **P 0.98** |

The threshold (`SEMANTIC_MATCH_THRESHOLD = 0.60`) is **calibrated, not guessed**:
against a cross-paired negative control (every `gold_i` vs every `recorded_j`,
i ≠ j) the matching pairs sit at median 0.736 (`outcome`) / 0.883 (`context`)
while mismatches reach only p99 0.510 / 0.531. At 0.60 the scorer accepts 87 % /
98 % of true paraphrases at a 0.1 % / 0.2 % false-match rate. The negative
control is the point: it shows the scorer separates paraphrase from unrelated
text rather than waving everything through. Re-run the calibration if the
embedding model changes.

Two properties keep this honest and cheap:

- **The lexical number stays on screen.** Every report prints the semantic score
  with the old token-overlap precision in brackets, so a reader can always tell
  whether a number moved because the model improved or because the ruler
  changed. `--lexical-text-scoring` forces the old scorer outright.
- **Offline and deterministic, like everything else.** The needed vectors are
  committed under `tests/fixtures/embeddings/`, so a CI run is pure cache reads —
  verified at zero model loads. If a vector is missing and the package is absent,
  `load_embeddings` warns and the harness **falls back to the lexical scorer**
  instead of failing. `tests/test_claim_prefill_scoring.py` locks in the
  paraphrase/unrelated behaviour, the fallback, and fixture coverage of the
  golden set.

After a `--record-live` run the recorded texts change, so re-run
`make eval-prefill` once with `sentence-transformers` installed to mint the new
vectors and commit `tests/fixtures/embeddings/` alongside the refreshed fixtures.

#### The decision: outcome/context are now gated, conditionally

They were ungated because they could not be measured fairly. Once they could,
the reason expired, so both carry a floor in `validate.yml`:

| field | measured | floor | headroom |
| --- | --- | --- | --- |
| `outcome` | 0.85 | `--min-outcome-precision 0.75` | 0.10 |
| `context` | 0.98 | `--min-context-precision 0.85` | 0.13 |

The headroom matches how the structured fields are gated (`age_range` 0.94
measured / 0.8 floor, `evidence_strength` 0.82 / 0.7): tight enough to catch a
real regression, loose enough that normal re-record jitter does not fail a run.

**Both gates skip themselves when the semantic scorer is unavailable.** This is
the important part. Under the lexical fallback `outcome` reads 0.11, so a 0.75
floor would fail every run where `tests/fixtures/embeddings/` is missing — a
red build caused by an absent file rather than by a regression. The script
prints a `SKIPPED:` line naming the floors it did not enforce and exits 0.
A gate that cannot distinguish "worse" from "unmeasurable" is worse than no gate.

They stay **precision-only**, for the reason the structured fields do: the
pre-fill suggests, so a safe abstention should not fail a run.

**Decommission rule.** Drop these two gates back to advisory if either holds:

1. a live re-record puts `outcome` or `context` precision below its floor for
   reasons of substance rather than jitter — i.e. the suggestions really did get
   worse and the prompt cannot recover them; or
2. the embedding model changes and the threshold calibration is not redone. The
   0.60 floor is a property of `all-MiniLM-L6-v2`'s similarity distribution, not
   a universal constant — re-run the cross-paired negative control first (see
   above) and only then re-enable.

This mirrors how `RELEVANCE_CLASSIFIER` is handled: a signal is switched on only
while a measurement supports it, and switching it back off is a documented,
expected move rather than a failure.

**The ceiling above these floors is not yet measured.** Every number above
compares the pipeline to `gold` and treats `gold` as ground truth. How
reproducible `gold` itself is has never been measured, and that decides how the
floors read: if two reviewers agree on `evidence_strength` only ~80% of the
time, then the measured 0.80 is already at the label ceiling and the 0.10 of
headroom is absorbing reviewer scatter rather than model regression.

`scripts/eval_agreement.py` (`make agreement`) measures the label side —
agreement, Cohen's kappa, a Wilson interval, and whether a comparison is
independent and large enough to carry a floor at all. It is **not** a CI gate
today, for a reason worth stating: the only comparison currently computable is
the 16-title overlap between `eval/relevance_labeled.json` and
`eval/relevance_harvested.json`, it agrees 16/16, and that number measures
nothing — the two sides most likely record the *same* review session rather than
two independent judgments. The tool reports it as PROVENANCE UNVERIFIED instead
of banking it. `make agreement-worksheet` produces the blind second-rater
worksheets that would close this; the protocol, the evidence behind the
provenance verdict, and the rule for reading a measured ceiling against these
floors are in [docs/eval-baseline.md](docs/eval-baseline.md). Nothing in
`validate.yml` changes until an independent pass exists.

**Recall is reported, not gated.** Precision — "when the model proposes a value,
is it right?" — is the metric that protects reviewer trust, so that is what the
gate enforces (`--min-precision`, `--min-age-range-precision`,
`--min-evidence-strength-precision`). Recall is printed but **not** a hard gate:
the pre-fill only *suggests*, so a safe abstention (null on an age-silent
abstract) just means the reviewer fills that field by hand — it should not fail
the run. Live re-records also showed recall cannot reach ~0.8 without the model
over-widening age bands to "recall" more, which *lowers* precision — a
precision/recall trade-off where precision is the one worth keeping. (`--min-recall`
still exists on the script for ad-hoc checks; CI just doesn't pass it.)

- `age_range`: numeric tolerance with the bands required to overlap, **±1 on the
  lower bound** (entry age is precise) and **±2 on the upper bound** (the
  school-stage "end" is fuzzy — "secondary" runs to 16–18 by country). Grade
  fuzz agrees; a lower bound off by years, an upper bound off by 3+, or a
  non-overlapping band is still flagged.
- `evidence_strength`: **exact category** — adjacent notches are *not* folded
  together, so a one-level disagreement keeps costing.

The prompt (v7) is calibrated to the gold to remove the systematic live biases
the English re-records surfaced: it no longer asks for a *conservative /
when-in-doubt-low* strength and instead pins an explicit study-type rubric
(RCT / systematic review / meta-analysis ⇒ strong; controlled or multi-site ⇒
moderate; single small or uncontrolled ⇒ low), and it tells the model not to pad
the age band to the scale ends. v5 additionally tried mapping a named school
stage to a typical age band to lift recall; the live run showed it backfired
(broad stage bands where the gold has the study's narrower one, `age_range`
precision 0.94 → 0.82), so v6 reverted that part.

**One evidence-strength vocabulary (v7).** The prompts and their JSON Schemas
used to ask for `{low, moderate, high}` while `schemas/claim.schema.json` and
`promote_candidate.py` use `{low, moderate, strong}`; a mapping in
`promote_candidate.py` papered over the gap on acceptance, but the assist block
a reviewer reads still showed a value the data model does not know, and the
golden set measured in the wrong vocabulary. Both prompts now render the
vocabulary from `common.EVIDENCE_STRENGTH_VALUES` (the way `AGE_SCALE` is
rendered), `tests/test_claim_prefill_scoring.py` asserts it still equals the
schema's enum, and the `"high" → "strong"` map survives only as pre-v7 legacy
compatibility.

**`evidence_strength` may now abstain (v7).** On the golden set it proposed a
value 50/50 — it never once said "I can't tell". A model that always guesses a
strength is exactly the reviewer-trust risk the gate exists to catch, so v7
names `null` as the right answer when the abstract does not reveal the study
type or sample. **This change is unmeasured until the next `--record-live` run**
(see below).

**Why `age_range` recall stays at 0.77.** Of its 8 recall misses, *none* names an
age in the abstract — they read "across grade levels", "across subjects and
school ages", "two primary cohorts", while the gold label derives a band from
the school stage. Recovering them means inferring age from a stage name, which
is precisely what v5 did and what cost precision 0.94 → 0.82. 0.77 is therefore
the ceiling under this gold definition, and it is a property of the golden set,
not a model weakness. Leave the age wording alone.

Those prompt effects are only visible on a **live** re-record — the offline gate
replays the frozen `_recorded`. Current offline regression, measured:

| field | P | R | note |
| --- | --- | --- | --- |
| `age_range` | 0.94 | 0.77 | gated ≥ 0.8 |
| `evidence_strength` | 0.82 | 0.82 | gated ≥ 0.7; never abstains (50/50) |
| `outcome` | 0.85 | 0.87 | advisory, semantic |
| `context` | 0.98 | 0.98 | advisory, semantic |
| **GATED (age+strength)** | **0.87** | 0.80 | gate ≥ 0.8 |

## Guardrails

- Review and merge the `research/candidates` PR promptly so candidates do not
  pile up across weeks in one PR.
- Retrain the model only with the fixed seed; commit the artifact and the CV
  verdict together.
- Score drift is auto-handled: `promote_candidate.py` recomputes scores and
  `validate_data.py` blocks drift.
- Reviews live **inside** the `candidates-*.json` files — `promote_candidate.py`
  flips `status` in place and never moves a record to a curated file. So the
  ingest workflows must not check those files out from the `research/candidates`
  branch wholesale; they merge instead
  (`scripts/restore_pending_candidates.py --ref FETCH_HEAD`), keeping the base
  branch's copy of every record it already carries and appending only the
  genuinely pending ones. If an ingest run ever fails with an `evidence_score`
  mismatch on a skill it never touched, that restore is the first place to look:
  a reverted claim status silently drops the claim out of scoring.

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

**Fresh-data false-positive classes (addressed).** Two classes were labeled in
`eval/relevance_labeled.json` (`origin: hard_case`) and each now has a targeted
rule (issue #63):

- **Teacher tool-use** (teachers are a legitimate audience, so a blanket teacher
  gate would cost recall) → `is_teacher_tooluse` drops a source only when a
  teacher/educator subject is paired with a productivity/tool-use marker
  (`EDUCATOR_OFF_KEYWORDS`) and no strong teacher-education phrase is present.
- **Disaster/health papers** that name a school-age audience and a topic in the
  title → an off-scope term in the **title** is now decisive in `is_off_scope`
  (the abstract-only title-anchor exemption stays); `disaster`/`earthquake` were
  added to `OFF_SCOPE_KEYWORDS`.

The heuristic now measures **precision 1.00 / recall 1.00** on the 87-example set
(was 0.86 / 1.00), and the model still does not beat it on held-out CV (F1 0.86 ≤
1.00). `test_hard_false_positive_classes_are_dropped` guards the fix.

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
training inputs): **precision 1.00 / recall 1.00** on 26 examples — the real
educator-strand positives plus editorial positives (incl. German cases) and
educator-shaped guard negatives (faculty development, teacher tool-use,
adult/corporate training). The regression floor is deliberately 0.85/0.85, below
the measured value: on a small set a 0.99 assertion is memorization, not
measurement. Run `make eval-educator`; the
learner floor is P 1.00 / R 1.00. See
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

### Improvement applied: multilingual (German, then French/Italian) keyword layer

The keyword vocabulary was English-only while the project is anchored to
Lehrplan 21 — a German EDK/KMK/PH-style abstract scored 0.0 and was silently
dropped, so German-language primary sources could never pass the automated
pipeline. Two changes closed the gap: `normalize_title` now folds diacritics to
base letters (before, "Schülerinnen" normalized to "sch lerinnen" and no German
keyword could match), and every vocabulary carries German equivalents — topics,
audience, Swiss school stages (Primarstufe, Volksschule, Zyklus 1–3, Sek-II
Berufsbildung so vocational learners do not trip the adult gate), the higher-ed
gate, off-scope terms, and the educator lane. The eval set grew 87 → 109 with 22
German cases (12 positives incl. educator lane and Sek-II vocational, 10
negatives incl. German higher-ed/workplace/health/tool-use);
`test_german_sources_pass_the_bilingual_filter` pins every classification. The
heuristic measures P 1.00 / R 1.00 on the grown set; the retried model (F1 0.75)
and embedding anchors (`st` 0.76 after the documented re-embed, `local` 0.59)
still do not beat it. French and Italian followed in a second pass (Plan
d'études romand / Piano di studio anchoring; élève↔étudiant and
alunni↔studenti universitari carry the audience gate; eval set 109 → 122 with
13 FR/IT cases, still P 1.00 / R 1.00). Known limit: no stemming (rare
inflections surface via the recall probe). Details:
[docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md).

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
| 2026-06-29 (backlog triage) | — | — | 0 | 0/9 | 85 | Backlog review (issue #66), not an ingest cycle. Cleared the standing pile: 9 open candidate claims + 38 candidate sources decided → 0 open claims / 0 orphan sources. Sources: 17 reviewed (in-scope AI-literacy / AI-in-education for K-18 learners + educators), 21 rejected (off-scope: health/WASH, economics, computer-vision, architecture, gender policy, EFL, higher-ed/SME workforce, ML/assessment tooling, general pedagogy). All 9 candidate claims rejected — every extracted statement was a meta/definitional "this study investigates…" sentence rather than a finding, so no new reviewed claim. Harvest 44 → 85. |
