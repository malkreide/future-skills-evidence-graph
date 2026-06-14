"""Evaluate the keyword relevance heuristic against a labeled set.

Roadmap step 2 (classify relevance) used a hand-picked threshold with no
measured precision or recall. This harness scores every labeled example in
eval/relevance_labeled.json with the same score_relevance the importers use,
reports precision/recall/F1 at the configured threshold, sweeps thresholds
so the choice is data-driven, and lists misclassified examples. With
--min-precision / --min-recall it doubles as a CI gate.

    python scripts/eval_relevance.py            # report + sweep
    python scripts/eval_relevance.py --min-precision 0.6 --min-recall 0.7
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from common import RELEVANCE_THRESHOLD, ROOT, filter_relevant_sources, load_json, score_relevance


EVAL_PATH = ROOT / "eval" / "relevance_labeled.json"


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the relevance heuristic against a labeled set.")
    parser.add_argument("--threshold", type=float, default=RELEVANCE_THRESHOLD)
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    args = parser.parse_args()

    examples = load_examples()
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
