"""Put an evidence_score next to the group it should be read against.

A single global number over all skills hides two different things.

The first is the peer group. Learner evidence and educator evidence come
from different literatures (K-12 intervention studies vs. teacher
professional-development research), so a learner score and an educator
score are not directly comparable. kurate.org ranks papers inside their
arXiv category for the same reason: "a paper's significance is easier to
interpret when compared with other papers from the same category."

The second, and on this catalogue the larger one, is breadth versus
depth. The composite multiplies the mean claim quality by a breadth
factor, and over the 16 active skills the claim COUNT drives the ranking
more than the claim QUALITY does (r = +0.66 vs +0.53), while count says
essentially nothing about quality (r = -0.11). A skill can therefore rank
low because the catalogue is thin on it, not because its evidence is
weak. score_evidence.score_breakdown exposes the parts; this module adds
the peer group around them.

Nothing here changes a score. It is computed at build time and shipped in
index.json rather than stored in data/skills/*.json, so there is no
second derived value that can drift from its formula.
"""

from __future__ import annotations

import statistics
from typing import Any

from score_evidence import score_breakdown

# Below this a rank is theatre: "rank 1 of 2" reads like a finding and is
# not one. The same restraint eval_agreement.py applies to an underpowered
# baseline -- report the group, withhold the ranking.
MIN_PEER_GROUP = 5

# The catalogue's own split of which literature a skill's evidence comes
# from. It is a real field on the record, not a bucket invented here.
PEER_GROUP_LABELS = {"learner": "Lernende", "educator": "Lehrende"}


def peer_group(skill: dict[str, Any]) -> str:
    return skill.get("audience") or "learner"


def score_contexts(
    skills: list[dict[str, Any]], claim_scores: dict[str, float]
) -> dict[str, dict[str, Any]]:
    """Per skill: the score's parts, plus where it sits in its peer group.

    Only active skills form a peer group. Candidates carry placeholder
    scores of 0.0 by construction (cluster_claims.py), so including them
    would drag every median toward zero and make the comparison read far
    better than it is.
    """
    active = [skill for skill in skills if skill.get("status") == "active"]
    groups: dict[str, list[float]] = {}
    for skill in active:
        groups.setdefault(peer_group(skill), []).append(float(skill.get("evidence_score") or 0.0))

    contexts = {}
    for skill in skills:
        breakdown = score_breakdown(skill, claim_scores)
        group_key = peer_group(skill)
        peers = sorted(groups.get(group_key, []), reverse=True)
        context: dict[str, Any] = {
            **breakdown,
            "peer_group": group_key,
            "peer_group_label": PEER_GROUP_LABELS.get(group_key, group_key),
            "peer_group_size": len(peers),
            "peer_group_median": round(statistics.median(peers), 3) if peers else None,
            "rank": None,
            "rank_note": None,
        }
        if skill.get("status") != "active":
            context["rank_note"] = "Nur aktive Skills werden verglichen."
        elif len(peers) < MIN_PEER_GROUP:
            context["rank_note"] = (
                f"Für eine Rangangabe zu klein — dafür braucht es mindestens "
                f"{MIN_PEER_GROUP} Skills."
            )
        else:
            score = float(skill.get("evidence_score") or 0.0)
            # Rank by how many peers score strictly higher, so tied scores
            # share a rank instead of being ordered by file position.
            context["rank"] = sum(1 for peer in peers if peer > score) + 1
        contexts[skill["id"]] = context
    return contexts


def quality_vs_breadth_note(context: dict[str, Any]) -> str | None:
    """Name the divergence when the composite understates claim quality.

    Only fires when the two really pull apart: strong evidence per claim
    held down by a short evidence path. Saying it on every skill would
    make it wallpaper.
    """
    quality = context.get("claim_quality")
    count = context.get("supporting_claims") or 0
    if quality is None or count == 0:
        return None
    if quality >= 0.75 and count < 4:
        return (
            f"Hohe Evidenzqualität je Aussage ({quality:.2f}), aber erst {count} "
            "geprüfte Belege. Der Gesamtscore ist deshalb niedriger — das ist eine "
            "dünne Beleglage, keine schwache Evidenz."
        )
    if quality <= 0.70 and count >= 6:
        # Under method 1.0.0 this case could be described as the score resting
        # on quantity: the breadth factor spanned 0.75 to 1.00, so a long
        # evidence path lifted a weak skill noticeably. Since 1.1.0 the factor
        # only spans 0.875 to 1.00, and at six claims it is exactly 1.00 -- the
        # score then simply *is* the claim quality, undamped. Saying it rests on
        # quantity would now overstate an effect the formula no longer has.
        return (
            f"Breite Beleglage ({count} Aussagen) bei eher niedriger Evidenzqualität "
            f"je Aussage ({quality:.2f}). Der Gesamtscore wird hier nicht durch eine "
            "dünne Beleglage gedämpft — er spiegelt die Stärke der Aussagen selbst."
        )
    return None
