# Die zwei Versionen: deterministischer Kern und KI-Erweiterung

Dieses Projekt existiert in zwei dokumentierten Ausbaustufen:

1. **Version 1 — „Vor KI“ / deterministisch:** der vollständig LLM-freie,
   reproduzierbare Kern (MVP). Er ist bis heute der **Default** — wer das Repo
   ohne besondere Umgebungsvariablen ausführt, betreibt exakt diese Version.
2. **Version 2 — KI-Version:** die optionale, abschaltbare KI-Schicht, die nach
   dem archivierten Umsetzungsplan
   [archiv/ki-weiterentwicklung-plan.md](archiv/ki-weiterentwicklung-plan.md)
   (Pakete P0–P4) gebaut wurde. Sie ist vollständig **opt-in**: jede
   KI-Fähigkeit sitzt hinter einem Env-Flag, hat den deterministischen Pfad als
   Fallback und erzeugt ausschließlich `candidate`-Daten.

Wichtig für das Verständnis: Die beiden Versionen sind **keine getrennten
Git-Stände**. Das Projekt vergibt keine Versions-Tags (siehe
[CHANGELOG.md](../CHANGELOG.md)), und der erste Commit der veröffentlichten
Historie (25.06.2026) enthält die KI-Schicht bereits — der Vor-KI-Stand ist
also nicht „auscheckbar“. Er ist stattdessen als **Konfiguration konserviert**:
Version 1 ist das Verhalten aller Skripte mit den Default-Flags, und ein
Regressionsanspruch aus dem Plan hält das fest — mit `AI_PROVIDER=none` ist die
Pipeline **byte-identisch** zum LLM-freien Verhalten.

---

## Version 1 — der deterministische Kern (Default)

Der Kern umfasst die komplette Kette von der Quelle bis zum Dashboard und kommt
ohne LLM, ohne Embeddings und ohne Netzabhängigkeit im Test aus:

- **Import & Dedupe:** die fünf API-Importer (OpenAlex, Crossref, Semantic
  Scholar, arXiv, ERIC; `scripts/ingest_*.py`) plus Web-Suche
  (`ingest_websearch.py`), alles Standard-Library, mit graceful degradation.
- **Relevanzfilter:** transparente Keyword-/Topic-Heuristik
  (`scripts/common.py::decide_relevance`, `RELEVANCE_CLASSIFIER=heuristic`),
  mehrsprachig, mit Audience-/Alters-Gate und Educator-Lane — gemessen gegen
  ein kuratiertes Label-Set (`scripts/eval_relevance.py`).
- **Claim-Extraktion:** wörtliche Befund-Sätze mit exaktem Text-Anker
  (`scripts/extract_claims.py`); Kontext, Altersbereich, Outcome und Stärke
  bleiben Menschen-Arbeit (Platzhalter).
- **Clustering:** Topic-Vokabular-Clustering (`scripts/cluster_claims.py`,
  `CLUSTER_METHOD=vocabulary`).
- **Scoring & Validierung:** reproduzierbares Evidenz-Scoring
  (`scripts/score_evidence.py`), von `scripts/validate_data.py` erzwungen.
- **Review & Veröffentlichung:** `scripts/promote_candidate.py` (Mensch
  entscheidet), statisches Dashboard (`scripts/build_site.py`).

**Garantien dieser Version:** gleiche Eingabe ⇒ gleiche Ausgabe; jede
Entscheidung ist aus Code und Daten erklärbar (Keyword-Spur `topics`); Tests
und CI laufen netzwerkfrei. Diese Garantien gelten unverändert weiter, denn
Version 1 ist der Default — sie ist die *Referenz*, gegen die jede
KI-Komponente gemessen wird.

So betreibt man Version 1 (bewusst redundant — das sind die Defaults):

```
AI_PROVIDER=none
EMBEDDING_PROVIDER=none
RELEVANCE_CLASSIFIER=heuristic
CLUSTER_METHOD=vocabulary
```

Eine Zwischenstufe gehört historisch ebenfalls zu Version 1: das optionale,
**statistische** (nicht-LLM) TF-IDF-+-LogisticRegression-Modell
(`scripts/train_relevance.py`, `RELEVANCE_CLASSIFIER=model`). Es etablierte das
Muster „Alternative hinter Flag, Heuristik als Fallback, Aktivierung nur nach
messbarem Gewinn“, das die KI-Schicht später übernahm — und es ist bis heute
deaktiviert, weil es die Heuristik nicht schlägt (siehe
[relevanz-entscheidung.md](relevanz-entscheidung.md)).

---

## Version 2 — die KI-Erweiterung (opt-in)

Die KI-Schicht wurde nach dem archivierten Plan
[archiv/ki-weiterentwicklung-plan.md](archiv/ki-weiterentwicklung-plan.md)
umgesetzt. Der Plan bleibt als historisches Dokument erhalten — er begründet,
*was* gebaut wurde und *warum*; die folgende Tabelle bildet seine Pakete auf
den heutigen Code ab:

| Paket | Fähigkeit | Umsetzung | Flag(s) | Status |
| --- | --- | --- | --- | --- |
| **P0** | Fundament: Provider-Abstraktion, Fixture-Cache, Provenienz, `assist`-Schema-Feld | `scripts/ai_provider.py`; `assist` in `schemas/claim.schema.json` / `schemas/source.schema.json` | `AI_PROVIDER` (`none`\|`anthropic`\|`cache`), `AI_MODEL`, `ANTHROPIC_API_KEY`; getrennt `EMBEDDING_PROVIDER` (`none`\|`local`\|`st`) | Umgesetzt; Default `none` = Version-1-Verhalten |
| **P1** | LLM-Claim-Pre-Fill: Vorschläge für die manuellen Review-Felder (`context`, `outcome`, `age_range`, `evidence_strength`) | `extract_claims.py` schreibt nur nach `claim["assist"]`; `promote_candidate.py --accept-suggestions`; Qualität via `scripts/eval_claim_prefill.py` gegen Golden-Set | `AI_PROVIDER` | Umgesetzt, opt-in; Review-Gate (Platzhalter) bleibt scharf |
| **P2** | Embedding-Relevanzfilter als Zusatzsignal | `scripts/build_relevance_anchors.py` → `models/relevance_anchors.json`; Modus `embedding` in `common.py::decide_relevance`; fairer Vergleich in `eval_relevance.py` | `RELEVANCE_CLASSIFIER=embedding` + `EMBEDDING_PROVIDER` | Umgesetzt, aber **deaktiviert ausgeliefert** — schlägt die Heuristik im Held-out-Vergleich nicht |
| **P3** | Embedding-basiertes Claim-Clustering | Modus `embedding` in `scripts/cluster_claims.py` | `CLUSTER_METHOD=embedding` + `EMBEDDING_PROVIDER` | Umgesetzt, opt-in; Default bleibt Vokabular-Clustering |
| **P4** | LLM-Import API-loser Berichtsquellen (OECD/WEF/UNESCO) | `scripts/ingest_reports.py` mit Verbatim-Guard (erfundene Zitate werden verworfen); manueller Workflow, Issue-Formular, Drag-&-Drop-Seite — siehe [report-import.md](report-import.md) | `AI_PROVIDER` (ohne Provider: No-op) | Umgesetzt, manuell/opt-in; einziger KI-Pfad im produktiven Betrieb |

### Die Leitplanken (der Vertrag zwischen den Versionen)

Die „nicht verhandelbaren“ Regeln aus Abschnitt 0 des Plans sind der Grund,
warum beide Versionen nebeneinander existieren können, ohne dass die
KI-Version das Vertrauenssignal der deterministischen Version beschädigt:

1. **KI nur im Vorschlags-/Kandidatenpfad** — nie im Score-Pfad
   (`score_evidence.py`), in der Validierung (`validate_data.py`) oder in der
   finalen Freigabe. Das Schema-Feld `assist` trägt nur Vorschläge + Provenienz
   und wird von Validierung und Scoring nicht gelesen.
2. **Opt-in & abschaltbar** — jede Fähigkeit hinter einem Env-Flag, mit dem
   deterministischen Pfad als Fallback.
3. **Determinismus in CI** — Pflicht-CI läuft netzwerkfrei gegen committete
   Fixtures (`tests/fixtures/`); Live-LLM-Aufrufe nur in manuell ausgelösten
   Workflows (z. B. das Neu-Aufzeichnen der Pre-Fill-Baseline,
   `make eval-prefill-record`).
4. **Messen vor Aktivieren** — keine KI-Komponente wird Default, bevor sie auf
   einem Label-Set messbar besser ist. Konsequenz sichtbar bei P2: gebaut,
   gemessen, ehrlich als „schlägt die Heuristik nicht“ dokumentiert — und
   deshalb deaktiviert liegen gelassen.
5. **Provenienz & Erklärbarkeit** — jede maschinelle Ausgabe trägt Modell-ID,
   Prompt-Version und Zeitstempel; die erklärbare Keyword-Spur (`topics`)
   bleibt in jedem Modus erhalten.
6. **Graceful Degradation** — API-Ausfälle brechen den Wochenlauf nicht ab
   (Warnung + Fallback).
7. **Wörtliche Beweise bleiben wörtlich** — `statement` und `text_anchor`
   bleiben in beiden Versionen verbatim aus der Quelle; KI schlägt nur die
   ohnehin manuellen Felder vor.

### So betreibt man Version 2

Alle Flags sind unabhängig kombinierbar; jedes einzelne fällt bei Fehler oder
fehlendem Artefakt auf das Version-1-Verhalten zurück:

```
AI_PROVIDER=anthropic            # Claim-Pre-Fill (P1) + Report-Import (P4); 'cache' = Offline-Replay
AI_MODEL=claude-opus-4-8         # Default; überschreibbar
ANTHROPIC_API_KEY=…              # nur für Live-Aufrufe
EMBEDDING_PROVIDER=local         # oder 'st' (sentence-transformers) für P2/P3
RELEVANCE_CLASSIFIER=embedding   # P2 — derzeit NICHT empfohlen (siehe Status oben)
CLUSTER_METHOD=embedding         # P3
```

Betriebsdetails (Re-Recording der Fixtures, was das CI-Gate wirklich misst)
stehen in [../OPERATIONS.md](../OPERATIONS.md#optional-ai-claim-pre-fill-p1);
die Relevanz-Modi und ihre Messwerte in
[relevanz-entscheidung.md](relevanz-entscheidung.md).

---

## Kurzreferenz: Welche Version läuft gerade?

| Frage | Version 1 (deterministisch) | Version 2 (KI) |
| --- | --- | --- |
| LLM-Aufrufe? | nie | nur Vorschläge (`assist`) und Report-Kandidaten |
| Embeddings? | nie | optional für Relevanz (P2) und Clustering (P3) |
| Reproduzierbar ohne Netz? | ja, vollständig | ja in CI (Fixtures); live nur mit API-Key |
| Kann etwas ohne Menschen `active` werden? | nein | nein — identisches Review-Gate |
| Werden Scores/Validierung von KI beeinflusst? | nein | nein — `assist` wird dort nicht gelesen |
| Wie erkennbar? | Default-Flags | gesetzte `AI_PROVIDER`/`EMBEDDING_PROVIDER`/…-Flags; `assist`-Blöcke mit Provenienz in Kandidaten |

Die Antwort auf die letzten beiden Fragen ist der Kern der ganzen
Versionierung: **Die KI-Version erweitert nur den Vorschlagsweg. Der
Vertrauensweg — Validierung, Scoring, menschliche Freigabe — ist in beiden
Versionen derselbe deterministische Code.**

---

*Verwandte Dokumente:*
[archiv/ki-weiterentwicklung-plan.md](archiv/ki-weiterentwicklung-plan.md) ·
[architektur.md](architektur.md) ·
[relevanz-entscheidung.md](relevanz-entscheidung.md) ·
[governance-und-haltung.md](governance-und-haltung.md) ·
[../CHANGELOG.md](../CHANGELOG.md) · [../OPERATIONS.md](../OPERATIONS.md)
