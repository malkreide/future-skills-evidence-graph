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

Summations use math.fsum rather than the builtin sum so a score sitting
exactly on a rounding boundary (e.g. a claim mean of 7.75/10) resolves
identically on every Python version. CPython 3.12 switched the builtin
sum to compensated floating-point summation, so plain sum would round
such a value differently on 3.11 vs 3.12 and make the stored score
non-reproducible across environments; fsum is exact on both.
"""

from __future__ import annotations

import argparse
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

CLAIM_WEIGHTS = {"strong": 1.0, "moderate": 0.7, "low": 0.35}

# A skill with this many supporting claims gets the full breadth factor.
BREADTH_SATURATION = 6
BREADTH_FLOOR = 0.7
CONTRADICTION_PENALTY = 0.1


def claim_score(claim: dict[str, Any], sources: dict[str, dict[str, Any]]) -> float:
    source_scores = [
        SOURCE_WEIGHTS.get(sources[source_id]["source_type"], 0.25)
        for source_id in claim.get("source_ids", [])
        if source_id in sources
    ]
    source_component = math.fsum(source_scores) / len(source_scores) if source_scores else 0
    claim_component = CLAIM_WEIGHTS.get(claim.get("evidence_strength"), 0)
    return round((source_component * 0.6) + (claim_component * 0.4), 3)


def reviewed_claim_scores(
    claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> dict[str, float]:
    """Score the claims that may enter the evidence path.

    Claims that are still candidates or were rejected get no score at
    all, so skill_score skips them for both supporting and contradicting
    references instead of counting them at full weight.
    """
    return {
        claim["id"]: claim_score(claim, sources)
        for claim in claims
        if claim.get("status") == "reviewed"
    }


def compute_claim_scores() -> dict[str, float]:
    sources = {source["id"]: source for source in load_records("sources")}
    return reviewed_claim_scores(load_records("claims"), sources)


def skill_score(skill: dict[str, Any], claim_scores: dict[str, float]) -> float:
    supporting = [
        claim_scores[claim_id]
        for claim_id in skill.get("supporting_claim_ids", [])
        if claim_id in claim_scores
    ]
    if not supporting:
        return 0.0
    base = math.fsum(supporting) / len(supporting)
    breadth = min(len(supporting), BREADTH_SATURATION) / BREADTH_SATURATION
    contradiction = math.fsum(
        claim_scores[claim_id]
        for claim_id in skill.get("contradicting_claim_ids", [])
        if claim_id in claim_scores
    )
    score = base * (BREADTH_FLOOR + (1 - BREADTH_FLOOR) * breadth)
    score -= CONTRADICTION_PENALTY * contradiction
    return round(max(0.0, min(1.0, score)), 2)


def compute_skill_scores() -> dict[str, float]:
    claim_scores = compute_claim_scores()
    return {skill["id"]: skill_score(skill, claim_scores) for skill in load_records("skills")}


def write_skill_scores() -> int:
    claim_scores = compute_claim_scores()
    changed = 0
    for path in iter_json_files("skills"):
        records = load_json(path)
        dirty = False
        for skill in records:
            new_score = skill_score(skill, claim_scores)
            old_score = skill.get("evidence_score")
            if old_score == new_score:
                continue
            skill["evidence_score"] = new_score
            skill["updated_at"] = TODAY
            skill.setdefault("change_log", []).append(
                {
                    "date": TODAY,
                    "change": f"evidence_score {old_score} -> {new_score}",
                    "reason": "Recomputed deterministically from supporting claim scores.",
                }
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

    claim_scores = compute_claim_scores()
    for claim_id, score in claim_scores.items():
        print(f"claim,{claim_id},{score}")
    for skill in load_records("skills"):
        print(f"skill,{skill['id']},{skill_score(skill, claim_scores)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
