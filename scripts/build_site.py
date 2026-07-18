from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

from common import ROOT, load_records, write_json
from validate_data import validate_repository

# Matches local CSS/JS references in the HTML, e.g. src="./assets/app.js".
# External URLs and data: URIs never match because they lack an assets/ segment.
_ASSET_REF = re.compile(r'(src|href)="((?:\.?/)?assets/[^"?]+\.(?:css|js))"')


def _fingerprint_assets(output: Path) -> None:
    """Append a content hash query to local asset links so browsers refetch them
    after a change. Without this, the unversioned styles.css / app.js can stay
    cached and mix with freshly deployed HTML, breaking the layout."""

    def replace(match: re.Match[str]) -> str:
        attribute, ref = match.group(1), match.group(2)
        asset = output / "assets" / ref.split("assets/", 1)[1]
        try:
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:10]
        except OSError:
            return match.group(0)
        return f'{attribute}="{ref}?v={digest}"'

    for page in output.glob("*.html"):
        page.write_text(_ASSET_REF.sub(replace, page.read_text(encoding="utf-8")), encoding="utf-8")


# Fields the dashboard never renders, stripped from the shipped index. The
# abstracts dominate the payload (the client downloads and parses the WHOLE
# index on every visit), and the assist blocks are reviewer-only provenance.
# The versioned files in data/ keep every field — this trims the transport,
# not the record. site/assets/app.js reads: sources(title, url, publisher,
# year, source_type), claims(statement, evidence_*, text_anchor, *_skill_ids),
# skills(everything), frameworks(everything).
_DROPPED_SOURCE_FIELDS = ("abstract", "assist")
_DROPPED_CLAIM_FIELDS = ("assist",)


def _slim(records: list[dict], dropped: tuple[str, ...]) -> list[dict]:
    return [
        {key: value for key, value in record.items() if key not in dropped}
        for record in records
    ]


def build_index() -> dict[str, object]:
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sources": _slim(load_records("sources"), _DROPPED_SOURCE_FIELDS),
        "claims": _slim(load_records("claims"), _DROPPED_CLAIM_FIELDS),
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
    _fingerprint_assets(output)
    index = build_index()
    write_json(output / "data" / "index.json", index)
    # Winzige Meta-Datei nur mit generated_at, damit das Status-Panel den
    # Datenstand anzeigen kann, ohne die ganze (~324 KB) index.json erneut zu
    # laden. [PERF-004]
    write_json(output / "data" / "meta.json", {"generated_at": index["generated_at"]})


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static dashboard output.")
    parser.add_argument("--output", default="public", help="Output directory.")
    args = parser.parse_args()
    build_site(ROOT / args.output)
    print(f"Built {args.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
