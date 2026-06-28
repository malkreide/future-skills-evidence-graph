# Die Such-Allowlist evidenzbasiert zusammenstellen und aktuell halten

*Praxisanleitung: Wie die Liste der vertrauenswürdigen Quell-Domains bei der
Suche entsteht, woher die Belege für ihre Zusammensetzung kommen und wie sie
ohne stilles Veralten nachgeführt wird.*

---

> **Begriffsklärung.** „Allowlist bei der Suche" meint hier die kuratierte Liste
> der **Publisher-Domains**, von denen das Projekt bei der Web-Recherche
> bevorzugt Informationen bezieht – nicht eine Liste von Suchbegriffen und nicht
> die [Future-Skills-„Tierliste"](tierliste-pflegen.md) (das Ranking der
> Kompetenzen).

Das tragende Prinzip ist dasselbe wie überall im Projekt: **keine Empfehlung
ohne Beleg-Pfad.** Auf die Allowlist übertragen heißt das: Eine Domain steht
nicht auf der Liste, *weil sie uns bekannt vorkommt*, sondern weil ein
nachvollziehbarer Beleg ihre Aufnahme stützt – und sie bleibt nur darauf, solange
die Belege das tragen.

---

## Die Allowlist hat zwei Hälften

| Datei | Rolle | Wirkung |
|-------|-------|---------|
| `data/source_domains.json` | **weiche** Trust-Tiers `trusted` / `watch` / `open` | nur **Label**: ordnet das Triage-Arbeitsblatt (vertrauenswürdig zuerst, `open` zuletzt und markiert). Geht **nie** in den `evidence_score` ein. |
| `CREDIBLE_DOMAINS` in `scripts/resolve_source_url.py` | **harte** Open-Web-Allowlist | **Filter**: der URL-Resolver akzeptiert SearXNG-/DuckDuckGo-Treffer nur von diesen Hosts (außer `RESOLVE_OPEN_WEB=1`). |

Beide sind bewusst per Suffix-Match gebaut: `read.oecd.org` zählt zu `oecd.org`.

**Kopplungs-Invariante.** `trusted ∪ watch` ist stets eine **Obermenge** von
`CREDIBLE_DOMAINS` – ein Publisher, der gut genug für den URL-Resolver ist, darf
im Discovery-Lane nie als `open` durchrutschen. Diese Invariante wird durch einen
Test erzwungen (`tests/test_ingest_websearch.py::test_trusted_plus_watch_covers_credible_domains`).

> Wichtig fürs Verständnis: Die Suche selbst ist **nicht** auf die Allowlist
> beschränkt (`ingest_websearch.py` durchsucht das offene Web → gute Recall).
> Die Allowlist *gewichtet* nur, was die Treffer wert sind, und der harte Filter
> greift ausschließlich beim gezielten URL-Resolver. „Allowlist" heißt hier also
> primär *Vertrauens-Kuratierung*, nicht *Ausschluss*.

---

## Teil 1 – Evidenzbasiert zusammenstellen

Die Aufnahme einer Domain stützt sich auf zwei Arten von Belegen – einen
*a-priori*-Beleg (institutioneller Charakter) und einen *empirischen* Beleg
(Track-Record im Projekt).

### A-priori-Kriterien (Warum ein Tier?)

Diese Regeln stehen im `_README` von `data/source_domains.json` und entscheiden,
*in welches* Tier eine Domain gehört:

- **`trusted`** – intergouvernemental / staatlich / offizielle Curricula /
  peer-reviewte Verlage (OECD, UNESCO, EU/Cedefop, EDK, KMK, ERIC, Nature …).
- **`watch`** – seriös, aber mit Interessenlage: Stiftungen, Think-Tanks, NGOs,
  Beratungen, Assessment-Anbieter, Bildungsmedien (Brookings, RAND, Bertelsmann,
  ETS …). Voller Review nötig.
- **`open`** – alles Übrige: bleibt Kandidat, wird aber markiert und ans Ende
  sortiert.

### Empirisches Kriterium (Trägt die Domain ihren Rang?)

Hier kommt die eigentliche Evidenz ins Spiel. Das Projekt zeichnet bereits die
einzige belastbare Wahrheit auf, die zählt: **die Promote-/Reject-Entscheidungen
der Reviewer auf den Quellen** (`promote_candidate.py` → `status: reviewed` bzw.
`rejected`). Daraus lässt sich pro Domain ein Track-Record bilden:

```bash
make audit-domains   # schreibt eval/domain_audit.json (gitignored, read-only)
```

`scripts/audit_domains.py` liest alle Quellen, bündelt sie nach Publisher-Host
und stellt drei Dinge zusammen:

1. **`promotion_candidates`** – bislang `open`-Domains, die mehrfach (≥ 2)
   akzeptiert wurden und eine hohe Akzeptanzrate (≥ 0,6) haben. Sie verdienen –
   belegt durch das Review-Ledger – ein Hochstufen nach `watch`/`trusted` **und**
   die Aufnahme in `CREDIBLE_DOMAINS`.
2. **`review_candidates`** – `trusted`/`watch`-Domains, deren Ledger nur aus
   Rejects besteht (0 akzeptiert, ≥ 2 abgelehnt). Ihr a-priori-Rang ist durch
   die Daten **nicht** gedeckt – ein Mensch sollte ihn prüfen.
3. **`invariant_credible_not_tiered`** – jede `CREDIBLE_DOMAINS`-Domain, die in
   den Tiers fehlt (sollte leer sein; vom Test bewacht).

**Infrastruktur ≠ Publisher.** DOI-/Handle-Resolver und Katalog-Aggregatoren
(`doi.org`, `dx.doi.org`, `semanticscholar.org`, `openalex.org` …) tauchen im
`url`-Feld auf, sind aber bloße Link-Weiterleitungen – nicht der eigentliche
Verlag. Sie als „häufig akzeptiert" hochzustufen würde *jeden* DOI-Link
freischalten und die Allowlist entwerten. `audit_domains.py` markiert sie deshalb
als `infrastructure` und nimmt sie nie in einen Vorschlag (`NON_PUBLISHER_HOSTS`).

> Die Schwellen (`MIN_ACCEPTED_FOR_PROMOTION`, `MIN_ACCEPT_RATE_FOR_PROMOTION`,
> `MIN_REJECTED_FOR_REVIEW`) stehen oben in `scripts/audit_domains.py` und sind
> bewusst konservativ: Das Arbeitsblatt **schlägt vor**, es ändert nichts.

---

## Teil 2 – Aktuell halten (Zyklus)

Die Allowlist wird im selben Rhythmus wie der Kandidaten-Review gepflegt
(Runbook: [OPERATIONS.md](../OPERATIONS.md)).

1. **Belege sammeln.** Im wöchentlichen Review werden Quellen mit
   `promote-source` / `reject-source` entschieden – das füllt automatisch den
   Track-Record jeder Domain.
2. **Audit fahren.** `make audit-domains` ausführen und `eval/domain_audit.json`
   lesen: Welche `open`-Domain hat sich Vertrauen verdient? Welche Tier-Domain
   liefert nur Ausschuss?
3. **Per PR entscheiden.** Vorschläge sind nur Leads. Eine echte Änderung ist
   immer ein **Pull Request**, der beide Hälften synchron hält:
   - Domain in `data/source_domains.json` ins passende Tier eintragen
     (`trusted` für offizielle/peer-reviewte, sonst `watch`), und
   - bei `watch`/`trusted` denselben Host in `CREDIBLE_DOMAINS`
     (`scripts/resolve_source_url.py`) aufnehmen.
   Das Arbeitsblatt liefert den `edit_hint` pro Domain wörtlich mit.
4. **Prüfen.** `python -m unittest discover -s tests` – der Superset-Test hält
   die Kopplungs-Invariante grün, bevor gemergt wird.

Off-cycle ergänzend: Wird über die [Web-Search-Discovery](report-import.md)
oder einen eingereichten Bericht wiederholt ein neuer seriöser Publisher
sichtbar, kann er direkt per PR (mit kurzer Begründung) aufgenommen werden –
auch das ist ein a-priori-Beleg.

---

## Die drei Hebel für „ehrlich aktuell"

- **Belegt statt behauptet.** Aufnahme/Abwahl stützt sich auf das Review-Ledger,
  nicht auf Bauchgefühl. `make audit-domains` macht den Beleg reproduzierbar.
- **Mensch im Loop.** Das Audit *schlägt vor*; aufgenommen/entfernt wird nur per
  PR. Bewusste Zurückhaltung gegen Über-Automatisierung.
- **Invariante erzwungen.** Ein Test hält die weiche und die harte Liste
  gekoppelt – die Allowlist kann nicht still inkonsistent werden.

---

## Checkliste vor jedem Allowlist-PR

- [ ] Jede neue Domain hat einen Beleg: a-priori (institutioneller Charakter)
      **oder** empirisch (≥ 2 akzeptierte Quellen, hohe Rate aus `audit-domains`).
- [ ] Keine Infrastruktur-/Resolver-Domain (`doi.org` & Co.) aufgenommen.
- [ ] `watch`/`trusted`-Domain auch in `CREDIBLE_DOMAINS` gespiegelt
      (Superset-Invariante).
- [ ] Eine Domain steht in genau **einem** Tier (Tiers sind disjunkt).
- [ ] `python -m unittest discover -s tests` ist grün (Superset- + Audit-Tests).

> Verwandte Dokumente: [OPERATIONS.md](../OPERATIONS.md) ·
> [tierliste-pflegen.md](tierliste-pflegen.md) ·
> [report-import.md](report-import.md) ·
> [relevanz-entscheidung.md](relevanz-entscheidung.md)
