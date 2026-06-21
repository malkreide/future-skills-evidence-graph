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
        P8["eval/train_relevance.py<br/>Relevanzfilter"]
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
    class SCRIPTS,P1,P2,P3,P4,P5,P6,P7,P8 proc;
```

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

    ING --> DEDUP[deduplicate_sources.py<br/>Dubletten entfernen]
    DEDUP --> FILTER{2 · Relevanzfilter<br/>Topic-Match? Schul-Zielgruppe?<br/>kein Off-Scope-Begriff?}

    FILTER -->|nein| DROP[❌ verworfen]
    FILTER -->|ja| EXTRACT[3 · extract_claims.py<br/>verbatim Befund-Satz → Claim<br/>mit Text-Anker]

    EXTRACT --> CLUSTER[6 · cluster_claims.py<br/>Claims → Kandidaten-Skills]
    CLUSTER --> PR[8 · Pull Request<br/>research/candidates Branch]

    PR --> REVIEW{👤 Mensch prüft<br/>promote_candidate.py}
    REVIEW -->|freigeben| ACTIVE[✅ aktiver Skill<br/>+ Relevanz-Label geerntet]
    REVIEW -->|ablehnen| REJECT[🚫 rejected / deprecated]

    classDef machine fill:#fef7e0,stroke:#f9ab00,color:#1a1a1a;
    classDef human fill:#e6f4ea,stroke:#34a853,color:#1a1a1a;
    class ING,DEDUP,FILTER,EXTRACT,CLUSTER,PR machine;
    class REVIEW,ACTIVE human;
```

**Der Relevanzfilter** (Schritt 2) ist das wichtigste Präzisions-Werkzeug:

- Standard: ein **transparenter Keyword-/Topic-Heuristik-Filter** (deterministisch,
  ohne Abhängigkeiten, immer der Fallback).
- Zusätzliche Tore: **Off-Scope-Begriffe** (z. B. Ernährung, Gehalt) und ein
  **Zielgruppen-Tor** (nur Alter 6–18, keine reinen Hochschul-/Workforce-Paper).
- Optional und **abschaltbar**: ein trainiertes TF-IDF-+-Logistic-Regression-Modell
  (`models/relevance_model.json`) sowie Embedding-Prototyp-Anker
  (`models/relevance_anchors.json`, real-semantisch via sentence-transformers
  `all-MiniLM-L6-v2`, fixture-gestützt offline). Beide sind aktuell **deaktiviert**,
  weil sie die Heuristik im fairen Vergleich (`eval_relevance.py --compare-model`
  bzw. `--compare-embedding`) *nicht* schlagen – die Heuristik führt auf dem
  Label-Set mit F1 0.92 (Modell 0.86, Embedding `st` 0.76).

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

---

## 8. Gesamtbild auf einen Blick

```mermaid
graph TB
    EXT["🌍 Externe Quellen-APIs<br/>OpenAlex · Crossref · S2 · arXiv · ERIC"]
    EXT --> PIPE

    subgraph AUTO["🤖 Automatisierung (schlägt vor)"]
        PIPE["Import → Filter → Extraktion → Clustering"] --> CAND["Kandidaten im PR"]
    end

    CAND --> HUMAN["👤 Menschliche Review<br/>(promote_candidate.py)"]

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
    class EXT ext;
    class PIPE,CAND auto;
    class SRC2,CLM2,SKL2,FWK2 graph;
    class HUMAN,VALID human;
```

---

*Verwandte Dokumente:* [README.md](../README.md) ·
[OPERATIONS.md](../OPERATIONS.md) (Runbook) ·
[erklaerung-fuer-laien.md](erklaerung-fuer-laien.md) (ohne Technik) ·
[lehrplan21-coverage-methodik.md](lehrplan21-coverage-methodik.md).
