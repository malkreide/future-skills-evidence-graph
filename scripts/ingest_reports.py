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
import sys
from typing import Any

import ai_provider
from common import (
    ROOT,
    TODAY,
    append_candidate_sources,
    append_unique_records,
    claim_statement_key,
    filter_new_claims,
    filter_new_sources,
    filter_relevant_sources,
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
  - age_range: Altersbereich der Lernenden als "min-max" (6-18-Skala), oder null.
  - evidence_strength: eine von {{low, moderate, high}}, konservativ; im Zweifel low.'''


def report_prompt(text: str, url: str) -> str:
    """Render the versioned report-import prompt for *text*/*url*."""
    return REPORT_PROMPT_TEMPLATE.format(
        url=url.strip(),
        text=text.strip(),
        source_types=", ".join(REPORT_SOURCE_TYPES),
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
    result = ai_provider.complete(report_prompt(text, url), schema=REPORT_OUTPUT_SCHEMA)
    if not isinstance(result, dict):
        return None
    return result


def _collapse(text: str) -> str:
    """Collapse all runs of whitespace to single spaces (line-wrap agnostic)."""
    return " ".join(str(text).split())


def verbatim_passage(statement: str, text: str) -> str | None:
    """Return the whitespace-normalized *statement* iff it is a verbatim quote.

    PDF-extracted plaintext wraps lines arbitrarily, so matching is done on the
    whitespace-collapsed forms; everything else (wording, case, punctuation) must
    match exactly. A paraphrased, summarized or invented statement does not occur
    literally in the text and returns None — the hallucination guard. Statements
    below MIN_PASSAGE_LENGTH are rejected as too thin to be evidence.
    """
    collapsed_statement = _collapse(statement)
    if len(collapsed_statement) < MIN_PASSAGE_LENGTH:
        return None
    if collapsed_statement in _collapse(text):
        return collapsed_statement
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a candidate report source + verbatim finding-claims via an LLM."
    )
    parser.add_argument("--report", required=True, help="Path to the report plaintext file.")
    parser.add_argument("--url", required=True, help="Canonical URL of the report.")
    parser.add_argument("--publisher", default=None, help="Publishing organisation (e.g. OECD).")
    parser.add_argument("--year", type=int, default=None, help="Publication year override.")
    parser.add_argument("--sources-output", default="data/sources/candidates-reports.json")
    parser.add_argument("--claims-output", default="data/claims/candidates-reports.json")
    args = parser.parse_args()

    report_path = ROOT / args.report
    if not report_path.exists():
        print(f"Report plaintext {report_path} does not exist.", file=sys.stderr)
        return 1
    report_text = report_path.read_text(encoding="utf-8")

    proposal = propose_report(report_text, args.url)
    if proposal is None:
        # AI off / unavailable: a deliberate no-op, like the rest of the project.
        print("AI provider off or unavailable; imported no report candidates.")
        return 0

    sources, _ = report_candidates(
        proposal, report_text, args.url, args.publisher, args.year
    )
    relevant = filter_relevant_sources(sources)
    new_sources = filter_new_sources(relevant)
    appended_sources = append_candidate_sources(ROOT / args.sources_output, new_sources)

    # Build claims only AFTER the source id is final: relevance + dedupe may have
    # suffixed it, and the claims must reference the id actually written. A source
    # that was filtered as irrelevant or already known yields no claims.
    appended_claims: list[dict[str, Any]] = []
    for source in appended_sources:
        claims = build_claims(proposal, source, report_text)
        new_claims = filter_new_claims(claims)
        appended_claims += append_unique_records(
            ROOT / args.claims_output, new_claims, lambda claim: [claim_statement_key(claim)]
        )

    print(
        f"Appended {len(appended_sources)} report source(s) to {args.sources_output} "
        f"and {len(appended_claims)} verbatim finding-claim(s) to {args.claims_output} "
        f"({len(sources) - len(relevant)} source(s) filtered as irrelevant)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
