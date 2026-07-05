# Relevance decision: the three modes

The relevance filter that decides which imported sources survive (pipeline
step 2) is **pluggable**. There are three modes — one heuristic and two optional,
opt-in alternatives — selected through the `RELEVANCE_CLASSIFIER` environment
variable. This document is the single source of truth for the two optional modes,
the measured comparisons behind them, and the rule for when a mode may be
activated or decommissioned.

[README.md](../README.md) carries the high-level summary of the relevance filter;
the operational triggers for acting on these comparisons — and the per-cycle
live-data precision history — live in [OPERATIONS.md](../OPERATIONS.md).

## The default keyword heuristic

Imported candidates pass a keyword relevance filter (`scripts/common.py`): titles
and abstracts are matched against the MVP topic vocabulary and audience terms, the
resulting `relevance_score` (0..1) is stored on each candidate, and topics are
derived from the matched vocabulary instead of being hardcoded. A candidate must
match at least one topic — audience terms ("school", "students") alone do not
qualify a source — and score at or above the threshold (default 0.3, tunable per
importer via `--min-relevance`) to survive before deduplication.

A candidate is additionally rejected when it hits a curated **off-scope** term
(`OFF_SCOPE_KEYWORDS`: e.g. `nutrition`, `menstrual`, `sanitation`, `wastewater`,
`salary`, `refinery`, `soil`, plus clinical, workplace/SME, pandemic-logistics,
physical-education and foreign-language-pedagogy (EAP/EFL/ESL) terms) *and* names
no future skill in its **title**. In-scope papers name the
skill they study in the title, so this drops off-domain papers that only match a
topic keyword in passing — a pupil-health study touching "complexity", a salary
agreement mentioning "collaboration" — while keeping abstract-only in-scope
candidates that carry no off-scope term. The over-broad `complexity` keyword was
also removed from the systems-thinking vocabulary (`computational thinking` and
`systems thinking` remain), as it matched only incidentally.

A candidate is also rejected by the **audience/age gate** (`is_adult_audience`)
when it names an adult / post-secondary audience (`HIGHER_ED_KEYWORDS`: university,
undergraduate, college student, workforce, employee, preservice/in-service
teacher, adult learner …) **and** no school-age audience (`SCHOOL_AGE_KEYWORDS`:
child, kindergarten, primary/secondary/middle/high school, pupil, adolescent …).
Unlike the off-scope filter this has no title-anchor exemption: "AI literacy" is
in scope only for ages 0-18, so a workforce or university AI-literacy paper is
dropped even though it names the skill in the title. Papers naming both audiences
(e.g. "secondary students preparing for university") are kept. The first live
operating cycle showed adult/higher-education papers were the dominant false
positive, so this gate is the highest-value precision lever.

The design is data-driven, not guessed: `eval/relevance_labeled.json` is a labeled
set (122 examples: real candidates from the live runs and live API queries across the
sources, clear anchor cases, the **hard false-positive classes** described
below, plus **German, French and Italian cases** — see the multilingual layer
below) and
`scripts/eval_relevance.py` reports precision/recall/F1 and sweeps
thresholds, so the filter's behavior is measured. On this set the heuristic holds
measured **precision 1.00 at recall 1.00** (F1 1.00): no relevant source is
dropped and no off-scope source is kept, including the hard cases.
`test_relevance_heuristic_meets_measured_floor` guards against regressions
(precision ≥ 0.90, recall ≥ 0.95, with margin below the measured values), and
`test_hard_false_positive_classes_are_dropped` pins the specific fix.

The two classes below were the residual false positives on **fresh** live data.
They are labeled in the set (`origin: hard_case`, all off-scope), and each now has
a dedicated rule so the heuristic drops them (previously it held precision 0.86 by
keeping them):

- **Teacher tool-use** — papers whose studied outcome is a *teacher's* own
  adoption of an AI tool (lesson planning, grading, administrative automation,
  quiz generation), not a future skill cultivated in 0-18 learners. Teachers are a
  legitimate audience, so a blanket teacher gate would cost recall; instead
  `is_teacher_tooluse` drops a source only when a teacher/educator **subject** is
  paired with a productivity/tool-use marker (`EDUCATOR_OFF_KEYWORDS`) **and** no
  strong teacher-education phrase is present — so genuine educator-competence work
  still rides the educator lane, and a learner paper that merely says "automated
  feedback" (no teacher subject) is untouched.
- **Disaster/health with a school-age word** — public-health or disaster-safety
  papers (WASH, nutrition, earthquake preparedness) that name a future-skill topic
  and a school-age audience in the title. The off-scope title-anchor exemption
  keeps abstract-only in-scope papers, so it stays — but an off-scope term in the
  **title** is now decisive (`is_off_scope`): a hygiene/nutrition/disaster paper is
  *about* that off-domain subject, so the co-occurring skill word no longer rescues
  it. (`disaster`/`earthquake` were added to `OFF_SCOPE_KEYWORDS`.)

## Mehrsprachiger Keyword-Layer (Deutsch, Französisch, Italienisch)

Das Projekt ist am Lehrplan 21 verankert, aber alle Keyword-Listen waren rein
englisch — ein deutschsprachiger EDK-/KMK-/PH-Abstract („Förderung von
kritischem Denken und KI-Kompetenz bei Schülerinnen und Schülern") erreichte
Score 0.0 und wurde stillschweigend verworfen. Deutschsprachige Primärquellen
konnten die automatische Pipeline strukturell nicht passieren. Zwei Änderungen
schließen die Lücke:

1. **`normalize_title` ist Unicode-fähig**: Umlaute werden auf ihre
   Basisbuchstaben zurückgeführt (ä→a, ü→u; ß→ss via casefold) statt zu
   verschwinden — vorher wurde „Schülerinnen" zu „sch lerinnen" zerlegt, sodass
   kein deutsches Keyword je matchen konnte. Die Normalisierung wirkt auf beiden
   Seiten des Vergleichs, Keywords sind daher in natürlicher Schreibweise
   gepflegt.
2. **Alle Vokabulare führen deutsche Äquivalente**: Topics (KI-Kompetenz,
   kritisches Denken, Medienkompetenz, …), Audience (Schülerinnen, Unterricht,
   Lehrplan, …), Schulstufen inkl. Schweizer Begriffen (Primarstufe,
   Volksschule, Zyklus 1–3, Sek II/Berufsbildung — Letzteres damit
   berufliche Grundbildung nicht als „adult" gegated wird), Higher-Ed-Gate
   (Hochschule, Studierende, Erwachsenenbildung), Off-Scope (Ernährung,
   Landwirtschaft, Unternehmen, Pandemie, Sportunterricht, …) und die
   Educator-Lane (Lehrerfortbildung, Lehramtsstudierende, Lehrpersonen +
   Kompetenz/Didaktik-Kontext). Da Phrasen exakt gematcht werden (kein
   Stemming), sind gängige Flexionsformen explizit gelistet.

Die beiden anderen Schweizer Schulsprachen folgen demselben Muster:
**Französisch** (Plan d'études romand — élèves/école als Schul-Marker,
étudiants/université als Higher-Ed-Marker, haute école pédagogique als
Educator-Strong-Phrase) und **Italienisch** (Piano di studio — alunni/scuola
vs. studenti universitari, formazione degli insegnanti). Die Unterscheidung
élève↔étudiant bzw. alunni↔studenti universitari trägt dabei das
Audience-Gate.

Das Eval-Set trägt dafür 22 deutsche (`[de]`), 7 französische (`[fr]`) und 6
italienische (`[it]`) Beispiele — Positive inkl. Educator-Lane, Negative aus
Higher-Ed-, Arbeitswelt-, Gesundheits- und Tool-Use-Klassen.
`test_german_sources_pass_the_bilingual_filter` und
`test_french_italian_sources_pass_the_multilingual_filter` pinnen jede
einzelne Klassifikation; `test_normalize_title_folds_german_diacritics` die
Normalisierung (die auch é→e, ç→c faltet). Grenze bleibt: kein Stemming —
seltene Flexionsformen können fehlen; der Recall-Probe-Mechanismus deckt sie
auf.

The per-cycle live-precision history lives in [OPERATIONS.md](../OPERATIONS.md).

## The educator lane

The catalog tracks two audiences (`schemas/skill.schema.json`): the future skills
of learners aged 0-18 (the default) and the competencies of the educators who
enable them, anchored to the UNESCO AI Competency Framework for Teachers. The
learner gate above intentionally drops adult / post-secondary audiences via
`is_adult_audience` — including pre-/in-service teachers — so educator-competence
evidence used to enter only through **manual re-opening** of a dropped source.
The **educator lane** (`scripts/common.py` `is_educator_audience`) automates that
path: running alongside the learner gate, it keeps a topic-anchored, in-scope
source whose **subject is a school educator's own competence** even though it
names an adult audience, and `filter_relevant_sources` tags every survivor with
`audience` (`learner` or `educator`, mirroring the skill schema; absence means
learner). The off-scope gate still runs first, so the lane never resurrects an
off-domain paper.

The lane is deliberately narrow — three rules keep it precise:

- **Strong educator anchors.** Phrases that on their own denote a school
  educator's competence as the subject (teacher education/training/preparation,
  pre-/in-service teachers, teacher competence, teaching AI literacy) keep a
  source outright. These are exempt from the higher-education guard below, because
  teacher training, though university-based, produces *school* teachers.
- **Subject + context.** Failing a strong anchor, a source qualifies only when it
  names an educator **subject** (teacher/educator/teaching staff) *and* a
  competence/development **context** (professional development, competence,
  pedagogy/pedagogical, TPACK, readiness, …). Bare "teacher"/"classroom" mentions
  in a learner study do not qualify — those stay on the learner lane.
- **Two guards.** A **higher-education** context with no school-age signal
  (university, undergraduate, college, faculty, …) is higher-ed faculty teaching
  adults, not a school educator → off the lane. Pure teacher **productivity /
  tool-use** (lesson planning, grading, marking, workload, administrative
  automation) is the educator's office automation, not a teaching competence → off
  the lane, where teacher-tool-use remains the tracked learner-lane false-positive
  class. The vocabulary is teacher-centric ("teacher"/"educator", not
  "faculty"/"lecturer"/"instructor") so the lane targets school educators by
  construction.

The lane is measured against its **own** labeled set,
`eval/relevance_educator.json`, kept separate from the learner
`eval/relevance_labeled.json` on purpose: that curated learner set is the source
of truth for the heuristic and the training input for the optional model and
embedding anchors (whose committed artifacts and fixtures are derived from it), so
educator examples must not perturb it. The set pairs the real reviewed
educator-strand sources (in-service teacher PD in AI literacy, secondary educators'
digital competence, AI literacy in teacher education, pre-service teachers) as
positives with educator-*shaped* negatives that exercise the guards (a
higher-education faculty paper, a teacher grading/workload tool). On it the lane
holds **precision 1.00 / recall 1.00**: every positive is recovered and tagged
`educator`, and neither guard-negative leaks onto the lane. Run it with
`python scripts/eval_relevance.py --educator-lane`. Adding the lane leaves the
learner heuristic's measured floor unchanged (P 1.00 / R 1.00 / F1 1.00 on the
87-example set), and `test_educator_lane_*` guards both the recovery and the
guards against regression.

## Optional trained relevance classifier

The relevance decision is **pluggable**. The default is the keyword heuristic —
transparent, dependency-free, and the fallback whenever anything goes wrong. As an
*opt-in* alternative, `scripts/train_relevance.py` trains a TF-IDF +
LogisticRegression model (scikit-learn) from the label files with a fixed
`random_state` and exports it to a versioned JSON artifact
(`models/relevance_model.json`). The model is consulted at filter time only when the
env flag `RELEVANCE_CLASSIFIER=model` is set **and** a valid artifact is present;
otherwise the heuristic runs. The topic/keyword hits stay an explainable companion
signal next to the model score: even in model mode, `topics` is still derived from the
vocabulary and the `relevance_score`/`topics` data model is unchanged.

The model is wired into the pipeline only if it **measurably beats** the heuristic on
held-out data, and we report that honestly. `python scripts/eval_relevance.py
--compare-model` runs a fair stratified cross-validation: the heuristic needs no
training and is scored on each test fold directly, while the model is retrained on the
train folds and scored on the held-out fold; both report pooled precision/recall/F1.
On the current 122-example set (including the German, French and Italian
cases) the heuristic reaches **F1 1.00** (P 1.00 / R 1.00), and the model
lands at **F1 0.68** (P 0.67 / R 0.69) — it does **not** beat the baseline on
held-out F1. The model trades recall for precision (it rejects some
cases the heuristic now handles directly, but also drops genuine positives),
so **the heuristic stays the default and active decision**; the model ships
disabled for a larger, less separable future label set.

**Reproducibility & trade-off.** Training is reproducible from a fixed seed
(`SEED = 42`, seeding both the classifier and the CV splits) and the artifact records
the seed, the scikit-learn version, the input files and label counts, and the
vectorizer configuration. Inference is pure standard library: `common.py` reproduces
scikit-learn's TF-IDF + logistic-regression math from the JSON artifact, so the
importers stay stdlib-only and never import scikit-learn (it is a dev/CI dependency for
*training* and the comparison). `scripts/train_relevance.py` asserts the stdlib scorer
reproduces scikit-learn's `predict_proba` to < 1e-9, and a sklearn-gated test guards
it. The trade-off is deliberate: the heuristic is fully deterministic and
human-auditable (you can read why a source was kept from its matched topics), whereas a
model trades some of that transparency for the *potential* to generalize. The JSON
artifact keeps the model inspectable and diffable, and keeping the keyword topics as a
companion signal preserves an explainable trace even when the model decides.

## Optional embedding relevance anchors

A second, lighter opt-in signal lives next to the trained model: a pair of
**prototype embeddings** ("anchors"). `scripts/build_relevance_anchors.py` embeds the
labeled examples through `ai_provider.embed` (so it needs an `EMBEDDING_PROVIDER`) and
stores the centroid of the relevant examples and the centroid of the irrelevant ones
in a versioned JSON artifact (`models/relevance_anchors.json`). At filter time, only
when `RELEVANCE_CLASSIFIER=embedding` is set **and** the artifact loads **and** an
embedding provider is configured, a source is kept when it is closer (cosine) to the
positive anchor than to the negative one by at least the artifact's
`decision_threshold`; a missing artifact or provider warns once and falls back to the
keyword heuristic. As with the model, `topics` stays the explainable keyword companion
signal and the `relevance_score`/`topics` data model is unchanged.

**Two embedding providers, one stdlib runtime.** `EMBEDDING_PROVIDER=local` is the
dependency-free, deterministic hashing embedding (256-dim, the CI default).
`EMBEDDING_PROVIDER=st` is a *real local semantic model* — sentence-transformers
`all-MiniLM-L6-v2` (384-dim). `sentence-transformers` is a pure dev/live dependency
(`requirements-dev.txt`), imported lazily and only to fill an embedding-cache *miss*;
each `(model, text)` vector is committed under `tests/fixtures/embeddings/`, so the
`st` path replays **offline and deterministically** in CI without the heavy package or
the network. The committed `models/relevance_anchors.json` is built with `st`, and its
provenance records the `model_name` (`all-MiniLM-L6-v2`) and `model_version`
(the sentence-transformers release), alongside the dimensionality, build date, the
input files and their SHA-256 hashes, and the label counts — so it is reproducible
and diffable.

The anchors are wired in only after a **measured win**.
`EMBEDDING_PROVIDER=st python scripts/eval_relevance.py --compare-embedding` runs the
same fair stratified cross-validation (anchors rebuilt on the train folds, heuristic
scored directly, pooled P/R/F1, honest `VERDICT`). The honest result on the current
122-example set (including the German, French and Italian cases):

| Signal | P | R | F1 | Verdict |
| --- | --- | --- | --- | --- |
| Heuristic (baseline) | 1.00 | 1.00 | **1.00** | active default |
| Embedding anchors, `st` (all-MiniLM-L6-v2) | 0.68 | 0.86 | 0.76 | does **not** beat baseline |
| Embedding anchors, `local` (hashing) | 0.68 | 0.69 | 0.69 | does **not** beat baseline |

The real semantic embedding (`st`, F1 0.76) is a clear step up from the local hashing
embedding (F1 0.69) and recovers more of the hard cases on recall, but it is noisier on
precision and still lands **well below the keyword heuristic** (F1 1.00), which is
already well separated on this small, keyword-shaped set. So **the heuristic stays the
default and active decision** and the anchors ship disabled. The verdict is recorded
honestly here rather than activated; activation would require a positive `VERDICT`.

## Welcher Modus – und warum keiner aktiv ist

| Modus (`RELEVANCE_CLASSIFIER`) | Artefakt | Status | Warum |
| --- | --- | --- | --- |
| `heuristic` (Default) | — | **aktiv** | Transparent, deterministisch, dependency-frei; auf dem Label-Set klar führend (F1 1.00). |
| `model` | `models/relevance_model.json` | deaktiviert | Schlägt die Heuristik im fairen Held-out-Vergleich nicht (F1 0.68 < 1.00 auf dem 122er-Set). |
| `embedding` | `models/relevance_anchors.json` | deaktiviert | Echtes Semantik-Embedding (`st`, all-MiniLM-L6-v2, F1 0.76) schlägt das lokale Hashing (F1 0.69), bleibt aber klar unter der Heuristik (F1 1.00). |

**Aktivierungsregel.** Ein optionaler Modus wird nur dann scharf geschaltet, wenn
er die Heuristik auf Held-out-Daten **messbar schlägt** (positives `VERDICT` aus
`eval_relevance.py --compare-model` bzw. `--compare-embedding`). Erst dann:
Artefakt mit fixem Seed neu bauen (`train_relevance.py` /
`build_relevance_anchors.py`), Artefakt **und** den CV-Verdict gemeinsam committen
und `RELEVANCE_CLASSIFIER` im Workflow-Env setzen (`embedding` zusätzlich mit
`EMBEDDING_PROVIDER`). Bis dahin bleibt die Heuristik der Default — das Gating ist
im Code eingebaut. Die operativen Trigger dazu stehen in
[OPERATIONS.md](../OPERATIONS.md).

**Decommission-Regel.** Die Heuristik ist **immer** der Fallback: Fehlt das
Artefakt (oder bei `embedding` der Provider), warnt der Code einmal und rechnet
heuristisch weiter. Ein aktivierter Modus wird zurückgebaut, sobald er die
Heuristik im wiederholten Vergleich nicht mehr schlägt oder sein Artefakt veraltet
— dann `RELEVANCE_CLASSIFIER` zurück auf `heuristic` (oder Env entfernen) und das
nun ungenutzte Artefakt entfernen. Weil der Default jederzeit allein lauffähig
ist, ist Decommission folgenlos.
