from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TODAY = date.today().isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)
        handle.write("\n")


def iter_json_files(kind: str) -> Iterable[Path]:
    directory = DATA_DIR / kind
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def load_records(kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in iter_json_files(kind):
        payload = load_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"{path} contains a non-object record")
            records.append(item)
    return records


def normalize_title(title: str) -> str:
    normalized = title.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def slugify(value: str, prefix: str | None = None, max_length: int = 72) -> str:
    slug = normalize_title(value).replace(" ", "-")
    slug = slug[:max_length].strip("-") or "record"
    return f"{prefix}-{slug}" if prefix else slug


def source_identity(source: dict[str, Any]) -> str:
    for field in ("doi", "openalex_id", "semantic_scholar_id", "eric_id", "url"):
        value = source.get(field)
        if value:
            return f"{field}:{str(value).casefold()}"
    return f"title:{normalize_title(str(source.get('title', '')))}"


def source_title_key(source: dict[str, Any]) -> str:
    year = source.get("year", "")
    return f"{normalize_title(str(source.get('title', '')))}::{year}"


def source_is_valid_candidate(source: dict[str, Any]) -> bool:
    return bool(
        source.get("title")
        and source.get("url")
        and isinstance(source.get("year"), int)
        and 1900 <= source.get("year") <= 2100
    )


def filter_new_sources(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = load_records("sources")
    known: set[str] = set()
    used_ids: set[str] = set()
    for source in existing:
        known.add(source_identity(source))
        known.add(source_title_key(source))
        used_ids.add(str(source.get("id", "")))
    seen: set[str] = set()
    new_records: list[dict[str, Any]] = []
    for source in candidates:
        if not source_is_valid_candidate(source):
            continue
        identity = source_identity(source)
        title_key = source_title_key(source)
        if identity in known or title_key in known or identity in seen or title_key in seen:
            continue
        base_id = str(source.get("id", "src-record"))
        source_id = base_id
        suffix = 2
        while source_id in used_ids:
            source_id = f"{base_id}-{suffix}"
            suffix += 1
        source["id"] = source_id
        used_ids.add(source_id)
        seen.add(identity)
        seen.add(title_key)
        new_records.append(source)
    return new_records


def append_unique_records(
    path: Path,
    new_records: list[dict[str, Any]],
    identities: Callable[[dict[str, Any]], list[str]],
) -> list[dict[str, Any]]:
    """Append candidate records to *path* instead of rewriting it.

    Earlier batches may still be awaiting review, so existing records must
    survive later runs. Records whose identity is already in the file are
    skipped; id collisions with existing records get a numeric suffix. When
    nothing new is appended the file is left untouched — in particular, a
    run without results creates no empty file that automation would stage
    and turn into a noise pull request. Returns the appended records.
    """
    existing: list[dict[str, Any]] = []
    if path.exists():
        payload = load_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        existing = payload
    known: set[str] = set()
    used_ids: set[str] = set()
    for record in existing:
        known.update(identities(record))
        used_ids.add(str(record.get("id", "")))
    appended: list[dict[str, Any]] = []
    for record in new_records:
        record_identities = identities(record)
        if any(identity in known for identity in record_identities):
            continue
        base_id = str(record.get("id", "record"))
        record_id = base_id
        suffix = 2
        while record_id in used_ids:
            record_id = f"{base_id}-{suffix}"
            suffix += 1
        record["id"] = record_id
        used_ids.add(record_id)
        known.update(record_identities)
        appended.append(record)
    if appended:
        write_json(path, existing + appended)
    return appended


def append_candidate_sources(path: Path, new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append source candidates, deduplicated by identity and title/year."""
    return append_unique_records(
        path,
        new_records,
        lambda source: [source_identity(source), source_title_key(source)],
    )


def claim_statement_key(claim: dict[str, Any]) -> str:
    return f"statement:{normalize_title(str(claim.get('statement', '')))}"


def filter_new_claims(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop claim candidates whose statement is already known repo-wide.

    Mirrors filter_new_sources: dedupes against every file in data/claims/
    and uniquifies ids with a numeric suffix.
    """
    existing = load_records("claims")
    known = {claim_statement_key(claim) for claim in existing}
    used_ids = {str(claim.get("id", "")) for claim in existing}
    seen: set[str] = set()
    new_records: list[dict[str, Any]] = []
    for claim in candidates:
        key = claim_statement_key(claim)
        if key in known or key in seen:
            continue
        base_id = str(claim.get("id", "claim-record"))
        claim_id = base_id
        suffix = 2
        while claim_id in used_ids:
            claim_id = f"{base_id}-{suffix}"
            suffix += 1
        claim["id"] = claim_id
        used_ids.add(claim_id)
        seen.add(key)
        new_records.append(claim)
    return new_records


def fetch_or_warn(
    label: str, fetch: Callable[[], list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Run an importer's network fetch, degrading gracefully on failure.

    One source's outage — a rate limit, a network error, or a malformed
    response — must not abort the whole research pipeline: the other
    importers and the downstream extraction and clustering steps should
    still run on whatever was fetched. On failure this logs a warning and
    returns an empty list so the importer writes no candidates this run.
    """
    try:
        # urllib's URLError/HTTPError/TimeoutError subclass OSError; a bad
        # JSON body raises JSONDecodeError, which subclasses ValueError.
        return list(fetch())
    except (OSError, ValueError) as exc:
        print(f"Warning: {label} fetch failed ({exc}); skipping this source.", file=sys.stderr)
        return []


def env_or_none(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None


def lp21_coverage_label(score: float) -> str:
    """Derive the Lehrplan 21 coverage label from the coverage score.

    Thresholds are documented in docs/lehrplan21-coverage-methodik.md and
    mirrored by the dashboard in site/assets/app.js (lp21CoverageLabel).
    """
    if score >= 2.4:
        return "gut abgedeckt"
    if score >= 1.5:
        return "teilweise"
    return "Zukunftsluecke"


# Topic vocabulary derived from the MVP scope in MASTER_PROMPT.md. Keys become
# the candidate's topics; keyword variants are matched against title and abstract.
TOPIC_KEYWORDS = {
    "ai literacy": (
        "ai literacy",
        "artificial intelligence literacy",
        "artificial intelligence",
        "machine learning",
        "generative ai",
        "large language model",
        "chatgpt",
    ),
    "critical thinking": ("critical thinking", "epistemic", "misinformation", "fact checking"),
    "digital competence": ("digital competence", "digital literacy", "digital skills", "media literacy"),
    "data literacy": ("data literacy", "data science education"),
    "creativity": ("creativity", "creative thinking", "creative problem solving"),
    "collaboration": ("collaboration", "collaborative", "teamwork", "cooperative learning"),
    "self-regulation": (
        "self-regulated",
        "self-regulation",
        "metacognition",
        "learning to learn",
        "lifelong learning",
    ),
    "ethics": ("ethics", "ethical", "responsible ai", "privacy", "fairness"),
    "systems thinking": ("systems thinking", "computational thinking"),
    "resilience": ("resilience", "adaptability"),
    "future skills": (
        "future skills",
        "21st century skills",
        "twenty-first century skills",
        "future of work",
        "key competencies",
    ),
}

AUDIENCE_KEYWORDS = (
    "child",
    "children",
    "adolescent",
    "youth",
    "student",
    "pupil",
    "k-12",
    "school",
    "education",
    "teacher",
    "classroom",
    "curriculum",
    "learner",
)

# Default minimum relevance for imported candidates: at least one topic match
# in the title, or a topic plus audience match in the abstract.
RELEVANCE_THRESHOLD = 0.3

# Curated off-scope vocabulary. These terms mark a source as belonging to a
# domain outside the MVP scope (AI / future-skills education for ages 6-18):
# public health and nutrition, environmental and process engineering, labour
# relations and finance, and audiences other than school-aged learners (clinical
# patients, university/graduate students, SMEs and workplaces). A candidate is
# only discarded for an off-scope term when it lacks a genuine topic anchor in
# its TITLE. In-scope papers name the future skill they study in the title, so
# an off-scope term paired with a merely incidental abstract topic match (e.g. a
# pupil health paper that touches "complexity", or a salary agreement that
# mentions "collaboration") is treated as out of scope. Keeping the guard on the
# title preserves abstract-only in-scope candidates while raising precision.
# Measured by scripts/eval_relevance.py.
OFF_SCOPE_KEYWORDS = (
    # public health / medicine / nutrition
    "nutrition",
    "dietary",
    "obesity",
    "menstrual",
    "menstruation",
    "hygiene",
    "sanitation",
    "wastewater",
    "effluent",
    "clinical",
    "patients",
    "disease",
    # environment / process engineering / agriculture
    "refinery",
    "refineries",
    "soil",
    "agriculture",
    "agricultural",
    # labour relations / governance / finance
    "salary",
    "salaries",
    "wages",
    "tax",
    # audiences outside ages 6-18 / non-education contexts
    "trauma",
    "posttraumatic",
    "immigrant",
    "immigrants",
    "immigration",
    "acculturation",
    "acculturative",
    "sme",
    "smes",
    "enterprise",
    "enterprises",
    "workplace",
    "organizational",
    "esg",
    # pandemic-era remote-teaching logistics
    "covid",
    "pandemic",
    "lockdown",
    "lockdowns",
)


def _contains(text: str, keyword: str) -> bool:
    return f" {normalize_title(keyword)} " in text


def score_relevance(source: dict[str, Any]) -> tuple[float, list[str]]:
    """Score how relevant a source is to the project scope (0..1).

    Each distinct topic matched in the title adds 0.3 (0.15 if only in the
    abstract), capped at 0.7. An audience term adds 0.3 from the title or
    0.15 from the abstract. Returns the score and the matched topics.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "
    topics: list[str] = []
    topic_component = 0.0
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(_contains(title, keyword) for keyword in keywords):
            topics.append(topic)
            topic_component += 0.3
        elif any(_contains(abstract, keyword) for keyword in keywords):
            topics.append(topic)
            topic_component += 0.15
    audience_component = 0.0
    if any(_contains(title, keyword) for keyword in AUDIENCE_KEYWORDS):
        audience_component = 0.3
    elif any(_contains(abstract, keyword) for keyword in AUDIENCE_KEYWORDS):
        audience_component = 0.15
    score = min(0.7, topic_component) + audience_component
    return round(min(1.0, score), 2), topics


def _title_topic_match(source: dict[str, Any]) -> bool:
    """Whether any topic keyword matches the source's title.

    A title match is treated as a genuine topic relation: in-scope papers name
    the future skill they study in the title, whereas off-scope papers tend to
    match a topic keyword only incidentally in the abstract.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    return any(
        any(_contains(title, keyword) for keyword in keywords)
        for keywords in TOPIC_KEYWORDS.values()
    )


def is_off_scope(source: dict[str, Any]) -> bool:
    """Whether a source hits an off-scope term without a genuine topic anchor.

    Returns True when an OFF_SCOPE_KEYWORDS term appears in the title or abstract
    and no topic keyword matches the title. This discards public-health,
    environmental, labour-relations and non-6-18-audience papers that match a
    topic keyword only in passing, while keeping abstract-only in-scope sources
    that carry no off-scope term.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "
    has_off_scope = any(
        _contains(title, keyword) or _contains(abstract, keyword)
        for keyword in OFF_SCOPE_KEYWORDS
    )
    if not has_off_scope:
        return False
    return not _title_topic_match(source)


def filter_relevant_sources(
    candidates: list[dict[str, Any]], min_relevance: float = RELEVANCE_THRESHOLD
) -> list[dict[str, Any]]:
    """Drop candidates below the relevance threshold and derive their topics.

    A candidate must match at least one topic in the vocabulary. Audience
    terms ("school", "students") alone do not qualify a source: that is the
    intent stated in score_relevance's docstring, but because an audience-only
    match scores exactly RELEVANCE_THRESHOLD it used to slip through, letting
    off-topic papers (public health, agriculture) into the candidate set.
    Requiring a topic match raises precision without dropping topic-matched
    candidates that sit at the threshold.

    Candidates that hit a curated off-scope term without a genuine topic anchor
    in the title (see is_off_scope / OFF_SCOPE_KEYWORDS) are also dropped: this
    removes incidental matches such as a pupil-health paper touching
    "complexity" or a salary agreement mentioning "collaboration". Measured by
    scripts/eval_relevance.py.
    """
    kept: list[dict[str, Any]] = []
    for source in candidates:
        score, topics = score_relevance(source)
        if not topics or score < min_relevance:
            continue
        if is_off_scope(source):
            continue
        source["relevance_score"] = score
        source["topics"] = topics
        kept.append(source)
    return kept
