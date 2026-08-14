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
    python scripts/eval_agreement.py --worksheet catalog --out FILE
    python scripts/eval_agreement.py --worksheet catalog --fields evidence_certainty,claim_type
    python scripts/eval_agreement.py --second-rater FILE   # score a completed worksheet
    python scripts/eval_agreement.py --explain FILE        # calibration walkthrough

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

import appraisal

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"

# OPERATIONS.md gates abstention (one flip moves it by 0.025) and refuses to
# gate link precision (one flip moves it by 0.071), calling the latter a
# tripwire instead. The same standard applied here: a metric may carry a floor
# once a single reviewer disagreement moves it by no more than this.
MAX_ONE_FLIP_FOR_GATE = 0.025
MIN_N_FOR_GATE = math.ceil(1 / MAX_ONE_FLIP_FOR_GATE)

# Fields a second rater re-judges, per set.
#
# Not every field of the appraisal belongs here. Bibliographic fields
# (authors, year, doi, ...) are transcription: two people reading the same
# record should write the same value, and disagreement there is a typo,
# not a difference of judgement. Descriptive fields that the abstract
# either states or does not (sample_size, follow_up) are the same. What is
# rated twice is what actually requires a judgement call, and what a wrong
# value would mislead a reviewer about:
#
#   evidence_certainty        the central variable; ordinal
#   claim_supported_by_source the claim-vs-source check, which is the one
#                             judgement no metadata field can stand in for
#   study_design              nominal, and the input the certainty
#                             derivation is most sensitive to
#   effect_direction          nominal; kept separate from certainty on
#                             purpose, so a rater who conflates the two
#                             becomes visible instead of invisible
#   age_range_explicit        reported ages only -- the field whose old
#                             version silently mixed reported and inferred
SECOND_RATER_APPRAISAL_FIELDS = [
    "evidence_certainty",
    # Rated because it decides which derivation path applies: two raters
    # who disagree here are answering different questions, and that would
    # otherwise surface as unexplained scatter in evidence_certainty.
    "claim_type",
    "claim_supported_by_source",
    "study_design",
    "effect_direction",
    "age_range_explicit",
]

SECOND_RATER_FIELDS = {
    "relevance": ["relevant"],
    # The legacy pair stays rated so the successor model can be compared
    # against the scale it replaces on the same items.
    "claim_prefill": [*SECOND_RATER_APPRAISAL_FIELDS, "evidence_strength", "age_range"],
    # The reviewed catalogue claims -- the appraisals that actually drive
    # the dashboard's evidence scores. evidence_strength is rated here too,
    # so one pass answers a question the eval set cannot: is the successor
    # scale MORE reproducible than the one it replaced, on the same
    # reading of the same claim?
    #
    # The legacy age_range is deliberately NOT rated. Four reviewed claims
    # carry the string "Lehrende" in it -- an audience, not an age. Asking
    # a second rater to reproduce that is asking them to reproduce a
    # defect, and the disagreement would say nothing about either scale.
    "catalog": [*SECOND_RATER_APPRAISAL_FIELDS, "evidence_strength"],
}

# Fields whose categories sit on an ordinal scale, mapped to that scale.
# Weighted kappa uses it: two raters splitting moderate/strong have not
# made the same size of mistake as two raters splitting very_low/strong,
# and unweighted kappa cannot tell those apart.
ORDINAL_SCALES: dict[str, tuple[str, ...]] = {
    "evidence_certainty": appraisal.ORDERED_CERTAINTY,
}

# Values that are legitimate ratings but sit off their field's ordinal
# scale. `unverifiable` is the case that matters: it says the source could
# not be identified, which is a statement about traceability, not a rung
# on the certainty ladder. It is a real rating -- it counts towards raw
# agreement and unweighted kappa -- but a pair containing it cannot carry
# an ordinal distance, so weighted kappa is computed without it and the
# report says how many pairs that removed.
OFF_SCALE_VALUES: dict[str, frozenset[str]] = {
    "evidence_certainty": frozenset({"unverifiable"}),
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


def weighted_kappa(
    pairs: list[tuple[Any, Any]], scale: tuple[str, ...]
) -> float | None:
    """Linearly weighted kappa over an ordinal *scale*. None when undefined.

    Linear rather than quadratic: quadratic weights make a two-step
    disagreement four times as forgiving as a one-step one, which reads as
    a precise statement about how much worse a two-step error is. Nothing
    here measures that. Linear weights say only "further apart is worse",
    which is the whole of what the ordinal scale actually claims.

    Pairs holding a value outside *scale* are the caller's problem -- see
    ordinal_pairs, which separates them so the count of what was excluded
    can be reported rather than silently absorbed.
    """
    total = len(pairs)
    if total == 0:
        return None
    index = {value: position for position, value in enumerate(scale)}
    if any(a not in index or b not in index for a, b in pairs):
        return None
    span = len(scale) - 1
    if span == 0:
        return None

    def closeness(a: Any, b: Any) -> float:
        return 1 - abs(index[a] - index[b]) / span

    observed = math.fsum(closeness(a, b) for a, b in pairs) / total
    left = {value: sum(1 for a, _ in pairs if a == value) / total for value in scale}
    right = {value: sum(1 for _, b in pairs if b == value) / total for value in scale}
    expected = math.fsum(
        left[a] * right[b] * closeness(a, b) for a in scale for b in scale
    )
    if math.isclose(expected, 1.0):
        return None
    return (observed - expected) / (1 - expected)


# Above this many categories a square matrix is wider than a terminal and
# almost all of it is zeros. study_design alone uses eighteen.
MAX_MATRIX_CATEGORIES = 6


def confusion_matrix(pairs: list[tuple[Any, Any]]) -> list[str]:
    """The full cross-tabulation, rendered as text.

    A single agreement number hides which way the raters diverge. Two
    raters at 0.60 who differ by one rung everywhere have a calibration
    offset that a sharpened anchor can fix; two who scatter have a rubric
    that is not working. The matrix is the only output that separates
    those, so it is printed rather than summarised.

    Wide nominal fields get the same information as a list of the cells
    that are actually occupied. A grid of eighteen mostly-zero columns
    communicates less than six lines naming who confused what.
    """
    categories = sorted({str(value) for pair in pairs for value in pair})
    if not categories:
        return []
    counts: dict[tuple[str, str], int] = {}
    for a, b in pairs:
        key = (str(a), str(b))
        counts[key] = counts.get(key, 0) + 1

    if len(categories) > MAX_MATRIX_CATEGORIES:
        lines = [
            f"cross-tabulation ({len(categories)} categories -- occupied cells only, "
            "primary -> second rater)"
        ]
        disagreements = sorted(
            ((count, a, b) for (a, b), count in counts.items() if a != b), reverse=True
        )
        agreed = sum(count for (a, b), count in counts.items() if a == b)
        lines.append(f"  agreed on: {agreed}")
        if not disagreements:
            lines.append("  no disagreements")
        for count, a, b in disagreements:
            lines.append(f"  {a} -> {b}: {count}")
        return lines

    width = max(11, *(len(category) for category in categories))
    lines = ["confusion matrix (rows: primary, columns: second rater)"]
    lines.append("  " + " ".ljust(width) + "".join(c.rjust(width + 1) for c in categories))
    for row in categories:
        cells = "".join(
            str(counts.get((row, column), 0)).rjust(width + 1) for column in categories
        )
        lines.append("  " + row.ljust(width) + cells)
    return lines


class Comparison:
    """Two judgments of the same items, plus what is known about their origin."""

    def __init__(
        self,
        name: str,
        field: str,
        pairs: list[tuple[Any, Any]],
        independent: bool,
        provenance: str,
        skipped: int = 0,
        calibration: bool = False,
    ) -> None:
        self.name = name
        self.field = field
        self.pairs = pairs
        self.independent = independent
        self.provenance = provenance
        # A calibration round is blind while it is rated and unusable as a
        # baseline all the same: its items were picked to span the rubric
        # rather than to represent the set, and they get discussed
        # afterwards. Marked so a number from one cannot be quoted as the
        # measured ceiling.
        self.calibration = calibration
        # Items the second rater left null. Reported rather than dropped:
        # a field skipped forty times out of fifty says something about
        # the field, and an agreement figure computed on the remaining ten
        # would not show it.
        self.skipped = skipped

    def ordinal_pairs(self) -> tuple[list[tuple[Any, Any]], int]:
        """Pairs usable for weighted kappa, and how many were set aside.

        A rating of `unverifiable` is not a missing value -- it counts
        everywhere else -- but it has no position on the certainty ladder,
        so it cannot contribute an ordinal distance.
        """
        scale = ORDINAL_SCALES.get(self.field)
        if scale is None:
            return [], 0
        off_scale = OFF_SCALE_VALUES.get(self.field, frozenset())
        usable = [
            pair for pair in self.pairs if not (set(pair) & off_scale) and all(
                value in scale for value in pair
            )
        ]
        return usable, len(self.pairs) - len(usable)

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
        return self.independent and not self.calibration and self.n >= MIN_N_FOR_GATE

    def report(self) -> list[str]:
        lines = [f"## {self.name} ({self.field})"]
        lines.append(f"rated: {self.n}    skipped (null on either side): {self.skipped}")
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
        if self.field in ORDINAL_SCALES:
            usable, excluded = self.ordinal_pairs()
            weighted = weighted_kappa(usable, ORDINAL_SCALES[self.field])
            # Name the values that were actually set aside. Saying "e.g.
            # 'unverifiable'" when the excluded pairs were all nulls tells
            # the reader the wrong reason for a number they cannot see.
            scale = ORDINAL_SCALES[self.field]
            off = sorted(
                {
                    "null" if value is None else str(value)
                    for pair in self.pairs
                    for value in pair
                    if value not in scale
                }
            )
            note = (
                f" ({excluded} pair(s) excluded, holding {', '.join(off)} -- a valid "
                "answer with no position on the ordinal scale)"
                if excluded
                else ""
            )
            lines.append(
                f"linearly weighted kappa: undefined{note}"
                if weighted is None
                else f"linearly weighted kappa (ordinal): {weighted:.3f}{note}"
            )
        lines.extend(confusion_matrix(self.pairs))
        lines.append(f"one disagreement moves agreement by: {self.one_flip:.3f}")
        lines.append(f"provenance: {self.provenance}")
        if not self.independent:
            lines.append(
                "VERDICT: PROVENANCE UNVERIFIED -- not usable as a baseline. Two "
                "records of the same judgment agree by construction."
            )
        elif self.calibration:
            lines.append(
                "VERDICT: calibration round -- not a baseline. Its items were "
                "chosen to span the rubric rather than to represent the set, and "
                "they are discussed afterwards; a later pass over the same items "
                "would no longer be blind."
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


COMPLETED_PASS_GLOB = "*_second_rater_completed.json"


def completed_passes() -> list[Path]:
    """Filled second-rater sheets stored in eval/, oldest name first.

    Picked up by the no-argument report so `make agreement` reflects what
    has actually been measured. Without this the summary kept printing
    "no comparison is usable as a baseline yet" after a baseline had been
    measured and committed -- the one sentence in the whole tool that
    somebody would quote, saying the opposite of the truth.

    The naming convention is the contract: a sheet is a completed pass
    once it is named *_second_rater_completed.json. The blank templates
    (*_second_rater.json) are regenerated by `make agreement-worksheet`
    and must never be swept up by that.
    """
    return sorted(EVAL_DIR.glob(COMPLETED_PASS_GLOB))


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


def _item_untouched(label: dict[str, Any], rated_fields: list[str]) -> bool:
    """Whether the rater left this whole item alone.

    The safe direction of the ambiguity. If null were read as an answer
    everywhere, a worksheet nobody filled in would report agreement on
    every field whose primary label is also null -- an empty file scoring
    as a baseline is the one outcome this protocol must never produce.
    """
    return all(label.get(field) is None for field in rated_fields)


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

    # What the worksheet asked for, not what the set could ask for. A pass
    # narrowed to two fields must be scored on those two: the fields nobody
    # was asked about are all null, and comparing them against a non-null
    # primary label would report six disagreements per item for work that
    # was never requested.
    rated_fields = resolve_fields(set_name, protocol.get("rated_fields"))
    comparisons = []
    for field in rated_fields:
        pairs = []
        skipped = 0
        for label in document.get("labels", []):
            key = label.get("key")
            if key not in primary or field not in label or field not in primary[key]:
                continue
            # null carries two meanings in a worksheet, and telling them
            # apart matters: "I did not judge this item" and "I judged it,
            # and the answer is nothing" -- no age is stated, the abstract
            # does not say enough. Deciding per field would collapse them
            # and throw away the second, which for age_range_explicit is
            # 48 of 50 items. Deciding per ITEM separates them: an item
            # where the rater entered nothing at all is a skip; in any
            # item they worked on, a null is an answer.
            if _item_untouched(label, rated_fields):
                skipped += 1
                continue
            pairs.append((primary[key][field], label[field]))
        comparisons.append(
            Comparison(
                name=f"{set_name}: primary vs second rater {rater}",
                field=field,
                pairs=pairs,
                skipped=skipped,
                # A worksheet that was not filled in blind is not a second
                # opinion; seeing the primary label makes agreement cheap.
                independent=blind,
                calibration=bool(protocol.get("calibration_subset")),
                provenance=(
                    f"second rater {rater}, blind={blind}, "
                    f"labeled_at={protocol.get('labeled_at') or '<unset>'}"
                    # Which ruleset the pass actually measured. Without it a
                    # kappa recorded against an anchor that has since been
                    # sharpened reads as if it described the current one.
                    + (
                        f", appraisal rules {protocol['appraisal_method_at_rating']}"
                        if protocol.get("appraisal_method_at_rating")
                        else ""
                    )
                    # A caveat about the pass belongs in the record, but
                    # not inside the rater's name -- the summary prints
                    # that per field, and a paragraph there buries the
                    # numbers it is meant to qualify.
                    + (f"\n  note: {protocol['notes']}" if protocol.get("notes") else "")
                ),
            )
        )
    return comparisons


def primary_labels(set_name: str) -> dict[str, dict[str, Any]]:
    """The primary judgment per item, keyed the way a worksheet keys it.

    For the pre-fill set this merges two label layers: the frozen legacy
    `gold` and the successor `gold_appraisal`. Both are offered to the
    comparison so one blind pass measures agreement on the new scale and
    on the scale it replaces, from the same reading of the same abstract.
    """
    if set_name == "relevance":
        return {
            normalize_title(example["title"]): {"relevant": example["relevant"]}
            for example in load_eval("relevance_labeled")["examples"]
        }
    if set_name == "catalog":
        return {
            claim["id"]: {
                "evidence_strength": claim.get("evidence_strength"),
                **claim["appraisal"],
            }
            for claim in appraised_claims()
        }
    labels = {}
    for example in load_eval("claim_prefill_labeled")["examples"]:
        merged = dict(example["gold"])
        merged.update(example.get("gold_appraisal") or {})
        labels[example["id"]] = merged
    return labels


def appraised_claims() -> list[dict[str, Any]]:
    """Reviewed catalogue claims that carry an appraisal, in a stable order."""
    from common import load_records

    return sorted(
        (claim for claim in load_records("claims") if claim.get("appraisal")),
        key=lambda claim: claim["id"],
    )


ANCHOR_DOC = EVAL_DIR.parent / "docs" / "evidenz-bewertung-anker.md"


ANCHOR_SECTION = "## Anker: `evidence_certainty`"
SUPPORT_ANCHOR_SECTION = "## Anker: `claim_supported_by_source`"


def _anchor_table(section: str, expected: set[str]) -> dict[str, str]:
    """Read one two-column anchor table out of the methodology document.

    Scoped to a section because the document carries several such tables;
    a document-wide scan would pick up whichever came first.
    """
    text = ANCHOR_DOC.read_text(encoding="utf-8")
    start = text.find(section)
    if start < 0:
        raise SystemExit(f"{ANCHOR_DOC}: section {section!r} not found")
    end = text.find("\n## ", start + len(section))
    body = text[start : end if end > 0 else len(text)]
    rows = re.findall(r"^\|\s*`([a-z_]+)`\s*\|\s*(.+?)\s*\|\s*$", body, re.M)
    rubric = {level: definition for level, definition in rows}
    if set(rubric) != expected:
        raise SystemExit(
            f"{ANCHOR_DOC}: the {section} table defines {sorted(rubric)}, but the "
            f"vocabulary is {sorted(expected)}. The worksheet must not ship with a "
            "rubric that omits a permitted value."
        )
    return rubric


def support_rubric() -> dict[str, str]:
    """The claim_supported_by_source anchors, read out of the document.

    Sharpened after the first measured pass put this field at kappa 0.039.
    The old wording let `cannot_determine` mean "the excerpt is too short
    to tell", which is a question two other fields already answer --
    source_verified for traceability, directness for PICO fit. Reading the
    definitions from the document rather than restating them here is what
    keeps the four places that describe this field from drifting apart.
    """
    return _anchor_table(
        SUPPORT_ANCHOR_SECTION, set(appraisal.CLAIM_SUPPORT_VALUES)
    )


def anchor_rubric() -> dict[str, str]:
    """The evidence_certainty anchors, read out of the methodology document.

    Extracted rather than restated: a copy pasted into this file would go
    stale the first time the anchors are sharpened, and a worksheet
    carrying an outdated rubric would produce disagreement that looks
    like rater variance but is really two different rulebooks.

    Scoped to one section because the document also carries the legacy
    three-level table for readers of old records; a document-wide scan
    would silently pick up whichever came first.

    Raises if the table cannot be found, because shipping a worksheet
    with an empty rubric is worse than not shipping one.
    """
    return _anchor_table(ANCHOR_SECTION, set(appraisal.CERTAINTY_VALUES))


def resolve_fields(set_name: str, requested: list[str] | None) -> list[str]:
    """The fields a worksheet asks for, defaulting to all of them.

    A rejected name lists what was available rather than just failing:
    the caller is picking from a vocabulary they cannot see.
    """
    available = SECOND_RATER_FIELDS[set_name]
    if not requested:
        return list(available)
    unknown = [field for field in requested if field not in available]
    if unknown:
        raise SystemExit(
            f"--fields: {', '.join(unknown)} is not rated for set {set_name!r}. "
            f"Available: {', '.join(available)}"
        )
    # Keep the canonical order rather than the order typed, so two
    # worksheets asking for the same fields look the same.
    return [field for field in available if field in requested]


def build_worksheet(
    set_name: str, fields: list[str] | None = None, only: list[str] | None = None
) -> dict[str, Any]:
    """A blind re-judging worksheet: inputs only, no gold, no notes.

    Withholding the primary label and its rationale is what makes the
    result a second opinion rather than a confirmation.

    *fields* narrows what is asked. The chosen set is recorded in
    protocol.rated_fields and scoring honours it -- without that, a
    worksheet asking for two fields would be scored against all eight,
    and the six nobody was asked about would each read as a disagreement.
    """
    fields = resolve_fields(set_name, fields)
    if set_name == "relevance":
        items = [
            {
                "key": normalize_title(example["title"]),
                "title": example["title"],
                "abstract": example["abstract"],
            }
            for example in load_eval("relevance_labeled")["examples"]
        ]
    elif set_name == "catalog":
        from common import load_records

        sources = {source["id"]: source for source in load_records("sources")}
        items = []
        for claim in appraised_claims():
            source = sources[claim["source_ids"][0]]
            # Only the claim's own statement and the SOURCE's abstract. The
            # claim's `context` and `text_anchor` are review-written and
            # name the design outright -- "single-group study", "Systematic
            # review synthesis", "Mixed-methods study". Handing those to a
            # second rater would be handing them one of the answers.
            items.append(
                {
                    "key": claim["id"],
                    "statement": claim["statement"],
                    "source_title": source.get("title"),
                    "source_type": source.get("source_type"),
                    "abstract": source.get("abstract"),
                }
            )
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
    if only:
        available = {item["key"] for item in items}
        unknown = [key for key in only if key not in available]
        if unknown:
            raise SystemExit(
                f"--only: {', '.join(unknown)} is not in set {set_name!r} "
                f"({len(available)} items available)"
            )
        items = [item for item in items if item["key"] in set(only)]
    for item in items:
        for field in fields:
            item[field] = None
    return {
        "_README": (
            f"Blind second-rater worksheet for the {set_name} set, generated by "
            "scripts/eval_agreement.py --worksheet. Fill in "
            f"{fields} for every item WITHOUT consulting the primary labels, the "
            "notes, or the pipeline output; apply the rubric carried in this file "
            "(the full version is docs/evidenz-bewertung-anker.md). Then fill in "
            "protocol.rater and protocol.labeled_at and score it with "
            "--second-rater. Leave an item's field null to skip it; skipped items "
            "are counted and reported, not silently dropped. Set protocol.blind to "
            "false if the primary labels were visible -- the result is then "
            "reported as not independent instead of silently counting as a baseline."
        ),
        "protocol": {
            "source_set": set_name,
            "rater": "",
            "labeled_at": "",
            # Free text about how this pass came about -- anything that
            # qualifies the numbers without being the rater's identity.
            "notes": "",
            "blind": True,
            # Stamped when the sheet is generated: the rules a rater will
            # apply are the rules in force now, and a later sharpening
            # must not silently reinterpret what they measured.
            "appraisal_method_at_rating": appraisal.APPRAISAL_VERSION,
            # A narrowed item set is a calibration round, not a baseline:
            # its cases get discussed afterwards, which ends their
            # independence. Recorded so a scored calibration sheet cannot
            # later be mistaken for a measured one.
            **({"calibration_subset": True} if only else {}),
            # What this worksheet actually asked for. Scoring reads it, so
            # a narrowed pass is compared on what it was asked and not on
            # what it was not.
            "rated_fields": fields,
        },
        # The rubric travels with the worksheet so a rater working through
        # fifty items never has to leave the file to recall what a level
        # means. Read live from the methodology doc, never restated here.
        **_rubric_for(fields),
        "labels": items,
    }


# Which rubric block belongs to which rated field. Explicit rather than
# derived from the key name: two blocks describe the same field, one block
# covers two fields, and a name-matching rule that has to carry both
# exceptions is harder to check than the mapping it replaces.
RUBRIC_FOR_FIELD: dict[str, tuple[str, ...]] = {
    "evidence_certainty": ("rubrik_evidence_certainty", "rubrik_evidence_certainty_hinweis"),
    "claim_type": ("rubrik_claim_type",),
    "claim_supported_by_source": ("rubrik_claim_supported_by_source",),
    "study_design": ("rubrik_study_design",),
    "effect_direction": ("rubrik_effect_direction",),
    "age_range_explicit": ("rubrik_age_range_explicit",),
    "evidence_strength": ("rubrik_legacy_felder",),
    "age_range": ("rubrik_legacy_felder",),
}


def _rubric_for(fields: list[str]) -> dict[str, Any]:
    """The rubric blocks a worksheet asking for *fields* should carry.

    A rubric entry for a field nobody is rating is noise in a file
    somebody has to read forty times.
    """
    if "evidence_certainty" not in fields:
        return {}
    wanted = {key for field in fields for key in RUBRIC_FOR_FIELD.get(field, ())}
    return {
        key: value for key, value in _prefill_rubric().items() if key in wanted
    }


def _prefill_rubric() -> dict[str, Any]:
    """The rubric block a pre-fill worksheet carries.

    Each entry says what the field is asking, in the terms the rater
    actually needs. The pointed ones are deliberate:

    - evidence_certainty is about how sure we can be, not about how large
      or how positive the effect is. A clean null finding is a finding.
    - claim_supported_by_source ignores quality entirely. A weak study can
      fully support a modestly-worded claim; a strong one can fail to
      support an overreaching claim drawn from it.
    - age_range_explicit takes reported ages only. The instruction it
      replaces told raters to fill in "the usual band for that stage",
      which is how 43 of the 50 legacy age labels came to describe ages
      nobody had reported.
    """
    return {
        "rubrik_evidence_certainty": anchor_rubric(),
        "rubrik_evidence_certainty_hinweis": (
            "Frage: Wie sicher kann man sich auf Basis der beschriebenen Evidenz "
            "sein, dass GENAU DIESE Aussage zutrifft? Nicht: wie gross oder wie "
            "positiv der Effekt ist. Ein sauber durchgefuehrter Nullbefund ist ein "
            "Befund und kann moderate oder hohe Sicherheit tragen. Der "
            "Publikationstyp allein entscheidet nichts -- ein systematischer "
            "Review aus schwachen, heterogenen Primaerstudien ist nicht 'strong'. "
            "Steht im Abstract zu wenig, ist null die richtige Antwort."
        ),
        "rubrik_claim_supported_by_source": {
            **support_rubric(),
            "_hinweis": (
                "Die Frage ist INHALTLICH: behauptet die Quelle, was die Aussage "
                "behauptet? Nicht: ist der Auszug ausfuehrlich genug, um es zu "
                "beweisen. KUERZE IST KEIN GRUND fuer cannot_determine -- ein "
                "Einzeiler, der die Aussage inhaltlich deckt, ergibt supported. "
                "Ob die Quelle auffindbar ist, misst source_verified; ob "
                "Population und Outcome zur Aussage passen, misst directness. "
                "Beides hier noch einmal zu bewerten, zaehlt es doppelt."
            ),
        },
        "rubrik_claim_type": (
            "Welche Art von Aussage ist das? "
            + ", ".join(appraisal.CLAIM_TYPE_VALUES)
            + ". Behauptet sie eine Wirkung (causal_effect), einen Zusammenhang "
            "(association), beschreibt sie, was beobachtet wurde (descriptive), "
            "empfiehlt sie etwas (normative) oder legt sie einen Begriff fest "
            "(definitional)? Danach richtet sich, woran die Aussage gemessen wird."
        ),
        "rubrik_study_design": (
            "Das im Text beschriebene Design, aus: "
            + ", ".join(appraisal.STUDY_DESIGN_VALUES)
            + ". Nicht vom Publikationstyp ableiten. Nennt der Text kein Design, "
            "'unknown' -- nicht das wahrscheinlichste raten."
        ),
        "rubrik_effect_direction": (
            "Richtung des berichteten Effekts, aus: "
            + ", ".join(appraisal.EFFECT_DIRECTION_VALUES)
            + ". 'null' heisst: kein Unterschied gefunden -- ein legitimes "
            "Ergebnis, keine schwache Evidenz. 'not_applicable', wenn gar kein "
            "Effekt gemessen wurde (z. B. reine Designbeschreibung)."
        ),
        "rubrik_age_range_explicit": (
            "NUR ausdruecklich im Text genannte Alterswerte, als \"von-bis\" in "
            "Jahren (z. B. \"22-55\"). Eine Schulstufe ist KEINE Altersangabe: "
            "\"11th-grade students\" oder \"upper secondary\" ergibt null, nicht "
            "16-17 -- dieselbe Stufenbezeichnung deckt je nach Land andere Jahre "
            "ab. Steht keine Altersangabe im Text, null."
        ),
        "rubrik_legacy_felder": (
            "evidence_strength und age_range sind die ALTEN Felder und werden nur "
            "mitgefuehrt, damit sich beide Skalen an derselben Lektuere vergleichen "
            "lassen. evidence_strength: low|moderate|strong nach der alten, "
            "vermischenden Rubrik. age_range: die alte Praxis inklusive aus der "
            "Schulstufe geschaetzter Spannen. Wer nur die neue Skala bewerten "
            "will, laesst beide null."
        ),
    }


def explain_report(path: Path) -> list[str]:
    """Per-item comparison for a calibration round.

    A calibration round normally ends in a conversation between the two
    raters. Here one side is a stored appraisal, so there is nobody in the
    room to ask why -- which would leave the round as a list of
    differences and no way to tell a rubric problem from a reading slip.

    derive_certainty() already returns its reasons; this prints them next
    to both answers. It is deliberately NOT part of --second-rater: seeing
    the stored reasoning is exactly what must not happen before a measured
    pass, and it should take a separate, deliberate command.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    protocol = document.get("protocol", {})
    set_name = protocol.get("source_set")
    if set_name not in SECOND_RATER_FIELDS:
        raise SystemExit(
            f"{path}: protocol.source_set must be one of {sorted(SECOND_RATER_FIELDS)}, "
            f"got {set_name!r}"
        )
    primary = primary_labels(set_name)
    rated = resolve_fields(set_name, protocol.get("rated_fields"))

    lines = [
        f"# Calibration walkthrough: {path.name}",
        "",
        "For each item: what you answered, what the stored appraisal says, and",
        "why. Use it to sort each disagreement into one of three kinds --",
        "the rubric was ambiguous (sharpen the anchor), one side misread the",
        "abstract (no action), or you genuinely judge it differently (record",
        "it and move on). Only the first kind is a defect.",
        "",
        "Do NOT run this on the items you intend to measure.",
        "",
    ]
    for label in document.get("labels", []):
        key = label.get("key")
        if key not in primary:
            continue
        differing = [
            field
            for field in rated
            if field in label and label[field] != primary[key].get(field)
        ]
        marker = "DISAGREE" if differing else "agree"
        lines.append(f"## [{marker}] {key}")
        for field in rated:
            if field not in label:
                continue
            mine, stored = label[field], primary[key].get(field)
            flag = "  <-- differs" if mine != stored else ""
            lines.append(f"  {field:26} you: {str(mine):22} stored: {str(stored)}{flag}")
        block = primary[key]
        if any(field in block for field in appraisal.APPRAISAL_FIELDS):
            level, reasons = appraisal.derive_certainty(block)
            lines.append(f"  why the stored evidence_certainty is {level}:")
            for reason in reasons:
                lines.append(f"    - {reason}")
        lines.append("")
    return lines


def legacy_drift_report() -> list[str]:
    """Where the frozen legacy labels and the appraisal disagree.

    Not a rater comparison -- both layers come from this repository. It
    answers a different question: what did replacing the conflated scale
    actually change, on the same fifty readings? Printing the
    cross-tabulation rather than a summary is the point; a single
    "34 changed" would hide that the change has a direction.
    """
    examples = load_eval("claim_prefill_labeled")["examples"]
    lines = ["# Legacy labels vs appraisal (same items, both from this repository)", ""]

    pairs = [
        (example["gold"]["evidence_strength"],
         (example.get("gold_appraisal") or {}).get("evidence_certainty"))
        for example in examples
    ]
    changed = sum(1 for legacy, new in pairs if legacy != new)
    lines.append(
        f"## evidence_strength -> evidence_certainty ({changed}/{len(pairs)} differ)"
    )
    lines.extend(confusion_matrix([(a, str(b)) for a, b in pairs]))
    lines.append("")

    legacy_ages = [e for e in examples if e["gold"]["age_range"]]
    explicit = [
        e for e in examples if (e.get("gold_appraisal") or {}).get("age_range_explicit")
    ]
    both = [e for e in legacy_ages if (e.get("gold_appraisal") or {}).get(
        "age_range_explicit"
    )]
    lines.append("## age_range -> age_range_explicit")
    lines.append(f"legacy age_range set:              {len(legacy_ages)}/{len(examples)}")
    lines.append(f"ages actually reported in source:  {len(explicit)}/{len(examples)}")
    lines.append(f"overlap:                           {len(both)}")
    for example in explicit:
        lines.append(
            f"  {example['id']}: source reports "
            f"{example['gold_appraisal']['age_range_explicit']}, legacy label was "
            f"{example['gold']['age_range']!r}"
        )
    return lines


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
        "--only",
        help="Comma-separated item keys to include -- for a calibration round. "
        "Marks the worksheet protocol.calibration_subset, because its cases get "
        "discussed afterwards and can no longer serve as a measured sample.",
    )
    parser.add_argument(
        "--fields",
        help="Comma-separated subset of fields the worksheet should ask for "
        "(default: all of them). Recorded in protocol.rated_fields and honoured "
        "by --second-rater, so a narrowed pass is scored on what it was asked.",
    )
    parser.add_argument(
        "--second-rater",
        action="append",
        default=[],
        help="Score a completed worksheet. May be repeated.",
    )
    parser.add_argument(
        "--explain",
        help="Walk through a completed CALIBRATION worksheet: both answers per "
        "item plus why the stored appraisal reads as it does. Never run this on "
        "items you still intend to measure.",
    )
    parser.add_argument(
        "--legacy-drift",
        action="store_true",
        help="Report where the legacy labels and the appraisal disagree on the "
        "same pre-fill items, instead of reporting rater agreement.",
    )
    args = parser.parse_args()

    if args.explain:
        print("\n".join(explain_report(Path(args.explain))))
        return 0

    if args.legacy_drift:
        print("\n".join(legacy_drift_report()))
        return 0

    if args.worksheet:
        chosen = [f.strip() for f in args.fields.split(",")] if args.fields else None
        only = [k.strip() for k in args.only.split(",")] if args.only else None
        worksheet = json.dumps(
            build_worksheet(args.worksheet, chosen, only), indent=2, ensure_ascii=False
        )
        if args.out:
            Path(args.out).write_text(worksheet + "\n", encoding="utf-8")
            print(f"Wrote worksheet to {args.out}")
        else:
            print(worksheet)
        return 0

    comparisons = [relevance_overlap()]
    for path in completed_passes():
        comparisons.extend(second_rater_comparisons(path))
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
