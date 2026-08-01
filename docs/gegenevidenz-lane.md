# Gegenevidenz-Lane: eine agentische Suche nach Widerspruch

Dieses Dokument ist die Entscheidungsgrundlage für die **optionale, isolierte
Agenten-Lane**, die aktiv nach Evidenz sucht, die einem aktiven Skill
*widerspricht*. Es beschreibt das Problem, warum diese eine Aufgabe agentisch
ist (und der Kern es nicht ist), den Isolations-Vertrag, und die Antwort auf die
Frage, die alles andere gefährden würde: wie ein nicht-deterministischer Agent
mit dem Reproduzierbarkeitsversprechen dieses Projekts koexistiert.

Format und Verbindlichkeit folgen
[docs/relevanz-entscheidung.md](relevanz-entscheidung.md): eine optionale
Fähigkeit bleibt aus, bis eine Messung sie rechtfertigt, und wie sie wieder
abgeschaltet wird, steht hier drin.

## Das Problem: Confirmation Bias by construction

`score_evidence.py` zieht für widersprechende Claims eine Strafe ab
(`CONTRADICTION_PENALTY`). Das Datenmodell kennt `contradicts_skill_ids`. Die
Mechanik ist also vorhanden — nur füllt sie niemand:

| | |
| --- | --- |
| Claims im Katalog | 146 |
| davon mit `contradicts_skill_ids` | **1** |
| betroffene Skills | `skill-critical-thinking` |

Das ist kein Versäumnis einzelner Reviews, sondern eine strukturelle Eigenschaft
der Pipeline:

1. Die Importer suchen mit kuratierten Queries **nach** Future-Skills-Themen.
2. `extract_claims.py` wählt bevorzugt einen **Befundsatz** — und Befundsätze in
   Abstracts sind überwiegend positiv formuliert („X improves Y"). Null-Resultate
   stehen häufig gar nicht im Abstract, oder in einer Nebenklausel.
3. Der Reviewer sieht nur, was der Import vorgelegt hat.

Jede Stufe verstärkt dieselbe Richtung. Das Ergebnis ist ein Katalog, dessen
`evidence_score` ein **Konfidenzmaß ohne Gegenprobe** ist — und damit genau die
Sorte Zahl, gegen die dieses Projekt sonst sorgfältig anschreibt („no skill
recommendation without an evidence path"). Ein Evidenzgraph, der Widerspruch
bestrafen kann, ihn aber nie sucht, misst seine eigene Suchstrategie.

## Warum *diese* Aufgabe agentisch ist — und der Kern nicht

Der deterministische Kern bleibt, wie er ist. Die Pipeline
discover → dedupe → relevance → extract → cluster → score → PR ist **statisch
und linear**: jeder Schritt kennt seine Eingabe, es gibt keine Verzweigung, die
vom Zwischenergebnis abhängt. Genau deshalb wäre ein Graph-Framework dort reiner
Overhead — das ist die Begründung, aus der dieses Repo LangChain im Kern nicht
verwendet.

Die Gegenevidenz-Suche hat die entgegengesetzte Form:

- **Die Query steht nicht vorab fest.** „Wo widerspricht die Literatur
  *Systems Thinking bei 10-12-Jährigen*?" ist keine Stichwortsuche. Man findet
  Null-Resultate über Formulierungen wie *no significant difference*, *failed to
  replicate*, *effects did not persist* — und welche davon greift, zeigt sich
  erst am Ergebnis der vorherigen Runde.
- **Es gibt eine echte Abbruchentscheidung.** „Genug gesucht" ist ein Urteil
  über die bisherigen Treffer, keine Konstante.
- **Reformulierung ist der Kern der Aufgabe.** Eine erfolglose Runde ist
  Information, die die nächste Query formt.

Iterativ, zustandsbehaftet, mit Verzweigung und Abbruchkriterium — das ist die
Problemform, für die LangGraph gebaut ist. Es kommt hier zum Einsatz, weil die
Aufgabe die Form hat, nicht weil das Framework verfügbar ist.

## Der Isolations-Vertrag

Nicht verhandelbar. Die Lane darf den Kern unter keinen Umständen erreichen:

| Regel | Durchsetzung |
| --- | --- |
| Eigenes Verzeichnis `agents/` | — |
| `scripts/` importiert **nie** aus `agents/` | Test (`test_agent_isolation.py`) |
| Abhängigkeiten in `requirements-agents.txt`, **nicht** in `requirements-dev.txt` | Test |
| CI bleibt grün **ohne** installiertes LangGraph | Die reguläre CI installiert es nicht |
| Nur `workflow_dispatch`, nie im Wochenlauf | — |
| Output ausschließlich `status: candidate` | Wie jeder andere Importer |
| Kein direkter Schreibzugriff auf aktive Records | `promote_candidate.py` bleibt der einzige Weg |

Die Richtung der Abhängigkeit ist einseitig: `agents/` **darf** `scripts/`
benutzen (und soll es — `ai_provider`, `common`, die Schemas), aber nie
umgekehrt. Damit ist die Lane jederzeit löschbar, ohne dass der Kern es merkt.

## Determinismus: die eigentliche Frage

Ein Agent ist nicht-deterministisch. Dieses Projekt verspricht reproduzierbare,
offline nachvollziehbare Läufe. Beides gleichzeitig geht nur mit einer klaren
Trennung — derselben, die das Projekt zwischen *Regression* und *Live-Accuracy*
schon zieht:

**Jeder LLM-Aufruf des Agenten läuft durch `ai_provider.complete`.** Nicht über
`langchain_anthropic` oder ein anderes Provider-Binding. Das ist die zentrale
Design-Entscheidung, und sie bringt drei Dinge auf einmal:

1. **Replay gratis.** `ai_provider` schreibt jede Antwort in den Fixture-Cache.
   Ein aufgezeichneter Lauf ist mit `AI_PROVIDER=cache` exakt wiederholbar —
   dieselbe Maschinerie, die den Claim-Prefill offline testbar macht.
2. **Keine Provider-Pakete.** LangGraph wird **nur als Zustandsmaschine**
   benutzt. Die `langchain-*`-Integrationspakete entfallen komplett, und die
   Lane erbt automatisch jeden Provider aus Punkt 2 (`anthropic`, `openai`,
   `ollama`).
3. **Dieselbe Degradations-Regel.** Fällt der Provider aus, gibt `complete`
   `None` zurück, und der Graph beendet die Runde ohne Vorschlag — statt zu
   scheitern.

Was damit **nicht** behauptet wird: dass der Agent deterministisch *ist*. Ein
frischer Live-Lauf kann bei gleichem Skill andere Queries stellen und andere
Quellen finden. Reproduzierbar ist der **aufgezeichnete** Lauf, und
nachvollziehbar ist der Pfad — jeder Schritt landet in einem Lauf-Protokoll
(`agents/runs/`), das dem Review-PR beiliegt. Ein Reviewer sieht, welche Queries
gestellt wurden, was sie lieferten und warum der Graph abgebrochen hat.

Das Protokoll führt unter `proposed` auch **jeden Vorschlag selbst** — Claim-ID,
Quelle, wörtliches Zitat und die **Begründung des Bewerters**. Eine blosse Anzahl
würde die eine Entscheidung nicht tragen, für die das Protokoll da ist: die
Präzision, über die die Aktivierung läuft, ist ein Urteil über jeden einzelnen
Vorschlag. Die Begründung wiegt dabei am schwersten — ein Zitat kann nach einem
*positiven* Befund klingen, während der Bewerter das Null-Resultat in einem
Nebensatz gesehen hat, den das Zitat abschneidet. Nur die Begründung trennt
diesen Fall vom Fehlalarm. Bei einem Trockenlauf ist das Protokoll ausserdem der
**einzige** Ort, an dem die Vorschläge existieren: Kandidaten werden keine
geschrieben.

Das ist bewusst schwächer als die Zusage des Kerns. Deshalb ist es eine
getrennte Lane und kein Pipeline-Schritt.

## Suchquellen: eine Fallback-Kette, keine Vereinigung

Die Lane fragte anfangs nur OpenAlex ab. Der erste echte Lauf zeigte, warum das
zu wenig ist: OpenAlex antwortete mit HTTP 429, der Lauf prüfte **null** Quellen,
und nichts unterschied „die Literatur schweigt" von „die eine Quelle war
gedrosselt". Beim Suchen nach Gegenevidenz ist das der teuerste
Interpretationsfehler überhaupt — er sieht aus wie eine Bestätigung.

Die Quellen werden **der Reihe nach** probiert, bis eine brauchbare Treffer
liefert:

| Reihenfolge | Quelle | Warum |
| --- | --- | --- |
| 1 | OpenAlex | breiteste Abdeckung |
| 2 | Semantic Scholar | liefert Abstracts, andere Infrastruktur |
| 3 | ERIC | bildungsspezifisch — die Domäne dieses Katalogs |

**Kette statt Vereinigung**, weil jede geprüfte Quelle einen Modellaufruf kostet:
alle drei pro Query abzufragen verdreifachte die Laufkosten für Redundanz, die
nur bei einem Ausfall gebraucht wird.

Weitergereicht wird nicht nur bei einem Fehler, sondern auch, wenn eine Quelle
zwar Treffer liefert, aber **keiner davon einen Abstract trägt** — zehn
abstractlose Treffer sind hier so wertlos wie ein Ausfall.

**Crossref fehlt bewusst.** Diese Lane kann eine Quelle nur beurteilen, wenn sie
einen Abstract hat: ohne ihn gibt es nichts zu bewerten und keinen wörtlichen
Satz, an dem ein Claim ankern könnte. `ingest_crossref.convert` setzt
`abstract: None` fest verdrahtet (Crossref liefert Abstracts nur als spärlich
befülltes JATS-XML). Crossref aufzunehmen hiesse, die Kette um ein Glied zu
verlängern, das nie etwas tragen kann — das sähe nach Redundanz aus, ohne welche
zu sein.

Das Laufprotokoll hält fest, **welche Quelle geantwortet hat** (`backends`).
Ein dünner Ertrag liest sich anders, wenn dort `["eric"]` statt `["openalex"]`
steht.

## Abbruch: harte Grenzen vor weichem Urteil

Ein Agent, dessen Abbruch nur von seinem eigenen Urteil abhängt, ist ein
unbegrenzter Kostenposten. Die weiche Entscheidung („genug gefunden") ist der
letzte Filter, nicht der erste:

- **maximal `MAX_ROUNDS` Runden** pro Skill (Default 5),
- **maximal `MAX_QUERIES` Suchanfragen** insgesamt (Default 12),
- **Abbruch bei zwei aufeinanderfolgenden Runden ohne neuen Fund**,
- danach erst das Urteil des Graphen.

Die Grenzen stehen als Konstanten im Modul, nicht im Prompt: eine Schranke, die
das Modell einhalten *soll*, ist keine Schranke.

**Die ersten beiden sind gekoppelt.** Der Prompt verlangt bis zu 3 Queries pro
Runde, ein Lauf kann also nie mehr als `MAX_ROUNDS × 3` Anfragen stellen. Liegt
`MAX_ROUNDS` zu niedrig, wird das Rundenlimit stillschweigend zum eigentlichen
Budget: `MAX_QUERIES` zu erhöhen ändert dann nichts, und das Laufprotokoll
schreibt `round_limit`, wo in Wahrheit eine Rechnung die Grenze war. Ein Test
(`QueryBudgetCouplingTest`) hält das zusammen.

Die Werte wurden nach dem ersten sauberen Lauf von 3/6 angehoben. Der prüfte 55
Quellen und lieferte **einen** Vorschlag — und über einen Vorschlag kann die
Präzision nur 0.0 oder 1.0 sein. Die Aktivierungsregel unten braucht eine
auflösbare Quote, keinen Münzwurf.

## Was als Widerspruch zählt — die Lehre aus v1

Die ersten beiden gemessenen Läufe lieferten 12 Vorschläge, von denen nach
Durchsicht die wenigsten echte Gegenevidenz waren. Das Problem lag nicht bei der
Suche — die Queries waren gut und die Trefferzahl hoch —, sondern bei einer zu
weiten Definition von „widerspricht" im Assess-Prompt. Zwei Fehlerklassen traten
systematisch auf:

**„Menschen können es nicht" ist kein Gegenargument.** Dass Jugendliche auf
Sensationalismus hereinfallen oder KI-Texte nicht von menschlichen unterscheiden
können, zeigt, dass die Fähigkeit **selten** ist — und das spricht *für* ihre
Bedeutung, nicht gegen ihren Nutzen. Diese Verwechslung erzeugte allein vier der
sieben Vorschläge im `critical-thinking`-Lauf.

**Ein Null-Befund über die falsche Grösse zählt nicht.** Das mittlere Niveau
einer Population gegen einen hypothetischen Mittelwert, oder ausbleibende
Unterschiede *zwischen* Gruppen, sagen nichts darüber, ob die Fähigkeit wirkt.

v2 verlangt deshalb kumulativ: eine **Messung** (kein Positionspapier, keine
Befragung von Meinungen), gemessen als **Ergebnis einer Intervention oder
Exposition**, die den Skill adressiert, und ein Ergebnis, das **ausbleibt, sich
umkehrt oder nicht anhält**.

**Der Anker muss den Befund tragen.** Ein Zitat kann wörtlich aus dem Abstract
stammen und trotzdem der falsche Satz sein — im `critical-thinking`-Lauf war
einmal die Methodenbeschreibung zitiert, während die Begründung einen Befund
nannte, den dieser Satz gar nicht enthält. Anders als die Wörtlichkeit lässt
sich diese Regel **nicht mechanisch prüfen**: der Code verwirft ein nicht
wörtliches Zitat, aber ob ein wörtliches Zitat den Befund *stützt*, kann nur der
Prompt verlangen und ein Reviewer nachhalten. Das ist eine bewusst schwächere
Zusage, und sie steht hier, damit niemand sie für eine harte hält.

## Was die Lane nicht darf

- **Keine aktiven Records ändern.** Sie erzeugt Kandidaten, sonst nichts.
- **Kein Claim ohne Textanker.** Es gilt dieselbe Regel wie überall: ein
  `statement` ist ein wörtliches Zitat mit nachprüfbarer Fundstelle, sonst
  entsteht kein Claim.
- **Keine erfundene Skill-Verknüpfung.** `contradicts_skill_ids` darf nur
  existierende, aktive Skill-IDs enthalten — wie beim Skill-Link-Assist.
- **Kein Automatismus.** Nur `workflow_dispatch`. Eine Lane, die wöchentlich
  ungefragt Widerspruch sucht, produziert Review-Last ohne Anlass.

## Aktivierungs- und Decommission-Regel

Die Lane ist **standardmäßig aus** und in keinen automatischen Workflow
eingebunden. Sie wird erst dann Teil des Betriebs, wenn sie sich bewährt hat:

**Aktivierung** setzt voraus, dass über mindestens **drei manuelle Läufe** die
Präzision der vorgeschlagenen Gegenevidenz — Anteil der Vorschläge, die ein
Reviewer als echten Widerspruch annimmt — bei **≥ 0.5** liegt. Der Schwellwert
ist bewusst niedrig: Gegenevidenz ist selten, und ein Fund unter zwei
Vorschlägen ist mehr, als der heutige Zustand (1 von 146) liefert. Er ist aber
nicht *null* — eine Lane, die überwiegend Fehlalarme produziert, kostet
Reviewzeit und untergräbt das Vertrauen in die Kandidaten-PRs.

**Die drei Läufe müssen denselben `PROMPT_VERSION` teilen.** Die beiden
v1-Läufe (`skill-self-regulated-learning`, `skill-critical-thinking`, Protokolle
unter `agents/runs/`) zählen **nicht** mit: sie haben v2 überhaupt erst
begründet, und eine Quote über zwei verschiedene Bewerter zu mitteln misst
weder den einen noch den anderen. Sie bleiben als Ausgangspunkt liegen — ohne
sie wäre nicht sichtbar geworden, *warum* die Vorschläge danebenlagen, und die
Vermutung wäre auf die Suche gefallen statt auf die Bewertung.

Deshalb steht die Version **im Dateinamen**:
`<datum>-<skill>-<prompt-version>.json`. Ohne sie überschrieb ein v2-Lauf das
v1-Protokoll desselben Skills am selben Tag — ausgerechnet das, was die
Aktivierungsregel unterscheiden muss, war das Einzige, was der Name nicht trug.
Zwei Läufe *derselben* Version am selben Tag fallen weiterhin zusammen, und das
ist richtig: das sind Wiederholungsmessungen, und die neuere gilt. Nur
Versionen dürfen nie verschmelzen. Die Regel ist damit am Verzeichnis ablesbar,
statt in jeder Datei einzeln nachgeschlagen werden zu müssen.

**Decommission**, wenn eines davon eintritt:

1. Die Präzision fällt über drei Läufe unter 0.4.
2. Die Lane erzeugt mehr Reviewaufwand, als der Katalog an Korrektur gewinnt —
   messbar daran, dass über einen Betriebsmonat kein einziger Vorschlag zu einem
   `reviewed` Claim wurde.
3. LangGraph zieht eine Abhängigkeit nach, die sich nicht mehr sauber in
   `requirements-agents.txt` einsperren lässt.

In allen drei Fällen ist das Entfernen ein Verzeichnis-Löschen plus eine
Workflow-Datei — genau dafür ist der Isolations-Vertrag da.
