"""Run reviewer slash-commands from a pull-request comment.

The review workflow (`promote_candidate.py`) required a local clone and Python
setup, which excluded GitHub-web-only reviewers. This bridge lets a maintainer
review from the browser: a comment on the candidate pull request such as

    /promote-source src-abc --year 2024
    /claim clm-xyz --context "..." --age-range "12-18" --outcome "..." \
        --evidence-type systematic_review --evidence-strength moderate --supports skill-ai-literacy
    /reject clm-uvw

is parsed here and executed through the SAME `promote_candidate.py` used
locally — every gate (placeholder blockade, reviewed-evidence invariant,
re-validation, score recompute) applies unchanged; this file is transport, not
policy. Lines copied verbatim from the triage worksheet
(`python scripts/promote_candidate.py ...`) are accepted too.

Security model (enforced by the calling workflow + this parser):

- Only comments from OWNER/MEMBER/COLLABORATOR reach this script.
- The body arrives via the COMMENT_BODY environment variable, never through
  shell interpolation.
- The first token must be an allow-listed promote_candidate subcommand and the
  argument vector is passed as an argv list (no shell). promote_candidate
  takes no filesystem-path arguments, so a hostile flag cannot redirect writes.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

from common import ROOT

# Exactly promote_candidate.py's subcommands: transport stays 1:1 with the CLI.
ALLOWED_SUBCOMMANDS = (
    "claim",
    "skill",
    "reject",
    "reject-source",
    "promote-source",
    "attach-claim",
    "reopen",
)

WORKSHEET_PREFIX = "python scripts/promote_candidate.py"


def parse_commands(body: str) -> tuple[list[list[str]], list[str]]:
    """Extract ``promote_candidate`` argv lists from a comment *body*.

    Returns ``(commands, problems)``. Recognized forms, one per line:
    ``/<subcommand> args...`` and the worksheet's
    ``python scripts/promote_candidate.py <subcommand> args...``. Anything
    else is prose and ignored; a recognized-looking line that fails to parse
    (unknown subcommand, unbalanced quotes) becomes a problem message instead
    of being silently dropped.
    """
    commands: list[list[str]] = []
    problems: list[str] = []
    for raw in body.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        # Fenced code blocks wrap worksheet commands; strip the fence markers.
        if line.startswith("`") and line.endswith("`"):
            line = line.strip("`").strip()
        if line.startswith(WORKSHEET_PREFIX):
            line = "/" + line[len(WORKSHEET_PREFIX) :].strip()
        if not line.startswith("/"):
            continue
        head = line[1:].split(None, 1)[0] if line[1:].split() else ""
        if head not in ALLOWED_SUBCOMMANDS:
            # Slash-prefixed but not ours (e.g. "/cc @user") — only report the
            # near-misses that were clearly meant for us.
            if head in {"promote", "promote-claim", "promote-skill"}:
                problems.append(
                    f"Unbekanntes Kommando `/{head}` – gemeint war wohl eines von: "
                    + ", ".join(f"`/{name}`" for name in ALLOWED_SUBCOMMANDS)
                )
            continue
        try:
            tokens = shlex.split(line[1:])
        except ValueError as exc:
            problems.append(f"Zeile nicht parsebar ({exc}): `{line}`")
            continue
        commands.append(tokens)
    return commands, problems


def run_command(tokens: list[str]) -> tuple[bool, str]:
    """Execute one promote_candidate command; returns (ok, transcript)."""
    argv = [sys.executable, str(ROOT / "scripts" / "promote_candidate.py"), *tokens]
    result = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    output = (result.stdout + result.stderr).strip()
    shown = " ".join(tokens)
    if result.returncode == 0:
        return True, f"✅ `/{shown}`\n{output}".strip()
    return False, f"❌ `/{shown}` (exit {result.returncode})\n{output}".strip()


def write_output(github_output: str | None, **fields: str) -> None:
    for key, value in fields.items():
        print(f"{key}={value}" if "\n" not in value else f"{key}=<<multiline>>\n{value}")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as handle:
                if "\n" in value:
                    handle.write(f"{key}<<__EOF__\n{value}\n__EOF__\n")
                else:
                    handle.write(f"{key}={value}\n")


def main() -> int:
    body = os.environ.get("COMMENT_BODY", "")
    github_output = os.environ.get("GITHUB_OUTPUT")

    commands, problems = parse_commands(body)
    if not commands and not problems:
        write_output(github_output, status="skip", summary="Keine Review-Kommandos im Kommentar gefunden.")
        return 0

    transcripts: list[str] = list(problems)
    failures = len(problems)
    for tokens in commands:
        ok, transcript = run_command(tokens)
        transcripts.append(transcript)
        if not ok:
            failures += 1

    summary = "\n\n".join(transcripts)
    write_output(
        github_output,
        status="ran",
        failures=str(failures),
        summary=summary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
