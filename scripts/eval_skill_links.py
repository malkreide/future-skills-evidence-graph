"""Evaluate the optional skill-link suggestion against a labeled golden set.

A claim only becomes `reviewed` once it links at least one skill, so a wrong
suggestion here attaches evidence to the wrong skill — the failure mode this
harness exists to catch. It mirrors `eval_claim_prefill.py`: the offline run is
a deterministic regression over committed fixtures, and `--record-live` is the
one path that calls the real model and therefore measures live accuracy.

Set-based scoring, because a claim may link zero, one or several skills:

- precision = correct links / links proposed  (the reviewer-trust metric)
- recall    = correct links / links in gold
- abstention accuracy = share of the empty-gold examples the model left empty

That last number carries most of the signal. The catalogue is future-skills
shaped and most education studies legitimately map to nothing, so 38 of the 50
golden examples have an empty gold link. A model that guesses a plausible skill
for every claim scores well on the 12 and floods the reviewer on the 38.

    python scripts/eval_skill_links.py                    # offline report
    python scripts/eval_skill_links.py --min-precision 0.8 # gate (see below)
    AI_PROVIDER=anthropic \
      python scripts/eval_skill_links.py --record-live    # measure live accuracy

**Gates are refused while the golden set is unreviewed.** The gold links were
proposed by an agent, and project governance puts editorial judgement with a
person. While `_status` is `proposed-unreviewed` this script reports numbers but
exits non-zero on any `--min-*` flag, so nothing can quietly gate CI on labels
nobody checked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import ai_provider
from common import ROOT, load_json
from extract_claims import (
    SKILL_LINK_FIELDS,
    SKILL_LINK_OUTPUT_SCHEMA,
    skill_catalogue,
    skill_link_prompt,
    suggest_skill_links,
)
from eval_claim_prefill import EVAL_PATH as PREFILL_PATH

EVAL_PATH = ROOT / "eval" / "skill_link_labeled.json"

# The golden set is only a measurement once a human has checked the links.
REVIEWED_STATUS = "reviewed"


@dataclass
class LinkMetrics:
    """Set-based link counts plus the abstention behaviour on empty-gold cases."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    empty_gold: int = 0
    empty_gold_correct: int = 0
    wrong: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        proposed = self.true_positives + self.false_positives
        return self.true_positives / proposed if proposed else 1.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def abstention(self) -> float:
        return self.empty_gold_correct / self.empty_gold if self.empty_gold else 1.0


def load_payload() -> dict[str, Any]:
    return load_json(EVAL_PATH)


def load_inputs() -> dict[str, dict[str, Any]]:
    """The shared example inputs, keyed by id, from the pre-fill golden set."""
    return {example["id"]: example for example in load_json(PREFILL_PATH)["examples"]}


def is_reviewed(payload: dict[str, Any]) -> bool:
    return str(payload.get("_status", "")).strip() == REVIEWED_STATUS


def _suggestion_for(
    example: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    catalogue: list[dict[str, str]],
) -> dict[str, list[str]]:
    """Replay the model's link suggestion, or an empty proposal when absent."""
    source = inputs.get(example["id"])
    if source is None:
        return {name: [] for name in SKILL_LINK_FIELDS}
    links = suggest_skill_links(
        source["abstract"], source["statement"], source.get("topics", []), catalogue
    )
    return links or {name: [] for name in SKILL_LINK_FIELDS}


def evaluate(
    payload: dict[str, Any], inputs: dict[str, dict[str, Any]], catalogue: list[dict[str, str]]
) -> dict[str, LinkMetrics]:
    """Score every example per link field."""
    metrics = {name: LinkMetrics() for name in SKILL_LINK_FIELDS}
    for example in payload["examples"]:
        predicted = _suggestion_for(example, inputs, catalogue)
        for name in SKILL_LINK_FIELDS:
            fm = metrics[name]
            gold = set(example["gold"].get(name) or [])
            pred = set(predicted.get(name) or [])
            fm.true_positives += len(gold & pred)
            fm.false_positives += len(pred - gold)
            fm.false_negatives += len(gold - pred)
            if not gold:
                fm.empty_gold += 1
                if not pred:
                    fm.empty_gold_correct += 1
                else:
                    fm.wrong.append(
                        f"{example['id']}: proposed {sorted(pred)} but gold is empty"
                    )
            elif gold != pred:
                fm.wrong.append(
                    f"{example['id']}: proposed {sorted(pred)} != gold {sorted(gold)}"
                )
    return metrics


def write_fixtures(
    payload: dict[str, Any], inputs: dict[str, dict[str, Any]], catalogue: list[dict[str, str]]
) -> int:
    """Replay each '_recorded' link suggestion into the offline fixture cache."""
    written = 0
    for example in payload["examples"]:
        recorded = example.get("_recorded")
        source = inputs.get(example["id"])
        if recorded is None or source is None:
            continue
        prompt = skill_link_prompt(
            source["abstract"], source["statement"], source.get("topics", []), catalogue
        )
        ai_provider.cache_write(
            {
                "kind": "complete",
                "model": ai_provider.ai_model(),
                "prompt": prompt,
                "schema": SKILL_LINK_OUTPUT_SCHEMA,
            },
            recorded,
        )
        written += 1
    return written


def record_live(
    payload: dict[str, Any], inputs: dict[str, dict[str, Any]], catalogue: list[dict[str, str]]
) -> int:
    """Re-record every '_recorded' (and its fixture) from the live model."""
    if ai_provider.ai_provider() != "anthropic":
        print(
            "FAIL: --record-live needs AI_PROVIDER=anthropic (it calls the live model). "
            f"Got {ai_provider.ai_provider()!r}.",
            file=sys.stderr,
        )
        return -1
    recorded = 0
    for example in payload["examples"]:
        source = inputs.get(example["id"])
        if source is None:
            continue
        prompt = skill_link_prompt(
            source["abstract"], source["statement"], source.get("topics", []), catalogue
        )
        response = ai_provider.complete(prompt, schema=SKILL_LINK_OUTPUT_SCHEMA)
        if not isinstance(response, dict):
            print(
                f"Warning: no live suggestion for {example['id']}; keeping its prior "
                "'_recorded'.",
                file=sys.stderr,
            )
            continue
        example["_recorded"] = {
            name: list(response.get(name) or []) for name in SKILL_LINK_FIELDS
        }
        recorded += 1
    EVAL_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return recorded


def _report(metrics: dict[str, LinkMetrics], payload: dict[str, Any]) -> None:
    print(f"Skill-link suggestions scored against gold ({EVAL_PATH.name}):\n")
    print(f"  {'field':<24} {'P':>5} {'R':>5} {'F1':>5}  {'abstain':>8}   TP/FP/FN")
    for name in SKILL_LINK_FIELDS:
        fm = metrics[name]
        print(
            f"  {name:<24} {fm.precision:>5.2f} {fm.recall:>5.2f} {fm.f1:>5.2f}"
            f"  {fm.abstention:>7.2f}   {fm.true_positives}/{fm.false_positives}/"
            f"{fm.false_negatives}"
        )
    support = metrics["supports_skill_ids"]
    print(
        f"\n  'abstain' is the share of the {support.empty_gold} empty-gold examples left "
        "empty.\n  Most education studies map to no catalogue skill, so that column is "
        "where\n  an over-eager model shows up first."
    )
    if not is_reviewed(payload):
        print(
            "\n  NOTE: the golden set is still '_status: proposed-unreviewed' — these "
            "links\n  were proposed by an agent, not curated. Numbers are indicative "
            "only and no\n  gate can be enforced until a reviewer sets _status to "
            "'reviewed'."
        )
    disagreements = [w for name in SKILL_LINK_FIELDS for w in metrics[name].wrong]
    if disagreements:
        print(f"\nDisagreements with gold ({len(disagreements)}):")
        for item in disagreements:
            print(f"  - {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the skill-link suggestions.")
    parser.add_argument(
        "--write-fixtures",
        action="store_true",
        help="Replay each example's '_recorded' suggestion into tests/fixtures/ai and exit.",
    )
    parser.add_argument(
        "--record-live",
        action="store_true",
        help="Re-record '_recorded' + fixtures from the live model (needs AI_PROVIDER=anthropic).",
    )
    parser.add_argument(
        "--min-precision", type=float, default=None,
        help="Gate on supports_skill_ids precision. Refused while the golden set is unreviewed.",
    )
    parser.add_argument(
        "--min-abstention", type=float, default=None,
        help="Gate on the share of empty-gold examples left empty. Refused while unreviewed.",
    )
    args = parser.parse_args()

    payload = load_payload()
    inputs = load_inputs()
    catalogue = skill_catalogue()

    if not catalogue:
        print("FAIL: no active skills in data/skills/; nothing to link against.", file=sys.stderr)
        return 1

    if args.write_fixtures:
        count = write_fixtures(payload, inputs, catalogue)
        print(f"Wrote {count} fixture(s) to {ai_provider.CACHE_DIR}.")
        return 0

    if args.record_live:
        count = record_live(payload, inputs, catalogue)
        if count < 0:
            return 1
        print(f"Re-recorded {count} example(s) from the live model. Live accuracy below:\n")
        os.environ["AI_PROVIDER"] = "cache"

    # Deterministic replay by default, exactly like the pre-fill harness.
    if ai_provider.ai_provider() == "none":
        os.environ["AI_PROVIDER"] = "cache"

    metrics = evaluate(payload, inputs, catalogue)
    _report(metrics, payload)

    requested = [
        ("supports precision", metrics["supports_skill_ids"].precision, args.min_precision),
        ("abstention", metrics["supports_skill_ids"].abstention, args.min_abstention),
    ]
    active = [gate for gate in requested if gate[2] is not None]
    if active and not is_reviewed(payload):
        # Refusing is the point: a gate over agent-proposed labels would dress
        # unreviewed judgement up as a measured floor.
        print(
            f"\nFAIL: refusing to enforce a gate while {EVAL_PATH.name} is "
            f"'_status: {payload.get('_status')}'. Have a reviewer check the gold links "
            "and set _status to 'reviewed' first.",
            file=sys.stderr,
        )
        return 1

    status = 0
    for label, value, minimum in active:
        if value < minimum:
            print(f"\nFAIL: {label} {value:.2f} < required {minimum}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
