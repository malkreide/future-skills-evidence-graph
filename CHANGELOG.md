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

- **KI-Assist: `outcome`/`context` werden semantisch gemessen statt lexikalisch.**
  Die beiden Freitext-Felder des optionalen Claim-Pre-Fills wurden per
  Jaccard-Token-Overlap gegen den Gold-Satz gescort — was die falsche Sache misst:
  das Modell formuliert denselben Befund mit anderen Worten, und eine treue
  Paraphrase zählte als Fehler. Gemessen lag `outcome` dadurch bei P 0.11, ein
  Artefakt des Maßstabs, kein Modellfehler. Beide Felder werden jetzt per
  Cosine-Similarity über die projekteigenen, fixture-gestützten Embeddings
  gescort (`outcome` 0.11 → **0.85**, `context` 0.44 → **0.98**, Disagreements
  80 → 19). Der Schwellwert 0.60 ist gegen eine cross-paarige Negativkontrolle
  kalibriert, nicht geraten. Der alte lexikalische Wert steht in jedem Report
  daneben, damit sichtbar bleibt, ob sich das Modell verbessert hat oder nur der
  Maßstab; ein CI-Lauf bleibt reiner Cache-Zugriff und damit offline.

- **KI-Assist: `outcome`/`context` sind jetzt bedingt gegated.** Floors 0.75 bzw.
  0.85 in `validate.yml`. Fehlen die Embedding-Fixtures, überspringen sich diese
  beiden Gates mit einer `SKIPPED`-Zeile, statt den Lauf rot zu machen — unter
  dem lexikalischen Fallback wäre ein semantischer Floor sonst ein Fehlschlag
  wegen einer fehlenden Datei statt wegen einer Verschlechterung. Inklusive
  Decommission-Regel nach dem Muster von `RELEVANCE_CLASSIFIER`.

- **Ein Evidenzstärke-Vokabular.** Die LLM-Prompts fragten `evidence_strength`
  als `{low, moderate, high}` ab, während `schemas/claim.schema.json` und
  `promote_candidate.py` `{low, moderate, strong}` kennen; ein Mapping
  überbrückte die Lücke beim Übernehmen, aber der `assist`-Block zeigte einem
  Reviewer weiterhin einen Wert, den das Datenmodell nicht kennt. Beide Prompts
  rendern das Vokabular jetzt aus `common.EVIDENCE_STRENGTH_VALUES` (wie
  `AGE_SCALE`), ein Test verankert die Gleichheit mit dem Schema-Enum. Prompt
  `claim-prefill-v7` erlaubt zusätzlich Abstinenz bei `evidence_strength` — auf
  dem Gold-Satz schlug das Modell 50/50 einen Wert vor, sagte also nie „nicht
  erkennbar". Die v7-Fixtures sind migriert, nicht neu gemessen; ein
  Live-Re-Record steht aus und ist in `OPERATIONS.md` als offener Punkt vermerkt.

### Added

- **Gegenevidenz-Lane: eine optionale, isolierte Agenten-Suche nach Widerspruch.**
  Der Katalog hält 146 Claims mit **genau einem** `contradicts_skill_ids`-Eintrag.
  `score_evidence.py` kann Widerspruch bestrafen, aber nichts sucht ihn: die
  Importer suchen *nach* Future-Skills-Themen, der Extraktor bevorzugt einen
  Befundsatz, und Befundsätze in Abstracts sind überwiegend positiv. Jede Stufe
  neigt in dieselbe Richtung — `evidence_score` war damit ein Konfidenzmaß ohne
  Gegenprobe. `agents/counter_evidence.py` sucht gezielt nach Null-Resultaten,
  gescheiterten Replikationen und Schäden und legt sie als Kandidaten-Claims zur
  Review vor.

  Dies ist die eine Aufgabe im Projekt, die wirklich agentisch ist — die Query
  steht nicht vorab fest, und jede Runde formuliert aus dem Ergebnis der
  vorherigen um. Deshalb LangGraph, und zwar **ausschliesslich als
  Zustandsmaschine**: jeder Modellaufruf läuft durch `ai_provider`, nicht durch
  ein `langchain-*`-Binding. Damit bleibt der Fixture-Replay erhalten, die Lane
  erbt alle Provider aus dem Kern, und kein einziges Integrationspaket wird
  gebraucht.

  **Isoliert per Vertrag, nicht per Konvention:** Abhängigkeit in
  `requirements-agents.txt` (von CI nie installiert), `scripts/` darf `agents/`
  nie importieren, nur `workflow_dispatch`, ausschliesslich Kandidaten-Output,
  und ein Claim entsteht nur, wenn sein Zitat **wörtlich** im Abstract steht.
  `tests/test_agent_isolation.py` erzwingt jede dieser Regeln und läuft in der
  normalen Suite — die kein LangGraph installiert, was der Beweis ist, dass der
  Kern es nicht braucht. Harte Grenzen (`MAX_ROUNDS`, `MAX_QUERIES`) stehen als
  Code-Konstanten da, nicht als Prompt-Bitte. Begründung, Grenzen und
  Aktivierungs-/Decommission-Regel in
  [docs/gegenevidenz-lane.md](docs/gegenevidenz-lane.md).

  Die Lane ist **standardmässig aus** und in keinen automatischen Workflow
  eingebunden. Aktivierung setzt eine gemessene Präzision ≥ 0.5 über drei
  manuelle Läufe voraus.

- **KI-Assist: Skill-Zuordnung als eigener, nicht-bindender Vorschlag.** Ein
  Claim wird erst `reviewed`, wenn er mindestens einen Skill verlinkt — der
  letzte rein manuelle Handgriff der Review-Schleife. Ein zweiter, unabhängig
  versionierter Aufruf (`skill-link-v1`) schlägt `supports_skill_ids` /
  `contradicts_skill_ids` vor und legt sie unter `claim["assist"]["skill_links"]`
  ab. Nur aktive Skills werden angeboten, unbekannte IDs werden verworfen und
  gewarnt, der Vorschlag bleibt rein beratend (`supports_skill_ids` bleibt leer,
  die Promotion braucht weiterhin ein explizites `--supports`), und bei
  `AI_PROVIDER=none` wird nicht einmal der Katalog gelesen. Der Gold-Satz
  `eval/skill_link_labeled.json` ist **vorgeschlagen, nicht kuratiert**:
  `eval_skill_links.py` verweigert jedes Gate, solange sein `_status` auf
  `proposed-unreviewed` steht. Das Feature ist damit vollständig, aber ungemessen
  und in keinen Workflow verdrahtet.

- **Telegram: `/dashboard` öffnet im Privat-Chat als Mini App.** Der Button in
  der `/dashboard`-Antwort ist im Privat-Chat jetzt ein `web_app`-Button —
  das Dashboard öffnet sich bildschirmfüllend in Telegram statt im
  In-App-Browser. In Gruppen bleibt es beim normalen Link-Button, weil die
  Bot API Web-App-Buttons nur in Privat-Chats akzeptiert (eine
  Gruppen-Nachricht mit `web_app`-Button würde komplett abgelehnt). Die Doku
  beschreibt zusätzlich den codefreien Weg, das Dashboard als dauerhaften
  Menü-Button des Bots zu hinterlegen (BotFather → Menu Button).

- **Telegram: Echtzeit-Modus per Webhook-Relay + dichterer Poll-Takt.** Der
  Intake-Workflow beherrscht jetzt zwei Zustellwege bei identischer Logik:
  Pull wie bisher (Poll-Takt von 30 auf **10 Minuten** verkürzt — im
  öffentlichen Repo kostenlos), und optional **Push**: ein minimaler,
  zustandsloser Cloudflare Worker (`relay/telegram-webhook-relay.js`) nimmt
  Telegrams Webhook entgegen, prüft das Webhook-Secret und löst nur den
  Intake-Workflow per `workflow_dispatch` aus, das Update als Input — Antworten
  kommen damit in ~15–40 s statt Minuten, während Allowlist, Befehle und
  Issue-Erstellung unverändert in GitHub Actions laufen. Bei gesetztem Webhook
  beantwortet Telegram `getUpdates` mit 409; der Poll erkennt das und
  überspringt sich, beide Trigger bleiben also gefahrlos aktiv. Push-Läufe
  gruppieren ihre Concurrency per `update_id`, damit GitHubs
  Ein-wartender-Lauf-Regel keine Nachricht verwirft; scheitert der Dispatch,
  antwortet das Relay mit 502 und Telegram stellt erneut zu. Rückbau jederzeit
  per `deleteWebhook`. Einrichtung:
  [docs/telegram-integration.md](docs/telegram-integration.md).

- **Telegram: Dashboard-Abfragen als Chat-Befehle.** Der Intake-Bot beantwortet
  jetzt Lese-Befehle aus denselben versionierten Daten, aus denen das Dashboard
  gebaut wird: `/skills` (Top-Skills nach Evidenz-Score, mit Status und
  Claim-Anzahl), `/skill <suchbegriff>` (ein Skill im Detail: Definition,
  Evidenz, Framework-Zuordnungen inkl. LP21-Abdeckung; exakter Name gewinnt,
  sonst Treffer-Liste zum Eingrenzen), `/lp21` (durchschnittliche
  Lehrplan-21-Abdeckung und alle Skills aufsteigend — größte Lücken zuerst)
  und `/dashboard` (Link-Button zum interaktiven Dashboard; URL aus dem
  Repository abgeleitet, per `DASHBOARD_URL`-Variable übersteuerbar). Alles
  rein lesend; Antworten kommen im Polling-Takt, die interaktive Echtzeit-Sicht
  bleibt bewusst das Dashboard selbst. Lange Antworten werden am
  Telegram-Limit gekürzt statt verworfen.

- **Versions-Dokumentation: deterministischer Kern vs. KI-Erweiterung.** Neue
  Seite [docs/versionen.md](docs/versionen.md) hält die zwei Ausbaustufen des
  Projekts fest: Version 1, der vollständig LLM-freie, deterministische Kern —
  bis heute der Default und nicht als Git-Stand, sondern als Konfiguration
  konserviert (`AI_PROVIDER=none` ⇒ byte-identisches Verhalten) — und
  Version 2, die opt-in KI-Schicht. Der archivierte Umsetzungsplan
  ([docs/archiv/ki-weiterentwicklung-plan.md](docs/archiv/ki-weiterentwicklung-plan.md))
  ist integriert: seine Pakete P0–P4 sind auf den heutigen Code, die Flags und
  den Aktivierungsstatus abgebildet, seine Leitplanken als „Vertrag zwischen
  den Versionen“ zusammengefasst. Verlinkt aus README und dem Archiv-Dokument.

- **Optionale Telegram-Integration: Benachrichtigungen + Einreichen per Chat.**
  Das Projekt lässt sich jetzt vom Messenger aus begleiten, ohne die
  GitHub-first-Architektur zu verlassen (serverlos, kein Webhook): Workflows
  melden das Ergebnis der wöchentlichen Recherche (inkl. Kandidaten-PR-Link),
  jeden Bericht-Import, jedes neu eröffnete Issue und Pipeline-Fehlschläge in
  den konfigurierten Chat (`scripts/telegram_notify.py` — Best-Effort, bricht
  nie einen Workflow ab). Umgekehrt pollt `telegram-intake.yml` alle 30 Minuten
  die Bot API und übersetzt Nachrichten aus allowgelisteten Chats — direkter
  PDF-Link, angehängtes PDF (im Runner extrahiert, kein Telegram-Token im
  Issue) oder eingefügter Berichtstext — in dasselbe „Bericht
  einreichen“-Issue wie das Formular; ein Import-Pfad, ein Review-Pfad, nur
  Kandidaten. Dazu `/status` (Bestand im Katalog) und `/hilfe`. Ohne die
  `TELEGRAM_*`-Secrets ist alles ein No-op. Sicherheitsmodell (Chat-Allowlist
  als Budget-Kontrolle, `ingest-approved` als übertragene
  Vertrauensentscheidung) und Einrichtung:
  [docs/telegram-integration.md](docs/telegram-integration.md).

### Changed

- **Wöchentliche Suchabfrage ist jetzt konfigurierbar statt fest verdrahtet.**
  Bisher stand die eine Suchabfrage (`"AI literacy education children future
  skills"`) hart in `research-pipeline.yml`, für jeden der fünf Importer wiederholt
  — den Suchraum zu ändern hieß, die CI-Datei zu bearbeiten. Die Abfragen liegen
  jetzt in der versionierten, editierbaren `config/research_queries.json` (JSON-Liste
  von Strings). Jeder Importer akzeptiert `--query` mehrfach und läuft ohne Angabe
  über alle konfigurierten Abfragen (dedupliziert über Abfragen hinweg), aufgelöst
  von `load_research_queries` mit der Reihenfolge **`RESEARCH_QUERIES`-Env →
  Config-Datei → eingebauter Standard**. Ein manueller `workflow_dispatch`-Lauf kann
  die Menge über den neuen `queries`-Input (zeilen- oder kommagetrennt) für einen
  Lauf überschreiben. Der Suchraum lässt sich damit erweitern oder umlenken, ohne
  Code zu ändern; der Pipeline geht nie die Abfrage aus.
- **Dublettenerkennung erkennt jetzt auch Titelvarianten.** Bisher wurden Quellen
  nur über eine starke Kennung (DOI/OpenAlex/Semantic-Scholar/ERIC-ID/URL) oder
  über normalisierten Titel+Jahr als Dublette erkannt — Preprint und publizierte
  Fassung mit unterschiedlicher DOI und leicht geändertem Titel rutschten doppelt
  durch. Ergänzt wurde ein deterministischer **Titel-Ähnlichkeits-Abgleich**
  (`is_title_duplicate`, `difflib`, ohne neue Abhängigkeit): Titel ab einer hohen
  Ähnlichkeitsschwelle innerhalb eines Ein-Jahres-Fensters gelten als dieselbe
  Arbeit. Der Abgleich läuft in `filter_new_sources` und beim Anhängen
  (`append_candidate_sources`), greift also in jedem Importer (wöchentlich, Web,
  Bericht-Import). Das Audit `deduplicate_sources.py` meldet solche Beinah-Dubletten
  zusätzlich zur Prüfung. Schwelle bewusst hoch, Jahresfenster schmal, damit echte,
  nur ähnlich betitelte Arbeiten nicht fälschlich zusammengeführt werden.

### Fixed

- **Dark Mode: Skill-Karten nicht mehr weiß.** Der Kartenhintergrund war fest auf
  ein Hellweiß verdrahtet (`#fbfcfb`) und folgte dem Theme nicht; er nutzt jetzt
  `var(--surface-2)`. Zusätzlich nutzt der Gegenbeleg-Rand jetzt `var(--red)` statt
  einer festen Farbe. Ein CSS-Audit bestätigt: keine weiteren hartkodierten Farben
  außerhalb der Theme-Definitionen – der gesamte Inhalt folgt jetzt dem Modus.

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
