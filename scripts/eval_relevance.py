"""Evaluate the keyword relevance heuristic against a labeled set.

Roadmap step 2 (classify relevance) used a hand-picked threshold with no
measured precision or recall. This harness scores every labeled example in
eval/relevance_labeled.json with the same score_relevance the importers use,
reports precision/recall/F1 at the configured threshold, sweeps thresholds
so the choice is data-driven, and lists misclassified examples. With
--min-precision / --min-recall it doubles as a CI gate.

    python scripts/eval_relevance.py            # report + sweep
    python scripts/eval_relevance.py --min-precision 0.6 --min-recall 0.7
    python scripts/eval_relevance.py --compare-model   # fair held-out heuristic vs model

The --compare-model flag adds a FAIR comparison of the keyword heuristic against
the optional trained classifier (scripts/train_relevance.py) using stratified
cross-validation: the heuristic needs no training, so it is scored on each test
fold directly, while the model is retrained on the train folds and scored on the
held-out test fold. Both report pooled precision/recall/F1. The data is small,
so the verdict is reported honestly and the heuristic stays the default unless
the model measurably beats it. This path needs scikit-learn; without it the
comparison is skipped and the heuristic report still runs.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    filter_relevant_sources,
    load_json,
    normalize_title,
    score_relevance,
)


EVAL_PATH = ROOT / "eval" / "relevance_labeled.json"
HARVESTED_PATH = ROOT / "eval" / "relevance_harvested.json"


@dataclass
class Metrics:
    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def load_examples() -> list[dict[str, Any]]:
    payload = load_json(EVAL_PATH)
    return payload["examples"]


def load_harvested_examples() -> list[dict[str, Any]]:
    """Load auto-harvested labels, or [] if none have been collected yet."""
    if not HARVESTED_PATH.exists():
        return []
    payload = load_json(HARVESTED_PATH)
    return payload.get("examples", []) if isinstance(payload, dict) else []


def combine_examples(
    curated: list[dict[str, Any]], harvested: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Curated set plus harvested labels, deduped by normalized title.

    Curated examples win on conflict, so the hand-labeled judgments are never
    overridden by an auto-harvested label for the same title.
    """
    combined = list(curated)
    seen = {normalize_title(str(ex.get("title", ""))) for ex in curated}
    for example in harvested:
        key = normalize_title(str(example.get("title", "")))
        if key and key not in seen:
            combined.append(example)
            seen.add(key)
    return combined


def is_predicted_relevant(example: dict[str, Any], threshold: float) -> bool:
    """Predict relevance exactly as filter_relevant_sources would decide it."""
    kept = filter_relevant_sources([{"title": example["title"], "abstract": example["abstract"]}], threshold)
    return bool(kept)


def evaluate(examples: list[dict[str, Any]], threshold: float) -> Metrics:
    tp = fp = fn = tn = 0
    for example in examples:
        predicted = is_predicted_relevant(example, threshold)
        actual = bool(example["relevant"])
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    return Metrics(threshold, tp, fp, fn, tn)


def metrics_from_predictions(
    predictions: list[bool], actuals: list[bool]
) -> Metrics:
    tp = fp = fn = tn = 0
    for predicted, actual in zip(predictions, actuals):
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    return Metrics(0.0, tp, fp, fn, tn)


def compare_with_model(
    examples: list[dict[str, Any]], threshold: float, folds: int, seed: int
) -> tuple[Metrics, Metrics] | None:
    """Fair held-out comparison: heuristic vs trained model via stratified CV.

    The heuristic needs no training, so it is scored directly on each test fold;
    the model is refit on the train folds and scored on the held-out test fold.
    Predictions are pooled across folds and a single precision/recall/F1 is
    reported for each. Returns (heuristic_metrics, model_metrics), or None when
    scikit-learn is unavailable.
    """
    try:
        from sklearn.model_selection import StratifiedKFold

        from train_relevance import DECISION_THRESHOLD, build_classifier, build_vectorizer
    except ImportError:
        return None

    texts = [f"{ex['title']} {ex['abstract']}" for ex in examples]
    labels = [1 if ex["relevant"] else 0 for ex in examples]
    n_pos = sum(labels)
    n_splits = max(2, min(folds, n_pos, len(labels) - n_pos))

    heuristic_pred: list[bool] = []
    model_pred: list[bool] = []
    actuals: list[bool] = []

    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(texts, labels):
        vectorizer = build_vectorizer()
        classifier = build_classifier()
        matrix = vectorizer.fit_transform([texts[i] for i in train_idx])
        classifier.fit(matrix, [labels[i] for i in train_idx])
        test_matrix = vectorizer.transform([texts[i] for i in test_idx])
        probs = classifier.predict_proba(test_matrix)[:, 1]
        for offset, i in enumerate(test_idx):
            actuals.append(bool(labels[i]))
            heuristic_pred.append(is_predicted_relevant(examples[i], threshold))
            model_pred.append(bool(probs[offset] >= DECISION_THRESHOLD))

    return (
        metrics_from_predictions(heuristic_pred, actuals),
        metrics_from_predictions(model_pred, actuals),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the relevance heuristic against a labeled set.")
    parser.add_argument("--threshold", type=float, default=RELEVANCE_THRESHOLD)
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument(
        "--include-harvested",
        action="store_true",
        help=(
            "Also measure auto-harvested labels from eval/relevance_harvested.json. "
            "These are biased (only filter-passing candidates get reviewed) and "
            "supplement, never replace, the curated set."
        ),
    )
    parser.add_argument(
        "--compare-model",
        action="store_true",
        help="Fairly compare the heuristic against the trained model via stratified CV.",
    )
    parser.add_argument("--folds", type=int, default=5, help="CV folds for --compare-model.")
    parser.add_argument("--seed", type=int, default=42, help="CV split seed for --compare-model.")
    args = parser.parse_args()

    examples = load_examples()
    if args.include_harvested:
        harvested = load_harvested_examples()
        examples = combine_examples(examples, harvested)
        print(f"Including {len(harvested)} harvested label(s) (deduped by title).")
    metrics = evaluate(examples, args.threshold)

    print(f"Labeled examples: {len(examples)} ({metrics.tp + metrics.fn} relevant)")
    print(f"At threshold {args.threshold}:")
    print(f"  precision {metrics.precision:.2f}  recall {metrics.recall:.2f}  f1 {metrics.f1:.2f}")
    print(f"  tp={metrics.tp} fp={metrics.fp} fn={metrics.fn} tn={metrics.tn}")

    print("\nThreshold sweep (precision / recall / f1):")
    for step in range(2, 15):
        t = round(step * 0.05, 2)
        m = evaluate(examples, t)
        print(f"  {t:.2f}: P {m.precision:.2f}  R {m.recall:.2f}  F1 {m.f1:.2f}")

    misses = []
    for example in examples:
        predicted = is_predicted_relevant(example, args.threshold)
        if predicted != bool(example["relevant"]):
            kind = "false positive" if predicted else "false negative"
            score, topics = score_relevance({"title": example["title"], "abstract": example["abstract"]})
            misses.append((kind, score, topics, example["title"]))
    if misses:
        print(f"\nMisclassified at threshold {args.threshold}:")
        for kind, score, topics, title in misses:
            print(f"  [{kind}] score={score} topics={topics or []}: {title[:70]}")

    if args.compare_model:
        print(f"\nFair held-out comparison (stratified {args.folds}-fold CV, seed {args.seed}):")
        result = compare_with_model(examples, args.threshold, args.folds, args.seed)
        if result is None:
            print("  scikit-learn not installed; skipping model comparison (heuristic stays active).")
        else:
            heuristic_cv, model_cv = result
            print(
                f"  heuristic:  P {heuristic_cv.precision:.2f}  R {heuristic_cv.recall:.2f}  "
                f"F1 {heuristic_cv.f1:.2f}  (tp={heuristic_cv.tp} fp={heuristic_cv.fp} "
                f"fn={heuristic_cv.fn} tn={heuristic_cv.tn})"
            )
            print(
                f"  model:      P {model_cv.precision:.2f}  R {model_cv.recall:.2f}  "
                f"F1 {model_cv.f1:.2f}  (tp={model_cv.tp} fp={model_cv.fp} "
                f"fn={model_cv.fn} tn={model_cv.tn})"
            )
            if model_cv.f1 > heuristic_cv.f1:
                print(
                    f"  VERDICT: model beats the heuristic on held-out F1 "
                    f"({model_cv.f1:.2f} > {heuristic_cv.f1:.2f}). Consider enabling "
                    "RELEVANCE_CLASSIFIER=model after review."
                )
            else:
                print(
                    f"  VERDICT: model does NOT beat the heuristic on held-out F1 "
                    f"({model_cv.f1:.2f} <= {heuristic_cv.f1:.2f}). The heuristic "
                    "stays the default and active decision."
                )

    status = 0
    if args.min_precision is not None and metrics.precision < args.min_precision:
        print(f"\nFAIL: precision {metrics.precision:.2f} < required {args.min_precision}")
        status = 1
    if args.min_recall is not None and metrics.recall < args.min_recall:
        print(f"FAIL: recall {metrics.recall:.2f} < required {args.min_recall}")
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
