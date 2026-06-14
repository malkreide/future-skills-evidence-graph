"""Promote a reviewed candidate claim or skill into the evidence graph.

The research pipeline only ever produces candidates; turning one into a
reviewed claim or an active skill is a human decision. This tool makes that
decision safe and repeatable: it applies the reviewer's field values, refuses
to promote while machine-generated placeholders remain, enforces the project
invariant that active skills rest only on reviewed evidence, and recomputes
evidence scores afterwards. Nothing is written unless the resulting record
passes its schema and every gate, so a failed promotion leaves the data
untouched.

Examples:

    python scripts/promote_candidate.py claim claim-foo \\
        --context "K-12 classrooms" --age-range "6-18" \\
        --outcome "Learners can critique AI outputs" \\
        --evidence-strength moderate --supports skill-ai-literacy

    python scripts/promote_candidate.py skill skill-creativity \\
        --definition "Ability to generate and evaluate novel ideas." \\
        --name "Creative Problem Solving"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from cluster_claims import DEFINITION_PLACEHOLDER_SUFFIX
from common import TODAY, iter_json_files, load_json, write_json
from extract_claims import (
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    OUTCOME_PLACEHOLDER,
)
from score_evidence import write_skill_scores
from validate_data import _load_validators, validate_repository


AGE_RANGE_PLACEHOLDERS = {AGE_RANGE_PLACEHOLDER.casefold(), "todo", "tbd", ""}


def find_record(kind: str, record_id: str) -> tuple[Path, list[dict[str, Any]], dict[str, Any]] | None:
    """Locate a record by id across data/<kind>/*.json."""
    for path in iter_json_files(kind):
        records = load_json(path)
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("id") == record_id:
                return path, records, record
    return None


def _is_placeholder_context(value: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped.endswith(CONTEXT_PLACEHOLDER_SUFFIX) or stripped.upper().startswith("TODO")


def _is_placeholder_outcome(value: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped == OUTCOME_PLACEHOLDER or stripped.upper().startswith("TODO")


def _is_placeholder_age_range(value: str) -> bool:
    return value.strip().casefold() in AGE_RANGE_PLACEHOLDERS or value.strip().upper().startswith("TODO")


def _is_placeholder_definition(value: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped.endswith(DEFINITION_PLACEHOLDER_SUFFIX) or stripped.upper().startswith("TODO")


def claim_review_errors(
    claim: dict[str, Any], skill_ids: set[str], source_ids: set[str]
) -> list[str]:
    """Gate checks for a (already mutated) claim becoming reviewed."""
    errors: list[str] = []
    if _is_placeholder_context(str(claim.get("context", ""))):
        errors.append("context still holds a placeholder; pass --context")
    if _is_placeholder_age_range(str(claim.get("age_range", ""))):
        errors.append("age_range still holds a placeholder; pass --age-range")
    if _is_placeholder_outcome(str(claim.get("outcome", ""))):
        errors.append("outcome still holds a placeholder; pass --outcome")
    if not claim.get("supports_skill_ids") and not claim.get("contradicts_skill_ids"):
        errors.append("a reviewed claim must link at least one skill; pass --supports or --contradicts")
    for skill_id in claim.get("supports_skill_ids", []) + claim.get("contradicts_skill_ids", []):
        if skill_id not in skill_ids:
            errors.append(f"references missing skill {skill_id}")
    for source_id in claim.get("source_ids", []):
        if source_id not in source_ids:
            errors.append(f"references missing source {source_id}")
    return errors


def promote_claim(args: argparse.Namespace) -> list[str]:
    """Build the reviewed claim in memory and return validation errors."""
    found = find_record("claims", args.id)
    if found is None:
        return [f"claim {args.id} not found in data/claims/"]
    _, records, claim = found
    if claim.get("status") == "rejected":
        return [f"claim {args.id} is rejected; re-open it before promoting"]

    if args.statement is not None:
        claim["statement"] = args.statement
    if args.text_anchor is not None:
        claim["text_anchor"] = args.text_anchor
    if args.context is not None:
        claim["context"] = args.context
    if args.age_range is not None:
        claim["age_range"] = args.age_range
    if args.outcome is not None:
        claim["outcome"] = args.outcome
    if args.evidence_strength is not None:
        claim["evidence_strength"] = args.evidence_strength
    if args.supports is not None:
        claim["supports_skill_ids"] = args.supports
    if args.contradicts is not None:
        claim["contradicts_skill_ids"] = args.contradicts

    skill_ids = {skill["id"] for skill in _records_of("skills")}
    source_ids = {source["id"] for source in _records_of("sources")}
    errors = claim_review_errors(claim, skill_ids, source_ids)

    claim["status"] = "reviewed"
    claim["reviewed_at"] = TODAY

    errors.extend(_schema_errors("claims", claim))
    if errors:
        return errors
    write_json(found[0], records)
    return []


def skill_activation_errors(skill: dict[str, Any], claims_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Gate checks for a (already mutated) skill becoming active."""
    errors: list[str] = []
    if _is_placeholder_definition(str(skill.get("definition", ""))):
        errors.append("definition still holds a placeholder; pass --definition")
    supporting = skill.get("supporting_claim_ids", [])
    if not supporting:
        errors.append("an active skill needs at least one supporting claim; pass --add-claim")
    for claim_id in supporting + skill.get("contradicting_claim_ids", []):
        claim = claims_by_id.get(claim_id)
        if claim is None:
            errors.append(f"references missing claim {claim_id}")
        elif claim.get("status") != "reviewed":
            errors.append(f"claim {claim_id} is {claim.get('status')}; only reviewed claims may back an active skill")
    return errors


def promote_skill(args: argparse.Namespace) -> list[str]:
    """Build the active skill in memory and return validation errors."""
    found = find_record("skills", args.id)
    if found is None:
        return [f"skill {args.id} not found in data/skills/"]
    _, records, skill = found
    if skill.get("status") == "deprecated":
        return [f"skill {args.id} is deprecated; not promoting"]

    if args.name is not None:
        skill["name"] = args.name
    if args.short_label is not None:
        skill["short_label"] = args.short_label
    if args.definition is not None:
        skill["definition"] = args.definition
    if args.age_range is not None:
        skill["age_range"] = args.age_range
    if args.trend is not None:
        skill["trend"] = args.trend
    if args.topics is not None:
        skill["topics"] = args.topics
    if args.uncertainty is not None:
        skill["uncertainty"] = args.uncertainty
    for claim_id in args.add_claim or []:
        if claim_id not in skill.setdefault("supporting_claim_ids", []):
            skill["supporting_claim_ids"].append(claim_id)
    for claim_id in args.add_contradicting_claim or []:
        if claim_id not in skill.setdefault("contradicting_claim_ids", []):
            skill["contradicting_claim_ids"].append(claim_id)

    claims_by_id = {claim["id"]: claim for claim in _records_of("claims")}
    errors = skill_activation_errors(skill, claims_by_id)

    skill["status"] = "active"
    skill["updated_at"] = TODAY
    skill.setdefault("change_log", []).append(
        {
            "date": TODAY,
            "change": "Promoted candidate skill to active",
            "reason": "Human review confirmed definition and reviewed supporting evidence.",
        }
    )

    errors.extend(_schema_errors("skills", skill))
    if errors:
        return errors
    write_json(found[0], records)
    return []


def _records_of(kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in iter_json_files(kind):
        payload = load_json(path)
        if isinstance(payload, list):
            records.extend(record for record in payload if isinstance(record, dict))
    return records


_VALIDATORS = None


def _schema_errors(kind: str, record: dict[str, Any]) -> list[str]:
    global _VALIDATORS
    if _VALIDATORS is None:
        _VALIDATORS = _load_validators()
    validator = _VALIDATORS[kind]
    messages: list[str] = []
    for error in sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path) or "<record>"
        messages.append(f"schema {path}: {error.message}")
    return messages


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote a reviewed candidate claim or skill.")
    sub = parser.add_subparsers(dest="kind", required=True)

    claim = sub.add_parser("claim", help="Promote a candidate claim to reviewed.")
    claim.add_argument("id")
    claim.add_argument("--statement")
    claim.add_argument("--text-anchor")
    claim.add_argument("--context")
    claim.add_argument("--age-range")
    claim.add_argument("--outcome")
    claim.add_argument("--evidence-strength", choices=["low", "moderate", "strong"])
    claim.add_argument("--supports", nargs="*")
    claim.add_argument("--contradicts", nargs="*")

    skill = sub.add_parser("skill", help="Promote a candidate skill to active.")
    skill.add_argument("id")
    skill.add_argument("--name")
    skill.add_argument("--short-label")
    skill.add_argument("--definition")
    skill.add_argument("--age-range")
    skill.add_argument("--trend", choices=["emerging", "growing", "stable", "declining"])
    skill.add_argument("--topics", nargs="*")
    skill.add_argument("--uncertainty")
    skill.add_argument("--add-claim", nargs="*")
    skill.add_argument("--add-contradicting-claim", nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    promote: Callable[[argparse.Namespace], list[str]] = (
        promote_claim if args.kind == "claim" else promote_skill
    )
    errors = promote(args)
    if errors:
        print(f"Refusing to promote {args.kind} {args.id}:")
        for error in errors:
            print(f"- {error}")
        return 1

    # The promotion changed reviewed evidence, so stored skill scores may drift.
    changed = write_skill_scores()
    repo_errors = validate_repository()
    if repo_errors:
        print("Promotion written but repository validation failed:")
        for error in repo_errors:
            print(f"- {error}")
        return 1
    print(f"Promoted {args.kind} {args.id}. Recomputed {changed} skill score(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
