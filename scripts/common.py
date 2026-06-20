from __future__ import annotations

import json
import math
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


# Audience/age gate. The MVP scope is learners aged 6-18, but "AI literacy" (and
# other topics) match regardless of who learns, so post-secondary and workplace
# papers slip through with a title topic anchor ("AI Literacy for the Workforce",
# "...in Higher Education", "College Students' AI Literacy"). HIGHER_ED_KEYWORDS
# mark an adult / post-secondary audience; SCHOOL_AGE_KEYWORDS mark the in-scope
# audience. A candidate is gated out only when an adult term is present AND no
# school-age term is, so papers covering both (e.g. "secondary students preparing
# for university") survive. Stored in normalized form (normalize_title collapses
# punctuation, so "k-12" -> "k 12", "pre-service" -> "pre service").
HIGHER_ED_KEYWORDS = (
    "higher education",
    "postsecondary",
    "post secondary",
    "tertiary",
    "university",
    "universities",
    "undergraduate",
    "undergraduates",
    "postgraduate",
    "postgraduates",
    "graduate student",
    "graduate students",
    "college student",
    "college students",
    "doctoral",
    "workforce",
    "employee",
    "employees",
    "preservice teacher",
    "preservice teachers",
    "pre service teacher",
    "pre service teachers",
    "in service teacher",
    "in service teachers",
    "adult learner",
    "adult learners",
    "adult education",
)
SCHOOL_AGE_KEYWORDS = (
    "child",
    "children",
    "kindergarten",
    "preschool",
    "pre school",
    "early childhood",
    "primary school",
    "primary education",
    "primary schools",
    "elementary",
    "secondary school",
    "secondary schools",
    "secondary education",
    "middle school",
    "high school",
    "primary student",
    "primary students",
    "secondary student",
    "secondary students",
    "school student",
    "school students",
    "high schooler",
    "high schoolers",
    "middle schooler",
    "middle schoolers",
    "k 12",
    "k12",
    "pupil",
    "pupils",
    "adolescent",
    "adolescents",
    "teenager",
    "teenagers",
    "schoolchild",
    "schoolchildren",
    "young learner",
    "young learners",
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


def is_adult_audience(source: dict[str, Any]) -> bool:
    """Whether a source targets an adult / post-secondary audience only.

    True when a HIGHER_ED_KEYWORDS term appears (title or abstract) and no
    SCHOOL_AGE_KEYWORDS term does. Unlike is_off_scope this has no title-anchor
    exemption: naming "AI literacy" in the title does not make a workforce or
    university paper in scope for ages 6-18. Papers that mention both an adult
    and a school-age audience are kept.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "

    def text_has(keywords: tuple[str, ...]) -> bool:
        return any(_contains(title, kw) or _contains(abstract, kw) for kw in keywords)

    if not text_has(HIGHER_ED_KEYWORDS):
        return False
    return not text_has(SCHOOL_AGE_KEYWORDS)


def heuristic_keep(
    source: dict[str, Any],
    score: float,
    topics: list[str],
    min_relevance: float = RELEVANCE_THRESHOLD,
) -> bool:
    """The deterministic keyword rule: a topic anchor at/above the threshold
    and no off-scope term without a title anchor.

    A candidate must match at least one topic in the vocabulary. Audience
    terms ("school", "students") alone do not qualify a source: that is the
    intent stated in score_relevance's docstring, but because an audience-only
    match scores exactly RELEVANCE_THRESHOLD it used to slip through, letting
    off-topic papers (public health, agriculture) into the candidate set.
    Requiring a topic match raises precision without dropping topic-matched
    candidates that sit at the threshold. Candidates that hit a curated
    off-scope term without a genuine topic anchor in the title (see
    is_off_scope / OFF_SCOPE_KEYWORDS) are dropped too, as are adult /
    post-secondary-audience papers with no school-age signal (see
    is_adult_audience). Measured by scripts/eval_relevance.py.
    """
    if not topics or score < min_relevance:
        return False
    if is_off_scope(source):
        return False
    if is_adult_audience(source):
        return False
    return True


# --- Optional trained relevance classifier ---------------------------------
#
# The default relevance decision is the deterministic keyword heuristic above:
# transparent, dependency-free, and the fallback whenever anything goes wrong.
# A trained TF-IDF + LogisticRegression model (scripts/train_relevance.py) can
# be opted into via the RELEVANCE_CLASSIFIER env flag, but ONLY the *training*
# step needs scikit-learn. The model is exported to a small, human-readable
# JSON artifact (models/relevance_model.json) and scored here with pure
# standard-library math that reproduces sklearn's TF-IDF + logistic regression
# exactly (train_relevance.py asserts the reproduction matches to < 1e-9), so
# the importers stay stdlib-only.

RELEVANCE_CLASSIFIER_ENV = "RELEVANCE_CLASSIFIER"
RELEVANCE_MODEL_PATH = ROOT / "models" / "relevance_model.json"
_TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")
_model_fallback_warned = False


def relevance_classifier_mode() -> str:
    """Active relevance decider: "heuristic" (default) or "model"."""
    return (os.getenv(RELEVANCE_CLASSIFIER_ENV) or "heuristic").strip().lower()


def load_relevance_model(path: Path | None = None) -> dict[str, Any] | None:
    """Load the JSON model artifact, or None if absent/unreadable/foreign."""
    if path is None:
        path = RELEVANCE_MODEL_PATH
    if not path.exists():
        return None
    try:
        artifact = load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(artifact, dict) or artifact.get("model_type") != "tfidf+logreg":
        return None
    return artifact


def _word_ngrams(tokens: list[str], ngram_range: tuple[int, int]) -> list[str]:
    """Reproduce sklearn CountVectorizer._word_ngrams: n-grams joined by a
    single space, for n in [min_n, max_n]."""
    min_n, max_n = ngram_range
    grams = list(tokens) if min_n == 1 else []
    n_tokens = len(tokens)
    for n in range(max(min_n, 2), max_n + 1):
        for i in range(n_tokens - n + 1):
            grams.append(" ".join(tokens[i : i + n]))
    return grams


def source_text(source: dict[str, Any]) -> str:
    """Title + abstract, the text the relevance model is trained and scored on."""
    return f"{source.get('title') or ''} {source.get('abstract') or ''}"


def model_relevance_probability(source: dict[str, Any], artifact: dict[str, Any]) -> float:
    """Probability that *source* is relevant under the trained model.

    Pure stdlib reimplementation of sklearn's TfidfVectorizer (smooth idf, L2
    norm) followed by binary LogisticRegression: tfidf = tf * idf, L2-normalize,
    logit = intercept + w . x, probability = sigmoid(logit).
    """
    vec = artifact["vectorizer"]
    clf = artifact["classifier"]
    vocabulary = vec["vocabulary"]
    idf = vec["idf"]
    coef = clf["coef"]
    intercept = float(clf["intercept"])
    ngram_range = tuple(vec.get("ngram_range", (1, 1)))

    tokens = _TOKEN_RE.findall(source_text(source).lower())
    counts: dict[int, int] = {}
    for gram in _word_ngrams(tokens, ngram_range):
        index = vocabulary.get(gram)
        if index is not None:
            counts[index] = counts.get(index, 0) + 1

    weighted = {index: count * idf[index] for index, count in counts.items()}
    norm = math.sqrt(sum(value * value for value in weighted.values()))
    logit = intercept
    if norm > 0.0:
        for index, value in weighted.items():
            logit += (value / norm) * coef[index]
    return 1.0 / (1.0 + math.exp(-logit))


def _warn_model_fallback(reason: str) -> None:
    global _model_fallback_warned
    if not _model_fallback_warned:
        print(
            f"Warning: RELEVANCE_CLASSIFIER=model but {reason}; "
            "falling back to the keyword heuristic.",
            file=sys.stderr,
        )
        _model_fallback_warned = True


def decide_relevance(
    source: dict[str, Any], min_relevance: float = RELEVANCE_THRESHOLD
) -> tuple[bool, float, list[str]]:
    """Decide whether to keep *source*; returns (keep, relevance_score, topics).

    The decision is pluggable. The default is the keyword heuristic, which is
    also the fallback whenever the model is not opted in or cannot be loaded.
    The trained model is consulted only when RELEVANCE_CLASSIFIER=model and a
    valid artifact is present.

    The topic/keyword hits are ALWAYS derived from the vocabulary and returned
    as an explainable companion signal next to whichever score decides keep, so
    the data model (relevance_score, topics) is unchanged regardless of mode.
    """
    score, topics = score_relevance(source)
    if relevance_classifier_mode() == "model":
        artifact = load_relevance_model()
        if artifact is None:
            _warn_model_fallback("the model artifact is missing or unreadable")
        else:
            probability = model_relevance_probability(source, artifact)
            threshold = float(artifact.get("decision_threshold", 0.5))
            keep = probability >= threshold
            return keep, round(probability, 2), topics
    return heuristic_keep(source, score, topics, min_relevance), score, topics


def filter_relevant_sources(
    candidates: list[dict[str, Any]], min_relevance: float = RELEVANCE_THRESHOLD
) -> list[dict[str, Any]]:
    """Drop irrelevant candidates and annotate the survivors.

    Uses the pluggable decide_relevance: the keyword heuristic by default (and
    as fallback), the trained model only when RELEVANCE_CLASSIFIER=model and an
    artifact is available. relevance_score and topics are written exactly as
    before; topics stay the explainable keyword companion signal in either mode.
    """
    kept: list[dict[str, Any]] = []
    for source in candidates:
        keep, score, topics = decide_relevance(source, min_relevance)
        if not keep:
            continue
        source["relevance_score"] = score
        source["topics"] = topics
        kept.append(source)
    return kept
