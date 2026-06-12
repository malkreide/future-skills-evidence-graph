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
python -m unittest discover -s tests
python -m http.server 8000
```

Then open `http://localhost:8000/site/`.

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

The weekly research workflow runs source importers for curated queries and opens a
candidate pull request when new source metadata is discovered. The workflow does not
publish active skills automatically.

Imported candidates pass a keyword relevance filter (`scripts/common.py`): titles
and abstracts are matched against the MVP topic vocabulary and audience terms, the
resulting `relevance_score` (0..1) is stored on each candidate, and topics are
derived from the matched vocabulary instead of being hardcoded. Candidates below
the threshold (default 0.3, tunable per importer via `--min-relevance`) are dropped
before deduplication.

## Roadmap

The master prompt (`MASTER_PROMPT.md`) defines a nine-step pipeline. The MVP
deliberately implements a subset; the remaining steps are open:

| Step | Status |
| --- | --- |
| 1. Discover and deduplicate sources | Implemented (`ingest_*.py`, `deduplicate_sources.py`) |
| 2. Classify relevance | Heuristic keyword/abstract score; no trained classifier yet |
| 3. Extract structured claims | Open — `extract_claim_templates.py` only generates templates for manual completion |
| 4. Link claims to sources and text anchors | Open — anchors are curated by hand |
| 5. Score evidence quality | Implemented (`score_evidence.py`, enforced by validation) |
| 6. Cluster claims into skill candidates | Open — skills are curated by hand |
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
