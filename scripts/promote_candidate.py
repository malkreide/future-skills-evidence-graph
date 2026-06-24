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

# The pre-fill prompt (Anhang A) proposes evidence_strength as low|moderate|high,
# but the claim schema's vocabulary is low|moderate|strong. Map on acceptance so
# an adopted suggestion lands as a valid start value; unknown values pass through
# untouched so the schema gate still catches anything out of range.
STRENGTH_SUGGESTION_TO_CLAIM = {
    "low": "low",
    "moderate": "moderate",
    "high": "strong",
    "strong": "strong",
}

# Review fields a suggestion can pre-fill, mapped to the claim key they populate.
SUGGESTION_REVIEW_FIELDS = ("context", "age_range", "outcome", "evidence_strength")

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


def remove_harvested_label(source: dict[str, Any]) -> int:
    """Drop any harvested relevance label for *source*, keyed by normalized title.

    Used when re-opening a rejected source: its rejection harvested an
    'irrelevant' label, which becomes stale once the source is back in scope.
    Removing it lets a later promote-source re-harvest the corrected (positive)
    label instead of being blocked by the append-only title dedup. The file is
    only rewritten when something is removed, so a no-op leaves no diff. Returns
    the count removed.
    """
    if not HARVEST_PATH.exists():
        return 0
    harvest = _load_harvest()
    key = normalize_title(str(source.get("title", "")))
    if not key:
        return 0
    kept = [e for e in harvest["examples"] if normalize_title(str(e.get("title", ""))) != key]
    removed = len(harvest["examples"]) - len(kept)
    if removed:
        harvest["examples"] = kept
        harvest["_README"] = HARVEST_README
        write_json(HARVEST_PATH, harvest)
    return removed


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


def claim_suggestions(claim: dict[str, Any]) -> dict[str, Any] | None:
    """Return the LLM-proposed review fields stored under claim["assist"], or None.

    The suggestion is purely advisory: it never reaches the real fields unless a
    reviewer opts in via --accept-suggestions, and it is never consulted by the
    promotion gate (claim_review_errors), so its presence cannot loosen review.
    """
    assist = claim.get("assist")
    if not isinstance(assist, dict):
        return None
    suggestions = assist.get("suggestions")
    if isinstance(suggestions, list) and suggestions and isinstance(suggestions[0], dict):
        return suggestions[0]
    return None


def format_claim_suggestions(claim: dict[str, Any]) -> list[str]:
    """Render the AI suggestion (if any) as human-readable lines for display."""
    suggestion = claim_suggestions(claim)
    if suggestion is None:
        return []
    assist = claim.get("assist", {})
    provenance = assist.get("provenance", {}) if isinstance(assist, dict) else {}
    stamp = ", ".join(
        f"{key} {provenance[key]}" for key in ("model", "prompt_version") if provenance.get(key)
    )
    lines = [f"AI suggestions for {claim.get('id')}" + (f" ({stamp})" if stamp else "") + ":"]
    for field in SUGGESTION_REVIEW_FIELDS:
        if field in suggestion:
            lines.append(f"  {field}: {suggestion[field]!r}")
    lines.append("  (advisory only; pass --accept-suggestions to adopt as starting values)")
    return lines


def apply_claim_suggestions(claim: dict[str, Any]) -> dict[str, Any]:
    """Adopt non-null AI suggestions into the claim's real fields as start values.

    Only fields the suggestion actually proposes (non-null) are written, and
    evidence_strength is mapped into the claim vocabulary. This fills nothing the
    model left as null, so a placeholder with no usable suggestion stays a
    placeholder and the promotion gate still refuses it. Explicit reviewer args
    are applied AFTER this and therefore override the adopted values. Returns the
    mapping of fields actually adopted (for display).
    """
    suggestion = claim_suggestions(claim)
    if suggestion is None:
        return {}
    adopted: dict[str, Any] = {}
    for field in ("context", "age_range", "outcome"):
        value = suggestion.get(field)
        if isinstance(value, str) and value.strip():
            claim[field] = value
            adopted[field] = value
    strength = suggestion.get("evidence_strength")
    if isinstance(strength, str) and strength.strip():
        mapped = STRENGTH_SUGGESTION_TO_CLAIM.get(strength.strip().casefold(), strength)
        claim["evidence_strength"] = mapped
        adopted["evidence_strength"] = mapped
    return adopted


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

    # Surface any AI suggestion so the reviewer can see it regardless of whether
    # they adopt it. Adoption is opt-in and never weakens the gate below.
    for line in format_claim_suggestions(claim):
        print(line)
    if getattr(args, "accept_suggestions", False):
        adopted = apply_claim_suggestions(claim)
        if adopted:
            print(f"Adopted AI suggestion(s) as starting values: {', '.join(sorted(adopted))}")

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
    claim.add_argument(
        "--accept-suggestions",
        action="store_true",
        help=(
            "Adopt any AI claim.assist suggestions as starting values for the "
            "review fields. Explicit flags still override them, and the review "
            "gate is unchanged: fields the model left null stay placeholders and "
            "block promotion."
        ),
    )

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

    reopen = sub.add_parser(
        "reopen",
        help="Re-open a rejected claim/source (or deprecated skill) back to candidate.",
    )
    reopen.add_argument("id")

    reject_src = sub.add_parser(
        "reject-source",
        help="Mark a source off-scope; harvests an 'irrelevant' relevance label.",
    )
    reject_src.add_argument("id")

    promote_src = sub.add_parser(
        "promote-source",
        help="Mark a source reviewed (in scope); harvests a 'relevant' label.",
    )
    promote_src.add_argument("id")

    attach = sub.add_parser(
        "attach-claim",
        help="Attach a reviewed claim to a skill's evidence and recompute scores.",
    )
    attach.add_argument("id", help="skill id")
    attach.add_argument("--claim", required=True, help="reviewed claim id")
    attach.add_argument(
        "--contradicting",
        action="store_true",
        help="Attach as contradicting evidence instead of supporting.",
    )
    return parser


def promote_source(args: argparse.Namespace) -> list[str]:
    """Mark a source reviewed (human-verified in scope); harvest a positive label.

    The counterpart to reject_source and the prerequisite for attaching a claim
    to an active skill, whose evidence path requires reviewed sources. A reviewed
    source is a confirmed in-scope relevance example, so it is harvested as a
    positive label, mirroring reject_source's negative.
    """
    found = find_record("sources", args.id)
    if found is None:
        return [f"source {args.id} not found in data/sources/"]
    _, records, source = found
    source["status"] = "reviewed"
    source["reviewed_at"] = TODAY
    errors = _schema_errors("sources", source)
    if errors:
        return errors
    write_json(found[0], records)
    record_relevance_labels([_harvest_example(source, True, "promote_source")])
    return []


def attach_claim(args: argparse.Namespace) -> list[str]:
    """Attach a reviewed claim to an existing skill's evidence list.

    The operating path for folding reviewed claims into skills: the importers
    only ever produce candidates and promote_skill handles the candidate->active
    transition, but reviewed claims also need to be folded into already-active
    skills. Only reviewed claims may be attached (the active-skill evidence
    invariant); the skill score is recomputed afterwards by main().
    """
    found = find_record("skills", args.id)
    if found is None:
        return [f"skill {args.id} not found in data/skills/"]
    _, records, skill = found
    claim_found = find_record("claims", args.claim)
    if claim_found is None:
        return [f"claim {args.claim} not found in data/claims/"]
    if claim_found[2].get("status") != "reviewed":
        return [f"claim {args.claim} is {claim_found[2].get('status')}; only reviewed claims may back a skill"]
    # An active skill's evidence path requires reviewed sources, so a claim
    # cannot be folded in until its sources are reviewed (promote-source first).
    sources = {s["id"]: s for s in _records_of("sources")}
    unreviewed = [
        sid for sid in claim_found[2].get("source_ids", [])
        if sources.get(sid, {}).get("status") != "reviewed"
    ]
    if unreviewed:
        return [
            f"claim {args.claim} has non-reviewed source(s) {', '.join(unreviewed)}; "
            "run promote-source on them first"
        ]

    role = "contradicting" if args.contradicting else "supporting"
    field = f"{role}_claim_ids"
    ids = skill.setdefault(field, [])
    if args.claim in ids:
        return [f"claim {args.claim} is already {role} evidence for {args.id}"]
    ids.append(args.claim)
    skill["updated_at"] = TODAY
    skill.setdefault("change_log", []).append(
        {
            "date": TODAY,
            "change": f"Attached reviewed claim {args.claim} as {role} evidence",
            "reason": "Folded reviewed candidate evidence into the skill during operations.",
        }
    )
    errors = _schema_errors("skills", skill)
    if errors:
        return errors
    write_json(found[0], records)
    return []


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


def reopen_record(args: argparse.Namespace) -> list[str]:
    """Re-open a rejected claim/source (or deprecated skill) back to candidate.

    The inverse of reject_record / reject_source: a record rejected under an
    earlier scope can become reviewable again when the scope itself changes -- in
    particular when the educator relevance lane brings teacher/educator studies
    that the learner gate once dropped back into scope. Re-opening ONLY resets the
    status to 'candidate' (skills keep their change log); every promote_* gate
    still applies before anything becomes reviewed or active, so this never
    promotes by itself. For a source, the stale 'irrelevant' label its rejection
    harvested is removed, so a later promote-source records the corrected positive
    instead of being blocked by the harvest's title dedup.
    """
    found = find_record("claims", args.id)
    kind = "claims"
    if found is None:
        found = find_record("sources", args.id)
        kind = "sources"
    if found is None:
        found = find_record("skills", args.id)
        kind = "skills"
    if found is None:
        return [f"record {args.id} not found in data/claims/, data/sources/ or data/skills/"]
    _, records, record = found

    if kind == "skills":
        if record.get("status") != "deprecated":
            return [f"skill {args.id} is {record.get('status')}, not deprecated; nothing to re-open"]
        record["status"] = "candidate"
        record["updated_at"] = TODAY
        record.setdefault("change_log", []).append(
            {
                "date": TODAY,
                "change": "Re-opened deprecated skill to candidate",
                "reason": "Re-opened for review under a changed scope.",
            }
        )
    else:
        if record.get("status") != "rejected":
            return [f"{kind[:-1]} {args.id} is {record.get('status')}, not rejected; nothing to re-open"]
        record["status"] = "candidate"
        record["reviewed_at"] = None

    errors = _schema_errors(kind, record)
    if errors:
        return errors
    write_json(found[0], records)
    if kind == "sources":
        removed = remove_harvested_label(record)
        if removed:
            print(f"Removed {removed} stale harvested label(s) for {args.id}.")
    return []


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    actions: dict[str, Callable[[argparse.Namespace], list[str]]] = {
        "claim": promote_claim,
        "skill": promote_skill,
        "reject": reject_record,
        "reject-source": reject_source,
        "promote-source": promote_source,
        "attach-claim": attach_claim,
        "reopen": reopen_record,
    }
    verb = {
        "reject": "Rejected",
        "reject-source": "Rejected",
        "attach-claim": "Attached",
        "reopen": "Re-opened",
    }.get(args.kind, "Promoted")
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
