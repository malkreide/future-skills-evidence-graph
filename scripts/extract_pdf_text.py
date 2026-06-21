"""Optional PDF -> plaintext helper for the report importer.

This is deliberately SEPARATE from scripts/ingest_reports.py: the importer takes
plaintext so it stays deterministic and free of a binary PDF dependency. An
operator runs this helper once to turn a downloaded OECD/WEF/UNESCO PDF into the
plaintext the importer (or the ingest-reports workflow) then consumes.

``pypdf`` is imported lazily and only inside ``extract_text``; the text cleaning
(``clean_extracted_text``) is pure standard library and unit-tested directly, so
the dependency is only needed when actually parsing a PDF.

    python scripts/extract_pdf_text.py --pdf report.pdf --output report.txt
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path


# Intra-word hyphenation at a line break ("curricu-\nlum" -> "curriculum") is the
# most common PDF-extraction artifact that corrupts a later verbatim match, so it
# is rejoined; the Unicode soft hyphen (U+00AD) is dropped likewise.
_LINEBREAK_HYPHEN = re.compile(r"­|(?<=\w)-\n(?=\w)")
_SOFT_HYPHEN = re.compile("­")


def clean_extracted_text(text: str) -> str:
    """Tidy raw extracted PDF text into readable, match-friendly plaintext.

    NFKC-folds compatibility forms (ligatures, full-width chars), rejoins
    hyphenated line breaks, collapses intra-line whitespace, and squeezes runs of
    blank lines to a single blank line so paragraph structure survives. Wording is
    preserved; this only removes extraction noise.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SOFT_HYPHEN.sub("", text)
    text = _LINEBREAK_HYPHEN.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned + "\n" if cleaned else ""


def extract_text(pdf_path: Path) -> str:
    """Extract cleaned plaintext from *pdf_path* (lazy ``pypdf`` dependency)."""
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - exercised only without pypdf
        raise SystemExit(
            "PDF extraction needs the optional 'pypdf' package: pip install pypdf"
        ) from exc

    reader = pypdf.PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return clean_extracted_text("\n\n".join(pages))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract cleaned plaintext from a report PDF (for ingest_reports.py)."
    )
    parser.add_argument("--pdf", required=True, help="Path to the report PDF.")
    parser.add_argument(
        "--output", default=None, help="Plaintext output path (default: stdout)."
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF {pdf_path} does not exist.", file=sys.stderr)
        return 1

    text = extract_text(pdf_path)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {len(text)} characters of plaintext to {args.output}.")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
