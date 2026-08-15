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

- **Der Bericht weist aus, welche Fälle das Methodendokument verrät.** Die
  Anker-Dokumentation lehrt die Rubrik an benannten Grenzfällen — und
  nennt dabei **17 der 50 Eval-Fälle mitsamt ihrer Bewertung**. Wer sie
  gelesen hat, erinnert sich dort, statt zu urteilen. Die Auswertung
  trennt jetzt „genannte Fälle" von „übrigen", erkannt aus dem Dokument
  statt aus einer gepflegten Liste, und weist aus, dass die verbleibenden
  33 unter den 40 liegen, die eine Schwelle tragen können. Die Angabe
  steht auch in der Zusammenfassung, weil das der Teil ist, der zitiert
  wird — eine nackte 0,780 verschweigt, dass ein Drittel der Stichprobe
  auswendig lernbar war.
  Der Katalog-Bogen ist nicht betroffen (0 von 59 im Dokument genannt);
  seine Teilexposition stammt aus gelesenen PR-Beschreibungen und bleibt
  deshalb von Hand in `protocol.notes`.

### Fixed

- **`eval/claim_prefill_second_rater.json` war wieder eine Generation
  alt** — er trug noch den `cannot_determine`-Text, der κ = 0,039 erzeugt
  hat, und keinen `appraisal_method_at_rating`. Neu erzeugt unter 1.2.0.
  Dasselbe Versäumnis wie beim letzten Mal: eine Regeländerung
  durchgezogen, aber nur einen der beiden Bögen neu geschrieben.

### Changed

- **`effect_direction` und `study_design` geschärft (`APPRAISAL_VERSION`
  1.3.0).** Die zwei kleineren Muster derselben Messung, beide mit einer
  Ursache im Regelwerk statt in den Personen.
  `effect_direction` (8× `not_applicable` → `positive`): der Anker sagt
  jetzt, dass die Richtung eines **gemessenen** Effekts gemeint ist, nicht
  der Tonfall des Befunds — „positive attitudes toward the tool"
  beschreibt Einstellungen und misst keine Wirkung. Ausdrücklich benannt
  ist auch die Gegenrichtung, weil sonst der Spiegelbildfehler entstanden
  wäre: berichtet die Quelle Ergebnisse, ist eine Richtung anzugeben, auch
  wenn die Aussage beschreibend klingt. Beim Nachlesen der acht Fälle
  hatte die primäre Bewertung 6× recht, die Zweitbewertung 2× — **diese
  zwei sind in den Daten korrigiert** (`not_applicable` → `positive`). Das
  ist folgenlos für jede Zahl: `effect_direction` erreicht die Herleitung
  nicht, kein `evidence_certainty` und kein Skill-Score bewegt sich
  dadurch (als Test hinterlegt; `score_evidence.py --write` meldet
  „Updated 0 skill score(s)"). Die gemessene Baseline bleibt stehen wie
  gemessen.
  `study_design` (5× `descriptive` → `policy_report`): Ursache ist eine
  Namenskollision im Vokabular — `policy_report`, `systematic_review` und
  `working_paper` stehen in `source_type` **und** in `study_design` und
  bedeuten dort Verschiedenes. Die Rubrik warnt jetzt namentlich vor genau
  diesen drei (Konstante `appraisal.OVERLAPPING_VOCABULARY`, gegen die
  echten Quelldaten geprüft, damit sie nicht veraltet) und sagt, was
  `policy_report` als *Design* heisst: das Dokument berichtet keine eigene
  Methode. Hier ändert sich kein gespeicherter Wert. Prompt
  `claim-appraisal-v3` trägt beide Schärfungen; beide Bögen sind auf
  1.3.0 neu erzeugt.
- **`claim_supported_by_source` geschärft (`APPRAISAL_VERSION` 1.2.0).**
  Der erste gemessene Zweitdurchgang zeigte das Feld bei **κ = 0,039** —
  Zufallsniveau, bei 21 systematischen Abweichungen. Ursache war der
  Ankertext selbst: `cannot_determine` hiess dort „aus dem Vorliegenden
  nicht entscheidbar", was einen knappen Auszug zu einem legitimen Grund
  machte. Der Anker sagt jetzt, dass die Frage **inhaltlich** ist —
  behauptet die Quelle, was die Aussage behauptet? — und schliesst Kürze
  ausdrücklich aus. Begründung: Die Prüfbarkeit des Auszugs beantworten
  bereits `source_verified` (Auffindbarkeit) und `directness` (Passung von
  Population und Outcome); sie hier ein drittes Mal zu bewerten zählt sie
  doppelt und nimmt dem Feld seine eigene Aussage. Die Festlegung ist
  redaktionell und hätte auch andersherum ausfallen können.
  **Kein zulässiger Wert und keine gespeicherte Stufe ändert sich** (57
  `supported`, 2 `partially_supported` wie zuvor); 59 Claims und 50
  Eval-Fälle sind auf 1.2.0 neu gestempelt. Prompt `claim-appraisal-v2`
  trägt dieselbe Schärfung.
- **Der Anker steht jetzt nur noch an einer Stelle.** Vier Orte
  beschrieben das Feld — Modul, Bogen-Rubrik, Extraktor-Prompt,
  Methodendokument. Die Rubrik liest die Definitionen jetzt wie schon die
  Certainty-Anker aus `docs/evidenz-bewertung-anker.md`, statt sie zu
  wiederholen.
- **Gemessene Durchgänge halten fest, welche Regelversion sie gemessen
  haben** (`protocol.appraisal_method_at_rating`, ausgewiesen im Bericht).
  Ohne das läse sich die κ = 0,039 nach der Schärfung als Aussage über den
  neuen Anker — sie beschreibt den alten.

### Added

- **Erste gemessene Inter-Rater-Baseline** (2026-08-14). Ein blinder
  Zweitdurchgang über alle 59 begutachteten Katalog-Claims liegt als
  `eval/catalog_second_rater_completed.json` vor. `evidence_certainty`
  erreicht κ = 0,50 (gewichtet 0,65), die abgelöste `evidence_strength`
  κ = 0,07 — praktisch Zufallsniveau. Die Richtung ist eindeutig, der
  Faktor überzeichnet: die Certainty-Urteile stammen von einer Person in
  einer Sitzung, die Legacy-Werte aus Monaten verschiedener
  Review-Sitzungen.
  Der Befund, der Arbeit verlangt: **`claim_supported_by_source` liegt bei
  κ = 0,039.** 21 Abweichungen, systematisch — bei Rahmenwerken und
  Policy-Berichten steht `partially_supported`/`cannot_determine` gegen
  `supported`. Beide Lesarten sind mit dem Ankertext vereinbar („stützt
  die Quelle das inhaltlich?" gegen „ist das am vorliegenden Auszug
  prüfbar?"), also ein Rubrikdefekt und keine Streuung.
  Festgehalten sind auch die Grenzen: keine Kalibrierrunde vorab, ein
  Teil der Fälle war durch gelesene PR-Beschreibungen nicht streng blind
  (nachgerechnet: diese stimmen *seltener* überein, 5/9 gegen 41/50 — die
  Zahl ist nicht nach oben verzerrt), und ein formal ungültiger Wert
  blieb bewusst unkorrigiert, weil eine Bewertung nachträglich zu ändern
  die Messung wertlos machte.

### Fixed

- **Der Standardbericht meldete weiterhin „keine Baseline vorhanden",
  nachdem eine gemessen und eingecheckt war.** `make agreement` las nur
  den Relevanz-Überlapp und, was per `--second-rater` übergeben wurde.
  Ausgefüllte Bögen mit dem Namensmuster `*_second_rater_completed.json`
  werden jetzt automatisch eingesammelt — leere Vorlagen ausdrücklich
  nicht, die erzeugt `make agreement-worksheet` neu.
- **`protocol.notes` statt Vorbehalt im Bewerternamen.** Die
  Zusammenfassung druckt den Namen einmal pro Feld; ein Absatz darin
  begräbt die Zahlen, die er einordnen soll.

### Added

- **Kalibrierrunde: `--only` und `--explain`.** Vor dem gemessenen
  Durchgang steht eine Runde, in der beide Seiten zehn Fälle bewerten und
  die Abweichungen besprechen. Dafür fehlten zwei Dinge. `--only` schneidet
  einen Bogen auf ausgewählte Fälle zu und setzt
  `protocol.calibration_subset` — die Auswertung weigert sich dann, ihn als
  Baseline zu zählen, egal wie gut die Übereinstimmung ausfällt: die Fälle
  sind danach besprochen und eine spätere Runde über dieselben nicht mehr
  blind. `--explain` zeigt pro Fall beide Antworten **und die Begründung**
  des gespeicherten Urteils. Das ist nötig, weil die primäre Bewertung von
  niemandem stammt, der mit im Raum sitzt; ohne die Begründungskette wäre
  die Runde eine Liste von Differenzen ohne Ansprechpartnerin. Bewusst ein
  eigener Befehl — die gespeicherte Begründung zu sehen ist genau das, was
  vor einem gemessenen Durchgang nicht passieren darf.
- **Anleitung mit zehn benannten Kalibrierfällen** in
  `docs/eval-baseline.md`: sechs Schritte, die zehn Fälle mit der Regel,
  die jeder prüft, und die drei Sorten von Abweichung — mehrdeutige Rubrik
  (Anker schärfen), Lesefehler (nichts tun), echte Urteilsdifferenz
  (notieren, **nicht** wegverhandeln).
  Korrektur am bisherigen Text: Kalibriert wird auf dem **Eval-Set**,
  gemessen auf dem Katalog. Vorher stand dort, auf dem Katalog zu
  kalibrieren — das hätte zehn der 59 Fälle für die Messung verbrannt.

### Fixed

- **`eval/claim_prefill_second_rater.json` war eine Generation alt** — beim
  Nachziehen von `--fields` wurde nur der Katalog-Bogen neu erzeugt. Der
  gespeicherte Prefill-Bogen trug kein `protocol.rated_fields`.
- **Die Meldung zu ausgeschlossenen Paaren nannte den falschen Grund.** Sie
  sagte pauschal „e.g. 'unverifiable'", auch wenn die ausgeschlossenen
  Paare `null` waren. Sie nennt jetzt die tatsächlich betroffenen Werte.

### Added

- **Zweitbewertungs-Bogen für den Katalog** (`--worksheet catalog`,
  `eval/catalog_second_rater.json`). Der vorhandene Bogen misst die 50
  synthetischen Eval-Fälle; seit der Begutachtung treiben aber die 59
  echten Katalog-Claims die Live-Scores, und dafür gab es keinen. Der neue
  Bogen bewertet zusätzlich das alte `evidence_strength` — damit
  beantwortet ein Durchgang, ob die neue Skala reproduzierbarer ist als
  die ersetzte, an derselben Lektüre desselben Claims. Das alte
  `age_range` bleibt aussen vor: vier geprüfte Claims tragen darin die
  Zeichenkette `"Lehrende"`, und wer einen Defekt reproduziert, misst
  nichts.
  Beim Entwurf fiel auf, dass zwei Claim-Felder die Antwort verraten
  hätten: `context` und `text_anchor` sind reviewgeschrieben und nennen
  das Design im Klartext („single-group study", „Systematic review
  synthesis"). Der Bogen zeigt nur Statement, Quellentitel, `source_type`
  und das Quellen-Abstract.
- **`--fields`: einen Durchgang verkleinern, ohne ihn zu verfälschen.**
  Sechs Urteilsfelder × 59 Fälle sind ein halber Arbeitstag. Wer vorher
  zwei Felder ausfüllte und den Rest leer liess, bekam für den Rest eine
  Übereinstimmung von **0,000** ausgewiesen — Arbeit, um die niemand
  gebeten hatte, gezählt als Widerspruch. Der gewählte Feldsatz steht
  jetzt in `protocol.rated_fields`, die Auswertung hält sich daran, die
  Rubrik im Bogen schrumpft mit, und ein unbekannter Feldname wird mit der
  Liste der verfügbaren abgelehnt. Bögen ohne die Angabe werden
  unverändert als Vollumfang gelesen.

### Changed

- **Die 59 geprüften Katalog-Claims sind begutachtet.** Erste produktive
  Anwendung des Bewertungsmodells: `evidence_certainty` steht jetzt an
  jedem geprüften Claim, bibliografische Felder aus dem Quellendatensatz
  abgeschrieben (nie getippt — ein Test prüft jeden DOI, jede URL, jeden
  Titel gegen den gespeicherten Datensatz). Verteilung: 40 `moderate`,
  7 `low`, 12 `very_low`, kein `strong` — keine der 51 Quellen berichtet
  im Abstract eine Bias-Prüfung. **14 von 16 Skill-Scores bewegen sich**
  (−0,21 bis +0,05), ohne Methodenänderung: die Konstanten stehen fest,
  die Urteile haben sich geändert.
- **`claim_type` und ein zweiter Herleitungspfad (`APPRAISAL_VERSION`
  1.1.0).** Bei der Begutachtung zeigte sich, dass nur 14 der 59 Aussagen
  überhaupt eine Wirkung behaupten; der Rest beschreibt, definiert,
  empfiehlt oder berichtet einen Zusammenhang. Die Design-Leiter
  beantwortet aber genau eine Frage — *kann dieses Design eine Ursache
  isolieren?* — und die ist bei „Digitalkompetenz umfasst
  Informationskompetenz" ein Kategorienfehler. Ohne die Unterscheidung
  wären rund vierzig Aussagen `very_low` geworden, und der Grund wäre eine
  nie gestellte Frage gewesen. Für Aussagen ohne Wirkungsbehauptung
  entscheidet jetzt `directness`: Ist die Quelle kompetente Zeugin für
  das, was die Aussage beschreibt? Zwei Studiendesigns ergänzt
  (`narrative_review`, `psychometric_validation`).
- **Begutachtungen tragen ihre Regelversion.** `appraisal_method` ist
  Pflicht, sobald eine Stufe erfasst ist — getrennt von `METHOD_VERSION`,
  das die Arithmetik versioniert. Eine Begutachtung von vor einer
  Regeländerung bleibt so als solche erkennbar.
- **Zwei Datenbefunde aus der Lektüre.** Vier geprüfte Claims tragen die
  Zeichenkette `"Lehrende"` im Feld `age_range` — eine Zielgruppe, kein
  Alter; das string-typisierte Schema hat das nie bemerkt. Und eine als
  `systematic_review` abgelegte Quelle beschreibt im Abstract eine
  Befragung: genau die Verwechslung, gegen die die Trennung von
  `source_type` und `study_design` gebaut wurde.

- **Evidenzbewertung: `evidence_certainty` löst `evidence_strength` ab.** Die
  alte Variable beantwortete mehrere Fragen mit einem Wert — Studiendesign,
  methodische Qualität, Menge, Replikation, Effektrichtung, Effektstärke,
  Generalisierbarkeit, Reviewqualität und Verifizierbarkeit. Das riss
  auseinander, sobald sie nicht in dieselbe Richtung zeigten: Ein sauber
  durchgeführter Nullbefund konnte auf ihr nicht anders als schwach heissen.
  Neu trennt `scripts/appraisal.py` die Dimensionen (`study_design`,
  `comparator`, `outcome_type`, `effect_direction`, `effect_magnitude`,
  `risk_of_bias`, `directness`, `replication`, `consistency`, `heterogeneity`,
  `precision`, `follow_up`, `claim_supported_by_source`, `source_verified`,
  `source_provenance`, …), alle als kontrollierte Enums. `evidence_certainty`
  hat fünf Stufen (`strong`, `moderate`, `low`, `very_low`, `unverifiable`);
  `unverifiable` liegt bewusst nicht auf der Ordinalskala und macht eine Claim
  unbewertbar statt schwach. `derive_certainty()` leitet einen Vorschlag
  GRADE-artig aus dem beschriebenen Design her — mit **benannten** Auf- und
  Abwertungen statt eines Punktesystems — und gibt die Begründungen mit
  zurück; `certainty_conflicts()` prüft die Guardrails, die ein Urteil nicht
  verletzen darf. `source_type` erreicht die Herleitung nachweislich nicht.
  Scoring-Methode **1.2.0**: die Claim-Komponente liest die Begutachtung, wenn
  eine vorliegt, und fällt sonst unverändert auf `evidence_strength` zurück.
  Keine gespeicherte Zahl ändert sich; alle 16 Skills sind neu gestempelt.
- **Alterslogik: gemeldet, abgeleitet und Schulstufe sind jetzt drei Felder.**
  Die Regel „genannte Schulstufe ergibt die übliche Altersspanne" ist entfernt
  — international nicht tragfähig, und das Repository hatte den Beleg bereits
  selbst produziert (Prefill-Prompt v5 versuchte genau das; `age_range`-
  Precision fiel 0,94 → 0,82). Neu: `age_range_explicit` (nur im Text genannte
  Alter), `grade_or_stage`, sowie `age_range_inferred` mit
  **verpflichtender** `age_inference_basis`. Am Goldset machte das sichtbar,
  dass das alte Feld invertiert war: von 43 gesetzten Werten stand **keiner**
  im Abstract, und die beiden Fälle, die tatsächlich Alter nennen, trugen
  `null`.
- **Die 50 Prefill-Fälle sind nach der neuen Rubrik neu begutachtet** und
  ausdrücklich als `synthetic_eval_case` markiert; `validate_data.py` weist
  eine so markierte Claim im Produktivkatalog zurück. Das alte `gold` bleibt
  eingefroren (die CI-Gates messen `_recorded` dagegen), die Begutachtung
  liegt als `gold_appraisal` daneben. 43 von 50 Certainty-Werten weichen vom
  alten Label ab; alle zehn alten `strong` fallen. `eval_agreement.py
  --legacy-drift` zeigt die Kreuztabelle.
- **Interrater-Auswertung: gewichtetes Kappa, Konfusionsmatrix, Zählungen.**
  Für ordinale Felder zusätzlich linear gewichtetes Kappa (nicht quadratisch —
  das behauptete eine Präzision über Fehlergrössen, die hier nichts misst).
  Bewertete und übersprungene Fälle werden ausgewiesen. `null` wird
  **fallweise** statt feldweise gedeutet: ein Fall ohne jeden Eintrag gilt als
  übersprungen, in einem bearbeiteten Fall ist `null` eine Antwort.
- **Zweitbewertungs-Bogen bewertet fünf Urteilsfelder** statt nur der beiden
  alten. Bibliografische Felder bleiben aussen vor — das ist Abschrift, kein
  Urteil. Die Rubrik im Bogen enthielt bis dahin selbst die Anweisung, aus
  einer Schulstufe die übliche Altersspanne einzutragen; sie ist ersetzt.
- **Neuer Prompt `claim-appraisal-v1`.** `claim-prefill-v7` bleibt eingefroren
  und ist als Legacy markiert: sein Schema-Cache hängt am Prompt-Volltext, ein
  geändertes Zeichen invalidiert alle 50 Fixtures und schickt die Offline-Eval
  live. Der Wechsel ist ein Aufnahmelauf, keine Textänderung.

- **Wöchentliche Suche: kuratierte Zusatz-Abfragen und opt-in Katalog-Modus.**
  `config/research_queries.json` enthält jetzt eine breitere kuratierte Auswahl
  (generative KI, Computational Thinking, Medienkompetenz, Fehlinformation/kritisches
  Denken, Datenkompetenz, Lehrkräfte-KI-Kompetenz, allgemeine Zukunftskompetenzen)
  statt nur der einen Ausgangs-Abfrage. Zusätzlich folgt die Suche auf Wunsch dem
  Evidenzgraphen selbst: der neue **opt-in Katalog-Modus** (`derive_catalog_queries`,
  aktivierbar per `include_catalog`-Checkbox im `workflow_dispatch` oder der
  Repo-Variable/Env `RESEARCH_QUERIES_INCLUDE_CATALOG`) erzeugt je **aktivem** Skill
  eine Abfrage — Skill-Name plus zielgruppengerechter Scope-Anker (Lernende vs.
  Lehrkräfte) — und vereint sie mit der Config-Liste. Ein neuer Skill weitet die
  Suche damit automatisch aus; die Menge ist gedeckelt (`CATALOG_QUERY_LIMIT`) und
  protokolliert bei Überschreitung, statt still Abdeckung zu verlieren. Standardmäßig
  aus, damit der Suchraum eine menschliche Entscheidung bleibt.
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

### Fixed

- **Import-Workflows setzen keine bereits gemergten Reviews mehr zurück.** Jeder
  Import-Workflow holte offene Kandidaten vom `research/candidates`-Branch —
  per `git checkout FETCH_HEAD -- data/*/candidates-*.json`, also *dateiweise*.
  Das war falsch: `promote_candidate.py` setzt `status` **in derselben**
  `candidates-*.json` **Datei** (ein promovierter Datensatz wandert nicht in eine
  kuratierte Datei), und der Review-Branch wird bei jedem Lauf von einem älteren
  Stand force-gepusht. Ein zwischenzeitlich gemergtes Review wurde damit
  überschrieben: der Claim kam als `candidate` zurück, fiel aus der Bewertung
  (`score_evidence.py` zählt nur `reviewed`) und die Pipeline starb an einem
  Skill, den der Lauf nie angefasst hatte — konkret
  `skills:skill-digital-media-literacy evidence_score 0.69 does not match
  computed 0.67`. Der Restore **merged** jetzt
  (`scripts/restore_pending_candidates.py`): die ausgecheckte Basis-Fassung eines
  Datensatzes gewinnt immer, nur wirklich ausschließlich auf dem Review-Branch
  vorhandene Kandidaten werden angehängt — die, welche die Importer zur
  Deduplizierung brauchen. Quellen werden zusätzlich über Identity- und
  Titel/Jahr-Schlüssel abgeglichen (dieselben, auf denen `validate_data.py`
  Dubletten ablehnt), damit eine seither zusammengeführte Quelle nicht unter
  altem Namen zurückkehrt.

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
