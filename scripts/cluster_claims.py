"""Cluster candidate claims into candidate skills.

Implements pipeline step 6 of MASTER_PROMPT.md deterministically: candidate
claims are grouped by the topics the shared keyword vocabulary finds in
their statements. A topic supported by at least --min-claims claims becomes
one candidate skill when no existing skill already covers the topic. Topics
an existing skill covers are only reported as review hints — attaching new
claims to an existing skill stays a human decision. Candidate skills keep
evidence_score 0.0 because scoring only counts reviewed claims.

The vocabulary method above is the default and the only one wired in by
default. An OPTIONAL embedding method (CLUSTER_METHOD=embedding) is available
as an opt-in alternative: it embeds the claim statements via ai_provider.embed
and groups them by agglomerative (single-linkage) clustering at a fixed cosine
threshold, proposing one candidate skill per cluster. It changes nothing by
default — with CLUSTER_METHOD unset the behaviour is exactly the vocabulary
method, and with no EMBEDDING_PROVIDER configured the embedding method warns and
falls back to the vocabulary method. Either way the proposals carry their
provenance in the change_log / uncertainty and stay status=candidate,
evidence_score 0.0, with a placeholder definition the promotion gate refuses
until a human reviews it. Existing skills are surfaced only as hints, never
attached automatically.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from typing import Any, Callable

from common import (
    ROOT,
    TODAY,
    append_unique_records,
    cosine_similarity,
    load_records,
    score_relevance,
    slugify,
    vector_centroid,
)


# Suffix of the auto-generated definition a human reviewer must replace before
# a clustered skill can be promoted to active. promote_candidate.py imports
# this so the review gate stays in sync with the clustering output.
DEFINITION_PLACEHOLDER_SUFFIX = "Definition requires human review."

# Env flag selecting the clustering method. Default is the keyword vocabulary,
# which is also the only method active by default.
CLUSTER_METHOD_ENV = "CLUSTER_METHOD"

# Fixed cosine similarity at/above which two claim embeddings are linked into the
# same agglomerative (single-linkage) cluster. Keeping the threshold fixed makes
# the embedding output reproducible for the same input.
EMBEDDING_CLUSTER_THRESHOLD = 0.5


def cluster_method() -> str:
    """Active clustering method: ``vocabulary`` (default) or ``embedding``."""
    return (os.getenv(CLUSTER_METHOD_ENV) or "vocabulary").strip().lower()


def claim_topics(claim: dict[str, Any]) -> list[str]:
    _, topics = score_relevance({"title": str(claim.get("statement") or "")})
    return topics


def _candidate_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidate claims only — clustering never touches reviewed/rejected ones."""
    return [claim for claim in claims if claim.get("status") == "candidate"]


def _candidate_skill(topic: str, claim_ids: list[str]) -> dict[str, Any]:
    return {
        "id": slugify(topic, "skill"),
        "name": topic.title(),
        "definition": (
            f"Candidate skill clustered from {len(claim_ids)} candidate claims about "
            f"{topic}. {DEFINITION_PLACEHOLDER_SUFFIX}"
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


# --- Optional embedding clustering -----------------------------------------


def _skill_text(skill: dict[str, Any]) -> str:
    """Name + definition: the text an existing skill is embedded from for hints."""
    return f"{skill.get('name') or ''} {skill.get('definition') or ''}"


def _embedding_candidate_skill(
    claim_ids: list[str], *, threshold: float, provider: str
) -> dict[str, Any]:
    """A candidate skill proposed from one embedding cluster.

    The id/name are derived deterministically from the cluster's representative
    (smallest) claim id; the provenance (method, embedding provider, threshold)
    lives in the change_log and uncertainty because the skill schema admits no
    extra fields. The definition keeps the placeholder suffix so the promotion
    gate refuses it until a human writes a real definition.
    """
    representative = claim_ids[0]
    return {
        "id": slugify(representative, "skill"),
        "name": f"Candidate skill cluster {representative}",
        "definition": (
            f"Candidate skill clustered from {len(claim_ids)} candidate claims by "
            f"embedding similarity (cosine >= {threshold}). {DEFINITION_PLACEHOLDER_SUFFIX}"
        ),
        "age_range": "6-18",
        "status": "candidate",
        "evidence_score": 0.0,
        "trend": "emerging",
        "topics": [],
        "supporting_claim_ids": claim_ids,
        "contradicting_claim_ids": [],
        "framework_mapping_ids": [],
        "uncertainty": (
            "Clustered automatically from unreviewed candidate claims by embedding "
            "similarity; the evidence score stays 0.0 until supporting claims are "
            "reviewed."
        ),
        "change_log": [
            {
                "date": TODAY,
                "change": "Created candidate skill from embedding claim clustering",
                "reason": (
                    f"{len(claim_ids)} candidate claims formed an embedding cluster "
                    f"(EMBEDDING_PROVIDER={provider}, cosine threshold {threshold})."
                ),
            }
        ],
        "created_at": TODAY,
    }


def _agglomerative_clusters(
    ids: list[str], vectors: list[list[float]], threshold: float
) -> list[list[str]]:
    """Single-linkage agglomerative clustering at a fixed cosine threshold.

    Two claims are linked when their embeddings are at least *threshold* cosine
    apart; the clusters are the connected components of that threshold graph
    (single linkage at a fixed cut). Returns each cluster as a list sorted by id,
    with the clusters themselves sorted by their representative (smallest) id, so
    the result is deterministic and reproducible for the same input regardless of
    the input ordering.
    """
    n = len(ids)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            if cosine_similarity(vectors[i], vectors[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[str]] = defaultdict(list)
    for index in range(n):
        groups[find(index)].append(ids[index])
    clusters = [sorted(members) for members in groups.values()]
    clusters.sort(key=lambda members: members[0])
    return clusters


def cluster_candidate_skills_embedding(
    claims: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    min_claims: int = 2,
    threshold: float = EMBEDDING_CLUSTER_THRESHOLD,
    embedder: Callable[[list[str]], list[list[float]] | None] | None = None,
    provider: str | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, list[str]]]] | None:
    """Group candidate claims into skill proposals by embedding similarity.

    Embeds the candidate claim statements via *embedder* (ai_provider.embed by
    default), clusters them agglomeratively at a fixed cosine threshold and
    proposes one candidate skill per cluster of at least *min_claims* claims.
    Existing skills are not used to suppress proposals — they are surfaced only
    as hints: for each proposed cluster the nearest existing skill (by cosine to
    the cluster centroid, at or above the threshold) is reported.

    Returns (proposals, hints), or None when no embedding provider is configured
    (the embedder returns nothing) so the caller can fall back to the vocabulary
    method.
    """
    if embedder is None:
        from ai_provider import embed as embedder  # lazy: keep the stdlib import path clean
    if provider is None:
        from ai_provider import embedding_provider

        provider = embedding_provider()

    candidates = sorted(_candidate_claims(claims), key=lambda claim: str(claim.get("id", "")))
    ids = [str(claim.get("id", "")) for claim in candidates]
    if not ids:
        return [], []

    vectors = embedder([str(claim.get("statement") or "") for claim in candidates])
    if not vectors:
        return None  # no embedding provider; caller falls back to the vocabulary method
    vector_by_id = dict(zip(ids, vectors))

    clusters = [
        cluster
        for cluster in _agglomerative_clusters(ids, vectors, threshold)
        if len(cluster) >= min_claims
    ]
    proposals = [
        _embedding_candidate_skill(cluster, threshold=threshold, provider=provider)
        for cluster in clusters
    ]

    hints: list[tuple[str, str, list[str]]] = []
    if clusters and skills:
        skill_ids = [str(skill.get("id", "")) for skill in skills]
        skill_vectors = embedder([_skill_text(skill) for skill in skills])
        if skill_vectors:
            for cluster in clusters:
                centroid = vector_centroid([vector_by_id[claim_id] for claim_id in cluster])
                matches = [
                    (cosine_similarity(centroid, skill_vector), skill_id)
                    for skill_id, skill_vector in zip(skill_ids, skill_vectors)
                ]
                matches = [match for match in matches if match[0] >= threshold]
                if matches:
                    # Most similar existing skill, smallest id breaking ties.
                    matches.sort(key=lambda match: (-match[0], match[1]))
                    hints.append((cluster[0], matches[0][1], cluster))
    return proposals, hints


def cluster_skills(
    claims: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    min_claims: int = 2,
    method: str | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, list[str]]]]:
    """Dispatch to the selected clustering method, defaulting to the vocabulary.

    The vocabulary method is the default and the fallback. The embedding method
    is used only when *method* (or CLUSTER_METHOD) is ``embedding`` AND an
    embedding provider is configured; otherwise this warns and degrades to the
    vocabulary method without raising into the pipeline.
    """
    if method is None:
        method = cluster_method()
    if method == "embedding":
        result = cluster_candidate_skills_embedding(claims, skills, min_claims)
        if result is not None:
            return result
        print(
            "Warning: CLUSTER_METHOD=embedding but no embedding provider is configured "
            "(set EMBEDDING_PROVIDER); falling back to the vocabulary method.",
        )
    elif method != "vocabulary":
        print(
            f"Warning: unknown CLUSTER_METHOD {method!r}; expected vocabulary|embedding. "
            "Falling back to the vocabulary method.",
        )
    return cluster_candidate_skills(claims, skills, min_claims)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster candidate claims into candidate skills.")
    parser.add_argument("--min-claims", type=int, default=2)
    parser.add_argument("--output", default="data/skills/candidates-clustered.json")
    args = parser.parse_args()

    proposals, hints = cluster_skills(
        load_records("claims"), load_records("skills"), args.min_claims
    )
    appended = append_unique_records(
        ROOT / args.output,
        proposals,
        lambda skill: [f"id:{skill.get('id')}"]
        + [f"topic:{topic}" for topic in skill.get("topics", [])],
    )
    print(f"Appended {len(appended)} candidate skill(s) to {args.output}")
    for key, skill_id, claim_ids in hints:
        print(
            f"review hint: '{key}' is covered by existing skill {skill_id}; "
            f"candidate claims {', '.join(claim_ids)} may support it"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
