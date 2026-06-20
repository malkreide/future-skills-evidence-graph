"""Optional, switchable AI helpers — off by default, deterministic to test.

This module is the foundation for *opt-in* AI features (assist suggestions,
embeddings). It changes nothing about the default pipeline: with the env flags
unset, ``complete`` and ``embed`` return ``None`` and nothing is imported beyond
the standard library. The design mirrors the rest of the project:

- **Default off.** ``AI_PROVIDER`` defaults to ``none``; the importers,
  ``validate_data.py`` and ``score_evidence.py`` never need this module.
- **No mandatory dependency in the import path.** The official ``anthropic`` SDK
  is imported *lazily*, only inside the ``anthropic`` branch — so when
  ``AI_PROVIDER`` is ``none`` or ``cache`` the import path stays stdlib-only and
  the whole module is network-free and reproducible.
- **Graceful degradation, fetch_or_warn-style.** Any provider failure (a missing
  SDK, a network error, a refusal, malformed output) logs a warning to stderr and
  yields an empty/None result. Nothing here raises into the pipeline.

Env flags
---------
``AI_PROVIDER``      ``none`` (default) | ``anthropic`` | ``cache``
``AI_MODEL``         model id for completions (default ``claude-opus-4-8``)
``ANTHROPIC_API_KEY``read by the anthropic SDK when ``AI_PROVIDER=anthropic``
``EMBEDDING_PROVIDER`` ``none`` (default) | ``local`` | ...  — a SEPARATE path,
                       because Anthropic has no embeddings API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# Fixture cache: stable request hash -> stored response. In `cache` mode this is
# read-only, so tests and CI run fully offline against committed fixtures.
CACHE_DIR = ROOT / "tests" / "fixtures" / "ai"
TODAY = date.today().isoformat()

# Default to the latest, most capable Claude model. Overridable via AI_MODEL.
DEFAULT_MODEL = "claude-opus-4-8"

# Dimensionality of the dependency-free local embedding (see _local_embedding).
EMBED_DIM = 256


# --- Env flags -------------------------------------------------------------


def ai_provider() -> str:
    """Active completion provider: ``none`` (default), ``anthropic`` or ``cache``."""
    return (os.getenv("AI_PROVIDER") or "none").strip().lower()


def ai_model() -> str:
    """Model id for completions (default ``claude-opus-4-8``)."""
    return (os.getenv("AI_MODEL") or DEFAULT_MODEL).strip()


def embedding_provider() -> str:
    """Active embedding provider: ``none`` (default), ``local`` or ...

    Kept separate from AI_PROVIDER on purpose: Anthropic has no embeddings API,
    so embeddings come from their own (local or third-party) provider.
    """
    return (os.getenv("EMBEDDING_PROVIDER") or "none").strip().lower()


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


# --- Fixture cache ---------------------------------------------------------


def _request_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a request, independent of dict ordering or Python version."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(payload: dict[str, Any]) -> Path:
    return CACHE_DIR / f"{_request_hash(payload)}.json"


def cache_read(payload: dict[str, Any]) -> Any | None:
    """Return the stored response for *payload*, or None on a miss/unreadable entry."""
    path = _cache_path(payload)
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn(f"AI cache entry {path.name} unreadable ({exc}); treating as a miss.")
        return None
    return stored.get("response")


def cache_write(payload: dict[str, Any], response: Any) -> None:
    """Persist *response* for *payload* so a later `cache` run can replay it."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        body = {
            "hash": _request_hash(payload),
            "kind": payload.get("kind"),
            "response": response,
        }
        text = json.dumps(body, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        _cache_path(payload).write_text(text, encoding="utf-8")
    except OSError as exc:
        _warn(f"AI cache write failed ({exc}); continuing without persisting.")


# --- Completions -----------------------------------------------------------


def complete(prompt: str, *, schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return a structured completion for *prompt*, or None when AI is off/unavailable.

    Determinism and the request surface follow the Opus 4.8 constraints: the
    JSON shape is constrained via ``output_config.format`` (a JSON Schema),
    determinism comes from ``output_config.effort='low'`` (NOT temperature, which
    is rejected on Opus 4.8), and there is NO assistant prefill (also rejected).
    A safety refusal (``stop_reason == 'refusal'``) yields None.

    - ``none`` (default): returns None — identical to having no AI at all.
    - ``cache``: read-only fixture replay; a miss warns and returns None.
    - ``anthropic``: live call via the official SDK, result cached for replay.
    """
    provider = ai_provider()
    if provider == "none":
        return None

    model = ai_model()
    payload = {"kind": "complete", "model": model, "prompt": prompt, "schema": schema}

    if provider == "cache":
        response = cache_read(payload)
        if response is None:
            # In CI (cache mode) a miss means the fixture is missing: there is no
            # offline answer, so the caller must treat None as a failure.
            _warn("AI cache miss for completion request; no fixture available in cache mode.")
        return response

    if provider == "anthropic":
        try:
            response = _anthropic_complete(model, prompt, schema)
        except Exception as exc:  # noqa: BLE001 - SDK/network must never abort the pipeline
            _warn(f"AI completion failed ({exc}); returning no suggestion.")
            return None
        if response is not None:
            cache_write(payload, response)
        return response

    _warn(f"Unknown AI_PROVIDER {provider!r}; expected none|anthropic|cache.")
    return None


def _anthropic_complete(
    model: str, prompt: str, schema: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Single structured call via the official anthropic SDK (lazy import)."""
    import anthropic  # lazy: keeps the import path stdlib for none|cache modes

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    # effort='low' gives determinism without temperature; no prefill is sent.
    output_config: dict[str, Any] = {"effort": "low"}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
    )

    if getattr(message, "stop_reason", None) == "refusal":
        _warn("AI completion refused (stop_reason=refusal); returning no suggestion.")
        return None

    text = next(
        (block.text for block in message.content if getattr(block, "type", None) == "text"),
        None,
    )
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        _warn(f"AI completion was not valid JSON ({exc}); returning no suggestion.")
        return None
    return data if isinstance(data, dict) else None


# --- Embeddings ------------------------------------------------------------


def embed(texts: list[str]) -> list[list[float]] | None:
    """Embed *texts*, or None when no embedding provider is configured.

    A separate path from completions: Anthropic has no embeddings API.
    - ``none`` (default): returns None.
    - ``local``: a deterministic, dependency-free hashing embedding that runs
      locally with no network — a real local model that can later be swapped for
      a heavier one without changing the call sites.
    """
    provider = embedding_provider()
    if provider == "none":
        return None
    if provider == "local":
        return [_local_embedding(text) for text in texts]
    _warn(f"Unknown EMBEDDING_PROVIDER {provider!r}; expected none|local.")
    return None


_EMBED_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _local_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic L2-normalized hashing embedding (stdlib only, no network)."""
    vector = [0.0] * dim
    for token in _EMBED_TOKEN_RE.findall((text or "").lower()):
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0.0:
        vector = [value / norm for value in vector]
    return vector


# --- Provenance ------------------------------------------------------------


def ai_provenance(prompt_version: str) -> dict[str, str]:
    """Provenance stamp for an AI-produced annotation (the ``assist.provenance``)."""
    return {
        "model": ai_model(),
        "prompt_version": prompt_version,
        "created_at": TODAY,
    }
