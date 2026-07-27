"""Compare AI providers on the claim pre-fill golden set.

Supporting several providers is only worth the code if the choice between them
can be *measured*. This is that measurement: the same 50 golden examples, the
same prompt, the same scorer, one column per provider.

It mirrors `eval_relevance.py --compare-model`, which exists for the same
reason — the project's rule is that an optional signal stays off until a
measurement says it beats the incumbent, and that rule needs a number.

    # offline: replay whatever each provider has recorded
    python scripts/compare_providers.py

    # record a provider live, then compare (needs that provider's key)
    AI_PROVIDER=openai OPENAI_API_KEY=... \\
      python scripts/compare_providers.py --record openai --model openai=gpt-4o

    # the keyless local option; needs a running ollama, no API budget
    python scripts/compare_providers.py --record ollama --model ollama=llama3.1

Reading the table: `GATED` is the micro-averaged precision of `age_range` and
`evidence_strength`, the two fields a wrong value actively misleads a reviewer
on. That is the number the activation rule below is written against — not the
free-text fields, which a reviewer rewrites anyway.

**Activation rule.** A provider replaces the incumbent (`anthropic`) only when
it beats it on GATED precision by a margin that is not noise, and does not lose
materially on either structured field individually. Ties go to the incumbent,
because switching costs a re-record of every fixture. A provider that merely
matches is worth knowing about — it means the pipeline is not vendor-locked —
but it is not a reason to switch.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import ai_provider
from eval_claim_prefill import (
    GATED_FIELDS,
    evaluate,
    load_embeddings,
    load_examples,
    micro_average,
    write_fixtures,
)
from extract_claims import PREFILL_OUTPUT_SCHEMA, PREFILL_SUGGESTION_FIELDS, prefill_prompt

# Starting model ids per provider. These are defaults, not recommendations —
# override with --model provider=id. Anthropic's comes from ai_provider so the
# comparison's incumbent is always whatever the pipeline actually runs.
DEFAULT_MODELS = {
    ai_provider.ANTHROPIC: ai_provider.DEFAULT_MODEL,
    ai_provider.OPENAI: "gpt-4o",
    ai_provider.OLLAMA: "llama3.1",
}

# How much better a challenger must be on GATED precision to count as better
# rather than as noise on a 50-example set.
ACTIVATION_MARGIN = 0.02

# How much a challenger may lose on either structured field individually before
# a GATED win stops counting — an average can hide a collapse in one field.
MATERIAL_REGRESSION = 0.05


def parse_model_overrides(values: list[str]) -> dict[str, str]:
    """Turn ['openai=gpt-4o'] into {'openai': 'gpt-4o'}."""
    models = dict(DEFAULT_MODELS)
    for value in values or []:
        provider, _, model = value.partition("=")
        provider = provider.strip().lower()
        if not model.strip():
            raise SystemExit(f"--model expects provider=id, got {value!r}")
        if provider not in DEFAULT_MODELS:
            known = ", ".join(sorted(DEFAULT_MODELS))
            raise SystemExit(f"--model: unknown provider {provider!r}; expected one of {known}")
        models[provider] = model.strip()
    return models


def score_provider(
    provider: str,
    model: str,
    examples: list[dict[str, Any]],
    embeddings: dict[str, list[float]] | None,
) -> dict[str, Any] | None:
    """Score one provider from its recordings, or None when it has none.

    Always reads through ``cache`` mode: a comparison must not be able to spend
    money or vary per run. Recording is a separate, explicit step (--record).
    """
    previous = {key: os.environ.get(key) for key in ("AI_PROVIDER", "AI_CACHE_PROVIDER", "AI_MODEL")}
    os.environ["AI_PROVIDER"] = ai_provider.CACHE
    os.environ["AI_CACHE_PROVIDER"] = provider
    os.environ["AI_MODEL"] = model
    try:
        metrics = evaluate(examples, embeddings)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    gated = micro_average(metrics, GATED_FIELDS)
    # No fixtures at all looks identical to "the model proposed nothing"; say so
    # rather than printing a hollow 1.00 precision over zero predictions.
    if gated.predicted == 0:
        return None
    return {"metrics": metrics, "gated": gated, "model": model}


def record_provider(provider: str, model: str, examples: list[dict[str, Any]]) -> int:
    """Call *provider* live once per example and cache each response."""
    if ai_provider.ai_provider() != provider:
        print(
            f"FAIL: --record {provider} needs AI_PROVIDER={provider} "
            f"(got {ai_provider.ai_provider()!r}); it calls the live model.",
            file=sys.stderr,
        )
        return -1
    previous_model = os.environ.get("AI_MODEL")
    os.environ["AI_MODEL"] = model
    recorded = 0
    try:
        for example in examples:
            prompt = prefill_prompt(
                example["abstract"], example["statement"], example.get("topics", [])
            )
            # complete() caches a successful response under this provider's key.
            if isinstance(ai_provider.complete(prompt, schema=PREFILL_OUTPUT_SCHEMA), dict):
                recorded += 1
            else:
                print(f"Warning: no suggestion for {example['id']}.", file=sys.stderr)
    finally:
        if previous_model is None:
            os.environ.pop("AI_MODEL", None)
        else:
            os.environ["AI_MODEL"] = previous_model
    return recorded


def _verdict(incumbent: dict[str, Any], challenger: dict[str, Any], name: str) -> str:
    """Apply the activation rule to one challenger."""
    delta = challenger["gated"].precision - incumbent["gated"].precision
    if delta <= ACTIVATION_MARGIN:
        shape = "ties" if abs(delta) <= ACTIVATION_MARGIN else "loses"
        return (
            f"  {name}: {shape} on GATED precision ({delta:+.2f}). Keep anthropic — "
            "switching costs a re-record of every fixture."
        )
    regressions = [
        field
        for field in GATED_FIELDS
        if challenger["metrics"][field].precision
        < incumbent["metrics"][field].precision - MATERIAL_REGRESSION
    ]
    if regressions:
        return (
            f"  {name}: wins on GATED ({delta:+.2f}) but regresses on "
            f"{', '.join(regressions)}. An average can hide a collapse in one field — "
            "not an activation."
        )
    return (
        f"  {name}: beats anthropic on GATED precision ({delta:+.2f}) with no material "
        "per-field regression. Candidate for activation; re-record and re-run before switching."
    )


def report(results: dict[str, dict[str, Any]], missing: list[str]) -> None:
    print("Claim pre-fill golden set, one column per provider (offline, from fixtures):\n")
    header = f"  {'provider':<12} {'model':<22} {'GATED':>6}"
    header += "".join(f" {field:>19}" for field in PREFILL_SUGGESTION_FIELDS)
    print(header)
    for provider, result in results.items():
        row = f"  {provider:<12} {result['model']:<22} {result['gated'].precision:>6.2f}"
        row += "".join(
            f" {result['metrics'][field].precision:>19.2f}"
            for field in PREFILL_SUGGESTION_FIELDS
        )
        print(row)
    print("\n  Values are precision. GATED = micro-average of age_range + evidence_strength.")

    if missing:
        print(
            f"\n  No recordings for: {', '.join(missing)}. Record with "
            "`--record <provider> --model <provider>=<id>` and that provider's key "
            "(ollama needs no key, just a running server)."
        )

    incumbent = results.get(ai_provider.ANTHROPIC)
    challengers = {name: r for name, r in results.items() if name != ai_provider.ANTHROPIC}
    if incumbent and challengers:
        print("\nActivation rule:")
        for name, result in challengers.items():
            print(_verdict(incumbent, result, name))
    elif not challengers:
        print(
            "\n  Only the incumbent has recordings, so there is nothing to compare yet. "
            "That is the expected state until someone records a challenger."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare AI providers on the pre-fill golden set.")
    parser.add_argument(
        "--record",
        choices=list(ai_provider.LIVE_PROVIDERS),
        help="Call this provider live once per golden example and cache the responses.",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="PROVIDER=ID",
        help="Override a provider's model id (repeatable), e.g. --model openai=gpt-4o.",
    )
    parser.add_argument(
        "--providers",
        nargs="*",
        default=list(ai_provider.LIVE_PROVIDERS),
        help="Which providers to include in the comparison.",
    )
    args = parser.parse_args()

    models = parse_model_overrides(args.model)
    examples = load_examples()

    if args.record:
        count = record_provider(args.record, models[args.record], examples)
        if count < 0:
            return 1
        print(
            f"Recorded {count}/{len(examples)} example(s) for {args.record} "
            f"({models[args.record]}) into {ai_provider.CACHE_DIR}.\n"
        )

    # Same scorer as the pre-fill harness, so the columns are comparable to the
    # numbers in OPERATIONS.md rather than to a private metric.
    if ai_provider.embedding_provider() == "none":
        os.environ["EMBEDDING_PROVIDER"] = "st"
    embeddings = load_embeddings(examples)

    results: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for provider in args.providers:
        scored = score_provider(provider, models[provider], examples, embeddings)
        if scored is None:
            missing.append(provider)
        else:
            results[provider] = scored

    if not results:
        print("No provider has any recorded fixtures; nothing to compare.", file=sys.stderr)
        return 1

    report(results, missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
