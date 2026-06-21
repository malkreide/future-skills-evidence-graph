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
in scope only for ages 6-18, so a workforce or university AI-literacy paper is
dropped even though it names the skill in the title. Papers naming both audiences
(e.g. "secondary students preparing for university") are kept. The first live
operating cycle showed adult/higher-education papers were the dominant false
positive, so this gate is the highest-value precision lever.

The design is data-driven, not guessed: `eval/relevance_labeled.json` is a labeled
set (81 examples: real candidates from the live runs and live API queries across the
sources, plus clear anchor cases) and `scripts/eval_relevance.py` reports
precision/recall/F1 and sweeps thresholds, so the filter's behavior is measured.
The off-scope filter and the audience gate hold measured **precision 1.00 at
recall 1.00** on the labeled set (the audience-gated higher-ed/workforce papers
are correctly excluded; no relevant source dropped).
`test_relevance_heuristic_meets_measured_floor` guards against regressions
(precision ≥ 0.90, recall ≥ 0.90, with margin below the measured values).

On **fresh** live data the eval-set 1.00 is optimistic: the remaining false
positives are harder classes (teacher tool-use, and disaster/health papers that
carry a school-age word). The per-cycle live-precision history lives in
[OPERATIONS.md](../OPERATIONS.md).

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
On the current 54-example set the heuristic already reaches **F1 1.00** (P 1.00 / R
1.00), and the model lands at **F1 ≈ 0.84** (P 0.94 / R 0.76) — it does **not** beat
the baseline. The data is small and the heuristic is already saturated, so **the
heuristic stays the default and active decision**; the model ships disabled for a
larger, less separable future label set.

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
labeled examples through `ai_provider.embed` (so it needs an `EMBEDDING_PROVIDER`, e.g.
the dependency-free, deterministic `EMBEDDING_PROVIDER=local`) and stores the centroid
of the relevant examples and the centroid of the irrelevant ones in a versioned JSON
artifact (`models/relevance_anchors.json`). At filter time, only when
`RELEVANCE_CLASSIFIER=embedding` is set **and** the artifact loads **and** an embedding
provider is configured, a source is kept when it is closer (cosine) to the positive
anchor than to the negative one by at least the artifact's `decision_threshold`; a
missing artifact or provider warns once and falls back to the keyword heuristic. As with
the model, `topics` stays the explainable keyword companion signal and the
`relevance_score`/`topics` data model is unchanged.

The anchors are wired in only after a **measured win**. `EMBEDDING_PROVIDER=local python
scripts/eval_relevance.py --compare-embedding` runs the same fair stratified
cross-validation (anchors rebuilt on the train folds, heuristic scored directly,
pooled P/R/F1, honest `VERDICT`). With the local hashing embedding the anchors land well
below the saturated heuristic, so **the heuristic stays the default and active
decision** and the anchors ship disabled. The artifact records its provenance — the
embedding provider, dimensionality, build date, the input files and their SHA-256
hashes, and the label counts — so it is reproducible and diffable.

## Welcher Modus – und warum keiner aktiv ist

| Modus (`RELEVANCE_CLASSIFIER`) | Artefakt | Status | Warum |
| --- | --- | --- | --- |
| `heuristic` (Default) | — | **aktiv** | Transparent, deterministisch, dependency-frei; auf dem Label-Set bereits gesättigt (F1 1.00). |
| `model` | `models/relevance_model.json` | deaktiviert | Schlägt die Heuristik im fairen Held-out-Vergleich nicht (F1 ≈ 0.84 < 1.00). |
| `embedding` | `models/relevance_anchors.json` | deaktiviert | Liegt mit dem lokalen Hashing-Embedding klar unter der gesättigten Heuristik. |

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
