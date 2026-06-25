# Go-Live-Checkliste

Der Code ist betriebsbereit (Validierung, Tests, Build und der Pages-Deploy sind
auf `main` grün). Die noch offenen Punkte für einen sauberen Go-Live sind
**konfigurativ und operativ**, nicht im Code. Diese Liste ist die
Abnahme-Checkliste: erst wenn jeder Haken sitzt, ist das Projekt „live" im Sinne
eines tragfähigen Wochenbetriebs.

Verwandte Dokumente: [../OPERATIONS.md](../OPERATIONS.md) (Runbook),
[../README.md](../README.md), [architektur.md](architektur.md).

---

## 1. GitHub-Repository-Einstellungen

- [ ] **Actions dürfen PRs öffnen.** Settings → Actions → General → *Workflow
      permissions*: „Read and write permissions" **und** „Allow GitHub Actions to
      create and approve pull requests" aktivieren. Ohne das kann der wöchentliche
      `research-pipeline.yml`-Lauf seinen `research/candidates`-PR **nicht öffnen**
      (er importiert dann zwar, aber das Ergebnis erreicht kein Review).
- [ ] **Pages-Quelle = GitHub Actions.** Settings → Pages → *Source* = „GitHub
      Actions". Der Deploy-Workflow (`deploy-pages.yml`) setzt `enablement: true`,
      aber die Quelle einmal sichtbar bestätigen.
- [ ] **Homepage-URL setzen.** Repo-About → die veröffentlichte Pages-URL
      eintragen, damit das Dashboard auffindbar ist.

## 2. Secrets & Variablen

- [ ] `SEMANTIC_SCHOLAR_API_KEY` als **Secret** hinterlegen. Ohne den Key liefert
      Semantic Scholar dauerhaft HTTP 429 und wird in jedem Lauf stumm
      übersprungen (die anderen Importer laufen trotzdem — graceful degradation).
- [ ] `OPENALEX_MAILTO` als **Variable** hinterlegen (höfliche Kontakt-E-Mail für
      den OpenAlex-„polite pool").
- [ ] *(Nur falls die optionale LLM-Vorbefüllung **oder** der manuelle
      Bericht-Import live genutzt wird)* `ANTHROPIC_API_KEY` als Secret und
      `AI_MODEL` als Variable hinterlegen. Beide treiben den manuellen
      Bericht-Import (Dashboard-Dropzone / Issue-Formular / Workflow-Dispatch,
      siehe [report-import.md](report-import.md)); ohne Provider ist dieser Pfad
      ein No-op. Für das Pflicht-CI **nicht** nötig — das läuft netzwerkfrei
      gegen Fixtures (`AI_PROVIDER=cache`).

## 3. Erster echter Betriebszyklus

Das Cycle-Log in [OPERATIONS.md](../OPERATIONS.md#cycle-log) enthält bisher nur
Dry-Runs. Go-Live verlangt **einen vollständig durchlaufenen, datierten Zyklus**:

- [ ] **Lauf auslösen.** Actions → „Research candidate import" → Run workflow
      (oder den Montags-Cron abwarten).
- [ ] **CI grün** auf dem geöffneten `research/candidates`-PR (`validate`).
- [ ] **Review** der Kandidaten mit dem Worksheet:
      ```bash
      make triage   # eval/candidate_triage.json (gitignored)
      ```
      dann je Eintrag `promote_candidate.py {claim,reject,promote-source,
      reject-source,attach-claim}` (siehe OPERATIONS.md, Schritt 3).
- [ ] **Merge** des Kandidaten-PR.
- [ ] **Deploy** läuft automatisch auf Push nach `main` (`deploy-pages.yml`) →
      Dashboard-URL prüfen.
- [ ] **Cycle-Log-Zeile** mit echten Zahlen ergänzen (Accepted, Live-Precision,
      Promoted, Promote-Rate, Harvest-Größe).

## 4. Daten-Abnahme (Inhalt)

- [ ] **Startbestand bestätigen.** Aktuell 13 aktive Skills, 26 reviewte Claims,
      32 reviewte Quellen. Entscheiden: reicht das als öffentlich kommunizierter
      Startbestand, oder soll der Kandidaten-Backlog vorher (teilweise) reviewt
      werden? (`make triage` liefert die Arbeitsliste: 36 offene Kandidaten-Claims,
      10 verwaiste Kandidaten-Quellen.)
- [ ] **Evidenzpfad-Stichprobe.** Auf der Live-Seite zwei, drei aktive Skills
      aufklappen und Quelle→Claim→Skill nachvollziehen (Validierung erzwingt das
      bereits, aber ein menschlicher Blick auf die Außenwirkung schadet nicht).

## 5. Qualitäts-Routinen scharf stellen

- [ ] **Recall-Probe einmal fahren** (`make recall-probe` → labeln →
      `make recall-ingest`), damit die abgelehnte Region des Filters Labels in den
      Eval-Satz speist (Gegengewicht zum Selektions-Bias der Harvest-Labels).
- [ ] **Klassifikator-Verdikt protokollieren** (`make eval-model`): bestätigen,
      dass die Heuristik weiterhin Default bleibt — solange kein Signal sie
      messbar schlägt.

## 6. Letzter Pflicht-Gate-Check

```bash
make install validate test eval build
```

- [ ] `validate` → „Validation passed."
- [ ] `test` → OK (Stand: 77 Tests, 1 skipped ohne optionale Dependency)
- [ ] `build` → „Built public/"

Erst wenn alle Haken sitzen, ist der Go-Live-Status erreicht. Offene
Weiterentwicklungen laufen danach als GitHub-Issues weiter (siehe
[OPERATIONS.md](../OPERATIONS.md), Abschnitt „Improvement tests").
