"""Build the OPTIONAL embedding relevance anchors from the labeled set.

Roadmap step 2 (classify relevance) ships a deterministic keyword heuristic by
default. Alongside the optional trained TF-IDF model (scripts/train_relevance.py)
this builds a second, lighter opt-in signal: a pair of prototype embeddings
("anchors"). The positive anchor is the centroid of the embeddings of the
relevant labeled examples in eval/relevance_labeled.json; the negative anchor is
the centroid of the irrelevant ones. At decision time a source is kept when it
is closer (cosine) to the positive anchor than to the negative one by at least
the artifact's decision_threshold (common.decide_relevance, embedding mode).

The embeddings come from ai_provider.embed, so an EMBEDDING_PROVIDER must be
configured (e.g. EMBEDDING_PROVIDER=local, the deterministic, dependency-free,
network-free hashing embedding). The artifact is small and human-readable, and
records its provenance: the embedding provider, dimensionality, build date, the
input files with their SHA-256 hashes, and the label counts -- everything needed
to reproduce it.

    EMBEDDING_PROVIDER=local python scripts/build_relevance_anchors.py
    EMBEDDING_PROVIDER=local python scripts/build_relevance_anchors.py --dry-run

Whether the anchors should actually be wired into the pipeline is a separate,
honest question answered by scripts/eval_relevance.py --compare-embedding (a
fair held-out comparison vs the heuristic). The default stays the heuristic;
activate only after a measured win.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path
from typing import Any

from ai_provider import embed, embedding_model_info, embedding_provider
from common import ROOT, load_json, source_text, vector_centroid, write_json


FORMAT_VERSION = 1
# Boundary difference: keep when cosine(pos) - cosine(neg) >= 0, i.e. closer to
# the positive anchor. Tunable per artifact without touching the scorer.
DEFAULT_DECISION_THRESHOLD = 0.0

EVAL_PATH = ROOT / "eval" / "relevance_labeled.json"
ANCHORS_PATH = ROOT / "models" / "relevance_anchors.json"


def file_sha256(path: Path) -> str:
    """Stable content hash of an input file, for reproducibility provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_texts(examples: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Return (relevant_texts, irrelevant_texts) from the labeled examples."""
    positives: list[str] = []
    negatives: list[str] = []
    for example in examples:
        text = source_text({"title": example.get("title"), "abstract": example.get("abstract")})
        (positives if example.get("relevant") else negatives).append(text)
    return positives, negatives


def build_artifact(
    positives: list[str],
    negatives: list[str],
    provider: str,
    threshold: float,
) -> dict[str, Any]:
    pos_vectors = embed(positives)
    neg_vectors = embed(negatives)
    if not pos_vectors or not neg_vectors:
        raise RuntimeError(
            f"embedding provider {provider!r} returned no vectors; "
            "set EMBEDDING_PROVIDER (e.g. EMBEDDING_PROVIDER=local)."
        )
    model_info = embedding_model_info(provider)
    return {
        "model_type": "embedding-anchors",
        "format_version": FORMAT_VERSION,
        "decision_threshold": threshold,
        "embedding_provider": provider,
        "embedding_dim": len(pos_vectors[0]),
        "anchors": {
            "positive": vector_centroid(pos_vectors),
            "negative": vector_centroid(neg_vectors),
        },
        "provenance": {
            "embedding_provider": provider,
            "model_name": model_info["model_name"],
            "model_version": model_info["model_version"],
            "embedding_dim": len(pos_vectors[0]),
            "built_at": date.today().isoformat(),
            "n_examples": len(positives) + len(negatives),
            "n_relevant": len(positives),
            "n_irrelevant": len(negatives),
            "input_files": [str(EVAL_PATH.relative_to(ROOT))],
            "input_hashes": {str(EVAL_PATH.relative_to(ROOT)): file_sha256(EVAL_PATH)},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the optional embedding relevance anchors.")
    parser.add_argument(
        "--output",
        default=str(ANCHORS_PATH),
        help="Where to write the JSON anchor artifact.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DECISION_THRESHOLD,
        help="Cosine-difference decision threshold stored in the artifact.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the anchors but do not write the artifact.",
    )
    args = parser.parse_args()

    provider = embedding_provider()
    if provider == "none":
        print(
            "No embedding provider configured. Set EMBEDDING_PROVIDER (e.g. "
            "EMBEDDING_PROVIDER=local) before building anchors.",
            file=sys.stderr,
        )
        return 1

    examples = load_json(EVAL_PATH)["examples"]
    positives, negatives = split_texts(examples)
    print(
        f"Building anchors from {len(examples)} labeled examples "
        f"({len(positives)} relevant, {len(negatives)} irrelevant) "
        f"via EMBEDDING_PROVIDER={provider}."
    )
    if not positives or not negatives:
        print("Need at least one relevant and one irrelevant example.", file=sys.stderr)
        return 1

    try:
        artifact = build_artifact(positives, negatives, provider, args.threshold)
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run: artifact not written.")
        return 0

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    write_json(output, artifact)
    print(f"Wrote anchor artifact to {output.relative_to(ROOT)} (provider {provider}).")
    print(
        "The heuristic remains the pipeline default; run "
        "eval_relevance.py --compare-embedding to compare."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
