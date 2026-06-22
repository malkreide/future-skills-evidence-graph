"""Evaluate the optional LLM claim pre-fill (P1) against a labeled golden set.

The pre-fill only ever *suggests* the manual review fields (context, outcome,
age_range, evidence_strength); this harness measures how trustworthy those
suggestions are before anyone leans on them. For every example in
eval/claim_prefill_labeled.json it replays the recorded model suggestion
(offline, from the fixture cache) and compares it field-by-field to the
hand-curated gold values, reporting precision-style metrics:

- precision per field: of the fields the model proposed a value for, how many
  match gold (a wrong suggestion costs reviewer trust, so this is the headline);
- recall per field: of the gold values present, how many the model recovered;
- exact match for age_range / evidence_strength, token-overlap for the free-text
  outcome / context fields.

    python scripts/eval_claim_prefill.py                      # offline report
    python scripts/eval_claim_prefill.py --min-precision 0.8  # CI gate
    python scripts/eval_claim_prefill.py --write-fixtures     # replay '_recorded' into the cache
    AI_PROVIDER=anthropic \
      python scripts/eval_claim_prefill.py --record-live      # re-record from the live model

Two clocks, kept honest and separate:

- The **offline report / CI gate** is a *regression*: every suggestion comes
  from the committed fixture cache (AI_PROVIDER=cache), never the network, so it
  is fully deterministic. It scores the *recorded* outputs against gold, i.e. it
  catches drift between what we froze and the labels -- not the live model's
  current accuracy. A cache miss means a fixture is missing; regenerate with
  --write-fixtures, which replays each example's '_recorded' through
  ai_provider.cache_write.
- **--record-live** (AI_PROVIDER=anthropic) is where *live accuracy* is actually
  measured: it calls the real model once per example, overwrites '_recorded' (and
  the fixture cache) with the fresh output, and prints the same field metrics --
  now against live suggestions. Commit the refreshed '_recorded' + fixtures to
  move the regression baseline forward. See OPERATIONS.md ("Re-recording").
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import ai_provider
from common import ROOT, load_json
from extract_claims import (
    PREFILL_OUTPUT_SCHEMA,
    PREFILL_SUGGESTION_FIELDS,
    prefill_prompt,
    suggest_claim_fields,
)


EVAL_PATH = ROOT / "eval" / "claim_prefill_labeled.json"

# Free-text fields are matched by token overlap; the categorical fields must
# match exactly. A suggestion and a gold value count as agreeing on a text field
# when their Jaccard token overlap reaches this floor.
TEXT_FIELDS = ("outcome", "context")
EXACT_FIELDS = ("age_range", "evidence_strength")
TEXT_MATCH_THRESHOLD = 0.5

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _values_match(field_name: str, gold: Any, predicted: Any) -> bool:
    """Whether a predicted value agrees with gold for *field_name* (both non-null)."""
    if field_name in EXACT_FIELDS:
        return str(gold).strip().casefold() == str(predicted).strip().casefold()
    gold_tokens, pred_tokens = _tokens(str(gold)), _tokens(str(predicted))
    if not gold_tokens or not pred_tokens:
        return False
    overlap = len(gold_tokens & pred_tokens) / len(gold_tokens | pred_tokens)
    return overlap >= TEXT_MATCH_THRESHOLD


def _present(value: Any) -> bool:
    """A field is 'present' when it carries a usable value (not null/blank)."""
    return isinstance(value, str) and bool(value.strip())


@dataclass
class FieldMetrics:
    name: str
    matches: int = 0
    predicted: int = 0  # gold-comparable predictions the model actually made
    gold: int = 0  # gold values present to be recovered
    abstain_correct: int = 0  # both null -> the model correctly proposed nothing
    wrong: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.matches / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        return self.matches / self.gold if self.gold else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def load_payload() -> dict[str, Any]:
    return load_json(EVAL_PATH)


def load_examples() -> list[dict[str, Any]]:
    return load_payload()["examples"]


def _dump_value(value: Any) -> str:
    """Compact JSON for a nested value, matching the golden file's hand style."""
    return json.dumps(value, ensure_ascii=False)


def dump_payload(payload: dict[str, Any]) -> str:
    """Serialize the golden set preserving its one-object-per-line layout.

    The file is hand-formatted (each example's keys on their own line, with
    'gold'/'_recorded'/'topics' as compact single-line JSON). --record-live
    rewrites it in place, so a faithful dumper keeps the diff to the lines that
    actually changed instead of reflowing the whole artifact.
    """
    lines = ["{"]
    top_keys = [key for key in payload if key != "examples"]
    for key in top_keys:
        lines.append(f"  {json.dumps(key)}: {_dump_value(payload[key])},")
    lines.append('  "examples": [')
    examples = payload["examples"]
    for example_index, example in enumerate(examples):
        lines.append("    {")
        keys = list(example.keys())
        for key_index, key in enumerate(keys):
            tail = "," if key_index < len(keys) - 1 else ""
            lines.append(f"      {json.dumps(key)}: {_dump_value(example[key])}{tail}")
        lines.append("    }" + ("," if example_index < len(examples) - 1 else ""))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _suggestion_for(example: dict[str, Any]) -> dict[str, Any] | None:
    """Replay the model's suggestion for *example* via suggest_claim_fields."""
    return suggest_claim_fields(
        example["abstract"], example["statement"], example.get("topics", [])
    )


def evaluate(examples: list[dict[str, Any]]) -> dict[str, FieldMetrics]:
    """Score every example field-by-field; missing fixtures count as no suggestion."""
    metrics = {name: FieldMetrics(name) for name in PREFILL_SUGGESTION_FIELDS}
    for example in examples:
        gold = example["gold"]
        predicted = _suggestion_for(example) or {}
        for name in PREFILL_SUGGESTION_FIELDS:
            fm = metrics[name]
            gold_value, pred_value = gold.get(name), predicted.get(name)
            gold_here, pred_here = _present(gold_value), _present(pred_value)
            if gold_here:
                fm.gold += 1
            if pred_here:
                fm.predicted += 1
            if gold_here and pred_here:
                if _values_match(name, gold_value, pred_value):
                    fm.matches += 1
                else:
                    fm.wrong.append(f"{example['id']}: {pred_value!r} != {gold_value!r}")
            elif not gold_here and not pred_here:
                fm.abstain_correct += 1
            elif pred_here and not gold_here:
                fm.wrong.append(f"{example['id']}: proposed {pred_value!r} but gold is null")
    return metrics


def micro_average(metrics: dict[str, FieldMetrics]) -> FieldMetrics:
    overall = FieldMetrics("overall")
    for fm in metrics.values():
        overall.matches += fm.matches
        overall.predicted += fm.predicted
        overall.gold += fm.gold
        overall.abstain_correct += fm.abstain_correct
    return overall


def write_fixtures(examples: list[dict[str, Any]]) -> int:
    """Record each example's '_recorded' suggestion into the offline fixture cache.

    The payload mirrors exactly what ai_provider.complete builds for the same
    prompt and schema, so a later AI_PROVIDER=cache run replays it deterministically.
    """
    written = 0
    for example in examples:
        recorded = example.get("_recorded")
        if recorded is None:
            continue
        prompt = prefill_prompt(
            example["abstract"], example["statement"], example.get("topics", [])
        )
        payload = {
            "kind": "complete",
            "model": ai_provider.ai_model(),
            "prompt": prompt,
            "schema": PREFILL_OUTPUT_SCHEMA,
        }
        ai_provider.cache_write(payload, recorded)
        written += 1
    return written


def _normalize_recorded(response: dict[str, Any]) -> dict[str, Any]:
    """Pin a live suggestion to the canonical field order for a clean diff."""
    return {name: response.get(name) for name in PREFILL_SUGGESTION_FIELDS}


def record_live(payload: dict[str, Any]) -> int:
    """Re-record every example's '_recorded' (and its fixture) from the live model.

    Requires AI_PROVIDER=anthropic: this is the one path that actually calls the
    network, so it is where live accuracy is measured. Each call goes through
    ai_provider.complete, which in 'anthropic' mode also caches the response, so
    the committed fixtures and '_recorded' stay in lock-step. A failed/refused
    call (complete -> None) leaves that example's prior recording untouched and
    warns, rather than wiping a good baseline. Returns the number re-recorded.
    """
    if ai_provider.ai_provider() != "anthropic":
        print(
            "FAIL: --record-live needs AI_PROVIDER=anthropic (it calls the live model). "
            f"Got {ai_provider.ai_provider()!r}.",
            file=sys.stderr,
        )
        return -1
    recorded = 0
    for example in payload["examples"]:
        prompt = prefill_prompt(
            example["abstract"], example["statement"], example.get("topics", [])
        )
        response = ai_provider.complete(prompt, schema=PREFILL_OUTPUT_SCHEMA)
        if not isinstance(response, dict):
            print(
                f"Warning: no live suggestion for {example['id']}; keeping its prior "
                "'_recorded'.",
                file=sys.stderr,
            )
            continue
        example["_recorded"] = _normalize_recorded(response)
        recorded += 1
    EVAL_PATH.write_text(dump_payload(payload), encoding="utf-8")
    return recorded


def _report(metrics: dict[str, FieldMetrics], overall: FieldMetrics) -> None:
    print(f"Labeled examples scored against gold review fields ({EVAL_PATH.name}):\n")
    print(f"  {'field':<18} {'P':>5} {'R':>5} {'F1':>5}   predicted/gold  abstain")
    for name in PREFILL_SUGGESTION_FIELDS:
        fm = metrics[name]
        print(
            f"  {name:<18} {fm.precision:>5.2f} {fm.recall:>5.2f} {fm.f1:>5.2f}"
            f"   {fm.predicted:>3}/{fm.gold:<3}        {fm.abstain_correct}"
        )
    print(
        f"  {'OVERALL (micro)':<18} {overall.precision:>5.2f} {overall.recall:>5.2f} "
        f"{overall.f1:>5.2f}   {overall.predicted:>3}/{overall.gold:<3}        "
        f"{overall.abstain_correct}"
    )
    disagreements = [w for name in PREFILL_SUGGESTION_FIELDS for w in metrics[name].wrong]
    if disagreements:
        print(f"\nDisagreements with gold ({len(disagreements)}):")
        for item in disagreements:
            print(f"  - {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the LLM claim pre-fill suggestions.")
    parser.add_argument(
        "--write-fixtures",
        action="store_true",
        help="Replay each example's '_recorded' suggestion into tests/fixtures/ai and exit.",
    )
    parser.add_argument(
        "--record-live",
        action="store_true",
        help="Re-record '_recorded' + fixtures from the live model (needs AI_PROVIDER=anthropic), "
        "then report live accuracy vs gold.",
    )
    parser.add_argument("--min-precision", type=float, default=None, help="Gate on overall precision.")
    parser.add_argument("--min-recall", type=float, default=None, help="Gate on overall recall.")
    parser.add_argument(
        "--min-evidence-strength-precision",
        type=float,
        default=None,
        help="Gate on evidence_strength precision (the field most likely to mislead a reviewer).",
    )
    parser.add_argument(
        "--min-age-range-precision",
        type=float,
        default=None,
        help="Gate on age_range precision.",
    )
    args = parser.parse_args()

    payload = load_payload()
    examples = payload["examples"]

    if args.write_fixtures:
        # Recording always uses the canonical cache path; no provider needed.
        count = write_fixtures(examples)
        print(f"Wrote {count} fixture(s) to {ai_provider.CACHE_DIR}.")
        return 0

    if args.record_live:
        # The live path: overwrite '_recorded' + fixtures, then fall through to
        # the report so the printed metrics are the freshly measured live accuracy.
        count = record_live(payload)
        if count < 0:
            return 1
        print(
            f"Re-recorded {count} example(s) from the live model into {EVAL_PATH.name} "
            f"and {ai_provider.CACHE_DIR.name}/. Live accuracy below:\n"
        )
        # Score the freshly written fixtures deterministically (no second live call).
        os.environ["AI_PROVIDER"] = "cache"

    # Read suggestions from the committed fixtures unless a live provider is set.
    # 'none' would make every suggestion None, so default to deterministic replay.
    if ai_provider.ai_provider() == "none":
        os.environ["AI_PROVIDER"] = "cache"

    metrics = evaluate(examples)
    overall = micro_average(metrics)
    _report(metrics, overall)

    status = 0
    gates = [
        ("precision", overall.precision, args.min_precision),
        ("recall", overall.recall, args.min_recall),
        ("evidence_strength precision", metrics["evidence_strength"].precision, args.min_evidence_strength_precision),
        ("age_range precision", metrics["age_range"].precision, args.min_age_range_precision),
    ]
    for label, value, minimum in gates:
        if minimum is not None and value < minimum:
            print(f"\nFAIL: {label} {value:.2f} < required {minimum}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
