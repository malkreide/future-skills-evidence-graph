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

### Changed

- **Klarere Seitenstruktur: alle Blöcke als einheitliche Karten.** Filterleiste und
  Kennzahlen „schwebten“ bisher ohne Container und Titel auf dem Hintergrund, während
  andere Abschnitte Karten waren. Jetzt ist jeder Top-Level-Block eine Karte mit
  einheitlichem Kopf (Eyebrow + Überschrift): „Auswahl / Filter & Suche“,
  „Überblick / Bestand im Katalog“ usw. Die Kennzahl-Kacheln heben sich innerhalb der
  Karte über eine dezente Hintergrundfläche ab.

### Added

- **Erklär-Abschnitt oben auf dem Dashboard.** Ein kompaktes Intro erklärt neuen
  Besuchenden direkt, was die Lösung ist, ihr Ziel und ihre Funktionsweise – in drei
  Karten (Die Lösung / Das Ziel / So funktioniert's) plus einer kleinen Evidenzkette
  (Quelle → Aussage → Skill → Lehrplan 21). Formuliert in der Projekt-Stimme aus
  `docs/erklaerung-fuer-laien.md`; theme-fähig und responsiv.

- **Interaktives Netzdiagramm als Zentrum der Seite.** Das Lehrplan-21-Radar ist
  größer und prominenter, die Achsen tragen die vollständig ausgeschriebenen
  Skill-Namen (statt Kürzel). Beim Überfahren wird die betreffende Achse
  hervorgehoben (fette Beschriftung, vergrößerte Datenpunkte) und ein Tooltip zeigt
  Kontext: Future-Evidence-Score, LP21-Abdeckung (/3), Einschätzung, Zyklen und den
  Lehrplan-21-Bezug. Tippen funktioniert auf Touch-Geräten; die Tabelle bleibt die
  barrierefreie Alternative.

### Fixed

- **`coverage_label` wird mit korrektem Umlaut angezeigt.** Das Dashboard zeigt
  „Zukunftslücke“ statt der gespeicherten ASCII-Schreibweise „Zukunftsluecke“ (in
  Tabelle und Radar-Tooltip). Die Datendateien bleiben bewusst ASCII-kodiert (siehe
  `docs/lehrplan21-coverage-methodik.md`); die Korrektur erfolgt rein in der Anzeige,
  Schema, Validierung und Ableitungslogik bleiben unberührt.

### Changed

- **Dashboard-Filter korrigiert.** Der Status „Deprecated“ heißt in der Oberfläche
  jetzt „Veraltet“. Die Perspektive listet „Alle“ zuerst (neuer Standard, konsistent
  mit „Status“ und „Alter“), gefolgt von Lernende und Lehrende. Der „Alter“-Filter
  bietet statt willkürlicher Altersbänder die drei Lehrplan-21-Zyklen (Zyklus 1 = 4–8 J.,
  Zyklus 2 = 8–12 J., Zyklus 3 = 12–15 J.); ein Skill zählt zu einem Zyklus, wenn seine
  Altersspanne die Zyklus-Spanne überlappt.

### Added

- **Dashboard-UX: Cache-Busting, Betriebs-Panel unten & einklappbar, klarere
  Bedienelemente.** Statische Assets (`styles.css`, `app.js`, …) erhalten beim
  Build einen Inhalts-Hash (`?v=…`), damit Browser nach einem Update nicht altes
  CSS/JS mit neuem HTML mischen. Das Betriebs-Panel „Pipeline & Jobs“ steht jetzt
  als eingeklapptes `<details>` am Seitenende und lädt seine GitHub-API-Daten erst
  beim Öffnen (schont das anonyme Rate-Limit). Die Kennzahl-Kachel „Skills“ ist
  nicht länger irreführend als aktiver Filter markiert; Schnellfilter mit Zählwert
  0 (z. B. „Kandidaten“) sind deaktiviert statt in eine leere Liste zu führen. Der
  Dark-Mode-Umschalter nutzt ein eindeutiges SVG-Icon statt eines Emojis.

- **Dashboard-UX: Kennzahl-Schnellfilter und Tastaturnavigation.** Die Kacheln
  „Skills“ und „Kandidaten“ wirken als umschaltbare Status-Schnellfilter
  (`aria-pressed`, teilbar über die URL); die Skill-Liste lässt sich mit den
  Pfeiltasten sowie `Home`/`End` bedienen – Fokus und Auswahl wandern gemeinsam.

- **Dashboard-UX: teilbarer Zustand, Dark Mode, Barrierefreiheit.** Filter- und
  Auswahlzustand werden in die URL geschrieben (teilbare, reload-feste Ansichten);
  neuer „Filter zurücksetzen“-Button mit aktiver Trefferzusammenfassung; Umschalter
  für ein dunkles Design (folgt der Systemeinstellung, merkt die Wahl). Zugänglichkeit
  verbessert durch Skip-Link, sichtbare Fokus-Ringe, `aria-pressed` auf Skill-Karten,
  eine Textbeschreibung des Netzdiagramms (`role="img"`) samt Tabellen-Alternative,
  `prefers-reduced-motion`-Respekt und eine entzerrte (debounced) Suche. Deutsche
  Oberflächentexte auf konsistente Umlaute korrigiert.

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

- **LLM-Prompt-Altersskala auf 0–18 nachgezogen.** Die Extraktions-Prompts in
  `extract_claims.py` und `ingest_reports.py` nannten weiterhin „6-18" und wiesen
  das Modell an, Altersbereiche außerhalb davon auf `null` zu setzen — wodurch
  früh-kindliche Studien (Kindergarten/Vorschule, Lehrplan-21-Zyklus 1) ihren
  Altersbezug verloren. Die Skala lebt jetzt als gemeinsame Konstante
  (`common.AGE_SCALE`), und der Prompt *beschreibt* den tatsächlich berichteten
  Bereich (0–18, frühe Kindheit ausdrücklich eingeschlossen), statt außerhalb
  liegende Studien zu verwerfen; Scope-Filterung bleibt allein Sache des
  Relevanz-Tors. Die Prefill-Fixtures wurden offline aus dem bestehenden
  `_recorded`-Baseline auf den neuen Prompt-Hash umgeschlüsselt; ein
  `make eval-prefill-record` mit `ANTHROPIC_API_KEY` bleibt als empfohlener
  Folgeschritt, um die Live-Baseline unter dem neuen Wortlaut aufzufrischen.
- Dokumentations-Konsistenz: einheitliche Altersangabe (0–18), Entfernung
  veralteter Bestandszahlen aus der Go-Live-Checkliste (jetzt live ermittelt),
  korrigiertes Skript-Label im Architektur-Diagramm.
