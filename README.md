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

The threshold is not guessed: `eval/relevance_labeled.json` is a labeled set
(real candidates from the first live run plus clear anchor cases) and
`scripts/eval_relevance.py` reports precision/recall/F1 and sweeps thresholds, so
the filter's behavior is measured. The current heuristic reaches precision 0.64 /
recall 1.00 on that set; `test_relevance_heuristic_meets_measured_floor` guards
against regressions. The keyword heuristic still admits incidental single-keyword
matches; a larger labeled set and a trained classifier are the planned next step.

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
python scripts/promote_candidate.py reject claim-id   # off-scope or unusable
```

Rejecting a candidate records the decision (claims become `rejected`, skills
`deprecated`) so it stays out of clustering and later review passes instead of
lingering as a candidate.

A claim only becomes `reviewed` once its context, age range, and outcome are real
(not the extraction placeholders) and it links at least one existing skill. A skill
only becomes `active` once its definition is real and every supporting and
contradicting claim is already `reviewed`.

## Roadmap

The master prompt (`MASTER_PROMPT.md`) defines a nine-step pipeline. The MVP
deliberately implements a subset; the remaining steps are open:

| Step | Status |
| --- | --- |
| 1. Discover and deduplicate sources | Implemented for OpenAlex, Crossref, Semantic Scholar, arXiv, ERIC (`ingest_*.py`, `deduplicate_sources.py`); OECD/WEF/UNESCO lack a public search API and stay manual |
| 2. Classify relevance | Keyword/abstract heuristic requiring a topic match; measured against a labeled set (`eval_relevance.py`), but no trained classifier yet |
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

## Licensing

Code is MIT licensed. Project-authored data and documentation are CC BY 4.0 licensed.
Do not commit copyrighted full text. Store metadata, abstracts where allowed, links, and
project-authored structured evidence extracts only.
