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

## Manueller Eingang per Issue (Drag & Drop, mobil)

Den `workflow_dispatch`-Pfad unten kann nur bedienen, wer Schreibrechte und
Zugriff auf die Actions-UI hat – am Handy praktisch nicht. Für die alltägliche
manuelle Einreichung gibt es daher ein **Issue-Formular** als Eingang:

```
Issue-Formular  ──(ingest-from-issue.yml)──▶  parse_ingest_issue.py  ──▶  ingest_reports.py  ──▶  Kandidaten-PR
```

1. **Einreichen.** Über *New issue → „Bericht einreichen"*
   (`.github/ISSUE_TEMPLATE/ingest-report.yml`) **einen** von drei Inhalten
   liefern: den **Berichtstext einfügen**, ein **PDF ins Anhang-Feld ziehen** (am
   Handy über das Anhang-Symbol Datei/Foto wählen) oder – wenn die URL direkt auf
   ein PDF zeigt – nichts weiter. Die **URL ist optional** (siehe URL-Auflösung
   unten). Das Formular vergibt automatisch das Label `ingest`.
2. **Auflösen.** `scripts/parse_ingest_issue.py` liest den Issue-Text, ermittelt
   die Plaintext-Quelle in der Reihenfolge *eingefügter Text → angehängtes PDF →
   PDF aus der URL*, lädt ein PDF (Größenlimit 25 MB) herunter und extrahiert es
   mit `extract_pdf_text.py`, und schreibt ein `ingest_reports`-Manifest. Findet
   es keinen Text, schreibt es kein Manifest, sondern einen verständlichen Grund.
3. **Importieren.** `.github/workflows/ingest-from-issue.yml` läuft bei jedem
   `ingest`-Issue, ruft denselben LLM-Importer und denselben Kandidaten-PR-Pfad
   wie unten auf und **kommentiert das Ergebnis (oder den Grund) zurück ins
   Issue**. Es bleibt alles `status=candidate` bis zur Review.

Das Sicherheitsmodell ist identisch zum `workflow_dispatch`-Pfad: derselbe
Verbatim-Guard, dieselbe Relevanz-/Dedupe-Filterung, nichts wird automatisch
aktiv.

### URL-Auflösung (URL-Feld optional)

Damit man beim Datei-Upload nicht zusätzlich die Quellen-URL abtippen muss, ist
das Feld optional. Fehlt es, ermittelt `scripts/resolve_source_url.py` die URL –
zweistufig, passend zur backend-losen Architektur:

- **Im Browser (Dashboard-Dropzone).** Schon beim Ablegen einer Datei sucht
  `site/assets/submit.js` eine URL/DOI **im Dokument** und sonst per **Crossref**
  (keyless, CORS) anhand des Titels und füllt das Feld als Vorschlag vor.
- **Server-seitig (Workflow, Option B).** Kommt das Issue ohne URL an, löst
  `resolve_source_url.py` sie in dieser Reihenfolge auf:
  **Dokument → Crossref → OpenAlex → SearXNG → DuckDuckGo → (optional) Google**.
  Ein Katalog-Treffer (Crossref/OpenAlex) wird nur über einer
  Titel-Ähnlichkeitsschwelle und – falls ein Jahr bekannt ist – innerhalb ±1 Jahr
  übernommen, damit ein unscharfer Titel nie eine falsche URL anhängt. Jeder
  Netz-Schritt scheitert still und fällt zum nächsten durch.

**Web-Suche für graue Literatur (quelloffen, keyless).** Berichte ohne DOI
(OECD/WEF/UNESCO/NFP …) finden die Kataloge oft nicht; dafür gibt es zwei
quelloffene, kostenlose Web-Such-Stufen ohne Secret:

- **DuckDuckGo** über die Open-Source-Bibliothek `ddgs` – läuft sofort, ohne Key
  und ohne Hosting (lazy importiert; fehlt sie, ist die Stufe ein No-op).
- **SearXNG** – eine selbst gehostete, voll quelloffene Meta-Suchmaschine mit
  JSON-API; aktivierbar per `SEARXNG_URL` (zeigt auf deine Instanz), sonst No-op.

Beide Web-Stufen übernehmen einen Treffer nur, wenn dessen Host auf der im Code
gepflegten **Allowlist glaubwürdiger Herausgeber** (`CREDIBLE_DOMAINS`) liegt –
so bleiben die Ergebnisse so quellen-seriös wie früher die 50-Domain-Beschränkung
der Google-Engine. `RESOLVE_OPEN_WEB=1` hebt die Allowlist auf das offene Web an.

**Google** bleibt nur als **optionaler letzter Fallback** (braucht ein Secret-Paar
`GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX`; ohne ist es ein No-op). Findet auch
das nichts, setzt der Workflow die **Issue-URL als Platzhalter** und weist im
Kommentar darauf hin, beim Review die echte Quell-URL nachzutragen – das Schema
verlangt für den Beweispfad eine `url`. Die aufgelöste URL wird im Issue-Kommentar
genannt und bleibt eine *Kandidaten*-Angabe bis zur menschlichen Prüfung.

Den ganzen Pfad (welche Stufe was liefert) zeigt der Diagnose-Workflow
**„Resolve URL check"** (`resolve-url-check.yml`, `workflow_dispatch`): Titel
eingeben → pro Stufe ein Ergebnis, ohne LLM-Aufruf oder Datenänderung.

### Dashboard-Dropzone (Komfort-Oberfläche)

Als hübschere Oberfläche auf genau diesem Eingang gibt es im statischen
Dashboard die Seite **„Bericht einreichen"** (`site/einreichen.html`,
`site/assets/submit.js`), verlinkt aus der Topbar. Sie bietet echtes Drag & Drop
(plus Datei-Auswahl und Texteinfügen, auch mobil) und liest eine abgelegte
**PDF im Browser** mit `pdf.js` (dynamischer, versionsgepinnter CDN-Import) zu
Text. Beim Absenden baut sie keinen API-Aufruf mit Token, sondern öffnet das
**vorausgefüllte Issue-Formular** (`?template=ingest-report.yml&url=…`), das der
Mensch auf GitHub bestätigt – so braucht die öffentliche Pages-Seite **kein
Secret im Browser** und die Anmeldung übernimmt GitHub. Ist der extrahierte Text
zu lang für die Issue-URL, landet er in der Zwischenablage und wird auf der
GitHub-Seite eingefügt; eine reine PDF-URL wird ohnehin erst serverseitig
gelesen. Die Dropzone ist damit nur eine Bedienhilfe – die eigentliche
Verarbeitung und alle Guard Rails bleiben der Issue-/Workflow-Pfad oben.

## Automation

`.github/workflows/ingest-reports.yml` runs the importer on
`workflow_dispatch` only. It takes either a single report (`report_path`, `url`,
optional `publisher`/`year`) or a `manifest`, runs with `AI_PROVIDER=anthropic`,
clusters and validates, and writes into the shared `research/candidates`
pull-request branch — the same human-review path as the weekly research
pipeline.
