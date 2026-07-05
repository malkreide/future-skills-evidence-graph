"""Tests for the PR-comment review bridge (run_review_command).

The bridge is transport, not policy: it must map maintainer comment lines
exactly onto promote_candidate.py argv lists (allow-listed subcommands, shlex
semantics, no shell) and ignore prose. Execution itself is promote_candidate's
already-tested territory, so these tests focus on the parser plus one
subprocess smoke case.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_review_command as rrc  # noqa: E402


class ParseCommandsTests(unittest.TestCase):
    def test_slash_command_lines_become_argv_lists(self):
        body = (
            "Danke fürs Einreichen!\n"
            "/promote-source src-abc --year 2024\n"
            '/claim clm-x --context "Swiss primary schools" --age-range "8-12" '
            '--outcome "Better reasoning" --evidence-type systematic_review '
            "--evidence-strength moderate --supports skill-ai-literacy\n"
        )
        commands, problems = rrc.parse_commands(body)
        self.assertEqual(problems, [])
        self.assertEqual(commands[0], ["promote-source", "src-abc", "--year", "2024"])
        self.assertEqual(commands[1][0], "claim")
        # shlex semantics: the quoted context arrives as ONE token.
        self.assertIn("Swiss primary schools", commands[1])

    def test_worksheet_lines_are_accepted_verbatim(self):
        # Reviewers copy commands straight out of eval/candidate_triage.json.
        body = (
            "```\n"
            "python scripts/promote_candidate.py reject clm-y\n"
            "```\n"
        )
        commands, problems = rrc.parse_commands(body)
        self.assertEqual(problems, [])
        self.assertEqual(commands, [["reject", "clm-y"]])

    def test_prose_and_foreign_slash_lines_are_ignored(self):
        body = (
            "Looks good /cc @maintainer\n"
            "The URL is https://example.org/claims/overview\n"
            "reject clm-z\n"  # no slash, no worksheet prefix -> prose
        )
        commands, problems = rrc.parse_commands(body)
        self.assertEqual(commands, [])
        self.assertEqual(problems, [])

    def test_near_miss_command_is_reported_not_dropped(self):
        commands, problems = rrc.parse_commands("/promote src-abc")
        self.assertEqual(commands, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("/promote", problems[0])

    def test_unbalanced_quotes_become_a_problem(self):
        commands, problems = rrc.parse_commands('/reject clm-x --note "unterminated')
        self.assertEqual(commands, [])
        self.assertEqual(len(problems), 1)

    def test_only_allowlisted_subcommands_run(self):
        # Even a plausible-looking injection line must not produce a command.
        body = "/rm -rf data\n/claim; echo pwned\n"
        commands, problems = rrc.parse_commands(body)
        for tokens in commands:
            self.assertIn(tokens[0], rrc.ALLOWED_SUBCOMMANDS)
        # "/claim; echo pwned" parses via shlex into tokens, NOT a shell string;
        # the ';' stays inside a token and reaches argparse as a literal that
        # promote_candidate rejects (no record of that id).
        self.assertTrue(all("rm" != tokens[0] for tokens in commands))


class RunCommandSmokeTests(unittest.TestCase):
    def test_unknown_record_fails_cleanly_without_shell(self):
        ok, transcript = rrc.run_command(["reject", "clm-does-not-exist-xyz"])
        self.assertFalse(ok)
        self.assertIn("clm-does-not-exist-xyz", transcript)


if __name__ == "__main__":
    unittest.main()
