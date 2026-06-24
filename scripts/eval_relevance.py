"""Evaluate the keyword relevance heuristic against a labeled set.

Roadmap step 2 (classify relevance) used a hand-picked threshold with no
measured precision or recall. This harness scores every labeled example in
eval/relevance_labeled.json with the same score_relevance the importers use,
reports precision/recall/F1 at the configured threshold, sweeps thresholds
so the choice is data-driven, and lists misclassified examples. With
--min-precision / --min-recall it doubles as a CI gate.

    python scripts/eval_relevance.py            # report + sweep
    python scripts/eval_relevance.py --min-precision 0.6 --min-recall 0.7
    python scripts/eval_relevance.py --compare-model       # fair held-out heuristic vs model
    python scripts/eval_relevance.py --compare-embedding   # fair held-out heuristic vs anchors

The --compare-model flag adds a FAIR comparison of the keyword heuristic against
the optional trained classifier (scripts/train_relevance.py) using stratified
cross-validation: the heuristic needs no training, so it is scored on each test
fold directly, while the model is retrained on the train folds and scored on the
held-out test fold. Both report pooled precision/recall/F1. The data is small,
so the verdict is reported honestly and the heuristic stays the default unless
the model measurably beats it. This path needs scikit-learn; without it the
comparison is skipped and the heuristic report still runs.

The --compare-embedding flag does the same FAIR held-out comparison for the
optional embedding anchors (scripts/build_relevance_anchors.py): the anchors are
rebuilt (positive/negative centroids) on each train fold and scored on the
held-out test fold, the heuristic scored directly. It needs an EMBEDDING_PROVIDER
(e.g. EMBEDDING_PROVIDER=local); without one the comparison is skipped and the
heuristic report still runs. Same honest verdict, same default.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from common import (
    RELEVANCE_THRESHOLD,
    ROOT,
    anchor_relevance_difference,
    filter_relevant_sources,
    is_educator_audience,
    load_json,
    normalize_title,
    score_relevance,
    source_text,
    vector_centroid,
)


EVAL_PATH = ROOT / "eval" / "relevance_labeled.json"
HARVESTED_PATH = ROOT / "eval" / "relevance_harvested.json"
EDUCATOR_PATH = ROOT / "eval" / "relevance_educator.json"


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


def predicted_audience(example: dict[str, Any], threshold: float) -> str | None:
    """The lane filter_relevant_sources would tag this example, or None if dropped."""
    kept = filter_relevant_sources(
        [{"title": example["title"], "abstract": example["abstract"]}], threshold
    )
    return kept[0]["audience"] if kept else None


def load_educator_examples() -> list[dict[str, Any]]:
    """Load the dedicated educator-lane labeled set, or [] if absent."""
    if not EDUCATOR_PATH.exists():
        return []
    payload = load_json(EDUCATOR_PATH)
    return payload.get("examples", []) if isinstance(payload, dict) else []


def educator_lane_report(examples: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Measure the automated educator lane against eval/relevance_educator.json.

    Kept separate from the learner set so educator labels never perturb the
    heuristic baseline or the optional model/anchor training inputs. Precision:
    of the educator-shaped examples the filter keeps AND tags audience="educator",
    the fraction that are genuinely relevant (the lane must reject the off-scope
    higher-education and teacher-tool-use negatives). Recall: of the positives
    labeled audience=="educator" -- the educator-competence evidence the learner
    gate drops as adult -- the fraction the lane recovers.
    """
    decisions = [(e, predicted_audience(e, threshold)) for e in examples]
    predicted = [e for e, aud in decisions if aud == "educator"]
    predicted_relevant = [e for e in predicted if e["relevant"]]
    labeled = [e for e in examples if e["relevant"] and e.get("audience") == "educator"]
    recalled = [e for e in labeled if predicted_audience(e, threshold) == "educator"]
    leaked = [e["title"] for e, aud in decisions if aud == "educator" and not e["relevant"]]
    return {
        "predicted": len(predicted),
        "predicted_relevant": len(predicted_relevant),
        "labeled": len(labeled),
        "recalled": len(recalled),
        "precision": len(predicted_relevant) / len(predicted) if predicted else 0.0,
        "recall": len(recalled) / len(labeled) if labeled else 0.0,
        "rescued": [e["title"] for e in recalled],
        "leaked": leaked,
    }


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


def _stratified_folds(labels: list[int], n_splits: int, seed: int) -> list[list[int]]:
    """Deterministic stratified k-fold split (pure stdlib, no scikit-learn).

    Positives and negatives are shuffled with a seeded RNG and dealt round-robin
    into the folds, so each fold keeps roughly the class balance. Returns the
    list of test-index lists.
    """
    import random

    rng = random.Random(seed)
    positives = [i for i, label in enumerate(labels) if label]
    negatives = [i for i, label in enumerate(labels) if not label]
    rng.shuffle(positives)
    rng.shuffle(negatives)
    folds: list[list[int]] = [[] for _ in range(n_splits)]
    for offset, index in enumerate(positives):
        folds[offset % n_splits].append(index)
    for offset, index in enumerate(negatives):
        folds[offset % n_splits].append(index)
    return folds


def compare_with_embedding(
    examples: list[dict[str, Any]], threshold: float, folds: int, seed: int
) -> tuple[Metrics, Metrics] | None:
    """Fair held-out comparison: heuristic vs embedding anchors via stratified CV.

    The anchors (positive/negative centroids) are rebuilt on the train folds and
    scored on the held-out test fold; the heuristic is scored on the test fold
    directly. Predictions are pooled across folds and a single precision/recall/
    F1 is reported for each. Returns (heuristic_metrics, embedding_metrics), or
    None when no embedding provider is configured (embed returns None).
    """
    from ai_provider import embed
    from build_relevance_anchors import DEFAULT_DECISION_THRESHOLD

    texts = [source_text({"title": ex["title"], "abstract": ex["abstract"]}) for ex in examples]
    vectors = embed(texts)
    if not vectors:
        return None

    labels = [1 if ex["relevant"] else 0 for ex in examples]
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    n_splits = max(2, min(folds, n_pos, n_neg))

    heuristic_pred: list[bool] = []
    embedding_pred: list[bool] = []
    actuals: list[bool] = []

    fold_tests = _stratified_folds(labels, n_splits, seed)
    for test_idx in fold_tests:
        test_set = set(test_idx)
        train_pos = [vectors[i] for i in range(len(labels)) if i not in test_set and labels[i]]
        train_neg = [vectors[i] for i in range(len(labels)) if i not in test_set and not labels[i]]
        if not train_pos or not train_neg:
            continue
        anchors = {"positive": vector_centroid(train_pos), "negative": vector_centroid(train_neg)}
        for i in test_idx:
            actuals.append(bool(labels[i]))
            heuristic_pred.append(is_predicted_relevant(examples[i], threshold))
            difference = anchor_relevance_difference(vectors[i], anchors)
            embedding_pred.append(bool(difference >= DEFAULT_DECISION_THRESHOLD))

    return (
        metrics_from_predictions(heuristic_pred, actuals),
        metrics_from_predictions(embedding_pred, actuals),
    )


def _print_comparison(name: str, heuristic_cv: Metrics, contender_cv: Metrics) -> None:
    """Shared report + honest verdict for a held-out heuristic-vs-X comparison."""
    print(
        f"  heuristic:  P {heuristic_cv.precision:.2f}  R {heuristic_cv.recall:.2f}  "
        f"F1 {heuristic_cv.f1:.2f}  (tp={heuristic_cv.tp} fp={heuristic_cv.fp} "
        f"fn={heuristic_cv.fn} tn={heuristic_cv.tn})"
    )
    print(
        f"  {name + ':':<11}P {contender_cv.precision:.2f}  R {contender_cv.recall:.2f}  "
        f"F1 {contender_cv.f1:.2f}  (tp={contender_cv.tp} fp={contender_cv.fp} "
        f"fn={contender_cv.fn} tn={contender_cv.tn})"
    )
    if contender_cv.f1 > heuristic_cv.f1:
        print(
            f"  VERDICT: {name} beats the heuristic on held-out F1 "
            f"({contender_cv.f1:.2f} > {heuristic_cv.f1:.2f}). Consider enabling it "
            "after review."
        )
    else:
        print(
            f"  VERDICT: {name} does NOT beat the heuristic on held-out F1 "
            f"({contender_cv.f1:.2f} <= {heuristic_cv.f1:.2f}). The heuristic "
            "stays the default and active decision."
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
    parser.add_argument(
        "--compare-embedding",
        action="store_true",
        help="Fairly compare the heuristic against the embedding anchors via stratified CV.",
    )
    parser.add_argument(
        "--educator-lane",
        action="store_true",
        help=(
            "Report precision/recall of the automated educator lane against the "
            "dedicated eval/relevance_educator.json set (kept separate from the "
            "learner labels so it never perturbs the heuristic baseline)."
        ),
    )
    parser.add_argument("--folds", type=int, default=5, help="CV folds for the held-out comparisons.")
    parser.add_argument("--seed", type=int, default=42, help="CV split seed for the held-out comparisons.")
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

    if args.educator_lane:
        educator = load_educator_examples()
        lane = educator_lane_report(educator, args.threshold)
        print(
            f"\nEducator lane (eval/relevance_educator.json, {len(educator)} examples):"
        )
        print(
            f"  precision {lane['precision']:.2f}  recall {lane['recall']:.2f}  "
            f"(kept+tagged educator {lane['predicted']}, of which relevant "
            f"{lane['predicted_relevant']}; labeled educator {lane['labeled']}, "
            f"recovered {lane['recalled']})"
        )
        for title in lane["rescued"]:
            print(f"  [rescued] {title[:74]}")
        for title in lane["leaked"]:
            print(f"  [LEAK - off-scope kept on educator lane] {title[:60]}")

    if args.compare_model:
        print(f"\nFair held-out comparison (stratified {args.folds}-fold CV, seed {args.seed}):")
        result = compare_with_model(examples, args.threshold, args.folds, args.seed)
        if result is None:
            print("  scikit-learn not installed; skipping model comparison (heuristic stays active).")
        else:
            heuristic_cv, model_cv = result
            _print_comparison("model", heuristic_cv, model_cv)

    if args.compare_embedding:
        print(f"\nFair held-out comparison (stratified {args.folds}-fold CV, seed {args.seed}):")
        result = compare_with_embedding(examples, args.threshold, args.folds, args.seed)
        if result is None:
            print(
                "  no embedding provider configured (set EMBEDDING_PROVIDER, e.g. "
                "EMBEDDING_PROVIDER=local); skipping embedding comparison (heuristic stays active)."
            )
        else:
            heuristic_cv, embedding_cv = result
            _print_comparison("embedding", heuristic_cv, embedding_cv)

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
