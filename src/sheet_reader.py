"""
sheet_reader.py
===============

Reads the season spreadsheet for both generator scripts.  Accepts either
the Excel workbook (``.xlsx``) or a CSV export of it, and returns the rows
as lists of strings in the same shape as ``csv.reader``.

For Excel input the values Excel cached for formula cells are used (e.g.
``Support Troop Amount`` is ``=2.65*Q3``), and the text colour is kept:
red text marks something that needs special action.  CSV exports lose
colour, so for CSV input the red text is unknown (``None``).
"""

import csv
import datetime
import os
from typing import Dict, List, Optional, Tuple

# (row index, column index) -> the red text in that cell, both 0-based.
RedText = Dict[Tuple[int, int], str]


def read_rows(path: str, sheet: Optional[str] = None) -> Tuple[List[List[str]], Optional[RedText]]:
    """Read all rows of a ``.xlsx`` sheet or a CSV file as strings.

    Parameters
    ----------
    path : str
        Path to the ``.xlsx`` workbook or CSV file.
    sheet : str | None
        Worksheet name for Excel input.  Defaults to the first sheet
        (``Customers`` in the season workbook).  Ignored for CSV.

    Returns
    -------
    tuple[list[list[str]], dict | None]
        The rows, and for Excel input the red text per cell (only cells
        that contain red text are present).  ``None`` for CSV input.
    """
    if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm"):
        return _read_xlsx(path, sheet)
    return _read_csv(path), None


def _read_csv(path: str) -> List[List[str]]:
    # Try UTF-8 first; fall back to cp1252 for Excel/Windows exports (e.g. 0x92 = smart quote).
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            if encoding == "latin-1":
                raise
    return []


def _read_xlsx(path: str, sheet: Optional[str]) -> Tuple[List[List[str]], RedText]:
    import warnings

    import openpyxl
    from openpyxl.cell.rich_text import CellRichText

    with warnings.catch_warnings():
        # The season workbook has a print header/footer openpyxl can't parse.
        warnings.simplefilter("ignore", UserWarning)
        wb = openpyxl.load_workbook(path, data_only=True, rich_text=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]

    rows: List[List[str]] = []
    red: RedText = {}
    for r, cells in enumerate(ws.iter_rows()):
        row: List[str] = []
        for c, cell in enumerate(cells):
            value = cell.value
            if isinstance(value, CellRichText):
                # Mixed formatting within the cell: keep only the red runs.
                # Runs without their own font use the cell's font.
                cell_red = _is_red(cell.font.color if cell.font else None)
                red_runs = [
                    str(block.text) if hasattr(block, "text") else str(block)
                    for block in value
                    if (_is_red(block.font.color) if getattr(block, "font", None) else cell_red)
                ]
                if red_runs:
                    red[(r, c)] = "".join(red_runs).strip()
                row.append(str(value))
                continue
            text = _format_value(value, cell.number_format)
            if text.strip() and _is_red(cell.font.color if cell.font else None):
                red[(r, c)] = text.strip()
            row.append(text)
        rows.append(row)
    wb.close()
    return rows, red


def _format_value(value, number_format: str) -> str:
    """Render a cell value as text, the way the CSV export would."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).upper()
    if isinstance(value, (int, float)):
        if "$" in (number_format or ""):
            return f"${value:,.2f}"
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.date().isoformat() if value.time() == datetime.time() else value.isoformat(" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _is_red(color) -> bool:
    """True for a font colour that is red (e.g. Excel's standard ``FF0000``)."""
    if color is None:
        return False
    if color.type == "rgb" and isinstance(color.rgb, str) and len(color.rgb) >= 6:
        rgb = color.rgb[-6:]
        try:
            r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return False
        return r >= 0xC0 and g < 0x60 and b < 0x60
    if color.type == "indexed":
        # Red in Excel's legacy indexed palette.
        return color.indexed in (2, 10)
    return False
