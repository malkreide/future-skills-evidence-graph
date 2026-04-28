# Future Skills Evidence Graph

Open, GitHub-first evidence catalog for future skills in AI and education.

Design principle: no skill recommendation without an evidence path.

The project starts as a static, versioned evidence graph. Research automation may create
candidate sources, claims, or skills, but publication of active skills requires human
review through pull requests.

## MVP contents

- Versioned data in `data/`
- JSON Schemas in `schemas/`
- Python standard-library validation and importer scripts in `scripts/`
- Static dashboard in `site/`
- GitHub Actions for validation, candidate research import, and GitHub Pages deploy
- Governance templates for source suggestions, claim corrections, and new skills
- Lehrplan 21 comparison view with radar chart, cycle filter, coverage table, and gap labels

## Local commands

```powershell
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
  `curriculum_area`, `coverage_label`, and a short `evidence_path`.

Each active skill must reference at least one supporting claim. Each claim must reference
at least one source. Candidate records may be incomplete, but must remain visibly marked
as `candidate`.

## Automation

The weekly research workflow runs source importers for curated queries and opens a
candidate pull request when new source metadata is discovered. The workflow does not
publish active skills automatically.

Optional environment variables:

- `SEMANTIC_SCHOLAR_API_KEY`: raises Semantic Scholar rate limits.
- `OPENALEX_MAILTO`: polite contact email appended to OpenAlex requests.

## Licensing

Code is MIT licensed. Project-authored data and documentation are CC BY 4.0 licensed.
Do not commit copyrighted full text. Store metadata, abstracts where allowed, links, and
project-authored structured evidence extracts only.
