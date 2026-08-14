# Methodik: Ankerdefinitionen der Evidenzbewertung

Dieses Dokument legt offen, was die Zahlen und Stufen der Evidenzbewertung
bedeuten: was `evidence_certainty` misst und was ausdrücklich nicht, warum
jeder `source_type` das Gewicht trägt, das er trägt, und unter welchen
Regeln diese Festlegungen geändert werden dürfen.

Der Anlass ist ein Vergleich mit [kurate.org](https://kurate.org/), das
wissenschaftliche Preprints über 16 Dimensionen bewertet. Dessen
methodisch stärkster Zug ist nicht die Zahl der Dimensionen, sondern dass
jede Skala **verankert** ist: der Bewertungs-Prompt sagt ausdrücklich, was
eine 1, was eine 5 und was eine 10 bedeutet.

Die Gewichte sind **redaktionelle Urteile**, keine gemessenen Größen. Was
sie leisten, ist Konsistenz zwischen Reviewenden — nicht Wahrheit.

## Was `evidence_certainty` beantwortet

> **Wie sicher können wir auf Basis der vorhandenen wissenschaftlichen
> Evidenz sein, dass die konkret formulierte Aussage gestützt wird?**

Nicht: „Wie gross ist der Effekt?" Das ist `effect_magnitude`.
Nicht: „Wie positiv ist er?" Das ist `effect_direction`.
Nicht: „Wie angesehen ist die Quelle?" Das ist `source_type`.

Die Vorgängervariable `evidence_strength` beantwortete alle diese Fragen
gleichzeitig mit einem Wert. Das ging so lange gut, wie sie in dieselbe
Richtung zeigten, und riss auseinander, sobald nicht: **ein sauber
durchgeführtes Experiment mit Nullbefund ist starke Evidenz dafür, dass
kein Unterschied nachweisbar war** — auf der alten Skala hiess „kein
signifikanter Unterschied" praktisch immer `low`.

Das ist keine hypothetische Sorge. Im Goldset trug
`prefill-handwriting-tablet` („Both groups improved legibility, with no
significant difference between conditions") den Wert `low`, und zwar
erkennbar wegen des Nullbefunds — ein gleichartiger Vergleich mit
positivem Ergebnis trug `moderate`.

## Die Dimensionen und wofür sie zuständig sind

| Feld | Beantwortet | Beantwortet **nicht** |
| --- | --- | --- |
| `source_type` | In welcher Publikationsform steht das? | Wie gut die Studie ist. |
| `study_design` | Welches methodische Design wird beschrieben? | In welchem Journal es erschien. |
| `evidence_certainty` | Wie sicher ist die Aussage gestützt? | Wie gross oder wie positiv der Effekt ist. |
| `effect_direction` | In welche Richtung geht der Befund? | Wie belastbar er ist. |
| `effect_magnitude` | Wie gross ist er? | Ob er real ist. |
| `claim_supported_by_source` | Sagt die Quelle, was die Aussage behauptet? | Wie gut die Quelle ist. |
| `source_verified` / `source_provenance` | Lässt sich die Quelle überhaupt auffinden? | Ob die Aussage stimmt. |

Die Trennung von `source_type` und `study_design` ist der Kern. Ein
`systematic_review` **als Publikationstyp** sagt nichts darüber, ob die
gepoolten Primärstudien etwas taugten. Deshalb geht `source_type` in die
Herleitung von `evidence_certainty` **gar nicht ein** — nachgewiesen durch
`test_source_type_never_reaches_the_derivation`.

## Anker: `evidence_certainty`

| `strong` | Der konkrete Claim wird durch hochwertige, direkte und ausreichend präzise Evidenz gestützt: mehrere konsistente hochwertige Studien oder eine hochwertige Synthese, angemessenes Design für die behauptete Kausalität, dokumentiert geringes Bias-Risiko, ausreichende Präzision, und Population/Intervention/Vergleich/Outcome passen direkt zum Claim. |
| `moderate` | Glaubwürdige empirische Grundlage mit relevanten Einschränkungen: eine einzelne randomisierte Studie ohne Replikation, eine Synthese ohne belegte Qualitätsprüfung, begrenzter Kontext, oder verbleibende Unsicherheit über das Bias-Risiko. |
| `low` | Deutlich eingeschränkte Grundlage: kontrolliert, aber nicht randomisiert; erhebliche Confounds möglich; schwache Vergleichsbedingung; oder eine Synthese, die durch Heterogenität oder methodische Mängel herabgestuft wurde. |
| `very_low` | Kein Design, das den behaupteten Effekt isolieren kann: unkontrolliertes Pre-Post, Einzelfall ohne Replikation, deskriptive oder explorative Daten, Fallberichte — oder ein Dokument, das gar keine eigenen Ergebnisse misst. |
| `unverifiable` | Die behauptete Quelle lässt sich mit den vorhandenen Angaben nicht identifizieren. Das ist **keine** Aussage darüber, ob der Claim stimmt, sondern darüber, dass seine Herkunft nicht prüfbar ist. |

`unverifiable` liegt bewusst **nicht** auf der Ordinalskala. Es ist nicht
„noch schwächer als very_low", sondern eine Aussage über
Nachvollziehbarkeit statt über Stärke. Für die Interrater-Statistik heisst
das: es zählt in die rohe Übereinstimmung und in Cohens Kappa, aber ein
Paar, das es enthält, trägt keine ordinale Distanz und fällt aus dem
gewichteten Kappa heraus (die Anzahl wird ausgewiesen).

## Zuerst: Was für eine Aussage ist das?

`claim_type` steht vor allem anderen, weil die Design-Leiter unten genau
**eine** Frage beantwortet: *Kann dieses Design eine Ursache isolieren?*
Das ist nur dann die richtige Frage, wenn die Aussage eine Ursache
behauptet.

| `claim_type` | Beispiel | Pfad |
| --- | --- | --- |
| `causal_effect` | „Die Intervention verbessert das Lernen." | Design-Leiter |
| `association` | „Digitalkompetenz hängt mit KI-Kompetenz zusammen." | Eignung |
| `descriptive` | „Eltern berichteten vier Schwierigkeiten." | Eignung |
| `normative` | „Kinder brauchen altersgerechtes Verständnis." | Eignung |
| `definitional` | „Digitalkompetenz umfasst Informationskompetenz." | Eignung |

Eine definitorische Aussage danach zu bewerten, ob sie randomisiert hat,
ist ein Kategorienfehler — und die Antwort `very_low` würde diesen Fehler
als Befund ausweisen. Bei der Anwendung auf den Produktivkatalog stellte
sich heraus, dass nur **14 von 59** geprüften Aussagen überhaupt eine
Wirkung behaupten. Ohne diese Unterscheidung wären rund vierzig Aussagen
`very_low` geworden, und der Grund dafür wäre eine Frage gewesen, die
niemand gestellt hat.

### Der Eignungspfad

Für Aussagen ohne Wirkungsbehauptung lautet die Frage nicht „konnte das
Design eine Ursache isolieren", sondern **„ist die Quelle eine kompetente
Zeugin für das, was die Aussage beschreibt?"** Ein Referenzrahmen ist die
Primärquelle für seinen eigenen Inhalt; eine Interviewstudie hat die
Wahrnehmungen, die sie berichtet, tatsächlich erhoben; neun
Länder-Fallstudien haben diese Lehrpläne tatsächlich angesehen. Das trägt
`directness`, und deshalb setzt dort sie die Baseline:

| `directness` | Baseline |
| --- | --- |
| `direct` | `moderate` |
| `partially_direct` | `low` |
| `indirect` | `very_low` |
| nicht erfasst | **keine** — Ergebnis `null` |

Auf diesem Pfad wird `directness` **nicht** zusätzlich abgewertet (sie hat
die Baseline schon gesetzt), und `comparator: historical_control` bleibt
folgenlos — eine Aussage ohne Wirkungsbehauptung hat keine
Vergleichsbedingung, die falsch sein könnte. Alles andere (Bias,
Inkonsistenz, Präzision, `claim_supported_by_source`) wirkt unverändert.

Die Aufwertung verlangt hier **keine** dokumentierte Bias-Prüfung: Eine
deskriptive Arbeit berichtet praktisch nie eine, und sie zu verlangen
machte die Aufwertung für die halbe Katalogseite unerreichbar — das wäre
eine Regel über Papierkram, nicht über Evidenz. Konsistenz über
Replikationen oder Kontexte bleibt Bedingung, und die tut die Arbeit.

## Wie die Herleitung funktioniert — und warum sie kein Punktesystem ist

`derive_certainty()` in `scripts/appraisal.py` startet bei dem, was das
**Design** hergibt, und wendet dann **benannte** Auf- und Abwertungen an.
Das ist die Logik von GRADE, angepasst an eine kleinere Einheit: GRADE
bewertet einen Evidenzkörper und startet randomisierte Designs bei „hoch";
hier steht eine einzelne Aussage mit oft einer einzelnen Studie, deshalb
starten die Baselines eine Stufe tiefer und `strong` muss durch Replikation
oder Synthese **verdient** werden.

| `study_design` | Baseline | Begründung |
| --- | --- | --- |
| `systematic_review`, `meta_analysis` | `moderate` | Eine Synthese ist so gut wie das, was sie gepoolt hat. |
| `narrative_review` | `very_low` | Kein offengelegtes Suchprotokoll, keine eigenen Primärdaten. |
| `psychometric_validation` | `very_low` | Geeignet für eine Validitätsaussage, ungeeignet für eine Wirkungsaussage. |
| `rct`, `cluster_rct` | `moderate` | Kausale Zuschreibung ist prinzipiell verfügbar. |
| `quasi_experimental`, `matched_comparison`, `controlled_pre_post`, `cohort` | `low` | Vergleich vorhanden, Confounding nicht ausgeschlossen. |
| `consensus_framework` | `low` | Belegt, worauf sich ein Feld geeinigt hat — nicht, dass es wirkt. |
| `uncontrolled_pre_post`, `cross_sectional`, `single_case`, `qualitative`, `descriptive` | `very_low` | Keine Vergleichsbedingung: Reifung, Regression zur Mitte und Testeffekte sind nicht trennbar. |
| `policy_report`, `working_paper` | `very_low` | Misst keine eigenen Lernergebnisse. |
| `other`, `unknown` | **keine** | Ergebnis ist `null` (unbekannt), nicht „schwach". |

Abwertungen (je eine Stufe, ausser wo vermerkt):

- `risk_of_bias: high` — −1
- Inkonsistenz — −1, **einmal**: `consistency: inconsistent` **oder**
  `heterogeneity: high`. Beides zu zählen bestrafte eine Review dafür,
  mehr offengelegt zu haben.
- `precision: imprecise` — −1
- `comparator: historical_control` — −1. Ein früherer Jahrgang ist keine
  Kontrollgruppe; alles andere, was sich zwischen den Jahren geändert hat,
  fährt mit.
- `directness: partially_direct` — −1, `indirect` — −2
- `claim_supported_by_source: partially_supported` — −1

Aufwertung (höchstens eine, und nur ohne Abwertung): Replikation über
mehrere Studien oder Kontexte **und** `consistency: consistent` **und**
`risk_of_bias: low`. Replikation bei hohem Bias-Risiko ist Replikation des
Bias.

Harte Grenzen: `claim_supported_by_source: not_supported` deckelt bei
`very_low`; `cannot_determine` ergibt `null`; eine nicht identifizierbare
Quelle ergibt `unverifiable`, bevor irgendetwas anderes geprüft wird.

**Kein Punktesystem.** Es gibt kein „RCT = +5, n > 200 = +2". Jeder
Schritt hat einen Namen und eine Begründung, und `derive_certainty` gibt
die Begründungen mit zurück. Mit einer Begründung kann eine Reviewende
streiten; mit einer 7,4 kann niemand streiten.

**Die Herleitung ist beratend.** Der gespeicherte Wert ist ein Urteil.
`certainty_conflicts()` prüft nur, was ein Urteil **nicht** tun darf — dort
sitzen die Guardrails, und nur die sind für `validate_data.py` Fehler.

### Warum `precision` nicht aus `sample_size` folgt

`sample_size` ist deskriptiv und geht in keine Regel ein. „n > 200, also
präzise" sieht objektiv aus und ist es nicht: Präzision hängt von der
Streuung des Outcomes und vom geschätzten Effekt ab, und beides trägt eine
Fallzahl nicht. `precision` ist deshalb ein eigenes Urteilsfeld mit
`unknown` als Normalfall.

## Grenzfälle

Die Fälle, an denen sich die Trennung entscheidet. „Felder" nennt jeweils
die, die den Ausschlag geben.

**1. Hochwertiges RCT mit positivem Effekt.** `study_design: rct`,
`risk_of_bias: unknown`, `replication: single_study` → **`moderate`**.
Nicht `strong`: eine Einzelstudie ohne Replikation und ohne dokumentierte
Bias-Prüfung. Katalogfall: `prefill-worked-examples-math`.

**2. Hochwertiges RCT mit Nullbefund.** `study_design: rct`,
`effect_direction: null`, `precision: adequate` → **`moderate`**. Identisch
zu Fall 1. `effect_direction` geht in die Herleitung **nicht** ein; ein
sauber gemessener Nullbefund ist gleich sicher wie ein sauber gemessener
positiver. Im Goldset gibt es diesen Fall nicht (siehe „Lücken").

**3. Kleines Quasi-Experiment.** `study_design: quasi_experimental`,
`precision: imprecise` → `low` −1 = **`very_low`**. Katalogfall:
`prefill-music-cognition` (48 Kinder, „small and not randomised").

**4. Pre-Post ohne Kontrollgruppe.** `study_design:
uncontrolled_pre_post`, `comparator: none` → **`very_low`**. Verbesserung
nach einer Massnahme heisst nicht, dass die Massnahme sie verursacht hat.
Katalogfall: `prefill-financial-literacy-secondary` (180 Lernende, Pre-Post
ohne Kontrolle).

**5. Single-Case Multiple Baseline.** `study_design: single_case`,
`outcome_type: behavioural` → **`very_low`**. Innerhalb der Person
sorgfältig, ohne externe Replikation nicht verallgemeinerbar. Katalogfall:
`prefill-adhd-selfmonitor`.

**6. Systematischer Review mit konsistenten Ergebnissen.**
`study_design: systematic_review`, `consistency: consistent`,
`risk_of_bias: unknown` → **`moderate`**. Für `strong` fehlt die
dokumentierte Bias-Prüfung. Katalogfall: `prefill-phonics-reception` (28
Trials, „consistently", „robust across languages") — der stärkste Fall im
Set, und er erreicht `strong` nicht.

**7. Systematischer Review mit hoher Heterogenität.**
`heterogeneity: high` → `moderate` −1 = **`low`**. Katalogfall:
`prefill-self-regulation-elementary` (32 Studien, „Heterogeneity across
studies was high").

**8. Review mit methodisch schwachen Primärstudien.**
`risk_of_bias: high` → `moderate` −1 = **`low`**. Katalogfall:
`prefill-mindset-intervention` („Many studies had methodological
limitations. The authors urge cautious interpretation.").

**9. Policy Report ohne neue empirische Daten.**
`study_design: policy_report`, `effect_direction: not_applicable` →
**`very_low`**. Die normative Empfehlung ist real und die Quelle trägt sie
(`claim_supported_by_source: supported`) — als *empirischer* Beleg für eine
Lernwirkung ist sie es nicht. Katalogfall: `prefill-policy-ai-ethics`.

**10. Working Paper ohne Learning Outcomes.**
`study_design: working_paper` → **`very_low`**. Eine Architektur- oder
Designbeschreibung ist keine Evidenz für Lernwirksamkeit. Katalogfälle:
`prefill-chatbot-design-null`, `prefill-robotics-club`,
`prefill-stem-camp-null`.

**11. Self-Report-Outcome.** `outcome_type: self_report`. **Für sich
genommen keine Abwertung.** Entscheidend ist, was der Claim behauptet: Sagt
er „reported higher empathy", ist das direkt (`directness: direct`); sagt
er „improved competence", ist es das nicht (`partially_direct`, −1).
Katalogfall: `prefill-vr-empathy` — der Claim benennt die Selbstauskunft
ausdrücklich, die Abwertung kommt allein vom unkontrollierten Design.

**12. Objektives standardisiertes Outcome.**
`outcome_type: standardized_objective` ist keine Aufwertung. Ein
standardisierter Test in einem unkontrollierten Design misst präzise, was
ohne Vergleichsbedingung nicht zugeordnet werden kann. Katalogfall:
`prefill-creativity-design` (standardisierte Kreativitätsrubrik,
quasi-experimentell, n = 84 → `very_low`).

**13. Synthetische Quelle.** `source_provenance: synthetic_eval_case`. Wird
nach dem **beschriebenen** Design bewertet — das ist ihr Zweck — und trägt
die Markierung mit, damit sie nirgends als reale Publikation gilt.
`validate_data.py` weist eine so markierte Claim in `data/claims/`
zurück. Alle 50 Fälle in `eval/claim_prefill_labeled.json` sind solche
Fälle.

**14. Nicht verifizierbare Quelle.** `source_verified: false` **und**
`source_provenance: unverified_source` → **`unverifiable`**, vor jeder
weiteren Prüfung. Nicht „falsch", sondern „Herkunft nicht prüfbar".

**15. Claim stärker als die Quelle.** Quelle: „Students improved from pre-
to post-test in an uncontrolled study." Claim: „The intervention improves
learning." → `claim_supported_by_source: partially_supported` (−1), weil
die kausale Wirkung nicht isoliert wurde. Ebenso: Quelle „Participants
reported higher confidence", Claim „The intervention improved competence" —
Selbstauskunft ist nicht Kompetenz.

**16. Explizite Altersangabe.** Quelle: „aged 22 to 55" →
`age_range_explicit: "22-55"`. Katalogfälle: `prefill-adult-mooc`,
`prefill-adult-digital-literacy`.

**17. Nur Schulstufe ohne Altersangabe.** Quelle: „11th-grade students" →
`age_range_explicit: null`, `grade_or_stage: "11th grade"`. **Nicht**
`16-17`. Katalogfall: `prefill-physics-simulations`.

## Alter: gemeldet, abgeleitet, oder gar nicht

Die frühere Regel — genannte Schulstufe ergibt die „übliche Altersspanne" —
ist entfernt. Sie ist international nicht tragfähig: `primary`,
`elementary`, `middle school`, `secondary`, `lower/upper secondary` decken
je nach Land verschiedene Jahre ab.

Das Repository hat den Beleg dafür bereits selbst produziert. Der
Prefill-Prompt **v5** versuchte genau diese Zuordnung, um den Recall zu
heben; der Live-Lauf zeigte breite Stufenbänder statt der engeren
Studienbänder, und die `age_range`-**Precision fiel von 0,94 auf 0,82**
(dokumentiert in `scripts/extract_claims.py`). v6 nahm die Regel zurück.

Drei getrennte Felder:

- `age_range_explicit` — **nur** im Text genannte Alterswerte.
- `grade_or_stage` — die Stufenbezeichnung, so wie sie dasteht.
- `age_range_inferred` + `age_inference_basis` — eine abgeleitete Spanne
  ist erlaubt, aber nur in ihrem eigenen Feld und nur mit ihrer Grundlage.
  `validate_appraisal()` weist eine abgeleitete Spanne ohne Grundlage
  zurück; ohne diese Kopplung wäre sie von einer gemeldeten nicht mehr zu
  unterscheiden.

### Was die Umstellung am Goldset sichtbar machte

| | alt (`age_range`) | neu (`age_range_explicit`) |
| --- | --- | --- |
| Fälle mit gesetztem Wert | 43 von 50 | 2 von 50 |
| davon mit im Text genannter Altersangabe | **0** | 2 |

Das alte Feld war nicht ungenau, sondern **invertiert**: keiner seiner 43
Werte stand im Abstract, und die beiden Fälle, die tatsächlich Alter nennen
(„aged 22 to 55", „aged 25 to 55"), trugen `null` — sie fielen aus der
0-18-Skala der Pipeline. Ein Feld, das genau dort schweigt, wo die Quelle
spricht, und genau dort spricht, wo sie schweigt.

## Anker: `source_type`

Die Reihenfolge folgt einer Frage: **Wie viel unabhängige Prüfung liegt
zwischen einer Einzelbeobachtung und dem, was hier steht?**

| `source_type` | Gewicht | Begründung |
| --- | --- | --- |
| `systematic_review` | 1,0 | Aggregiert Primärstudien nach einem vorab festgelegten, offengelegten Verfahren. Höchste Prüfdichte. |
| `framework` | 0,85 | Referenzrahmen (Lehrplan 21, DigComp, UNESCO AI CF). Nicht empirisch, aber konsentiert, öffentlich verantwortet und für dieses Projekt normativ verbindlich. |
| `peer_reviewed_article` | 0,8 | Externe Fachprüfung einer Einzelstudie. |
| `book` | 0,75 | Redaktionell geprüft und in der Regel breiter kontextualisiert, aber ohne durchgängiges Peer-Review-Verfahren. |
| `policy_report` | 0,7 | Institutionell verantwortet und meist qualitätsgesichert, aber mit einem Auftrag geschrieben; die Belegtiefe schwankt stark. |
| `conceptual_review` | 0,65 | Ordnet ein Feld, ohne ein systematisches Suchprotokoll offenzulegen. |
| `working_paper` | 0,45 | Noch nicht extern geprüft. |
| `dataset` | 0,4 | Trägt Daten, aber keine geprüfte Interpretation. Derzeit im Katalog nicht belegt. |
| `web_resource` | 0,25 | Keine erkennbare externe Prüfung. Derzeit im Katalog nicht belegt. |

Diese Gewichte bilden die **Publikationsform** ab und sind die 60 % des
Claim-Scores. Sie sind ausdrücklich **kein** Qualitätsurteil über die
Studie — dafür ist `evidence_certainty` zuständig, und dass beide getrennt
bleiben, ist die Voraussetzung der Formel (siehe „Warum 60/40").

## Die Formel

Ein Claim-Score besteht zu 60 % aus der Quellenqualität (`source_type`)
und zu 40 % aus der Claim-Komponente. Die Claim-Komponente liest
`appraisal.evidence_certainty`, wenn die Claim begutachtet ist, und fällt
sonst auf die alte `evidence_strength` zurück.

| Stufe | Gewicht |
| --- | --- |
| `strong` | 1,0 |
| `moderate` | 0,7 |
| `low` | 0,35 |
| `very_low` | 0,15 |
| `unverifiable` | **kein Gewicht** — die Claim ist nicht bewertbar |

Der Skill-Score ist der Mittelwert seiner geprüften Claim-Scores, skaliert
um einen Breitenfaktor (voll ab `BREADTH_SATURATION` = 6 unabhängigen
Claims, Untergrenze `BREADTH_FLOOR` = 0,85) und vermindert um
`CONTRADICTION_PENALTY` = 0,1 je widersprechendem Claim.

### Legacy: `evidence_strength`

| Stufe | Gewicht | Definition (historisch) |
| --- | --- | --- |
| `strong` | 1,0 | Systematisch erhobene Evidenz über mehrere Studien, Länder oder Kohorten — oder konsentierte Festlegung eines Referenzrahmens. |
| `moderate` | 0,7 | Konkrete, aber begrenzte empirische Grundlage. |
| `low` | 0,35 | Plausibel und korrekt entnommen, aber deskriptiv oder normativ. |

Diese Stufen bleiben lesbar und behalten exakt ihre bisherigen Gewichte.
Sie werden **nicht** automatisch in `evidence_certainty` übersetzt: ein
altes `moderate` kann eine Einzelkontextstudie, einen gemischten Befund
oder ein zurückhaltendes Urteil bedeutet haben. `migrate_legacy()`
überträgt deshalb nur, was der alte Datensatz zuverlässig trägt, und lässt
`evidence_certainty` auf `null` — unbekannt, bis jemand begutachtet.

## Unbekannt ist nicht schwach

Der zweite übernommene Zug von kurate.org: dort bekommt eine Dimension,
deren Voraussetzung nicht erfüllt ist, ausdrücklich `null` statt einer
erzwungenen Zahl — ein Bewertungslauf, der Werte erfindet, gilt als
Fehler.

Seit `METHOD_VERSION` 1.0.0 gilt: `claim_score()` gibt **`None`** zurück,
wenn eine Claim keine Quelle hat, eine Quelle nicht auflösbar ist, ein
`source_type` kein Gewicht besitzt oder die Claim-Komponente keine
verankerte Stufe ist. Seit 1.2.0 zählt `evidence_certainty:
unverifiable` dazu. `None` heisst „nicht bewertbar", nicht „schwach".
`validate_data.py` macht daraus bei geprüften Claims einen **Fehler**.

Dieselbe Regel gilt beim Begutachten: Wenn der Text es nicht hergibt, ist
`unknown` bzw. `null` die richtige Antwort. Aus dem typischen Verlauf eines
Designs auf eine Eigenschaft zu schliessen, ist eine Erfindung — ein Text,
der sich `systematic_review` nennt, aber kein Bias-Verfahren erwähnt, hat
`risk_of_bias: unknown` und nicht `low`.

## Warum 60/40 — und was das empirisch trägt

Die Aufteilung setzt voraus, dass die beiden Komponenten verschiedene
Dinge messen. Über die geprüften Claims des Katalogs beträgt die
Korrelation zwischen Quellenkomponente und Stärkekomponente **r = −0,031**
(Stand 2026-08-09, n = 59). Sie sind praktisch unabhängig: 16 peer-reviewte
Artikel tragen `low`, drei Policy Reports tragen `strong`.

Die konkrete Höhe von 60 zu 40 ist damit **nicht** belegt; belegt ist nur,
dass beide Komponenten Information tragen.

## Methodenversion

1. **`METHOD_VERSION`** in `scripts/score_evidence.py` — die vom Menschen
   erklärte Version der Methode.
2. **`METHOD_FINGERPRINTS`** — der Fingerabdruck, den diese Version
   erzeugen muss, berechnet aus den Konstanten selbst. Wer ein Gewicht
   ändert, ohne die Version zu erhöhen, lässt `validate_data.py` und
   `test_method_fingerprint_pins_declared_version` scheitern.
3. **`evidence_score_method`** am Skill-Datensatz — jeder aktive Skill
   trägt die Version, unter der seine gespeicherte Zahl entstanden ist.

### Regel für Änderungen

Wer eine Konstante in `score_evidence.py` ändert:

1. begründet die Änderung in diesem Dokument (Anker anpassen, nicht nur
   die Zahl),
2. erhöht `METHOD_VERSION` (Patch für eine Präzisierung ohne
   Score-Wirkung, Minor für geänderte Gewichte, Major für eine geänderte
   Formel),
3. trägt den neuen Fingerabdruck in `METHOD_FINGERPRINTS` ein — den
   berechneten Wert zeigt `python scripts/score_evidence.py` in der
   ersten Ausgabezeile,
4. lässt `python scripts/score_evidence.py --write` laufen,
5. hält alte Einträge in `METHOD_FINGERPRINTS` fest, statt sie zu
   ersetzen.

### Versionsverlauf des Bewertungsmodells (`APPRAISAL_VERSION`)

Getrennt von `METHOD_VERSION`: Diese Version beschreibt die **Regeln**
(Vokabulare, Baselines, Herleitung), jene die **Arithmetik**, die aus einer
Stufe eine Zahl macht. Jede erfasste Begutachtung trägt in
`appraisal_method` die Version, unter der sie entstand — eine Begutachtung
von vor einer Regeländerung ist damit als solche erkennbar, statt still
unter Regeln gelesen zu werden, die ihre Autorin nie gesehen hat.
`validate_appraisal()` verlangt das Feld, sobald eine Stufe erfasst ist.

| Version | Änderung |
| --- | --- |
| 1.0.0 | Erstfassung: fünfstufige `evidence_certainty`, GRADE-artige Herleitung. |
| 1.1.0 | `claim_type` mit zweitem Herleitungspfad; `narrative_review` und `psychometric_validation` ergänzt. |

### Versionsverlauf der Scoring-Methode (`METHOD_VERSION`)

| Version | Datum | Änderung | Wirkung |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-09 | Erstfassung: Anker dokumentiert, „unbekannt ≠ schwach", Versionierung eingeführt. | Keine Score-Änderung; die Formel war zuvor unversioniert dieselbe. |
| 1.1.0 | 2026-08-09 | `BREADTH_FLOOR` 0,7 → 0,85. | 11 von 16 Scores geändert (+0,01 bis +0,08). Rangfolge in der Gruppe Lernende: Datenkompetenz 8 → 3, Systemdenken 7 → 10. |
| 1.2.0 | 2026-08-10 | Claim-Komponente liest `appraisal.evidence_certainty`; `very_low` = 0,15 ergänzt, `unverifiable` macht unbewertbar. | Keine Score-Änderung zum Zeitpunkt der Einführung; alle 16 Skills neu gestempelt. |

Die erste inhaltliche Score-Bewegung entstand nicht durch eine
Methodenänderung, sondern durch **Daten**: die Begutachtung der 59
geprüften Claims (siehe unten). Das ist der gewollte Weg — die Methode
steht fest, die Urteile ändern sich.

## Der Score misst Menge stärker als Qualität

Der Gesamtscore verrechnet die Evidenzqualität **je Aussage** und die
**Menge** unabhängiger Aussagen. Unter Methode **1.0.0** war die Menge der
stärkere Treiber; **1.1.0** korrigiert das Verhältnis.

| Zusammenhang | 1.0.0 (`BREADTH_FLOOR` 0,7) | 1.1.0 (`BREADTH_FLOOR` 0,85) |
| --- | --- | --- |
| Score ↔ Anzahl geprüfter Aussagen | **+0,663** | +0,352 |
| Score ↔ Evidenzqualität je Aussage | +0,530 | **+0,827** |
| Evidenzqualität ↔ Anzahl | −0,112 | −0,112 |

Die dritte Zeile ist der eigentliche Befund: Die Anzahl geprüfter Aussagen
sagt über deren Qualität **nichts** aus.

| Skill | Qualität je Aussage | Belege | Score 1.0.0 | Score 1.1.0 |
| --- | --- | --- | --- | --- |
| Datenkompetenz | 0,828 | 2 | 0,66 → Rang 8 | 0,74 → **Rang 3** |
| Systemdenken | 0,675 | 10 | 0,68 → Rang 7 | 0,68 → **Rang 10** |

(Ränge in der Vergleichsgruppe *Lernende*, 14 Skills.)

### Warum 0,85 und nicht 1,0

Der Breitenfaktor ist `BREADTH_FLOOR + (1 − BREADTH_FLOOR) · min(n, 6)/6`.
Ihn ganz abzuschalten wäre die einfachere Antwort und die falsche:
**mehrere unabhängige Belege sind ein echtes Qualitätssignal**, nur ein
anderes als die Stärke des einzelnen. Die Wahl ist ausdrücklich
**redaktionell**; messbar ist die Wirkung, nicht die Richtigkeit.

### Vergleichsgruppen

Die Vergleichsgruppe ist die `audience`. Unter `MIN_PEER_GROUP` = 5 Skills
gibt das Dashboard **keinen Rang** aus. „Rang 1 von 2" liest sich wie ein
Befund und ist keiner.

## Lücken

- **Inter-Rater-Baseline: gemessen, mit einem klaren Defekt.** Ein blinder
  Zweitdurchgang über alle 59 begutachteten Katalog-Claims (2026-08-14)
  ergab für `evidence_certainty` κ = 0,50 (gewichtet 0,65) gegenüber
  κ = 0,07 für die abgelöste `evidence_strength`. Für
  `claim_supported_by_source` dagegen **κ = 0,039** — dort trägt der Anker
  nicht (siehe [docs/eval-baseline.md](eval-baseline.md)). Für das
  Eval-Set, an dem die CI-Schwellen hängen, ist die Baseline weiterhin
  offen.
- **Das Goldset erreicht nirgends `strong`.** Keiner der 50 Abstracts
  berichtet eine Bias-Prüfung, und ohne die verbietet der Guardrail
  `strong` auf einer Synthese. Das ist die beabsichtigte Wirkung und
  zugleich eine echte Grenze: **aus einem Abstract allein lässt sich
  `strong` in aller Regel nicht begründen.** Wer es vergeben will, muss
  den Volltext lesen und die Bias-Prüfung eintragen.
- **Kein hochwertiger Nullbefund im Goldset.** Die drei Nullbefunde
  (`handwriting-tablet`, `vr-history`, `ar-anatomy`) sind alle
  quasi-experimentell. Grenzfall 2 ist deshalb in
  `tests/test_appraisal.py` konstruiert statt am Katalog belegt.
- **Die Herleitung wurde an denselben 50 Fällen entworfen**, an denen sie
  jetzt zutrifft. Ihre Übereinstimmung mit der Begutachtung ist deshalb
  **kein** unabhängiger Beleg — sie zeigt Konsistenz, nicht Gültigkeit.
- **Nur die geprüften Claims sind begutachtet.** 59 von 1814; die
  Kandidaten tragen weiterhin nur `evidence_strength`. Für den Score ist
  das folgenlos (nur geprüfte Claims zählen), für eine spätere Freigabe
  nicht.
- **Auch der Katalog erreicht nirgends `strong`.** Wie im Goldset: keine
  der 51 Quellen berichtet im Abstract eine Bias-Prüfung, und der
  Eignungspfad kommt ohne Replikation *und* belegte Konsistenz nicht über
  `moderate` hinaus.
- **Die Begutachtung stützt sich auf Abstracts**, nicht auf Volltexte. Für
  neun Aussagen kommt erschwerend hinzu, dass sie eine Sekundärquelle
  zitieren, die ihrerseits eine Primärstudie referiert (JRC-Bericht →
  Rijke et al., Bower et al., Lamprou & Repenning). Deren Design ist nur
  so weit erfasst, wie das Zitat es hergibt.
- Der Score ist eine Konfidenzzahl, die fast nur bestätigende Evidenz
  kennt. Siehe [docs/gegenevidenz-lane.md](gegenevidenz-lane.md).
