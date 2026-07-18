# Remediation-Plan: Future Skills Evidence Graph — Stand 2026-07-18

**Basis:** [Audit-Report 2026-07-18](reports/2026-07-18-audit.md) · Score: **79/100**
(26/26 verifiziert) · Ziel: **≥ 90, null offene critical/high**

## Spielregeln

- Ein Finding = ein Commit, Message-Format: `fix(<kategorie>): <beschreibung> [<CHECK-ID>]`
- Nach jedem Fix: Checkbox abhaken, Finding-Status auf `in-remediation`
- `accepted-risk` nur mit Begründung im Finding

## Welle 1 — Release-Blocker (alle high, Effort S) — bringt den Score über ~90

- [ ] **A11Y-002** Fokus-Indikator (high, S) — [Finding](findings/2026-07-18-A11Y-002.md)
      Erster Schritt: in `architektur.css:56-60` das `outline: none` auf `.arch-tab:focus-visible`
      entfernen; in `submit.css:65-70` den 25%-Outline durch `2px solid var(--focus)` ersetzen.
- [ ] **A11Y-004** Skip-Link (high, S) — [Finding](findings/2026-07-18-A11Y-004.md)
      Erster Schritt: den `.skip-link` aus `index.html:41` in `einreichen.html` und
      `architektur.html` einsetzen, Ziel-`id` auf `<main>` (`tabindex="-1"`).
- [ ] **A11Y-006** Formular-Fehlerzuordnung (high, S–M) — [Finding](findings/2026-07-18-A11Y-006.md)
      Erster Schritt: `#urlInput` um `required`/`aria-required`/`aria-describedby` ergänzen,
      in `submit.js onSubmit()` bei Fehler `aria-invalid="true"` setzen + Hint referenzieren.
      ⚠ Gemeinsam mit USE-005 umsetzen (dieselben URL-/Jahr-Felder).

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
