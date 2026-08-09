"""Measure how reproducible the evaluation LABELS are.

Every existing gate (eval_relevance.py, eval_claim_prefill.py,
eval_skill_links.py) measures a pipeline against `gold` and treats gold as
ground truth. None of them measures how reproducible gold itself is. That
gap decides how to read the gates: if two competent reviewers agree on
`evidence_strength` only ~80% of the time, a measured precision of 0.80
is already at the ceiling and the 0.70 floor has no room left to catch a
real regression before it hits label noise.

This script measures the label side. It compares two independent
judgments of the same items and reports agreement, Cohen's kappa, a
Wilson interval and — using the one-flip standard OPERATIONS.md applies
to its own thresholds — whether the sample is large enough to carry a
floor at all.

Independence is the whole game, so it is a first-class output rather than
an assumption. A comparison whose two sides cannot be shown to come from
separate judgments is reported as PROVENANCE UNVERIFIED and explicitly
not offered as a baseline: two records of one decision agree by
construction and measure nothing.

Usage:
    python scripts/eval_agreement.py                      # report every comparison
    python scripts/eval_agreement.py --worksheet relevance --out FILE
    python scripts/eval_agreement.py --worksheet claim_prefill --out FILE
    python scripts/eval_agreement.py --second-rater FILE   # score a completed worksheet

See docs/eval-baseline.md for the protocol and for what the numbers may
and may not be used for.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"

# OPERATIONS.md gates abstention (one flip moves it by 0.025) and refuses to
# gate link precision (one flip moves it by 0.071), calling the latter a
# tripwire instead. The same standard applied here: a metric may carry a floor
# once a single reviewer disagreement moves it by no more than this.
MAX_ONE_FLIP_FOR_GATE = 0.025
MIN_N_FOR_GATE = math.ceil(1 / MAX_ONE_FLIP_FOR_GATE)

# Fields a second rater re-judges, per set. Relevance is binary; the pre-fill
# fields are categorical or free text -- only the two structured ones can be
# compared as exact matches, which is why the worksheet asks for those.
SECOND_RATER_FIELDS = {
    "relevance": ["relevant"],
    "claim_prefill": ["evidence_strength", "age_range"],
}


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def load_eval(name: str) -> dict[str, Any]:
    return json.loads((EVAL_DIR / f"{name}.json").read_text(encoding="utf-8"))


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion.

    Chosen over the normal approximation because the interesting cases
    here sit at or near 1.0, where the normal interval collapses to a
    point and would suggest a precision the sample cannot support.
    """
    if total == 0:
        return (0.0, 1.0)
    phat = successes / total
    denominator = 1 + z**2 / total
    centre = (phat + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z**2 / (4 * total**2)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def cohens_kappa(pairs: list[tuple[Any, Any]]) -> float | None:
    """Chance-corrected agreement. None when it is undefined.

    Kappa is undefined when both raters used a single category: expected
    agreement is then 1.0 and the formula divides by zero. That is not a
    perfect score, it is an unusable sample, so it must not be reported
    as a number.
    """
    total = len(pairs)
    if total == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / total
    categories = {value for pair in pairs for value in pair}
    expected = sum(
        (sum(1 for a, _ in pairs if a == category) / total)
        * (sum(1 for _, b in pairs if b == category) / total)
        for category in categories
    )
    if math.isclose(expected, 1.0):
        return None
    return (observed - expected) / (1 - expected)


class Comparison:
    """Two judgments of the same items, plus what is known about their origin."""

    def __init__(
        self,
        name: str,
        field: str,
        pairs: list[tuple[Any, Any]],
        independent: bool,
        provenance: str,
    ) -> None:
        self.name = name
        self.field = field
        self.pairs = pairs
        self.independent = independent
        self.provenance = provenance

    @property
    def n(self) -> int:
        return len(self.pairs)

    @property
    def agreements(self) -> int:
        return sum(1 for a, b in self.pairs if a == b)

    @property
    def agreement(self) -> float | None:
        return self.agreements / self.n if self.n else None

    @property
    def one_flip(self) -> float | None:
        return 1 / self.n if self.n else None

    def gate_ready(self) -> bool:
        """Whether this comparison could carry a CI floor.

        Independence first: a large sample of one judgment recorded twice
        is still no baseline.
        """
        return self.independent and self.n >= MIN_N_FOR_GATE

    def report(self) -> list[str]:
        lines = [f"## {self.name} ({self.field})", f"pairs: {self.n}"]
        if self.n == 0:
            lines.append("no double-judged items -- nothing measured")
            lines.append(f"provenance: {self.provenance}")
            return lines
        low, high = wilson_interval(self.agreements, self.n)
        kappa = cohens_kappa(self.pairs)
        lines.append(
            f"agreement: {self.agreement:.3f} ({self.agreements}/{self.n}), "
            f"95% Wilson CI [{low:.3f}, {high:.3f}]"
        )
        lines.append(
            "cohen's kappa: undefined (only one category used -- the sample cannot "
            "separate agreement from chance)"
            if kappa is None
            else f"cohen's kappa: {kappa:.3f}"
        )
        lines.append(f"one disagreement moves agreement by: {self.one_flip:.3f}")
        lines.append(f"provenance: {self.provenance}")
        if not self.independent:
            lines.append(
                "VERDICT: PROVENANCE UNVERIFIED -- not usable as a baseline. Two "
                "records of the same judgment agree by construction."
            )
        elif self.n < MIN_N_FOR_GATE:
            lines.append(
                f"VERDICT: independent but underpowered -- {MIN_N_FOR_GATE - self.n} more "
                f"double-judged items needed before one flip drops to "
                f"{MAX_ONE_FLIP_FOR_GATE} and the number could carry a floor."
            )
        else:
            lines.append(
                f"VERDICT: usable as a baseline (one flip {self.one_flip:.3f} <= "
                f"{MAX_ONE_FLIP_FOR_GATE})."
            )
        return lines


def relevance_overlap() -> Comparison:
    """Curated relevance labels against the auto-harvested review decisions.

    These are the only two label sources in the repository that judge the
    same items, so they look like a free baseline. They are not, and the
    reason is recorded here rather than in a comment nobody reads:

    - Every overlapping item was harvested between 2026-06-20 and
      2026-06-29, all of it before the repository's first commit
      (2026-07-12), so git cannot establish which judgment came first.
    - 12 of the overlapping curated entries carry origin 'live_run' --
      "real candidates from the live pipeline runs", the same runs whose
      review decisions produced the harvested labels.
    - Their notes read as review rationales ("WASH public-health review;
      'education' is incidental"), i.e. what a reviewer writes while
      deciding, not what a second rater writes when re-judging blind.

    The likeliest history is one review session that both decided (and
    was auto-harvested) and hand-wrote the curated entry. Independence is
    therefore unverified, and the comparison is reported as such.
    """
    curated = {
        normalize_title(example["title"]): example
        for example in load_eval("relevance_labeled")["examples"]
    }
    harvested = {
        normalize_title(example["title"]): example
        for example in load_eval("relevance_harvested")["examples"]
    }
    pairs = [
        (curated[key]["relevant"], harvested[key]["relevant"])
        for key in sorted(set(curated) & set(harvested))
    ]
    return Comparison(
        name="curated vs harvested relevance labels",
        field="relevant",
        pairs=pairs,
        independent=False,
        provenance=(
            "same-session risk: overlap predates the repository's first commit and "
            "12/16 curated entries are 'live_run' from the runs that produced the "
            "harvested decisions (see docstring and docs/eval-baseline.md)"
        ),
    )


def second_rater_comparisons(path: Path) -> list[Comparison]:
    """Score a completed blind worksheet against the primary labels."""
    document = json.loads(path.read_text(encoding="utf-8"))
    protocol = document.get("protocol", {})
    set_name = protocol.get("source_set")
    if set_name not in SECOND_RATER_FIELDS:
        raise SystemExit(
            f"{path}: protocol.source_set must be one of {sorted(SECOND_RATER_FIELDS)}, "
            f"got {set_name!r}"
        )
    blind = bool(protocol.get("blind"))
    rater = protocol.get("rater") or "<unnamed>"
    primary = primary_labels(set_name)

    comparisons = []
    for field in SECOND_RATER_FIELDS[set_name]:
        pairs = []
        for label in document.get("labels", []):
            key = label.get("key")
            if key in primary and field in label and field in primary[key]:
                pairs.append((primary[key][field], label[field]))
        comparisons.append(
            Comparison(
                name=f"{set_name}: primary vs second rater {rater}",
                field=field,
                pairs=pairs,
                # A worksheet that was not filled in blind is not a second
                # opinion; seeing the primary label makes agreement cheap.
                independent=blind,
                provenance=(
                    f"second rater {rater}, blind={blind}, "
                    f"labeled_at={protocol.get('labeled_at') or '<unset>'}"
                ),
            )
        )
    return comparisons


def primary_labels(set_name: str) -> dict[str, dict[str, Any]]:
    """The primary judgment per item, keyed the way a worksheet keys it."""
    if set_name == "relevance":
        return {
            normalize_title(example["title"]): {"relevant": example["relevant"]}
            for example in load_eval("relevance_labeled")["examples"]
        }
    return {
        example["id"]: dict(example["gold"])
        for example in load_eval("claim_prefill_labeled")["examples"]
    }


def build_worksheet(set_name: str) -> dict[str, Any]:
    """A blind re-judging worksheet: inputs only, no gold, no notes.

    Withholding the primary label and its rationale is what makes the
    result a second opinion rather than a confirmation.
    """
    fields = SECOND_RATER_FIELDS[set_name]
    if set_name == "relevance":
        items = [
            {
                "key": normalize_title(example["title"]),
                "title": example["title"],
                "abstract": example["abstract"],
            }
            for example in load_eval("relevance_labeled")["examples"]
        ]
    else:
        items = [
            {
                "key": example["id"],
                "statement": example["statement"],
                "abstract": example["abstract"],
                "source_type": example["source_type"],
            }
            for example in load_eval("claim_prefill_labeled")["examples"]
        ]
    for item in items:
        for field in fields:
            item[field] = None
    return {
        "_README": (
            f"Blind second-rater worksheet for the {set_name} set, generated by "
            "scripts/eval_agreement.py --worksheet. Fill in "
            f"{fields} for every item WITHOUT consulting the primary labels, the "
            "notes, or the pipeline output; for evidence_strength apply the anchors "
            "in docs/evidenz-bewertung-anker.md. Then fill in protocol.rater and "
            "protocol.labeled_at and score it with --second-rater. Leave an item's "
            "field null to skip it; skipped items are simply not compared. Set "
            "protocol.blind to false if the primary labels were visible -- the "
            "result is then reported as not independent instead of silently "
            "counting as a baseline."
        ),
        "protocol": {
            "source_set": set_name,
            "rater": "",
            "labeled_at": "",
            "blind": True,
        },
        "labels": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure reproducibility of the evaluation labels."
    )
    parser.add_argument(
        "--worksheet",
        choices=sorted(SECOND_RATER_FIELDS),
        help="Emit a blind second-rater worksheet for this set instead of reporting.",
    )
    parser.add_argument("--out", help="Where to write the worksheet (default: stdout).")
    parser.add_argument(
        "--second-rater",
        action="append",
        default=[],
        help="Score a completed worksheet. May be repeated.",
    )
    args = parser.parse_args()

    if args.worksheet:
        worksheet = json.dumps(build_worksheet(args.worksheet), indent=2, ensure_ascii=False)
        if args.out:
            Path(args.out).write_text(worksheet + "\n", encoding="utf-8")
            print(f"Wrote worksheet to {args.out}")
        else:
            print(worksheet)
        return 0

    comparisons = [relevance_overlap()]
    for path in args.second_rater:
        comparisons.extend(second_rater_comparisons(Path(path)))

    print("# Label reproducibility\n")
    print(
        "These numbers describe the LABELS, not the pipeline. A gate measured\n"
        "against gold cannot be read without them: a floor above the label\n"
        "ceiling demands agreement the reviewers themselves do not reach.\n"
    )
    for comparison in comparisons:
        print("\n".join(comparison.report()))
        print()

    usable = [comparison for comparison in comparisons if comparison.gate_ready()]
    print("## Summary\n")
    if usable:
        for comparison in usable:
            print(f"- {comparison.name} ({comparison.field}): {comparison.agreement:.3f}")
    else:
        print(
            "No comparison is usable as a baseline yet, so no CI floor may be\n"
            "justified by label agreement. The floors in .github/workflows/validate.yml\n"
            "stay anchored where OPERATIONS.md put them (measured value minus\n"
            "headroom); what is still unknown is the ceiling those measurements sit\n"
            "under. docs/eval-baseline.md describes how to close that."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
