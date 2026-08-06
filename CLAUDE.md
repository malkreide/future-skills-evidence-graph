## Vor der Arbeit
- Klon-Aktualität prüfen: `git fetch origin main && git rev-list --count HEAD..origin/main`
  Ein veralteter Klon erzeugt eine rote CI, deren Ursache nicht im Diff steht.
  Am 3.8.2026 zweimal passiert — beide Male fehlten genau die Commits, die
  das Gate einführten, an dem der Branch scheiterte.
- Gates lokal fahren, mit der GEPINNTEN ruff-Version aus der CI. Eine andere
  Version meldet Abweichungen, die niemand verursacht hat.

## Tests
- **Gegenprobe ist Pflicht.** Ein Test, der grün bleibt, wenn man die
  Implementierung entfernt, prüft nichts. Jede neue Zusicherung einzeln
  neutralisieren und zeigen, dass genau die zugehörigen Tests fallen.
  Zwei Fallen, die beide grün blieben:
  - Eine Fake-Uhr, die nur beim Schlafen vorrückt, kann eine Zusicherung über
    *echte* Zeit nicht widerlegen.
  - `monkeypatch.setattr(modul.asyncio, "sleep", ...)` greift ins Modul
    `asyncio` selbst und entschärft die Mechanik im ganzen Prozess. Patche
    einen Modul-Alias (`_sleep = asyncio.sleep`), nicht das fremde Modul.
- Handgeschriebene Fixtures kodieren die Annahme des Autors und können sie
  nicht widerlegen. Mindestens eine aufgezeichnete Antwort pro externem
  Endpunkt, mit Aufnahmedatum.

## Wenn etwas rot ist
- **Roter Live-Test: erst die Quelle abfragen, dann einordnen.** Nicht aus der
  Fehlermeldung schliessen. Am 3.8.2026 hiess "nicht gefunden" nicht, dass der
  Datensatz weg war, sondern dass die Quelle die Schreibweise ihrer Kopfzeile
  gewechselt hatte — vier von sechs Datensätzen produktiv kaputt, alle
  Unit-Tests grün.
- **PR ohne jeden Check** ist selten ein Repo ohne CI, meistens ein
  Merge-Konflikt: GitHub berechnet dafür keinen Merge-Commit und startet nichts.
- Ein Codex-Review auf einem PR wird **beantwortet oder behoben**, nie ignoriert.

## Repository-Gates
- **Befund:** Weder die Workflows noch eine `.pre-commit-config.yaml` enthalten
  ruff oder eine ruff-Version; die verlangte Versionsübereinstimmung ist daher
  nicht gegeben.
- Exakte Befehle aus `.github/workflows/validate.yml`:
  - `python scripts/validate_data.py`
  - `python -m unittest discover -s tests`
  - `python scripts/eval_claim_prefill.py --min-precision 0.8 --min-evidence-strength-precision 0.7 --min-age-range-precision 0.8 --min-outcome-precision 0.75 --min-context-precision 0.85`
  - `python scripts/eval_skill_links.py --min-abstention 0.85 --min-precision 0.6`
  - `python scripts/build_site.py`
- **Befund (DRIFT-005):** Es gibt keinen geplanten Live-Test-Workflow. Die zwei
  Live-Baseline-Workflows sind nur manuell; Live-Tests werden auch nicht mit
  `-m "not live"` ausgeschlossen.
