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
from common import ROOT, TODAY, iter_json_files, load_json, normalize_title, write_json
from extract_claims import (
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    OUTCOME_PLACEHOLDER,
)
from score_evidence import write_skill_scores
from validate_data import _load_validators, validate_repository


AGE_RANGE_PLACEHOLDERS = {AGE_RANGE_PLACEHOLDER.casefold(), "todo", "tbd", ""}

# Auto-harvested relevance labels accumulate here, separate from the curated
# eval/relevance_labeled.json. Each human review decision is, in effect, a
# relevance label for the underlying source, so the training base for a future
# relevance classifier grows with review throughput instead of by hand.
HARVEST_PATH = ROOT / "eval" / "relevance_harvested.json"

HARVEST_README = (
    "Auto-harvested relevance labels written by scripts/promote_candidate.py on "
    "each review decision. DO NOT edit by hand. Mapping: a claim promoted to "
    "'reviewed' marks its source(s) 'relevant' (positives); a reviewer source "
    "reject ('reject-source') marks a source 'irrelevant' (negative). Rejected "
    "claims are NOT harvested -- a weak sentence does not make its source "
    "off-scope. SELECTION BIAS: only candidates that already passed the relevance "
    "filter reach human review, so this set under-represents the off-scope region "
    "the filter discards upstream and is missing most true negatives. It must NOT "
    "replace the curated eval/relevance_labeled.json; use it only as a supplement "
    "(eval_relevance.py --include-harvested), never on its own."
)


def _load_harvest() -> dict[str, Any]:
    """Return the harvested-labels document, or a fresh skeleton if absent."""
    if HARVEST_PATH.exists():
        payload = load_json(HARVEST_PATH)
        if isinstance(payload, dict) and isinstance(payload.get("examples"), list):
            return payload
    return {"_README": HARVEST_README, "examples": []}


def _harvest_example(
    source: dict[str, Any], relevant: bool, decision: str, **provenance: Any
) -> dict[str, Any]:
    """Build a labeled relevance example (title + abstract) with provenance."""
    example = {
        "title": str(source.get("title") or ""),
        "abstract": str(source.get("abstract") or ""),
        "relevant": relevant,
        "origin": "harvested",
        "decision": decision,
        "harvested_at": TODAY,
        "source_id": source.get("id"),
    }
    example.update(provenance)
    return example


def record_relevance_labels(examples: list[dict[str, Any]]) -> int:
    """Append harvested relevance labels, deduped by normalized title.

    The first recorded decision for a given (normalized) title wins, so the
    harvest stays deterministic and append-only across re-runs. Titleless
    examples are skipped. The file is only written when something new is added,
    so a no-op review never produces a noise diff. Returns the count appended.
    """
    if not examples:
        return 0
    harvest = _load_harvest()
    known = {normalize_title(str(item.get("title", ""))) for item in harvest["examples"]}
    added = 0
    for example in examples:
        key = normalize_title(str(example.get("title", "")))
        if not key or key in known:
            continue
        harvest["examples"].append(example)
        known.add(key)
        added += 1
    if added:
        harvest["_README"] = HARVEST_README
        write_json(HARVEST_PATH, harvest)
    return added


def _harvest_promoted_claim(claim: dict[str, Any]) -> int:
    """Harvest a positive label for every source backing a reviewed claim."""
    examples: list[dict[str, Any]] = []
    for source_id in claim.get("source_ids", []):
        located = find_record("sources", source_id)
        if located is None:
            continue
        _, _, source = located
        examples.append(
            _harvest_example(source, True, "promote_claim", claim_id=claim.get("id"))
        )
    return record_relevance_labels(examples)


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
    if args.evidence_type is not None:
        claim["evidence_type"] = args.evidence_type
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
    # The review decision is a relevance label for the claim's source(s).
    _harvest_promoted_claim(claim)
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
    claim.add_argument(
        "--evidence-type",
        choices=[
            "framework_synthesis",
            "policy_synthesis",
            "empirical_study",
            "systematic_review",
            "conceptual_review",
            "labor_market_forecast",
            "expert_consensus",
        ],
    )
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

    reject = sub.add_parser("reject", help="Reject a candidate claim (or deprecate a skill).")
    reject.add_argument("id")

    reject_src = sub.add_parser(
        "reject-source",
        help="Mark a source off-scope; harvests an 'irrelevant' relevance label.",
    )
    reject_src.add_argument("id")
    return parser


def reject_record(args: argparse.Namespace) -> list[str]:
    """Close out a candidate: claims become rejected, skills deprecated.

    Recording the decision keeps rejected candidates out of clustering and
    out of any later review pass, instead of leaving them lingering as
    candidates. Reasons live in the commit/PR, since the schemas carry no
    free-text review field on claims.
    """
    found = find_record("claims", args.id)
    kind = "claims"
    if found is None:
        found = find_record("skills", args.id)
        kind = "skills"
    if found is None:
        return [f"record {args.id} not found in data/claims/ or data/skills/"]
    _, records, record = found
    if kind == "claims":
        record["status"] = "rejected"
        record["reviewed_at"] = TODAY
    else:
        record["status"] = "deprecated"
        record["updated_at"] = TODAY
        record.setdefault("change_log", []).append(
            {"date": TODAY, "change": "Deprecated candidate skill", "reason": "Rejected during review."}
        )
    errors = _schema_errors(kind, record)
    if errors:
        return errors
    write_json(found[0], records)
    return []


def reject_source(args: argparse.Namespace) -> list[str]:
    """Mark a source off-scope and harvest an 'irrelevant' relevance label.

    This is the deliberate, documented path for negatives: a reviewer judges a
    source itself out of scope (not merely its auto-extracted claim). Rejected
    *claims* are never harvested as negatives -- a poorly extracted sentence does
    not make its source irrelevant. The source's status becomes 'rejected' so it
    drops out of later passes, mirroring reject_record for claims/skills.
    """
    found = find_record("sources", args.id)
    if found is None:
        return [f"source {args.id} not found in data/sources/"]
    _, records, source = found
    source["status"] = "rejected"
    source["reviewed_at"] = TODAY
    errors = _schema_errors("sources", source)
    if errors:
        return errors
    write_json(found[0], records)
    record_relevance_labels([_harvest_example(source, False, "reject_source")])
    return []


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    actions: dict[str, Callable[[argparse.Namespace], list[str]]] = {
        "claim": promote_claim,
        "skill": promote_skill,
        "reject": reject_record,
        "reject-source": reject_source,
    }
    verb = "Rejected" if args.kind in ("reject", "reject-source") else "Promoted"
    errors = actions[args.kind](args)
    if errors:
        print(f"Refusing to {verb.lower()} {args.id}:")
        for error in errors:
            print(f"- {error}")
        return 1

    # The change may have altered reviewed evidence, so stored scores may drift.
    changed = write_skill_scores()
    repo_errors = validate_repository()
    if repo_errors:
        print("Change written but repository validation failed:")
        for error in repo_errors:
            print(f"- {error}")
        return 1
    print(f"{verb} {args.id}. Recomputed {changed} skill score(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
