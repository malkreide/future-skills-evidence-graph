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

Das ist bewusst schwächer als die Zusage des Kerns. Deshalb ist es eine
getrennte Lane und kein Pipeline-Schritt.

## Abbruch: harte Grenzen vor weichem Urteil

Ein Agent, dessen Abbruch nur von seinem eigenen Urteil abhängt, ist ein
unbegrenzter Kostenposten. Die weiche Entscheidung („genug gefunden") ist der
letzte Filter, nicht der erste:

- **maximal `MAX_ROUNDS` Runden** pro Skill (Default 3),
- **maximal `MAX_QUERIES` Suchanfragen** insgesamt (Default 6),
- **Abbruch bei zwei aufeinanderfolgenden Runden ohne neuen Fund**,
- danach erst das Urteil des Graphen.

Die Grenzen stehen als Konstanten im Modul, nicht im Prompt: eine Schranke, die
das Modell einhalten *soll*, ist keine Schranke.

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

**Decommission**, wenn eines davon eintritt:

1. Die Präzision fällt über drei Läufe unter 0.4.
2. Die Lane erzeugt mehr Reviewaufwand, als der Katalog an Korrektur gewinnt —
   messbar daran, dass über einen Betriebsmonat kein einziger Vorschlag zu einem
   `reviewed` Claim wurde.
3. LangGraph zieht eine Abhängigkeit nach, die sich nicht mehr sauber in
   `requirements-agents.txt` einsperren lässt.

In allen drei Fällen ist das Entfernen ein Verzeichnis-Löschen plus eine
Workflow-Datei — genau dafür ist der Isolations-Vertrag da.
