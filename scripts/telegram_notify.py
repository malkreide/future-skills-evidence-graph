"""Optional Telegram notifications for pipeline events (standard library only).

The project stays GitHub-first: Telegram is a *mirror*, never a control plane.
Workflows call this script after notable events (weekly research run, report
import, new issues, failures) and it sends one short message to the configured
chat via the Telegram Bot API. It must NEVER fail the calling workflow:

- Without ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` it is a silent no-op
  (exit 0), so forks and repos without a bot run all workflows unchanged.
- Any HTTP or API error is printed as a warning and the exit code stays 0 —
  a broken notification must not break the pipeline it reports on.

    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \
        python scripts/telegram_notify.py --title "Titel" --text "Nachricht"

Setup and the full integration story are in docs/telegram-integration.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.telegram.org"

# Telegram rejects messages longer than 4096 characters; truncate instead of
# failing so a long failure log still produces a (shortened) notification.
MAX_MESSAGE_CHARS = 4096
TRUNCATION_MARKER = "\n… [gekürzt]"

REQUEST_TIMEOUT_SECONDS = 20


def telegram_config() -> tuple[str, str] | None:
    """Return ``(bot_token, chat_id)`` from the environment, or None.

    Both values must be present; a half-configured environment behaves like an
    unconfigured one (no-op) rather than erroring, so a missing secret in a
    fork never breaks CI.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def format_message(title: str, lines: list[str] | tuple[str, ...] = (), text: str = "") -> str:
    """Compose a plain-text message from *title*, bullet *lines*, and *text*.

    Plain text (no Markdown/HTML parse mode) so titles and issue names with
    ``*_[`` characters can never break rendering or inject formatting. The
    result is truncated to Telegram's message limit.
    """
    parts = [title.strip()] if title.strip() else []
    parts.extend(f"• {line.strip()}" for line in lines if line.strip())
    if text.strip():
        parts.append(text.strip())
    message = "\n".join(parts)
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return message


def redact_token(text: str, token: str) -> str:
    """Strip the bot *token* out of *text* (URLs in urllib errors contain it)."""
    return text.replace(token, "***") if token else text


def send_message(token: str, chat_id: str, text: str) -> bool:
    """Send *text* to *chat_id* via the Bot API; True on success.

    Failures are printed (token-redacted) and reported as False, never raised:
    callers treat notifications as best-effort.
    """
    if not text.strip():
        return False
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            # Link previews would balloon every candidate-PR notification.
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        print(
            f"WARNUNG: Telegram-Nachricht nicht gesendet: {redact_token(str(exc), token)}",
            file=sys.stderr,
        )
        return False
    if not body.get("ok"):
        print(
            f"WARNUNG: Telegram-API lehnte die Nachricht ab: {body.get('description', body)}",
            file=sys.stderr,
        )
        return False
    return True


def notify(title: str, lines: list[str] | tuple[str, ...] = (), text: str = "") -> bool:
    """Send a formatted notification if Telegram is configured; True when sent."""
    config = telegram_config()
    if config is None:
        print("Telegram nicht konfiguriert (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) – übersprungen.")
        return False
    token, chat_id = config
    return send_message(token, chat_id, format_message(title, lines, text))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send an optional Telegram notification (no-op without configuration)."
    )
    parser.add_argument("--title", default="", help="First line of the message.")
    parser.add_argument(
        "--line",
        action="append",
        default=[],
        help="Bullet line, repeatable; empty values are dropped.",
    )
    parser.add_argument("--text", default="", help="Free-text paragraph after the bullets.")
    args = parser.parse_args()

    if not (args.title.strip() or args.text.strip() or any(l.strip() for l in args.line)):
        print("Leere Nachricht – nichts gesendet.")
        return 0

    if notify(args.title, args.line, args.text):
        print("Telegram-Benachrichtigung gesendet.")
    # A failed or skipped notification must never fail the calling workflow.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
