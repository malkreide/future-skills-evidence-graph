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

## Sicherheitsmodell

The verbatim guard is the importer's defence against an LLM that invents
evidence. It is deliberately narrow, so it is worth being precise about what it
does and does not buy us. (The adversarial suite in
`tests/test_data_integrity.py::ReportImportTests` exercises every line below.)

**What the guard guarantees**

- **Literal provenance.** Every retained statement occurs *verbatim* in the
  report plaintext. Paraphrases, summaries, reorderings, truncations and outright
  inventions do not occur literally and are dropped — including the hard case
  where a paraphrase reuses *every* word of a real sentence but changes their
  order. Shared vocabulary is not shared provenance.
- **Codepoint-level matching.** After a *closed* normalization (NFKC folding, a
  fixed map of curly quotes / dashes / non-breaking space, and rejoining
  hyphenated line breaks) the comparison is exact on characters. A homoglyph
  forgery — e.g. a Cyrillic `а` standing in for a Latin `a` — looks identical but
  is a different codepoint and is rejected, not silently accepted.
- **Conservative bias.** Normalization only ever neutralizes that closed set of
  PDF artefacts and only joins hyphens across a newline. At worst this rejects a
  genuine quote (e.g. a real compound that happened to wrap); it never invents a
  match. The guard fails safe.

**What the guard does *not* guarantee**

- **Semantic fidelity.** A verbatim quote can still be cherry-picked, quoted out
  of context, or paired with a wrong `outcome` / `context` / `age_range` /
  `evidence_strength` in the non-binding `assist` block. *Verbatim ≠ true,
  representative, or correctly interpreted.* The `text_anchor` proves where a
  sentence came from, not what it means.
- **Source authenticity.** The guard checks the statement against the plaintext
  it is handed; it does not verify that the plaintext is a faithful extraction of
  the real PDF, nor that the `title` / `year` / `url` are correct. Misleading
  plaintext in yields a faithfully-anchored misleading claim out.
- **A trustworthy report.** If the report text itself asserts something false,
  the guard will dutifully anchor it. It constrains the *LLM*, not the *author*.
- **Well-formed quotes.** A match only has to be a contiguous passage; it may be a
  fragment or straddle a sentence boundary.

In short, the guard removes the LLM's freedom to invent wording and reduces it to
*which* true-to-text passages to surface. Judging whether a surfaced passage is
true, fairly framed and correctly interpreted remains a human job — which is why
everything stays `status=candidate` / `evidence_strength=low` until a reviewer
promotes it via `promote_candidate.py`.

## Automation

`.github/workflows/ingest-reports.yml` runs the importer on
`workflow_dispatch` only. It takes either a single report (`report_path`, `url`,
optional `publisher`/`year`) or a `manifest`, runs with `AI_PROVIDER=anthropic`,
clusters and validates, and writes into the shared `research/candidates`
pull-request branch — the same human-review path as the weekly research
pipeline.
