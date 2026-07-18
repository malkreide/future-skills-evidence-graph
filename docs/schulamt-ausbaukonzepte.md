# Ausbaukonzepte für das Schulamt

*Zwölf konkrete Weiterentwicklungen des Future Skills Evidence Graph – gedacht
aus der Perspektive einer Steuerungsrolle im Schulamt (Beschaffung, Governance,
Weiterbildung, Politik, Beteiligung).*

Dieses Dokument übersetzt zwölf Ideen in **umsetzbare Konzepte**. Jedes Konzept
folgt derselben Struktur:

- **Ziel** – welches Problem im Verwaltungsalltag es löst.
- **Was es ist** – die Funktion in einem Satz.
- **Datenmodell** – die konkrete Schema-/Datei-Änderung. Wichtig: alle vier
  Schemas in `schemas/` haben `additionalProperties: false`. Jedes neue Feld ist
  deshalb eine **bewusste, versionierte Schema-Erweiterung**, kein Freitext-Zusatz –
  das ist ein Feature, kein Hindernis (der Beleg-Pfad bleibt geschlossen).
- **Umsetzung** – die Schritte entlang der bestehenden Architektur.
- **Aufwand** – S (Tage) / M (1–2 Wochen) / L (mehrere Wochen).
- **Haltung & Risiko** – warum es zur eisernen Regel *Kompetenz → Aussage →
  Quelle* passt und was zu beachten ist.

Leitplanke für alle Konzepte: **Der deterministische Kern bleibt Default, KI
bleibt optional und abschaltbar, nichts wird ohne menschliche Freigabe aktiv.**

**Priorisierung (Empfehlung):**

| Priorität | Konzept | Begründung |
| --- | --- | --- |
| 🔴 Jetzt | #1 Beschaffungs-Gate | Unmittelbarer, einzigartiger Verwaltungsnutzen |
| 🔴 Jetzt | #8 Interessenkonflikt-Flag | Kritisches Alleinstellungsmerkmal, kleiner Aufwand |
| 🔴 Jetzt | #2 Lagebericht | GL-taugliches Steuerungsdokument aus vorhandenen Daten |
| 🟠 Bald | #7 Contested Skills, #12 Gremien-Deck, #4 Verbund | Hoher Hebel, moderater Aufwand |
| 🟡 Später | #3, #5, #6, #9, #10, #11 | Wertvoll, aber grösser oder abhängig von Vorarbeit |

---

## #1 – Beschaffungs-Gate für KI- und EdTech-Tools

**Ziel.** Dein grösster Hebel im Schulamt ist Beschaffung. Wenn ein Anbieter
behauptet, sein Tool „fördere kritisches Denken / KI-Kompetenz", brauchst du ein
reproduzierbares, politisch verteidigbares Argument statt Bauchgefühl.

**Was es ist.** Eine Ansicht, die eine Liste von Anbieter-Versprechen gegen den
Evidence-Graph matcht und pro Versprechen zeigt: belegt (mit Beleg-Pfad und
Evidenz-Score), schwach belegt, oder nicht belegt.

**Datenmodell.**
- Keine Schema-Änderung nötig für die Grundfunktion – die Ansicht liest den
  bestehenden `data/index.json`.
- Optional neue Entität `data/assessments/*.json` (eigenes Schema
  `schemas/assessment.schema.json`): ein Beschaffungs-Check als versioniertes,
  auditierbares Dokument (Anbieter, Datum, geprüfte Kompetenzen, Ergebnis,
  entscheidende Person). So wird jede Beschaffungsempfehlung nachvollziehbar.

**Umsetzung.**
1. `site/beschaffung.html` + `site/assets/`-Modul: Eingabefeld für Anbieter-Claims
   (frei getippt oder als Zeilenliste), Matching gegen Skill-Namen/`topics`/
   Definitionen aus `index.json`.
2. Matching zuerst deterministisch (Token-/Topic-Overlap wie in
   `scripts/common.py`); optional später semantisch über die bereits vorhandenen
   Embedding-Anker.
3. Ergebnis: pro Versprechen ein Ampel-Status + Klick auf den Beleg-Pfad
   (Kompetenz → stützende Aussagen → Quellen).
4. „Als Assessment speichern"-Knopf erzeugt den JSON-Datensatz und öffnet – wie
   bei `einreichen.html` – ein vorbefülltes Issue zur Ablage per PR.

**Aufwand.** M.

**Haltung & Risiko.** Macht die Lücke sichtbar, ohne dem Anbieter Unrecht zu tun
(„nicht belegt" ≠ „wirkt nicht", sondern „keine Evidenz im Katalog"). Genau diese
ehrliche Differenzierung ist der Wert für die Verwaltung.

---

## #2 – Automatischer Zukunftskompetenz-Lagebericht

**Ziel.** Die GL braucht ein jährliches, verteidigbares Steuerungsdokument – kein
handgebautes Foliendeck, das beim nächsten Datenstand veraltet ist.

**Was es ist.** Ein per Knopfdruck generierter Bericht (Markdown → PDF/DOCX):
Coverage gegen Lehrplan 21 pro Zyklus/Fachbereich, grösste Evidenzlücken,
bestbelegte Kompetenzen, neue Kandidaten der Periode.

**Datenmodell.** Keine Änderung – aggregiert vorhandene Felder
(`coverage_score`, `cycles`, `curriculum_area`, `coverage_label`,
`evidence_score`, `trend`).

**Umsetzung.**
1. `scripts/build_report.py`: liest `data/index.json` + Lehrplan-21-Mappings,
   rendert eine strukturierte Markdown-Vorlage.
2. Konvertierung nach PDF/DOCX über die vorhandenen Dokument-Werkzeuge
   (bzw. `pandoc` in einem Workflow-Schritt).
3. Neuer Workflow `report.yml` (`workflow_dispatch` + optional quartalsweise),
   der den Bericht als Artefakt/Release-Anhang ablegt.
4. Deutsch als Ausgabesprache (nutzt `name_de`/`definition_de`).

**Aufwand.** S–M.

**Haltung & Risiko.** Jeder Satz im Bericht ist rückverfolgbar – der Bericht
verlinkt in die Live-Ansicht. Achtung: Redaktioneller Rahmentext (Einleitung,
Fazit) muss als solcher gekennzeichnet sein, damit er nicht mit belegten Aussagen
verwechselt wird.

---

## #3 – Umsetzungs-Layer „Was heisst das für den Unterricht?"

**Ziel.** Evidenz allein hilft Lehrpersonen nicht; sie brauchen den Schritt von
der belegten Kompetenz zur didaktischen Handlung.

**Was es ist.** Pro aktivem Skill ein optionales, menschlich freigegebenes Feld
mit zyklus-spezifischen Umsetzungshinweisen – klar getrennt von Belegen.

**Datenmodell.**
- `schemas/skill.schema.json`: neues optionales Feld `practice_hints` (Array von
  `{ cycle, hint, added_by, added_at }`).
- Wichtig: Ein Hinweis ist **kein Claim** und geht **nicht** in den
  `evidence_score` ein (`score_evidence.py` bleibt unverändert). Damit bleibt die
  eiserne Regel intakt: Belege bleiben Belege, Didaktik bleibt Didaktik.

**Umsetzung.**
1. Schema erweitern + `validate_data.py` (Feld ist optional, keine Pflicht).
2. `promote_candidate.py`: Flag `--practice-hint`/`--cycle` zum Setzen bei Review.
3. `build_site.py` + Skill-Detailansicht: Hinweise sichtbar, deutlich als
   „didaktischer Hinweis (redaktionell)" markiert.

**Aufwand.** M.

**Haltung & Risiko.** Nützlichster Praxis-Hebel, aber Verwässerungsgefahr –
darum die strikte visuelle und rechnerische Trennung von Evidenz.

---

## #4 – Interkantonaler/-kommunaler Fork-Verbund

**Ziel.** Aus einem Zürcher Tool einen nationalen Standard machen – und damit
deiner Rolle echten Gestaltungseinfluss geben. Die Lösung ist bereits auf alle
drei Schweizer Lehrpläne (LP21, PER, Piano di studio) viersprachig gemappt.

**Was es ist.** Eine dokumentierte „Instanz übernehmen"-Vorlage plus ein
neutraler Governance-Sitz, sodass andere Schulämter/Kantone denselben Graph
speisen und forken können. Jede Review-Entscheidung anderswo verbessert die
gemeinsame Datenbasis.

**Datenmodell.**
- `data/sources`/`skills`: optionales Feld `instance`/`provenance_org`, um
  Herkunft von Beiträgen zu kennzeichnen (wer hat eingereicht/geprüft).
- Kein Bruch – bestehende Records ohne Feld bleiben gültig.

**Umsetzung.**
1. `docs/instanz-uebernehmen.md`: Fork-, Konfigurations- und Governance-Anleitung
   (die `go-live-checkliste.md` ist die Basis).
2. Beitrags-Rückfluss: PRs aus Fork-Instanzen gegen die Referenz-Instanz;
   `relevance_harvested.json` sammelt Labels über alle Instanzen.
3. Klärung des Governance-Modells (wer moderiert die Referenz-Instanz –
   Fachstelle, interkantonales Gremium?).

**Aufwand.** L (v. a. organisatorisch, weniger technisch).

**Haltung & Risiko.** Grösster strategischer Hebel. Risiko liegt nicht im Code,
sondern in der Governance-Frage „wem gehört der gemeinsame Standard".

---

## #5 – Evidenz-Konsens statt Einzelmeinung (Zwei-Augen-Prinzip)

**Ziel.** Für institutionelle Glaubwürdigkeit gegenüber Politik und Öffentlichkeit
darf ein aktiver Skill nicht von einer einzigen Person abhängen.

**Was es ist.** Ein leichtes Mehr-Augen-Prinzip: Ein Skill wird erst `active`,
wenn zwei unabhängige Reviews vorliegen – über GitHub-PR-Approvals, ohne neue
Infrastruktur.

**Datenmodell.**
- `schemas/skill.schema.json`: optionales `review_approvals` (Array von
  `{ reviewer, date }`), gefüllt aus dem Merge-Prozess.
- Alternativ rein prozessual über GitHub `CODEOWNERS` + Branch Protection
  (Required Approvals ≥ 2) ohne Schema-Änderung.

**Umsetzung.**
1. `CODEOWNERS` für `data/skills/` + Branch-Protection-Regel „2 Approvals".
2. Optional: `promote_candidate.py` prüft, dass ≥ 2 Reviewer im `change_log`
   vermerkt sind, bevor `active` gesetzt wird.
3. Dokumentation in `OPERATIONS.md` (Review-Schritt).

**Aufwand.** S (grösstenteils Konfiguration).

**Haltung & Risiko.** Erhöht Robustheit gegen den Vorwurf „das ist nur eine
Meinung". Risiko: langsamerer Durchsatz – bei kleinem Team ggf. nur für `active`,
nicht für Kandidaten.

---

## #6 – Beteiligungs-Portal für Lehrpersonen und Eltern

**Ziel.** Bildungspolitik partizipativ machen und zugleich die Pipeline mit
Praxis-Quellen speisen. Der Intake existiert schon (Issue-Formular, Telegram) –
er ist nur nicht als Bürgerkanal sichtbar.

**Was es ist.** Eine niederschwellige, sichtbare Einreichseite: „Kennst du eine
Studie oder einen Bericht dazu, was Kinder künftig können müssen? Reich sie ein."

**Datenmodell.** Keine Änderung – nutzt den bestehenden Kandidaten-/Review-Pfad
(`ingest_reports.py`, `parse_ingest_issue.py`). Optional `submitter_role`
(Lehrperson/Eltern/Fachperson) zur Auswertung der Beteiligung.

**Umsetzung.**
1. `einreichen.html` inhaltlich als Beteiligungskanal aufbereiten (Sprache,
   Beispiele, Vertrauen/Datenschutz-Hinweis).
2. Sichtbarkeit: Verlinkung aus Elternbriefen/Schul-Kommunikation.
3. Moderations-Hinweis: Alles bleibt Kandidat bis zur menschlichen Freigabe –
   das schützt vor Missbrauch.

**Aufwand.** S–M.

**Haltung & Risiko.** Passt zum kritisch-pädagogischen Anspruch (Stimmen
einbeziehen statt nur Top-down). Risiko: Moderationslast – die conservative
Kandidaten-Gate deckt das bereits ab.

---

## #7 – „Contested Skills": Widersprüche sichtbar machen

**Ziel.** Intellektuelle Ehrlichkeit als Markenzeichen: nicht falsche Sicherheit
verkaufen, sondern zeigen, wo die Forschung uneins ist (z. B. Handschrift vs.
Tippen, „Coding für alle?").

**Was es ist.** Eine Ansicht, die Kompetenzen mit widersprechenden Aussagen
hervorhebt und den Konflikt gegenüberstellt.

**Datenmodell.** Keine Änderung – nutzt bestehende `contradicting_claim_ids` /
`contradicts_skill_ids` und das `uncertainty`-Feld. Nur die Darstellung ist neu.

**Umsetzung.**
1. `build_site.py`: Kennzahl „hat Widerspruch" pro Skill in den Index.
2. Neue Ansicht/Filter „umstrittene Kompetenzen": stützende vs. widersprechende
   Aussagen nebeneinander, beide mit Beleg-Pfad.
3. `uncertainty`-Text prominent zeigen.

**Aufwand.** S–M.

**Haltung & Risiko.** Ehrlicher als jede Tier-Liste; erfüllt den Anspruch des
`critical-ai-literacy`-Denkens. Kaum Risiko – nutzt vorhandene Daten.

---

## #8 – Interessenkonflikt- und Herkunfts-Flag bei Quellen

**Ziel.** Sichtbar machen, ob eine „Zukunftskompetenz" überproportional von
Anbietern mit Verkaufsinteresse getrieben wird – Ideologiekritik in Code.

**Was es ist.** Quellen tragen eine Finanzierungs-/Herkunftskategorie; die
Skill-Ansicht kann zeigen, auf welcher Art von Evidenz eine Kompetenz ruht.

**Datenmodell.**
- `schemas/source.schema.json`: neues optionales Feld `funding` mit
  kontrollierter Enum, z. B. `public`, `academic`, `foundation`, `industry`,
  `advocacy`, `unknown`. Optional Freitext `funding_note`.
- Aggregation pro Skill zur Bauzeit: Anteil `industry`-finanzierter Belege.

**Umsetzung.**
1. Schema + `validate_data.py` (optional, Default `unknown`).
2. `promote_candidate.py promote-source`: Flag `--funding`.
3. `build_site.py`: Herkunfts-Mix pro Skill; Warnhinweis bei hoher
   Anbieter-Abhängigkeit.
4. Rückwirkend: bestehende Quellen nach und nach klassifizieren (Kandidaten
   bleiben `unknown`).

**Aufwand.** M.

**Haltung & Risiko.** Starkes, verwaltungsspezifisches Differenzierungsmerkmal.
Risiko: Kategorisierung ist teils Ermessenssache – darum konservative Enum +
sichtbares `unknown` statt Scheingenauigkeit.

---

## #9 – Fairness-/Exklusions-Lens auf Kompetenzen

**Ziel.** Verhindern, dass der Katalog unbewusst privilegierte Kinder bevorzugt –
kritische Pädagogik als eingebaute Qualitätssicherung.

**Was es ist.** Pro Kompetenz die Frage „für wen ist sie erreichbar?" – braucht
sie teure Geräte, Elternhaus-Ressourcen, bestimmte Sprache? – plus Filter „zeige
Kompetenzen mit Zugangshürden".

**Datenmodell.**
- `schemas/skill.schema.json`: optionales `equity_note` (Freitext, redaktionell)
  und/oder `access_barriers` (Enum-Array: `device`, `connectivity`,
  `home_support`, `language`, `cost`).
- Redaktionelles Feld, fliesst **nicht** in den Evidenz-Score.

**Umsetzung.**
1. Schema + Review-Flag in `promote_candidate.py`.
2. `build_site.py`: Badge + Filter „Zugangshürden".
3. Redaktionelle Leitlinie in `docs/` (wie wird eine Hürde beurteilt), analog zur
   Lehrplan-21-Coverage-Methodik.

**Aufwand.** M.

**Haltung & Risiko.** Direkter Ausdruck des `critical-pedagogy`-Anspruchs.
Risiko: normative Beurteilung – darum Methodik-Doku und redaktionelle Kennzeichnung.

---

## #10 – „Frag den Graphen": natürlichsprachige Abfrage über verifizierte Daten

**Ziel.** Zugänglichkeit für Nicht-Techniker, ohne die Haltung zu verraten: KI,
die auf auditierbare Fakten *zeigt*, statt sie zu erfinden.

**Was es ist.** Ein optionaler Frage-Modus („Welche gut belegten Kompetenzen für
Zyklus 2 stehen im LP21?"), der Antworten **ausschliesslich** aus dem Graph mit
klickbaren Beleg-Pfaden zusammenstellt – nie halluziniert.

**Datenmodell.** Keine Änderung – reine Retrieval-Schicht über `index.json`.

**Umsetzung.**
1. Stufe 1 (deterministisch, empfohlen als Default): strukturierte Filter-Fragen
   ohne LLM – Dropdowns/Chips, die in Graph-Queries übersetzt werden.
2. Stufe 2 (optional, abschaltbar wie die ganze KI-Schicht über `AI_PROVIDER`):
   LLM formuliert nur die Antwort aus bereits gefilterten Records; jede Aussage
   verlinkt ihre Quelle, keine freien Behauptungen.
3. Guardrail: Antworten dürfen nur Fakten aus dem übergebenen Kontext enthalten;
   ohne Treffer „keine belegte Kompetenz gefunden".

**Aufwand.** M (Stufe 1) / L (Stufe 2).

**Haltung & Risiko.** Muss strikt retrieval-gebunden bleiben, sonst untergräbt es
die eiserne Regel. Stufe 1 zuerst – sie liefert 80 % des Nutzens ohne KI-Risiko.

---

## #11 – Zeitachse & Emerging-Skills-Radar

**Ziel.** Ein datengetriebenes Frühwarn-Signal für die GL statt hype-getriebener
Consulting-Trendreports – jeder Datenpunkt rückverfolgbar.

**Was es ist.** Eine Trend-Ansicht: welche Kompetenz gewinnt an Evidenz-Momentum
(mehr/neuere Quellen), welche stagniert.

**Datenmodell.** Keine Änderung nötig – nutzt `year` der Quellen, `created_at` und
das bestehende `trend`-Enum. Optional: Momentum zur Bauzeit aus dem Quellen-Jahr
je Skill berechnen und als abgeleitetes Feld in den Index schreiben.

**Umsetzung.**
1. `build_site.py`: pro Skill Evidenz über die Zeit (Anzahl/Alter der stützenden
   Quellen) aggregieren.
2. Ansicht „Emerging Radar": Skills nach Momentum sortiert, mit Sparkline.
3. Klarstellung: Momentum ≠ Qualität – der Evidenz-Score bleibt das Trust-Signal.

**Aufwand.** M.

**Haltung & Risiko.** Attraktiv für Gremien. Risiko: „mehr neue Quellen" mit
„wichtiger" zu verwechseln – darum Momentum und Score getrennt ausweisen.

---

## #12 – Ein-Klick-Briefing für Gremien (Deck + Sprechnotiz)

**Ziel.** Mit tagesaktuellem, verteidigbarem Stand in jede Sitzung – der Graph
baut die Folien, nicht du.

**Was es ist.** Aus dem Live-Graphen automatisch ein Kurz-Deck: bestbelegte
Kompetenzen, grösste Lücken, neue Kandidaten der Woche, offene Widersprüche.

**Datenmodell.** Keine Änderung – aggregiert wie #2, nur anderes Ausgabeformat.

**Umsetzung.**
1. `scripts/build_briefing.py`: zieht Kennzahlen aus `index.json`.
2. Rendering als PPTX über das vorhandene Präsentations-Werkzeug (bzw. eine
   schlanke Vorlage); Sprechnotizen aus denselben Daten.
3. `workflow_dispatch`-Workflow legt das Deck als Artefakt ab; optional
   Telegram-Benachrichtigung „Briefing bereit".

**Aufwand.** S–M (teilt viel Logik mit #2 – idealerweise gemeinsam bauen).

**Haltung & Risiko.** Reiner Effizienzgewinn ohne Modell-Risiko. Deck immer mit
Datenstand-Datum und Link in die Live-Ansicht versehen.

---

## Gemeinsame Bausteine (einmal bauen, mehrfach nutzen)

- **Reporting-Kern** (#2, #11, #12): eine Aggregations-Bibliothek über
  `index.json`, aus der Bericht, Radar und Deck schöpfen.
- **Redaktionelle Zusatzfelder** (#3, #8, #9): dasselbe Muster – optionales
  Schema-Feld, das **nie** in den Evidenz-Score fliesst, sichtbar als
  „redaktionell" gekennzeichnet, per `promote_candidate.py`-Flag gesetzt.
- **Neue Ansichten** (#1, #7, #10): alle lesen den bestehenden Index, keine
  Backend-Infrastruktur.

## Nächster Schritt

Empfehlung: mit **#1, #2 und #8** starten – sie liefern den grössten
Verwaltungsnutzen bei überschaubarem Aufwand und teilen den Reporting-/
Zusatzfeld-Baustein. Jedes Konzept lässt sich als GitHub-Issue mit der obigen
Struktur eröffnen und einzeln über einen PR umsetzen.
