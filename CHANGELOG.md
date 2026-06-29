# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Das Projekt vergibt bislang keine Versions-Tags; alle bisherigen Änderungen laufen
unter `[Unreleased]`. Die jeweils gelebte Architektur und Bedienung stehen in
[README.md](README.md), [docs/architektur.md](docs/architektur.md) und
[OPERATIONS.md](OPERATIONS.md); dieser Changelog hält fest, *wann* welche Fähigkeit
dazugekommen ist. Bestandszahlen (Anzahl Skills/Claims/Quellen) gehören bewusst
nicht hierher — sie werden live aus den Daten ermittelt.

## [Unreleased]

### Added

- **Evidenz-Graph als Fundament.** Versioniertes, datei-basiertes Datenmodell
  (`Source → Claim → Skill → FrameworkMapping`) mit JSON-Schemas (`schemas/`),
  Validierung der Belegketten (`scripts/validate_data.py`) und statischem
  Dashboard (`scripts/build_site.py`, GitHub Pages).
- **Reproduzierbares Evidenz-Scoring.** `scripts/score_evidence.py` berechnet
  `evidence_score` aus Quellenqualität (60 %) und Evidenzstärke (40 %), skaliert
  über einen Breiten-Faktor und Widerspruchs-Abzug; Drift wird von der Validierung
  erzwungen.
- **Wöchentliche Forschungs-Pipeline.** Importer für OpenAlex, Crossref, Semantic
  Scholar, arXiv und ERIC (`scripts/ingest_*.py`) mit graceful degradation,
  Deduplizierung, verbatim Claim-Extraktion (`scripts/extract_claims.py`) und
  Clustering (`scripts/cluster_claims.py`); Ergebnis ist ein
  `research/candidates`-Pull-Request (`research-pipeline.yml`).
- **Mensch-in-der-Schleife-Review.** `scripts/promote_candidate.py`
  (`claim`/`skill`/`reject`/`reject-source`/`promote-source`/`attach-claim`/`reopen`)
  promotet Kandidaten nur ohne maschinelle Platzhalter und auf geprüfter Belegkette.
- **Relevanzfilter mit drei Modi.** Transparente Keyword-/Topic-Heuristik als
  Default plus zwei optionale, abschaltbare Alternativen (trainiertes
  TF-IDF-+-LogReg-Modell, Embedding-Prototyp-Anker, real-semantisch via
  `all-MiniLM-L6-v2`). Faire Held-out-Vergleiche (`scripts/eval_relevance.py`)
  halten die Aktivierungs-/Decommission-Regel ehrlich fest; siehe
  [docs/relevanz-entscheidung.md](docs/relevanz-entscheidung.md).
- **Educator-Lane.** Automatische Erkennung von Quellen über die eigene Kompetenz
  schulischer Lehrpersonen (`is_educator_audience`), getaggt mit
  `audience: "educator"`, gemessen gegen ein eigenes Label-Set
  (`eval/relevance_educator.json`).
- **Optionale LLM-Claim-Vorbefüllung.** `AI_PROVIDER=anthropic` schlägt
  Review-Felder unter einem nicht-bindenden `assist`-Block vor; Default `none`
  bleibt byte-identisch und LLM-frei. Qualität via `scripts/eval_claim_prefill.py`
  (offline-Regression gegen Fixtures).
- **Manueller Bericht-Import (OECD/WEF/UNESCO).** `scripts/ingest_reports.py` mit
  Verbatim-Guard; drei Eingänge (Workflow-Dispatch, Issue-Formular
  `ingest-from-issue.yml`, Drag-&-Drop-Seite `site/einreichen.html`), alle münden
  in denselben Kandidaten-PR. Siehe [docs/report-import.md](docs/report-import.md).
- **Web-Search-Discovery (grauer Literatur).** `scripts/ingest_websearch.py` mit
  keyless DuckDuckGo, optionalem SearXNG und Google-Fallback; Strategie „offene
  Suche, gestufter Trust" über `data/source_domains.json`.
- **URL-Auflösung.** `scripts/resolve_source_url.py` (Dokument → Crossref →
  OpenAlex → SearXNG → DuckDuckGo → optional Google) für Berichte ohne DOI, mit
  Diagnose-Workflow `resolve-url-check.yml`.
- **Allowlist-Audit.** `scripts/audit_domains.py` (`make audit-domains`) leitet
  evidenzbasiert aus dem Review-Ledger ab, welche Domains eine Trust-Stufe
  verdienen. Siehe [docs/allowlist-pflegen.md](docs/allowlist-pflegen.md).
- **Lehrplan-21-Vergleich.** Coverage-Scores, Radar-Chart, Zyklus-Filter und
  Lücken-Labels im Dashboard; Methodik offengelegt in
  [docs/lehrplan21-coverage-methodik.md](docs/lehrplan21-coverage-methodik.md).
- **Relevanz-Label-Harvesting & Recall-Probe.** Review-Entscheidungen erzeugen
  Trainings-Labels (`eval/relevance_harvested.json`); `make recall-probe`
  kontert den Selektions-Bias der Harvest-Labels.
- **Umfassende Dokumentation.** Laien-Erklärung, Governance-/Haltungs-Story,
  Architektur mit Mermaid-Diagrammen, Betriebs-Runbook, Go-Live-Checkliste und
  Pflege-Anleitungen für Skill-Liste und Allowlist.

### Changed

- **Scope-Erweiterung auf Altersgruppe 0–18.** Die ursprüngliche MVP-Zielgruppe
  6–18 wurde um die frühe Kindheit (0–6) erweitert; Dokumentation und
  Code-Kommentare nennen nun durchgängig 0–18.

### Fixed

- Dokumentations-Konsistenz: einheitliche Altersangabe (0–18), Entfernung
  veralteter Bestandszahlen aus der Go-Live-Checkliste (jetzt live ermittelt),
  korrigiertes Skript-Label im Architektur-Diagramm.
