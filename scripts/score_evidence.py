from __future__ import annotations

from common import load_records


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


def main() -> int:
    sources = {source["id"]: source for source in load_records("sources")}
    for claim in load_records("claims"):
        source_scores = [
            SOURCE_WEIGHTS.get(sources[source_id]["source_type"], 0.25)
            for source_id in claim.get("source_ids", [])
            if source_id in sources
        ]
        source_component = sum(source_scores) / len(source_scores) if source_scores else 0
        claim_component = CLAIM_WEIGHTS.get(claim.get("evidence_strength"), 0)
        score = round((source_component * 0.6) + (claim_component * 0.4), 3)
        print(f"{claim['id']},{score},{claim.get('evidence_strength')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
