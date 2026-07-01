# Architektur des Future Skills Evidence Graph

*Eine verständliche Erklärung der Lösung – mit Diagrammen.*

Dieses Dokument erklärt, **wie** die Anwendung aufgebaut ist und **wie die Teile
zusammenspielen**. Die fachliche Idee „keine Kompetenz ohne Beweis-Pfad" wird in
[erklaerung-fuer-laien.md](erklaerung-fuer-laien.md) ohne Technik beschrieben –
hier geht es um die technische Architektur.

---

## 1. Das Grundprinzip in einem Satz

> Ein **versioniertes, statisches Daten-Repository** (kein Server, keine
> Datenbank) bildet einen Wissensgraphen aus *Quellen → Aussagen → Kompetenzen →
> Frameworks*. Skripte befüllen, prüfen und veröffentlichen diesen Graphen;
> Menschen geben über Pull Requests frei.

Die ganze Lösung ist bewusst **datei-basiert**: Alle Inhalte liegen als JSON in
`data/`, werden durch JSON-Schemas validiert und durch Python-Skripte
verarbeitet. Es gibt keine laufende Server-Komponente – die „Anwendung" ist ein
Build-Schritt, der eine statische Webseite erzeugt.

---

## 2. Das Datenmodell (der Graph)

Das Herz der Lösung sind vier Datentypen, die wie eine Beweiskette
zusammenhängen. Jeder Pfeil ist eine erzwungene Referenz.

```mermaid
graph LR
    SRC["📄 Source<br/><i>Quelle</i><br/>Studie / Bericht / Politik-Dokument"]
    CLM["🔖 Claim<br/><i>Aussage</i><br/>strukturierte Evidenz aus einer Quelle"]
    SKL["🎯 Skill<br/><i>Kompetenz</i><br/>Zukunftsfähigkeit (aktiv / Kandidat)"]
    FWK["🗺️ FrameworkMapping<br/>Abbildung auf externe Rahmenwerke<br/>(UNESCO, DigComp, Lehrplan 21)"]

    CLM -->|"references (≥ 1)"| SRC
    SKL -->|"supporting_claim_ids (≥ 1)"| CLM
    SKL -. "contradicting_claim_ids" .-> CLM
    SKL -->|"framework_mapping_ids"| FWK

    classDef source fill:#e8f0fe,stroke:#4285f4,color:#1a1a1a;
    classDef claim fill:#fef7e0,stroke:#f9ab00,color:#1a1a1a;
    classDef skill fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    classDef fwk fill:#fce8e6,stroke:#ea4335,color:#1a1a1a;
    class SRC source;
    class CLM claim;
    class SKL skill;
    class FWK fwk;
```

**Die eisernen Regeln (von `validate_data.py` erzwungen):**

- Jede **aktive** Kompetenz braucht ≥ 1 stützende Aussage.
- Jede Aussage braucht ≥ 1 Quelle samt exaktem Text-Anker.
- Unfertige Einträge bleiben sichtbar als `candidate` markiert.

Die Schemas dazu liegen in `schemas/` (`source.schema.json`, `claim.schema.json`,
`skill.schema.json`, `framework_mapping.schema.json`).

---

## 3. Die Komponenten-Landkarte

So sind die Verzeichnisse und ihre Rollen verteilt:

```mermaid
graph TB
    subgraph DATA["📦 data/ – die Wahrheit (versioniert)"]
        D1[sources/]
        D2[claims/]
        D3[skills/]
        D4[frameworks/]
    end

    subgraph SCHEMA["📐 schemas/ – Verträge"]
        S1[*.schema.json]
    end

    subgraph SCRIPTS["⚙️ scripts/ – Verarbeitung (Python, stdlib)"]
        P1["ingest_*.py<br/>Quellen importieren"]
        P2["extract_claims.py<br/>Aussagen extrahieren"]
        P3["cluster_claims.py<br/>zu Kandidaten clustern"]
        P4["score_evidence.py<br/>Evidenz bewerten"]
        P5["validate_data.py<br/>alles prüfen"]
        P6["build_site.py<br/>Webseite bauen"]
        P7["promote_candidate.py<br/>Freigabe durch Mensch"]
        P8["train_relevance.py<br/>Relevanzfilter"]
        P9["ingest_websearch.py<br/>Grau-Literatur-Suche"]
        P10["triage_candidates.py<br/>Review-Arbeitsblatt"]
    end

    subgraph SITE["🌐 site/ – statisches Dashboard"]
        W1[index.html]
        W2[assets/app.js]
        W3[assets/styles.css]
    end

    subgraph CI["🤖 .github/workflows/ – Automatisierung"]
        C1[research-pipeline.yml]
        C2[validate.yml]
        C3[deploy-pages.yml]
    end

    SCHEMA -. validiert .-> DATA
    SCRIPTS -->|liest/schreibt| DATA
    P6 -->|"erzeugt data/index.json"| SITE
    CI -->|"führt aus"| SCRIPTS
    C3 -->|"published"| PAGES["☁️ GitHub Pages"]

    classDef data fill:#e8f0fe,stroke:#4285f4,color:#1a1a1a;
    classDef proc fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    class DATA,D1,D2,D3,D4 data;
    class SCRIPTS,P1,P2,P3,P4,P5,P6,P7,P8,P9,P10 proc;
```

Nur `validate.yml` läuft verpflichtend bei jedem Push. Der Wochenlauf
(`research-pipeline.yml`) wird durch **manuell ausgelöste** Workflows ergänzt:
`ingest-websearch.yml` (Grau-Literatur-Suche), `ingest-from-issue.yml` und
`ingest-reports.yml` (Bericht-Import), `resolve-url-check.yml`
(URL-Auflösungs-Diagnose) und `eval-prefill-record.yml` (LLM-Prefill-Baseline).

---

## 4. Die Forschungs-Pipeline (Maschine schlägt vor)

Der wöchentliche Workflow füllt den Graphen mit **Kandidaten**. Wichtig: jeder
Schritt ist bewusst konservativ und nichts wird automatisch „aktiv".

```mermaid
flowchart TD
    START([⏰ Wöchentlicher Lauf]) --> ING

    subgraph ING["1 · Discover"]
        OA[OpenAlex] & CR[Crossref] & SS[Semantic Scholar] & AX[arXiv] & ER[ERIC]
    end

    WEB["🔎 Web-Suche (manuell)<br/>ingest_websearch.py<br/>SearXNG · DuckDuckGo"] --> DEDUP

    ING --> DEDUP[deduplicate_sources.py<br/>Dubletten entfernen]
    DEDUP --> FILTER{2 · Relevanzfilter<br/>Topic-Match? Schul-Zielgruppe?<br/>kein Off-Scope-Begriff?}

    FILTER -->|nein| DROP[❌ verworfen]
    FILTER -->|ja| EXTRACT[3 · extract_claims.py<br/>verbatim Befund-Satz → Claim<br/>mit Text-Anker]

    EXTRACT --> CLUSTER[6 · cluster_claims.py<br/>Claims → Kandidaten-Skills]
    CLUSTER --> PR[8 · Pull Request<br/>research/candidates Branch]

    PR --> TRIAGE[triage_candidates.py<br/>Review-Arbeitsblatt]
    TRIAGE --> REVIEW{👤 Mensch prüft<br/>promote_candidate.py}
    REVIEW -->|freigeben| ACTIVE[✅ aktiver Skill<br/>+ Relevanz-Label geerntet]
    REVIEW -->|ablehnen| REJECT[🚫 rejected / deprecated]

    classDef machine fill:#fef7e0,stroke:#f9ab00,color:#1a1a1a;
    classDef human fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    class ING,DEDUP,FILTER,EXTRACT,CLUSTER,PR,WEB,TRIAGE machine;
    class REVIEW,ACTIVE human;
```

**Der Relevanzfilter** (Schritt 2) ist das wichtigste Präzisions-Werkzeug:

- Standard: ein **transparenter Keyword-/Topic-Heuristik-Filter** (deterministisch,
  ohne Abhängigkeiten, immer der Fallback).
- Zusätzliche Tore: **Off-Scope-Begriffe** (z. B. Ernährung, Gehalt) und ein
  **Zielgruppen-Tor** (nur Alter 0–18, keine reinen Hochschul-/Workforce-Paper).
- Optional und **abschaltbar**: ein trainiertes TF-IDF-+-Logistic-Regression-Modell
  (`models/relevance_model.json`) sowie Embedding-Prototyp-Anker
  (`models/relevance_anchors.json`, real-semantisch via sentence-transformers
  `all-MiniLM-L6-v2`, fixture-gestützt offline). Beide sind aktuell **deaktiviert**,
  weil sie die Heuristik im fairen Vergleich (`eval_relevance.py --compare-model`
  bzw. `--compare-embedding`) *nicht* schlagen – die Heuristik führt auf dem
  Label-Set mit F1 0.92 (Modell 0.86, Embedding `st` 0.76).

### 4a · Manueller Eingang (Mensch reicht selbst ein)

Neben dem wöchentlichen Lauf kann ein Mensch einen Bericht (OECD / WEF / UNESCO
o. ä.) **jederzeit selbst einreichen** – per Drag & Drop im Dashboard, über ein
Issue-Formular oder per Workflow-Dispatch. Alle drei Wege münden in **denselben
Kandidaten-PR und dieselben Guard Rails** wie die Pipeline; nichts wird
automatisch aktiv.

```mermaid
flowchart TD
    DASH["🌐 Dashboard-Dropzone<br/>site/einreichen.html<br/>Drag&Drop · PDF→Text (pdf.js) · mobil"]
    FORM["📝 Issue-Formular<br/>ingest-report.yml · Label ingest"]
    DISP["⚙️ workflow_dispatch<br/>ingest-reports.yml"]

    DASH -->|"vorausgefülltes Issue<br/>(kein Token im Browser)"| FORM
    FORM --> WF["ingest-from-issue.yml<br/>parse_ingest_issue.py<br/>Text · PDF-Anhang · PDF-URL"]
    DISP --> IMP
    WF --> IMP["ingest_reports.py (LLM)<br/>verbatim Befund → Claim"]
    IMP --> CANDPR["Kandidaten im<br/>research/candidates-PR"]
    CANDPR --> REVIEW2["👤 Menschliche Review<br/>promote_candidate.py"]

    classDef ui fill:#e8f0fe,stroke:#4285f4,color:#1a1a1a;
    classDef machine fill:#fef7e0,stroke:#f9ab00,color:#1a1a1a;
    classDef human fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    class DASH,FORM,DISP ui;
    class WF,IMP,CANDPR machine;
    class REVIEW2 human;
```

Der **Verbatim-Guard** gilt auch hier: jede vom LLM vorgeschlagene Aussage muss
ein wörtliches Zitat des Berichtstexts sein, sonst wird sie verworfen. Die
Dashboard-Seite hält bewusst **kein Secret** – sie liest die Datei lokal und
öffnet nur ein vorausgefülltes Issue, das der Mensch bestätigt; die Anmeldung
übernimmt GitHub. Eine reine PDF-URL wird erst serverseitig (im Workflow)
gelesen. Details: [report-import.md](report-import.md).

### 4b · Web-Suche (graue Literatur, manuell)

Neben den fünf Katalog-APIs gibt es eine **nur manuell ausgelöste** Discovery-Lane
für graue Literatur: `scripts/ingest_websearch.py` (Workflow `ingest-websearch.yml`,
nur `workflow_dispatch`) stellt eine Topic-Suchanfrage an offene Backends
(SearXNG, keyless DuckDuckGo, optional Google) und legt Treffer als
Kandidaten-Quellen an – genau jene, die die schlüssellosen Kataloge nie zeigen.
Die Strategie ist **offene Suche, gestufter Trust** (`data/source_domains.json`):
jede Fundstelle bekommt eine Trust-Stufe (`trusted`/`watch`/`open`), aber die
Stufe ist nur ein **Label** für die Triage-Reihenfolge – sie ist kein Filter und
fließt **nicht** in den `evidence_score`. Web-Treffer bleiben
`source_type: web_resource` (niedrigstes Gewicht) und minten **keine** Claims;
diese entstehen weiterhin verbatim über `extract_claims.py` /
`ingest_reports.py`. `scripts/audit_domains.py` (`make audit-domains`) leitet aus
den Review-Entscheidungen evidenzbasiert ab, welche Domains eine Trust-Stufe
verdienen (siehe [allowlist-pflegen.md](allowlist-pflegen.md)).

---

## 5. Das Vertrauens-Prinzip: Mensch + reproduzierbare Bewertung

Zwei Dinge sorgen dafür, dass dem Katalog vertraut werden kann:

```mermaid
flowchart LR
    subgraph SCORE["Evidenz-Score (reproduzierbar berechnet)"]
        Q["Quellen-Qualität<br/>60 %"] --> CS[Claim-Score]
        E["Evidenz-Stärke<br/>40 %"] --> CS
        CS --> AGG["Aggregation pro Skill<br/>Mittelwert × Breite − Widersprüche"]
        AGG --> ES[("evidence_score 0–1")]
    end

    ES -. "validate_data.py prüft:<br/>gespeichert == neu berechnet" .-> GUARD{Drift?}
    GUARD -->|ja| FAIL[❌ CI schlägt fehl]
    GUARD -->|nein| OK[✅]
```

Der `evidence_score` wird **nie von Hand gesetzt** – `score_evidence.py` berechnet
ihn, und `validate_data.py` lässt den Build fehlschlagen, sobald ein gespeicherter
Wert von der Formel abweicht. So bleibt das Vertrauenssignal des Dashboards immer
reproduzierbar.

Die **menschliche Freigabe** (`promote_candidate.py`) ist das zweite Prinzip: Sie
verweigert die Freigabe, solange maschinelle Platzhalter übrig sind, erzwingt,
dass aktive Skills nur auf geprüften Claims ruhen, berechnet die Scores neu und
re-validiert – und schreibt nichts, falls eine Prüfung fehlschlägt.

Damit der Mensch den offenen Kandidaten-Rückstand überblickt, bündelt
`scripts/triage_candidates.py` alle offenen Kandidaten zu einem geordneten
Review-Arbeitsblatt (verbatim-Aussage, Topics, Quelle(n), optionale
LLM-`assist`-Vorschläge) samt den exakten `promote_candidate.py`-Befehlen. Es
schreibt nichts nach `data/` und promotet nichts – es ist reine Lesehilfe vor der
menschlichen Entscheidung.

---

## 6. Vom Daten-Commit zur Webseite (Veröffentlichung)

```mermaid
sequenceDiagram
    participant Dev as 👤 Mensch (PR)
    participant Repo as 📦 data/*.json
    participant CI as 🤖 GitHub Actions
    participant Val as validate_data.py
    participant Build as build_site.py
    participant Pages as ☁️ GitHub Pages
    participant User as 🧑‍💻 Besucher

    Dev->>Repo: ändert/ergänzt Daten
    Repo->>CI: Push / Merge
    CI->>Val: Schema + Score + Beweis-Pfad prüfen
    Val-->>CI: OK (sonst Abbruch)
    CI->>Build: data/index.json erzeugen + site/ kopieren
    Build->>Pages: statische Seite deployen
    User->>Pages: öffnet Dashboard
    Pages-->>User: app.js lädt index.json,<br/>zeigt Skills, Beweis-Pfade,<br/>Lehrplan-21-Vergleich (Radar)
```

Das Dashboard ist rein statisch: `app.js` liest die einzige generierte Datei
`data/index.json` und rendert daraus alle Ansichten – inkl. des Lehrplan-21-
Vergleichs mit Radar-Chart, Zyklus-Filter, Abdeckungstabelle und Lücken-Labels.

---

## 7. Warum diese Architektur? (Die Leitentscheidungen)

| Entscheidung | Begründung |
| --- | --- |
| **Datei-basiert, kein Server/DB** | Versionierbar, diff-bar, prüfbar über Git; nichts läuft dauerhaft, nichts kann „still" driften. |
| **JSON-Schemas als Verträge** | Datenqualität wird maschinell erzwungen, nicht per Konvention erhofft. |
| **Nur Standardbibliothek im Import-/Inferenzpfad** | Importer bleiben dependency-frei und robust; scikit-learn nur als Dev-/CI-Abhängigkeit fürs *Training*. |
| **Mensch-in-der-Schleife über Pull Requests** | Automatik erzeugt nur Kandidaten; Veröffentlichung ist immer eine bewusste menschliche Entscheidung. |
| **Reproduzierbare Scores statt Handnoten** | Niemand kann eine Lieblingskompetenz „hochstufen"; das Vertrauenssignal ist nachrechenbar. |
| **Heuristik als Default, Modell optional** | Transparenz und Auditierbarkeit vor Black-Box; das Modell wird nur aktiv, wenn es messbar besser ist. |
| **Graceful Degradation der Importer** | Fällt eine Quelle aus, laufen die anderen weiter – der wöchentliche Lauf bricht nicht ab. |
| **Offene Web-Suche, gestufter Trust (Label statt Filter)** | Graue Literatur wird gefunden (guter Recall), aber Domain-Vertrauen ordnet nur die Triage-Reihenfolge – es verzerrt nie den reproduzierbaren `evidence_score`. |

---

## 8. Gesamtbild auf einen Blick

```mermaid
graph TB
    EXT["🌍 Externe Quellen-APIs<br/>OpenAlex · Crossref · S2 · arXiv · ERIC"]
    WEBSRC["🔎 Web-Suche (manuell)<br/>graue Literatur"]
    EXT --> PIPE
    WEBSRC --> PIPE

    subgraph AUTO["🤖 Automatisierung (schlägt vor)"]
        PIPE["Import → Filter → Extraktion → Clustering"] --> CAND["Kandidaten im PR"]
        CAND --> TRIAGE["🗂️ Triage-Arbeitsblatt<br/>(triage_candidates.py)"]
    end

    TRIAGE --> HUMAN["👤 Menschliche Review<br/>(promote_candidate.py)"]

    subgraph GRAPH["📦 Evidenz-Graph (versioniert in data/)"]
        SRC2[Sources] --> CLM2[Claims] --> SKL2[Skills] --> FWK2[Frameworks]
    end

    HUMAN -->|"freigegeben"| GRAPH
    GRAPH --> VALID["✅ validate_data.py<br/>(Schema · Score · Beweis-Pfad)"]
    VALID --> BUILD2["build_site.py → index.json"]
    BUILD2 --> DASH["🌐 Statisches Dashboard<br/>GitHub Pages"]

    classDef ext fill:#f1f3f4,stroke:#5f6368,color:#1a1a1a;
    classDef auto fill:#fef7e0,stroke:#f9ab00,color:#1a1a1a;
    classDef graph fill:#e8f0fe,stroke:#4285f4,color:#1a1a1a;
    classDef human fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    class EXT,WEBSRC ext;
    class PIPE,CAND,TRIAGE auto;
    class SRC2,CLM2,SKL2,FWK2 graph;
    class HUMAN,VALID human;
```

---

*Verwandte Dokumente:* [README.md](../README.md) ·
[OPERATIONS.md](../OPERATIONS.md) (Runbook) ·
[erklaerung-fuer-laien.md](erklaerung-fuer-laien.md) (ohne Technik) ·
[report-import.md](report-import.md) (manueller Bericht-Import) ·
[lehrplan21-coverage-methodik.md](lehrplan21-coverage-methodik.md).
