"""Restore still-pending candidates from the review branch without reverting reviews.

Every ingest workflow checks out the base branch and then needs the candidates
an earlier run left unmerged on ``research/candidates``, so the importers
deduplicate against them instead of importing the same works again.

Checking those files out wholesale (``git checkout <ref> -- data/*/candidates-*.json``)
did that, but it also reverted every review decision that had reached the base
branch in the meantime. promote_candidate.py flips ``status`` **in place** inside
the candidates-*.json files -- a promoted record is never moved to a curated
file -- and the review branch is force-pushed from an older base on every run.
So a claim reviewed on the base branch came back as a candidate, dropped out of
scoring (score_evidence.py only counts reviewed claims), and validate_data.py
failed with an evidence_score mismatch on a skill nobody had touched.

This merges instead of overwriting: the checked-out base copy of a record always
wins, and only records that exist *solely* on the review branch are appended --
those are the genuinely pending ones the importers need for deduplication.
Sources are additionally matched on their identity and title/year keys, the same
keys validate_data.py rejects duplicates on, so restoring never reintroduces a
work the base branch already carries under a different id.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import ROOT, load_json, source_identity, source_title_key, write_json


# Kinds whose candidates-*.json files the ingest workflows carry across runs.
CANDIDATE_KINDS = ("sources", "claims", "skills")
CANDIDATE_PREFIX = "candidates-"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def ref_exists(root: Path, ref: str) -> bool:
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    return True


def candidate_paths_on_ref(root: Path, ref: str, kind: str) -> list[str]:
    """Repository-relative candidates-*.json paths for *kind* on *ref*."""
    try:
        listing = _git(root, "ls-tree", "-r", "--name-only", ref, "--", f"data/{kind}/")
    except subprocess.CalledProcessError:
        return []
    return sorted(
        path
        for path in listing.splitlines()
        if Path(path).name.startswith(CANDIDATE_PREFIX) and path.endswith(".json")
    )


def read_records_on_ref(root: Path, ref: str, path: str) -> list[dict[str, Any]]:
    payload = json.loads(_git(root, "show", f"{ref}:{path}"))
    if not isinstance(payload, list):
        raise ValueError(f"{ref}:{path} must contain a JSON array")
    return [record for record in payload if isinstance(record, dict)]


def record_keys(kind: str, record: dict[str, Any]) -> set[str]:
    keys = {f"id:{record.get('id', '')}"}
    if kind == "sources":
        keys.add(f"identity:{source_identity(record)}")
        keys.add(f"title:{source_title_key(record)}")
    return keys


def known_keys(root: Path, kind: str) -> set[str]:
    """Identity keys of every record the checked-out base branch already carries.

    Keys span *all* files of the kind, not just the candidates-*.json ones: a
    record may have been merged, deduplicated or re-filed since the review
    branch was cut, and restoring a second copy of it would trip the duplicate
    checks in validate_data.py.
    """
    keys: set[str] = set()
    directory = root / "data" / kind
    if not directory.exists():
        return keys
    for path in sorted(directory.glob("*.json")):
        payload = load_json(path)
        if not isinstance(payload, list):
            continue
        for record in payload:
            if isinstance(record, dict):
                keys.update(record_keys(kind, record))
    return keys


def restore_kind(root: Path, ref: str, kind: str) -> tuple[int, int]:
    """Merge *kind*'s candidate files from *ref* into the working tree.

    Returns (restored, skipped): records appended as still pending, and records
    the base branch already carries, which are therefore left as base has them.
    """
    base_keys = known_keys(root, kind)
    restored = 0
    skipped = 0
    for path in candidate_paths_on_ref(root, ref, kind):
        branch_records = read_records_on_ref(root, ref, path)
        target = root / path
        base_records = load_json(target) if target.exists() else []
        if not isinstance(base_records, list):
            raise ValueError(f"{path} must contain a JSON array")

        pending: list[dict[str, Any]] = []
        for record in branch_records:
            keys = record_keys(kind, record)
            if keys & base_keys:
                skipped += 1
                continue
            base_keys.update(keys)
            pending.append(record)

        if not pending:
            continue
        write_json(target, list(base_records) + pending)
        restored += len(pending)
        print(f"Restored {len(pending)} pending record(s) into {path}.")
    return restored, skipped


def restore_pending(root: Path, ref: str, kinds: tuple[str, ...]) -> tuple[int, int]:
    restored = 0
    skipped = 0
    for kind in kinds:
        kind_restored, kind_skipped = restore_kind(root, ref, kind)
        restored += kind_restored
        skipped += kind_skipped
    return restored, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge still-pending candidates from the review branch into the checked-out tree."
        )
    )
    parser.add_argument(
        "--ref",
        default="FETCH_HEAD",
        help="Git ref holding the review branch (default: FETCH_HEAD).",
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=CANDIDATE_KINDS,
        help="Restrict to one record kind (repeatable). Default: all of them.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root to operate on (default: this checkout).",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not ref_exists(root, args.ref):
        print(f"No {args.ref} to restore from; keeping the checked-out candidates.")
        return 0

    restored, skipped = restore_pending(root, args.ref, tuple(args.kind or CANDIDATE_KINDS))
    print(
        f"Restored {restored} pending candidate record(s); "
        f"kept the base branch copy of {skipped} already-merged record(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
