"""Hand a blind second-rater worksheet out as Excel, and read it back.

The worksheets that scripts/eval_agreement.py writes are JSON, which is
right for the scorer and wrong for most raters: filling one in means typing
quoted strings into a text editor, and a single dropped quote makes the whole
file unreadable. This module wraps the same worksheet in an .xlsx with a
drop-down per field, and turns the filled workbook back into exactly the JSON
--second-rater expects.

    python scripts/worksheet_xlsx.py export eval/claim_prefill_calibration.json --out bogen.xlsx
    python scripts/worksheet_xlsx.py import bogen_ausgefuellt.xlsx --out eval/..._completed.json

Three properties carry the design, because each one guards the measurement
rather than the convenience:

* **The workbook is built from a BLANK worksheet only.** Exporting refuses a
  file that already holds a rated value, so the labelled eval set cannot be
  handed out by mistake -- that would give the rater the answers.
* **The rater can change answers and nothing else.** The case list, the
  rubric and the protocol travel inside the workbook as the exact JSON it
  was made from, with a checksum. Import fills answers into that original
  rather than rebuilding it from the sheet, so a deleted row, an edited
  abstract or a stale rules version is an error, not a silent change of
  instrument.
* **Excel's own conversions are caught, not trusted.** A typed "10-12"
  becomes 10 December in many locales. The age columns are stored as text,
  and import rejects a date or a number where a band belongs instead of
  converting it back and guessing.

openpyxl is imported lazily: the rest of the pipeline stays standard-library
only, and only exporting or importing a workbook needs it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import appraisal

FORMAT_VERSION = 1

# Which drop-down each rated field gets. Fields not listed here are free
# text; the only ones today are the two age bands, and they are checked on
# import against the same pattern validate_appraisal() uses.
VOCABULARIES: dict[str, tuple[str, ...]] = {
    "evidence_certainty": tuple(appraisal.CERTAINTY_VALUES),
    "claim_type": tuple(appraisal.CLAIM_TYPE_VALUES),
    "claim_supported_by_source": tuple(appraisal.CLAIM_SUPPORT_VALUES),
    "study_design": tuple(appraisal.STUDY_DESIGN_VALUES),
    "effect_direction": tuple(appraisal.EFFECT_DIRECTION_VALUES),
    # The legacy three-level scale, rated alongside so the two can be
    # compared on the same reading. Not in the appraisal module because it
    # is no longer part of the appraisal.
    "evidence_strength": ("low", "moderate", "strong"),
}
AGE_FIELDS = frozenset({"age_range_explicit", "age_range"})
AGE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")

# German column hints. The header keeps the raw field name, because that is
# what the rubric sheet explains; the hint only says which question it is.
FIELD_HINTS = {
    "evidence_certainty": "Wie sicher?",
    "claim_type": "Art der Aussage",
    "claim_supported_by_source": "Deckt die Quelle sie?",
    "study_design": "Studiendesign",
    "effect_direction": "Richtung des gemessenen Effekts",
    "age_range_explicit": "Alter, nur wörtlich genannt (von-bis)",
    "evidence_strength": "ALT: Evidenzstärke",
    "age_range": "ALT: Alter inkl. Schätzung (von-bis)",
}
CONTEXT_LABELS = {
    "statement": "Aussage",
    "source_title": "Titel der Quelle",
    "abstract": "Abstract",
    "source_type": "Publikationstyp",
}
CONTEXT_WIDTHS = {"statement": 42, "source_title": 30, "abstract": 70, "source_type": 16}

SHEET_INSTRUCTIONS = "Anleitung"
SHEET_RATING = "Bewertung"
SHEET_RUBRIC = "Rubrik"
SHEET_LISTS = "Listen"
SHEET_META = "_meta"

# Where the protocol inputs sit on the instructions sheet. Named once so
# export and import cannot disagree about a cell address.
PROTOCOL_CELLS = {
    "rater": "C12",
    "labeled_at": "C13",
    "blind": "C14",
    "notes": "C15",
}

# One cell holds at most 32,767 characters. The catalogue worksheet is
# ~91,000, so the embedded original is split across a column.
CHUNK = 30_000

FONT = "Arial"


class WorkbookError(ValueError):
    """The workbook cannot be turned back into a worksheet as it stands.

    Carries every problem found, not just the first, so a rater who has to
    fix their file gets one list rather than one round trip per mistake.
    """

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def _openpyxl():
    try:
        import openpyxl  # noqa: PLC0415 -- deliberately lazy, see module docstring
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "openpyxl is needed to export or import a workbook: "
            "pip install -r requirements-dev.txt"
        ) from exc
    return openpyxl


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _col(index: int) -> str:
    """1-based column number to letters (1 -> A, 27 -> AA)."""
    letters = ""
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _layout(worksheet: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Context columns and rated columns, in worksheet order.

    Derived rather than listed, because the two sets differ: the catalogue
    sheet shows the source title, the pre-fill sheet does not. Anything on
    an item that is not its key and not a rated field is context the rater
    reads.
    """
    rated = list(worksheet["protocol"]["rated_fields"])
    first = worksheet["labels"][0]
    context = [k for k in first if k != "key" and k not in rated]
    return context, rated


def _refuse_filled(worksheet: dict[str, Any]) -> None:
    problems = []
    if "protocol" not in worksheet or "labels" not in worksheet:
        problems.append(
            "not a worksheet: expected 'protocol' and 'labels' as written by "
            "eval_agreement.py --worksheet"
        )
    else:
        rated = worksheet["protocol"].get("rated_fields") or []
        for item in worksheet["labels"]:
            filled = [f for f in rated if item.get(f) is not None]
            if filled:
                problems.append(f"{item.get('key')}: already carries {filled}")
        if worksheet["protocol"].get("rater"):
            problems.append("protocol.rater is set -- this is a completed pass")
    if problems:
        raise WorkbookError(
            ["Refusing to export: only a BLANK worksheet may be handed out, "
             "or the rater would see answers."] + problems
        )


def export_workbook(worksheet: dict[str, Any], out: Path) -> None:
    """Write a blank worksheet as an .xlsx for a rater to fill in."""
    _refuse_filled(worksheet)
    openpyxl = _openpyxl()
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation

    original = json.dumps(worksheet, ensure_ascii=False, indent=2)
    context, rated = _layout(worksheet)
    protocol = worksheet["protocol"]
    n = len(worksheet["labels"])

    base = Font(name=FONT, size=10)
    bold = Font(name=FONT, size=10, bold=True)
    title = Font(name=FONT, size=14, bold=True)
    muted = Font(name=FONT, size=9, color="666666")
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    input_fill = PatternFill("solid", fgColor="FFF2CC")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap_top = Alignment(wrap_text=True, vertical="top")
    unlocked = Protection(locked=False)

    wb = openpyxl.Workbook()

    # --- Lists (hidden): one column per vocabulary, reached through names.
    lists = wb.active
    lists.title = SHEET_LISTS
    for col, (field, values) in enumerate(VOCABULARIES.items(), start=1):
        if field not in rated:
            continue
        letter = _col(col)
        for row, value in enumerate(values, start=1):
            lists.cell(row=row, column=col, value=value)
        ref = f"'{SHEET_LISTS}'!${letter}$1:${letter}${len(values)}"
        wb.defined_names[f"lst_{field}"] = DefinedName(f"lst_{field}", attr_text=ref)
    lists.cell(row=1, column=len(VOCABULARIES) + 1, value="ja")
    lists.cell(row=2, column=len(VOCABULARIES) + 1, value="nein")
    yn = _col(len(VOCABULARIES) + 1)
    wb.defined_names["lst_blind"] = DefinedName(
        "lst_blind", attr_text=f"'{SHEET_LISTS}'!${yn}$1:${yn}$2"
    )
    lists.sheet_state = "veryHidden"

    # --- Rating sheet: one row per case.
    ws = wb.create_sheet(SHEET_RATING)
    headers = ["Nr", "Fall-ID"] + [CONTEXT_LABELS.get(c, c) for c in context] + rated
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font, cell.fill, cell.border, cell.alignment = bold, header_fill, box, wrap_top
    first_rated_col = 3 + len(context)
    for offset, field in enumerate(rated):
        hint = FIELD_HINTS.get(field)
        if hint:
            ws.cell(row=1, column=first_rated_col + offset).comment = Comment(hint, "Bogen")

    for row, item in enumerate(worksheet["labels"], start=2):
        ws.cell(row=row, column=1, value=row - 1)
        ws.cell(row=row, column=2, value=item["key"]).font = muted
        lines = 1
        for offset, field in enumerate(context):
            value = item.get(field)
            ws.cell(row=row, column=3 + offset, value=value)
            width = CONTEXT_WIDTHS.get(field, 20)
            lines = max(lines, math.ceil(len(str(value or "")) / (width * 1.15)))
        for col in range(1, first_rated_col):
            cell = ws.cell(row=row, column=col)
            cell.border, cell.alignment = box, wrap_top
            if col != 2:
                cell.font = base
        for offset, field in enumerate(rated):
            cell = ws.cell(row=row, column=first_rated_col + offset)
            cell.fill, cell.border, cell.protection = input_fill, box, unlocked
            cell.font, cell.alignment = base, wrap_top
            if field in AGE_FIELDS:
                # Stored as text so Excel keeps "10-12" a band instead of
                # turning it into 10 December.
                cell.number_format = "@"
        ws.row_dimensions[row].height = min(409, max(30, 13 * lines + 6))

    last_row = n + 1
    for offset, field in enumerate(rated):
        letter = _col(first_rated_col + offset)
        rng = f"{letter}2:{letter}{last_row}"
        if field in VOCABULARIES:
            dv = DataValidation(
                type="list",
                formula1=f"=lst_{field}",
                allow_blank=True,
                showErrorMessage=True,
                errorTitle="Kein zulässiger Wert",
                error="Bitte einen Wert aus der Liste wählen oder die Zelle leer lassen.",
                promptTitle=field,
                prompt=(FIELD_HINTS.get(field, "") + ". Leer lassen = keine Angabe möglich.")[:255],
                showInputMessage=True,
            )
        else:
            dv = DataValidation(
                type="textLength",
                operator="lessThanOrEqual",
                formula1="5",
                allow_blank=True,
                showErrorMessage=True,
                errorTitle="Format von-bis",
                error='Altersspanne als "von-bis" in Jahren, z. B. 8-10. Sonst leer lassen.',
                promptTitle=field,
                prompt=(FIELD_HINTS.get(field, "") + '. Format "8-10". Leer lassen = keine Angabe.')[:255],
                showInputMessage=True,
            )
        dv.add(rng)
        ws.add_data_validation(dv)

    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 14
    # Hidden, not removed: import matches answers by this ID. Worksheets
    # now carry opaque IDs (eval_agreement.rater_key), so it no longer
    # leaks anything -- but a hash is noise to a rater, and the case
    # number is what they talk about. A workbook exported from an older
    # sheet still holds real IDs here, which is one more reason to hide it.
    ws.column_dimensions["B"].hidden = True
    for offset, field in enumerate(context):
        ws.column_dimensions[_col(3 + offset)].width = CONTEXT_WIDTHS.get(field, 20)
    for offset, field in enumerate(rated):
        ws.column_dimensions[_col(first_rated_col + offset)].width = (
            22 if field in VOCABULARIES else 14
        )
    ws.freeze_panes = ws.cell(row=2, column=first_rated_col)
    ws.protection.sheet = True
    ws.protection.formatColumns = False
    ws.protection.formatRows = False

    # --- Rubric sheet: the definitions carried by the worksheet, verbatim.
    rub = wb.create_sheet(SHEET_RUBRIC)
    for col, text in enumerate(("Feld", "Wert", "Bedeutung"), start=1):
        cell = rub.cell(row=1, column=col, value=text)
        cell.font, cell.fill, cell.border = bold, header_fill, box
    r = 2
    for key, value in worksheet.items():
        if not key.startswith("rubrik_"):
            continue
        field = key[len("rubrik_"):]
        entries = value.items() if isinstance(value, dict) else [("", value)]
        for level, text in entries:
            label = "Hinweis" if level == "_hinweis" else level
            for col, content in enumerate((field, label, text), start=1):
                cell = rub.cell(row=r, column=col, value=content)
                cell.font, cell.alignment, cell.border = base, wrap_top, box
            rub.row_dimensions[r].height = min(409, max(15, 13 * math.ceil(len(str(text)) / 95) + 4))
            r += 1
    rub.column_dimensions["A"].width = 26
    rub.column_dimensions["B"].width = 20
    rub.column_dimensions["C"].width = 90
    rub.freeze_panes = "A2"
    rub.protection.sheet = True
    rub.protection.formatColumns = False
    rub.protection.formatRows = False

    # --- Instructions sheet: first thing the rater sees.
    ins = wb.create_sheet(SHEET_INSTRUCTIONS, 0)
    kind = "Kalibrierrunde" if protocol.get("calibration_subset") else "Bewertungsdurchgang"
    ins["A1"] = f"Blinder Zweitbewertungsbogen – {kind}, {n} Fälle"
    ins["A1"].font = title
    text_rows = [
        ("A3", "So geht's", bold),
        ("A4", f"1. Im Blatt «{SHEET_RATING}» jede gelbe Zelle ausfüllen: Wert aus der Auswahlliste wählen.", base),
        ("A5", "2. Wo der Text keine Antwort hergibt, die Zelle LEER lassen. Das ist eine gültige Antwort, kein Ausweichen.", base),
        ("A6", f"3. Die Bedeutung jedes Werts steht im Blatt «{SHEET_RUBRIC}». Sie ist vollständig – bitte nichts anderes nachlesen.", base),
        ("A7", "4. Achtung Verwechslung: «null» in effect_direction heisst «kein Unterschied gefunden». Leer heisst «keine Angabe möglich».", base),
        ("A8", "5. Unten Name und Datum eintragen, Datei speichern und zurückschicken. Das ist keine Prüfung: gemessen wird die Rubrik, nicht du.", base),
        ("A10", "Protokoll (gelbe Felder ausfüllen)", bold),
        ("B12", "Name", base),
        ("B13", "Datum", base),
        ("B14", "Blind bewertet?", base),
        ("B15", "Notizen", base),
        ("D14", "«nein», falls du vorher Bewertungen aus dem Projekt gesehen hast.", muted),
        ("D15", "Alles, was die Blindheit einschränkt – auch grob geschätzt. Leer, wenn nichts.", muted),
    ]
    for ref, text, font in text_rows:
        ins[ref] = text
        ins[ref].font = font
    for field, ref in PROTOCOL_CELLS.items():
        cell = ins[ref]
        cell.fill, cell.border, cell.protection, cell.font = input_fill, box, unlocked, base
        cell.alignment = wrap_top
    ins[PROTOCOL_CELLS["blind"]] = "ja"
    ins[PROTOCOL_CELLS["labeled_at"]].number_format = "yyyy-mm-dd"
    blind_dv = DataValidation(type="list", formula1="=lst_blind", allow_blank=False)
    blind_dv.add(PROTOCOL_CELLS["blind"])
    ins.add_data_validation(blind_dv)
    ins.row_dimensions[15].height = 60

    # Progress, as a live formula so it counts what is actually filled.
    first_letter = _col(first_rated_col)
    last_letter = _col(first_rated_col + len(rated) - 1)
    ins["B17"] = "Ausgefüllt"
    ins["B17"].font = bold
    ins["C17"] = f"=COUNTA('{SHEET_RATING}'!{first_letter}2:{last_letter}{last_row})"
    ins["C17"].font = bold
    ins["D17"] = f"von {n * len(rated)} Zellen (leer lassen ist erlaubt – die Zahl ist nur eine Orientierung)"
    ins["D17"].font = muted

    # Format example. Invented, on a topic none of the rated cases touch,
    # and showing only entries that need no rubric judgement: a design the
    # text names outright, an age the text states, and an empty cell. A
    # first draft used a reading programme rated "low" -- one of the ten
    # calibration cases is a reading intervention, so the example would
    # have nudged exactly the answer being measured.
    ins["A19"] = "Formatbeispiel (erfundener Fall, wird nicht ausgewertet)"
    ins["A19"].font = bold
    example = [
        ("Aussage", "In einer randomisierten Studie mit Kindern im Alter von 8 bis 10 "
                    "Jahren verbesserte ein Schwimmkurs die Wassersicherheit.", ""),
        ("study_design", "rct", "Wert aus der Liste – hier nennt der Text das Design ausdrücklich"),
        ("age_range_explicit", "8-10", "Text «von-bis», nur wenn das Alter wörtlich im Text steht"),
        ("jedes Feld", "(leer)", "wenn der Text dazu keine Antwort hergibt"),
    ]
    for offset, (label, value, why) in enumerate(example, start=20):
        ins.cell(row=offset, column=2, value=label).font = muted
        ins.cell(row=offset, column=3, value=value).font = muted
        ins.cell(row=offset, column=4, value=why).font = muted
        ins.cell(row=offset, column=3).alignment = wrap_top
    ins.row_dimensions[20].height = 40
    ins.column_dimensions["A"].width = 3
    ins.column_dimensions["B"].width = 20
    ins.column_dimensions["C"].width = 40
    ins.column_dimensions["D"].width = 70
    for ref in ("A4", "A5", "A6", "A7", "A8"):
        ins[ref].alignment = Alignment(wrap_text=False, vertical="top")
    ins.protection.sheet = True

    # --- Meta (very hidden): the exact worksheet this was made from.
    meta = wb.create_sheet(SHEET_META)
    meta["A1"] = "format_version"
    meta["B1"] = FORMAT_VERSION
    meta["A2"] = "sha256"
    meta["B2"] = _checksum(original)
    meta["A3"] = "chunks"
    chunks = [original[i : i + CHUNK] for i in range(0, len(original), CHUNK)]
    meta["B3"] = len(chunks)
    for i, chunk in enumerate(chunks, start=5):
        meta.cell(row=i, column=1, value=chunk)
    meta.sheet_state = "veryHidden"
    meta.protection.sheet = True

    wb.active = wb.sheetnames.index(SHEET_INSTRUCTIONS)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


def _embedded_original(wb) -> dict[str, Any]:
    if SHEET_META not in wb.sheetnames:
        raise WorkbookError([f"no '{SHEET_META}' sheet -- not a workbook this script exported"])
    meta = wb[SHEET_META]
    if meta["B1"].value != FORMAT_VERSION:
        raise WorkbookError([f"workbook format {meta['B1'].value!r}, expected {FORMAT_VERSION}"])
    count = int(meta["B3"].value or 0)
    text = "".join(str(meta.cell(row=5 + i, column=1).value or "") for i in range(count))
    if _checksum(text) != meta["B2"].value:
        raise WorkbookError([
            "the embedded worksheet does not match its checksum -- the hidden "
            f"'{SHEET_META}' sheet was edited, so the instrument can no longer be "
            "identified. Ask for the original file."
        ])
    return json.loads(text)


def _answer(field: str, raw: Any, where: str, problems: list[str]) -> Any:
    """One cell to one worksheet value, or a recorded problem."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None
    if field in AGE_FIELDS:
        if isinstance(raw, (dt.date, dt.datetime)):
            problems.append(
                f"{where}: Excel hat die Eingabe als Datum ({raw:%d.%m.}) gespeichert. "
                'Bitte als Text "von-bis" eintragen, z. B. 8-10.'
            )
            return None
        if not isinstance(raw, str):
            problems.append(f'{where}: {raw!r} ist keine Altersspanne. Format "von-bis", z. B. 8-10.')
            return None
        if not AGE_RE.match(raw):
            problems.append(f'{where}: "{raw}" ist nicht im Format "von-bis", z. B. 8-10.')
            return None
        low, high = (int(x) for x in raw.split("-"))
        if low > high:
            problems.append(f'{where}: "{raw}" -- die untere Grenze ist grösser als die obere.')
            return None
        return raw
    allowed = VOCABULARIES.get(field)
    value = str(raw)
    if allowed is not None and value not in allowed:
        problems.append(f'{where}: "{value}" ist kein zulässiger Wert. Erlaubt: {", ".join(allowed)}.')
        return None
    return value


def _protocol_value(field: str, raw: Any, problems: list[str]) -> Any:
    if field == "labeled_at":
        if isinstance(raw, dt.datetime):
            return raw.date().isoformat()
        if isinstance(raw, dt.date):
            return raw.isoformat()
        text = str(raw or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            problems.append(
                f"{SHEET_INSTRUCTIONS}!{PROTOCOL_CELLS['labeled_at']}: Datum fehlt oder ist unlesbar "
                f"({text!r}). Bitte als Datum eintragen."
            )
        return text
    if field == "blind":
        text = str(raw or "").strip().lower()
        if text not in ("ja", "nein"):
            problems.append(f"{SHEET_INSTRUCTIONS}!{PROTOCOL_CELLS['blind']}: bitte «ja» oder «nein».")
            return True
        return text == "ja"
    text = "" if raw is None else str(raw).strip()
    if field == "rater" and not text:
        problems.append(f"{SHEET_INSTRUCTIONS}!{PROTOCOL_CELLS['rater']}: Name fehlt.")
    return text


def import_workbook(path: Path) -> dict[str, Any]:
    """Read a filled workbook back into the worksheet it was made from."""
    openpyxl = _openpyxl()
    wb = openpyxl.load_workbook(path, data_only=True)
    worksheet = _embedded_original(wb)
    context, rated = _layout(worksheet)
    first_rated_col = 3 + len(context)
    problems: list[str] = []

    if SHEET_RATING not in wb.sheetnames:
        raise WorkbookError([f"no '{SHEET_RATING}' sheet"])
    ws = wb[SHEET_RATING]
    header = [ws.cell(row=1, column=first_rated_col + i).value for i in range(len(rated))]
    if header != rated:
        raise WorkbookError([
            f"the answer columns are {header}, expected {rated} -- columns were "
            "moved or renamed, so answers cannot be matched to fields"
        ])

    expected = [item["key"] for item in worksheet["labels"]]
    answers: dict[str, dict[str, Any]] = {}
    for row in range(2, ws.max_row + 1):
        key = ws.cell(row=row, column=2).value
        if key is None or str(key).strip() == "":
            continue
        key = str(key).strip()
        if key not in expected:
            problems.append(f"{SHEET_RATING} Zeile {row}: unbekannte Fall-ID {key!r}")
            continue
        if key in answers:
            problems.append(f"{SHEET_RATING} Zeile {row}: Fall-ID {key!r} kommt doppelt vor")
            continue
        answers[key] = {
            field: _answer(
                field,
                ws.cell(row=row, column=first_rated_col + i).value,
                f"{SHEET_RATING} Zeile {row} ({field})",
                problems,
            )
            for i, field in enumerate(rated)
        }
    missing = [key for key in expected if key not in answers]
    if missing:
        problems.append(f"{SHEET_RATING}: Fälle fehlen: {', '.join(missing)}")

    ins = wb[SHEET_INSTRUCTIONS]
    protocol = {
        field: _protocol_value(field, ins[ref].value, problems)
        for field, ref in PROTOCOL_CELLS.items()
    }
    if problems:
        raise WorkbookError(problems)

    for item in worksheet["labels"]:
        item.update(answers[item["key"]])
    worksheet["protocol"].update(protocol)
    return worksheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="blank worksheet JSON -> .xlsx")
    exp.add_argument("worksheet")
    exp.add_argument("--out", required=True)
    imp = sub.add_parser("import", help="filled .xlsx -> worksheet JSON for --second-rater")
    imp.add_argument("workbook")
    imp.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            worksheet = json.loads(Path(args.worksheet).read_text(encoding="utf-8"))
            export_workbook(worksheet, Path(args.out))
            print(f"Wrote {args.out}")
        else:
            worksheet = import_workbook(Path(args.workbook))
            Path(args.out).write_text(
                json.dumps(worksheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"Wrote {args.out} -- score it with: "
                  f"python scripts/eval_agreement.py --second-rater {args.out}")
    except WorkbookError as exc:
        print("Nicht übernommen:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
