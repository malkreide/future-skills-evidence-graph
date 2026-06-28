# Die Skill-„Tierliste" evidenzbasiert erstellen und aktuell halten

*Praxisanleitung: Wie die Liste der Future Skills entsteht und gepflegt wird.*

---

> **Begriffsklärung.** „Tierliste" meint hier das **Ranking der Future Skills**
> (engl. *tier list*) – also die nach Evidenz gewichtete Liste der
> Zukunftskompetenzen –, **nicht** eine Liste von Tieren. Der Ausgangs-Branch
> `evidence-based-animal-list` beruht auf einer Fehlübersetzung von *Tier*
> (=Rang) zu *Tier* (=animal).

Das tragende Prinzip des Projekts lautet: **Keine Kompetenz-Empfehlung ohne
Beleg-Pfad.** Genau daran hängen beide Hälften dieser Anleitung:

- *evidenzbasiert erstellen* = jede Kompetenz an eine nachvollziehbare
  Belegkette `Quelle → Claim → Skill` binden,
- *aktuell halten* = diese Kette automatisiert nachführen, aber jede
  Veröffentlichung von Menschen prüfen lassen.

---

## Teil 1 – Evidenzbasiert erstellen

Die Liste wird **nie frei behauptet**, sondern entsteht über die Belegkette des
Datenmodells (`MASTER_PROMPT.md`, `README.md`):

| Baustein | Was es ist | Regel |
|----------|------------|-------|
| **Source** | Echte Studie / Report (OpenAlex, Crossref, Semantic Scholar, arXiv, ERIC; manuell auch OECD, WEF, UNESCO, DigComp) | Nur Metadaten, Abstracts wo erlaubt, Links, projekteigene Extrakte – **kein** urheberrechtlicher Volltext |
| **Claim** | Strukturierte Aussage, **wörtlich** aus dem Abstract extrahiert (`extract_claims.py`) | Nur Befund-Sätze, kein Methodik-Satz; immer mit Text-Anker auf die Originalstelle |
| **Skill** | Aus geclusterten Claims (`cluster_claims.py`) | Aktiv nur mit ≥ 1 reviewtem Claim und Framework-Mapping (Lehrplan 21 bzw. UNESCO-for-Teachers) |

Die Regeln, die „evidenzbasiert" durchsetzen:

1. **Belegkette ist Pflicht.** Jeder *aktive* Skill referenziert mindestens
   einen reviewten `Claim`; jeder Claim mindestens eine `Source`.
2. **Score ist abgeleitet, nicht handgesetzt.** `score_evidence.py` berechnet
   den `evidence_score` aus Quellenqualität (60 %) und Evidenzstärke (40 %),
   skaliert mit einem Breiten-Faktor für mehrere unabhängige Claims (sättigt
   bei 6), minus Abzug für widersprechende Claims.
3. **Drift wird erzwungen.** `validate_data.py` rechnet jeden gespeicherten
   Score nach und **schlägt fehl**, wenn ein Wert von der Formel abweicht – der
   Trust-Wert im Dashboard bleibt damit reproduzierbar.
4. **Kandidat ≠ aktiv.** Automatik erzeugt ausschließlich `candidate`-Datensätze.
   Ein Mensch promotet sie per Pull Request über `promote_candidate.py`;
   maschinelle Platzhalter blockieren die Promotion.

Lokal nachrechnen und prüfen:

```bash
pip install -r requirements-dev.txt
python scripts/score_evidence.py --write   # evidence_score neu berechnen
python scripts/validate_data.py            # Belegketten + Score-Drift prüfen → "Validation passed."
python scripts/build_site.py               # Dashboard-Daten (data/index.json) neu bauen
```

---

## Teil 2 – Aktuell halten (wöchentlicher Zyklus)

Der Betriebs-Runbook steht in [OPERATIONS.md](../OPERATIONS.md); hier die
Kurzfassung. Die Pipeline (`research-pipeline.yml`) läuft per Cron montags um
05:17 UTC und kann manuell über *Actions → „Research candidate import" → Run
workflow* ausgelöst werden.

1. **Run.** Die Pipeline importiert neue Quellen, extrahiert Claims, clustert
   Kandidaten und öffnet einen `research/candidates`-Pull-Request. Spätere Läufe
   hängen an denselben PR an, statt Duplikate zu erzeugen.
2. **CI.** Auf dem PR muss der `validate`-Check grün sein.
3. **Review.** Erst ein Arbeitsblatt erzeugen, dann jeden Kandidaten
   entscheiden:

   ```bash
   make triage   # schreibt eval/candidate_triage.json (gitignored, read-only)
   ```

   Das Arbeitsblatt listet jeden offenen Kandidaten-Claim mit wörtlichem
   Statement, getroffenen Topics, seinen Quellen, etwaigen `assist`-Vorschlägen
   und den fertigen `promote_candidate.py`-Befehlen. Promotet wird nichts
   automatisch – die Befehle führst du selbst aus:

   ```bash
   # Guter Claim → reviewed:
   python scripts/promote_candidate.py claim <claim-id> \
     --context "..." --age-range "12-18" --outcome "..." \
     --evidence-type systematic_review --evidence-strength moderate \
     --supports <skill-id>

   # Unbrauchbarer Claim → rejected:
   python scripts/promote_candidate.py reject <claim-id>

   # Off-scope Quelle → rejected + harvestet ein NEGATIVES Relevanz-Label:
   python scripts/promote_candidate.py reject-source <source-id>

   # In-scope Quelle → reviewed + harvestet ein POSITIVES Relevanz-Label:
   python scripts/promote_candidate.py promote-source <source-id>

   # Reviewten Claim in einen bestehenden Skill einfalten (rechnet Score neu):
   python scripts/promote_candidate.py attach-claim <skill-id> --claim <claim-id>
   ```

4. **Publizieren.** Merge des PR nach `main` deployt das Dashboard automatisch
   (`deploy-pages.yml`).

Off-cycle ergänzend, beide münden in denselben Kandidaten-Review-Pfad:

- **Berichte einreichen** (OECD/WEF/UNESCO): Issue-Formular „Bericht einreichen"
  oder die Drag-&-Drop-Seite `site/einreichen.html` (PDF im Browser) →
  `ingest-from-issue.yml`. Siehe [report-import.md](report-import.md).
- **Web-Search-Discovery**: `ingest-websearch.yml` (manueller Dispatch,
  keyless) → Kandidaten-Quellen mit gestuftem Trust.

---

## Die drei Hebel für „ehrlich aktuell"

- **Versionierung.** Alle Daten liegen versioniert in `data/`; jede
  Skill-Änderung ist über Git/PRs nachvollziehbar – inklusive, wie sich ein
  Skill über Versionen verändert hat.
- **Mensch im Loop.** Automatik *schlägt vor*, Menschen *entscheiden* per PR.
  Das ist bewusste Zurückhaltung gegen Über-Automatisierung.
- **Widersprüche sichtbar.** Widersprechende Claims senken den Score, statt
  versteckt zu werden; Unsicherheit wird markiert statt geglättet.

---

## Checkliste vor jedem Merge

- [ ] `validate` ist grün (Belegketten vollständig, kein Score-Drift).
- [ ] Jeder aktive Skill hat ≥ 1 reviewten Claim und ein Framework-Mapping.
- [ ] Jede reviewte Quelle wurde mit `promote-source` **oder** `reject-source`
      bewertet (baut die Relevanz-Labels auf).
- [ ] Keine maschinellen Platzhalter in aktiven Datensätzen.
- [ ] `evidence_score` mit `score_evidence.py --write` neu berechnet.

> Verwandte Dokumente: [OPERATIONS.md](../OPERATIONS.md) ·
> [architektur.md](architektur.md) · [erklaerung-fuer-laien.md](erklaerung-fuer-laien.md) ·
> [relevanz-entscheidung.md](relevanz-entscheidung.md)
