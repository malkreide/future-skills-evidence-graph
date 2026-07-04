from __future__ import annotations

import argparse
from collections import defaultdict

from common import (
    is_title_duplicate,
    load_records,
    source_identity,
    source_title_key,
    title_similarity,
)


def duplicate_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for source in load_records("sources"):
        source_id = source.get("id", "<missing id>")
        groups[source_identity(source)].append(source_id)
        groups[source_title_key(source)].append(source_id)
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def fuzzy_duplicate_pairs() -> list[tuple[str, str, float]]:
    """Near-duplicate source pairs the exact keys miss (preprint/publication, variants).

    Reports pairs that ``is_title_duplicate`` links but that do not already share
    an exact identity or title/year key, so the output surfaces only the extra
    matches the fuzzy pass adds. Each pair carries its title similarity.
    """
    sources = load_records("sources")
    exact_keys = [
        {source_identity(source), source_title_key(source)} for source in sources
    ]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            if exact_keys[i] & exact_keys[j]:
                continue  # already caught by an exact key; not an *extra* match
            if is_title_duplicate(sources[i], sources[j]):
                left = str(sources[i].get("id", "<missing id>"))
                right = str(sources[j].get("id", "<missing id>"))
                score = title_similarity(
                    sources[i].get("title", ""), sources[j].get("title", "")
                )
                pairs.append((left, right, round(score, 3)))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Report duplicate source records.")
    parser.parse_args()
    duplicates = duplicate_groups()
    fuzzy = fuzzy_duplicate_pairs()
    if not duplicates and not fuzzy:
        print("No duplicate sources found.")
        return 0
    if duplicates:
        print("Duplicate source groups:")
        for key, ids in sorted(duplicates.items()):
            print(f"- {key}: {', '.join(ids)}")
    if fuzzy:
        print("Fuzzy near-duplicate source pairs (title similarity, review manually):")
        for left, right, score in sorted(fuzzy):
            print(f"- {left} ~ {right} (similarity {score})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
