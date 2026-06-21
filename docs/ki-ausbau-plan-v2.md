# Ausbauplan v2: Schwächen beheben & Weiterentwicklung

*Folgeplan zu [ki-weiterentwicklung-plan.md](ki-weiterentwicklung-plan.md), nach
der Umsetzung von P0–P4. Wieder paketweise, mit fertigen Prompts.*

Leitplanken aus v1 gelten unverändert (KI nur im Kandidatenpfad, opt-in,
deterministisches Offline-CI, „messen vor aktivieren", Provenienz, Heuristik als
Fallback). Dieser Plan adressiert die in der Repo-Analyse gefundenen Schwächen.

## Übersicht

| # | Paket | Behebt | Abhängig |
| - | --- | --- | --- |
| **A0** | Doku-Konzision & Komplexitäts-Disziplin | lange/redundante README+OPERATIONS, 3 Relevanzmodi | – |
| **A1** | Echtes Semantik-Embedding + härtere Eval-Labels | Hashing-Platzhalter, nicht belastbare P2/P3-Messung | – |
| **A2** | Inhaltliche Tiefe (Vorzeige-Strang) | dünner Korpus (10 Skills / 19 Claims) | – |
| **A3** | Thought-Leadership-Layer (deutsch) | Governance-Story nur implizit, EN-lastig | A2 |
| **A4** | P1-Eval härten | „Regressionstest" als „Live-Precision" überverkauft | – |
| **A5** | P4-Halluzinationsschutz adversarial belegen | Sicherheitsbehauptung nur an Happy-Path-Fixtures | – |

Reihenfolge: **A0 → A1 → A4 → A5** (Hygiene/Belastbarkeit), parallel **A2 → A3**
(Inhalt/Narrativ). Jedes Paket = ein PR mit demselben Lebenszyklus wie in v1.

---

## A0 — Doku-Konzision & Komplexitäts-Disziplin

**Ziel.** Prosa straffen, Redundanz zwischen README (325 Z.) und OPERATIONS
(212 Z.) entfernen, und die drei Relevanzmodi auf eine klare Linie bringen.

**Umfang.**
- README auf **Einstieg + Verweise** reduzieren: die ausführlichen Abschnitte
  „Optional trained relevance classifier" und „Optional embedding relevance
  anchors" in **eine** Datei `docs/relevanz-entscheidung.md` auslagern; README
  behält je 2–3 Sätze + Link.
- Überschneidung README↔OPERATIONS auflösen: Betriebsabläufe leben nur in
  OPERATIONS, Konzepte nur in README; jede Wiederholung wird durch einen Link
  ersetzt (Single Source of Truth).
- **Komplexitäts-Entscheid dokumentieren:** ein kurzer Abschnitt „Welcher
  Relevanzmodus — und warum keiner aktiv ist" mit der Decommission-/Aktivierungs-
  Regel (wann ein Modus Default werden darf, wann er entfernt wird).
- Keine Code-Änderung; nur Doku + Links. Mermaid-Diagramme bleiben.

**Akzeptanz.**
- README < ~220 Zeilen; keine Messzahl/Erklärung steht doppelt in README *und*
  OPERATIONS (stichprobenartig prüfbar).
- Alle internen Links auflösbar (kein toter Verweis).
- `python scripts/build_site.py` und Tests bleiben grün (Doku-only).

#### Umsetzungs-Prompt A0

```
Kontext: Repo future-skills-evidence-graph. Lies README.md, OPERATIONS.md und
docs/architektur.md. Die KI-Analyse ergab: README+OPERATIONS sind lang und teils
redundant; es gibt drei Relevanzmodi (heuristic/model/embedding), zwei davon
deaktiviert.

Aufgabe: Doku straffen, ohne Inhalt zu verlieren. KEINE Code-Aenderung.

1. Lagere die README-Abschnitte "Optional trained relevance classifier" und
   "Optional embedding relevance anchors" nach docs/relevanz-entscheidung.md aus.
   In README bleibt je ein 2-3-Satz-Absatz + Link.
2. Entferne Redundanz zwischen README und OPERATIONS: Konzepte nur in README,
   Betrieb nur in OPERATIONS; ersetze Wiederholungen durch Links (Single Source
   of Truth). Erhalte alle Messzahlen genau EINMAL.
3. Ergaenze in docs/relevanz-entscheidung.md einen Abschnitt "Welcher Modus -
   und warum keiner aktiv ist" mit der Aktivierungs-/Decommission-Regel.
4. Pruefe alle internen Links. Ziel: README < ~220 Zeilen.

Constraints: Inhalt/Genauigkeit unveraendert, nur Form. Lauf
`python -m unittest discover -s tests` und `python scripts/build_site.py` bis gruen.
```

---

## A1 — Echtes Semantik-Embedding + härtere Eval-Labels

**Ziel.** Das `_local_embedding`-Hashing durch ein echtes, lokales semantisches
Embedding ersetzen — und die Relevanz-Labels um die harten Restfälle erweitern,
damit der Vergleich überhaupt aussagekräftig wird (das aktuelle Label-Set ist bei
Heuristik-F1 1.00 gesättigt, ein Sieg ist dort gar nicht zeigbar).

**Umfang.**
- Neuer `EMBEDDING_PROVIDER=st` (sentence-transformers, lokal, z. B.
  `all-MiniLM-L6-v2`) in `ai_provider.embed`; `local` (Hashing) bleibt als
  dependency-freier CI-Default erhalten. `sentence-transformers` als reine
  Dev-/Live-Abhängigkeit dokumentieren (Laufzeit-Importpfad bleibt stdlib bei
  `none`/`local`).
- **Reproduzierbarkeit:** Modellname + Version im Anker-Artefakt-Provenienz
  mitschreiben; Embeddings werden im Fixture-Cache abgelegt, damit CI weiter
  offline läuft.
- **Härtere Labels:** `eval/relevance_labeled.json` um die in OPERATIONS
  getrackten Fehlklassen erweitern (Lehrer-Tool-Nutzung, Katastrophen-/
  Gesundheits-Paper mit Schul-Wort), sodass die Heuristik nicht mehr 1.00 ist.
- Anker mit `st` neu bauen, `eval_relevance.py --compare-embedding` erneut laufen,
  **ehrliches VERDICT** dokumentieren. Aktivierung nur bei messbarem Gewinn.

**Akzeptanz.**
- `EMBEDDING_PROVIDER=local` (CI) verhält sich unverändert; `st` ist opt-in.
- Erweitertes Label-Set; Heuristik-F1 dort < 1.00 (Vergleich wird aussagekräftig).
- Neues VERDICT in `docs/relevanz-entscheidung.md`; Default bleibt heuristik,
  außer `st` schlägt sie messbar.
- `test_relevance_heuristic_meets_measured_floor` an die neuen Labels angepasst
  (Floor mit Marge), bleibt grün.

#### Umsetzungs-Prompt A1

```
Kontext: Baut auf P0/P2. Lies scripts/ai_provider.py (_local_embedding, embed),
scripts/build_relevance_anchors.py, scripts/eval_relevance.py (compare-embedding),
common.py (embedding_relevance_decision) und OPERATIONS.md (Fehlklassen).

Aufgabe: Echtes lokales Semantik-Embedding ergaenzen und den Embedding-Pfad fair
messbar machen. Heuristik bleibt Default.

1. Erweitere embed() um EMBEDDING_PROVIDER='st': lokales sentence-transformers
   Modell (all-MiniLM-L6-v2), lazy import. 'local' (Hashing) bleibt CI-Default.
   sentence-transformers in requirements-dev.txt als reine Dev-/Live-Dependency
   mit Kommentar (Laufzeitpfad stdlib bei none/local).
2. Provenienz im Anker-Artefakt um modell_name + version erweitern; Embeddings
   im Fixture-Cache ablegen, damit CI offline bleibt.
3. Erweitere eval/relevance_labeled.json um die in OPERATIONS getrackten harten
   Fehlklassen (teacher tool-use, disaster/health mit Schul-Wort), sauber gelabelt.
4. Baue Anker mit EMBEDDING_PROVIDER=st neu, lauf --compare-embedding, schreibe
   das ehrliche VERDICT nach docs/relevanz-entscheidung.md. Aktivierung nur bei
   messbarem Gewinn.
5. Passe test_relevance_heuristic_meets_measured_floor an die neuen Labels an
   (Floor mit Marge).

Constraints: CI bleibt offline & deterministisch (Fixtures). Default unveraendert.
Lauf unittest + validate_data.py + eval_relevance.py bis gruen.
```

---

## A2 — Inhaltliche Tiefe (ein Vorzeige-Strang)

**Ziel.** Den Korpus von „Demo" auf „belastbar" heben — an **einem** Thema
exemplarisch durchgezogen, statt überall dünn.

**Umfang.**
- Einen Themen-Strang wählen (z. B. **KI-Kompetenz / AI literacy, 6–18**) und ihn
  vollständig ausbauen: mehrere reviewte Quellen → Claims → 2–3 aktive Skills →
  Framework-Mappings (inkl. Lehrplan 21), alle mit echtem Beweis-Pfad.
- Ziel-Größenordnung: dieser Strang verdoppelt die reviewten Claims und liefert
  ein erkennbar „tiefes" Beispiel für das Dashboard.
- Review ausschließlich über `promote_candidate.py` (kein Schema-Bypass);
  Evidenz-Scores bleiben berechnet.

**Akzeptanz.**
- Mind. 2 neue aktive Skills im gewählten Strang, je mit ≥ 2 reviewten,
  quellenbelegten Claims; `validate_data.py` grün.
- Lehrplan-21-Abdeckung des Strangs im Dashboard sichtbar.

#### Umsetzungs-Prompt A2

```
Kontext: Repo future-skills-evidence-graph. Lies README.md (Data model, Reviewing
candidates), scripts/promote_candidate.py, docs/lehrplan21-coverage-methodik.md
und die bestehenden data/skills/*.json.

Aufgabe: EINEN Themen-Strang (Vorschlag: AI literacy, Alter 6-18) zu einem tiefen,
voll belegten Beispiel ausbauen. Keine Heuristik-/Pipeline-Aenderung.

1. Recherchiere/ergaenze mehrere serioese Quellen zum Strang (Metadaten +
   Abstract, kein Volltext) als reviewte Sources.
2. Leite je Quelle strukturierte Claims ab (Kontext, Alter, Outcome, Evidenz-
   staerke real ausgefuellt) und promote sie via promote_candidate.py.
3. Definiere 2-3 aktive Skills mit >= 2 stuetzenden Claims und Framework-Mappings
   inkl. Lehrplan 21.
4. Regeneriere Scores (score_evidence.py --write) und das Dashboard.

Constraints: Kein Schema-Bypass; jeder aktive Skill ruht nur auf reviewten Claims.
Lauf validate_data.py + unittest + build_site.py bis gruen.
```

---

## A3 — Thought-Leadership-Layer (deutsch)

**Ziel.** Die Governance-Story aus dem Code holen und **verbreitbar** machen — für
die Position KI · Verwaltung · Bildung.

**Umfang.**
- Neues `docs/governance-und-haltung.md` (deutsch, ~2 Seiten): das Prinzip
  „ehrliche KI" — deterministisch, auditierbar, Mensch-in-der-Schleife,
  deaktivierte-bis-belegte Modelle als *Feature*, Datenschutz/Nachvollziehbarkeit
  als Verwaltungs-/Bildungsnutzen. Konkret an diesem Repo belegt (mit den
  Negativresultaten als Stärke).
- README-Sprachstrategie: deutschsprachige Einstiegszeile + Verweis auf die
  deutschen Docs (erklaerung-fuer-laien, governance-und-haltung), damit die
  DACH-Zielgruppe abgeholt wird.
- Optional: ein knapper „Blogpost-Entwurf" als Abschnitt, der ohne Repo-Kontext
  lesbar ist (für Wiederverwendung außerhalb GitHub).

**Akzeptanz.**
- `docs/governance-und-haltung.md` existiert, deutsch, ohne Code-Jargon lesbar,
  verlinkt aus README; nennt konkrete Belege (deaktiviertes Modell, Eval-VERDICTs,
  Beweis-Pfad-Zwang).
- Keine Funktionsänderung.

#### Umsetzungs-Prompt A3

```
Kontext: Repo future-skills-evidence-graph. Lies docs/architektur.md,
docs/erklaerung-fuer-laien.md, README.md (Evidence scoring, Automation) und
docs/ki-weiterentwicklung-plan.md. Nutzer positioniert sich als Thought Leader in
KI, Verwaltung und Bildung (DACH).

Aufgabe: Die Governance-/Haltungs-Story sichtbar und verbreitbar machen. Reine Doku.

1. Schreibe docs/governance-und-haltung.md (deutsch, ~2 Seiten, ohne Code-Jargon):
   Warum "ehrliche, auditierbare KI" - deterministische Heuristik als Default,
   Modelle deaktiviert bis messbar besser, Mensch-in-der-Schleife, Beweis-Pfad-
   Zwang, Provenienz. Belege jede Aussage konkret an diesem Repo (deaktiviertes
   TF-IDF-Modell, Embedding-VERDICT, reproduzierbares CI). Bezug zu Verwaltung &
   Bildung (Vertrauen, Datenschutz, Nachvollziehbarkeit) explizit machen.
2. Ergaenze eine deutschsprachige Einstiegszeile in README mit Links zu den
   deutschen Docs.
3. Optional: ein "Blogpost-Entwurf"-Abschnitt, ausserhalb des Repos lesbar.

Constraints: Faktentreu zum Repo-Stand (keine ueberzogenen Claims). Keine
Code-Aenderung. Tests/Build bleiben gruen.
```

---

## A4 — P1-Eval härten

**Ziel.** Aus dem eingefrorenen Regressionstest eine belastbare Genauigkeits-
aussage machen und ehrlich rahmen.

**Umfang.**
- Golden-Set `eval/claim_prefill_labeled.json` von 22 auf ~50 Beispiele erweitern
  (breitere Themen/Altersbänder, schwierigere Outcome-/Strength-Fälle).
- **Re-Record-Workflow** dokumentieren: ein Make-/Skript-Target, das die Fixtures
  mit `AI_PROVIDER=anthropic` neu aufzeichnet, damit die Messung periodisch gegen
  die echte API frisch wird; CI bleibt cache-offline.
- README/OPERATIONS-Formulierung präzisieren: „CI-Gate = Regression gegen
  aufgezeichnete Modell-Ausgaben; Live-Genauigkeit wird beim Re-Record gemessen."

**Akzeptanz.**
- ~50 Beispiele; `eval_claim_prefill.py` mit unverändertem CI-Gate grün.
- Re-Record-Target vorhanden und dokumentiert; CI weiterhin offline.
- Kein „Live-Precision"-Wording mehr ohne den Re-Record-Hinweis.

#### Umsetzungs-Prompt A4

```
Kontext: Baut auf P1. Lies scripts/eval_claim_prefill.py, eval/claim_prefill_
labeled.json, scripts/ai_provider.py (Cache), .github/workflows/validate.yml und
die README/OPERATIONS-Stellen zum Pre-Fill.

Aufgabe: Das Pre-Fill-Eval belastbarer und ehrlicher machen.

1. Erweitere eval/claim_prefill_labeled.json auf ~50 Beispiele (breitere Themen,
   Altersbaender, schwierigere outcome/evidence_strength-Faelle), sauber gelabelt.
2. Fuege ein Re-Record-Target hinzu (Makefile/Skript): zeichnet die Pre-Fill-
   Fixtures mit AI_PROVIDER=anthropic neu auf. Dokumentiere es in OPERATIONS.
3. Praezisiere README/OPERATIONS: CI-Gate ist eine Regression gegen aufgezeichnete
   Ausgaben; Live-Genauigkeit wird beim Re-Record gemessen.

Constraints: CI bleibt cache-offline & deterministisch; bestehendes --min-* Gate
unveraendert. Lauf eval_claim_prefill.py + unittest bis gruen.
```

---

## A5 — P4-Halluzinationsschutz adversarial belegen

**Ziel.** Die zentrale Sicherheitsbehauptung des Report-Importers (nur wörtliche
Zitate überleben) messbar nachweisen — inklusive Grenzfällen.

**Umfang.**
- Adversariale Fixture-Suite für `verbatim_passage`/`build_claims`: erfundene,
  paraphrasierte, gekürzte und typografisch verfälschte Statements müssen
  **verworfen** werden; echte (auch über Zeilenumbruch/Ligatur) müssen **bestehen**.
- Mindestens ein bewusst harter Grenzfall (z. B. ein paraphrasiertes Statement,
  das viele Wörter teilt) als Negativ-Beweis.
- Kurzer „Sicherheitsmodell"-Abschnitt in `docs/report-import.md`: was der Guard
  garantiert, was nicht.

**Akzeptanz.**
- Neue Tests in `tests/test_data_integrity.py` decken alle vier Verwerf-Klassen
  + zwei Bestehens-Klassen ab; grün, offline.
- `docs/report-import.md` benennt Garantie und Grenzen explizit.

#### Umsetzungs-Prompt A5

```
Kontext: Baut auf P4. Lies scripts/ingest_reports.py (normalize_for_match,
verbatim_passage, build_claims), tests/test_data_integrity.py (ReportImportTests)
und docs/report-import.md.

Aufgabe: Den Halluzinationsschutz adversarial belegen.

1. Ergaenze ReportImportTests um eine adversariale Suite: erfundene, paraphrasierte,
   gekuerzte und typografisch verfaelschte Statements werden VERWORFEN; echte
   (inkl. Zeilenumbruch-Hyphenation und Ligaturen) BESTEHEN. Mindestens ein harter
   Paraphrase-Grenzfall (viele gemeinsame Woerter) als Negativbeweis.
2. Ergaenze in docs/report-import.md einen Abschnitt "Sicherheitsmodell": was der
   verbatim-Guard garantiert und was nicht (z. B. semantische Treue garantiert er
   nicht - nur woertliche Herkunft).

Constraints: Offline, deterministisch, keine Live-API. Lauf
`python -m unittest discover -s tests` bis gruen.
```

---

## Definition of Done (je Paket)

- [ ] Default-Verhalten unverändert (Provider/Modus `none`/`local`/`heuristic`).
- [ ] Offline-Tests grün; `validate_data.py` grün.
- [ ] Bei A1/A4: ehrliches VERDICT bzw. präzises Eval-Framing dokumentiert.
- [ ] Bei A0/A3: keine toten Links; README schlanker statt nur verschoben.
- [ ] Ein PR pro Paket, mit Vorher/Nachher-Beleg (Zeilenzahl, Messzahl, Test).

*Verwandte Dokumente:* [ki-weiterentwicklung-plan.md](ki-weiterentwicklung-plan.md)
(v1) · [architektur.md](architektur.md) · [../README.md](../README.md) ·
[../OPERATIONS.md](../OPERATIONS.md).
