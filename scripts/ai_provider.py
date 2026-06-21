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
``EMBEDDING_PROVIDER`` ``none`` (default) | ``local`` | ``st`` — a SEPARATE path,
                       because Anthropic has no embeddings API.
``ST_EMBED_MODEL``   sentence-transformers model id for ``EMBEDDING_PROVIDER=st``
                       (default ``all-MiniLM-L6-v2``).
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
# Fixture cache for `st` embeddings, one file per (model, text). Committed so CI
# replays real sentence-transformers vectors offline, without the heavy package.
EMBED_CACHE_DIR = ROOT / "tests" / "fixtures" / "embeddings"
TODAY = date.today().isoformat()

# Default to the latest, most capable Claude model. Overridable via AI_MODEL.
DEFAULT_MODEL = "claude-opus-4-8"

# Dimensionality of the dependency-free local embedding (see _local_embedding).
EMBED_DIM = 256

# Default sentence-transformers model for EMBEDDING_PROVIDER=st. Small, widely
# used, 384-dim; overridable via ST_EMBED_MODEL. Only loaded on a cache miss.
ST_DEFAULT_MODEL = "all-MiniLM-L6-v2"


# --- Env flags -------------------------------------------------------------


def ai_provider() -> str:
    """Active completion provider: ``none`` (default), ``anthropic`` or ``cache``."""
    return (os.getenv("AI_PROVIDER") or "none").strip().lower()


def ai_model() -> str:
    """Model id for completions (default ``claude-opus-4-8``)."""
    return (os.getenv("AI_MODEL") or DEFAULT_MODEL).strip()


def embedding_provider() -> str:
    """Active embedding provider: ``none`` (default), ``local`` or ``st``.

    Kept separate from AI_PROVIDER on purpose: Anthropic has no embeddings API,
    so embeddings come from their own (local or third-party) provider.

    - ``local``: the deterministic, dependency-free hashing embedding (CI default).
    - ``st``: a real local sentence-transformers model, served offline from the
      committed embedding fixtures (the heavy package is only imported on a miss).
    """
    return (os.getenv("EMBEDDING_PROVIDER") or "none").strip().lower()


def st_model_name() -> str:
    """sentence-transformers model id for ``EMBEDDING_PROVIDER=st``."""
    return (os.getenv("ST_EMBED_MODEL") or ST_DEFAULT_MODEL).strip()


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
    - ``local`` (CI default): a deterministic, dependency-free hashing embedding
      that runs locally with no network.
    - ``st``: a real local sentence-transformers model (semantic embeddings),
      served offline from the committed fixture cache; the heavy package is only
      imported on a cache miss (i.e. for a text not yet recorded).
    """
    provider = embedding_provider()
    if provider == "none":
        return None
    if provider == "local":
        return [_local_embedding(text) for text in texts]
    if provider == "st":
        return _st_embed(texts)
    _warn(f"Unknown EMBEDDING_PROVIDER {provider!r}; expected none|local|st.")
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


# --- Local sentence-transformers embeddings (st), fixture-backed -----------
#
# A real semantic embedding, kept offline-safe the same way the AI completion
# cache is: each (model, text) maps to a stable hash and the L2-normalized vector
# is committed under tests/fixtures/embeddings/. With the fixtures present every
# call is a cache hit, so CI never imports sentence-transformers and never hits
# the network. The package is a pure dev/live dependency, imported lazily only to
# fill a cache *miss* (when building anchors or recording new fixtures locally).

_st_model_cache: tuple[str, Any] | None = None


def _embed_cache_key(model: str, text: str) -> str:
    blob = json.dumps([model, text], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _embed_cache_path(model: str, text: str) -> Path:
    return EMBED_CACHE_DIR / f"{_embed_cache_key(model, text)}.json"


def embed_cache_read(model: str, text: str) -> list[float] | None:
    """Return the cached vector for (model, text), or None on a miss."""
    path = _embed_cache_path(model, text)
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn(f"embedding fixture {path.name} unreadable ({exc}); treating as a miss.")
        return None
    vector = stored.get("embedding")
    return vector if isinstance(vector, list) else None


def embed_cache_write(model: str, text: str, vector: list[float]) -> None:
    """Persist *vector* for (model, text) so a later run replays it offline."""
    try:
        EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        body = {
            "model": model,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "dim": len(vector),
            "embedding": vector,
        }
        text_blob = json.dumps(body, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        _embed_cache_path(model, text).write_text(text_blob, encoding="utf-8")
    except OSError as exc:
        _warn(f"embedding fixture write failed ({exc}); continuing without persisting.")


def _load_st_model(model: str) -> Any:
    """Lazily load (and memoize) the sentence-transformers model."""
    global _st_model_cache
    if _st_model_cache is None or _st_model_cache[0] != model:
        from sentence_transformers import SentenceTransformer  # lazy, dev/live only

        _st_model_cache = (model, SentenceTransformer(model))
    return _st_model_cache[1]


def _st_embed(texts: list[str]) -> list[list[float]] | None:
    """L2-normalized sentence-transformers vectors, cache-first.

    Returns the cached vector for every text that has a committed fixture. Any
    miss is filled by loading the model (network/package required); when the
    model cannot be loaded a miss warns and yields None, so callers fall back to
    the keyword heuristic instead of failing.
    """
    model = st_model_name()
    results: list[list[float] | None] = [embed_cache_read(model, text) for text in texts]
    missing = [index for index, vector in enumerate(results) if vector is None]
    if missing:
        try:
            encoder = _load_st_model(model)
        except Exception as exc:  # noqa: BLE001 - missing package/network must not abort
            _warn(
                f"sentence-transformers unavailable for EMBEDDING_PROVIDER=st ({exc}); "
                f"{len(missing)} text(s) not in the embedding fixture cache."
            )
            return None
        encoded = encoder.encode(
            [texts[index] for index in missing], normalize_embeddings=True
        )
        for offset, index in enumerate(missing):
            vector = [float(value) for value in encoded[offset]]
            embed_cache_write(model, texts[index], vector)
            results[index] = vector
    return [vector for vector in results if vector is not None]


def embedding_model_info(provider: str | None = None) -> dict[str, str]:
    """Provenance for the active embedding provider: model name + version.

    - ``st``: the sentence-transformers model id and the installed package
      version (``unknown`` when the package is absent, e.g. a fixture-only run).
    - ``local``: the deterministic hashing scheme and its dimensionality.
    """
    if provider is None:
        provider = embedding_provider()
    if provider == "st":
        try:
            import sentence_transformers  # lazy: only to read the version string

            version = sentence_transformers.__version__
        except Exception:  # noqa: BLE001 - version is best-effort provenance
            version = "unknown"
        return {"model_name": st_model_name(), "model_version": f"sentence-transformers {version}"}
    if provider == "local":
        return {"model_name": "local-hashing-sha1", "model_version": f"dim-{EMBED_DIM}"}
    return {"model_name": "", "model_version": ""}


# --- Provenance ------------------------------------------------------------


def ai_provenance(prompt_version: str) -> dict[str, str]:
    """Provenance stamp for an AI-produced annotation (the ``assist.provenance``)."""
    return {
        "model": ai_model(),
        "prompt_version": prompt_version,
        "created_at": TODAY,
    }
