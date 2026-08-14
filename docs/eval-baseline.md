# Methodik: Wie verlässlich sind unsere Eval-Labels?

Jedes CI-Gate des Projekts misst eine Pipeline gegen `gold` und behandelt
`gold` als Wahrheit. Keines misst, wie reproduzierbar `gold` selbst ist.
Dieses Dokument schliesst diese Lücke — oder genauer: es macht sie
messbar, benennt, was heute darüber bekannt ist (wenig), und legt fest,
wie ein gemessener Wert die bestehenden Schwellen einordnen wird.

## Warum das zählt

[kurate.org](https://kurate.org/) validiert seine KI-Bewertungen an 62
ICLR-Papers mit 262 Expertenreviews. Die berichtete Übereinstimmung
zwischen KI und Experte beträgt 76,1 % — und daneben steht die
Übereinstimmung **zwischen zwei Experten**: 79,5 %. Erst das zweite
Paar Zahlen macht das erste lesbar. 76,1 % ist nicht „24 % falsch",
sondern „fast an der Decke dessen, was Menschen untereinander schaffen".

Ohne diese Decke ist jede Schwelle blind gesetzt. Zwei Fehler werden
möglich, und man kann nicht unterscheiden, welcher vorliegt:

- Eine Schwelle liegt **über** der Decke. Sie verlangt eine Konsistenz,
  die die Bewertenden selbst nicht erreichen — die Pipeline kann sie nur
  zufällig halten.
- Ein gemessener Wert liegt **auf** der Decke. Weiteres Anziehen misst
  dann nur noch Label-Rauschen, nicht Modellqualität.

## Wo unsere Schwellen heute verankert sind

Zur Klarstellung, weil es leicht falsch dargestellt wird: Die Floors in
`.github/workflows/validate.yml` sind **keine willkürlich gewählten
runden Zahlen**. [OPERATIONS.md](../OPERATIONS.md) leitet sie systematisch
her — gemessener Wert minus explizit begründeter Spielraum, mit einer
Sensitivitätsrechnung dazu, wie stark ein einzelner Umschlag die Metrik
bewegt:

| Metrik | gemessen | Floor | Spielraum |
| --- | --- | --- | --- |
| `age_range`-Precision | 0,91 | 0,80 | 0,11 |
| `outcome`-Precision | 0,87 | 0,75 | 0,12 |
| `context`-Precision | 0,96 | 0,85 | 0,11 |
| `evidence_strength`-Precision | 0,80 | 0,70 | 0,10 |
| GATED-Precision (age + strength) | 0,85 | 0,80 | 0,05 |
| Abstention (Skill-Links) | 0,93 | 0,85 | 0,08 |

(Gemessene Werte aus dem Lauf der beiden Eval-Skripte am 2026-08-09.
OPERATIONS.md nennt an zwei Stellen leicht ältere Zahlen aus früheren
Aufnahmegenerationen — massgeblich ist die Ausgabe der Skripte.)

OPERATIONS.md begründet dort auch, **warum** manche Metrik kein Gate
trägt: Bei der Skill-Link-Precision bewegt ein einziger Umschlag den Wert
um 0,071, bei der Abstention nur um 0,025 — deshalb ist die eine ein
Gate und die andere ausdrücklich nur eine Stolperdrahtschwelle.

Diese Herleitung ist sauber. Sie verankert die Floors aber an der
**gemessenen Leistung der Pipeline**, nicht an der Decke, unter der diese
Messung stattfindet. Genau das ist die offene Flanke: `evidence_strength`
misst 0,80 gegen ein Gate von 0,70. Wenn zwei Bewertende bei
`evidence_strength` nur zu etwa 80 % übereinstimmen, ist 0,80 bereits die
Decke — der Spielraum von 0,10 fängt dann Label-Rauschen ab statt
Modell-Regression, und das Gate kann eine echte Verschlechterung nicht
mehr von Bewertungsstreuung trennen. Ob das so ist, weiss heute niemand.

## Was heute gemessen ist: fast nichts, und warum

Im Repository gibt es genau zwei Label-Quellen, die **dieselben** Objekte
beurteilen:

- `eval/relevance_labeled.json` — kuratierte redaktionelle Labels.
- `eval/relevance_harvested.json` — Labels, die
  `scripts/promote_candidate.py` bei jeder Review-Entscheidung automatisch
  mitschreibt.

Sie überschneiden sich in **16 Titeln**, und die Labels stimmen in
16 von 16 Fällen überein. Das sieht nach einer geschenkten Baseline aus.
Es ist keine.

`scripts/eval_agreement.py` meldet diesen Vergleich deshalb als
**PROVENANCE UNVERIFIED**. Die Gründe:

- Alle 16 überlappenden Fälle wurden zwischen dem 2026-06-20 und dem
  2026-06-29 geerntet — sämtlich **vor dem ersten Commit des
  Repositories** (2026-07-12). Die Versionsgeschichte kann also nicht
  belegen, welches Urteil zuerst da war.
- 12 der 16 kuratierten Einträge tragen `origin: "live_run"`, laut dem
  README des Sets „real candidates from the live pipeline runs" — also
  aus denselben Läufen, deren Review-Entscheidungen geerntet wurden.
- Ihre `note`-Felder lesen sich wie Review-Begründungen („WASH
  public-health review; 'education' is incidental"). Das schreibt jemand
  **beim Entscheiden**, nicht beim blinden Nachbewerten.

Die wahrscheinlichste Geschichte ist eine einzige Review-Sitzung, die
sowohl die Entscheidung traf (und automatisch geerntet wurde) als auch
den kuratierten Eintrag von Hand anlegte. Dann sind die 16/16 keine
Übereinstimmung, sondern **dasselbe Urteil zweimal notiert**. Es misst
per Konstruktion 100 %, ganz gleich wie konsistent die Bewertung
tatsächlich ist.

Auch das Gegenteil ist nicht bewiesen — vielleicht war es doch eine
zweite Runde. Aber eine Baseline, deren Unabhängigkeit man nicht zeigen
kann, ist keine Baseline. Sie wird deshalb nicht als solche verwendet.

### Nebenwirkung auf `--include-harvested`

`scripts/eval_relevance.py --include-harvested` faltet die geernteten
Labels für eine „grössere Stichprobe" in den Bericht. Wenn ein Teil der
Überlappung tatsächlich dasselbe Urteil doppelt ist, vergrössert dieser
Modus die Stichprobe weniger als es aussieht: 16 der 105 geernteten
Beispiele (15 %) haben ein Gegenstück im kuratierten Set. Der Modus
dedupliziert bereits nach Titel, die gemeldete Fallzahl ist also korrekt
— die *Unabhängigkeit* der verbleibenden Beispiele bleibt aber die
gleiche offene Frage.

## Wie eine echte Baseline entsteht

`scripts/eval_agreement.py` erzeugt einen **blinden Bewertungsbogen** und
wertet ihn aus.

**Zwei Bögen liegen leer im Repository und warten auf einen Durchgang.**
Welcher der richtige ist, hängt an der Frage:

| Bogen | Fälle | Beantwortet |
| --- | --- | --- |
| [`eval/catalog_second_rater.json`](../eval/catalog_second_rater.json) | 59 begutachtete Katalog-Claims | Ist die Evidenzbewertung **im Dashboard** reproduzierbar? |
| [`eval/claim_prefill_second_rater.json`](../eval/claim_prefill_second_rater.json) | 50 synthetische Eval-Fälle | Lassen sich die **CI-Schwellen** lesen? |

Der Katalog-Bogen misst die Urteile, die live die Skill-Scores treiben,
und ist deshalb der dringlichere. Er bewertet zusätzlich das alte
`evidence_strength` — damit beantwortet ein Durchgang eine Frage, die der
Eval-Bogen nicht stellen kann: **Ist die neue Skala reproduzierbarer als
die, die sie ersetzt hat?**, an derselben Lektüre desselben Claims. Das
alte `age_range` wird dort nicht bewertet: vier geprüfte Claims tragen
darin die Zeichenkette `"Lehrende"`, und wer einen Defekt reproduziert,
misst nichts.

Ausfüllen, `protocol.rater` und `protocol.labeled_at` setzen, auswerten:

```powershell
python scripts/eval_agreement.py --second-rater eval/catalog_second_rater.json
```

Alle Bögen neu erzeugen (überschreibt begonnene): `make agreement-worksheet`.

### Weniger Felder bewerten

Sechs Urteilsfelder × 59 Fälle ist ein halber Arbeitstag. `--fields`
verkleinert den Auftrag:

```powershell
python scripts/eval_agreement.py --worksheet catalog \
  --fields evidence_certainty,claim_type --out bogen.json
```

Der gewählte Satz steht in `protocol.rated_fields`, und die Auswertung
hält sich daran. **Das ist keine Bequemlichkeit, sondern eine
Korrektheitsfrage:** Wer vorher zwei Felder ausfüllte und sechs leer
liess, bekam für die sechs eine Übereinstimmung von 0,000 ausgewiesen —
Arbeit, um die niemand gebeten hatte, gezählt als Widerspruch. Die
Rubrik im Bogen schrumpft mit; ein unbekannter Feldname wird mit der
Liste der verfügbaren abgelehnt.

### Was im Bogen steht

Pro Fall: `statement`, `abstract`, `source_type` — und die zu bewertenden
Felder. Kein `gold`, kein `gold_appraisal`, kein `_recorded`, keine `note`.

**Bewertet werden fünf Urteilsfelder** und zusätzlich die beiden alten:

| Feld | Warum bewertet |
| --- | --- |
| `evidence_certainty` | die zentrale Variable; ordinal |
| `claim_supported_by_source` | der Abgleich Aussage↔Quelle, für den kein Metadatenfeld einspringen kann |
| `study_design` | nominal, und der Eingang, auf den die Herleitung am stärksten reagiert |
| `effect_direction` | nominal; getrennt erhoben, damit eine Person, die Richtung und Sicherheit vermischt, sichtbar wird statt unsichtbar |
| `age_range_explicit` | nur gemeldete Alter — das Feld, dessen Vorgänger Gemeldetes und Geschätztes vermischte |
| `claim_type` | entscheidet, welcher Herleitungspfad gilt; wer hier abweicht, bewertet eine andere Frage |
| `evidence_strength`, `age_range` | die alten Felder, mitgeführt, damit sich beide Skalen an derselben Lektüre vergleichen lassen |

**Nicht bewertet** werden bibliografische Felder (`authors`, `year`, `doi`,
…). Das ist Abschrift, kein Urteil: Wer denselben Titel liest, schreibt
denselben Titel, und eine Abweichung dort ist ein Tippfehler, keine
Bewertungsdifferenz.

Dazu die **Rubrik im Bogen selbst**: die fünf
`evidence_certainty`-Ankerdefinitionen werden beim Erzeugen aus
[docs/evidenz-bewertung-anker.md](evidenz-bewertung-anker.md)
ausgelesen, nicht im Code wiederholt. Ließe sich die Tabelle nicht lesen,
bricht die Erzeugung ab, statt einen Bogen ohne Rubrik auszuliefern.

Die Reihenfolge bleibt die des Goldsets. Sie wurde geprüft: 30
Kategorienwechsel bei 50 Fällen (unter Zufall ~31 erwartet), längster
gleichartiger Block 4 — es gibt kein Muster, gegen das ein Mischen
schützen müsste.

### Was `null` im Bogen bedeutet

`null` trägt zwei Bedeutungen, und sie auseinanderzuhalten entscheidet
über die Aussagekraft:

- **„Ich habe diesen Fall nicht bewertet."**
- **„Ich habe ihn bewertet, und die Antwort ist nichts."** — kein Alter
  genannt, Design nicht berichtet, Abstract gibt zu wenig her.

Entschieden wird deshalb **fallweise, nicht feldweise**: Ein Fall, in dem
gar kein Feld ausgefüllt ist, gilt als übersprungen; in jedem Fall, an dem
gearbeitet wurde, ist ein `null` eine Antwort.

Feldweise zu entscheiden hätte die zweite Bedeutung verschluckt — bei
`age_range_explicit` betrifft sie 48 von 50 Fällen, die Stichprobe wäre auf
zwei zusammengeschrumpft. Umgekehrt darf `null` nicht überall als Antwort
gelten: Ein Bogen, den niemand ausgefüllt hat, stimmte dann mit jedem
`null`-Primärlabel überein und meldete sich selbst als Baseline. Genau das
prüft `test_an_untouched_worksheet_measures_nothing`.

Übersprungene Fälle werden **gezählt und ausgewiesen**, nicht stillschweigend
weggelassen.

### Welche Kennzahlen berichtet werden

Für jedes Feld:

- **Anzahl bewerteter und übersprungener Fälle**
- **rohe Übereinstimmung** mit 95-%-Wilson-Intervall
- **Cohens Kappa** — zufallskorrigiert; `undefined`, wenn nur eine
  Kategorie vorkam (dann ist die erwartete Übereinstimmung 1,0 und die
  Zahl wäre eine Division durch null, kein perfektes Ergebnis)
- **linear gewichtetes Kappa** für ordinale Felder (derzeit nur
  `evidence_certainty`)
- **Konfusionsmatrix**; bei mehr als sechs Kategorien stattdessen die
  besetzten Zellen als Liste, weil ein Raster aus achtzehn fast leeren
  Spalten weniger zeigt als sechs Zeilen, die benennen, wer was verwechselt
  hat

**Ordinal ist nur `evidence_certainty`** (`very_low` < `low` < `moderate` <
`strong`). Alle anderen bewerteten Felder sind nominal und bekommen kein
gewichtetes Kappa.

**Gewichtung: linear, nicht quadratisch.** Quadratische Gewichte machen
eine Zwei-Stufen-Abweichung viermal so nachsichtig wie eine
Ein-Stufen-Abweichung — das ist eine präzise Behauptung darüber, wie viel
schlimmer der grössere Fehler ist, und nichts hier misst das. Lineare
Gewichte sagen nur „weiter auseinander ist schlechter", und mehr behauptet
die Ordinalskala nicht.

**`unverifiable` ist kein fehlender Wert.** Es zählt in die rohe
Übereinstimmung und in Cohens Kappa wie jede andere Kategorie. Es liegt
aber nicht auf der Ordinalskala — es sagt etwas über Auffindbarkeit, nicht
über Stärke —, deshalb fällt ein Paar, das es enthält, aus dem gewichteten
Kappa heraus. Die Anzahl der so entfernten Paare wird ausgewiesen.

**Nicht-blinde Bewertungen** werden weiterhin als `PROVENANCE UNVERIFIED`
gemeldet und nie als Baseline gezählt, unabhängig davon, wie hoch die
Übereinstimmung ausfällt.

### Die Kalibrierrunde, Schritt für Schritt

**Kalibriert wird auf dem Eval-Set, gemessen wird auf dem Katalog.** So
geht kein Katalogfall für die Messung verloren, und die Kalibrierfälle
decken die Design-Leiter breiter ab, als der Katalog es könnte (dort
behaupten nur 14 von 59 Aussagen überhaupt eine Wirkung).

**Schritt 1 — Bogen erzeugen.** Diese zehn Fälle stellen je eine andere
Regel auf die Probe; zusammen decken sie alle vier Certainty-Stufen, neun
Studiendesigns und drei `claim_type`-Werte ab:

```powershell
python scripts/eval_agreement.py --worksheet claim_prefill --out kalibrierung.json --only `
  prefill-handwriting-tablet,prefill-worked-examples-math,prefill-phonics-reception,`
  prefill-self-regulation-elementary,prefill-financial-literacy-secondary,`
  prefill-adhd-selfmonitor,prefill-physics-simulations,prefill-adult-mooc,`
  prefill-policy-ai-ethics,prefill-collaboration-middle
```

| Fall | prüft |
| --- | --- |
| `handwriting-tablet` | Ein Nullbefund senkt die Sicherheit **nicht**. |
| `worked-examples-math` | Ein gutes RCT bleibt `moderate` — ohne Replikation kein `strong`. |
| `phonics-reception` | 28 Trials, konsistent — und trotzdem nicht `strong`, weil keine Bias-Prüfung berichtet ist. |
| `self-regulation-elementary` | Hohe Heterogenität wertet eine Meta-Analyse ab. |
| `financial-literacy-secondary` | Pre-Post ohne Kontrollgruppe. |
| `adhd-selfmonitor` | Single-Case. |
| `physics-simulations` | „11th grade" ergibt **keine** Altersspanne. |
| `adult-mooc` | `association` statt `causal_effect`, und „aged 22 to 55" ist eine echte Altersangabe. |
| `policy-ai-ethics` | Normative Aussage → Eignungspfad statt Design-Leiter. |
| `collaboration-middle` | Design nicht berichtet → `null` ist die richtige Antwort. |

Der Bogen trägt `protocol.calibration_subset: true`. Die Auswertung
weigert sich damit, ihn als Baseline zu zählen, egal wie gut die
Übereinstimmung ausfällt.

**Schritt 2 — blind ausfüllen.** Die bewertende Person füllt die Felder
aus, ohne dieses Dokument über die Rubrik hinaus zu lesen und ohne in den
Katalog zu schauen. `protocol.rater` und `protocol.labeled_at` setzen.

**Schritt 3 — Zahlen ansehen.**

```powershell
python scripts/eval_agreement.py --second-rater kalibrierung.json
```

Die Konfusionsmatrix ist hier wichtiger als die Prozentzahl: Ein
durchgehender Versatz um eine Stufe ist etwas anderes als Streuung.

**Schritt 4 — das Gespräch führen.**

```powershell
python scripts/eval_agreement.py --explain kalibrierung.json
```

Das zeigt pro Fall beide Antworten **und die Begründung** des
gespeicherten Urteils („baseline moderate for study_design meta_analysis;
high heterogeneity between pooled studies (-1)"). Das ist nötig, weil die
primäre Bewertung von niemandem stammt, der mit im Raum sitzt — die
Begründungskette ist die Gesprächspartnerin.

**Schritt 5 — jede Abweichung einsortieren.** Genau drei Sorten:

| Sorte | Woran erkennbar | Was zu tun ist |
| --- | --- | --- |
| **Rubrik war mehrdeutig** | Beide Lesarten sind mit dem Ankertext vereinbar | Ankertext schärfen — das ist ein Defekt und die einzige Sorte, die eine Änderung verlangt |
| **Jemand hat den Abstract falsch gelesen** | Eine Seite räumt es beim Nachlesen ein | Nichts. Ein Lesefehler ist kein Methodenproblem |
| **Echte Urteilsdifferenz** | Beide bleiben nach dem Gespräch bei ihrer Lesart | Notieren, stehenlassen. Nicht wegverhandeln — diese Streuung ist das, was die Baseline später messen soll |

Die Versuchung ist Sorte drei: sich auf eine „richtige" Antwort zu
einigen und dann zu messen. Das erzeugt eine hohe Übereinstimmung, die
nichts bedeutet.

**Schritt 6 — messen.** Erst jetzt der volle Durchgang, auf einem
frischen Bogen, über den ganzen Katalog:

```powershell
python scripts/eval_agreement.py --second-rater eval/catalog_second_rater.json
```

Die zehn Kalibrierfälle stammen aus dem Eval-Set und tauchen dort nicht
auf; alle 59 Katalogfälle bleiben messbar.

### Wer bewerten kann

**Keine Fachexpertise in KI oder Bildungsforschung nötig.** Die Person
muss ein Abstract lesen und eine geschriebene Rubrik anwenden können —
die Rubrik liegt im Bogen. Genau dafür wurden die Anker aufgeschrieben.

Wenn niemand verfügbar ist: derselbe Mensch zeitversetzt. Das misst
Selbstkonsistenz (Test-Retest) und ist eine **Obergrenze** für die
Übereinstimmung zwischen Personen — verwertbar, aber es muss in
`protocol.rater` so stehen.

### Protokoll

1. **Blind.** Die bewertende Person sieht Titel/Abstract bzw.
   Statement/Abstract/`source_type` — nicht das primäre Label, nicht die
   `note`, nicht die Pipeline-Ausgabe. Der erzeugte Bogen enthält diese
   Felder gar nicht erst.
2. **Nach den geschriebenen Ankern.** Für `evidence_certainty` gelten die
   Definitionen aus
   [docs/evidenz-bewertung-anker.md](evidenz-bewertung-anker.md). Das
   misst zugleich, ob diese Anker tragen: Wenn zwei Personen mit
   demselben Regeltext auseinanderlaufen, ist der Regeltext das Problem,
   nicht die Person.
3. **Zweite Person, wenn möglich.** Eine zeitversetzte zweite Runde
   derselben Person misst nur die *Selbst*konsistenz (Test-Retest) und
   ist eine Obergrenze für die Übereinstimmung zwischen Personen. Sie ist
   besser als nichts, muss aber in `protocol.rater` als solche kenntlich
   sein.
4. **Ehrlich deklarieren.** War das primäre Label sichtbar, gehört
   `protocol.blind: false` in die Datei. Das Werkzeug meldet den
   Vergleich dann als nicht unabhängig, statt ihn stillschweigend als
   Baseline zu zählen.
5. Einzelne Felder dürfen `null` bleiben; übersprungene Positionen werden
   nicht verglichen.

### Wie viele Fälle es braucht

Nach demselben Massstab, den OPERATIONS.md an die eigenen Schwellen legt
(ein Umschlag darf eine gattende Metrik um höchstens 0,025 bewegen):
**mindestens 40 doppelt beurteilte Fälle pro Feld**. Darunter meldet das
Werkzeug „independent but underpowered" und nennt die fehlende Anzahl.

Beide Sets sind dafür bereits gross genug — `claim_prefill` hat 50
Beispiele, `relevance` 122. Es fehlt keine Datenerhebung, nur der zweite
Durchgang.

## Die erste gemessene Baseline (2026-08-14)

Ein blinder Durchgang über alle 59 begutachteten Katalog-Claims liegt vor:
[`eval/catalog_second_rater_completed.json`](../eval/catalog_second_rater_completed.json).
Auswertung mit `python scripts/eval_agreement.py --second-rater
eval/catalog_second_rater_completed.json`.

| Feld | Übereinstimmung | Cohens κ | gewichtetes κ |
| --- | --- | --- | --- |
| `evidence_certainty` | 0,780 | 0,503 | **0,649** |
| `claim_type` | 0,797 | 0,714 | — |
| `study_design` | 0,780 | 0,750 | — |
| `effect_direction` | 0,746 | 0,514 | — |
| `claim_supported_by_source` | 0,644 | **0,039** | — |
| `age_range_explicit` | 0,966 | 0,489 | — |
| `evidence_strength` (Legacy) | **0,407** | **0,070** | — |

n = 59, ein Umschlag bewegt 0,017 — über der Schwelle, ab der eine Zahl
ein Gate tragen könnte.

### Die neue Skala ist reproduzierbarer als die alte — aber der Vergleich ist schief

`evidence_certainty` erreicht κ = 0,50, die abgelöste `evidence_strength`
κ = 0,07 — praktisch Zufallsniveau. Das ist die Frage, für die der
Katalog-Bogen gebaut wurde, und die Richtung ist eindeutig.

**Der Faktor ist trotzdem überzeichnet.** Die 59 Certainty-Urteile stammen
von einer Bewerterin, in einer Sitzung, nach einem Regelwerk. Die alten
`evidence_strength`-Werte sind über Monate in verschiedenen
Review-Sitzungen entstanden. Ein Teil des Abstands misst „ein konsistenter
Bewerter gegen viele", nicht „bessere Skala gegen schlechtere".

### Der eigentliche Befund: `claim_supported_by_source` trägt nicht

κ = 0,039 bei 21 Abweichungen — und sie sind **systematisch**. Bei
Rahmenwerken und Policy-Berichten vergab die Zweitbewertung
`partially_supported` (12×) oder `cannot_determine` (8×), wo die primäre
`supported` sagte.

Die beiden Lesarten sind beide mit dem Ankertext vereinbar:

- „Paraphrasiert die Aussage korrekt, was die Quelle sagt?" → `supported`
- „Lässt sich das am Vorliegenden nachprüfen?" → bei einem
  Einzeiler-Abstract eher `cannot_determine`

Das ist ein **Rubrikdefekt**, keine Bewertungsstreuung — die einzige Sorte
Abweichung, die eine Änderung verlangt.

**Behoben in `APPRAISAL_VERSION` 1.2.0.** Der Anker sagt jetzt, dass die
Frage auf den *Inhalt* zielt, und schliesst Kürze als Grund für
`cannot_determine` ausdrücklich aus — die Prüfbarkeit des Auszugs
beantworten `source_verified` und `directness`, und sie hier noch einmal
zu bewerten zählt sie doppelt. Kein gespeicherter Wert ändert sich.

**Die Zahlen oben messen die Regeln der Version 1.1.0.** Der Datensatz
hält das in `protocol.appraisal_method_at_rating` fest, und der Bericht
schreibt es zu jeder Vergleichszeile — sonst läse sich κ = 0,039 später
als Aussage über den geschärften Anker. Ob die Schärfung wirkt, zeigt
erst ein neuer Durchgang.

Zwei kleinere Muster derselben Art: 8× `not_applicable` → `positive` bei
`effect_direction`, und 5× `descriptive` → `policy_report` bei
`study_design` — dort steht der Publikationstyp statt des Designs, also
genau die Verwechslung, gegen die die Trennung gebaut wurde.

### Grenzen dieser Zahl

- **Keine Kalibrierrunde vorab.** Der Durchgang ging direkt über alle 59.
  Die Abweichungen vermischen deshalb „Rubrik war unklar" mit „echte
  Urteilsdifferenz"; sie lassen sich nur nachträglich mit `--explain`
  sortieren, was für diese Messung folgenlos ist (sie ist bereits gebucht),
  für die nächste aber nicht mehr geht.
- **Teilweise nicht streng blind.** Dieselbe Person hatte im Verlauf der
  Arbeit PR-Beschreibungen gelesen, die für rund neun der 59 Claims die
  vergebene Stufe nannten. Nachgerechnet: diese neun stimmen zu **5/9**
  überein, die übrigen 50 zu **41/50 = 0,820**. Die Einschränkung hat das
  Ergebnis also nicht nach oben verzerrt.
- **Ein formal ungültiger Wert** blieb stehen: `age_range_explicit: "4"`
  statt einer Spanne (die Quelle nennt „average age of 4 years", einen
  Mittelwert). Er wurde **nicht** korrigiert — eine Bewertung
  nachträglich zu ändern wäre genau das Wegverhandeln, das die Messung
  wertlos macht. Er zählt als Abweichung und gehört in die Aussprache.
- **Gemessen sind die Katalog-Labels, nicht die des Eval-Sets.** Die
  CI-Schwellen messen gegen `eval/claim_prefill_labeled.json`. Diese Zahl
  darf **nicht** auf sie übertragen werden: das dortige Gold stammt aus
  einer konsistenten Kuratierung, die Katalog-Legacy-Werte nicht. Wer die
  Gates einordnen will, braucht den Prefill-Bogen — der liegt ausgefüllt
  bereit.

## Was mit dem Ergebnis geschieht

Sei **C** die gemessene Label-Übereinstimmung für ein Feld (die Decke) und
**V** der gemessene Pipeline-Wert. Dann gilt:

- **V ≥ C:** Die Pipeline arbeitet auf Höhe des Label-Rauschens. Eine
  Verschärfung des Floors misst ab hier nichts mehr; die richtige Antwort
  ist ein präziserer Anker, nicht ein höheres Gate.
- **Floor > C:** Das Gate verlangt mehr Konsistenz, als die Bewertung
  hergibt. Es muss gesenkt oder die Labelqualität verbessert werden.
- **Floor ≤ C − Spielraum:** Der bestehende Spielraum fängt echte
  Regression ab. Die Herleitung in OPERATIONS.md bleibt gültig und
  bekommt zusätzlich eine Obergrenze, gegen die sie lesbar ist.

Der Bericht wird als **`C = …` neben `V = …`** in OPERATIONS.md
festgehalten, so wie kurate.org 76,1 % neben 79,5 % stellt.

## Was dieses Dokument heute **nicht** tut

Es ändert **keine einzige Schwelle**. `eval_agreement.py` ist kein
CI-Gate: Der einzige heute berechenbare Vergleich ist nicht unabhängig,
und ein Wert, der nichts misst, darf nichts blockieren. Die Floors in
`validate.yml` bleiben exakt dort, wo OPERATIONS.md sie hergeleitet hat.

Was neu ist, ist die Fähigkeit, die Frage überhaupt zu stellen — und ein
Werkzeug, das eine unabhängige Antwort von einer bequemen unterscheidet.

## Grenzen

- Die Übereinstimmung misst **Konsistenz, nicht Richtigkeit**. Zwei
  Bewertende können zuverlässig dasselbe Falsche urteilen; ein hohes
  Kappa schliesst einen geteilten blinden Fleck nicht aus.
- Cohens Kappa ist undefiniert, wenn beide Seiten nur eine Kategorie
  benutzt haben. Das Werkzeug meldet das ausdrücklich, statt eine 1,0
  auszugeben, die wie ein perfektes Ergebnis aussieht.
- Die Auswahl ist verzerrt: Was im kuratierten Set steht, hat jemand für
  bewertungswürdig gehalten; was im geernteten Set steht, hat den
  Relevanzfilter bereits passiert (siehe
  [docs/relevanz-entscheidung.md](relevanz-entscheidung.md)). Eine
  Baseline aus diesen Sets gilt für ihre Region des Eingaberaums, nicht
  für den ganzen.
