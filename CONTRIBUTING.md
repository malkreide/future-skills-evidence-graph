# Contributing

This project is intentionally conservative: new skills are welcome, but no
skill can become active without an evidence path.

## Contribution types

- Add a trusted source.
- Correct a claim or text anchor.
- Propose a candidate skill.
- Improve mappings to external frameworks.
- Improve validation, ingestion, or the dashboard.

## Review rules

- Active skills must reference at least one supporting claim.
- Claims must reference at least one source.
- Claims must distinguish evidence from interpretation.
- Candidate records must remain marked as `candidate`.
- Do not add copyrighted full text. Link to sources instead.
- Prefer stable identifiers: DOI, OpenAlex ID, Semantic Scholar ID, ERIC ID,
  ISBN, or official report URL.

## Local validation

```powershell
pip install -r requirements-dev.txt
python scripts/validate_data.py
python -m unittest discover -s tests
```

