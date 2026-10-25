"""Count how far each record has travelled along the human review path.

The catalogue holds far more than it vouches for. The weekly harvest adds
sources and claims as candidates by the hundred; only what a person has
reviewed and accepted may feed a score or a skill. A bare "2637 claims" on
the dashboard hides that difference, so this module splits each record
type into the stages the review path actually has:

- captured:   every record, whatever its status
- open:       still a candidate, no human decision yet
- decided:    a human looked at it (accepted or rejected)
- accepted:   reviewed and kept
- rejected:   reviewed and dropped
- in_catalog: accepted AND reaching an active skill -- for claims through
              the skill's supporting or contradicting ids, for sources
              through such a claim

"Rejected" and "open" stay separate on purpose. A rejection is the filter
doing its job; an open candidate is review capacity not yet spent. Folding
both into "not accepted" would make a backlog look like rigour, or rigour
like a backlog.

Computed at build time and shipped in index.json, like score_context:
nothing here is stored in data/, so there is no second value that can drift
from the records it counts.
"""

from __future__ import annotations

from typing import Any

# The record statuses the schemas allow (schemas/source.schema.json and
# schemas/claim.schema.json). A status outside this set cannot be placed in a
# stage, and silently dropping it would break captured == open + decided.
RECORD_STATUSES = ("candidate", "reviewed", "rejected")
SKILL_STATUSES = ("active", "candidate", "deprecated")


def _status_counts(records: list[dict[str, Any]], allowed: tuple[str, ...], kind: str) -> dict[str, int]:
    counts = dict.fromkeys(allowed, 0)
    for record in records:
        status = record.get("status")
        if status not in counts:
            raise ValueError(f"{kind} {record.get('id')!r} has unknown status {status!r}")
        counts[status] += 1
    return counts


def _stages(records: list[dict[str, Any]], reached: set[str], kind: str) -> dict[str, int]:
    counts = _status_counts(records, RECORD_STATUSES, kind)
    accepted_ids = {record["id"] for record in records if record["status"] == "reviewed"}
    return {
        "captured": len(records),
        "open": counts["candidate"],
        "decided": counts["reviewed"] + counts["rejected"],
        "accepted": counts["reviewed"],
        "rejected": counts["rejected"],
        "in_catalog": len(accepted_ids & reached),
    }


def review_funnel(
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    skills: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Stage counts per record type, plus the skill statuses at the end."""
    skill_counts = _status_counts(skills, SKILL_STATUSES, "skill")
    claims_in_skills: set[str] = set()
    for skill in skills:
        if skill["status"] != "active":
            continue
        claims_in_skills.update(skill.get("supporting_claim_ids") or [])
        claims_in_skills.update(skill.get("contradicting_claim_ids") or [])

    claim_stages = _stages(claims, claims_in_skills, "claim")

    # A source reaches the catalogue only through a claim that does: an
    # accepted claim inside an active skill. A reviewed source whose claims
    # were all rejected is accepted, but carries nothing.
    sources_in_skills: set[str] = set()
    for claim in claims:
        if claim["status"] == "reviewed" and claim["id"] in claims_in_skills:
            sources_in_skills.update(claim.get("source_ids") or [])

    return {
        "sources": _stages(sources, sources_in_skills, "source"),
        "claims": claim_stages,
        "skills": skill_counts,
    }
