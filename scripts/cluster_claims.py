"""Cluster candidate claims into candidate skills.

Implements pipeline step 6 of MASTER_PROMPT.md deterministically: candidate
claims are grouped by the topics the shared keyword vocabulary finds in
their statements. A topic supported by at least --min-claims claims becomes
one candidate skill when no existing skill already covers the topic. Topics
an existing skill covers are only reported as review hints — attaching new
claims to an existing skill stays a human decision. Candidate skills keep
evidence_score 0.0 because scoring only counts reviewed claims.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from common import ROOT, TODAY, append_unique_records, load_records, score_relevance, slugify


def claim_topics(claim: dict[str, Any]) -> list[str]:
    _, topics = score_relevance({"title": str(claim.get("statement") or "")})
    return topics


def _candidate_skill(topic: str, claim_ids: list[str]) -> dict[str, Any]:
    return {
        "id": slugify(topic, "skill"),
        "name": topic.title(),
        "definition": (
            f"Candidate skill clustered from {len(claim_ids)} candidate claims about "
            f"{topic}. Definition requires human review."
        ),
        "age_range": "6-18",
        "status": "candidate",
        "evidence_score": 0.0,
        "trend": "emerging",
        "topics": [topic],
        "supporting_claim_ids": claim_ids,
        "contradicting_claim_ids": [],
        "framework_mapping_ids": [],
        "uncertainty": (
            "Clustered automatically from unreviewed candidate claims; the evidence "
            "score stays 0.0 until supporting claims are reviewed."
        ),
        "change_log": [
            {
                "date": TODAY,
                "change": "Created candidate skill from claim clustering",
                "reason": f"{len(claim_ids)} candidate claims matched topic '{topic}'.",
            }
        ],
        "created_at": TODAY,
    }


def cluster_candidate_skills(
    claims: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    min_claims: int = 2,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, list[str]]]]:
    """Group candidate claims by topic into skill proposals.

    Returns (proposals, hints): proposals are new candidate skill records
    for uncovered topics; hints are (topic, existing skill id, claim ids)
    tuples for topics an existing skill already covers.
    """
    covered: dict[str, str] = {}
    existing_ids: set[str] = set()
    for skill in skills:
        existing_ids.add(str(skill.get("id", "")))
        for topic in skill.get("topics", []):
            covered.setdefault(topic, str(skill.get("id", "")))
    groups: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        if claim.get("status") != "candidate":
            continue
        for topic in claim_topics(claim):
            groups[topic].append(str(claim.get("id", "")))
    proposals: list[dict[str, Any]] = []
    hints: list[tuple[str, str, list[str]]] = []
    for topic in sorted(groups):
        claim_ids = groups[topic]
        if len(claim_ids) < min_claims:
            continue
        proposal_id = slugify(topic, "skill")
        if topic in covered or proposal_id in existing_ids:
            hints.append((topic, covered.get(topic, proposal_id), claim_ids))
            continue
        proposals.append(_candidate_skill(topic, claim_ids))
    return proposals, hints


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster candidate claims into candidate skills.")
    parser.add_argument("--min-claims", type=int, default=2)
    parser.add_argument("--output", default="data/skills/candidates-clustered.json")
    args = parser.parse_args()

    proposals, hints = cluster_candidate_skills(
        load_records("claims"), load_records("skills"), args.min_claims
    )
    appended = append_unique_records(
        ROOT / args.output,
        proposals,
        lambda skill: [f"id:{skill.get('id')}"]
        + [f"topic:{topic}" for topic in skill.get("topics", [])],
    )
    print(f"Appended {len(appended)} candidate skill(s) to {args.output}")
    for topic, skill_id, claim_ids in hints:
        print(
            f"review hint: topic '{topic}' is covered by existing skill {skill_id}; "
            f"candidate claims {', '.join(claim_ids)} may support it"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
