from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TODAY = date.today().isoformat()

# Target age band for the project's evidence scope. The original MVP used 6-18;
# the scope now spans the whole "Lebenszyklus des Kindes" from early childhood
# through upper secondary (see CHANGELOG: Scope-Erweiterung auf 0-18), which
# covers all three Lehrplan-21 Zyklen -- Zyklus 1 begins at Kindergarten (~4 J.),
# so a 6-year floor would silently drop the youngest band. Both LLM prompts
# render this band from here, so a future scope change is a one-line edit instead
# of an edit across every prompt (and a re-recording of every fixture).
AGE_SCALE_MIN = 0
AGE_SCALE_MAX = 18
AGE_SCALE = f"{AGE_SCALE_MIN}-{AGE_SCALE_MAX}"


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


# The weekly source importers used to hard-code a single query string in the
# workflow YAML, so broadening the harvest meant editing CI. The query set now
# lives in a versioned, human-editable config file (config/research_queries.json)
# with an env override for one-off manual runs, resolved by load_research_queries.
DEFAULT_RESEARCH_QUERIES = ["AI literacy education children future skills"]
RESEARCH_QUERIES_PATH = ROOT / "config" / "research_queries.json"
RESEARCH_QUERIES_ENV = "RESEARCH_QUERIES"


def dedupe_queries(candidates: Iterable[str]) -> list[str]:
    """Trim/collapse whitespace, drop blanks, and de-dupe while preserving order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for candidate in candidates:
        text = " ".join(str(candidate).split())
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def load_research_queries() -> list[str]:
    """Ordered, de-duplicated research queries for the weekly source importers.

    Resolution order, falling through to the next level when one yields nothing
    usable so the pipeline never runs without a query:

    1. The ``RESEARCH_QUERIES`` env var (newline- or comma-separated) — lets a
       manual ``workflow_dispatch`` override the set for a single run.
    2. ``config/research_queries.json`` (a JSON array of strings) — the versioned,
       editable default the scheduled run uses. Malformed content is ignored.
    3. ``DEFAULT_RESEARCH_QUERIES`` — the built-in fallback.
    """
    raw_env = os.getenv(RESEARCH_QUERIES_ENV)
    if raw_env:
        queries = dedupe_queries(re.split(r"[\n,]", raw_env))
        if queries:
            return queries
    if RESEARCH_QUERIES_PATH.exists():
        try:
            payload = load_json(RESEARCH_QUERIES_PATH)
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, list):
            queries = dedupe_queries(entry for entry in payload if isinstance(entry, str))
            if queries:
                return queries
    return list(DEFAULT_RESEARCH_QUERIES)


def normalize_title(title: str) -> str:
    # Casefold first (ß -> ss), then strip diacritics via NFKD so accented
    # letters keep their base character instead of vanishing: without this,
    # "Schülerinnen" became "sch lerinnen" and no German keyword could ever
    # match — the relevance filter was structurally blind to German sources.
    normalized = title.casefold()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
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


# Two sources with different strong identifiers (DOI/URL) can still be the same
# work -- a preprint and its published version, a translation, or a re-issue with
# a lightly reworded title. The exact-identity keys above miss those, so a fuzzy
# title pass catches them: titles at or above TITLE_SIMILARITY_THRESHOLD (after
# normalize_title) count as the same work when their years fall within
# TITLE_SIMILARITY_YEAR_WINDOW. The threshold is deliberately high and the year
# window narrow so genuinely distinct works with similar titles are not merged --
# at worst a real duplicate slips through, never a distinct source silently
# dropped. Matching stays deterministic and dependency-free (difflib).
TITLE_SIMILARITY_THRESHOLD = 0.92
TITLE_SIMILARITY_YEAR_WINDOW = 1


def title_similarity(left: str, right: str) -> float:
    """Similarity in [0, 1] of two titles after normalization; 0 if either is empty."""
    left_norm = normalize_title(str(left))
    right_norm = normalize_title(str(right))
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def is_title_duplicate(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
    year_window: int = TITLE_SIMILARITY_YEAR_WINDOW,
) -> bool:
    """True when two sources look like the same work by fuzzy title plus close year.

    A high title similarity alone is not enough: when both records carry a year
    they must fall within *year_window* of each other, so a preprint and its
    next-year publication still match while two distinct same-titled works years
    apart do not. A missing year on either side falls back to the title alone.
    """
    if title_similarity(candidate.get("title", ""), existing.get("title", "")) < threshold:
        return False
    candidate_year = candidate.get("year")
    existing_year = existing.get("year")
    if isinstance(candidate_year, int) and isinstance(existing_year, int):
        return abs(candidate_year - existing_year) <= year_window
    return True


def source_is_valid_candidate(source: dict[str, Any]) -> bool:
    # A missing year (None) is allowed for CANDIDATES: an otherwise relevant
    # source without a publication_year used to arrive as year=0 and was
    # silently discarded here. The reviewer supplies the real year at
    # promote-source time — a source cannot become reviewed with year=None.
    year = source.get("year")
    return bool(
        source.get("title")
        and source.get("url")
        and (year is None or (isinstance(year, int) and 1900 <= year <= 2100))
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
    # Records to fuzzy-compare each candidate against: everything already in the
    # repo plus the candidates kept earlier in this same batch, so an incoming
    # preprint/publication pair also dedupes within one run.
    kept_records: list[dict[str, Any]] = list(existing)
    new_records: list[dict[str, Any]] = []
    for source in candidates:
        if not source_is_valid_candidate(source):
            continue
        identity = source_identity(source)
        title_key = source_title_key(source)
        if identity in known or title_key in known or identity in seen or title_key in seen:
            continue
        if any(is_title_duplicate(source, other) for other in kept_records):
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
        kept_records.append(source)
        new_records.append(source)
    return new_records


def append_unique_records(
    path: Path,
    new_records: list[dict[str, Any]],
    identities: Callable[[dict[str, Any]], list[str]],
    fuzzy_match: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Append candidate records to *path* instead of rewriting it.

    Earlier batches may still be awaiting review, so existing records must
    survive later runs. Records whose identity is already in the file are
    skipped; id collisions with existing records get a numeric suffix. When
    nothing new is appended the file is left untouched — in particular, a
    run without results creates no empty file that automation would stage
    and turn into a noise pull request. Returns the appended records.

    *fuzzy_match*, when given, is a second, exact-miss guard: a record is also
    skipped when it fuzzy-matches any record already in the file or appended
    earlier in this call. Sources pass ``is_title_duplicate`` here so a
    preprint/publication pair with different identifiers still dedupes on append.
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
    # Records to fuzzy-compare against: what is already in the file plus what this
    # call has appended so far.
    kept_records: list[dict[str, Any]] = list(existing)
    appended: list[dict[str, Any]] = []
    for record in new_records:
        record_identities = identities(record)
        if any(identity in known for identity in record_identities):
            continue
        if fuzzy_match is not None and any(fuzzy_match(record, other) for other in kept_records):
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
        kept_records.append(record)
        appended.append(record)
    if appended:
        write_json(path, existing + appended)
    return appended


def append_candidate_sources(path: Path, new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append source candidates, deduplicated by identity, title/year, and fuzzy title."""
    return append_unique_records(
        path,
        new_records,
        lambda source: [source_identity(source), source_title_key(source)],
        fuzzy_match=is_title_duplicate,
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
#
# The vocabulary is BILINGUAL (English + German): the project is anchored to
# Lehrplan 21, so German-language primary sources (EDK, KMK, PH publications,
# SNF studies) must be able to pass the automated pipeline. Keywords are written
# in natural spelling — normalize_title folds umlauts (ä→a, ü→u, ß→ss) on both
# sides of the match, so "künstliche intelligenz" also matches "kuenstliche"-free
# text after normalization. German nouns are inflected; the common case forms
# are listed explicitly because matching is exact-phrase, not stemmed.
TOPIC_KEYWORDS = {
    "ai literacy": (
        "ai literacy",
        "artificial intelligence literacy",
        "artificial intelligence",
        "machine learning",
        "generative ai",
        "large language model",
        "chatgpt",
        "ki kompetenz",
        "ki kompetenzen",
        "ki bildung",
        "ki grundbildung",
        "künstliche intelligenz",
        "künstlicher intelligenz",
        "maschinelles lernen",
        "maschinellem lernen",
        "generative ki",
        "generativer ki",
        "sprachmodell",
        "sprachmodelle",
    ),
    "critical thinking": (
        "critical thinking",
        "epistemic",
        "misinformation",
        "fact checking",
        "kritisches denken",
        "kritischen denkens",
        "kritischem denken",
        "kritische denken",
        "desinformation",
        "fehlinformation",
        "faktencheck",
    ),
    "digital competence": (
        "digital competence",
        "digital literacy",
        "digital skills",
        "media literacy",
        "digitale kompetenz",
        "digitale kompetenzen",
        "digitalen kompetenzen",
        "digitaler kompetenzen",
        "digitale bildung",
        "digitale grundbildung",
        "medienkompetenz",
        "medienkompetenzen",
        "medienbildung",
    ),
    "data literacy": (
        "data literacy",
        "data science education",
        "datenkompetenz",
        "datenkompetenzen",
    ),
    "creativity": (
        "creativity",
        "creative thinking",
        "creative problem solving",
        "kreativität",
        "kreatives denken",
        "kreativem denken",
        "kreatives problemlösen",
    ),
    "collaboration": (
        "collaboration",
        "collaborative",
        "teamwork",
        "cooperative learning",
        "zusammenarbeit",
        "kollaboration",
        "kollaboratives lernen",
        "kollaborativen lernens",
        "kooperatives lernen",
        "kooperativen lernens",
    ),
    "self-regulation": (
        "self-regulated",
        "self-regulation",
        "metacognition",
        "learning to learn",
        "lifelong learning",
        "selbstregulation",
        "selbstreguliertes lernen",
        "selbstregulierten lernens",
        "metakognition",
        "lernen lernen",
        "lebenslanges lernen",
        "lebenslangen lernens",
    ),
    "ethics": (
        "ethics",
        "ethical",
        "responsible ai",
        "privacy",
        "fairness",
        "ethik",
        "ethisch",
        "ethische",
        "ethischen",
        "ethischer",
        "verantwortungsvolle ki",
        "datenschutz",
    ),
    "systems thinking": (
        "systems thinking",
        "computational thinking",
        "systemdenken",
        "systemisches denken",
        "informatisches denken",
    ),
    "resilience": (
        "resilience",
        "adaptability",
        "resilienz",
        "anpassungsfähigkeit",
    ),
    "future skills": (
        "future skills",
        "21st century skills",
        "twenty-first century skills",
        "future of work",
        "key competencies",
        "zukunftskompetenz",
        "zukunftskompetenzen",
        "schlüsselkompetenzen",
        "kompetenzen des 21 jahrhunderts",
        "überfachliche kompetenzen",
        "überfachlichen kompetenzen",
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
    # German (see the bilingual note on TOPIC_KEYWORDS). "schüler" normalizes
    # to "schuler" and also covers the first token of "Schüler*innen".
    "kind",
    "kinder",
    "kindern",
    "jugendliche",
    "jugendlichen",
    "schüler",
    "schülerinnen",
    "schülern",
    "schule",
    "schulen",
    "unterricht",
    "bildung",
    "lehrplan",
    "lehrperson",
    "lehrpersonen",
    "lehrkraft",
    "lehrkräfte",
    "lernende",
    "lernenden",
    "klassenzimmer",
)

# Default minimum relevance for imported candidates: at least one topic match
# in the title, or a topic plus audience match in the abstract.
RELEVANCE_THRESHOLD = 0.3

# Curated off-scope vocabulary. These terms mark a source as belonging to a
# domain outside the MVP scope (AI / future-skills education for ages 0-18):
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
    # natural-disaster / emergency-preparedness domain (a disaster paper that
    # names a school audience and a skill word -- "resilience", "critical
    # thinking" -- in its title is still a disaster paper, not a future-skill one)
    "disaster",
    "disasters",
    "earthquake",
    "earthquakes",
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
    # audiences outside ages 0-18 / non-education contexts
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
    # physical education / health-promotion (not a future-skill domain)
    "physical education",
    "physical activity",
    "physical fitness",
    # foreign-language pedagogy (EAP/EFL/ESL is out of the MVP topic scope)
    "eap",
    "efl",
    "esl",
    # German equivalents of the classes above (health, engineering/agriculture,
    # labour/finance, workplace, pandemic logistics, PE). Reactive like the
    # English list: grown from observed false positives, not exhaustive.
    "ernährung",
    "klinisch",
    "klinische",
    "patienten",
    "patientinnen",
    "katastrophe",
    "katastrophen",
    "erdbeben",
    "landwirtschaft",
    "gehalt",
    "gehälter",
    "löhne",
    "steuern",
    "arbeitsplatz",
    "unternehmen",
    "betriebe",
    "pandemie",
    "sportunterricht",
    "bewegungsförderung",
)


# Audience/age gate. The MVP scope is learners aged 0-18, but "AI literacy" (and
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
    # German. Deliberately NOT "weiterbildung" (too broad — teacher PD lives
    # there and belongs to the educator lane, not the adult gate).
    "hochschule",
    "hochschulen",
    "universität",
    "universitäten",
    "studierende",
    "studierenden",
    "studenten",
    "studentinnen",
    "erwachsenenbildung",
    "berufstätige",
    "berufstätigen",
    "arbeitnehmende",
    "arbeitnehmer",
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
    # German / Swiss school stages (Lehrplan 21 anchoring). "berufsbildung" /
    # "berufsschule" mark Sek-II vocational learners (ages ~15-18, in scope) so
    # a German "college"-like term does not trip the adult gate.
    "kind",
    "kinder",
    "kindern",
    "vorschule",
    "frühe kindheit",
    "primarstufe",
    "primarschule",
    "grundschule",
    "volksschule",
    "sekundarstufe",
    "sekundarschule",
    "mittelschule",
    "oberstufe",
    "gymnasium",
    "gymnasien",
    "schulkinder",
    "schülerinnen und schüler",
    "jugendliche",
    "jugendlichen",
    "zyklus 1",
    "zyklus 2",
    "zyklus 3",
    "berufsbildung",
    "berufsschule",
    "berufsschulen",
)


# Educator relevance lane. The catalog tracks two audiences (see
# schemas/skill.schema.json): the future skills of learners aged 0-18 (default)
# and the competencies of the educators who enable them, anchored to the UNESCO
# AI Competency Framework for Teachers. The learner lane above intentionally
# drops adult / post-secondary audiences via is_adult_audience -- including
# pre-/in-service teachers -- so until now educator evidence could only enter
# through manual review. This lane keeps that evidence automatically: a
# topic-anchored, in-scope source whose SUBJECT is the (school) educator's own
# competence is kept and tagged audience="educator", even though it names an
# adult audience.
#
# The lane is deliberately narrow. EDUCATOR_STRONG_KEYWORDS are phrases that on
# their own denote a SCHOOL educator's competence as the subject of study
# (teacher education/training, pre-/in-service teachers, teacher competence,
# teaching AI literacy) -- these are exempt from the higher-education guard
# because teacher training, though university-based, produces school teachers.
# Failing a strong phrase, a source still qualifies only when it names an
# educator SUBJECT *and* a competence/development CONTEXT (which is where the
# non-school-bound pedagogy markers such as AI pedagogy / TPACK live, so they
# still need an educator subject and remain subject to the higher-ed guard).
# Bare "teacher"/"classroom" mentions, and pure teacher-productivity tool-use
# (lesson planning, grading, administrative automation), do NOT qualify -- those
# stay on the learner lane, where teacher-tool-use remains the tracked
# false-positive class (docs/relevanz-entscheidung.md). The vocabulary is
# teacher-centric on purpose ("teacher"/"educator", not "faculty"/"lecturer"/
# "instructor"), so it targets school educators rather than higher-education
# faculty teaching adults. The off-scope gate still applies before this lane.
EDUCATOR_STRONG_KEYWORDS = (
    "teacher education",
    "teacher educator",
    "teacher educators",
    "teacher training",
    "teacher preparation",
    "teacher professional development",
    "professional development for teachers",
    "professional development of teachers",
    "preservice teacher",
    "preservice teachers",
    "pre service teacher",
    "pre service teachers",
    "in service teacher",
    "in service teachers",
    "trainee teacher",
    "trainee teachers",
    "student teacher",
    "student teachers",
    "teacher candidate",
    "teacher candidates",
    "teacher competence",
    "teacher competency",
    "teacher competencies",
    "educator competence",
    "educator competency",
    "educator competencies",
    "teacher readiness",
    "teaching ai literacy",
    "teachers ai literacy",
    # German: teacher education/PD phrases that on their own denote a school
    # educator's competence as the subject (see the bilingual note above).
    "lehrerbildung",
    "lehrerinnenbildung",
    "lehrpersonenbildung",
    "lehrerausbildung",
    "lehrerfortbildung",
    "lehrerweiterbildung",
    "lehrpersonenfortbildung",
    "lehrpersonenweiterbildung",
    "lehrerkompetenz",
    "lehrerkompetenzen",
    "kompetenzen von lehrpersonen",
    "kompetenzen von lehrkräften",
    "angehende lehrpersonen",
    "angehende lehrkräfte",
    "lehramtsstudierende",
    "lehramtsstudierenden",
)
EDUCATOR_SUBJECT_KEYWORDS = (
    "teacher",
    "teachers",
    "educator",
    "educators",
    "teaching staff",
    "lehrperson",
    "lehrpersonen",
    "lehrkraft",
    "lehrkräfte",
    "lehrkräften",
    "lehrer",
    "lehrerinnen",
)
EDUCATOR_CONTEXT_KEYWORDS = (
    "professional development",
    "professional learning",
    "teacher education",
    "teacher training",
    "competence",
    "competency",
    "competencies",
    "readiness",
    "pedagogy",
    "pedagogical",
    "didactic",
    "didactics",
    "preservice",
    "pre service",
    "in service",
    "upskilling",
    "capacity building",
    "continuing education",
    "professional learning community",
    "tpack",
    "pedagogical content knowledge",
    "fortbildung",
    "weiterbildung",
    "kompetenz",
    "kompetenzen",
    "pädagogik",
    "pädagogisch",
    "pädagogische",
    "pädagogischen",
    "didaktik",
    "didaktisch",
    "didaktische",
    "didaktischen",
    "professionalisierung",
)
# Teacher PRODUCTIVITY / tool-use is the educator's adoption of an AI tool to
# reduce their own workload (lesson planning, grading, administrative
# automation), not the development of a teaching competence. It is the tracked
# false-positive class on the learner lane and is held off the educator lane too:
# the educator strand is about competence and pedagogy, not office automation.
EDUCATOR_OFF_KEYWORDS = (
    "lesson planning",
    "lesson plan",
    "grading",
    "marking",
    "workload",
    "administrative",
    "administration",
    "quiz question",
    "quiz questions",
    "automate",
    "automating",
    "automation",
)
# A school educator -- not a higher-education faculty member teaching adults --
# is the educator lane's subject. A source set in a higher-education TEACHING
# context with no school-age signal is therefore out of the lane, even if it
# names teachers/educators and a competence. Pre-/in-service teacher training
# (an EDUCATOR_STRONG_KEYWORDS phrase) is exempt: it is trained at universities
# but produces school teachers, so it is decided before this guard.
HIGHER_ED_TEACHING_KEYWORDS = (
    "higher education",
    "postsecondary",
    "post secondary",
    "tertiary",
    "university",
    "universities",
    "undergraduate",
    "undergraduates",
    "college student",
    "college students",
    "graduate student",
    "graduate students",
    "faculty",
    "hochschule",
    "hochschulen",
    "hochschuldidaktik",
    "universität",
    "universitäten",
    "studierende",
    "studierenden",
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

    An off-scope term in the TITLE is decisive: the paper is *about* that
    off-domain subject (a disaster/health/hygiene study), so the co-occurring
    skill word -- "resilience", "critical thinking", "self-regulation" -- is
    incidental and does not rescue it. This is the fix for the hard false-positive
    class of disaster/health papers that name a school audience and a skill word
    in the title (docs/relevanz-entscheidung.md).

    An off-scope term only in the ABSTRACT keeps the title-anchor exemption: a
    genuine in-scope paper names the future skill it studies in its title, so an
    abstract-only off-scope mention is treated as incidental when the title
    carries a topic. This preserves abstract-only in-scope sources.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "
    if any(_contains(title, keyword) for keyword in OFF_SCOPE_KEYWORDS):
        return True
    if any(_contains(abstract, keyword) for keyword in OFF_SCOPE_KEYWORDS):
        return not _title_topic_match(source)
    return False


def is_adult_audience(source: dict[str, Any]) -> bool:
    """Whether a source targets an adult / post-secondary audience only.

    True when a HIGHER_ED_KEYWORDS term appears (title or abstract) and no
    SCHOOL_AGE_KEYWORDS term does. Unlike is_off_scope this has no title-anchor
    exemption: naming "AI literacy" in the title does not make a workforce or
    university paper in scope for ages 0-18. Papers that mention both an adult
    and a school-age audience are kept.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "

    def text_has(keywords: tuple[str, ...]) -> bool:
        return any(_contains(title, kw) or _contains(abstract, kw) for kw in keywords)

    if not text_has(HIGHER_ED_KEYWORDS):
        return False
    return not text_has(SCHOOL_AGE_KEYWORDS)


def is_educator_audience(source: dict[str, Any]) -> bool:
    """Whether a source's subject is a (school) educator's own competence.

    True when the title/abstract carries a strong educator-competence phrase
    (EDUCATOR_STRONG_KEYWORDS), or names both an educator SUBJECT and a
    competence/development CONTEXT. This is the signal for the educator lane:
    such a source is kept and tagged audience="educator" even though it names an
    adult audience the learner lane would drop (see heuristic_keep). The off-scope
    gate is applied first, so this never resurrects an off-domain paper. The
    vocabulary is teacher-centric (not faculty/lecturer/instructor), so it tracks
    school educators rather than higher-education faculty teaching adults.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "

    def text_has(keywords: tuple[str, ...]) -> bool:
        return any(_contains(title, kw) or _contains(abstract, kw) for kw in keywords)

    # Teacher-productivity tool-use is not a competence: held off the lane.
    if text_has(EDUCATOR_OFF_KEYWORDS):
        return False
    # A higher-education teaching context with no school-age signal is
    # higher-ed faculty, not a school educator -- out of the lane. Strong
    # pre-/in-service teacher-education phrases are decided first and exempt.
    if text_has(EDUCATOR_STRONG_KEYWORDS):
        return True
    if text_has(HIGHER_ED_TEACHING_KEYWORDS) and not text_has(SCHOOL_AGE_KEYWORDS):
        return False
    return text_has(EDUCATOR_SUBJECT_KEYWORDS) and text_has(EDUCATOR_CONTEXT_KEYWORDS)


def is_teacher_tooluse(source: dict[str, Any]) -> bool:
    """Whether a source is teacher-productivity tool-use (an off-scope class).

    True when a teacher/educator SUBJECT is paired with a productivity/tool-use
    marker (EDUCATOR_OFF_KEYWORDS: lesson planning, grading, administrative
    automation, quiz generation). Such a paper is about a teacher adopting an AI
    tool to reduce their own workload -- neither a learner future skill nor an
    educator competence -- so it is dropped rather than merely held off the
    educator lane, where it was the tracked learner-lane false positive
    (docs/relevanz-entscheidung.md). Genuine teacher education/competence work
    (EDUCATOR_STRONG_KEYWORDS) is exempt, so "teacher training" evidence that
    happens to mention lesson planning still rides the educator lane.
    """
    title = f" {normalize_title(str(source.get('title') or ''))} "
    abstract = f" {normalize_title(str(source.get('abstract') or ''))} "

    def text_has(keywords: tuple[str, ...]) -> bool:
        return any(_contains(title, kw) or _contains(abstract, kw) for kw in keywords)

    if text_has(EDUCATOR_STRONG_KEYWORDS):
        return False
    return text_has(EDUCATOR_SUBJECT_KEYWORDS) and text_has(EDUCATOR_OFF_KEYWORDS)


def classify_audience(source: dict[str, Any]) -> str:
    """The relevance lane a kept source belongs to: "educator" or "learner".

    Educator-competence sources (is_educator_audience) ride the educator lane;
    everything else is a learner future-skill source. Mirrors the skill schema's
    audience axis (absence means learner) and is written onto survivors by
    filter_relevant_sources as an explainable companion signal next to topics.
    """
    return "educator" if is_educator_audience(source) else "learner"


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
    is_adult_audience) -- UNLESS the source rides the educator lane
    (is_educator_audience), which keeps in-scope educator-competence evidence the
    adult gate would otherwise drop. Measured by scripts/eval_relevance.py.
    """
    if not topics or score < min_relevance:
        return False
    if is_off_scope(source):
        return False
    # Teacher-productivity tool-use (a teacher subject + workload/admin automation)
    # is neither a learner future skill nor an educator competence -- drop it.
    if is_teacher_tooluse(source):
        return False
    # Educator lane: a topic-anchored, in-scope source about an educator's own
    # competence is kept even though it names an adult audience the learner gate
    # would otherwise drop. filter_relevant_sources tags it audience="educator".
    if is_educator_audience(source):
        return True
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


# --- Optional embedding relevance anchors ----------------------------------
#
# A SECOND optional, opt-in relevance signal (alongside the trained model): a
# pair of prototype embeddings ("anchors"). The positive anchor is the centroid
# of the embeddings of the relevant labeled examples, the negative anchor the
# centroid of the irrelevant ones (scripts/build_relevance_anchors.py). A source
# is kept when it is closer (cosine) to the positive anchor than to the negative
# one by at least the artifact's decision_threshold. The embeddings come from
# ai_provider.embed, so this needs an EMBEDDING_PROVIDER; when the artifact is
# absent or no embedding provider is configured we warn and fall back to the
# keyword heuristic, exactly like the model path. The default stays the
# heuristic; activate only after a measured win (eval_relevance.py).

RELEVANCE_ANCHORS_PATH = ROOT / "models" / "relevance_anchors.json"
ANCHORS_MODEL_TYPE = "embedding-anchors"
_embedding_fallback_warned = False


def load_relevance_anchors(path: Path | None = None) -> dict[str, Any] | None:
    """Load the anchor artifact, or None if absent/unreadable/foreign."""
    if path is None:
        path = RELEVANCE_ANCHORS_PATH
    if not path.exists():
        return None
    try:
        artifact = load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(artifact, dict) or artifact.get("model_type") != ANCHORS_MODEL_TYPE:
        return None
    return artifact


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is zero)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def vector_centroid(vectors: list[list[float]]) -> list[float]:
    """L2-normalized mean of *vectors* (the prototype anchor for a class)."""
    if not vectors:
        raise ValueError("cannot build a centroid from no vectors")
    dim = len(vectors[0])
    sums = [0.0] * dim
    for vector in vectors:
        for index, value in enumerate(vector):
            sums[index] += value
    mean = [value / len(vectors) for value in sums]
    norm = math.sqrt(sum(value * value for value in mean))
    if norm > 0.0:
        mean = [value / norm for value in mean]
    return mean


def anchor_relevance_difference(vector: list[float], anchors: dict[str, Any]) -> float:
    """cosine(vector, positive) - cosine(vector, negative): >0 leans relevant."""
    return cosine_similarity(vector, anchors["positive"]) - cosine_similarity(
        vector, anchors["negative"]
    )


def embedding_relevance_decision(
    source: dict[str, Any],
    artifact: dict[str, Any],
    embedder: Callable[[list[str]], list[list[float]] | None] | None = None,
) -> tuple[bool, float] | None:
    """Keep decision and similarity difference for *source* from the anchors.

    Embeds the source text via *embedder* (ai_provider.embed by default) and
    compares it to the two anchors. Returns (keep, difference), or None when no
    embedding provider is configured (embed returns None) so the caller can fall
    back to the heuristic.
    """
    if embedder is None:
        from ai_provider import embed as embedder  # lazy: stdlib import path stays clean
    vectors = embedder([source_text(source)])
    if not vectors:
        return None
    difference = anchor_relevance_difference(vectors[0], artifact["anchors"])
    threshold = float(artifact.get("decision_threshold", 0.0))
    return difference >= threshold, difference


def _anchor_difference_to_score(difference: float) -> float:
    """Map the cosine difference in [-2, 2] to a bounded relevance_score in [0, 1].

    The boundary difference (0.0, equally close to both anchors) maps to 0.5, so
    the stored score stays schema-valid and monotonic with the keep decision.
    """
    return round(min(1.0, max(0.0, (difference + 1.0) / 2.0)), 2)


def _warn_embedding_fallback(reason: str) -> None:
    global _embedding_fallback_warned
    if not _embedding_fallback_warned:
        print(
            f"Warning: RELEVANCE_CLASSIFIER=embedding but {reason}; "
            "falling back to the keyword heuristic.",
            file=sys.stderr,
        )
        _embedding_fallback_warned = True


def decide_relevance(
    source: dict[str, Any], min_relevance: float = RELEVANCE_THRESHOLD
) -> tuple[bool, float, list[str]]:
    """Decide whether to keep *source*; returns (keep, relevance_score, topics).

    The decision is pluggable. The default is the keyword heuristic, which is
    also the fallback whenever an opt-in classifier is not selected or cannot be
    loaded. The trained TF-IDF model is consulted only when
    RELEVANCE_CLASSIFIER=model; the embedding anchors only when
    RELEVANCE_CLASSIFIER=embedding and an EMBEDDING_PROVIDER is configured. A
    missing artifact or missing provider warns once and degrades to the
    heuristic, never raising into the pipeline.

    The topic/keyword hits are ALWAYS derived from the vocabulary and returned
    as an explainable companion signal next to whichever score decides keep, so
    the data model (relevance_score, topics) is unchanged regardless of mode.
    """
    score, topics = score_relevance(source)
    mode = relevance_classifier_mode()
    if mode == "model":
        artifact = load_relevance_model()
        if artifact is None:
            _warn_model_fallback("the model artifact is missing or unreadable")
        else:
            probability = model_relevance_probability(source, artifact)
            threshold = float(artifact.get("decision_threshold", 0.5))
            keep = probability >= threshold
            return keep, round(probability, 2), topics
    elif mode == "embedding":
        artifact = load_relevance_anchors()
        if artifact is None:
            _warn_embedding_fallback("the anchor artifact is missing or unreadable")
        else:
            decision = embedding_relevance_decision(source, artifact)
            if decision is None:
                _warn_embedding_fallback(
                    "no embedding provider is configured (set EMBEDDING_PROVIDER)"
                )
            else:
                keep, difference = decision
                return keep, _anchor_difference_to_score(difference), topics
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
        source["audience"] = classify_audience(source)
        kept.append(source)
    return kept
