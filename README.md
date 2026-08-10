# Future Skills Evidence Graph

Open, GitHub-first evidence catalog for future skills in AI and education.

Design principle: no skill recommendation without an evidence path.

> 🇩🇪 **Deutschsprachiger Einstieg:** Worum es geht, ohne Technik, steht in
> [docs/erklaerung-fuer-laien.md](docs/erklaerung-fuer-laien.md); die technische
> Architektur in [docs/architektur.md](docs/architektur.md); die zwei
> Ausbaustufen des Projekts – deterministischer Vor-KI-Kern (Default) und
> optionale KI-Erweiterung – in [docs/versionen.md](docs/versionen.md); die
> Governance- und
> Haltungs-Story – warum ehrliche, auditierbare KI – in
> [docs/governance-und-haltung.md](docs/governance-und-haltung.md); die
> Praxisanleitung, wie die Skill-Liste evidenzbasiert erstellt und aktuell
> gehalten wird, in [docs/tierliste-pflegen.md](docs/tierliste-pflegen.md); die
> aktuell offenen Messungen der drei noch ungemessenen KI-Fähigkeiten in
> [docs/naechste-schritte.md](docs/naechste-schritte.md); wie
> die vertrauenswürdige Such-Allowlist (Quell-Domains) evidenzbasiert
> zusammengestellt und gepflegt wird, in
> [docs/allowlist-pflegen.md](docs/allowlist-pflegen.md); die Ankerdefinitionen
> hinter den Evidenz-Zahlen – was `low`/`moderate`/`strong` heisst, warum jeder
> Quellentyp sein Gewicht trägt und wie die Methode versioniert wird – in
> [docs/evidenz-bewertung-anker.md](docs/evidenz-bewertung-anker.md); wie
> verlässlich die Eval-Labels selbst sind, gegen die alle CI-Schwellen messen,
> in [docs/eval-baseline.md](docs/eval-baseline.md).

The project starts as a static, versioned evidence graph. Research automation may create
candidate sources, claims, or skills, but publication of active skills requires human
review through pull requests.

## MVP contents

- Versioned data in `data/`
- JSON Schemas in `schemas/`
- Python validation (JSON Schema via `jsonschema`) and standard-library importer scripts in `scripts/`
- Static dashboard in `site/`
- GitHub Actions for validation, candidate research import, and GitHub Pages deploy
- Governance templates for source suggestions, claim corrections, and new skills
- Lehrplan 21 comparison view with radar chart, cycle filter, coverage table, and gap labels

## Architecture

For a visual walkthrough of how the pieces fit together — the data model, the
research pipeline, the human review loop, and publication — see
[docs/architektur.md](docs/architektur.md) (with Mermaid diagrams). A
non-technical overview is in
[docs/erklaerung-fuer-laien.md](docs/erklaerung-fuer-laien.md).

## Local commands

```powershell
pip install -r requirements-dev.txt
python scripts/validate_data.py
python scripts/build_site.py
python scripts/eval_relevance.py
python scripts/eval_relevance.py --compare-model   # fair heuristic vs model
python scripts/train_relevance.py                  # (re)train the optional model
python -m unittest discover -s tests
python -m http.server 8000
```

Then open `http://localhost:8000/public/`. The dashboard reads all data from the
generated `data/index.json`, so rerun `build_site.py` after changing data files.
The shipped index is slimmed for transport: fields the dashboard never renders
(source abstracts, `assist` blocks) are stripped at build time — the versioned
records in `data/` keep every field. The index is still a single file the
client loads whole; splitting it into shards is deliberately deferred until the
catalog approaches ~5,000 sources.

## Data model

- `Source`: bibliographic or policy source metadata.
- `Claim`: structured evidence statement extracted from a source.
- `Skill`: reviewed or candidate future-skill profile. The editorial display
  fields carry an optional German translation (`name_de`, `definition_de`): the
  dashboard prefers them and falls back to English, active skills ship both
  (guarded by a test), and claims stay verbatim in their source language —
  only editorial text translates. `promote_candidate.py skill` accepts
  `--name-de` / `--definition-de`. An optional `audience`
  field separates the two perspectives the catalog tracks: `learner` (default —
  the future skills of learners aged 0-18, anchored to Lehrplan 21 and learner
  frameworks) and `educator` (the competencies of the teachers who enable them,
  anchored to the UNESCO AI Competency Framework for Teachers). Absence means
  `learner`. Educator-competence evidence (teacher studies the learner gate
  drops as adult) now enters through an **automated educator relevance lane**
  (`scripts/common.py` `is_educator_audience`): a topic-anchored, in-scope source
  whose subject is a school educator's own competence is kept and tagged
  `audience: "educator"` instead of requiring manual re-opening. An active
  educator skill must carry a UNESCO-for-Teachers mapping the way a learner skill
  must carry a Lehrplan 21 one.
- `FrameworkMapping`: mapping between local skills and external frameworks.
- Lehrplan 21 mappings add `coverage_score` on a 0-3 scale, `cycles`,
  `curriculum_area`, `coverage_label`, and a short `evidence_path`. The
  coverage scores are editorial judgments; how they were assessed, the label
  thresholds, and the method's limits are documented in
  [docs/lehrplan21-coverage-methodik.md](docs/lehrplan21-coverage-methodik.md).

Each active skill must reference at least one supporting claim. Each claim must reference
at least one source. Candidate records may be incomplete, but must remain visibly marked
as `candidate`.

## Evidence scoring

Skill `evidence_score` values are derived, not hand-set. `scripts/score_evidence.py`
computes a claim score from source quality (60%) and stated evidence strength (40%),
then aggregates supporting claim scores per skill: the mean is scaled by a breadth
factor that rewards multiple independent claims (saturating at 6), minus a penalty
for contradicting claims. After changing claims or sources, regenerate the stored
scores with:

```powershell
python scripts/score_evidence.py --write
```

`scripts/validate_data.py` recomputes every skill score and fails when a stored
value drifts from the formula, so the dashboard's trust signal always has a
reproducible evidence path.

What the numbers *mean* is documented in
[docs/evidenz-bewertung-anker.md](docs/evidenz-bewertung-anker.md): anchored
definitions of `low` / `moderate` / `strong`, a rationale for every source-type
weight, and the rule for changing them. Two properties the scoring enforces:

- **Unknown is not weak.** A claim with an unresolvable source, an unweighted
  `source_type`, an `evidence_certainty` of `unverifiable`, or an
  `evidence_strength` outside the three anchored levels is
  *unscoreable*: `claim_score` returns `None` instead of substituting a low
  number that reads like a bad score. Such a claim leaves the calculation, and
  `validate_data.py` fails on any *reviewed* claim that cannot be scored — so a
  data defect is loud instead of quietly counted as weak evidence.
- **Every stored score names its method.** `score_evidence.py` carries a
  `METHOD_VERSION` plus a fingerprint derived from the scoring constants
  themselves; changing a weight without bumping the version fails validation and
  the pinning test. Each active skill records the `evidence_score_method` that
  produced its number, and a method change writes a `change_log` entry even when
  the value stays the same — otherwise the same stored `0.74` would silently
  mean something new.

## Automation

See [OPERATIONS.md](OPERATIONS.md) for the operating runbook: the weekly cycle,
the per-cycle verification tests, and the improvement triggers. Bringing the
project live for the first time is a separate, mostly configurative checklist:
[docs/go-live-checkliste.md](docs/go-live-checkliste.md).

The weekly research workflow runs source importers for curated queries across
OpenAlex, Crossref, Semantic Scholar, arXiv, and ERIC. The query set is no longer
hard-coded in the workflow: it lives in the versioned, human-editable
`config/research_queries.json` (a JSON array of query strings), so broadening or
retargeting the harvest is a data edit, not a CI change. Each importer runs every
configured query and deduplicates across them; adding a query needs no code. A
manual `workflow_dispatch` run can override the set for one run via its `queries`
input (one per line or comma-separated), and the `RESEARCH_QUERIES` environment
variable does the same locally — both fall back to the config file, which falls
back to a built-in default, so the pipeline never runs query-less. Beyond the
curated list, an **opt-in catalog mode** makes the harvest follow the evidence
graph itself: with the `include_catalog` dispatch checkbox (or the
`RESEARCH_QUERIES_INCLUDE_CATALOG` repo variable / env), `derive_catalog_queries`
adds one query per **active** skill — the skill name plus an audience-appropriate
scope anchor (learner vs. educator) — unioned onto the base set. So adding a skill
automatically widens the search to hunt for evidence about it, capped and logged
so a growing catalog never silently blows up the API load. It stays off by
default, keeping the search space a human decision. The importers
extract candidate claims from the new sources' abstracts (`scripts/extract_claims.py`),
clusters those claims into candidate skills (`scripts/cluster_claims.py`), and opens
a candidate pull request. While that pull request stays unmerged, later runs append
to its `research/candidates` branch instead of opening duplicates. The automated
path stays deliberately conservative: claim statements are verbatim abstract
sentences with exact text anchors, evidence strength starts at `low`, clustered
skills start at `evidence_score` 0.0, and nothing becomes active without human
review. Extraction prefers a sentence that reports a finding and never emits a
pure methodology or structure sentence ("we used interviews", "this paper
introduces a design") as a claim, so a source with no finding sentence simply
yields no auto-claim. The workflow does not publish active skills automatically.

Each importer degrades gracefully: if one source is rate-limited or unreachable,
it logs a warning and contributes no candidates that run, so the other importers
and the downstream extraction and clustering still complete. The five importers
share one pipeline (`common.run_importer`): per source only `fetch()` and
`convert()` differ, so a filter or argument change lands in one place. Harvest
depth is deliberately bounded: each importer fetches a **single page of
`--limit` results (default 25) per query and source** — no pagination; a deeper
harvest is a `--limit` bump in the workflow, not a hidden loop.

The master prompt also lists OECD, WEF, UNESCO, and EU DigComp as preferred
sources. OECD, WEF, and UNESCO publish reports without a public bibliographic
search API, so they are not part of the weekly automated harvest. They have a
dedicated **manual, opt-in** LLM importer instead
(`scripts/ingest_reports.py`, triggered via the `ingest-reports`
`workflow_dispatch` workflow): it turns a report's plaintext into a candidate
source plus candidate finding-claims, where every claim statement must be a
*verbatim* passage of the report (else it is discarded) and everything starts at
`status=candidate`/`evidence_strength=low` for human review. PDF→plaintext is a
separate step (`scripts/extract_pdf_text.py`, optional `pypdf`), kept out of the
import path. Besides the `workflow_dispatch` trigger, the same importer also has
a **mobile-friendly issue intake**: filing the "Bericht einreichen" issue form
(`.github/ISSUE_TEMPLATE/ingest-report.yml`) — pasting report text, drag-and-drop
or attaching a PDF, or giving a direct PDF URL — runs `ingest-from-issue.yml`,
which resolves the input (`scripts/parse_ingest_issue.py`) and feeds the same
candidate-PR review path, commenting the result back on the issue. The dashboard
adds a drag-and-drop convenience page on top (`site/einreichen.html`) that reads
a dropped PDF in-browser and opens the pre-filled issue form — no browser token,
GitHub handles auth. See [docs/report-import.md](docs/report-import.md). DigComp
is a
single framework document, not a search source (it already appears in
`data/frameworks/`), and enters through the manual source-suggestion governance
template.

An **optional Telegram integration** mirrors the pipeline into a chat and adds a
mobile submission channel — serverless, staying GitHub-first: workflows notify
the configured chat about weekly research results, report imports, new issues,
and failures (`scripts/telegram_notify.py`, a no-op without the secrets), and a
polling workflow (`telegram-intake.yml`) turns messages from allow-listed chats
(a direct PDF link, an attached PDF, or pasted report text) into the same
"Bericht einreichen" issue the form produces — one shared import and review
path, candidates only. Read-only chat commands render the dashboard's data as
text (`/status`, `/skills`, `/skill <term>`, `/lp21`) and `/dashboard` links
the interactive view. Replies arrive with the ~10-minute poll by default; an
optional push mode (a minimal Cloudflare relay, `relay/`, that only
re-dispatches the same workflow per webhook) brings them down to seconds
while all logic stays in Actions. Setup and security model:
[docs/telegram-integration.md](docs/telegram-integration.md).

Imported candidates pass a **relevance filter** (`scripts/common.py`) before
deduplication. The default is a transparent keyword/topic heuristic: a candidate
must match at least one MVP topic, score at or above the threshold, clear a curated
off-scope term list, and pass an audience/age gate that keeps only the ages 0-18
learner audience. The vocabulary is **multilingual (English, German, French,
Italian)**, including the school-stage terms of all three Swiss curricula
(Lehrplan 21, Plan d'études romand, Piano di studio), so sources in every Swiss
school language pass the automated pipeline like English ones. Running alongside that learner lane, an **educator lane** keeps
the topic-anchored evidence about a school educator's own competence that the
adult-audience gate would otherwise drop, tagging each survivor `audience`
(`learner` or `educator`); its higher-education and teacher-tool-use guards keep
the lane precise. The decision is **pluggable** via `RELEVANCE_CLASSIFIER`: two optional,
opt-in alternatives (a trained TF-IDF + LogisticRegression model and a pair of
embedding prototype anchors) exist but ship **disabled**, because neither beats the
heuristic on the held-out comparison. The filter mechanics, the measured
precision/recall, the optional modes, and the activation/decommission rule are all
documented in
[docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md).

## Reviewing candidates

Automation only ever produces candidates; promoting one is a human decision made
through `scripts/promote_candidate.py`. The tool applies the reviewer's field
values, refuses to promote while machine-generated placeholders remain, enforces
that an active skill rests only on reviewed claims, recomputes evidence scores, and
re-validates the repository — writing nothing if any check fails. The exact
subcommands and their flags are in the review step of
[OPERATIONS.md](OPERATIONS.md).

Rejecting a candidate records the decision (claims become `rejected`, skills
`deprecated`) so it stays out of clustering and later review passes instead of
lingering as a candidate.

`attach-claim` folds a reviewed claim into an existing skill's evidence and
recomputes the score. It refuses to attach unless the claim and all its sources
are reviewed, so the active-skill evidence path stays intact — review the source
with `promote-source` first (which also harvests a positive relevance label).

A claim only becomes `reviewed` once its context, age range, and outcome are real
(not the extraction placeholders) and it links at least one existing skill. A skill
only becomes `active` once its definition is real and every supporting and
contradicting claim is already `reviewed`.

### Harvesting relevance labels

Every review decision is, in effect, a relevance label for the underlying
**source**, so `promote_candidate.py` records each one as a labeled example
(title + abstract, with provenance) in `eval/relevance_harvested.json` — kept
**separate** from the hand-curated `eval/relevance_labeled.json`. This grows the
training base for a future relevance classifier automatically with review
throughput. The mapping is:

- Promoting a claim to `reviewed` → its source(s) are labeled **relevant**
  (positives), tagged with the deciding `claim_id`.
- `reject-source src-id` → the reviewer marks a source itself off-scope, labeling
  it **irrelevant** (a negative); the source's status becomes `rejected`.

Negatives come **only** from this explicit source reject, never naively from
rejected claims: a poorly extracted claim sentence does not mean its source is
off-scope. Labels are deduped by normalized title (first decision wins) and carry
provenance (`decision`, `harvested_at`, `source_id`, plus `claim_id` for
positives).

**Selection bias (important).** Only candidates that already passed the relevance
filter ever reach human review, so the harvested set systematically
*under-represents the off-scope region the filter discards upstream* and is missing
most true negatives. It is therefore a **supplement, not a replacement** for the
curated eval set: `eval/relevance_labeled.json` and the regression test
(`test_relevance_heuristic_meets_measured_floor`) stay the source of truth.
`python scripts/eval_relevance.py --include-harvested` folds the harvested labels
into the report (deduped against the curated set, which wins on conflict) for an
exploratory, larger-sample view — but never measure on the harvested set alone.

## Roadmap

The master prompt (`MASTER_PROMPT.md`) defines a nine-step pipeline. The MVP
deliberately implements a subset; the remaining steps are open:

| Step | Status |
| --- | --- |
| 1. Discover and deduplicate sources | Implemented for OpenAlex, Crossref, Semantic Scholar, arXiv, ERIC (`ingest_*.py`, `deduplicate_sources.py`); OECD/WEF/UNESCO lack a public search API and use a manual, opt-in LLM report importer (`ingest_reports.py`, see [docs/report-import.md](docs/report-import.md)) |
| 2. Classify relevance | Keyword/abstract heuristic requiring a topic match (default, fallback, fully deterministic), measured against a labeled set (`eval_relevance.py`); two **optional** opt-in signals — a TF-IDF + LogisticRegression classifier (`train_relevance.py`, `RELEVANCE_CLASSIFIER=model`) and embedding prototype anchors (`build_relevance_anchors.py`, `RELEVANCE_CLASSIFIER=embedding`) — exist but stay disabled because neither beats the heuristic on the held-out comparison |
| 3. Extract structured claims | Implemented conservatively (`extract_claims.py`): a verbatim finding sentence becomes a candidate claim (methodology/structure sentences are skipped); context, age range, outcome, and strength stay human work. An **optional, opt-in** LLM pre-fill (`AI_PROVIDER=anthropic`) only *suggests* those review fields under a non-binding `claim["assist"]` block — off by default, the output is byte-identical to the LLM-free path. Its quality is tracked by `eval_claim_prefill.py` against a labeled golden set; see [OPERATIONS.md](OPERATIONS.md#optional-ai-claim-pre-fill-p1) |
| 4. Link claims to sources and text anchors | Implemented for extracted claims — anchors cite the exact abstract sentence; reviewed claims keep curated anchors |
| 5. Score evidence quality | Implemented (`score_evidence.py`, enforced by validation) |
| 6. Cluster claims into skill candidates | Implemented conservatively (`cluster_claims.py`): topic-vocabulary clustering proposes candidate skills for uncovered topics; existing skills only get review hints |
| 7. Map skill candidates to frameworks | Implemented as curated data (`data/frameworks/`) |
| 8. Create changes as pull requests | Implemented (weekly research workflow) |
| 9. Show reviewed skills in the dashboard | Implemented (`build_site.py`, GitHub Pages) |

## Counter-evidence lane (optional, isolated)

The catalogue holds 146 claims with **exactly one** `contradicts_skill_ids`
entry. `score_evidence.py` can penalise contradiction, but nothing ever looks
for it: the importers search *for* future-skills topics and the extractor
prefers a finding sentence, which in abstracts is overwhelmingly positive. Every
stage leans the same way, so `evidence_score` is a confidence number without a
counter-check.

An **optional, opt-in agent lane** (`agents/counter_evidence.py`) closes that
gap: it searches for studies that report a null result, a failed replication or
a harm for an active skill, and emits them as candidate claims for review. This
is the one task in the project that is genuinely agentic — the query is not
known in advance, and each round reformulates from what the last one returned —
so it uses LangGraph, purely as a state machine.

It is **isolated by contract**, not by convention: its dependency lives in
`requirements-agents.txt` (never installed by CI), `scripts/` may never import
it, every model call routes through `ai_provider` rather than a `langchain-*`
binding, it runs on `workflow_dispatch` only, and it emits candidates only. A
test suite enforces each of these. The rationale, the limits, and the
activation/decommission rule are in
[docs/gegenevidenz-lane.md](docs/gegenevidenz-lane.md); the lane's own rules in
[agents/README.md](agents/README.md).

Optional environment variables:

- `SEMANTIC_SCHOLAR_API_KEY`: raises Semantic Scholar rate limits.
- `OPENALEX_MAILTO`: polite contact email appended to OpenAlex requests.
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`: enable the optional Telegram
  notifications and chat intake (plus optional `TELEGRAM_ALLOWED_CHAT_IDS` and
  `TELEGRAM_GITHUB_TOKEN`); unset, every Telegram step is a no-op. See
  [docs/telegram-integration.md](docs/telegram-integration.md).
- `RELEVANCE_CLASSIFIER`: `heuristic` (default) keeps the deterministic keyword
  filter; `model` opts into the trained classifier (`models/relevance_model.json`);
  `embedding` opts into the embedding anchors (`models/relevance_anchors.json`, also
  needs `EMBEDDING_PROVIDER`). Both fall back to the heuristic if their artifact (or, for
  embeddings, the provider) is missing, and neither currently beats the heuristic, so the
  default is recommended.
- `AI_PROVIDER`: `none` (default) | `anthropic` | `cache`. Enables the optional claim
  pre-fill (step 3). `none` keeps the pipeline LLM-free and byte-identical; `anthropic`
  asks the live model (via `AI_MODEL`, default `claude-opus-4-8`) to *suggest* the manual
  review fields; `cache` replays committed fixtures offline. The `eval_claim_prefill.py`
  CI gate runs in `cache` mode — a **regression** that scores the recorded outputs against
  the golden labels, fully deterministic; live accuracy is measured separately when the
  fixtures are re-recorded (`make eval-prefill-record`, see [OPERATIONS.md](OPERATIONS.md#optional-ai-claim-pre-fill-p1)).
- `EMBEDDING_PROVIDER`: `none` (default) | `local` | `st`. Selects the embedding backend
  used by `ai_provider.embed`, `build_relevance_anchors.py`, and the `embedding` relevance
  mode. `local` is the dependency-free, deterministic hashing embedding (CI default); `st`
  is a real local semantic model (sentence-transformers `all-MiniLM-L6-v2`), a dev/live
  dependency that replays committed vectors from `tests/fixtures/embeddings/` offline and
  only imports the package to embed an uncached text.

## Licensing

Code is MIT licensed. Project-authored data and documentation are CC BY 4.0 licensed.
Do not commit copyrighted full text. Store metadata, abstracts where allowed, links, and
project-authored structured evidence extracts only.
