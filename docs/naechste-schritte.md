# Nächste Schritte: die offenen Messungen

Drei Fähigkeiten sind gebaut, aber **noch nicht gemessen**. Sie sind deshalb
alle standardmässig aus und in keinen automatischen Workflow eingebunden — was
korrekt ist, aber auch heisst, dass niemand weiss, wie gut sie sind. Diese Liste
schliesst diese Lücke.

Jeder Block ist **eigenständig abarbeitbar** und braucht einen
`ANTHROPIC_API_KEY` (Block 2 nicht). Es gibt keine Reihenfolge zwischen den
Blöcken ausser: Block 2 setzt Block 1.5 voraus.

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

Der Prompt `claim-prefill-v7` ist nie gegen das echte Modell gelaufen: seine
Fixtures wurden aus v6 **migriert** (`high` → `strong`, dieselbe Bewertung unter
dem Namen, den das Datenmodell akzeptiert). Die Regression ist damit als
Drift-Check gültig, aber v7s Live-Verhalten ist unbekannt — insbesondere die neu
erlaubte Abstinenz bei `evidence_strength`.

### 1.1 Claim-Prefill aufzeichnen — 50 API-Calls

- [ ] ```bash
      make eval-prefill-record
      ```

Ruft für jedes der 50 Gold-Beispiele das Modell auf, überschreibt `_recorded`
und die Fixtures, und druckt die **live gemessene** Genauigkeit.

| Feld | migrierte Baseline | CI-Gate |
| --- | --- | --- |
| `age_range` | P 0.94 | ≥ 0.80 |
| `evidence_strength` | P 0.82, **abstain 0/50** | ≥ 0.70 |
| `outcome` | P 0.85 | ≥ 0.75 |
| `context` | P 0.98 | ≥ 0.85 |

> **Der eigentliche Prüfpunkt ist die `abstain`-Spalte bei
> `evidence_strength`.** v7 erlaubt erstmals „nicht erkennbar"; unter v6 riet das
> Modell in 50 von 50 Fällen. Steht dort weiterhin `0`, hat die Prompt-Änderung
> nicht gewirkt. Das ist ein **Befund, kein Fehler** — er gehört dann in
> `OPERATIONS.md` und begründet ein v8.

### 1.2 Embedding-Vektoren prägen — kein API-Call

- [ ] ```bash
      make eval-prefill
      ```

Die Antworten aus 1.1 sind neue Texte ohne Vektor; dieser Lauf erzeugt sie.
**Er dauert dann ein bis zwei Minuten statt sieben Sekunden** — das ist das
Zeichen, dass Vektoren geprägt werden, kein Hänger.

### 1.3 Absichern

- [ ] ```bash
      make test        # der Fixture-Coverage-Test schlägt an, falls Vektoren fehlen
      make validate
      ```

### 1.4 Committen — alle drei zusammen

- [ ] ```bash
      git add eval/claim_prefill_labeled.json tests/fixtures/ai/ tests/fixtures/embeddings/
      git commit -m "eval: Live-Baseline fuer Prompt v7 aufgezeichnet"
      ```

Aufzeichnung, Fixtures und Vektoren gehören in **einen** Commit, sonst laufen
Aufzeichnung und Replay auseinander.

- [ ] **Gemessene Zahlen in `OPERATIONS.md` nachtragen** (Abschnitt „Optional AI
      claim pre-fill") und den Hinweis „Outstanding for v7" entfernen.

### 1.5 Skill-Links aufzeichnen — 50 API-Calls

- [ ] ```bash
      make eval-skill-links-record
      make eval-skill-links
      ```

> **Lies die `abstain`-Spalte zuerst, nicht die Precision.** 39 der 50 Beispiele
> bilden auf *keinen* Skill ab. Ein Modell, das für jeden Claim einen plausiblen
> Skill rät, sieht bei den 11 gut aus und überflutet den Reviewer bei den 39.

Das Gate bleibt hier **verweigert** — das ist Absicht und wird in Block 2
aufgehoben.

---

## 2. Skill-Link-Gold-Satz durchsehen — keine API-Calls

`eval/skill_link_labeled.json` trägt im Kopf:

```json
"_status": "proposed-unreviewed"
```

Die Zuordnungen wurden **von einem Agenten vorgeschlagen, nicht kuratiert**.
Redaktionelles Urteil liegt laut Governance bei einem Menschen, deshalb
verweigert `eval_skill_links.py` jedes `--min-*`-Gate mit Exit 1, solange dieser
Status steht.

### 2.1 Die 11 Zuordnungen ansehen

- [ ] ```bash
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

- [ ] **Drei Grenzfälle entscheiden** — hier ist fachliches Urteil nötig:

      - `prefill-spaced-retrieval` — ist die Wirksamkeit einer *Lernstrategie*
        Evidenz für **Selbstreguliertes Lernen**?
      - `prefill-adhd-selfmonitor` — Selbstüberwachung senkt Off-Task-Verhalten.
        Selbstreguliertes Lernen oder Verhaltensintervention?
      - `prefill-misinformation-game` — der einzige Fall mit **zwei** Links
        (`critical-thinking` + `digital-media-literacy`). Trägt er beide?

- [ ] **Die restlichen acht prüfen.** Nach der obigen Regel geradlinig.

### 2.3 Freigeben und gaten

- [ ] `"_status": "reviewed"` in `eval/skill_link_labeled.json` setzen.

- [ ] Schwellen **aus den gemessenen Werten** aus 1.5 ableiten, mit Abstand —
      so wie `age_range` bei 0.94 gemessen und auf 0.80 gegatet ist:

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

### 3.1 Trockenlauf — schreibt nichts

- [ ] ```bash
      AI_PROVIDER=anthropic python agents/counter_evidence.py \
        --skill skill-systems-thinking --dry-run
      ```

### 3.2 Das Laufprotokoll lesen — das ist der Kern

- [ ] ```bash
      cat agents/runs/$(date +%F)-skill-systems-thinking.json
      ```

Ein Lauf ist nicht reproduzierbar wie der Kern, deshalb ist er nachvollziehbar.
Prüfe:

- **`queries_used`** — sucht der Agent wirklich nach Null-Resultaten
  („no significant difference", „failed to replicate"), oder formuliert er nur
  den Skillnamen um? Das entscheidet über die Qualität mehr als alles andere.
- **`stopped_because`** — Abbruch durch Rundenlimit oder durch Erschöpfung?
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
