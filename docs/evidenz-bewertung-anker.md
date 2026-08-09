# Methodik: Ankerdefinitionen der Evidenzbewertung

Dieses Dokument legt offen, was die Zahlen in `scripts/score_evidence.py`
bedeuten: was ein Claim mit `evidence_strength` `low`, `moderate` oder
`strong` ist, warum jeder `source_type` das Gewicht trägt, das er trägt,
und unter welchen Regeln diese Konstanten geändert werden dürfen.

Der Anlass ist ein Vergleich mit [kurate.org](https://kurate.org/), das
wissenschaftliche Preprints über 16 Dimensionen bewertet. Dessen
methodisch stärkster Zug ist nicht die Zahl der Dimensionen, sondern dass
jede Skala **verankert** ist: der Bewertungs-Prompt sagt ausdrücklich, was
eine 1, was eine 5 und was eine 10 bedeutet. Unsere Skala war bis dahin
reproduzierbar, aber unbegründet — neun hartkodierte Quellengewichte und
drei Stärkestufen ohne eine Zeile darüber, was sie unterscheidet.
Reproduzierbar-aber-willkürlich ist genau die Scheinpräzision, gegen die
das Projektprinzip antritt: keine Skill-Empfehlung ohne Evidenzpfad.

Die Gewichte sind **redaktionelle Urteile**, keine gemessenen Größen. Was
sie leisten, ist Konsistenz zwischen Reviewenden — nicht Wahrheit.

## Die Formel in einem Satz

Ein Claim-Score besteht zu 60 % aus der Quellenqualität (`source_type`)
und zu 40 % aus der im Review vergebenen `evidence_strength`. Der
Skill-Score ist der Mittelwert seiner geprüften Claim-Scores, skaliert um
einen Breitenfaktor (voll ab `BREADTH_SATURATION` = 6 unabhängigen
Claims, Untergrenze `BREADTH_FLOOR` = 0,85) und vermindert um
`CONTRADICTION_PENALTY` = 0,1 je widersprechendem Claim.

## Anker: `evidence_strength`

`evidence_strength` bewertet **den Claim, nicht die Quelle**. Ein
angesehener Bericht kann eine schwach belegte Einzelaussage enthalten,
und ein kleines Paper kann eine sauber belegte. Die beiden Komponenten
sind absichtlich unabhängig; siehe „Warum 60/40" unten.

| Stufe | Gewicht | Definition |
| --- | --- | --- |
| `strong` | 1,0 | Die Aussage wird durch systematisch erhobene Evidenz über mehrere Studien, Länder oder Kohorten getragen — oder sie ist eine konsentierte Festlegung eines Referenzrahmens, der selbst auf einem dokumentierten Konsensverfahren beruht. |
| `moderate` | 0,7 | Die Aussage benennt eine konkrete empirische Grundlage (Stichprobe, Fallstudienreihe, Erhebung), die aber begrenzt ist: eine Population, ein Kontext, ein Zeitpunkt, oder ohne Kontrollbedingung. |
| `low` | 0,35 | Die Aussage ist plausibel und aus der Quelle korrekt entnommen, aber deskriptiv oder normativ: sie beschreibt eine verbreitete Praxis, eine Empfehlung oder eine Einschätzung, ohne im Text eine tragende Evidenz dafür zu nennen. |

### Beispiele aus dem Katalog

Alle drei Stufen kommen im selben Quellentyp vor — das ist der Punkt.

- **`strong`** — `claim-ai-literacy-k12-systematic-review`: „A systematic
  review of K-12 AI literacy concludes that learners can develop AI
  literacy across conceptual understanding, hands-on use, and ethical
  awareness …". Systematische Aggregation über viele Primärstudien.
- **`moderate`** — `claim-reviewing-computational-thinking-…-5`: „Evidence
  collected from in-depth case studies involving nine European countries
  shows that basic CS concepts integrated into curricula centre around
  …". Konkrete empirische Grundlage, aber Fallstudiendesign und auf neun
  Länder begrenzt.
- **`low`** — `claim-reviewing-computational-thinking-…-3`: „The value of
  debugging as a strategy is exploited both at primary and lower
  secondary level to create a culture of learning-through-error …". Aus
  **derselben** Quelle wie das `moderate`-Beispiel, aber eine
  Praxisbeschreibung ohne genannten Beleg.

### Was keine `strong`-Aussage ist

- Eine Aussage, die stark klingt, weil die Quelle prominent ist (OECD,
  UNESCO, WEF). Der Quellentyp ist bereits die anderen 60 %; ihn hier
  noch einmal zu belohnen, zählt ihn doppelt.
- Eine Aussage über einen **Bedarf** oder eine **Forderung**
  („Schulen müssen …"). Das ist eine normative Setzung, kein Befund —
  `low`, auch in einem Referenzrahmen.
- Eine Aussage, die über die Belege der Quelle hinaus verallgemeinert.
  Der Claim wird an dem gemessen, was die Quelle für ihn hergibt.

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

`dataset` und `web_resource` bleiben definiert, obwohl keine Quelle sie
nutzt: die Gewichte müssen feststehen, **bevor** die erste solche Quelle
eintrifft, sonst wird die Skala am Einzelfall gebogen.

## Warum 60/40 — und was das empirisch trägt

Die Aufteilung setzt voraus, dass die beiden Komponenten verschiedene
Dinge messen. Wären sie redundant (würde ein `systematic_review` fast
immer `strong` tragen), wäre die zweite Komponente Dekoration und die
Gewichtung Scheinpräzision.

Über die geprüften Claims des Katalogs gemessen beträgt die Korrelation
zwischen Quellenkomponente und Stärkekomponente **r = −0,031** (Stand
2026-08-09, n = 59). Sie sind praktisch unabhängig. Die Kreuztabelle
zeigt es direkt: 16 peer-reviewte Artikel tragen `low`, drei Policy
Reports tragen `strong`. Die Reviewenden bewerten Claim und Quelle
tatsächlich getrennt — die Voraussetzung der Formel hält.

Die konkrete Höhe von 60 zu 40 ist damit **nicht** belegt; belegt ist nur,
dass beide Komponenten Information tragen. Die Aufteilung gewichtet die
prüfbarere Größe (Quellentyp, aus Metadaten ableitbar) höher als die
redaktionelle (`evidence_strength`, ein Urteil).

## Unbekannt ist nicht schwach

Der zweite übernommene Zug von kurate.org: dort bekommt eine Dimension,
deren Voraussetzung nicht erfüllt ist, ausdrücklich `null` statt einer
erzwungenen Zahl — ein Bewertungslauf, der Werte erfindet, gilt als
Fehler.

Dieselbe Falle war bei uns eingebaut, nur in der Gegenrichtung: Ein
fehlender `evidence_strength` ergab 0, eine Claim ohne auflösbare Quelle
ergab 0 für die Quellenkomponente, und ein unbekannter `source_type` fiel
auf 0,25 zurück — das Gewicht des schwächsten *bekannten* Typs. In allen
drei Fällen sah ein Datendefekt wie schwache Evidenz aus und floss
stillschweigend in den Skill-Score ein.

Seit `METHOD_VERSION` 1.0.0 gilt:

- `claim_score()` gibt **`None`** zurück, wenn eine Claim keine Quelle
  hat, eine Quelle nicht auflösbar ist, ein `source_type` kein Gewicht
  besitzt oder die `evidence_strength` keine der drei verankerten Stufen
  ist. `None` heißt „nicht bewertbar", nicht „schwach".
- `reviewed_claim_scores()` lässt solche Claims aus der Rechnung — wie
  Kandidaten und abgelehnte Claims auch.
- `unscoreable_reviewed_claims()` benennt sie mitsamt Grund, und
  `validate_data.py` macht daraus einen **Fehler**. Eine geprüfte Claim
  trägt die Evidenz eines aktiven Skills; sie darf nicht unbemerkt aus
  dem Score fallen. Bei Kandidaten-Claims ist eine offene Referenz
  dagegen normaler Pipeline-Zustand und bleibt still.

## Methodenversion

kurate.org zeigt auch, was ohne Versionierung passiert: dort tragen
Papers vor 2024 nur fünf der 16 Dimensionen, und diese Scores stehen
unmarkiert in derselben Rangliste wie die vollständig bewerteten. Zwei
Zahlen, zwei Methoden, eine Spalte.

Dagegen greifen drei Mechanismen:

1. **`METHOD_VERSION`** in `scripts/score_evidence.py` — die vom Menschen
   erklärte Version der Methode.
2. **`METHOD_FINGERPRINTS`** — der Fingerabdruck, den diese Version
   erzeugen muss. Er wird aus den Konstanten selbst berechnet
   (`fingerprint(method_parameters())`). Wer ein Gewicht ändert, ohne die
   Version zu erhöhen, lässt `validate_data.py` und
   `test_method_fingerprint_pins_declared_version` scheitern. Die Version
   kann also nicht hinter den Konstanten zurückbleiben.
3. **`evidence_score_method`** am Skill-Datensatz — jeder aktive Skill
   trägt die Version, unter der seine gespeicherte Zahl entstanden ist.
   `validate_data.py` verlangt sie auf aktiven Skills.

`score_evidence.py --write` schreibt einen `change_log`-Eintrag auch
dann, wenn sich die Methode geändert hat, die **Zahl aber gleich blieb** —
sonst bedeutete dieselbe gespeicherte 0,74 zwei verschiedene Dinge, ohne
dass es irgendwo stünde.

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
4. lässt `python scripts/score_evidence.py --write` laufen; jeder
   betroffene Skill bekommt Stempel und Changelog-Eintrag,
5. hält alte Einträge in `METHOD_FINGERPRINTS` fest, statt sie zu
   ersetzen — sonst ist nicht mehr prüfbar, was eine ältere gespeicherte
   Zahl bedeutete.

### Versionsverlauf

| Version | Datum | Änderung | Wirkung |
| --- | --- | --- | --- |
| 1.0.0 | 2026-08-09 | Erstfassung: Anker dokumentiert, „unbekannt ≠ schwach", Versionierung eingeführt. | Keine Score-Änderung; die Formel war zuvor unversioniert dieselbe. |
| 1.1.0 | 2026-08-09 | `BREADTH_FLOOR` 0,7 → 0,85. | 11 von 16 Scores geändert (+0,01 bis +0,08). Rangfolge in der Gruppe Lernende: Datenkompetenz 8 → 3, Systemdenken 7 → 10. |

Ein Score aus einer älteren Methode ist an `evidence_score_method` am
Skill-Datensatz erkennbar; `validate_data.py` verlangt auf aktiven Skills
die aktuelle Version, sodass zwei Methodenstände nie unmarkiert
nebeneinander stehen können.

## Grenzen

- Die Gewichte sind **eine redaktionelle Einzelbewertung**, ohne
  Inter-Rater-Verfahren. Es ist bisher nicht gemessen, wie gut zwei
  Personen bei derselben Claim dieselbe `evidence_strength` vergeben
  würden. Solange diese Baseline fehlt, ist die Konsistenz der Skala eine
  Annahme, keine Feststellung — dieselbe offene Flanke, die
  [docs/lehrplan21-coverage-methodik.md](lehrplan21-coverage-methodik.md)
  für die Coverage-Scores benennt.
- Der `evidence_score` ist **global** über alle Skills, Stränge und
  Zielgruppen. Ein Thema mit systematischen Reviews erreicht strukturell
  höhere Werte als ein junges; der Score bildet damit auch die Reife
  eines Forschungsfeldes ab, nicht nur die Evidenzlage einer Kompetenz.
  Wie stark, ist inzwischen gemessen — siehe den nächsten Abschnitt.
- Die Gegenprobe fehlt weitgehend: Der Score ist eine Konfidenzzahl, die
  fast nur bestätigende Evidenz kennt. Siehe
  [docs/gegenevidenz-lane.md](gegenevidenz-lane.md).

## Der Score misst Menge stärker als Qualität

Der Gesamtscore verrechnet zwei Dinge zu einer Zahl: die Evidenzqualität
**je Aussage** (der Mittelwert der Claim-Scores) und die **Menge**
unabhängiger Aussagen (der Breitenfaktor). Unter Methode **1.0.0** war
die Menge der stärkere Treiber — was ein Score, der Evidenz behauptet zu
messen, nicht sein sollte. Methode **1.1.0** korrigiert das Verhältnis.

Gemessen über die 16 aktiven Skills (Stand 2026-08-09):

| Zusammenhang | 1.0.0 (`BREADTH_FLOOR` 0,7) | 1.1.0 (`BREADTH_FLOOR` 0,85) |
| --- | --- | --- |
| Score ↔ Anzahl geprüfter Aussagen | **+0,663** | +0,352 |
| Score ↔ Evidenzqualität je Aussage | +0,530 | **+0,827** |
| Evidenzqualität ↔ Anzahl | −0,112 | −0,112 |

Die dritte Zeile ist der eigentliche Befund und ändert sich nicht: Die
Anzahl geprüfter Aussagen sagt über deren Qualität **nichts** aus
(r ≈ −0,11). Sie ist zu einem erheblichen Teil ein Produkt des
Review-Durchsatzes und der Reife eines Forschungsfeldes, nicht der
Belegkraft. Unter 1.0.0 trieb genau diese uninformative Größe die
Rangfolge stärker als die informative.

Der Fall, an dem es sichtbar wurde:

(Ränge in der Vergleichsgruppe *Lernende*, 14 Skills — so, wie das
Dashboard sie ausweist.)

| Skill | Qualität je Aussage | Belege | Score 1.0.0 | Score 1.1.0 |
| --- | --- | --- | --- | --- |
| Datenkompetenz | 0,828 (zweithöchste im Katalog) | 2 | 0,66 → Rang 8 | 0,74 → **Rang 3** |
| Systemdenken | 0,675 (eine der niedrigsten) | 10 | 0,68 → Rang 7 | 0,68 → **Rang 10** |

Unter 1.0.0 stand Systemdenken über Datenkompetenz, obwohl seine Evidenz
je Aussage deutlich schwächer ist. Wer die Rangliste als Rangliste las,
zog daraus den falschen Schluss.

### Warum 0,85 und nicht 1,0

Der Breitenfaktor ist `BREADTH_FLOOR + (1 − BREADTH_FLOOR) · min(n, 6)/6`.
Die Untergrenze bestimmt, wie stark ein kurzer Evidenzpfad den Score
dämpft: bei 0,7 reichte der Faktor von 0,75 (ein Beleg) bis 1,00 (ab
sechs), bei 0,85 nur noch von 0,875 bis 1,00.

Ihn ganz abzuschalten (`BREADTH_FLOOR` = 1,0) wäre die einfachere
Antwort und die falsche: **mehrere unabhängige Belege sind ein echtes
Qualitätssignal**, nur ein anderes als die Stärke des einzelnen Belegs.
Eine Aussage, die dreimal unabhängig repliziert wurde, ist besser
abgesichert als eine gleich starke Einzelstudie — der Score soll das noch
sehen, nur nicht mehr dominieren lassen. 0,85 lässt die Breite als
nachgeordnetes Signal wirken (r sinkt von 0,66 auf 0,35), während die
Qualität den Score klar bestimmt (r steigt von 0,53 auf 0,83).

Die Wahl ist damit ausdrücklich **redaktionell**, nicht hergeleitet. Was
sich messen lässt, ist die Wirkung, nicht die Richtigkeit; die Tabelle
oben zeigt sie für 0,85, und `git log` bewahrt, wogegen entschieden
wurde.

### Was die Zerlegung zusätzlich leistet

Auch mit korrigierter Gewichtung bleibt der Gesamtscore eine
Zusammenfassung. Das Dashboard zeigt deshalb weiterhin die Zerlegung
daneben (Qualität je Aussage, Anzahl Belege, Breitenfaktor), nennt die
Vergleichsgruppe und benennt die Divergenz im Klartext, wo sie auftritt.
Die Liste lässt sich nach Qualität je Aussage oder nach Anzahl Belege
sortieren statt nur nach dem Gesamtscore. Berechnet wird das in
`scripts/score_context.py` zur Bauzeit; gespeichert wird nichts davon,
damit kein zweiter abgeleiteter Wert von seiner Formel abdriften kann.

### Vergleichsgruppen

Die Vergleichsgruppe ist die `audience` — Evidenz über Lernende und
Evidenz über Lehrpersonen stammt aus verschiedenen Literaturen
(K-12-Interventionsstudien vs. Professionalisierungsforschung) und ist
nicht direkt vergleichbar. kurate.org rankt aus demselben Grund innerhalb
der arXiv-Kategorie.

Unter `MIN_PEER_GROUP` = 5 Skills gibt das Dashboard **keinen Rang** aus,
sondern sagt, dass die Gruppe zu klein ist. „Rang 1 von 2" liest sich wie
ein Befund und ist keiner. Das ist dieselbe Zurückhaltung, die
[docs/eval-baseline.md](eval-baseline.md) bei einer unterpowerten
Baseline anwendet. Die Gruppe „Lehrende" umfasst derzeit 2 Skills und
bekommt deshalb keinen Rang.

Kandidaten-Skills bilden keine Vergleichsgruppe: Sie tragen
konstruktionsbedingt `evidence_score` 0,0 (`cluster_claims.py`) und
würden jeden Median gegen null ziehen.
