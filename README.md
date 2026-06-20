# Future Skills Evidence Graph

Open, GitHub-first evidence catalog for future skills in AI and education.

Design principle: no skill recommendation without an evidence path.

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

## Data model

- `Source`: bibliographic or policy source metadata.
- `Claim`: structured evidence statement extracted from a source.
- `Skill`: reviewed or candidate future-skill profile.
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

## Automation

See [OPERATIONS.md](OPERATIONS.md) for the operating runbook: the weekly cycle,
the per-cycle verification tests, and the improvement triggers.

The weekly research workflow runs source importers for curated queries across
OpenAlex, Crossref, Semantic Scholar, arXiv, and ERIC, extracts
candidate claims from the new sources' abstracts (`scripts/extract_claims.py`),
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
and the downstream extraction and clustering still complete.

The master prompt also lists OECD, WEF, UNESCO, and EU DigComp as preferred
sources. They are not auto-imported: OECD, WEF, and UNESCO publish reports
without a public bibliographic search API, and DigComp is a single framework
document, not a search source (it already appears in `data/frameworks/`). Those
sources enter through the manual source-suggestion governance template instead.

Imported candidates pass a keyword relevance filter (`scripts/common.py`): titles
and abstracts are matched against the MVP topic vocabulary and audience terms, the
resulting `relevance_score` (0..1) is stored on each candidate, and topics are
derived from the matched vocabulary instead of being hardcoded. A candidate must
match at least one topic — audience terms ("school", "students") alone do not
qualify a source — and score at or above the threshold (default 0.3, tunable per
importer via `--min-relevance`) to survive before deduplication.

A candidate is additionally rejected when it hits a curated **off-scope** term
(`OFF_SCOPE_KEYWORDS`: e.g. `nutrition`, `menstrual`, `sanitation`, `wastewater`,
`salary`, `refinery`, `soil`, plus clinical, workplace/SME and pandemic-logistics
terms) *and* names no future skill in its **title**. In-scope papers name the
skill they study in the title, so this drops off-domain papers that only match a
topic keyword in passing — a pupil-health study touching "complexity", a salary
agreement mentioning "collaboration" — while keeping abstract-only in-scope
candidates that carry no off-scope term. The over-broad `complexity` keyword was
also removed from the systems-thinking vocabulary (`computational thinking` and
`systems thinking` remain), as it matched only incidentally.

The design is data-driven, not guessed: `eval/relevance_labeled.json` is a labeled
set (54 examples: real candidates from the live run and live API queries across the
sources, plus clear anchor cases) and `scripts/eval_relevance.py` reports
precision/recall/F1 and sweeps thresholds, so the filter's behavior is measured.
The off-scope filter raised measured **precision from 0.78 to 1.00 at recall 1.00**
(F1 0.88 → 1.00) at the default threshold, eliminating all six false positives
without dropping any relevant source. `test_relevance_heuristic_meets_measured_floor`
guards against regressions (precision ≥ 0.90, recall ≥ 0.90, with margin below the
measured values).

### Optional trained relevance classifier

The relevance decision is **pluggable**. The default is the keyword heuristic above —
transparent, dependency-free, and the fallback whenever anything goes wrong. As an
*opt-in* alternative, `scripts/train_relevance.py` trains a TF-IDF +
LogisticRegression model (scikit-learn) from the label files with a fixed
`random_state` and exports it to a versioned JSON artifact
(`models/relevance_model.json`). The model is consulted at filter time only when the
env flag `RELEVANCE_CLASSIFIER=model` is set **and** a valid artifact is present;
otherwise the heuristic runs. The topic/keyword hits stay an explainable companion
signal next to the model score: even in model mode, `topics` is still derived from the
vocabulary and the `relevance_score`/`topics` data model is unchanged.

The model is wired into the pipeline only if it **measurably beats** the heuristic on
held-out data, and we report that honestly. `python scripts/eval_relevance.py
--compare-model` runs a fair stratified cross-validation: the heuristic needs no
training and is scored on each test fold directly, while the model is retrained on the
train folds and scored on the held-out fold; both report pooled precision/recall/F1.
On the current 54-example set the heuristic already reaches **F1 1.00** (P 1.00 / R
1.00), and the model lands at **F1 ≈ 0.84** (P 0.94 / R 0.76) — it does **not** beat
the baseline. The data is small and the heuristic is already saturated, so **the
heuristic stays the default and active decision**; the model ships disabled for a
larger, less separable future label set.

**Reproducibility & trade-off.** Training is reproducible from a fixed seed
(`SEED = 42`, seeding both the classifier and the CV splits) and the artifact records
the seed, the scikit-learn version, the input files and label counts, and the
vectorizer configuration. Inference is pure standard library: `common.py` reproduces
scikit-learn's TF-IDF + logistic-regression math from the JSON artifact, so the
importers stay stdlib-only and never import scikit-learn (it is a dev/CI dependency for
*training* and the comparison). `scripts/train_relevance.py` asserts the stdlib scorer
reproduces scikit-learn's `predict_proba` to < 1e-9, and a sklearn-gated test guards
it. The trade-off is deliberate: the heuristic is fully deterministic and
human-auditable (you can read why a source was kept from its matched topics), whereas a
model trades some of that transparency for the *potential* to generalize. The JSON
artifact keeps the model inspectable and diffable, and keeping the keyword topics as a
companion signal preserves an explainable trace even when the model decides.

## Reviewing candidates

Automation only ever produces candidates; promoting one is a human decision made
through `scripts/promote_candidate.py`. The tool applies the reviewer's field
values, refuses to promote while machine-generated placeholders remain, enforces
that an active skill rests only on reviewed claims, recomputes evidence scores, and
re-validates the repository — writing nothing if any check fails.

```powershell
python scripts/promote_candidate.py claim claim-id `
  --context "..." --age-range "6-18" --outcome "..." `
  --evidence-type systematic_review --evidence-strength moderate --supports skill-id
python scripts/promote_candidate.py skill skill-id --definition "..." --name "..."
python scripts/promote_candidate.py reject claim-id          # unusable claim
python scripts/promote_candidate.py reject-source src-id     # source is off-scope
```

Rejecting a candidate records the decision (claims become `rejected`, skills
`deprecated`) so it stays out of clustering and later review passes instead of
lingering as a candidate.

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
| 1. Discover and deduplicate sources | Implemented for OpenAlex, Crossref, Semantic Scholar, arXiv, ERIC (`ingest_*.py`, `deduplicate_sources.py`); OECD/WEF/UNESCO lack a public search API and stay manual |
| 2. Classify relevance | Keyword/abstract heuristic requiring a topic match (default, fallback, fully deterministic), measured against a labeled set (`eval_relevance.py`); an **optional** TF-IDF + LogisticRegression classifier (`train_relevance.py`, opt-in via `RELEVANCE_CLASSIFIER=model`) exists but stays disabled because it does not beat the heuristic on the held-out comparison |
| 3. Extract structured claims | Implemented conservatively (`extract_claims.py`): a verbatim finding sentence becomes a candidate claim (methodology/structure sentences are skipped); context, age range, outcome, and strength stay human work |
| 4. Link claims to sources and text anchors | Implemented for extracted claims — anchors cite the exact abstract sentence; reviewed claims keep curated anchors |
| 5. Score evidence quality | Implemented (`score_evidence.py`, enforced by validation) |
| 6. Cluster claims into skill candidates | Implemented conservatively (`cluster_claims.py`): topic-vocabulary clustering proposes candidate skills for uncovered topics; existing skills only get review hints |
| 7. Map skill candidates to frameworks | Implemented as curated data (`data/frameworks/`) |
| 8. Create changes as pull requests | Implemented (weekly research workflow) |
| 9. Show reviewed skills in the dashboard | Implemented (`build_site.py`, GitHub Pages) |

Optional environment variables:

- `SEMANTIC_SCHOLAR_API_KEY`: raises Semantic Scholar rate limits.
- `OPENALEX_MAILTO`: polite contact email appended to OpenAlex requests.
- `RELEVANCE_CLASSIFIER`: `heuristic` (default) keeps the deterministic keyword
  filter; `model` opts into the trained classifier (`models/relevance_model.json`),
  falling back to the heuristic if the artifact is missing. The model currently does
  not beat the heuristic, so the default is recommended.

## Licensing

Code is MIT licensed. Project-authored data and documentation are CC BY 4.0 licensed.
Do not commit copyrighted full text. Store metadata, abstracts where allowed, links, and
project-authored structured evidence extracts only.
