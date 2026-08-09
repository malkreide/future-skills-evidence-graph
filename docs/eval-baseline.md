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

**Der Bogen für die 50 Prefill-Fälle liegt bereits im Repository:**
[`eval/claim_prefill_second_rater.json`](../eval/claim_prefill_second_rater.json).
Er ist leer und wartet auf einen Durchgang — ausfüllen, `protocol.rater`
und `protocol.labeled_at` setzen, auswerten:

```powershell
python scripts/eval_agreement.py --second-rater eval/claim_prefill_second_rater.json
```

Neu erzeugen (überschreibt einen begonnenen Bogen) oder den
Relevanz-Bogen dazunehmen:

```powershell
python scripts/eval_agreement.py --worksheet claim_prefill --out eval/claim_prefill_second_rater.json
python scripts/eval_agreement.py --worksheet relevance --out eval/relevance_second_rater.json
```

### Was im Bogen steht

Pro Fall: `statement`, `abstract`, `source_type` — und die beiden leeren
Felder `evidence_strength` und `age_range`. Kein `gold`, kein
`_recorded`, keine `note`.

Dazu die **Rubrik im Bogen selbst**: die drei
`evidence_strength`-Ankerdefinitionen werden beim Erzeugen aus
[docs/evidenz-bewertung-anker.md](evidenz-bewertung-anker.md)
ausgelesen, nicht im Code wiederholt. Über 50 Fälle erspart das den
Dokumentwechsel, und eine später geschärfte Ankerdefinition kann nicht
still vom Bogen abweichen — ließe sich die Tabelle nicht lesen, bricht
die Erzeugung ab, statt einen Bogen ohne Rubrik auszuliefern.

Die Reihenfolge bleibt die des Goldsets. Sie wurde geprüft: 30
Kategorienwechsel bei 50 Fällen (unter Zufall ~31 erwartet), längster
gleichartiger Block 4 — es gibt kein Muster, gegen das ein Mischen
schützen müsste.

### Protokoll

1. **Blind.** Die bewertende Person sieht Titel/Abstract bzw.
   Statement/Abstract/`source_type` — nicht das primäre Label, nicht die
   `note`, nicht die Pipeline-Ausgabe. Der erzeugte Bogen enthält diese
   Felder gar nicht erst.
2. **Nach den geschriebenen Ankern.** Für `evidence_strength` gelten die
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
