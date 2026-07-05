"""LLM importer for API-less report sources (OECD / WEF / UNESCO).

Unlike the metadata APIs (OpenAlex, Crossref, ...), the big policy bodies
publish their evidence as prose PDFs with no structured query endpoint. This
importer turns the *already-extracted plaintext* of such a report into a
candidate source plus candidate finding-claims, using ``ai_provider.complete``
to propose the metadata and the findings.

The PDF -> plaintext extraction is deliberately OUT of this path: the importer
takes plaintext on stdin/file so it stays deterministic, testable and free of a
binary PDF dependency. A human still chooses which report to feed it and still
reviews every candidate; nothing here is ever auto-activated.

Two guard rails keep the LLM honest, mirroring the rest of the project:

- **Hallucination guard.** Every proposed claim ``statement`` must occur as a
  *verbatim passage* in the report plaintext (whitespace-normalized). A
  statement that is paraphrased, summarized or invented is discarded, and the
  ``text_anchor`` quotes the exact passage that was found. No anchor, no claim.
- **Candidate-only, low evidence.** Every source and claim is written with
  ``status='candidate'`` and ``evidence_strength='low'``; the LLM's richer
  guesses (outcome, context, age range, strength) live ONLY under the
  non-binding ``assist`` block with provenance, exactly like extract_claims.py.

With ``AI_PROVIDER=none`` (the default) the whole importer is a no-op: it
proposes nothing and writes no files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import ai_provider
from common import (
    AGE_SCALE,
    ROOT,
    TODAY,
    append_candidate_sources,
    append_unique_records,
    claim_statement_key,
    filter_new_claims,
    filter_new_sources,
    filter_relevant_sources,
    load_json,
    score_relevance,
    slugify,
)
from extract_claims import (
    AGE_RANGE_PLACEHOLDER,
    CONTEXT_PLACEHOLDER_SUFFIX,
    DEFAULT_EVIDENCE_TYPE,
    EVIDENCE_TYPE_BY_SOURCE_TYPE,
    OUTCOME_PLACEHOLDER,
)


# Versioned so every proposed source/claim carries its prompt version in
# provenance, like the claim pre-fill in extract_claims.py.
REPORT_PROMPT_VERSION = "report-import-v1"

# A proposed claim statement shorter than this is dropped as too thin to be an
# evidence statement, matching extract_claims.MIN_SENTENCE_LENGTH.
MIN_PASSAGE_LENGTH = 40

# Hard cap on how much report text is sent to the model. The issue intake
# accepts PDFs up to 25 MB, whose extracted text would otherwise reach the API
# in full — an unbounded, submitter-controlled input-token bill. Only the
# PROMPT is capped: the verbatim guard still checks statements against the
# complete text, so nothing about candidate integrity changes. Overridable for
# operators via MAX_REPORT_CHARS.
MAX_REPORT_CHARS = int(os.environ.get("MAX_REPORT_CHARS", 150_000))

# Report source types the model may pick from; anything else (or null) falls
# back to policy_report, the dominant case for OECD / WEF / UNESCO output.
REPORT_SOURCE_TYPES = (
    "policy_report",
    "framework",
    "working_paper",
    "conceptual_review",
    "web_resource",
)
DEFAULT_SOURCE_TYPE = "policy_report"

# Strict JSON Schema for the proposal (enforced via output_config.format). The
# model proposes source metadata plus a list of verbatim findings; every richer
# review field is optional (null when the text does not support it).
REPORT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "year", "source_type", "authors", "summary", "findings"],
    "properties": {
        "title": {"type": ["string", "null"]},
        "year": {"type": ["integer", "null"]},
        "source_type": {"enum": [*REPORT_SOURCE_TYPES, None]},
        "authors": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": ["string", "null"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["statement", "outcome", "context", "age_range", "evidence_strength"],
                "properties": {
                    "statement": {"type": "string"},
                    "outcome": {"type": ["string", "null"]},
                    "context": {"type": ["string", "null"]},
                    "age_range": {"type": ["string", "null"]},
                    "evidence_strength": {"enum": ["low", "moderate", "high", None]},
                },
            },
        },
    },
}

SUGGESTION_FIELDS = ("age_range", "outcome", "context", "evidence_strength")

# In-feature prompt, version 1. Mirrors the claim pre-fill prompt's contract:
# the model invents nothing, returns null for anything the text does not give,
# and — crucially — every finding statement must be an EXACT quote from the
# report so the importer can verify it verbatim.
REPORT_PROMPT_TEMPLATE = '''System: Du extrahierst strukturierte Evidenz aus dem Volltext eines \
bildungspolitischen Berichts (z. B. OECD, WEF, UNESCO). Du erfindest nichts. \
Wenn der Text eine Angabe nicht hergibt, gib fuer das Feld null zurueck. Jede \
Befund-Aussage (statement) MUSS ein woertliches, unveraendertes Zitat aus dem \
Berichtstext sein - keine Paraphrase, keine Zusammenfassung, keine \
Umformulierung. Antworte ausschliesslich als JSON nach dem vorgegebenen Schema.

User:
Quellen-URL: {url}

Berichts-Volltext:
"""{text}"""

Liefere:
- title: Titel des Berichts, oder null.
- year: Erscheinungsjahr (vierstellig), oder null.
- source_type: einer von {source_types}, oder null (im Zweifel policy_report).
- authors: herausgebende Organisation(en)/Autor(en) als Liste, sonst leere Liste.
- summary: 1-2 Saetze, worum es im Bericht geht (neutral), oder null.
- findings: Liste der wichtigsten Befunde zu Zukunftskompetenzen/Bildung. Pro \
Befund:
  - statement: WOERTLICHES Zitat eines Befund-Satzes aus dem Text (unveraendert).
  - outcome: 1 Satz, welches Lernergebnis/Effekt berichtet wird, oder null.
  - context: 1 Satz zum Setting (Land, Schulstufe, Interventionsart), oder null.
  - age_range: Tatsaechlich berichteter Altersbereich der Lernenden als "min-max" \
auf der {age_scale}-Skala (fruehe Kindheit und Kindergarten / Lehrplan-21-Zyklus 1 \
eingeschlossen), oder null. Ueber {age_scale} hinausreichende Bereiche auf \
{age_scale} beschneiden.
  - evidence_strength: eine von {{low, moderate, high}}, konservativ; im Zweifel low.'''


def truncate_report_text(text: str, limit: int | None = None) -> str:
    """Return *text* capped at *limit* characters for the LLM prompt.

    The cut lands on the last sentence/paragraph boundary inside the limit (so
    the model never sees a half sentence it might quote), falling back to a
    hard cut when no boundary exists. Text at or under the limit is returned
    unchanged. *limit* defaults to the module's MAX_REPORT_CHARS at call time,
    so an operator override stays effective.
    """
    if limit is None:
        limit = MAX_REPORT_CHARS
    if len(text) <= limit:
        return text
    head = text[:limit]
    boundary = max(head.rfind(". "), head.rfind(".\n"), head.rfind("\n\n"))
    if boundary > 0:
        head = head[: boundary + 1]
    return head


def report_prompt(text: str, url: str) -> str:
    """Render the versioned report-import prompt for *text*/*url*."""
    return REPORT_PROMPT_TEMPLATE.format(
        url=url.strip(),
        text=text.strip(),
        source_types=", ".join(REPORT_SOURCE_TYPES),
        age_scale=AGE_SCALE,
    )


def propose_report(text: str, url: str) -> dict[str, Any] | None:
    """Ask the LLM to propose source metadata + findings, or None when off.

    Returns None when the provider is ``none`` (default), on a refusal, on any
    failure, or on a cache miss — so a missing proposal is indistinguishable
    from AI being off and the importer becomes a no-op.
    """
    # Off by default: skip even building the prompt so the path is fully inert.
    if ai_provider.ai_provider() == "none":
        return None
    # Cost cap: only the prompt is truncated; the verbatim guard downstream
    # still verifies every statement against the FULL report text.
    prompt_text = truncate_report_text(text)
    if len(prompt_text) < len(text):
        print(
            f"Report text truncated for the LLM prompt: {len(text)} -> "
            f"{len(prompt_text)} chars (cap {MAX_REPORT_CHARS}); findings beyond "
            "the cap are not extracted automatically."
        )
    result = ai_provider.complete(report_prompt(prompt_text, url), schema=REPORT_OUTPUT_SCHEMA)
    if not isinstance(result, dict):
        return None
    return result


# Typographic noise from PDF extraction that carries no semantic difference and
# must not defeat a verbatim match: curly quotes, the various dashes, and the
# non-breaking space are mapped to their plain ASCII equivalents. Applied
# SYMMETRICALLY to both the statement and the report text, so paraphrases (which
# differ in actual words) still fail — only typography is neutralized.
_CHAR_MAP = {
    **{ord(c): "'" for c in "‘’‚‛′"},  # ' ' ‚ ‛ ′
    **{ord(c): '"' for c in "“”„‟″"},  # " " „ ‟ ″
    **{ord(c): "-" for c in "‐‑‒–—―−"},  # ‐ ‑ ‒ – — ― −
    0x00A0: " ",  # non-breaking space
}

# Intra-word hyphenation at a line break ("curricu-\nlum" -> "curriculum") is a
# PDF artifact and is rejoined before whitespace is collapsed. The same is done
# for the Unicode soft hyphen (U+00AD), the explicit hyphenation point. This is
# deliberately conservative: it only joins across a newline, so a genuine
# compound that happens to wrap ("decision-\nmaking") is also joined — at worst
# that rejects a real quote, never invents one.
_LINEBREAK_HYPHEN = re.compile(r"­\s*|-\s*\n\s*")


def normalize_for_match(text: str) -> str:
    """Normalize *text* for verbatim matching, neutralizing PDF typography.

    NFKC folds compatibility forms (ligatures like ``ﬁ`` -> ``fi``, full-width
    characters); curly quotes/dashes/nbsp are mapped to ASCII; hyphenated line
    breaks are rejoined; whitespace is collapsed. Wording and case are preserved,
    so the result is still a faithful, verbatim form of the passage.
    """
    text = unicodedata.normalize("NFKC", str(text))
    text = text.translate(_CHAR_MAP)
    text = _LINEBREAK_HYPHEN.sub("", text)
    return " ".join(text.split())


def verbatim_passage(statement: str, text: str) -> str | None:
    """Return the normalized *statement* iff it is a verbatim quote of *text*.

    Matching runs on the typography-normalized forms (see normalize_for_match):
    PDF line wraps, curly quotes, dashes, ligatures and hyphenation are
    neutralized, but the actual words and their order must match exactly. A
    paraphrased, summarized or invented statement does not occur literally and
    returns None — the hallucination guard. Statements below MIN_PASSAGE_LENGTH
    are rejected as too thin to be evidence.
    """
    normalized_statement = normalize_for_match(statement)
    if len(normalized_statement) < MIN_PASSAGE_LENGTH:
        return None
    if normalized_statement in normalize_for_match(text):
        return normalized_statement
    return None


def _resolve_year(proposal: dict[str, Any], year_override: int | None) -> int | None:
    """Pick a schema-valid publication year, preferring the operator override."""
    for candidate in (year_override, proposal.get("year")):
        if isinstance(candidate, int) and 1900 <= candidate <= 2100:
            return candidate
    return None


def _resolve_source_type(proposal: dict[str, Any]) -> str:
    value = proposal.get("source_type")
    return value if value in REPORT_SOURCE_TYPES else DEFAULT_SOURCE_TYPE


def build_source(
    proposal: dict[str, Any],
    url: str,
    publisher: str | None,
    year_override: int | None,
) -> dict[str, Any] | None:
    """Build a candidate source from the proposal, or None when unusable.

    Returns None when the model proposed no title or no schema-valid year — the
    two fields the importer cannot responsibly invent. Relevance scoring/topics
    are filled provisionally here and authoritatively by filter_relevant_sources.
    """
    title = proposal.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    year = _resolve_year(proposal, year_override)
    if year is None:
        return None
    title = title.strip()
    summary = proposal.get("summary")
    authors = [a for a in proposal.get("authors", []) if isinstance(a, str) and a.strip()]
    source_type = _resolve_source_type(proposal)
    score, topics = score_relevance({"title": title, "abstract": summary})
    return {
        "id": slugify(title, "src"),
        "title": title,
        "authors": authors,
        "year": year,
        "doi": None,
        "url": url,
        "openalex_id": None,
        "semantic_scholar_id": None,
        "eric_id": None,
        "publisher": (publisher or (authors[0] if authors else "Report")).strip(),
        "source_type": source_type,
        "license": None,
        "abstract": summary if isinstance(summary, str) and summary.strip() else None,
        "topics": topics,
        "relevance_score": score,
        "status": "candidate",
        "created_at": TODAY,
        "reviewed_at": None,
    }


def build_claims(
    proposal: dict[str, Any], source: dict[str, Any], report_text: str
) -> list[dict[str, Any]]:
    """Build candidate claims for *source* from the proposal's verbatim findings.

    Each finding's statement is checked against the report text; only verbatim
    quotes survive (hallucination guard), and the text_anchor quotes the exact
    passage. The richer review fields the model guessed are attached ONLY under
    the non-binding ``assist`` block; the real fields keep placeholders and
    evidence_strength stays low until a human review fills them in.
    """
    source_id = str(source["id"])
    source_slug = source_id.removeprefix("src-")
    evidence_type = EVIDENCE_TYPE_BY_SOURCE_TYPE.get(
        str(source.get("source_type")), DEFAULT_EVIDENCE_TYPE
    )
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in proposal.get("findings", []):
        if not isinstance(finding, dict):
            continue
        passage = verbatim_passage(str(finding.get("statement", "")), report_text)
        if passage is None or passage in seen:
            continue
        seen.add(passage)
        index = len(claims) + 1
        claim: dict[str, Any] = {
            "id": slugify(f"{source_slug} finding {index}", "claim"),
            "statement": passage,
            "source_ids": [source_id],
            "text_anchor": f'report excerpt: "{passage}"',
            "context": f"Auto-extracted candidate from report. {CONTEXT_PLACEHOLDER_SUFFIX}",
            "age_range": AGE_RANGE_PLACEHOLDER,
            "outcome": OUTCOME_PLACEHOLDER,
            "evidence_type": evidence_type,
            "evidence_strength": "low",
            "supports_skill_ids": [],
            "contradicts_skill_ids": [],
            "extraction_method": "llm_report_finding_extraction",
            "status": "candidate",
            "created_at": TODAY,
            "reviewed_at": None,
        }
        suggestion = {field: finding.get(field) for field in SUGGESTION_FIELDS}
        if any(value is not None for value in suggestion.values()):
            claim["assist"] = {
                "suggestions": [suggestion],
                "provenance": ai_provider.ai_provenance(REPORT_PROMPT_VERSION),
            }
        claims.append(claim)
    return claims


def report_candidates(
    proposal: dict[str, Any] | None,
    report_text: str,
    url: str,
    publisher: str | None,
    year_override: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn a proposal into (sources, claims), or ([], []) when there is none."""
    if not proposal:
        return [], []
    source = build_source(proposal, url, publisher, year_override)
    if source is None:
        return [], []
    return [source], build_claims(proposal, source, report_text)


def load_jobs(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Resolve the report import jobs from --manifest or a single --report.

    A manifest is a JSON array of objects, each ``{"report", "url",
    "publisher"?, "year"?}``; the single-report form mirrors one such entry on
    the command line. Each job's report plaintext is read here so missing files
    fail fast before any LLM call. Raises ValueError on a malformed request.
    """
    if args.manifest:
        entries = load_json(ROOT / args.manifest)
        if not isinstance(entries, list):
            raise ValueError(f"{args.manifest} must contain a JSON array of report entries")
    elif args.report and args.url:
        entries = [{"report": args.report, "url": args.url,
                    "publisher": args.publisher, "year": args.year}]
    else:
        raise ValueError("provide either --manifest, or both --report and --url")

    jobs: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("report") or not entry.get("url"):
            raise ValueError(f"each report entry needs a 'report' path and a 'url': {entry!r}")
        report_path = ROOT / entry["report"]
        if not report_path.exists():
            raise ValueError(f"report plaintext {report_path} does not exist")
        year = entry.get("year")
        jobs.append({
            "text": report_path.read_text(encoding="utf-8"),
            "url": str(entry["url"]),
            "publisher": entry.get("publisher"),
            "year": int(year) if isinstance(year, (int, str)) and str(year).isdigit() else None,
        })
    return jobs


def import_job(
    job: dict[str, Any], sources_path: Path, claims_path: Path
) -> tuple[int, int, int]:
    """Import one report job, returning (sources, claims, irrelevant) counts.

    Cross-job dedupe is automatic: each append re-reads the candidate files, and
    filter_new_sources/filter_new_claims dedupe against the whole repository, so a
    later job in the same run sees the earlier jobs' appends.
    """
    proposal = propose_report(job["text"], job["url"])
    sources, _ = report_candidates(
        proposal, job["text"], job["url"], job["publisher"], job["year"]
    )
    relevant = filter_relevant_sources(sources)
    new_sources = filter_new_sources(relevant)
    appended_sources = append_candidate_sources(sources_path, new_sources)

    # Build claims only AFTER the source id is final: relevance + dedupe may have
    # suffixed it, and the claims must reference the id actually written. A source
    # that was filtered as irrelevant or already known yields no claims.
    claim_count = 0
    for source in appended_sources:
        new_claims = filter_new_claims(build_claims(proposal, source, job["text"]))
        appended = append_unique_records(
            claims_path, new_claims, lambda claim: [claim_statement_key(claim)]
        )
        claim_count += len(appended)
    return len(appended_sources), claim_count, len(sources) - len(relevant)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import candidate report source(s) + verbatim finding-claims via an LLM."
    )
    parser.add_argument("--report", help="Path to a single report plaintext file.")
    parser.add_argument("--url", help="Canonical URL of the single report.")
    parser.add_argument("--publisher", default=None, help="Publishing organisation (e.g. OECD).")
    parser.add_argument("--year", type=int, default=None, help="Publication year override.")
    parser.add_argument(
        "--manifest",
        help="JSON array of {report, url, publisher?, year?} entries to import in one run.",
    )
    parser.add_argument("--sources-output", default="data/sources/candidates-reports.json")
    parser.add_argument("--claims-output", default="data/claims/candidates-reports.json")
    args = parser.parse_args()

    # Off by default: skip even reading files so the path is fully inert and the
    # message is unambiguous, exactly like the rest of the project's AI features.
    if ai_provider.ai_provider() == "none":
        print("AI provider off; imported no report candidates.")
        return 0

    try:
        jobs = load_jobs(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sources_path = ROOT / args.sources_output
    claims_path = ROOT / args.claims_output
    total_sources = total_claims = total_irrelevant = 0
    for job in jobs:
        n_sources, n_claims, n_irrelevant = import_job(job, sources_path, claims_path)
        total_sources += n_sources
        total_claims += n_claims
        total_irrelevant += n_irrelevant

    print(
        f"Imported {len(jobs)} report(s): appended {total_sources} source(s) to "
        f"{args.sources_output} and {total_claims} verbatim finding-claim(s) to "
        f"{args.claims_output} ({total_irrelevant} source(s) filtered as irrelevant)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
