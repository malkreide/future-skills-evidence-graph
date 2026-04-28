from __future__ import annotations

import argparse
from collections import defaultdict

from common import load_records, source_identity, source_title_key


def duplicate_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for source in load_records("sources"):
        source_id = source.get("id", "<missing id>")
        groups[source_identity(source)].append(source_id)
        groups[source_title_key(source)].append(source_id)
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def main() -> int:
    parser = argparse.ArgumentParser(description="Report duplicate source records.")
    parser.parse_args()
    duplicates = duplicate_groups()
    if not duplicates:
        print("No duplicate sources found.")
        return 0
    print("Duplicate source groups:")
    for key, ids in sorted(duplicates.items()):
        print(f"- {key}: {', '.join(ids)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

