# Importing API-less report sources (OECD / WEF / UNESCO)

OECD, WEF and UNESCO publish their evidence as prose PDFs with no public
bibliographic search API, so they cannot be harvested like OpenAlex or Crossref.
`scripts/ingest_reports.py` imports them instead via an LLM: it turns a report's
**plaintext** into a candidate source plus candidate finding-claims. Like
everything else in the project, it only ever produces *candidates* — a human
reviews and promotes them; nothing is auto-activated.

This path is **opt-in and manual**. It is never part of the mandatory CI
(`validate.yml`), never scheduled, and is a no-op unless an AI provider is
configured (`AI_PROVIDER`).

## Pipeline

```
PDF  ──(extract_pdf_text.py, optional)──▶  plaintext  ──(ingest_reports.py + LLM)──▶  candidates
```

1. **PDF → plaintext (separate step).** Kept out of the import path so the
   importer stays deterministic and free of a binary PDF dependency. Use the
   optional helper (needs `pypdf`):

   ```bash
   python scripts/extract_pdf_text.py --pdf report.pdf --output report.txt
   ```

   It rejoins hyphenated line breaks, folds ligatures/typography, and squeezes
   blank lines so the plaintext matches cleanly later.

2. **plaintext → candidates.** The importer asks the model (via
   `ai_provider.complete`, strict JSON Schema) to propose the source metadata and
   the report's key findings:

   ```bash
   AI_PROVIDER=anthropic python scripts/ingest_reports.py \
     --report report.txt \
     --url "https://www.oecd.org/.../report.pdf" \
     --publisher OECD --year 2023
   ```

   Multiple reports in one run via a manifest (a JSON array):

   ```json
   [
     {"report": "oecd-2030.txt", "url": "https://oecd.org/...", "publisher": "OECD", "year": 2023},
     {"report": "wef-jobs.txt",  "url": "https://weforum.org/...", "publisher": "WEF", "year": 2023}
   ]
   ```

   ```bash
   AI_PROVIDER=anthropic python scripts/ingest_reports.py --manifest reports.json
   ```

## Guard rails

- **Hallucination guard.** Every proposed claim `statement` must occur as a
  *verbatim passage* in the report plaintext, or it is discarded. Matching
  (`normalize_for_match`) neutralizes PDF typography only — line wraps, curly
  quotes, dashes, ligatures, non-breaking spaces, and hyphenated line breaks —
  so the actual words and their order must still match exactly. A paraphrase, a
  summary or an invention does not occur literally and is dropped. The
  `text_anchor` quotes the exact passage that was found; no anchor, no claim.
- **Candidate-only, low evidence.** Every source and claim is written with
  `status=candidate` and `evidence_strength=low`. The model's richer guesses
  (outcome, context, age range, strength) live only under the non-binding
  `assist` block with provenance; the real review fields keep their placeholders
  until a human fills them in via `promote_candidate.py`.
- **Relevance + dedupe.** Sources pass the same keyword relevance filter
  (`filter_relevant_sources`) and deduplication as every other importer. Across a
  batch run, later reports deduplicate against the earlier ones' appends.
- **No provider, no-op.** With `AI_PROVIDER=none` (the default) the importer reads
  nothing, calls nothing, and writes nothing.

## Automation

`.github/workflows/ingest-reports.yml` runs the importer on
`workflow_dispatch` only. It takes either a single report (`report_path`, `url`,
optional `publisher`/`year`) or a `manifest`, runs with `AI_PROVIDER=anthropic`,
clusters and validates, and writes into the shared `research/candidates`
pull-request branch — the same human-review path as the weekly research
pipeline.
