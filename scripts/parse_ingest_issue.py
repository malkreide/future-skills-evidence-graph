"""Turn a 'Bericht einreichen' issue-form body into an ingest_reports manifest.

This is the bridge between the manual, mobile-friendly intake (a GitHub issue
filed from the ``ingest-report`` form) and the existing report importer
(``scripts/ingest_reports.py``). The issue form lets a human paste report text,
drag in a PDF, or just give a PDF URL – from a desktop *or* a phone – and the
``ingest-from-issue`` workflow runs this parser to resolve that input into the
plaintext + metadata the importer consumes.

It only ever prepares an import; like everything else in the project it produces
nothing active. The importer still runs the verbatim hallucination guard and
writes ``status=candidate`` records for human review.

Resolution order for the report plaintext (first that yields text wins):

1. The pasted **Berichtstext** field, if non-empty.
2. A **PDF attachment** dragged into the body (a ``user-attachments`` or ``.pdf``
   link), downloaded and extracted with :mod:`extract_pdf_text`.
3. The **Quellen-URL**, if it points directly at a ``.pdf``, downloaded and
   extracted the same way.

When none of these yields text the parser writes no manifest and reports a
human-readable reason, so the workflow can comment it back on the issue instead
of failing. The parser performs no LLM call and writes nothing into ``data/``.

The issue form's URL is optional: when it is blank the parser resolves one via
``resolve_source_url.resolve_url`` (document → Crossref → OpenAlex → optional
Google), falling back to the issue URL (``ISSUE_URL``) as a flagged placeholder.

    ISSUE_BODY="$(...)" python scripts/parse_ingest_issue.py --workdir .ingest_work

Outputs (for the workflow) are written to ``$GITHUB_OUTPUT`` when set, and always
mirrored to stdout:

    status=ingest|skip
    manifest=<path>        # only when status=ingest
    reason=<text>          # human-readable, always
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from common import ROOT
from extract_pdf_text import clean_extracted_text, extract_text
from resolve_source_url import resolve_url

# The issue-form field labels (see .github/ISSUE_TEMPLATE/ingest-report.yml).
# GitHub renders each field as a "### <label>" section in the issue body, so the
# parser keys off these exact strings. Keep them in sync with the form.
FIELD_LABELS = {
    "Quellen-URL": "url",
    "Herausgeber": "publisher",
    "Erscheinungsjahr": "year",
    "Berichtstext (einfügen)": "plaintext",
    "PDF anhängen": "attachment",
}

# GitHub writes this placeholder into the body for any field left empty.
NO_RESPONSE = "_No response_"

# Guard the PDF download so a hostile or mistaken link cannot exhaust the runner.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30

# Markdown link / image: [label](url) and ![label](url). Used to find an attached
# or linked PDF in the free-text fields.
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((https?://[^\s)]+)\)")


def parse_sections(body: str) -> dict[str, str]:
    """Split an issue-form *body* into ``{field_key: value}``.

    GitHub renders each form field as a ``### <label>`` heading followed by the
    value. Unknown headings are ignored; an empty field (GitHub's
    ``_No response_`` placeholder, or whitespace) maps to an empty string.
    """
    values: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current_key is None:
            return
        text = "\n".join(buffer).strip()
        values[current_key] = "" if text == NO_RESPONSE else text

    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = line.strip()
        if heading.startswith("### "):
            flush()
            label = heading[4:].strip()
            current_key = FIELD_LABELS.get(label)
            buffer = []
            continue
        if current_key is not None:
            buffer.append(line)
    flush()
    return values


def find_pdf_url(*texts: str) -> str | None:
    """Return the first PDF link found across *texts*, or None.

    A PDF is either an explicit ``.pdf`` URL or a GitHub ``user-attachments``
    upload (drag-and-drop / mobile attach), which carries the real filename in
    its path. The first match wins so a deliberately attached PDF beats an
    incidental link.
    """
    for text in texts:
        for url in _MARKDOWN_LINK.findall(text):
            if is_pdf_url(url):
                return url
    return None


def is_pdf_url(url: str) -> bool:
    """True when *url* looks like a downloadable PDF.

    GitHub stores dragged/attached files under ``/user-attachments/files/<id>/
    <name>`` keeping the real filename, so an attached PDF ends in ``.pdf`` here
    too; matching on the extension covers both explicit links and attachments.
    """
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".pdf")


def assert_public_http_url(url: str) -> None:
    """Reject *url* unless it is plain http(s) to a publicly routed host.

    The URL comes straight out of an issue body, i.e. from an arbitrary GitHub
    account — without this check the runner could be pointed at cloud metadata
    endpoints or hosts on its internal network (SSRF). Every DNS answer for the
    host must be a public address; scheme and port are pinned to standard web.
    Raises ``RuntimeError`` with a human-readable reason.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(f"Nur http(s)-URLs werden geladen, nicht: {url}")
    if not parsed.hostname:
        raise RuntimeError(f"URL ohne Hostnamen: {url}")
    if parsed.port not in (None, 80, 443):
        raise RuntimeError(f"Nur die Standard-Ports 80/443 werden geladen: {url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise RuntimeError(f"Hostname nicht auflösbar ({parsed.hostname}): {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise RuntimeError(
                f"URL zeigt auf eine nicht-öffentliche Adresse ({parsed.hostname} → "
                f"{address}) und wird nicht geladen."
            )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect hop against :func:`assert_public_http_url`.

    A public URL may 302 to an internal one; urllib follows redirects silently,
    so each hop is validated and the redirected request is rebuilt WITHOUT the
    original headers — the GitHub token must never travel to a redirect target
    off github.com.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N803
        assert_public_http_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and "github.com" not in newurl:
            redirected.headers.pop("Authorization", None)
        return redirected


def download(url: str, dest: Path, token: str | None) -> None:
    """Download *url* to *dest*, sending the GitHub token for private assets.

    Raises ``RuntimeError`` with a human-readable message on any failure or when
    the response exceeds :data:`MAX_DOWNLOAD_BYTES`, so the caller can surface it
    as an issue comment rather than a stack trace. The URL (and every redirect
    hop) must point at a public web host — see :func:`assert_public_http_url`.
    """
    assert_public_http_url(url)
    headers = {"User-Agent": "future-skills-evidence-graph-ingest"}
    # github.com attachment URLs for a private repo need auth; a public asset
    # ignores the header, so sending it is always safe.
    if token and "github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    try:
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise RuntimeError(f"Download fehlgeschlagen ({url}): {exc}") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError(
            f"Datei größer als das Limit von {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB."
        )
    dest.write_bytes(data)


def resolve_plaintext(
    values: dict[str, str], body: str, workdir: Path, token: str | None
) -> tuple[str | None, str]:
    """Resolve the report plaintext from the parsed fields, with a reason.

    Returns ``(text, reason)``; ``text`` is None when no input yielded usable
    plaintext, and ``reason`` always explains what happened (which path was used,
    or what to do next). PDF downloads/extractions that fail are turned into a
    reason, never an exception.
    """
    pasted = values.get("plaintext", "").strip()
    if pasted:
        return pasted, "Berichtstext aus dem Formular übernommen."

    attachment = values.get("attachment", "")
    pdf_url = find_pdf_url(attachment, body)
    source_label = "angehängtes PDF"
    if pdf_url is None:
        url = values.get("url", "").strip()
        if url and is_pdf_url(url):
            pdf_url = url
            source_label = "PDF aus der Quellen-URL"

    if pdf_url is None:
        return None, (
            "Kein Text gefunden: bitte den Berichtstext einfügen, ein PDF "
            "anhängen oder eine direkte PDF-URL angeben, dann das Issue erneut "
            "mit dem Label `ingest` versehen."
        )

    pdf_path = workdir / "report.pdf"
    try:
        download(pdf_url, pdf_path, token)
        text = clean_extracted_text(extract_text(pdf_path))
    except (RuntimeError, SystemExit) as exc:
        return None, f"PDF konnte nicht verarbeitet werden: {exc}"
    if not text.strip():
        return None, (
            f"Aus dem {source_label} ließ sich kein Text extrahieren (evtl. ein "
            "gescanntes PDF ohne Textebene). Bitte den Text einfügen."
        )
    return text, f"Text aus {source_label} extrahiert."


def parse_year(raw: str) -> int | None:
    """Return a four-digit year from *raw*, or None."""
    match = re.search(r"\b(19|20)\d{2}\b", raw)
    return int(match.group(0)) if match else None


def determine_url(
    provided: str,
    text: str,
    publisher: str | None,
    year: int | None,
    issue_url: str,
) -> tuple[str, str]:
    """Resolve the source URL, returning ``(url, human_readable_note)``.

    A URL the submitter typed wins untouched. Otherwise resolve one from the
    report (`resolve_source_url`: document → Crossref → OpenAlex → optional
    Google). If that also fails, fall back to the issue URL as provenance so the
    schema's required ``url`` is satisfied — flagged so a reviewer corrects it.
    Returns an empty URL only when nothing is available (e.g. a local run with no
    issue URL), and the caller then skips.
    """
    if provided:
        return provided, "Quellen-URL aus dem Formular übernommen."
    resolved = resolve_url(text, title=None, year=year, publisher=publisher)
    if resolved:
        via = {
            "document": "aus dem Dokument",
            "crossref": "via Crossref",
            "openalex": "via OpenAlex",
            "google": "via Google-Suche",
        }.get(resolved["via"], resolved["via"])
        return resolved["url"], (
            f"Quellen-URL {via} ermittelt ({resolved['url']}) – bitte beim Review prüfen."
        )
    if issue_url:
        return issue_url, (
            "Keine Quell-URL gefunden – als Platzhalter die Issue-URL gesetzt; "
            "bitte beim Review die echte Quell-URL nachtragen."
        )
    return "", ""


def write_output(github_output: str | None, **fields: str) -> None:
    """Emit key=value lines to ``$GITHUB_OUTPUT`` (if set) and to stdout."""
    for key, value in fields.items():
        # GITHUB_OUTPUT needs a heredoc for any multi-line value (e.g. a reason).
        line = f"{key}={value}"
        print(line)
        if github_output:
            with open(github_output, "a", encoding="utf-8") as handle:
                if "\n" in value:
                    handle.write(f"{key}<<__EOF__\n{value}\n__EOF__\n")
                else:
                    handle.write(line + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse an ingest-report issue body into an ingest_reports manifest."
    )
    parser.add_argument(
        "--workdir",
        default=".ingest_work",
        help="Directory (under the repo root) for the downloaded PDF, plaintext and manifest.",
    )
    parser.add_argument(
        "--body",
        default=None,
        help="Issue body text; defaults to the ISSUE_BODY environment variable.",
    )
    args = parser.parse_args()

    body = args.body if args.body is not None else os.environ.get("ISSUE_BODY", "")
    github_output = os.environ.get("GITHUB_OUTPUT")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    workdir = (ROOT / args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    values = parse_sections(body)
    text, reason = resolve_plaintext(values, body, workdir, token)
    if text is None:
        write_output(github_output, status="skip", reason=reason)
        return 0

    publisher = values.get("publisher", "").strip() or None
    year = parse_year(values.get("year", ""))
    url, url_note = determine_url(
        values.get("url", "").strip(),
        text,
        publisher,
        year,
        os.environ.get("ISSUE_URL", "").strip(),
    )
    if not url:
        write_output(
            github_output,
            status="skip",
            reason=(
                "Keine Quellen-URL angegeben und keine im Dokument oder per "
                "Katalog-Suche (Crossref/OpenAlex) gefunden. Bitte eine URL "
                "eintragen und das Issue erneut mit dem Label `ingest` versehen."
            ),
        )
        return 0

    report_path = workdir / "report.txt"
    report_path.write_text(text, encoding="utf-8")
    manifest = [
        {"report": str(report_path.relative_to(ROOT)), "url": url,
         "publisher": publisher, "year": year}
    ]
    manifest_path = workdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    write_output(
        github_output,
        status="ingest",
        manifest=str(manifest_path.relative_to(ROOT)),
        reason=f"{reason} {url_note}".strip(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
