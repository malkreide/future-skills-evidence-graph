"""Tests for the issue-form -> report-import bridge (parse_ingest_issue).

These cover the parsing and input-resolution logic only; no network and no LLM
are exercised (PDF download/extraction is patched). They lock in the contract the
ingest-from-issue workflow depends on: a manifest is produced only when usable
plaintext is found, and every other case becomes a human-readable skip reason.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import parse_ingest_issue as pii  # noqa: E402


def make_body(url="", publisher="", year="", plaintext="", attachment="") -> str:
    """Render an issue-form body the way GitHub does (### heading per field)."""

    def field(value: str) -> str:
        return value if value else pii.NO_RESPONSE

    return "\n\n".join(
        [
            f"### Quellen-URL\n\n{field(url)}",
            f"### Herausgeber\n\n{field(publisher)}",
            f"### Erscheinungsjahr\n\n{field(year)}",
            f"### Berichtstext (einfügen)\n\n{field(plaintext)}",
            f"### PDF anhängen\n\n{field(attachment)}",
        ]
    )


def _addrinfo(ip: str):
    """A minimal getaddrinfo result resolving to *ip*."""
    import socket

    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]


class PublicUrlGuardTests(unittest.TestCase):
    """The PDF URL comes from an arbitrary issue body, so the downloader must
    refuse anything that is not plain http(s) to a publicly routed host (SSRF)."""

    def test_public_host_passes(self):
        with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            pii.assert_public_http_url("https://example.org/report.pdf")  # no raise

    def test_private_loopback_linklocal_and_metadata_are_rejected(self):
        for ip in ("10.1.2.3", "192.168.0.5", "172.16.9.9", "127.0.0.1",
                   "169.254.169.254", "0.0.0.0"):
            with mock.patch("socket.getaddrinfo", return_value=_addrinfo(ip)):
                with self.assertRaises(RuntimeError, msg=ip):
                    pii.assert_public_http_url("https://internal.host/x.pdf")

    def test_one_private_answer_among_public_ones_rejects(self):
        # DNS may return several records; a single internal one must veto.
        answers = _addrinfo("93.184.216.34") + _addrinfo("10.0.0.7")
        with mock.patch("socket.getaddrinfo", return_value=answers):
            with self.assertRaises(RuntimeError):
                pii.assert_public_http_url("https://mixed.host/x.pdf")

    def test_non_http_scheme_and_odd_port_are_rejected(self):
        with self.assertRaises(RuntimeError):
            pii.assert_public_http_url("ftp://example.org/x.pdf")
        with self.assertRaises(RuntimeError):
            pii.assert_public_http_url("file:///etc/passwd")
        with self.assertRaises(RuntimeError):
            pii.assert_public_http_url("https://example.org:8080/x.pdf")

    def test_unresolvable_host_becomes_runtime_error(self):
        with mock.patch("socket.getaddrinfo", side_effect=OSError("no such host")):
            with self.assertRaises(RuntimeError):
                pii.assert_public_http_url("https://does-not-exist.example/x.pdf")

    def test_download_checks_url_before_opening(self):
        # The guard fires before any connection is attempted.
        with mock.patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            with mock.patch("urllib.request.build_opener") as opener:
                with self.assertRaises(RuntimeError):
                    pii.download("https://internal/x.pdf", Path("/tmp/x.pdf"), None)
                opener.return_value.open.assert_not_called()

    def test_redirect_off_github_drops_authorization(self):
        handler = pii._SafeRedirectHandler()
        request = mock.Mock()
        redirected = mock.Mock()
        redirected.headers = {"Authorization": "Bearer secret"}
        with mock.patch.object(pii, "assert_public_http_url") as guard, mock.patch.object(
            pii.urllib.request.HTTPRedirectHandler,
            "redirect_request",
            return_value=redirected,
        ):
            result = handler.redirect_request(
                request, None, 302, "Found", {}, "https://elsewhere.org/x.pdf"
            )
        guard.assert_called_once_with("https://elsewhere.org/x.pdf")
        self.assertNotIn("Authorization", result.headers)


class ParseSectionsTests(unittest.TestCase):
    def test_maps_labels_to_keys_and_blanks_no_response(self):
        body = make_body(url="https://example.org/r.pdf", publisher="OECD")
        values = pii.parse_sections(body)
        self.assertEqual(values["url"], "https://example.org/r.pdf")
        self.assertEqual(values["publisher"], "OECD")
        # Untouched fields render as the placeholder and must come back empty.
        self.assertEqual(values["year"], "")
        self.assertEqual(values["plaintext"], "")

    def test_unknown_headings_ignored(self):
        body = "### Something else\n\nvalue\n\n### Quellen-URL\n\nhttps://x.org/a.pdf"
        values = pii.parse_sections(body)
        self.assertEqual(values, {"url": "https://x.org/a.pdf"})

    def test_multiline_value_preserved(self):
        body = make_body(plaintext="Line one.\nLine two.")
        self.assertEqual(pii.parse_sections(body)["plaintext"], "Line one.\nLine two.")


class PdfDetectionTests(unittest.TestCase):
    def test_is_pdf_url_handles_query_and_case(self):
        self.assertTrue(pii.is_pdf_url("https://x.org/A.PDF?token=1"))
        self.assertTrue(pii.is_pdf_url("https://github.com/user-attachments/files/9/r.pdf"))
        self.assertFalse(pii.is_pdf_url("https://x.org/page.html"))

    def test_find_pdf_url_prefers_first_attachment(self):
        attachment = "[report.pdf](https://github.com/user-attachments/files/1/report.pdf)"
        self.assertEqual(
            pii.find_pdf_url(attachment, ""),
            "https://github.com/user-attachments/files/1/report.pdf",
        )

    def test_find_pdf_url_ignores_non_pdf_links(self):
        self.assertIsNone(pii.find_pdf_url("[site](https://x.org/page.html)", ""))


class ParseYearTests(unittest.TestCase):
    def test_extracts_four_digit_year(self):
        self.assertEqual(pii.parse_year("2023"), 2023)
        self.assertEqual(pii.parse_year("erschienen 2019 bei OECD"), 2019)
        self.assertIsNone(pii.parse_year(""))
        self.assertIsNone(pii.parse_year("letztes Jahr"))


class ResolvePlaintextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_pasted_text_wins(self):
        values = {"plaintext": "Ein Befund über Zukunftskompetenzen."}
        text, reason = pii.resolve_plaintext(values, "", self.workdir, None)
        self.assertEqual(text, "Ein Befund über Zukunftskompetenzen.")
        self.assertIn("Formular", reason)

    def test_pdf_attachment_downloaded_and_extracted(self):
        values = {"attachment": "[r.pdf](https://github.com/user-attachments/files/1/r.pdf)"}
        with mock.patch.object(pii, "download") as dl, mock.patch.object(
            pii, "extract_text", return_value="Extrahierter PDF-Text."
        ):
            text, reason = pii.resolve_plaintext(values, "", self.workdir, "tok")
        dl.assert_called_once()
        self.assertEqual(text.strip(), "Extrahierter PDF-Text.")
        self.assertIn("angehängtes PDF", reason)

    def test_pdf_from_url_when_no_paste_or_attachment(self):
        values = {"url": "https://oecd.org/report.pdf"}
        with mock.patch.object(pii, "download"), mock.patch.object(
            pii, "extract_text", return_value="Aus der URL."
        ):
            text, reason = pii.resolve_plaintext(values, "", self.workdir, None)
        self.assertEqual(text.strip(), "Aus der URL.")
        self.assertIn("Quellen-URL", reason)

    def test_no_input_yields_skip_reason(self):
        text, reason = pii.resolve_plaintext({"url": "https://x.org/page.html"}, "", self.workdir, None)
        self.assertIsNone(text)
        self.assertIn("Kein Text gefunden", reason)

    def test_failed_download_becomes_reason_not_exception(self):
        values = {"url": "https://oecd.org/report.pdf"}
        with mock.patch.object(pii, "download", side_effect=RuntimeError("404")):
            text, reason = pii.resolve_plaintext(values, "", self.workdir, None)
        self.assertIsNone(text)
        self.assertIn("PDF konnte nicht verarbeitet werden", reason)

    def test_empty_extraction_asks_for_text(self):
        values = {"url": "https://oecd.org/report.pdf"}
        with mock.patch.object(pii, "download"), mock.patch.object(
            pii, "extract_text", return_value="   "
        ):
            text, reason = pii.resolve_plaintext(values, "", self.workdir, None)
        self.assertIsNone(text)
        self.assertIn("kein Text extrahieren", reason)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir_name = ".ingest_work_test"
        self._out = Path(self._tmp.name) / "out.txt"
        self.addCleanup(self._tmp.cleanup)

    def _run(self, body):
        argv = ["parse_ingest_issue.py", "--workdir", self.workdir_name, "--body", body]
        env = {"GITHUB_OUTPUT": str(self._out)}
        with mock.patch.object(sys, "argv", argv), mock.patch.dict("os.environ", env, clear=False):
            pii.main()
        return self._out.read_text(encoding="utf-8") if self._out.exists() else ""

    def tearDown(self):
        workdir = pii.ROOT / self.workdir_name
        if workdir.exists():
            for child in workdir.iterdir():
                child.unlink()
            workdir.rmdir()

    def test_pasted_text_writes_manifest(self):
        body = make_body(
            url="https://oecd.org/r.pdf",
            publisher="OECD",
            year="2023",
            plaintext="Ein wichtiger Befund zu Zukunftskompetenzen in Schulen.",
        )
        output = self._run(body)
        self.assertIn("status=ingest", output)
        manifest_path = pii.ROOT / self.workdir_name / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1)
        entry = manifest[0]
        self.assertEqual(entry["url"], "https://oecd.org/r.pdf")
        self.assertEqual(entry["publisher"], "OECD")
        self.assertEqual(entry["year"], 2023)
        self.assertTrue((pii.ROOT / entry["report"]).exists())

    def test_no_url_and_no_resolution_skips(self):
        # URL optional now (Option B), but with nothing resolvable and no issue
        # URL fallback the run still skips with a clear reason.
        with mock.patch.object(pii, "resolve_url", return_value=None), mock.patch.dict(
            "os.environ", {"ISSUE_URL": ""}, clear=False
        ):
            output = self._run(make_body(plaintext="text but no url anywhere"))
        self.assertIn("status=skip", output)
        self.assertIn("Katalog-Suche", output)

    def test_no_url_resolved_via_catalog(self):
        resolved = {"url": "https://doi.org/10.1/abc", "via": "crossref", "match": "A title"}
        with mock.patch.object(pii, "resolve_url", return_value=resolved):
            output = self._run(
                make_body(plaintext="Ein Befund zu Zukunftskompetenzen.", year="2023")
            )
        self.assertIn("status=ingest", output)
        manifest = json.loads(
            (pii.ROOT / self.workdir_name / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest[0]["url"], "https://doi.org/10.1/abc")
        self.assertIn("via Crossref", output)

    def test_no_url_falls_back_to_issue_url(self):
        with mock.patch.object(pii, "resolve_url", return_value=None), mock.patch.dict(
            "os.environ", {"ISSUE_URL": "https://github.com/o/r/issues/5"}, clear=False
        ):
            output = self._run(make_body(plaintext="Ein Befund ohne URL im Text."))
        self.assertIn("status=ingest", output)
        manifest = json.loads(
            (pii.ROOT / self.workdir_name / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest[0]["url"], "https://github.com/o/r/issues/5")
        self.assertIn("Platzhalter", output)

    def test_no_text_skips(self):
        output = self._run(make_body(url="https://x.org/page.html"))
        self.assertIn("status=skip", output)


if __name__ == "__main__":
    unittest.main()
