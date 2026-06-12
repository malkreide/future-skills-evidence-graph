from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from common import (
    ROOT,
    load_json,
    load_records,
    lp21_coverage_label,
    source_identity,
    source_title_key,
)
from score_evidence import reviewed_claim_scores, skill_score


SCHEMA_FILES = {
    "sources": "source.schema.json",
    "claims": "claim.schema.json",
    "skills": "skill.schema.json",
    "frameworks": "framework_mapping.schema.json",
}


def _load_validators() -> dict[str, Draft202012Validator]:
    validators: dict[str, Draft202012Validator] = {}
    for kind, filename in SCHEMA_FILES.items():
        schema = load_json(ROOT / "schemas" / filename)
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema, format_checker=FormatChecker())
    return validators


def _check_schema(
    kind: str,
    validator: Draft202012Validator,
    records: list[dict[str, Any]],
    errors: list[str],
) -> None:
    for record in records:
        record_id = record.get("id", "<missing id>")
        for error in sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path)):
            path = ".".join(str(part) for part in error.absolute_path) or "<record>"
            errors.append(f"{kind}:{record_id} {path}: {error.message}")


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
    for key, ids in identity_groups.items():
        if key and len(ids) > 1:
            errors.append(f"sources duplicate identity {key}: {', '.join(ids)}")
    for key, ids in title_groups.items():
        if key and len(ids) > 1:
            errors.append(f"sources duplicate title/year {key}: {', '.join(ids)}")


def validate_repository() -> list[str]:
    errors: list[str] = []
    validators = _load_validators()
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
        _check_schema(kind, validators[kind], records, errors)
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

    sources_by_id = {source["id"]: source for source in sources}
    claim_scores = reviewed_claim_scores(claims, sources_by_id)
    for skill in skills:
        skill_id = skill.get("id", "<missing id>")
        expected_score = skill_score(skill, claim_scores)
        if skill.get("evidence_score") != expected_score:
            errors.append(
                f"skills:{skill_id} evidence_score {skill.get('evidence_score')!r} does not "
                f"match computed {expected_score} (run scripts/score_evidence.py --write)"
            )
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
            score = mapping.get("coverage_score")
            label = mapping.get("coverage_label")
            if isinstance(score, (int, float)) and label != lp21_coverage_label(score):
                errors.append(
                    f"frameworks:{mapping_id} coverage_label {label!r} does not match "
                    f"coverage_score {score} (expected {lp21_coverage_label(score)!r})"
                )

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
