"""Train the OPTIONAL relevance classifier (TF-IDF + LogisticRegression).

Roadmap step 2 (classify relevance) ships a deterministic keyword heuristic by
default. This script trains a small scikit-learn model from the labeled sets
(eval/relevance_labeled.json, optionally plus eval/relevance_harvested.json) and
exports it to a versioned, human-readable JSON artifact (models/relevance_model.json).

The artifact stores the fitted vocabulary, idf weights, logistic-regression
coefficients and intercept -- everything needed to score a source -- so the
importers can consult the model with pure standard-library math
(common.model_relevance_probability) and stay dependency-free. Only THIS training
step needs scikit-learn.

Reproducibility:
- A fixed random_state (SEED) seeds LogisticRegression and the CV splits.
- The artifact records the seed, the scikit-learn version, the input files and
  their label counts, and the vectorizer configuration.
- After training, the script asserts that the stdlib reimplementation reproduces
  scikit-learn's predict_proba to < 1e-9, guarding the reimplementation.

    python scripts/train_relevance.py                 # train + write artifact
    python scripts/train_relevance.py --include-harvested
    python scripts/train_relevance.py --dry-run       # train + self-check, no write

Whether the model should actually be wired into the pipeline is a separate,
honest question answered by scripts/eval_relevance.py --compare-model (fair
held-out comparison vs the heuristic). The default stays the heuristic.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from common import (
    RELEVANCE_MODEL_PATH,
    ROOT,
    load_json,
    model_relevance_probability,
    source_text,
    write_json,
)


SEED = 42
ARTIFACT_FORMAT_VERSION = 1
DECISION_THRESHOLD = 0.5

EVAL_PATH = ROOT / "eval" / "relevance_labeled.json"
HARVESTED_PATH = ROOT / "eval" / "relevance_harvested.json"

# Vectorizer configuration. Kept explicit and faithfully reproducible by the
# stdlib scorer: smooth idf, L2 norm, no stop-word list (so n-gram boundaries
# match exactly; common tokens are simply down-weighted by the classifier).
VECTORIZER_PARAMS: dict[str, Any] = {
    "lowercase": True,
    "ngram_range": (1, 1),
    "min_df": 2,
    "sublinear_tf": False,
    "norm": "l2",
    "smooth_idf": True,
    "stop_words": None,
}


def build_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(**VECTORIZER_PARAMS)


def build_classifier() -> LogisticRegression:
    # class_weight balances the modest positive/negative skew; lbfgs is
    # deterministic given the fixed seed and bounded iterations.
    return LogisticRegression(
        random_state=SEED,
        max_iter=1000,
        class_weight="balanced",
    )


def load_examples(include_harvested: bool) -> tuple[list[str], list[int], list[str]]:
    """Return (texts, labels, source_files) from the labeled sets."""
    payload = load_json(EVAL_PATH)
    examples = list(payload["examples"])
    files = [str(EVAL_PATH.relative_to(ROOT))]
    if include_harvested and HARVESTED_PATH.exists():
        harvested = load_json(HARVESTED_PATH)
        harvested_examples = (
            harvested.get("examples", []) if isinstance(harvested, dict) else []
        )
        if harvested_examples:
            examples.extend(harvested_examples)
            files.append(str(HARVESTED_PATH.relative_to(ROOT)))
    texts = [source_text({"title": ex.get("title"), "abstract": ex.get("abstract")}) for ex in examples]
    labels = [1 if ex.get("relevant") else 0 for ex in examples]
    return texts, labels, files


def fit_model(
    texts: list[str], labels: list[int]
) -> tuple[TfidfVectorizer, LogisticRegression]:
    vectorizer = build_vectorizer()
    matrix = vectorizer.fit_transform(texts)
    classifier = build_classifier()
    classifier.fit(matrix, labels)
    return vectorizer, classifier


def build_artifact(
    vectorizer: TfidfVectorizer,
    classifier: LogisticRegression,
    texts: list[str],
    labels: list[int],
    files: list[str],
) -> dict[str, Any]:
    vocabulary = {term: int(index) for term, index in vectorizer.vocabulary_.items()}
    return {
        "model_type": "tfidf+logreg",
        "format_version": ARTIFACT_FORMAT_VERSION,
        "decision_threshold": DECISION_THRESHOLD,
        "vectorizer": {
            "ngram_range": list(VECTORIZER_PARAMS["ngram_range"]),
            "sublinear_tf": VECTORIZER_PARAMS["sublinear_tf"],
            "norm": VECTORIZER_PARAMS["norm"],
            "smooth_idf": VECTORIZER_PARAMS["smooth_idf"],
            "vocabulary": vocabulary,
            "idf": [float(value) for value in vectorizer.idf_.tolist()],
        },
        "classifier": {
            "coef": [float(value) for value in classifier.coef_[0].tolist()],
            "intercept": float(classifier.intercept_[0]),
        },
        "training": {
            "seed": SEED,
            "sklearn_version": sklearn.__version__,
            "trained_at": date.today().isoformat(),
            "n_examples": len(labels),
            "n_relevant": int(sum(labels)),
            "n_features": int(len(vocabulary)),
            "label_files": files,
        },
    }


def self_check(
    artifact: dict[str, Any],
    vectorizer: TfidfVectorizer,
    classifier: LogisticRegression,
    texts: list[str],
) -> float:
    """Assert the stdlib scorer reproduces sklearn's predict_proba.

    Returns the maximum absolute probability difference over the training texts.
    """
    sklearn_probs = classifier.predict_proba(vectorizer.transform(texts))[:, 1]
    max_diff = 0.0
    for text, expected in zip(texts, sklearn_probs):
        got = model_relevance_probability({"title": text, "abstract": ""}, artifact)
        max_diff = max(max_diff, abs(got - float(expected)))
    return max_diff


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the optional relevance classifier.")
    parser.add_argument("--include-harvested", action="store_true")
    parser.add_argument(
        "--output",
        default=str(RELEVANCE_MODEL_PATH),
        help="Where to write the JSON artifact.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Train and self-check, but do not write the artifact.",
    )
    args = parser.parse_args()

    texts, labels, files = load_examples(args.include_harvested)
    print(f"Training on {len(labels)} examples ({sum(labels)} relevant) from {', '.join(files)}.")

    vectorizer, classifier = fit_model(texts, labels)
    artifact = build_artifact(vectorizer, classifier, texts, labels, files)
    print(f"Fitted {artifact['training']['n_features']} TF-IDF features (ngram {VECTORIZER_PARAMS['ngram_range']}).")

    max_diff = self_check(artifact, vectorizer, classifier, texts)
    print(f"Stdlib reproduction self-check: max |Δprob| = {max_diff:.2e}")
    if max_diff > 1e-9:
        print("FAIL: stdlib scorer does not reproduce scikit-learn within tolerance.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run: artifact not written.")
        return 0

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    write_json(output, artifact)
    print(f"Wrote model artifact to {output.relative_to(ROOT)} (seed {SEED}, sklearn {sklearn.__version__}).")
    print("The heuristic remains the pipeline default; run eval_relevance.py --compare-model to compare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
