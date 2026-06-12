# Methodik: Lehrplan-21-Coverage-Bewertung

Dieses Dokument beschreibt, wie die `coverage_score`-Werte (0–3) der
Lehrplan-21-Mappings in `data/frameworks/lehrplan21.json` zustande kommen.
Die Scores sind **redaktionelle Urteile**, keine empirisch gemessenen Werte.
Im Sinne des Projektprinzips — keine Aussage ohne nachvollziehbaren
Evidenzpfad — wird hier offengelegt, wer wie bewertet hat und wo die
Grenzen der Methode liegen.

## Wer bewertet

Die Erstbewertung (Stand `created_at: 2026-04-28`) wurde von den
Projekt-Maintainern als redaktionelle Einzelbewertung vorgenommen. Es gab
**kein Inter-Rater-Verfahren**; die Werte spiegeln das Urteil einer
Redaktion, nicht einen Konsens mehrerer unabhängiger Bewertenden.
Änderungen laufen wie alle Daten über Pull Requests und werden dort
begründet und reviewt.

## Was bewertet wird

Für jeden aktiven Future Skill wird eingeschätzt, wie gut der
[Lehrplan 21](https://www.lehrplan21.ch/) die Kompetenz **heute explizit
abdeckt** — nicht, ob sie sich in den Lehrplan hineininterpretieren ließe.
Bewertungsgrundlage sind die öffentlich zugänglichen Lehrplantexte, primär:

- der Modullehrplan **Medien und Informatik**,
- die **überfachlichen Kompetenzen** (personale, soziale, methodische).

Die konsultierte Stelle ist pro Mapping in `framework_url`, `competency`
und `curriculum_area` dokumentiert; `rationale` fasst das Urteil zusammen,
`evidence_path` verbindet es mit der Evidenzbasis des Skills.

## Skala

Der `coverage_score` ist eine Zahl von 0 bis 3 mit einer Dezimalstelle.
In das Urteil fließen drei Fragen ein:

1. **Explizitheit:** Wird die Kompetenz im Lehrplantext ausdrücklich
   benannt, oder ist sie nur implizit angelegt?
2. **Breite:** Über wie viele Zyklen (`cycles`) und Fachbereiche ist die
   Kompetenz verankert?
3. **Zukunftsschärfe:** Deckt der Lehrplan auch die zukunftsgerichteten
   Aspekte des Skills ab (z. B. generative KI bei AI Literacy), oder nur
   den klassischen Kern?

Ankerpunkte der Skala:

| Score | Bedeutung |
| --- | --- |
| 0 | Keine erkennbare Verankerung im Lehrplan |
| 1 | Nur implizit oder punktuell angelegt |
| 2 | Klar angelegt, aber mit Lücken in Explizitheit, Breite oder Zukunftsschärfe |
| 3 | Explizit, über mehrere Zyklen verankert und inhaltlich aktuell |

## Ableitung des Labels

Das `coverage_label` ist **deterministisch** aus dem Score abgeleitet und
kein eigenständiges Urteil:

| Score | Label |
| --- | --- |
| ≥ 2.4 | `gut abgedeckt` |
| ≥ 1.5 und < 2.4 | `teilweise` |
| < 1.5 | `Zukunftsluecke` |

Die Schwellen sind in `scripts/common.py` (`lp21_coverage_label`) definiert
und werden vom Dashboard (`site/assets/app.js`) gespiegelt.
`scripts/validate_data.py` prüft, dass gespeicherte Labels mit den
Schwellen übereinstimmen. (Die Schreibweise `Zukunftsluecke` ohne Umlaut
ist beabsichtigt: die Datendateien sind ASCII-kodiert.)

## Grenzen und geplante Verbesserungen

- Die Scores sind subjektive Einschätzungen einer einzelnen Redaktion.
  Eine Zweitbewertung mit Abgleich (Inter-Rater-Reliabilität) steht aus.
- Die Bewertung bezieht sich auf den kantonsübergreifenden Vorlagentext
  des Lehrplan 21; kantonale Anpassungen und gelebte Unterrichtspraxis
  sind nicht erfasst.
- Die Dezimalstellen suggerieren mehr Präzision, als ein redaktionelles
  Urteil hergibt; belastbar ist vor allem die Label-Stufe.

Korrekturen und Zweitmeinungen sind ausdrücklich erwünscht: bitte als
Pull Request oder Issue mit Verweis auf die konkrete Lehrplanstelle.
