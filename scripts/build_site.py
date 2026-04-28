from __future__ import annotations

import argparse
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

from common import ROOT, load_records, write_json
from validate_data import validate_repository


def build_index() -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sources": load_records("sources"),
        "claims": load_records("claims"),
        "skills": load_records("skills"),
        "frameworks": load_records("frameworks"),
    }


def _make_writable_and_retry(function, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def build_site(output: Path) -> None:
    output = output.resolve()
    root = ROOT.resolve()
    if root not in output.parents and output != root:
        raise ValueError(f"Refusing to build outside repository: {output}")

    errors = validate_repository()
    if errors:
        raise SystemExit("Validation failed. Run scripts/validate_data.py for details.")

    if output.exists():
        shutil.rmtree(output, onerror=_make_writable_and_retry)
    output.mkdir(parents=True)

    site_dir = ROOT / "site"
    for item in site_dir.iterdir():
        target = output / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    write_json(output / "data" / "index.json", build_index())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static dashboard output.")
    parser.add_argument("--output", default="public", help="Output directory.")
    args = parser.parse_args()
    build_site(ROOT / args.output)
    print(f"Built {args.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
