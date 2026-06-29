# Governance und Haltung: Warum ehrliche, auditierbare KI

*Eine Standortbestimmung für Entscheiderinnen und Entscheider in Verwaltung und
Bildung – ohne Technik-Detail, aber mit konkreten Belegen aus diesem Projekt.*

---

## Die Kernhaltung

Dieses Projekt baut einen belegbaren Katalog von Zukunftskompetenzen. Es hätte
naheliegend sein können, modernste KI-Modelle in den Mittelpunkt zu stellen.
Stattdessen folgt das Projekt einer bewussten, unbequemen Entscheidung:

> **KI darf vorschlagen, aber nie entscheiden. Und sie wird erst dann
> eingeschaltet, wenn sie nachweisbar besser ist als eine einfache,
> nachvollziehbare Regel – nicht früher.**

Das ist keine Technik-Vorliebe, sondern eine Vertrauensentscheidung. Wer
öffentliche Bildung mitgestaltet, kann sich kein Werkzeug leisten, das gute
Empfehlungen ausspricht, ohne sagen zu können, *warum*. Die folgenden fünf
Prinzipien sind im Projekt nicht nur behauptet, sondern überprüfbar verankert.

---

## 1. Deterministische Heuristik als Standard

Im Herzstück des Projekts – dem Filter, der entscheidet, welche
wissenschaftlichen Quellen überhaupt in Betracht kommen – arbeitet als
Standardeinstellung eine **transparente, regelbasierte Heuristik**. Sie prüft
nachvollziehbare Kriterien: Passt das Thema? Geht es um die Altersgruppe 0–18?
Taucht ein Ausschlussbegriff auf? Jede Entscheidung lässt sich an den getroffenen
Stichworten ablesen – man kann buchstäblich nachlesen, *weshalb* eine Quelle
behalten oder verworfen wurde.

Das Gegenmodell wäre eine „Black Box", die ein Ergebnis liefert, das niemand
zurückverfolgen kann. Genau das vermeidet das Projekt bewusst – dokumentiert in
der Architektur-Leitentscheidung „Heuristik als Default, Modell optional:
Transparenz und Auditierbarkeit vor Black-Box".

## 2. Modelle bleiben deaktiviert, bis sie messbar besser sind

Das Projekt *hat* fortgeschrittenere KI-Verfahren – es nutzt sie nur nicht
blind. Zwei optionale Alternativen sind vollständig gebaut und liegen versioniert
im Repository:

- ein trainiertes statistisches Modell (`models/relevance_model.json`),
- ein semantisches Embedding-Verfahren auf Basis eines echten Sprachmodells
  (`models/relevance_anchors.json`, `all-MiniLM-L6-v2`).

**Beide sind abgeschaltet.** Der Grund ist nicht Bequemlichkeit, sondern eine
ehrliche Messung. In einem fairen Vergleich auf einem von Hand geprüften
Datensatz (87 Beispiele) erreicht die einfache Heuristik den besten Wert
(F1 0,92). Das trainierte Modell bleibt darunter (F1 0,86), das semantische
Embedding ebenfalls (F1 0,76). Diese Zahlen sind im Projekt nicht beschönigt: Das
Vergleichswerkzeug spricht ein ausdrückliches **„VERDICT"** aus – ein ehrliches
Urteil, das im Klartext festhält, dass die KI-Variante die einfache Regel *nicht*
schlägt. Dieses negative Urteil ist sichtbar dokumentiert, statt unter den Tisch
zu fallen.

Damit wird ein Versprechen eingelöst, das viele KI-Projekte nur behaupten: **Die
aufwendigere Technik gewinnt nur, wenn sie wirklich gewinnt.** Bleibt der Gewinn
aus, bleibt sie als auditierbare, abschaltbare Option liegen.

## 3. Mensch in der Schleife

Die Automatik dieses Projekts produziert ausschließlich **Kandidaten** –
Vorschläge, die sichtbar als „ungeprüft" markiert sind. Kein automatisch
gefundener Eintrag wird je von selbst „offiziell". Erst eine bewusste menschliche
Freigabe macht aus einem Vorschlag einen aktiven Katalogeintrag.

Dieser Schritt ist nicht nur Konvention, sondern erzwungen: Das Freigabe-Werkzeug
(`promote_candidate.py`) verweigert die Veröffentlichung, solange maschinelle
Platzhalter übrig sind, besteht darauf, dass aktive Kompetenzen nur auf geprüften
Aussagen ruhen, und schreibt gar nichts, falls eine Prüfung fehlschlägt.

> Die Maschine ist der fleißige Rechercheassistent. Der Mensch bleibt der
> Chefredakteur.

## 4. Beweis-Pfad-Zwang

Der zentrale Grundsatz des Projekts lautet: **keine Kompetenz ohne Beweis-Pfad.**
Jede aktive Kompetenz muss auf mindestens einer Aussage ruhen, jede Aussage auf
mindestens einer echten Quelle mit exaktem Textbeleg. Man kann von jeder
Empfehlung lückenlos zurückgehen: Kompetenz → Aussage → Quelle.

Auch das ist nicht nur ein Vorsatz, sondern maschinell erzwungen. Eine
Prüfroutine (`validate_data.py`) lässt den gesamten Bauprozess fehlschlagen,
sobald diese Kette irgendwo reißt. Ebenso wird die Vertrauens-Note jeder
Kompetenz **nie von Hand gesetzt**, sondern aus den Belegen berechnet; weicht ein
gespeicherter Wert von der Formel ab, bricht die Prüfung ab. Niemand – auch nicht
die Projektleitung – kann eine Lieblingskompetenz „hochstufen".

## 5. Provenienz und Reproduzierbarkeit

Alles, was eine Maschine beiträgt, trägt seine Herkunft mit sich: Modell-Kennung,
Version, Zeitstempel, die verwendeten Eingabedateien samt Prüfsummen. Die
abgelegten KI-Artefakte sind als lesbare, vergleichbare Dateien gespeichert –
inspizierbar und nachbaubar, nicht in einer undurchsichtigen Datenbank versteckt.

Und das Ganze ist **reproduzierbar**: Die automatisierten Prüfungen laufen ohne
Netzzugriff gegen festgehaltene Testdaten. Wer das Projekt heute oder in einem
Jahr prüft, bekommt dasselbe Ergebnis. Es gibt keinen Server, keine still
driftende Datenbank – nur versionierte Dateien, die sich über die
Versionsverwaltung Zeile für Zeile nachvollziehen lassen.

---

## Warum das für Verwaltung und Bildung zählt

Diese fünf Prinzipien sind kein Selbstzweck. Sie übersetzen sich direkt in die
drei Anforderungen, an denen sich der Einsatz von KI im öffentlichen Sektor
entscheidet:

**Vertrauen.** Eine Empfehlung an Schulen, Lehrpläne oder Bildungspolitik ist nur
so viel wert wie ihre Begründbarkeit. Weil hier jede Empfehlung an Quellen hängt
und jede Note nachgerechnet werden kann, ist Vertrauen nicht eine Frage des
Glaubens an „die KI", sondern eine Frage der Prüfung – die jederzeit jeder
nachvollziehen kann.

**Datenschutz und Datenhoheit.** Das Projekt arbeitet bewusst datei-basiert und
in der Standardeinstellung ohne externe KI-Dienste. Der reguläre Betrieb braucht
keinen Cloud-Anbieter, dem Inhalte zur Verarbeitung übergeben werden. Das
semantische Modell läuft, wo es genutzt wird, lokal. Für eine Verwaltung, die
Datenabflüsse rechtfertigen muss, ist „funktioniert ohne externen Dienst" kein
Nebeneffekt, sondern eine Voraussetzung.

**Nachvollziehbarkeit (Accountability).** Behörden müssen Entscheidungen
begründen können – zunehmend auch regulatorisch (Stichwort algorithmische
Transparenz). Ein System, das jeden Schritt protokolliert, jede maschinelle
Ausgabe mit Herkunft versieht und die menschliche Letztentscheidung erzwingt,
liefert genau die Belegkette, die eine ordentliche Verwaltung verlangt. Die KI
ersetzt hier kein Urteil – sie macht das menschliche Urteil schneller und besser
belegt.

---

## In einem Satz

> Ehrliche, auditierbare KI heißt: das einfachste nachvollziehbare Verfahren als
> Standard, die stärkere Technik erst nach bewiesenem Mehrwert, der Mensch immer
> als letzte Instanz – und alles so dokumentiert, dass Verwaltung und Bildung
> nicht *vertrauen müssen*, sondern *prüfen können*.

---

## Anhang: Blogpost-Entwurf

*Frei verwendbarer Textentwurf für eine Veröffentlichung außerhalb des Repositorys
(LinkedIn, Fachblog, Newsletter). Faktentreu zum Projektstand.*

---

### Wir haben die KI eingebaut – und wieder ausgeschaltet. Mit Absicht.

Es gibt einen Moment in fast jedem KI-Projekt, in dem man sich entscheiden muss:
Vertraut man dem Modell, oder vertraut man dem, was man überprüfen kann?

In unserem **Future Skills Evidence Graph** – einem offenen, quellenbelegten
Katalog von Zukunftskompetenzen für die Bildung – haben wir uns für das
Überprüfbare entschieden. Nicht aus Technikskepsis, sondern aus Respekt vor dem
Kontext: Wer Empfehlungen für Schulen und Lehrpläne ausspricht, muss jede davon
begründen können.

Konkret heißt das: Den Filter, der entscheidet, welche Studien in unseren Katalog
kommen, betreibt im Standard eine schlichte, regelbasierte Heuristik. Man kann an
den getroffenen Stichworten ablesen, warum eine Quelle behalten oder verworfen
wurde. Keine Black Box.

Dabei *hätten* wir es moderner haben können. Wir haben zwei fortgeschrittene
Varianten vollständig gebaut – ein trainiertes Modell und ein semantisches
Embedding-Verfahren auf Basis eines echten Sprachmodells. Beide liegen fertig im
Projekt. Beide sind abgeschaltet.

Warum? Weil wir gemessen haben. In einem fairen Vergleich erreicht die einfache
Regel den besten Wert (F1 0,92), das trainierte Modell bleibt darunter (0,86),
das Embedding ebenfalls (0,76). Unser Vergleichswerkzeug spricht dazu ein
ehrliches „VERDICT" aus – und in diesem Fall lautet es: *Die KI schlägt die
einfache Regel nicht.* Dieses Urteil steht sichtbar in unserer Dokumentation,
statt unter den Tisch zu fallen.

Das ist für uns der Kern von **ehrlicher, auditierbarer KI**:

1. Das Nachvollziehbare ist der Standard.
2. Die stärkere Technik gewinnt nur, wenn sie nachweisbar gewinnt.
3. Der Mensch gibt jede Veröffentlichung frei – die Maschine liefert nur Vorschläge.
4. Keine Empfehlung ohne lückenlosen Beweis-Pfad bis zur Originalquelle.
5. Alles reproduzierbar, mit Herkunftsangabe, ohne stillen Datenabfluss.

Für Verwaltung und Bildung ist das keine akademische Feinheit. Es ist die
Differenz zwischen einem System, dem man *glauben muss*, und einem, das man
*prüfen kann*. Wir glauben, dass öffentliche Institutionen Letzteres verdienen –
gerade beim Thema KI.

*Das Projekt ist offen einsehbar. Wer die Mess-Verdikte selbst nachvollziehen
will, findet die Vergleichswerte und die Aktivierungsregel in der
Projektdokumentation.*

---

*Verwandte Dokumente:* [README.md](../README.md) ·
[architektur.md](architektur.md) ·
[erklaerung-fuer-laien.md](erklaerung-fuer-laien.md) ·
[relevanz-entscheidung.md](relevanz-entscheidung.md) ·
[archiv/ki-weiterentwicklung-plan.md](archiv/ki-weiterentwicklung-plan.md).
</content>
</invoke>
