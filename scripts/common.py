from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable


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


def known_source_keys(extra_records: list[dict[str, Any]] | None = None) -> set[str]:
    sources = load_records("sources")
    if extra_records:
        sources.extend(extra_records)
    keys: set[str] = set()
    for source in sources:
        keys.add(source_identity(source))
        keys.add(source_title_key(source))
    return keys


def source_is_valid_candidate(source: dict[str, Any]) -> bool:
    return bool(
        source.get("title")
        and source.get("url")
        and isinstance(source.get("year"), int)
        and 1900 <= source.get("year") <= 2100
    )


def filter_new_sources(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = known_source_keys()
    seen: set[str] = set()
    new_records: list[dict[str, Any]] = []
    id_counts: dict[str, int] = {}
    for source in candidates:
        if not source_is_valid_candidate(source):
            continue
        identity = source_identity(source)
        title_key = source_title_key(source)
        if identity in known or title_key in known or identity in seen or title_key in seen:
            continue
        source_id = str(source.get("id", "src-record"))
        id_counts[source_id] = id_counts.get(source_id, 0) + 1
        if id_counts[source_id] > 1:
            source["id"] = f"{source_id}-{id_counts[source_id]}"
        seen.add(identity)
        seen.add(title_key)
        new_records.append(source)
    return new_records


def env_or_none(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None
