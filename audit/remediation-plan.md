# Remediation-Plan: Future Skills Evidence Graph — Stand 2026-07-18

**Basis:** [Audit-Report 2026-07-18](reports/2026-07-18-audit.md) · Score: **79/100**
(26/26 verifiziert) · Ziel: **≥ 90, null offene critical/high**

## Spielregeln

- Ein Finding = ein Commit, Message-Format: `fix(<kategorie>): <beschreibung> [<CHECK-ID>]`
- Nach jedem Fix: Checkbox abhaken, Finding-Status auf `in-remediation`
- `accepted-risk` nur mit Begründung im Finding

## Welle 1 — Release-Blocker (alle high, Effort S) — ✅ umgesetzt & browser-verifiziert 2026-07-18

- [x] **A11Y-002** Fokus-Indikator (high, S) — [Finding](findings/2026-07-18-A11Y-002.md)
      `architektur.css`: `outline:none` auf `.arch-tab:focus-visible` entfernt; `submit.css`:
      Fokusring auf `2px solid var(--focus)`. Verifiziert: arch-Tab & URL-Feld fokussiert →
      `solid 2px rgb(49,95,159)`. Commit `0ce25fe`.
- [x] **A11Y-004** Skip-Link (high, S) — [Finding](findings/2026-07-18-A11Y-004.md)
      Skip-Link + `<main id="hauptinhalt" tabindex="-1">` auf `einreichen.html` und
      `architektur.html`. Verifiziert: Skip-Link auf allen 3 Seiten, Ziel fokussierbar.
      Commit `af90407`.
- [x] **A11Y-006** Formular-Fehlerzuordnung (high, S–M) — [Finding](findings/2026-07-18-A11Y-006.md)
      `#urlInput` mit `required`/`aria-required`/`aria-describedby`; `submit.js` setzt bei
      Fehler `aria-invalid="true"` + `aria-describedby="urlHint submitHint"`, Reset bei
      gültiger Eingabe. Verifiziert im Browser. Commit `fa227c0`.
      ⚠ Rest von USE-005 (Jahr-Constraint, `<form>`, Inline-URL-Prüfung) bleibt offen für Welle 2.

## Welle 2 — Restliche medium

- [ ] **USE-005** Inline-Validierung + Jahr-Constraint (medium, S) — [Finding](findings/2026-07-18-USE-005.md)
      Block in `<form>` heben, `pattern` aufs Jahr, URL vor Issue-Öffnen prüfen.
- [ ] **A11Y-003** Architektur-SVG benennen (medium, S) — [Finding](findings/2026-07-18-A11Y-003.md)
      `<title>`/`<desc>` + `aria-labelledby` auf `#archSvg`, im View-Wechsel mitschreiben.
- [ ] **A11Y-010** Nav-Link-Zielgrösse (medium, S) — [Finding](findings/2026-07-18-A11Y-010.md)
      `.nav-link` in `styles.css:142` auf `min-height: 44px` (padding-block) heben.
- [ ] **USE-009** Eigene 404-Seite (medium, S) — [Finding](findings/2026-07-18-USE-009.md)
      `site/404.html` im Site-Stil anlegen, in `build_site.py` nach `public/` kopieren.
- [ ] **PERF-004** index.json nicht doppelt laden (medium, S–M) — [Finding](findings/2026-07-18-PERF-004.md)
      `status.js loadGenerated()` nicht die volle JSON erneut laden lassen.

## Welle 3 — low / Polish

- [ ] **PERF-005** `no-cache` statt `no-store` für Katalog-Fetch (low, S) — [Finding](findings/2026-07-18-PERF-005.md)
      + manuelle Prüfung der Prod-Cache-/Kompressions-Header auf der Live-URL.

## Nicht angegangen (accepted-risk)

| Check | Begründung | Entschieden von | Datum |
|---|---|---|---|
| | | | |

---

**Prognose:** Welle 1 (3× high, alle S/S–M) hebt A11Y von 73 auf ~90+ und
entfernt alle Release-Blocker → **Score ≈ 91, release-ready**. Welle 2+3 bringen
den Score Richtung 96+.

**Nach Welle 1 (+ optional 2):** Re-Audit auslösen (Phase C im ux-audit-Skill) —
alle partial-Checks re-verifizieren + Regressionsstichprobe (bevorzugt A11Y +
das Einreichungsformular, weil dort CSS/Markup angefasst wird).
