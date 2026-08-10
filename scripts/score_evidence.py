"""Deterministic evidence scoring for claims and skills.

Claim scores combine source quality (60%) with the claim's stated
evidence strength (40%). Only reviewed claims are scored: candidate or
rejected claims neither support nor penalize a skill. Skill scores are
derived from the supporting claim scores: the mean claim score is
scaled by a breadth factor that rewards multiple independent claims
(saturating at BREADTH_SATURATION), minus a penalty for contradicting
claims. This keeps the dashboard's central trust signal on a
reproducible evidence path.

validate_data.py recomputes these values and fails when stored
evidence_score values drift from the formula. Run with --write to
update data/skills/*.json after claims change.

What the two components mean, what a "low"/"moderate"/"strong" claim is,
and why each source type carries the weight it does is documented in
docs/evidenz-bewertung-anker.md. Changing any constant in this module is
a method change: bump METHOD_VERSION and record the new fingerprint, or
the pinning test fails.

The claim component reads appraisal.evidence_certainty when the claim has
been appraised and falls back to the legacy evidence_strength when it has
not. The two are not translations of each other: certainty answers "how
sure are we that this claim holds", the legacy value conflated design,
quantity and effect direction. scripts/appraisal.py is the successor
model; a legacy value keeps producing exactly the number it always did.

Unknown is not the same as weak. A claim whose source is missing, whose
source type has no weight, whose certainty is 'unverifiable', or whose
evidence_strength is not one of the anchored levels is *unscoreable*:
claim_score returns None instead
of quietly substituting a low number that reads like a bad score.
reviewed_claim_scores drops those claims, and validate_data.py fails on
any reviewed claim that cannot be scored, so an unscoreable claim is
loud rather than silently counted as weak evidence.

Summations use math.fsum rather than the builtin sum so a score sitting
exactly on a rounding boundary (e.g. a claim mean of 7.75/10) resolves
identically on every Python version. CPython 3.12 switched the builtin
sum to compensated floating-point summation, so plain sum would round
such a value differently on 3.11 vs 3.12 and make the stored score
non-reproducible across environments; fsum is exact on both.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from typing import Any

from common import TODAY, iter_json_files, load_json, load_records, write_json


SOURCE_WEIGHTS = {
    "systematic_review": 1.0,
    "framework": 0.85,
    "peer_reviewed_article": 0.8,
    "book": 0.75,
    "policy_report": 0.7,
    "conceptual_review": 0.65,
    "working_paper": 0.45,
    "dataset": 0.4,
    "web_resource": 0.25,
}

# Legacy claim vocabulary. Kept because the catalogue is stored in it;
# see docs/evidenz-bewertung-anker.md on why a legacy value is not
# reinterpreted as a certainty judgement.
CLAIM_WEIGHTS = {"strong": 1.0, "moderate": 0.7, "low": 0.35}

# The successor scale. very_low is a real, scoreable level -- weak
# evidence is still evidence. `unverifiable` deliberately has no weight:
# it says the source could not be identified, which is a statement about
# traceability, not a low grade. Weighting it would put an unfindable
# source on the same axis as a badly-run study. It therefore makes a
# claim UNSCOREABLE, the same way a missing source does -- "unknown is
# not weak", applied to the one case the old scale could not express.
CERTAINTY_WEIGHTS = {"strong": 1.0, "moderate": 0.7, "low": 0.35, "very_low": 0.15}

# A skill with this many supporting claims gets the full breadth factor.
BREADTH_SATURATION = 6
BREADTH_FLOOR = 0.85
CONTRADICTION_PENALTY = 0.1

SOURCE_COMPONENT_WEIGHT = 0.6
CLAIM_COMPONENT_WEIGHT = 0.4

# Human-declared version of the scoring method. Bump it whenever any
# constant above changes: the stored evidence_score of an active skill
# records the version that produced it, so two numbers computed under
# different methods can never sit side by side unmarked.
METHOD_VERSION = "1.2.0"

# The fingerprint each declared version must produce. It is derived from
# the constants themselves, so editing a weight without bumping
# METHOD_VERSION makes test_method_fingerprint_pins_declared_version fail
# instead of silently redefining what every stored score means.
METHOD_FINGERPRINTS = {
    "1.0.0": "7e6e20f1eec2da83",
    "1.1.0": "75279e202834675b",
    "1.2.0": "963ef4091391eaaa",
}


def method_parameters() -> dict[str, Any]:
    """Every constant that determines a score, in one canonical mapping."""
    return {
        "source_weights": SOURCE_WEIGHTS,
        "claim_weights": CLAIM_WEIGHTS,
        "certainty_weights": CERTAINTY_WEIGHTS,
        "breadth_saturation": BREADTH_SATURATION,
        "breadth_floor": BREADTH_FLOOR,
        "contradiction_penalty": CONTRADICTION_PENALTY,
        "source_component_weight": SOURCE_COMPONENT_WEIGHT,
        "claim_component_weight": CLAIM_COMPONENT_WEIGHT,
    }


def fingerprint(parameters: dict[str, Any]) -> str:
    """Stable short digest of a parameter set.

    Takes the parameters as an argument rather than reading the module
    constants so a test can show that changing any single weight changes
    the fingerprint.
    """
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def method_fingerprint() -> str:
    return fingerprint(method_parameters())


def claim_score_problem(
    claim: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> str | None:
    """Explain why a claim cannot be scored, or None when it can.

    Every branch here is a case where the old code substituted a number:
    a missing source and an unknown evidence_strength both scored as 0,
    an unknown source type scored 0.25 — the weight of the weakest known
    type. All three made a data defect look like weak evidence.
    """
    source_ids = claim.get("source_ids", [])
    if not source_ids:
        return "claim has no source_ids"
    for source_id in source_ids:
        if source_id not in sources:
            return f"source {source_id} is missing"
        source_type = sources[source_id].get("source_type")
        if source_type not in SOURCE_WEIGHTS:
            return f"source {source_id} has unweighted source_type {source_type!r}"
    certainty = (claim.get("appraisal") or {}).get("evidence_certainty")
    if certainty is not None:
        if certainty == "unverifiable":
            return "evidence_certainty is 'unverifiable': the source could not be identified"
        if certainty not in CERTAINTY_WEIGHTS:
            return f"evidence_certainty {certainty!r} has no anchored weight"
        return None
    if claim.get("evidence_strength") not in CLAIM_WEIGHTS:
        return f"evidence_strength {claim.get('evidence_strength')!r} has no anchored weight"
    return None


def claim_strength_weight(claim: dict[str, Any]) -> float:
    """The claim component's weight, from the appraisal when there is one.

    A claim that has been appraised is scored on its certainty; one that
    has not falls back to its legacy evidence_strength. The fallback is
    not a translation -- the legacy value keeps producing exactly the
    number it always produced, and nothing pretends it means certainty.
    """
    certainty = (claim.get("appraisal") or {}).get("evidence_certainty")
    if certainty is not None:
        return CERTAINTY_WEIGHTS[certainty]
    return CLAIM_WEIGHTS[claim["evidence_strength"]]


def claim_score(claim: dict[str, Any], sources: dict[str, dict[str, Any]]) -> float | None:
    """Score a claim, or return None when it is unscoreable.

    None means "we cannot say", not "weak". Callers must skip it rather
    than coerce it to a number; see claim_score_problem for the reasons.
    """
    if claim_score_problem(claim, sources) is not None:
        return None
    source_scores = [
        SOURCE_WEIGHTS[sources[source_id]["source_type"]]
        for source_id in claim["source_ids"]
    ]
    source_component = math.fsum(source_scores) / len(source_scores)
    claim_component = claim_strength_weight(claim)
    return round(
        (source_component * SOURCE_COMPONENT_WEIGHT)
        + (claim_component * CLAIM_COMPONENT_WEIGHT),
        3,
    )


def unscoreable_reviewed_claims(
    claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Reviewed claims that cannot be scored, mapped to the reason.

    validate_data.py turns these into errors: a reviewed claim carries an
    active skill's evidence, so it must never drop out of the score
    without anyone noticing.
    """
    return {
        claim["id"]: problem
        for claim in claims
        if claim.get("status") == "reviewed"
        and (problem := claim_score_problem(claim, sources)) is not None
    }


def reviewed_claim_scores(
    claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> dict[str, float]:
    """Score the claims that may enter the evidence path.

    Claims that are still candidates or were rejected get no score at
    all, so skill_score skips them for both supporting and contradicting
    references instead of counting them at full weight. Unscoreable
    reviewed claims drop out the same way, and validate_data.py reports
    them via unscoreable_reviewed_claims.
    """
    scores = {}
    for claim in claims:
        if claim.get("status") != "reviewed":
            continue
        score = claim_score(claim, sources)
        if score is not None:
            scores[claim["id"]] = score
    return scores


def compute_claim_scores() -> dict[str, float]:
    sources = {source["id"]: source for source in load_records("sources")}
    return reviewed_claim_scores(load_records("claims"), sources)


def score_breakdown(skill: dict[str, Any], claim_scores: dict[str, float]) -> dict[str, Any]:
    """The score's components, not just its total.

    The composite folds two things a reader needs apart: how good the
    evidence is *per claim* (claim_quality) and how many independent
    claims a reviewer has attached (breadth_factor). Over the current
    catalogue the second drives the ranking more than the first — see the
    limits section of docs/evidenz-bewertung-anker.md — so a skill can sit
    low because the catalogue is thin on it rather than because its
    evidence is weak. Exposing the parts is what lets the dashboard say
    which of the two it is.

    This is the single implementation of the formula; skill_score reads
    its total, so the parts can never drift from the number they explain.
    """
    supporting = [
        claim_scores[claim_id]
        for claim_id in skill.get("supporting_claim_ids", [])
        if claim_id in claim_scores
    ]
    contradicting = [
        claim_scores[claim_id]
        for claim_id in skill.get("contradicting_claim_ids", [])
        if claim_id in claim_scores
    ]
    if not supporting:
        return {
            "claim_quality": None,
            "supporting_claims": 0,
            "contradicting_claims": len(contradicting),
            "breadth_factor": None,
            "contradiction_penalty": None,
            "evidence_score": 0.0,
        }
    base = math.fsum(supporting) / len(supporting)
    breadth = min(len(supporting), BREADTH_SATURATION) / BREADTH_SATURATION
    breadth_factor = BREADTH_FLOOR + (1 - BREADTH_FLOOR) * breadth
    penalty = CONTRADICTION_PENALTY * math.fsum(contradicting)
    score = base * breadth_factor - penalty
    return {
        "claim_quality": round(base, 3),
        "supporting_claims": len(supporting),
        "contradicting_claims": len(contradicting),
        "breadth_factor": round(breadth_factor, 3),
        "contradiction_penalty": round(penalty, 3),
        "evidence_score": round(max(0.0, min(1.0, score)), 2),
    }


def skill_score(skill: dict[str, Any], claim_scores: dict[str, float]) -> float:
    return score_breakdown(skill, claim_scores)["evidence_score"]


def compute_skill_scores() -> dict[str, float]:
    claim_scores = compute_claim_scores()
    return {skill["id"]: skill_score(skill, claim_scores) for skill in load_records("skills")}


def write_skill_scores() -> int:
    """Rewrite stored scores and stamp the method version that produced them.

    A method change that leaves a score numerically unchanged still gets
    a change_log entry: without one, the stored 0.74 of a skill would
    silently mean something different than it did before, which is
    exactly the drift the version stamp exists to prevent.
    """
    claim_scores = compute_claim_scores()
    changed = 0
    for path in iter_json_files("skills"):
        records = load_json(path)
        dirty = False
        for skill in records:
            new_score = skill_score(skill, claim_scores)
            old_score = skill.get("evidence_score")
            old_method = skill.get("evidence_score_method")
            if old_score == new_score and old_method == METHOD_VERSION:
                continue
            if old_score == new_score:
                change = f"evidence_score method {old_method} -> {METHOD_VERSION}"
                reason = (
                    f"Recomputed under scoring method {METHOD_VERSION}; the value stayed "
                    f"at {new_score}."
                )
            else:
                change = f"evidence_score {old_score} -> {new_score}"
                reason = (
                    "Recomputed deterministically from supporting claim scores "
                    f"(scoring method {METHOD_VERSION})."
                )
            skill["evidence_score"] = new_score
            skill["evidence_score_method"] = METHOD_VERSION
            skill["updated_at"] = TODAY
            skill.setdefault("change_log", []).append(
                {"date": TODAY, "change": change, "reason": reason}
            )
            dirty = True
            changed += 1
        if dirty:
            write_json(path, records)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Score claims and skills deterministically.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Update evidence_score in data/skills/*.json instead of printing scores.",
    )
    args = parser.parse_args()

    if args.write:
        changed = write_skill_scores()
        print(f"Updated {changed} skill score(s).")
        return 0

    print(f"method,{METHOD_VERSION},{method_fingerprint()}")
    claim_scores = compute_claim_scores()
    for claim_id, score in claim_scores.items():
        print(f"claim,{claim_id},{score}")
    for skill in load_records("skills"):
        print(f"skill,{skill['id']},{skill_score(skill, claim_scores)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
