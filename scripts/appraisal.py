"""Multi-dimensional appraisal of a claim's evidence.

This module replaces a single conflated variable with separate ones.
``evidence_strength`` asked one question and answered several at once:
study design, methodological quality, amount of evidence, replication,
effect direction, effect size, generalisability, review quality and
whether the source can be verified at all. Those pull apart constantly.
The clearest case: a well-run trial reporting *no* difference is strong
evidence about a null effect, and the old scale had no way to say so --
"no significant difference" read as weak.

The central variable is now ``evidence_certainty``. It answers exactly
one question:

    How certain can we be, from the available scientific evidence, that
    THIS PARTICULAR CLAIM is supported?

Not "how large is the effect", not "how positive is it", not "how
prestigious is the source". Those are ``effect_magnitude``,
``effect_direction`` and ``source_type``, and they are separate fields
precisely so nobody has to guess which one a number meant.

Two things this module deliberately does NOT do:

- It does not derive certainty from ``source_type``. A systematic review
  of weak, heterogeneous primary studies is not strong evidence, and a
  single well-run trial can be. ``source_type`` stays a descriptive
  publication label; ``study_design`` is the methodological one, and only
  the latter reaches the derivation.
- It does not compute a point score. ``derive_certainty`` starts from the
  design, then applies *named* downgrades and upgrades in the manner of
  GRADE, and returns the reasons alongside the level. A reviewer can
  argue with a reason; nobody can argue with 7.4.

The derivation is an aid, not the authority. The recorded
``evidence_certainty`` is a human judgement. ``certainty_conflicts``
checks that judgement against the invariants that must hold regardless of
who rated it -- that is where the guardrails live.
"""

from __future__ import annotations

import json
import re
from typing import Any


# --- Controlled vocabularies ----------------------------------------------
#
# Every appraisal field is an enum, not free text. Free text cannot be
# aggregated, cannot be checked, and cannot be compared between two
# raters -- and comparing two raters is the whole point of the second-rater
# protocol in docs/eval-baseline.md.

# Ordinal, weakest to strongest. `unverifiable` is deliberately NOT on
# this scale: it is not "even weaker than very_low", it is a statement
# about traceability rather than about strength. Ordinal statistics
# (weighted kappa) run over ORDERED_CERTAINTY only; see eval_agreement.py.
ORDERED_CERTAINTY: tuple[str, ...] = ("very_low", "low", "moderate", "strong")
CERTAINTY_VALUES: tuple[str, ...] = (*ORDERED_CERTAINTY, "unverifiable")

SOURCE_PROVENANCE_VALUES = (
    "verified_real_source",
    "unverified_source",
    "synthetic_eval_case",
)

TRISTATE = ("true", "false", "unknown")

STUDY_DESIGN_VALUES = (
    "systematic_review",
    "meta_analysis",
    "rct",
    "cluster_rct",
    "quasi_experimental",
    "matched_comparison",
    "controlled_pre_post",
    "uncontrolled_pre_post",
    "cohort",
    "cross_sectional",
    "single_case",
    "qualitative",
    "descriptive",
    "policy_report",
    "working_paper",
    "consensus_framework",
    "other",
    "unknown",
)

COMPARATOR_VALUES = (
    "active_control",
    "passive_control",
    "waitlist",
    "business_as_usual",
    "historical_control",
    "matched_comparison",
    "none",
    "unclear",
)

OUTCOME_TYPE_VALUES = (
    "standardized_objective",
    "objective_nonstandardized",
    "behavioural",
    "teacher_rating",
    "self_report",
    "administrative",
    "mixed",
    "unclear",
)

EFFECT_DIRECTION_VALUES = (
    "positive",
    "negative",
    "null",
    "mixed",
    "unclear",
    "not_applicable",
)

EFFECT_MAGNITUDE_VALUES = (
    "large",
    "moderate",
    "small",
    "trivial",
    "null",
    "mixed",
    "unknown",
)

RISK_OF_BIAS_VALUES = ("low", "some_concerns", "high", "unknown")

DIRECTNESS_VALUES = ("direct", "partially_direct", "indirect", "unknown")

REPLICATION_VALUES = (
    "single_study",
    "multiple_studies",
    "multiple_contexts",
    "systematic_synthesis",
    "unknown",
)

# Consistency and heterogeneity are not in the original field list but a
# systematic review cannot be appraised without them: "32 studies" says
# nothing until you know whether they agreed. Kept as two fields because
# a review can report I-squared without discussing direction, or vice
# versa; the derivation counts them once (see _inconsistency_downgrade).
CONSISTENCY_VALUES = ("consistent", "mixed", "inconsistent", "unknown")
HETEROGENEITY_VALUES = ("low", "moderate", "high", "unknown")

# Precision is an explicit judgement, never derived from sample_size.
# "n > 200 therefore precise" is the kind of arithmetic that looks
# objective and is not: precision depends on the outcome's variance and
# the effect being estimated, neither of which a sample count carries.
PRECISION_VALUES = ("adequate", "imprecise", "unknown")

FOLLOW_UP_VALUES = (
    "none",
    "immediate_post",
    "delayed_post",
    "longitudinal",
    "unknown",
)

CLAIM_SUPPORT_VALUES = (
    "supported",
    "partially_supported",
    "not_supported",
    "cannot_determine",
)

# field name -> permitted values. Membership in this mapping is what makes
# a field an appraisal enum; validate_appraisal and the JSON Schema are
# both generated from it so a new value can never be permitted in one
# place and rejected in the other.
ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "source_provenance": SOURCE_PROVENANCE_VALUES,
    "source_verified": TRISTATE,
    "study_design": STUDY_DESIGN_VALUES,
    "comparator": COMPARATOR_VALUES,
    "outcome_type": OUTCOME_TYPE_VALUES,
    "effect_direction": EFFECT_DIRECTION_VALUES,
    "effect_magnitude": EFFECT_MAGNITUDE_VALUES,
    "risk_of_bias": RISK_OF_BIAS_VALUES,
    "directness": DIRECTNESS_VALUES,
    "replication": REPLICATION_VALUES,
    "consistency": CONSISTENCY_VALUES,
    "heterogeneity": HETEROGENEITY_VALUES,
    "precision": PRECISION_VALUES,
    "follow_up": FOLLOW_UP_VALUES,
    "claim_supported_by_source": CLAIM_SUPPORT_VALUES,
    "evidence_certainty": CERTAINTY_VALUES,
}

# Free-form / numeric appraisal fields. None is always allowed and always
# means "not derivable from the source", never "zero" and never "no".
SCALAR_FIELDS: dict[str, str] = {
    "sample_size": "integer",
    "effect_size": "number",
    "effect_size_metric": "string",
    "confidence_interval": "string",
    "age_range_explicit": "string",
    "age_range_inferred": "string",
    "age_inference_basis": "string",
    "grade_or_stage": "string",
    "country_or_jurisdiction": "string",
    "authors": "string",
    "year": "integer",
    "title": "string",
    "journal_or_publisher": "string",
    "doi": "string",
    "url": "string",
}

APPRAISAL_FIELDS: tuple[str, ...] = (*ENUM_FIELDS, *SCALAR_FIELDS)

# Bibliographic fields are transcription, not judgement: two people
# reading the same title should write the same title. They are excluded
# from the second-rater worksheet for that reason -- see
# SECOND_RATER_APPRAISAL_FIELDS in eval_agreement.py.
BIBLIOGRAPHIC_FIELDS: tuple[str, ...] = (
    "authors",
    "year",
    "title",
    "journal_or_publisher",
    "doi",
    "url",
)


# --- Validation ------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_appraisal(appraisal: dict[str, Any]) -> list[str]:
    """Every problem with *appraisal*, as human-readable messages.

    Returns a list rather than raising on the first problem: a reviewer
    fixing a record wants all of them at once, and the CLI prints them
    as a block.
    """
    problems: list[str] = []
    for field, value in sorted(appraisal.items()):
        if field not in APPRAISAL_FIELDS:
            problems.append(
                f"{field}: unknown appraisal field "
                f"(known fields: {', '.join(sorted(APPRAISAL_FIELDS))})"
            )
            continue
        if value is None:
            continue
        if field in ENUM_FIELDS:
            permitted = ENUM_FIELDS[field]
            if value not in permitted:
                problems.append(
                    f"{field}: {value!r} is not one of {', '.join(permitted)}"
                )
            continue
        kind = SCALAR_FIELDS[field]
        if kind == "integer" and not _is_int(value):
            problems.append(f"{field}: expected an integer or null, got {value!r}")
        elif kind == "number" and not isinstance(value, (int, float)):
            problems.append(f"{field}: expected a number or null, got {value!r}")
        elif kind == "string" and not isinstance(value, str):
            problems.append(f"{field}: expected a string or null, got {value!r}")
    problems.extend(_age_problems(appraisal))
    return problems


_AGE_RANGE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")


def _age_problems(appraisal: dict[str, Any]) -> list[str]:
    """Rules that keep reported ages apart from derived ones.

    A school stage is not an age. "11th grade" spans 15-17 in one country
    and 16-18 in another, and the repository already has the receipt: the
    pre-fill prompt tried stage-to-age mapping in v5 and age_range
    precision fell from 0.94 to 0.82 (see extract_claims.py). So an
    inferred band is allowed, but only in its own field and only with its
    basis written down.
    """
    problems: list[str] = []
    for field in ("age_range_explicit", "age_range_inferred"):
        value = appraisal.get(field)
        if value is not None and not _AGE_RANGE_RE.match(str(value)):
            problems.append(f'{field}: expected "min-max" in years, got {value!r}')
            continue
        if value is None:
            continue
        low, high = (int(part) for part in str(value).split("-"))
        if low > high:
            problems.append(f"{field}: {value!r} has its bounds the wrong way round")
    if appraisal.get("age_range_inferred") is not None and not appraisal.get(
        "age_inference_basis"
    ):
        problems.append(
            "age_range_inferred is set without age_inference_basis; an inferred "
            "band without its basis is indistinguishable from a reported one"
        )
    return problems


def normalized(appraisal: dict[str, Any]) -> dict[str, Any]:
    """*appraisal* with every known field present, missing ones as None.

    Absent and explicitly-null mean the same thing -- not derivable from
    the source -- so downstream code never has to distinguish them.
    """
    return {field: appraisal.get(field) for field in APPRAISAL_FIELDS}


# --- Certainty derivation --------------------------------------------------
#
# Adapted from GRADE: start from what the design can support, then apply
# named downgrades and upgrades. GRADE rates a *body* of evidence and
# starts randomised designs at "high"; a single claim backed by a single
# study is a narrower unit, so the baselines here start one step lower and
# "strong" has to be earned by replication or synthesis. That is the
# adaptation, and it is the reason a lone RCT lands at moderate rather
# than strong.

BASELINE_BY_DESIGN: dict[str, str | None] = {
    # Synthesis designs. Moderate, never strong, on the design alone:
    # a review is only as good as what it pooled, and whether it pooled
    # well is what consistency/heterogeneity/risk_of_bias record.
    "systematic_review": "moderate",
    "meta_analysis": "moderate",
    # Randomised designs: causal attribution is available in principle.
    "rct": "moderate",
    "cluster_rct": "moderate",
    # Controlled but not randomised: a comparison exists, confounding is
    # not ruled out.
    "quasi_experimental": "low",
    "matched_comparison": "low",
    "controlled_pre_post": "low",
    "cohort": "low",
    # No comparison condition at all. A pre-post improvement is consistent
    # with the intervention working, with maturation, with regression to
    # the mean and with testing effects; the design cannot separate them.
    "uncontrolled_pre_post": "very_low",
    "cross_sectional": "very_low",
    "single_case": "very_low",
    "qualitative": "very_low",
    "descriptive": "very_low",
    # Documents that report no primary outcome data of their own. A policy
    # report is not weak *as a policy report* -- it simply carries no
    # measured learning effect, which is what a learning claim needs.
    "policy_report": "very_low",
    "working_paper": "very_low",
    # A consensus framework rests on a documented procedure, which is real
    # evidence about what the field agreed on -- and no evidence about
    # whether following it improves learning. A causal claim from one gets
    # downgraded through directness, not through its baseline.
    "consensus_framework": "low",
    "other": None,
    "unknown": None,
}

_UPGRADING_REPLICATION = ("multiple_studies", "multiple_contexts", "systematic_synthesis")


def _shift(level: str, steps: int) -> str:
    """Move *level* along the ordinal scale, clamped at both ends."""
    index = ORDERED_CERTAINTY.index(level)
    return ORDERED_CERTAINTY[max(0, min(len(ORDERED_CERTAINTY) - 1, index + steps))]


def _inconsistency_downgrade(appraisal: dict[str, Any]) -> tuple[int, list[str]]:
    """One downgrade for inconsistency, however it was reported.

    High heterogeneity and inconsistent findings are the same problem
    described two ways. Counting both would punish a review twice for
    disclosing more.
    """
    if appraisal.get("consistency") == "inconsistent":
        return 1, ["inconsistent findings across studies (-1)"]
    if appraisal.get("heterogeneity") == "high":
        return 1, ["high heterogeneity between pooled studies (-1)"]
    return 0, []


def derive_certainty(appraisal: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Suggest a certainty level for *appraisal*, with the reasons.

    Returns ``(level, reasons)``. ``level`` is None when the record does
    not say enough -- that is a legitimate outcome and means "unknown",
    never "weak". The reasons are the audit trail; a caller that shows the
    level without them has thrown away the part a reviewer can argue with.

    This is advisory. The recorded evidence_certainty is a judgement, and
    a reviewer who overrides this is not doing anything wrong -- see
    certainty_conflicts for what a judgement may NOT do.
    """
    reasons: list[str] = []

    # Traceability first: if the claimed source cannot be identified at
    # all, no amount of described method makes it verifiable evidence.
    # Synthetic evaluation cases are exempt by construction -- their job
    # is to exercise this logic on a described design (their record still
    # carries source_provenance: synthetic_eval_case, so nothing
    # downstream can mistake one for a real publication).
    if (
        appraisal.get("source_provenance") == "unverified_source"
        and appraisal.get("source_verified") == "false"
    ):
        return "unverifiable", ["the cited source could not be identified"]

    support = appraisal.get("claim_supported_by_source")
    if support == "cannot_determine":
        return None, ["cannot determine whether the source supports this claim"]

    design = appraisal.get("study_design")
    baseline = BASELINE_BY_DESIGN.get(design) if design else None
    if baseline is None:
        return None, [f"no baseline for study_design {design!r}"]
    reasons.append(f"baseline {baseline} for study_design {design}")
    level = baseline

    downgrades = 0
    if appraisal.get("risk_of_bias") == "high":
        downgrades += 1
        reasons.append("high risk of bias (-1)")
    steps, why = _inconsistency_downgrade(appraisal)
    downgrades += steps
    reasons.extend(why)
    if appraisal.get("precision") == "imprecise":
        downgrades += 1
        reasons.append("imprecise estimate (-1)")
    # A previous cohort is not a control group. Everything else that
    # changed between the two years -- staff, intake, curriculum, the
    # pandemic -- rides along with the intervention.
    if appraisal.get("comparator") == "historical_control":
        downgrades += 1
        reasons.append("comparison against a historical cohort (-1)")
    directness = appraisal.get("directness")
    if directness == "indirect":
        downgrades += 2
        reasons.append("indirect evidence for this claim (-2)")
    elif directness == "partially_direct":
        downgrades += 1
        reasons.append("only partially direct evidence for this claim (-1)")
    if support == "partially_supported":
        downgrades += 1
        reasons.append("source only partially supports the claim as worded (-1)")

    if downgrades:
        level = _shift(level, -downgrades)

    # A single upgrade, and only for evidence that is both replicated and
    # clean. Replication in the presence of high bias is replication of
    # the bias.
    if (
        not downgrades
        and appraisal.get("replication") in _UPGRADING_REPLICATION
        and appraisal.get("consistency") == "consistent"
        and appraisal.get("risk_of_bias") == "low"
    ):
        level = _shift(level, 1)
        reasons.append("replicated, consistent and at low risk of bias (+1)")

    if support == "not_supported":
        level = "very_low"
        reasons.append("source does not support the claim as worded (capped at very_low)")

    return level, reasons


# --- Guardrails ------------------------------------------------------------


def certainty_conflicts(appraisal: dict[str, Any]) -> list[str]:
    """Invariants a recorded evidence_certainty must not violate.

    Distinct from derive_certainty on purpose. The derivation is a
    suggestion a reviewer may override; these are the overrides that are
    never defensible, so validate_data.py and the tests can treat them as
    errors without freezing anybody's judgement.
    """
    problems: list[str] = []
    recorded = appraisal.get("evidence_certainty")
    if recorded is None:
        return problems

    design = appraisal.get("study_design")
    support = appraisal.get("claim_supported_by_source")

    # The rule the old scale broke most often, in both directions.
    if recorded == "strong" and design in ("systematic_review", "meta_analysis"):
        if appraisal.get("consistency") not in ("consistent",) or appraisal.get(
            "risk_of_bias"
        ) not in ("low",):
            problems.append(
                "evidence_certainty 'strong' on a review requires consistency "
                "'consistent' and risk_of_bias 'low' to be recorded; a review is "
                "not strong because it is a review"
            )
    if recorded == "strong" and design in (
        "uncontrolled_pre_post",
        "single_case",
        "cross_sectional",
        "descriptive",
        "qualitative",
        "policy_report",
        "working_paper",
    ):
        problems.append(
            f"evidence_certainty 'strong' is not available for study_design "
            f"{design!r}: the design cannot isolate the effect the claim asserts"
        )
    if recorded in ("strong", "moderate") and support == "not_supported":
        problems.append(
            f"evidence_certainty {recorded!r} contradicts "
            "claim_supported_by_source 'not_supported'"
        )
    if recorded != "unverifiable" and appraisal.get("source_provenance") == (
        "unverified_source"
    ) and appraisal.get("source_verified") == "false":
        problems.append(
            f"evidence_certainty {recorded!r} on a source that could not be "
            "identified; the honest value is 'unverifiable'"
        )
    return problems


# --- Legacy migration ------------------------------------------------------
#
# The old vocabulary was {low, moderate, strong} on a variable that meant
# several things at once. The values are not wrong so much as
# under-determined: a legacy "moderate" might have meant a single-context
# study, a mixed finding, or a reviewer hedging.

LEGACY_STRENGTH_VALUES = ("low", "moderate", "strong")


def legacy_note(strength: str | None) -> str:
    """What a stored legacy evidence_strength does and does not tell us."""
    if strength not in LEGACY_STRENGTH_VALUES:
        return "no legacy evidence_strength recorded"
    return (
        f"legacy evidence_strength {strength!r}, assigned under the conflated "
        "pre-2.0 rubric; it mixes design, quantity and effect direction and is "
        "not a certainty judgement"
    )


def migrate_legacy(claim: dict[str, Any]) -> dict[str, Any]:
    """The appraisal a legacy claim record can honestly be read as.

    Deliberately thin. Copying ``evidence_strength`` into
    ``evidence_certainty`` would import the conflation this module exists
    to undo, so certainty comes out None -- unknown until somebody
    appraises it. The one thing the legacy record does carry reliably is
    that it was reviewed against a real source, which is why
    source_provenance is set and nothing else is.

    The age field gets the same treatment. A legacy ``age_range`` may have
    been read off the source or inferred from a stage name; the record
    does not say which, so it becomes neither age_range_explicit nor
    age_range_inferred. Guessing which one would launder an inference into
    a reported value, and that is the specific failure this migration is
    written to avoid.
    """
    appraisal = normalized({})
    appraisal["source_provenance"] = "verified_real_source"
    appraisal["source_verified"] = "true"
    return appraisal


def migration_report(claim: dict[str, Any]) -> dict[str, Any]:
    """What migrating *claim* would and would not carry over."""
    legacy_age = claim.get("age_range")
    return {
        "id": claim.get("id"),
        "migrated": sorted(k for k, v in migrate_legacy(claim).items() if v is not None),
        "not_migrated": {
            "evidence_strength": legacy_note(claim.get("evidence_strength")),
            "age_range": (
                f"legacy age_range {legacy_age!r} is of unrecorded origin (reported "
                "or inferred from a school stage); it stays in age_range and enters "
                "neither age_range_explicit nor age_range_inferred"
                if legacy_age
                else "no legacy age_range recorded"
            ),
        },
    }


# --- JSON Schema generation ------------------------------------------------


def json_schema() -> dict[str, Any]:
    """The appraisal object as JSON Schema, generated from the vocabularies.

    Generated rather than hand-written so schemas/claim.schema.json and
    validate_appraisal can never permit different value sets.
    """
    properties: dict[str, Any] = {}
    for field, values in ENUM_FIELDS.items():
        properties[field] = {"enum": [*values, None]}
    for field, kind in SCALAR_FIELDS.items():
        properties[field] = {"type": [kind, "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def _migration_summary() -> list[str]:
    """What migrating the stored catalogue would and would not carry over.

    Read-only by design. There is no --write: filling in an appraisal
    means reading the source, and a script that populated thirteen
    dimensions from a legacy record would be inventing twelve of them.
    What the command does is make the size of that gap visible.
    """
    from common import load_records

    claims = load_records("claims")
    reviewed = [claim for claim in claims if claim.get("status") == "reviewed"]
    already = [claim for claim in claims if (claim.get("appraisal") or {}).get(
        "evidence_certainty"
    )]
    with_age = [claim for claim in claims if claim.get("age_range")]
    lines = [
        "# Legacy -> appraisal migration",
        "",
        f"claims in the catalogue:            {len(claims)}",
        f"  of them reviewed:                 {len(reviewed)}",
        f"  already carrying a certainty:     {len(already)}",
        f"  carrying a legacy age_range:      {len(with_age)}",
        "",
        "Carried over automatically:",
        "  source_provenance = verified_real_source",
        "  source_verified   = true",
        "",
        "NOT carried over, and why:",
        f"  evidence_strength -> evidence_certainty: {legacy_note('moderate')}",
        "  age_range -> age_range_explicit: a legacy band may have been read off",
        "    the source or estimated from a school stage; the record does not say",
        "    which, so it enters neither the explicit nor the inferred field.",
        "",
        "Effect on scoring: none. An unappraised claim keeps scoring on its",
        "legacy evidence_strength and produces exactly the number it always did.",
    ]
    return lines


def main() -> int:
    """Print the vocabulary, or report what a legacy migration would do."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--migration-report",
        action="store_true",
        help="Report what migrating the stored claims would and would not carry.",
    )
    args = parser.parse_args()
    if args.migration_report:
        print("\n".join(_migration_summary()))
        return 0
    print(
        json.dumps(
            {
                "ordered_certainty": list(ORDERED_CERTAINTY),
                "certainty_values": list(CERTAINTY_VALUES),
                "enum_fields": {k: list(v) for k, v in ENUM_FIELDS.items()},
                "scalar_fields": SCALAR_FIELDS,
                "baseline_by_design": BASELINE_BY_DESIGN,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
