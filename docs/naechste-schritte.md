# Nächste Schritte: die offenen Messungen

Drei Fähigkeiten waren gebaut, aber **noch nicht gemessen**. Sie sind deshalb
alle standardmässig aus und in keinen automatischen Workflow eingebunden — was
korrekt ist, aber auch heisst, dass niemand weiss, wie gut sie sind. Diese Liste
schliesst diese Lücke.

**Stand 2026-08-01.** Erledigt: Block 1.1–1.4 (Claim-Prefill live gemessen,
Zahlen in [../OPERATIONS.md](../OPERATIONS.md) unter „Measured baseline") und
Block 2 (Gold-Satz durchgesehen, `_status: reviewed`). Offen: **1.5** — die
Skill-Link-Aufzeichnung, für die es jetzt einen Workflow gibt —, die daraus
abzuleitenden Schwellen in 2.3, und **Block 3**, die Gegenevidenz-Lane.

Jeder Block ist **eigenständig abarbeitbar** und braucht einen
`ANTHROPIC_API_KEY` (Block 2 nicht). Es gibt keine Reihenfolge zwischen den
Blöcken ausser einer: der **letzte Schritt** von Block 2 — die Schwellen setzen
und in `validate.yml` aufnehmen — setzt die Messung aus 1.5 voraus. Die
Durchsicht selbst braucht sie nicht und ist deshalb vorgezogen worden.

Verwandte Dokumente: [../OPERATIONS.md](../OPERATIONS.md) (Runbook),
[gegenevidenz-lane.md](gegenevidenz-lane.md) (Agenten-Lane),
[go-live-checkliste.md](go-live-checkliste.md) (Betriebs-Abnahme).

> **Wann dieses Dokument verschwindet.** Es beschreibt einen Übergangszustand.
> Sobald alle drei Blöcke abgehakt sind, wandern die gemessenen Zahlen und die
> Aktivierungsentscheidungen nach `OPERATIONS.md` und diese Datei wird gelöscht.
> Eine Liste offener Punkte, die niemand mehr abarbeitet, ist schlimmer als
> keine.

---

## 0. Vorbereitung

```bash
pip install -r requirements-dev.txt        # anthropic, sentence-transformers, jsonschema
pip install -r requirements-agents.txt     # nur für Block 3 (langgraph)
export ANTHROPIC_API_KEY="sk-ant-..."
```

- [ ] **Auf einem Branch arbeiten.** Die Record-Läufe **überschreiben**
      `_recorded` und die Fixtures. Auf einem Branch ist der Rückweg ein Befehl:

      ```bash
      git checkout -b messungen/live-baseline
      # Rückweg jederzeit:  git checkout -- eval/ tests/fixtures/
      ```

- [ ] **`sentence-transformers` prüfen.** Fehlt das Paket, fällt der Scorer
      **still** auf die lexikalische Messung zurück, die Textfeld-Gates
      überspringen sich, und die neuen Embedding-Vektoren werden nie erzeugt —
      CI schlägt dann erst später fehl.

      ```bash
      python -c "import sentence_transformers; print('OK')"
      ```

---

## 1. Live-Messungen des KI-Assists

> ✅ **Erledigt am 2026-08-01** (PRs #180, #181). Zwei Live-Läufe über den
> Workflow `eval-prefill-record`; Lauf 2 ist committet. Die Details stehen in
> [../OPERATIONS.md](../OPERATIONS.md) → „Measured baseline". Die Schritte 1.1–1.4
> bleiben als **Rezept** stehen, weil sie bei jedem v8, jedem Modellwechsel und
> jeder Erweiterung des Gold-Satzes erneut gebraucht werden.

Der Prompt `claim-prefill-v7` war nie gegen das echte Modell gelaufen: seine
Fixtures wurden aus v6 **migriert** (`high` → `strong`, dieselbe Bewertung unter
dem Namen, den das Datenmodell akzeptiert). Die Regression war damit als
Drift-Check gültig, aber v7s Live-Verhalten unbekannt — insbesondere die neu
erlaubte Abstinenz bei `evidence_strength`.

### 1.1 Claim-Prefill aufzeichnen — 50 API-Calls

- [x] ```bash
      make eval-prefill-record
      ```

Ruft für jedes der 50 Gold-Beispiele das Modell auf, überschreibt `_recorded`
und die Fixtures, und druckt die **live gemessene** Genauigkeit.

| Feld | migrierte Baseline | **live gemessen** | CI-Gate |
| --- | --- | --- | --- |
| `age_range` | P 0.94 | **P 0.91** | ≥ 0.80 ✓ |
| `evidence_strength` | P 0.82, abstain 0/50 | **P 0.80, abstain 0/50** | ≥ 0.70 ✓ |
| `outcome` | P 0.85 | **P 0.87** | ≥ 0.75 ✓ |
| `context` | P 0.98 | **P 0.96** | ≥ 0.85 ✓ |

> **Der eigentliche Prüfpunkt war die `abstain`-Spalte bei
> `evidence_strength`.** v7 erlaubt erstmals „nicht erkennbar"; unter v6 riet das
> Modell in 50 von 50 Fällen. **Sie steht weiterhin auf `0` — in beiden Läufen.**
> Die Prompt-Änderung hat für dieses Feld also nicht gewirkt. Das ist ein
> **Befund, kein Fehler**: er ist in `OPERATIONS.md` festgehalten und begründet
> ein v8, zusammen mit den durchgängig zu breiten `age_range`-Vorschlägen.

> **Kürzester Weg: Actions → *Re-record claim pre-fill live baseline (manual)*.**
> Der Workflow erledigt 1.1 bis 1.4 in einem Lauf und öffnet einen PR. Die
> folgenden Schritte sind der lokale Weg — und die Erklärung, was der Workflow
> tut, falls er einmal etwas auslässt. Genau das ist beim ersten echten Lauf
> passiert: er hatte `tests/fixtures/embeddings/` nicht committet (behoben in
> #181).

### 1.2 Embedding-Vektoren prägen — kein API-Call

- [x] ```bash
      make eval-prefill
      ```

Die Antworten aus 1.1 sind neue Texte ohne Vektor; dieser Lauf erzeugt sie.
**Er dauert dann ein bis zwei Minuten statt sieben Sekunden** — das ist das
Zeichen, dass Vektoren geprägt werden, kein Hänger.

Diesen Schritt zu überspringen fällt **nicht** von selbst auf: ohne Vektoren
fällt der Scorer auf lexikalisch zurück, und das semantische Gate ist bewusst so
gebaut, dass es dann *überspringt* statt zu scheitern. Die CI wäre grün und
würde nichts mehr prüfen. Deshalb 1.3.

### 1.3 Absichern

- [x] ```bash
      make test        # der Fixture-Coverage-Test schlägt an, falls Vektoren fehlen
      make validate
      ```

### 1.4 Committen — alle drei zusammen

- [x] ```bash
      git add eval/claim_prefill_labeled.json tests/fixtures/ai/ tests/fixtures/embeddings/
      git commit -m "eval: Live-Baseline fuer Prompt v7 aufgezeichnet"
      ```

Aufzeichnung, Fixtures und Vektoren gehören in **einen** Commit, sonst laufen
Aufzeichnung und Replay auseinander.

- [x] **Gemessene Zahlen in `OPERATIONS.md` nachtragen** (Abschnitt „Optional AI
      claim pre-fill") und den Hinweis „Outstanding for v7" entfernen.

### 1.5 Skill-Links aufzeichnen — 50 API-Calls

> **Kürzester Weg: Actions → *Re-record skill-link live baseline (manual)*.**
> Derselbe Aufbau wie beim Prefill: aufzeichnen, offline gegenprüfen, PR öffnen.
> Die Gate-Eingaben bleiben beim ersten Lauf **leer** — es gibt noch keinen
> gemessenen Wert, aus dem sich eine Schwelle ableiten liesse.

- [ ] ```bash
      make eval-skill-links-record   # oder der Workflow oben
      make eval-skill-links
      ```

> **Lies die `abstain`-Spalte zuerst, nicht die Precision.** 40 der 50 Beispiele
> bilden auf *keinen* Skill ab. Ein Modell, das für jeden Claim einen plausiblen
> Skill rät, sieht bei den 10 gut aus und überflutet den Reviewer bei den 40.

Das Gate ist seit der Freigabe in Block 2 **erlaubt**, aber noch nicht gesetzt:
erst messen, dann schwellen. `_recorded` ist derzeit 0 von 50 — es existiert
also noch gar keine Aufzeichnung, gegen die ein Offline-Lauf etwas replayen
könnte.

---

## 2. Skill-Link-Gold-Satz durchsehen — keine API-Calls

> ✅ **Erledigt am 2026-07-31** (Commit `10e9d3a`). Ergebnis der Durchsicht:
> `prefill-spaced-retrieval` wurde **entfernt** — die Studie misst die Retention
> einer *vorgegebenen* Spacing-Technik, also ein Gedächtnisergebnis, und nicht
> die Selbstregulation der Lernenden. Der Kontrast zu `prefill-adhd-selfmonitor`
> (misst eine SRL-*Handlung*, bleibt) ist der Grund, warum die beiden Fälle
> auseinandergehen. Der Zwei-Link-Fall `prefill-misinformation-game` trägt beide
> Links. Die übrigen acht blieben wie vorgeschlagen. Damit: **10 Links, 40 leer**,
> `_status: reviewed`.
>
> Die Schritte bleiben als **Rezept** stehen — bei jeder Erweiterung des
> Gold-Satzes ist dieselbe Durchsicht fällig, und der Maßstab in 2.2 ist die
> Regel, an der sie sich misst.

`eval/skill_link_labeled.json` trug im Kopf:

```json
"_status": "proposed-unreviewed"
```

Die Zuordnungen waren **von einem Agenten vorgeschlagen, nicht kuratiert**.
Redaktionelles Urteil liegt laut Governance bei einem Menschen, deshalb
verweigert `eval_skill_links.py` jedes `--min-*`-Gate mit Exit 1, solange dieser
Status steht.

### 2.1 Die vorgeschlagenen Zuordnungen ansehen

- [x] ```bash
      python - <<'PY'
      import json
      links=json.load(open('eval/skill_link_labeled.json'))
      pre={e['id']:e for e in json.load(open('eval/claim_prefill_labeled.json'))['examples']}
      for e in links['examples']:
          if not e['gold']['supports_skill_ids']: continue
          print(f"\n{e['id']}\n  {pre[e['id']]['statement']}\n  -> {e['gold']['supports_skill_ids']}")
          if e.get('_note'): print(f"  Notiz: {e['_note']}")
      PY
      ```

### 2.2 Der Maßstab

Die Regel steht im `_README` der Datei und gilt für jede Entscheidung:

> Ein Claim verlinkt einen Skill nur, wenn er ein **gemessenes Ergebnis** zu
> diesem Skill berichtet. Ein Positionspapier, eine Empfehlung oder eine
> Design-Beschreibung, die für einen Skill argumentiert, ohne etwas zu messen,
> wird **leer** gelabelt — so passend sie thematisch auch liest. Blosse Nähe zum
> Thema eines Skills genügt ebenfalls nicht.

Eine leere Liste ist ein gültiges Label, kein Versäumnis.

- [x] **Drei Grenzfälle entscheiden** — hier ist fachliches Urteil nötig:

      - `prefill-spaced-retrieval` — ist die Wirksamkeit einer *Lernstrategie*
        Evidenz für **Selbstreguliertes Lernen**?
      - `prefill-adhd-selfmonitor` — Selbstüberwachung senkt Off-Task-Verhalten.
        Selbstreguliertes Lernen oder Verhaltensintervention?
      - `prefill-misinformation-game` — der einzige Fall mit **zwei** Links
        (`critical-thinking` + `digital-media-literacy`). Trägt er beide?

- [x] **Die restlichen acht prüfen.** Nach der obigen Regel geradlinig.

### 2.3 Freigeben und gaten

- [x] `"_status": "reviewed"` in `eval/skill_link_labeled.json` setzen.

- [ ] Schwellen **aus den gemessenen Werten** aus 1.5 ableiten, mit Abstand —
      so wie `age_range` live bei 0.91 gemessen und auf 0.80 gegatet ist:

      ```bash
      python scripts/eval_skill_links.py --min-precision <gemessen-0.1> \
                                          --min-abstention <gemessen-0.1>
      ```

- [ ] Erst wenn das hält: den Aufruf in `.github/workflows/validate.yml`
      aufnehmen und die Entscheidung in `OPERATIONS.md` festhalten.

---

## 3. Gegenevidenz-Lane erproben

Der Katalog hält 146 Claims mit **genau einem** `contradicts_skill_ids`-Eintrag.
Die Lane ([gegenevidenz-lane.md](gegenevidenz-lane.md)) soll das schliessen —
ob sie es tut, ist ungemessen.

Kosten je Lauf: bis zu 3 Query-Calls + bis zu 60 Assess-Calls.

### 3.1 Trockenlauf — schreibt keine Kandidaten

- [ ] ```bash
      AI_PROVIDER=anthropic python agents/counter_evidence.py \
        --skill skill-systems-thinking --dry-run
      ```

> **`--dry-run` heisst nicht „schreibt nichts".** Unterdrückt werden nur
> Kandidaten-Claims und -Quellen. Weiterhin geschrieben werden: das
> **Laufprotokoll** unter `agents/runs/` (das ist der Zweck des Trockenlaufs)
> und — bei `AI_PROVIDER=anthropic` — je ein **Fixture** pro Modellaufruf unter
> `tests/fixtures/ai/`. Drei Läufe können den Arbeitsbaum also um etliche
> Dateien erweitern.
>
> Was damit tun: die **Laufprotokolle committen** (sie sind der Audit-Trail und
> gehören zur Messung), die **Fixtures verwerfen**, solange kein Replay des
> Agenten gewünscht ist:
>
> ```bash
> git add agents/runs/
> git checkout -- tests/fixtures/ai/ 2>/dev/null; git clean -f tests/fixtures/ai/
> ```

### 3.2 Das Laufprotokoll lesen — das ist der Kern

- [ ] ```bash
      cat agents/runs/$(date +%F)-skill-systems-thinking.json
      ```

Ein Lauf ist nicht reproduzierbar wie der Kern, deshalb ist er nachvollziehbar.
Prüfe:

- **`queries_used`** — sucht der Agent wirklich nach Null-Resultaten
  („no significant difference", „failed to replicate"), oder formuliert er nur
  den Skillnamen um? Das entscheidet über die Qualität mehr als alles andere.
- **`stopped_because`** — nennt den konkreten Grund: `round_limit` (Rundenbudget
  aufgebraucht), `query_budget` (Query-Budget aufgebraucht), `no_new_queries`
  (der Generator lieferte nichts Neues mehr) oder `no_new_findings` (zwei Runden
  ohne Fund). Der Unterschied zählt: `no_new_findings` heisst „hier ist
  vermutlich nichts", `round_limit` heisst „das Budget war zu klein".
- **`sources_examined` vs. `findings`** — 60 geprüfte Quellen mit 0 Funden ist
  ein **valides Ergebnis**. Gegenevidenz ist selten; das ist der Grund, warum es
  diese Lane gibt.

### 3.3 Drei Läufe für die Aktivierungsschwelle

- [ ] Drei **verschiedene** Skills nehmen, sonst misst man eine
      Query-Formulierung statt der Lane:

      ```bash
      for s in skill-systems-thinking skill-critical-thinking skill-creative-problem-solving; do
        AI_PROVIDER=anthropic python agents/counter_evidence.py --skill "$s" --dry-run
      done
      ```

- [ ] Je Lauf notieren: **Vorschläge / davon echte Widersprüche**.

Die Aktivierungsschwelle ist **Präzision ≥ 0.5** über die drei Läufe — bewusst
niedrig, weil ein Fund unter zwei Vorschlägen den heutigen Stand (1 aus 146)
bereits schlägt, aber nicht null: eine Lane, die überwiegend Fehlalarme
produziert, kostet Reviewzeit.

### 3.4 Erst wenn die Schwelle hält: echter Lauf

- [ ] ```bash
      AI_PROVIDER=anthropic python agents/counter_evidence.py --skill skill-systems-thinking
      make validate
      ```

- [ ] Kandidaten über `scripts/promote_candidate.py` prüfen — **jedes Zitat
      gegen die Quelle**, auch wenn der Agent die Wörtlichkeit bereits
      maschinell geprüft hat.

- [ ] Ergebnis der drei Läufe in `gegenevidenz-lane.md` festhalten (Abschnitt
      „Aktivierungs- und Decommission-Regel").

---

## Aufwand im Überblick

| Block | API-Calls | Zeit | Voraussetzung |
| --- | --- | --- | --- |
| 1.1–1.4 Prefill | 50 | ~10 Min | Key |
| 1.5 Skill-Links | 50 | ~5 Min | Key |
| 2 Durchsicht | 0 | ~30 Min Kopfarbeit | Block 1.5 |
| 3 Lane, je Lauf | bis 63 | ~15 Min | Key + `langgraph` |

Block 3 ist unabhängig von 1 und 2. Wer nur eines machen will, nimmt Block 3 —
dort ist der inhaltliche Ertrag am grössten.
