"""Tests for the optional Telegram integration (notify + intake).

Pure logic only — no network: the Bot API client is faked and the GitHub
issue creation is patched. The central contract locked in here is that a
Telegram submission renders an issue body that ``parse_ingest_issue`` parses
exactly like a "Bericht einreichen" form submission, so both intakes share
one import path.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import parse_ingest_issue as pii  # noqa: E402
import telegram_intake as ti  # noqa: E402
import telegram_notify as tn  # noqa: E402


class FormatMessageTests(unittest.TestCase):
    def test_composes_title_bullets_and_text(self):
        message = tn.format_message("Titel", ["eins", "", "zwei"], "Absatz")
        self.assertEqual(message, "Titel\n• eins\n• zwei\nAbsatz")

    def test_truncates_to_telegram_limit(self):
        message = tn.format_message("T", text="x" * 10_000)
        self.assertLessEqual(len(message), tn.MAX_MESSAGE_CHARS)
        self.assertTrue(message.endswith(tn.TRUNCATION_MARKER))

    def test_redact_token_strips_secret(self):
        self.assertNotIn("123:abc", tn.redact_token("url/bot123:abc/send", "123:abc"))


class NotifyConfigTests(unittest.TestCase):
    def test_unconfigured_is_a_noop(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(tn.telegram_config())
            self.assertFalse(tn.notify("Titel", text="Text"))

    def test_half_configured_behaves_like_unconfigured(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t"}, clear=True):
            self.assertIsNone(tn.telegram_config())

    def test_cli_exits_zero_without_configuration(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(sys, "argv", ["telegram_notify.py", "--title", "Hi"]):
                self.assertEqual(tn.main(), 0)


class AllowedChatIdsTests(unittest.TestCase):
    def test_allowlist_env_wins_and_splits_on_commas(self):
        env = {"TELEGRAM_ALLOWED_CHAT_IDS": "1, -42 ,7", "TELEGRAM_CHAT_ID": "99"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(ti.allowed_chat_ids(), {"1", "-42", "7"})

    def test_falls_back_to_notification_chat(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "99"}, clear=True):
            self.assertEqual(ti.allowed_chat_ids(), {"99"})


class ClassifyMessageTests(unittest.TestCase):
    def test_command_with_bot_suffix(self):
        action = ti.classify_message({"text": "/status@evidence_bot"})
        self.assertEqual(action, {"kind": "command", "name": "status"})

    def test_pdf_url_is_a_submission(self):
        action = ti.classify_message({"text": "Bitte: https://oecd.org/report.pdf"})
        self.assertEqual(action["kind"], "submission")
        self.assertEqual(action["url"], "https://oecd.org/report.pdf")
        self.assertEqual(action["text"], "")

    def test_landing_page_url_alone_yields_guidance(self):
        action = ti.classify_message({"text": "https://doi.org/10.1234/abcd"})
        self.assertEqual(action["kind"], "guidance")

    def test_long_url_does_not_count_as_report_text(self):
        url = "https://example.org/" + "a" * ti.MIN_REPORT_CHARS
        self.assertEqual(ti.classify_message({"text": url})["kind"], "guidance")

    def test_long_pasted_text_is_a_submission(self):
        text = "Befund. " * 50
        action = ti.classify_message({"text": text})
        self.assertEqual(action["kind"], "submission")
        self.assertEqual(action["text"], text.strip())

    def test_short_text_yields_guidance_and_empty_is_ignored(self):
        self.assertEqual(ti.classify_message({"text": "hallo"})["kind"], "guidance")
        self.assertEqual(ti.classify_message({})["kind"], "ignore")

    def test_pdf_document_is_a_submission(self):
        message = {
            "document": {"file_id": "f1", "file_name": "Bericht.PDF"},
            "caption": "OECD Bericht",
        }
        action = ti.classify_message(message)
        self.assertEqual(action["kind"], "submission")
        self.assertEqual(action["document"]["file_id"], "f1")

    def test_non_pdf_document_without_text_is_ignored(self):
        message = {"document": {"file_id": "f2", "file_name": "notizen.docx"}}
        self.assertEqual(ti.classify_message(message)["kind"], "ignore")


class IssueBodyRoundtripTests(unittest.TestCase):
    """The generated body must parse like a real issue-form submission."""

    def test_url_and_plaintext_survive_parse_sections(self):
        body = ti.build_issue_body(
            url="https://example.org/report.pdf",
            plaintext="Erster Absatz.\n\nZweiter Absatz.",
            provenance="Eingereicht über den Telegram-Intake.",
        )
        values = pii.parse_sections(body)
        self.assertEqual(values["url"], "https://example.org/report.pdf")
        self.assertEqual(values["plaintext"], "Erster Absatz.\n\nZweiter Absatz.")
        # Empty fields must come back empty (the NO_RESPONSE placeholder),
        # and the extra provenance heading must be invisible to the parser.
        self.assertEqual(values["publisher"], "")
        self.assertEqual(values["year"], "")
        self.assertNotIn("Herkunft", values)

    def test_overlong_plaintext_is_truncated_for_the_issue(self):
        body = ti.build_issue_body(plaintext="x" * (ti.MAX_ISSUE_PLAINTEXT_CHARS + 500))
        self.assertLess(len(body), ti.MAX_ISSUE_PLAINTEXT_CHARS + 1000)
        self.assertIn("gekürzt", body)

    def test_issue_title_prefers_filename_then_url_then_text(self):
        self.assertEqual(
            ti.build_issue_title({"document": {"file_name": "report.pdf"}}),
            "[ingest] report.pdf",
        )
        self.assertEqual(
            ti.build_issue_title({"url": "https://oecd.org/x/skills2030.pdf"}),
            "[ingest] skills2030.pdf",
        )
        self.assertTrue(
            ti.build_issue_title({"text": "Ein sehr langer Befundtext " * 20}).startswith(
                "[ingest] Ein sehr langer"
            )
        )


class FakeClient(ti.TelegramClient):
    """Records outbound calls instead of talking to the Bot API."""

    def __init__(self) -> None:
        super().__init__("fake-token")
        self.sent: list[tuple[Any, str]] = []
        self.acknowledged: int | None = None

    def send_message(self, chat_id, text, reply_to=None):  # noqa: D102
        self.sent.append((chat_id, text))

    def acknowledge(self, last_update_id):  # noqa: D102
        self.acknowledged = last_update_id

    def download_document(self, file_id, dest):  # noqa: D102
        dest.write_bytes(b"%PDF-fake")


class ProcessUpdateTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.workdir = Path(__file__).parent

    def _update(self, text: str, chat_id: int = 1) -> dict:
        return {
            "update_id": 10,
            "message": {"message_id": 5, "chat": {"id": chat_id}, "text": text},
        }

    def test_unauthorized_chat_is_ignored_without_reply(self):
        outcome = ti.process_update(
            self._update("https://x.org/a.pdf", chat_id=666),
            self.client,
            {"1"},
            "owner/repo",
            self.workdir,
        )
        self.assertIn("nicht autorisiert", outcome)
        self.assertEqual(self.client.sent, [])

    def test_help_command_replies_with_help(self):
        ti.process_update(self._update("/hilfe"), self.client, {"1"}, "owner/repo", self.workdir)
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn("PDF", self.client.sent[0][1])

    def test_submission_creates_issue_and_replies_with_link(self):
        env = {"TELEGRAM_GITHUB_TOKEN": "pat"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                ti, "create_issue", return_value="https://github.com/owner/repo/issues/7"
            ) as create:
                outcome = ti.process_update(
                    self._update("https://oecd.org/report.pdf"),
                    self.client,
                    {"1"},
                    "owner/repo",
                    self.workdir,
                )
        self.assertEqual(outcome, "Einreichung als Issue erfasst")
        args = create.call_args
        self.assertEqual(args.args[0], "owner/repo")
        self.assertEqual(args.args[1], "pat")
        # The allowlist authenticates the sender, so the issue is pre-approved.
        self.assertEqual(args.args[4], ["ingest", "ingest-approved"])
        self.assertIn("issues/7", self.client.sent[0][1])
        self.assertIn("startet automatisch", self.client.sent[0][1])

    def test_submission_with_default_token_mentions_manual_label(self):
        env = {"GITHUB_TOKEN": "ghs_default"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(ti, "create_issue", return_value="https://x/issues/8"):
                ti.process_update(
                    self._update("https://oecd.org/report.pdf"),
                    self.client,
                    {"1"},
                    "owner/repo",
                    self.workdir,
                )
        self.assertIn("ingest-approved", self.client.sent[0][1])
        self.assertIn("Maintainer", self.client.sent[0][1])

    def test_failed_issue_creation_becomes_a_chat_reply(self):
        env = {"TELEGRAM_GITHUB_TOKEN": "pat"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                ti, "create_issue", side_effect=RuntimeError("API kaputt")
            ):
                outcome = ti.process_update(
                    self._update("https://oecd.org/report.pdf"),
                    self.client,
                    {"1"},
                    "owner/repo",
                    self.workdir,
                )
        self.assertIn("fehlgeschlagen", outcome)
        self.assertIn("nicht geklappt", self.client.sent[0][1])

    def test_pdf_document_is_downloaded_and_extracted(self):
        update = {
            "update_id": 11,
            "message": {
                "message_id": 6,
                "chat": {"id": 1},
                "document": {"file_id": "f1", "file_name": "bericht.pdf"},
            },
        }
        env = {"TELEGRAM_GITHUB_TOKEN": "pat"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(ti, "extract_text", return_value="Befundtext.\n") as extract:
                with mock.patch.object(ti, "create_issue", return_value="https://x/issues/9") as create:
                    with tempfile.TemporaryDirectory() as tmp:
                        ti.process_update(update, self.client, {"1"}, "owner/repo", Path(tmp))
        extract.assert_called_once()
        body = create.call_args.args[3]
        self.assertIn("Befundtext.", body)
        # The token-bearing Telegram file URL must never reach the issue.
        self.assertNotIn("api.telegram.org", body)


class StatusTextTests(unittest.TestCase):
    def test_counts_records_by_status(self):
        records = {
            "sources": [{"status": "candidate"}, {"status": "reviewed"}],
            "claims": [{"status": "candidate"}],
            "skills": [],
        }
        with mock.patch.object(ti, "load_records", side_effect=records.get):
            text = ti.status_text()
        self.assertIn("Quellen: 2", text)
        self.assertIn("1 candidate", text)
        self.assertIn("Skills: 0", text)


if __name__ == "__main__":
    unittest.main()
