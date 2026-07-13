"""Telegram intake: turn chat messages into report-import issues (poll-based).

This is the inbound half of the optional Telegram integration (the outbound
half is ``telegram_notify.py``). The project stays GitHub-first and serverless:
no webhook endpoint exists. Instead, a scheduled workflow polls the Bot API
(``getUpdates``) and translates each authorized chat message into the SAME
mobile-friendly intake the project already has — a "Bericht einreichen" issue
(label ``ingest``) whose body uses the exact issue-form field headings, so
``parse_ingest_issue.py`` and the ``ingest-from-issue`` workflow process a
Telegram submission exactly like a form submission. Telegram is transport,
not policy: everything still becomes a *candidate* for human review.

What a chat member can do:

- Send a **direct PDF link** (``https://…/report.pdf``) → issue with that URL.
- Attach a **PDF document** → downloaded via the Bot API, extracted to
  plaintext here (so no token-bearing Telegram file URL ever lands in the
  issue), pasted into the form's text field.
- Paste **report text** (at least :data:`MIN_REPORT_CHARS` characters) → issue
  with that text.
- Read-only dashboard queries: ``/status`` (catalog counts), ``/skills`` (top
  skills by evidence score), ``/skill <term>`` (one skill in detail),
  ``/lp21`` (Lehrplan 21 coverage summary), ``/dashboard`` (link button);
  ``/hilfe`` (or ``/help``, ``/start``) → usage help. These read the same
  versioned records the dashboard is built from — answers arrive with the
  polling cadence, the always-current interactive view stays the dashboard.

Security model:

- Only messages from chats allow-listed via ``TELEGRAM_ALLOWED_CHAT_IDS``
  (fallback: ``TELEGRAM_CHAT_ID``) are processed; everything else is ignored
  silently, so the bot cannot be used as a spam relay or to spend LLM budget.
- Because the allowlist already authenticates the submitter, created issues
  carry ``ingest-approved`` alongside ``ingest`` — the same trust decision a
  maintainer makes for external form submissions.
- Updates are acknowledged (offset advanced) BEFORE processing: a crash mid-run
  then loses at most one poll's messages — which the per-message error reply
  and the workflow-failure notification surface — instead of re-filing
  duplicate issues every 30 minutes.

State lives entirely at Telegram (unconfirmed updates are kept ~24h), so the
poller needs no state file and writes nothing into the repository.

    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... GITHUB_REPOSITORY=owner/repo \
        GITHUB_TOKEN=... python scripts/telegram_intake.py

Setup and operations are documented in docs/telegram-integration.md.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from common import load_records
from extract_pdf_text import extract_text
from telegram_notify import API_BASE, MAX_MESSAGE_CHARS, TRUNCATION_MARKER, redact_token

REQUEST_TIMEOUT_SECONDS = 30

# A pasted message below this length is guidance-worthy chatter, not a report.
MIN_REPORT_CHARS = 200

# GitHub caps issue bodies at 65536 characters; leave room for the other fields.
MAX_ISSUE_PLAINTEXT_CHARS = 60_000

# The Bot API refuses files above 20 MB anyway; enforce locally too.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# GitHub writes this placeholder for empty form fields; parse_ingest_issue
# expects it, so the generated body mirrors it for fields we leave blank.
NO_RESPONSE = "_No response_"

_URL = re.compile(r"https?://[^\s<>()]+")

HELP_TEXT = (
    "So reichst du ein Paper oder einen Bericht ein:\n"
    "• Direkten PDF-Link senden (https://…/bericht.pdf)\n"
    "• PDF-Datei als Dokument anhängen\n"
    f"• Oder den Berichtstext als Nachricht einfügen (mind. {MIN_REPORT_CHARS} Zeichen)\n"
    "Daraus entsteht ein GitHub-Issue mit Label `ingest`; der Import erzeugt nur "
    "Kandidaten – aktiv wird nichts ohne menschliches Review.\n"
    "Befehle:\n"
    "/status – Bestand im Katalog\n"
    "/skills – Top-Skills nach Evidenz-Score\n"
    "/skill <suchbegriff> – ein Skill im Detail\n"
    "/lp21 – Lehrplan-21-Abdeckung im Überblick\n"
    "/dashboard – Link zum interaktiven Dashboard\n"
    "/hilfe – diese Hilfe"
)

GUIDANCE_TEXT = (
    "Das kann ich nicht automatisch verarbeiten: Ich brauche einen direkten "
    "PDF-Link, eine angehängte PDF-Datei oder den eingefügten Berichtstext "
    f"(mind. {MIN_REPORT_CHARS} Zeichen). Eine Landing-Page-URL oder DOI allein "
    "reicht nicht, weil dahinter meist kein frei ladbares PDF steht. /hilfe zeigt "
    "alle Wege."
)


class TelegramClient:
    """Minimal Bot API client (standard library only).

    Every call goes through :meth:`_request`, so tests exercise the intake
    logic by replacing that single method. Errors are raised as
    ``RuntimeError`` with the bot token redacted (urllib embeds the request
    URL — which contains the token — in its exceptions).
    """

    def __init__(self, token: str) -> None:
        self.token = token

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(params or {}).encode("utf-8")
        request = urllib.request.Request(
            f"{API_BASE}/bot{self.token}/{method}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"Telegram-API-Aufruf {method} fehlgeschlagen: {redact_token(str(exc), self.token)}"
            ) from exc
        if not body.get("ok"):
            raise RuntimeError(
                f"Telegram-API-Aufruf {method} abgelehnt: {body.get('description', body)}"
            )
        return body.get("result")

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": 0, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._request("getUpdates", params) or []

    def acknowledge(self, last_update_id: int) -> None:
        """Confirm all updates up to *last_update_id* (Telegram-side state)."""
        self._request("getUpdates", {"offset": last_update_id + 1, "timeout": 0, "limit": 1})

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to: int | None = None,
        url_button: tuple[str, str] | None = None,
    ) -> None:
        # Telegram rejects messages over its hard limit; truncating beats
        # dropping a long /skills or /lp21 answer entirely.
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[: MAX_MESSAGE_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to is not None:
            params["reply_parameters"] = {
                "message_id": reply_to,
                "allow_sending_without_reply": True,
            }
        if url_button is not None:
            label, url = url_button
            params["reply_markup"] = {"inline_keyboard": [[{"text": label, "url": url}]]}
        self._request("sendMessage", params)

    def download_document(self, file_id: str, dest: Path) -> None:
        """Fetch a chat attachment to *dest* via getFile + the file endpoint."""
        info = self._request("getFile", {"file_id": file_id}) or {}
        file_path = info.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram lieferte keinen Dateipfad für den Anhang.")
        url = f"{API_BASE}/file/bot{self.token}/{file_path}"
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                data = response.read(MAX_DOWNLOAD_BYTES + 1)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            raise RuntimeError(
                f"Anhang-Download fehlgeschlagen: {redact_token(str(exc), self.token)}"
            ) from exc
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise RuntimeError(
                f"Anhang größer als das Limit von {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB."
            )
        dest.write_bytes(data)


def allowed_chat_ids() -> set[str]:
    """Chat IDs allowed to use the intake, from the environment.

    ``TELEGRAM_ALLOWED_CHAT_IDS`` (comma-separated) wins; otherwise the single
    notification chat ``TELEGRAM_CHAT_ID`` doubles as the allowlist, so the
    minimal setup (one bot, one chat) needs no extra secret.
    """
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip() or os.environ.get(
        "TELEGRAM_CHAT_ID", ""
    )
    return {part.strip() for part in raw.split(",") if part.strip()}


def find_url(text: str) -> str | None:
    """First http(s) URL in *text*, stripped of trailing punctuation, or None."""
    match = _URL.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?»'\"")


def is_pdf_url(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".pdf")


def is_pdf_document(document: dict[str, Any]) -> bool:
    if document.get("mime_type") == "application/pdf":
        return True
    return str(document.get("file_name", "")).lower().endswith(".pdf")


def classify_message(message: dict[str, Any]) -> dict[str, Any]:
    """Map a Telegram *message* to an intake action.

    Returns ``{"kind": ...}`` with kind one of ``command`` (plus ``name``),
    ``submission`` (plus ``url``/``text``/``document``), ``guidance`` (the
    sender tried to submit something unusable, e.g. a landing-page URL), or
    ``ignore`` (empty/unsupported content such as photos or stickers).
    """
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/"):
        head, _, rest = text.partition(" ")
        name = head.split("@", 1)[0].lstrip("/").lower()
        return {"kind": "command", "name": name, "args": rest.strip()}

    document = message.get("document")
    pdf_document = document if document and is_pdf_document(document) else None
    url = find_url(text)
    # The URL itself is not report text; judge the remaining prose.
    prose = text.replace(url, "").strip() if url else text
    plaintext = prose if len(prose) >= MIN_REPORT_CHARS else ""

    if pdf_document or plaintext or (url and is_pdf_url(url)):
        return {
            "kind": "submission",
            "document": pdf_document,
            "url": url or "",
            "text": plaintext,
        }
    if url or text:
        # A bare landing-page URL/DOI or a short note: guaranteed to skip in
        # parse_ingest_issue, so answer with guidance instead of filing noise.
        return {"kind": "guidance"}
    return {"kind": "ignore"}


def build_issue_title(submission: dict[str, Any]) -> str:
    """Derive the ``[ingest] …`` issue title from the submission content."""
    document = submission.get("document")
    if document and document.get("file_name"):
        hint = str(document["file_name"])
    elif submission.get("url"):
        parsed = urllib.parse.urlsplit(submission["url"])
        hint = Path(parsed.path).name or parsed.hostname or submission["url"]
    else:
        hint = submission.get("text", "").split("\n", 1)[0]
    hint = hint.strip() or "Einreichung via Telegram"
    if len(hint) > 80:
        hint = hint[:77] + "…"
    return f"[ingest] {hint}"


def build_issue_body(url: str = "", plaintext: str = "", provenance: str = "") -> str:
    """Render an issue body with the exact "Bericht einreichen" form headings.

    ``parse_ingest_issue.parse_sections`` keys off these ``### <label>``
    headings (unknown headings like ``Herkunft`` are ignored there), so a
    Telegram submission flows through the identical import path as the form.
    """
    if len(plaintext) > MAX_ISSUE_PLAINTEXT_CHARS:
        plaintext = plaintext[:MAX_ISSUE_PLAINTEXT_CHARS] + "\n… [für das Issue gekürzt]"
    sections = [
        f"### Quellen-URL\n\n{url.strip() or NO_RESPONSE}",
        f"### Herausgeber\n\n{NO_RESPONSE}",
        f"### Erscheinungsjahr\n\n{NO_RESPONSE}",
        f"### Berichtstext (einfügen)\n\n{plaintext.strip() or NO_RESPONSE}",
        f"### PDF anhängen\n\n{NO_RESPONSE}",
    ]
    if provenance.strip():
        sections.append(f"### Herkunft\n\n{provenance.strip()}")
    return "\n\n".join(sections)


def github_tokens() -> tuple[str, bool]:
    """Return ``(token, triggers_workflows)`` for issue creation.

    Issues created with the workflow's own ``GITHUB_TOKEN`` do not fire
    ``issues``-triggered workflows (GitHub's recursion guard), so the import
    would wait for a maintainer to re-set a label. A dedicated
    ``TELEGRAM_GITHUB_TOKEN`` (fine-grained PAT, issues read/write) makes the
    import start automatically; the reply tells the sender which case applies.
    """
    pat = os.environ.get("TELEGRAM_GITHUB_TOKEN", "").strip()
    if pat:
        return pat, True
    return os.environ.get("GITHUB_TOKEN", "").strip(), False


def create_issue(repo: str, token: str, title: str, body: str, labels: list[str]) -> str:
    """Create the intake issue via the GitHub REST API; returns its html_url."""
    payload = json.dumps({"title": title, "body": body, "labels": labels}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "future-skills-evidence-graph-telegram-intake",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            created = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"GitHub-Issue konnte nicht erstellt werden ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"GitHub-Issue konnte nicht erstellt werden: {exc}") from exc
    return created.get("html_url", "")


def status_text() -> str:
    """Catalog counts by record status, for the ``/status`` command."""
    lines = ["Bestand im Katalog:"]
    for kind, label in (("sources", "Quellen"), ("claims", "Claims"), ("skills", "Skills")):
        records = load_records(kind)
        by_status: dict[str, int] = {}
        for record in records:
            status = record.get("status", "unbekannt")
            by_status[status] = by_status.get(status, 0) + 1
        detail = ", ".join(f"{count} {status}" for status, count in sorted(by_status.items()))
        lines.append(f"• {label}: {len(records)} ({detail})" if detail else f"• {label}: 0")
    return "\n".join(lines)


# --- Read-only dashboard queries -------------------------------------------
#
# These render the SAME versioned records the dashboard is built from
# (build_site.py reads data/ too), as plain chat text. They read only; the
# interactive, always-current view stays the dashboard itself (/dashboard).

STATUS_DE = {"active": "aktiv", "candidate": "Kandidat", "deprecated": "veraltet"}
AUDIENCE_DE = {"learner": "Lernende", "educator": "Lehrende"}
TREND_DE = {"growing": "wachsend", "stable": "stabil", "declining": "rückläufig"}
SKILLS_LIMIT = 12


def display_coverage_label(label: str) -> str:
    """The stored ASCII label, displayed with its umlaut (like the dashboard)."""
    return label.replace("Zukunftsluecke", "Zukunftslücke")


def skill_display_name(skill: dict[str, Any]) -> str:
    """German name first, English fallback — the dashboard's display rule."""
    return (skill.get("name_de") or skill.get("name") or skill.get("id", "?")).strip()


def dashboard_url() -> str:
    """The published dashboard URL, or empty when it cannot be derived.

    ``DASHBOARD_URL`` overrides (e.g. a custom domain); otherwise the standard
    GitHub-Pages URL is derived from ``GITHUB_REPOSITORY`` — the deploy
    workflow publishes ``public/`` as the site root.
    """
    override = os.environ.get("DASHBOARD_URL", "").strip()
    if override:
        return override
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return ""


def skills_text() -> str:
    """Top skills by evidence score, for the ``/skills`` command."""
    skills = [s for s in load_records("skills") if s.get("status") != "deprecated"]
    if not skills:
        return "Noch keine Skills im Katalog."
    skills.sort(key=lambda s: s.get("evidence_score") or 0.0, reverse=True)
    lines = [f"Top-Skills nach Evidenz-Score ({min(len(skills), SKILLS_LIMIT)} von {len(skills)}):"]
    for rank, skill in enumerate(skills[:SKILLS_LIMIT], start=1):
        status = STATUS_DE.get(skill.get("status", ""), skill.get("status", "?"))
        claims = len(skill.get("supporting_claim_ids") or [])
        lines.append(
            f"{rank}. {skill_display_name(skill)} – Score "
            f"{skill.get('evidence_score') or 0.0:.2f} · {status} · {claims} Claims"
        )
    lines.append("Details: /skill <suchbegriff> · interaktiv: /dashboard")
    return "\n".join(lines)


def matching_skills(query: str) -> list[dict[str, Any]]:
    """Skills whose name (de/en), id, or short label contains *query*."""
    needle = query.casefold()
    matches = []
    for skill in load_records("skills"):
        # The id is matched without its uniform "skill-" prefix — otherwise a
        # query like "KI" would match EVERY skill (s-KI-ll).
        haystack = " ".join(
            (
                str(skill.get("name", "")),
                str(skill.get("name_de", "")),
                str(skill.get("short_label", "")),
                str(skill.get("id", "")).removeprefix("skill-"),
            )
        ).casefold()
        if needle in haystack:
            matches.append(skill)
    # An exact name wins over substring hits: "/skill KI-Kompetenz" (typed
    # straight from the /skills list) must not be "ambiguous" just because
    # other skills contain that name as a substring.
    exact = [
        skill
        for skill in matches
        if needle
        in {
            str(skill.get("name", "")).casefold(),
            str(skill.get("name_de", "")).casefold(),
            str(skill.get("short_label", "")).casefold(),
            str(skill.get("id", "")).removeprefix("skill-").casefold(),
        }
    ]
    return exact if exact else matches


def skill_detail_text(query: str) -> str:
    """One skill in detail, for the ``/skill <term>`` command."""
    query = query.strip()
    if not query:
        return "Bitte einen Suchbegriff angeben, z. B. `/skill KI`. Die Liste zeigt /skills."
    matches = matching_skills(query)
    if not matches:
        return f"Kein Skill passt zu „{query}“. Die Liste zeigt /skills."
    if len(matches) > 1:
        names = "\n".join(f"• {skill_display_name(s)}" for s in matches[:10])
        return f"Mehrere Treffer für „{query}“ – bitte eingrenzen:\n{names}"

    skill = matches[0]
    name = skill_display_name(skill)
    english = (skill.get("name") or "").strip()
    if english and english != name:
        name = f"{name} ({english})"
    status = STATUS_DE.get(skill.get("status", ""), skill.get("status", "?"))
    facts = [f"Status: {status}", f"Evidenz-Score: {skill.get('evidence_score') or 0.0:.2f}"]
    if skill.get("age_range"):
        facts.append(f"Alter: {skill['age_range']}")
    facts.append(f"Perspektive: {AUDIENCE_DE.get(skill.get('audience', 'learner'), skill.get('audience'))}")
    if skill.get("trend"):
        facts.append(f"Trend: {TREND_DE.get(skill['trend'], skill['trend'])}")

    lines = [name, " · ".join(facts)]
    definition = (skill.get("definition_de") or skill.get("definition") or "").strip()
    if definition:
        lines.append(definition)
    supporting = len(skill.get("supporting_claim_ids") or [])
    contradicting = len(skill.get("contradicting_claim_ids") or [])
    lines.append(f"Evidenz: {supporting} unterstützende, {contradicting} widersprechende Claims")

    mappings = [m for m in load_records("frameworks") if m.get("skill_id") == skill.get("id")]
    for mapping in mappings:
        entry = f"• {mapping.get('framework', '?')}: {mapping.get('competency', '?')}"
        if mapping.get("coverage_score") is not None:
            label = display_coverage_label(mapping.get("coverage_label", ""))
            cycles = ", ".join(mapping.get("cycles") or [])
            entry += f" — Abdeckung {mapping['coverage_score']}/3 ({label}"
            entry += f"; {cycles})" if cycles else ")"
        lines.append(entry)
    return "\n".join(lines)


def lp21_text() -> str:
    """Lehrplan 21 coverage summary, for the ``/lp21`` command."""
    mappings = [
        m
        for m in load_records("frameworks")
        if m.get("framework") == "Lehrplan 21" and m.get("coverage_score") is not None
    ]
    if not mappings:
        return "Noch keine Lehrplan-21-Abdeckungswerte im Katalog."
    names = {s.get("id"): skill_display_name(s) for s in load_records("skills")}
    average = sum(m["coverage_score"] for m in mappings) / len(mappings)
    # Ascending: the dashboard's headline question is where the gaps are.
    mappings.sort(key=lambda m: m["coverage_score"])
    lines = [f"Lehrplan-21-Abdeckung (Ø {average:.1f}/3, kleinste zuerst):"]
    for mapping in mappings:
        label = display_coverage_label(mapping.get("coverage_label", ""))
        lines.append(
            f"• {names.get(mapping.get('skill_id'), mapping.get('skill_id', '?'))}: "
            f"{mapping['coverage_score']}/3 ({label})"
        )
    lines.append(
        "Die Werte sind redaktionelle Einzelurteile (Methodik: "
        "docs/lehrplan21-coverage-methodik.md). Radar & Details: /dashboard"
    )
    return "\n".join(lines)


def handle_submission(
    submission: dict[str, Any], client: TelegramClient, repo: str, workdir: Path
) -> str:
    """Turn a *submission* into an intake issue; returns the Telegram reply."""
    url = submission.get("url", "")
    plaintext = submission.get("text", "")
    document = submission.get("document")

    if document:
        pdf_path = workdir / "telegram-report.pdf"
        client.download_document(document["file_id"], pdf_path)
        try:
            extracted = extract_text(pdf_path)
        except SystemExit as exc:  # extract_text: missing optional pypdf
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:  # a corrupt PDF must become a chat reply
            raise RuntimeError(f"PDF konnte nicht gelesen werden: {exc}") from exc
        if not extracted.strip():
            return (
                "Aus dem angehängten PDF ließ sich kein Text extrahieren (evtl. ein "
                "gescanntes PDF ohne Textebene). Bitte den Text als Nachricht einfügen."
            )
        # The extracted text becomes the pasted-text field: the Telegram file
        # URL is token-bearing and short-lived, so it must never reach GitHub.
        plaintext = extracted

    token, triggers_workflows = github_tokens()
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY oder GitHub-Token fehlt im Workflow-Umfeld.")

    body = build_issue_body(
        url=url,
        plaintext=plaintext,
        provenance="Eingereicht über den Telegram-Intake (autorisierter Chat).",
    )
    # The chat allowlist already authenticates the sender, so the issue gets
    # the same approval a maintainer would grant an external form submission.
    issue_url = create_issue(
        repo, token, build_issue_title(submission), body, ["ingest", "ingest-approved"]
    )
    reply = f"Danke! Einreichung erfasst: {issue_url}"
    if triggers_workflows:
        reply += "\nDer Import startet automatisch; das Ergebnis wird im Issue kommentiert."
    else:
        reply += (
            "\nHinweis: Der automatische Import startet erst, wenn ein Maintainer im "
            "Issue das Label `ingest-approved` neu setzt (kein TELEGRAM_GITHUB_TOKEN "
            "hinterlegt)."
        )
    reply += "\nEs entstehen nur Kandidaten – aktiv wird nichts ohne Review."
    return reply


def process_update(
    update: dict[str, Any], client: TelegramClient, allowed: set[str], repo: str, workdir: Path
) -> str:
    """Process one update; returns a log line. Replies happen inside."""
    message = update.get("message")
    if not message:
        return "übersprungen (kein message-Update)"
    chat_id = message.get("chat", {}).get("id")
    if str(chat_id) not in allowed:
        # Unknown chats are ignored WITHOUT a reply: answering would turn the
        # bot into a probe/spam target; authorized chats are configured, not
        # self-served.
        return f"ignoriert (Chat {chat_id} nicht autorisiert)"

    action = classify_message(message)
    message_id = message.get("message_id")
    if action["kind"] == "command":
        name = action["name"]
        queries = {
            "status": lambda: status_text(),
            "skills": lambda: skills_text(),
            "skill": lambda: skill_detail_text(action.get("args", "")),
            "lp21": lambda: lp21_text(),
        }
        if name in queries:
            try:
                reply = queries[name]()
            except Exception as exc:  # a data problem must become a chat reply
                reply = f"Abfrage fehlgeschlagen: {exc}"
            client.send_message(chat_id, reply, reply_to=message_id)
            return f"Befehl /{name} beantwortet"
        if name == "dashboard":
            url = dashboard_url()
            if url:
                client.send_message(
                    chat_id,
                    f"Das interaktive Dashboard (Skills, Evidenz-Scores, "
                    f"Lehrplan-21-Radar):\n{url}",
                    reply_to=message_id,
                    url_button=("Dashboard öffnen", url),
                )
            else:
                client.send_message(
                    chat_id,
                    "Keine Dashboard-URL konfiguriert (DASHBOARD_URL oder "
                    "GITHUB_REPOSITORY fehlt im Workflow-Umfeld).",
                    reply_to=message_id,
                )
            return "Befehl /dashboard beantwortet"
        client.send_message(chat_id, HELP_TEXT, reply_to=message_id)
        return f"Befehl /{name} mit Hilfe beantwortet"
    if action["kind"] == "guidance":
        client.send_message(chat_id, GUIDANCE_TEXT, reply_to=message_id)
        return "Hinweis gesendet (kein verwertbarer Inhalt)"
    if action["kind"] == "ignore":
        return "übersprungen (kein Text/PDF-Inhalt)"

    try:
        reply = handle_submission(action, client, repo, workdir)
    except RuntimeError as exc:
        client.send_message(
            chat_id,
            f"Die Einreichung hat leider nicht geklappt: {exc}\nBitte erneut senden.",
            reply_to=message_id,
        )
        return f"Einreichung fehlgeschlagen: {exc}"
    client.send_message(chat_id, reply, reply_to=message_id)
    return "Einreichung als Issue erfasst"


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Telegram nicht konfiguriert (TELEGRAM_BOT_TOKEN) – Intake übersprungen.")
        return 0
    allowed = allowed_chat_ids()
    if not allowed:
        print("Keine erlaubten Chats (TELEGRAM_CHAT_ID/TELEGRAM_ALLOWED_CHAT_IDS) – Intake übersprungen.")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    client = TelegramClient(token)
    updates = client.get_updates()
    if not updates:
        print("Keine neuen Nachrichten.")
        return 0

    # Acknowledge first: a crash below must not re-file the same submissions
    # as duplicate issues on every poll (see module docstring).
    client.acknowledge(max(update["update_id"] for update in updates))

    failures = 0
    with tempfile.TemporaryDirectory(prefix="telegram-intake-") as tmp:
        workdir = Path(tmp)
        for update in updates:
            try:
                outcome = process_update(update, client, allowed, repo, workdir)
            except RuntimeError as exc:
                failures += 1
                outcome = f"FEHLER: {exc}"
            print(f"Update {update.get('update_id')}: {outcome}")
    print(f"{len(updates)} Update(s) verarbeitet, {failures} Fehler.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
