from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from restore_pending_candidates import (  # noqa: E402
    CANDIDATE_KINDS,
    candidate_paths_on_ref,
    known_keys,
    record_keys,
    ref_exists,
    restore_pending,
)


def _source(source_id: str, **overrides: object) -> dict[str, object]:
    record = {
        "id": source_id,
        "title": source_id.replace("-", " "),
        "year": 2025,
        "doi": f"10.1000/{source_id}",
        "source_type": "peer_reviewed_article",
        "status": "candidate",
    }
    record.update(overrides)
    return record


def _claim(claim_id: str, **overrides: object) -> dict[str, object]:
    record = {
        "id": claim_id,
        "statement": claim_id,
        "source_ids": [],
        "evidence_strength": "low",
        "status": "candidate",
    }
    record.update(overrides)
    return record


class RestorePendingCandidatesTest(unittest.TestCase):
    """The ingest workflows carry pending candidates across runs; reviews must survive."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _write(self, relative: str, records: list[dict[str, object]]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    def _read(self, relative: str) -> list[dict[str, object]]:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def _commit(self, message: str) -> None:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    def _build_review_branch(
        self,
        branch_files: dict[str, list[dict[str, object]]],
        base_files: dict[str, list[dict[str, object]]],
    ) -> None:
        """Commit *branch_files* on review/branch, then check *base_files* out on main.

        Mirrors the real setup: the review branch is force-pushed from an older
        base, so it lags behind whatever reviews have landed on main since.
        """
        for relative, records in branch_files.items():
            self._write(relative, records)
        self._commit("base")
        self._git("branch", "review")
        for relative, records in base_files.items():
            self._write(relative, records)
        self._commit("reviews merged on main")

    def test_review_on_base_survives_a_stale_review_branch(self) -> None:
        # The regression: a claim reviewed on main is still 'candidate' on the
        # review branch. Checking the file out reverted it, the claim dropped out
        # of scoring, and validate_data.py failed on an untouched skill's score.
        self._build_review_branch(
            branch_files={
                "data/claims/candidates-extracted.json": [
                    _claim("claim-reviewed-since"),
                    _claim("claim-still-pending"),
                ]
            },
            base_files={
                "data/claims/candidates-extracted.json": [
                    _claim("claim-reviewed-since", status="reviewed", reviewed_at="2026-07-31"),
                    _claim("claim-still-pending"),
                ]
            },
        )

        restored, skipped = restore_pending(self.root, "review", CANDIDATE_KINDS)

        records = {record["id"]: record for record in self._read("data/claims/candidates-extracted.json")}
        self.assertEqual(records["claim-reviewed-since"]["status"], "reviewed")
        self.assertEqual(len(records), 2)
        self.assertEqual((restored, skipped), (0, 2))

    def test_pending_candidates_are_restored(self) -> None:
        # The point of the restore: candidates that exist only on the review
        # branch come back, so the importers deduplicate against them.
        self._build_review_branch(
            branch_files={
                "data/sources/candidates-openalex.json": [
                    _source("src-known"),
                    _source("src-only-on-review-branch"),
                ]
            },
            base_files={"data/sources/candidates-openalex.json": [_source("src-known")]},
        )

        restored, skipped = restore_pending(self.root, "review", CANDIDATE_KINDS)

        ids = [record["id"] for record in self._read("data/sources/candidates-openalex.json")]
        self.assertEqual(ids, ["src-known", "src-only-on-review-branch"])
        self.assertEqual((restored, skipped), (1, 1))

    def test_candidate_file_absent_on_base_is_recreated(self) -> None:
        # A file the base branch never had is restored whole -- every record in it
        # is pending by definition.
        self._write("data/sources/candidates-eric.json", [_source("src-pending")])
        self._commit("base")
        self._git("branch", "review")
        (self.root / "data/sources/candidates-eric.json").unlink()
        self._commit("drop the candidate file on main")

        restored, _ = restore_pending(self.root, "review", CANDIDATE_KINDS)

        self.assertEqual(restored, 1)
        ids = [record["id"] for record in self._read("data/sources/candidates-eric.json")]
        self.assertEqual(ids, ["src-pending"])

    def test_source_re_filed_under_a_new_id_is_not_restored_twice(self) -> None:
        # deduplicate_sources.py can re-file a source; restoring the review
        # branch's copy would reintroduce the duplicate identity that
        # validate_data.py rejects.
        self._build_review_branch(
            branch_files={
                "data/sources/candidates-crossref.json": [_source("src-old-id")],
            },
            base_files={
                "data/sources/candidates-crossref.json": [],
                "data/sources/seed.json": [
                    dict(_source("src-old-id"), id="src-merged-id", status="reviewed")
                ],
            },
        )

        restored, skipped = restore_pending(self.root, "review", CANDIDATE_KINDS)

        self.assertEqual((restored, skipped), (0, 1))
        self.assertEqual(self._read("data/sources/candidates-crossref.json"), [])

    def test_only_candidate_files_are_touched(self) -> None:
        # Curated files are the reviewer's, never the restore's.
        self._build_review_branch(
            branch_files={"data/claims/seed.json": [_claim("claim-seed")]},
            base_files={
                "data/claims/seed.json": [_claim("claim-seed", status="reviewed")],
            },
        )

        self.assertEqual(candidate_paths_on_ref(self.root, "review", "claims"), [])
        restore_pending(self.root, "review", CANDIDATE_KINDS)

        self.assertEqual(self._read("data/claims/seed.json")[0]["status"], "reviewed")

    def test_missing_ref_is_a_no_op(self) -> None:
        # First run ever: no review branch to restore from.
        self._write("data/claims/candidates-extracted.json", [_claim("claim-a")])
        self._commit("base")

        self.assertFalse(ref_exists(self.root, "does-not-exist"))
        self.assertEqual(candidate_paths_on_ref(self.root, "does-not-exist", "claims"), [])

    def test_source_keys_cover_identity_and_title(self) -> None:
        keys = record_keys("sources", _source("src-a"))
        self.assertIn("id:src-a", keys)
        self.assertTrue(any(key.startswith("identity:") for key in keys))
        self.assertTrue(any(key.startswith("title:") for key in keys))
        # Claims and skills dedupe on id alone -- they carry no bibliographic identity.
        self.assertEqual(record_keys("claims", _claim("claim-a")), {"id:claim-a"})

    def test_known_keys_span_every_file_of_the_kind(self) -> None:
        self._write("data/claims/seed.json", [_claim("claim-seed")])
        self._write("data/claims/candidates-extracted.json", [_claim("claim-candidate")])
        keys = known_keys(self.root, "claims")
        self.assertIn("id:claim-seed", keys)
        self.assertIn("id:claim-candidate", keys)


if __name__ == "__main__":
    unittest.main()
