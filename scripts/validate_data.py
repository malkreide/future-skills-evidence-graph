from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Any

from common import load_records, source_identity, source_title_key


REQUIRED = {
    "sources": {
        "id",
        "title",
        "year",
        "source_type",
        "publisher",
        "url",
        "topics",
        "status",
        "created_at",
    },
    "claims": {
        "id",
        "statement",
        "source_ids",
        "text_anchor",
        "context",
        "age_range",
        "outcome",
        "evidence_type",
        "evidence_strength",
        "supports_skill_ids",
        "status",
        "created_at",
    },
    "skills": {
        "id",
        "name",
        "definition",
        "age_range",
        "status",
        "evidence_score",
        "trend",
        "supporting_claim_ids",
        "contradicting_claim_ids",
        "framework_mapping_ids",
        "change_log",
        "created_at",
    },
    "frameworks": {
        "id",
        "skill_id",
        "framework",
        "framework_url",
        "competency",
        "mapping_strength",
        "rationale",
        "created_at",
    },
}

ENUMS = {
    "sources.source_type": {
        "framework",
        "policy_report",
        "peer_reviewed_article",
        "systematic_review",
        "conceptual_review",
        "working_paper",
        "book",
        "dataset",
        "web_resource",
    },
    "sources.status": {"candidate", "reviewed", "rejected"},
    "claims.evidence_type": {
        "framework_synthesis",
        "policy_synthesis",
        "empirical_study",
        "systematic_review",
        "conceptual_review",
        "labor_market_forecast",
        "expert_consensus",
    },
    "claims.evidence_strength": {"low", "moderate", "strong"},
    "claims.status": {"candidate", "reviewed", "rejected"},
    "skills.status": {"candidate", "active", "deprecated"},
    "skills.trend": {"emerging", "growing", "stable", "declining"},
    "frameworks.mapping_strength": {"weak", "moderate", "strong"},
    "frameworks.coverage_label": {"gut abgedeckt", "teilweise", "Zukunftsluecke"},
}


def _require_fields(kind: str, records: list[dict[str, Any]], errors: list[str]) -> None:
    for record in records:
        record_id = record.get("id", "<missing id>")
        missing = sorted(REQUIRED[kind] - set(record))
        if missing:
            errors.append(f"{kind}:{record_id} missing required fields: {', '.join(missing)}")
        for field, allowed in ENUMS.items():
            enum_kind, enum_field = field.split(".", 1)
            if enum_kind == kind and enum_field in record and record[enum_field] not in allowed:
                errors.append(
                    f"{kind}:{record_id} has invalid {enum_field}: {record[enum_field]!r}"
                )


def _check_unique(kind: str, records: list[dict[str, Any]], errors: list[str]) -> None:
    ids = [str(record.get("id", "")) for record in records]
    for record_id, count in Counter(ids).items():
        if count > 1:
            errors.append(f"{kind}:{record_id} is duplicated {count} times")


def _check_sources(sources: list[dict[str, Any]], errors: list[str]) -> None:
    identity_groups: dict[str, list[str]] = defaultdict(list)
    title_groups: dict[str, list[str]] = defaultdict(list)
    for source in sources:
        source_id = str(source.get("id", "<missing id>"))
        identity_groups[source_identity(source)].append(source_id)
        title_groups[source_title_key(source)].append(source_id)
        year = source.get("year")
        if not isinstance(year, int) or year < 1900 or year > 2100:
            errors.append(f"sources:{source_id} has invalid year: {year!r}")
        topics = source.get("topics")
        if not isinstance(topics, list) or not topics:
            errors.append(f"sources:{source_id} must have at least one topic")
    for key, ids in identity_groups.items():
        if key and len(ids) > 1:
            errors.append(f"sources duplicate identity {key}: {', '.join(ids)}")
    for key, ids in title_groups.items():
        if key and len(ids) > 1:
            errors.append(f"sources duplicate title/year {key}: {', '.join(ids)}")


def validate_repository() -> list[str]:
    errors: list[str] = []
    sources = load_records("sources")
    claims = load_records("claims")
    skills = load_records("skills")
    mappings = load_records("frameworks")

    collections = {
        "sources": sources,
        "claims": claims,
        "skills": skills,
        "frameworks": mappings,
    }
    for kind, records in collections.items():
        _require_fields(kind, records, errors)
        _check_unique(kind, records, errors)

    _check_sources(sources, errors)

    source_ids = {source["id"] for source in sources}
    claim_ids = {claim["id"] for claim in claims}
    skill_ids = {skill["id"] for skill in skills}
    mapping_ids = {mapping["id"] for mapping in mappings}

    for claim in claims:
        claim_id = claim.get("id", "<missing id>")
        for source_id in claim.get("source_ids", []):
            if source_id not in source_ids:
                errors.append(f"claims:{claim_id} references missing source {source_id}")
        for skill_id in claim.get("supports_skill_ids", []):
            if skill_id not in skill_ids:
                errors.append(f"claims:{claim_id} supports missing skill {skill_id}")
        for skill_id in claim.get("contradicts_skill_ids", []):
            if skill_id not in skill_ids:
                errors.append(f"claims:{claim_id} contradicts missing skill {skill_id}")

    for skill in skills:
        skill_id = skill.get("id", "<missing id>")
        score = skill.get("evidence_score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            errors.append(f"skills:{skill_id} evidence_score must be between 0 and 1")
        if skill.get("status") == "active" and not skill.get("supporting_claim_ids"):
            errors.append(f"skills:{skill_id} is active without supporting claims")
        for claim_id in skill.get("supporting_claim_ids", []):
            if claim_id not in claim_ids:
                errors.append(f"skills:{skill_id} references missing supporting claim {claim_id}")
        for claim_id in skill.get("contradicting_claim_ids", []):
            if claim_id not in claim_ids:
                errors.append(f"skills:{skill_id} references missing contradicting claim {claim_id}")
        for mapping_id in skill.get("framework_mapping_ids", []):
            if mapping_id not in mapping_ids:
                errors.append(f"skills:{skill_id} references missing mapping {mapping_id}")

    for mapping in mappings:
        mapping_id = mapping.get("id", "<missing id>")
        skill_id = mapping.get("skill_id")
        if skill_id not in skill_ids:
            errors.append(f"frameworks:{mapping_id} references missing skill {skill_id}")
        if mapping.get("framework_group") == "Lehrplan 21":
            coverage_score = mapping.get("coverage_score")
            if not isinstance(coverage_score, (int, float)) or not 0 <= coverage_score <= 3:
                errors.append(f"frameworks:{mapping_id} coverage_score must be between 0 and 3")
            cycles = mapping.get("cycles")
            if not isinstance(cycles, list) or not cycles:
                errors.append(f"frameworks:{mapping_id} must define at least one Lehrplan 21 cycle")
            if not mapping.get("curriculum_area"):
                errors.append(f"frameworks:{mapping_id} must define curriculum_area")
            if not mapping.get("evidence_path"):
                errors.append(f"frameworks:{mapping_id} must define evidence_path")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate evidence graph data.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args()

    errors = validate_repository()
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print("Validation passed.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
