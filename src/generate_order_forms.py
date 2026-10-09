"""
generate_order_forms.py
=======================

This script generates order form PDFs from the season spreadsheet
(``.xlsx``, first sheet by default, or a CSV export), grouped by
``Delivery Route``.  Only rows with a positive ``Number of Bags`` are
treated as orders, so the full season export can be used directly.
Each delivery route produces one combined PDF
containing all order forms for that route, named after the route (e.g.
``Fairfax_12B.pdf``).  It reads values from named columns such as
``Comment``, ``Support Troop Amount``, ``LastName``, ``FirstName``,
``Town``, ``Street Address``, ``EmailAddress``, ``Number of Bags`` and
``Delivery Route``.

Fields and their mapping
-----------------------

* **Order #** – extracted from the ``Comment`` column by removing the
  prefix ``"Order "`` and taking the subsequent digits.  If no such
  pattern is found, the field is left blank.
* **Amount Supporting BSA Troop 1865** – the value from the ``Support Troop Amount`` column.
* **Delivery Customer** – composed from ``LastName`` followed by a comma and
  ``FirstName``.
* **Delivery City** – the ``Town`` column.
* **Delivery Address** – the ``Street Address`` column.
* **Buyer's Email** – the ``EmailAddress`` column.
* **Bags** – the ``Number of Bags`` column.
* **Route** – the ``Delivery Route`` column.
* **ID** – a sequential identifier based on the order's position in the input.
* **Stop** – "3 of 7": the stop's place on its route's single pass (with
  ``--stop-order``, made by ``route_order.py``).  The route's pages are
  printed in that order.
* **Special Instructions** – the ``Delivery Instructions`` column, if present.

Usage
-----

Run the script from a command prompt.  It requires the Pillow library
(available by default in this environment).  Example:

    python generate_order_forms.py --input "Mulch Sales - Fall 2026.xlsx" --output forms

This creates a directory called ``forms`` (if it does not already exist)
and writes one PDF per delivery route (e.g. ``Fairfax_12B.pdf``), each
containing all order form pages for that route.

"""

import argparse
import os
import re
from collections import OrderedDict
from typing import List, Dict, Any, Optional

from PIL import Image, ImageDraw, ImageFont

from route_order import in_stop_order, load_stop_order, stop_label
from sheet_reader import read_rows

# Page dimensions in points (1 pt = 1/72 in).  8.5x11 in page.
PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def is_order_row(row: Dict[str, str]) -> bool:
    """Return True if a spreadsheet row is an actual order.

    The season export is the full customer list, so only rows with a
    positive ``Number of Bags`` and a name or address are orders.  This
    also skips the summary rows (Totals, Pallets, ...) at the bottom.
    """
    bags = (row.get("Number of Bags") or "").strip()
    if not re.fullmatch(r"\d+", bags) or int(bags) == 0:
        return False
    return bool((row.get("LastName") or "").strip() or (row.get("Street Address") or "").strip())


def parse_order_records(path: str, sheet: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse relevant fields from the season spreadsheet.

    Parameters
    ----------
    path : str
        Path to the ``.xlsx`` workbook or a CSV export of it.
    sheet : str | None
        Worksheet name for Excel input; defaults to the first sheet.

    Returns
    -------
    list[dict]
        A list of dictionaries containing the extracted fields for each
        record.  The order of the records is preserved.
    """
    rows, _ = read_rows(path, sheet)
    if not rows:
        return []
    # Find the header row: the season sheet has a title row
    # (e.g. "Fall 2026") before the column names.
    header_row_idx = 0
    for i, candidate in enumerate(rows[:10]):
        if "LastName" in [c.strip() for c in candidate]:
            header_row_idx = i
            break
    header = [c.strip() for c in rows[header_row_idx]]

    records: List[Dict[str, Any]] = []
    for row_idx in range(header_row_idx + 1, len(rows)):
        row = dict(zip(header, rows[row_idx]))
        if not is_order_row(row):
            continue
        record: Dict[str, Any] = {"row": row_idx + 1}  # the row number in the sheet
        # Order number: extract digits following "Order "
        comment = row.get("Comment", "") or ""
        order_no = ""
        match = re.search(r"Order\s+(\d+)", comment)
        if match:
            order_no = match.group(1)
        record["order_no"] = order_no
        # Amount supporting troop
        record["amount_support"] = row.get("Support Troop Amount", "").strip()
        # Delivery customer: LastName, FirstName
        last = row.get("LastName", "").strip()
        first = row.get("FirstName", "").strip()
        customer = ", ".join(filter(None, [last, first])) if last or first else ""
        record["customer"] = customer
        # Delivery city
        record["city"] = row.get("Town", "").strip()
        # Delivery address
        record["address"] = row.get("Street Address", "").strip()
        # Buyer email
        record["email"] = row.get("EmailAddress", "").strip()
        # Bags
        record["bags"] = row.get("Number of Bags", "").strip()
        # Route
        record["route"] = row.get("Delivery Route", "").strip()
        # ID (sequential among orders)
        record["id"] = len(records) + 1
        # Special instructions.  The fallback font has no em/en dash (it
        # prints a box), so use a hyphen.
        record["instructions"] = (
            row.get("Delivery Instructions", "").strip().replace("\u2014", " - ").replace("\u2013", "-")
        )
        records.append(record)
        # Flag rows that must be fixed in the sheet before the final print.
        who = f"{record['customer']} ({record['route']})"
        if record["instructions"].upper() == "TBD":
            print(f"WARNING: {who}: Delivery Instructions are still 'TBD'.")
        if not row.get("Map Link", "").strip():
            print(f"WARNING: {who}: no Map Link; no map page will be printed.")
    return records


def load_fonts() -> Dict[str, ImageFont.FreeTypeFont]:
    """Load the fonts used in the form.

    Returns
    -------
    dict
        A dictionary mapping names to PIL font objects.
    """
    fonts: Dict[str, ImageFont.FreeTypeFont] = {}
    # Paths to TrueType fonts.  Use DejaVu Sans for both labels and values.
    # If the fonts are unavailable, PIL will fall back to a default font.
    try:
        fonts["label"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        fonts["value"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        fonts["small"] = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except Exception:
        # Fallback to default font if DejaVuSans is not available
        fonts["label"] = ImageFont.load_default()
        fonts["value"] = ImageFont.load_default()
        fonts["small"] = ImageFont.load_default()
    return fonts


def draw_order_form(record: Dict[str, Any], fonts: Dict[str, ImageFont.FreeTypeFont]) -> Image.Image:
    """Create an image representing the order form for a single record.

    Parameters
    ----------
    record : dict
        A dictionary with the extracted fields.
    fonts : dict
        A dictionary of PIL font objects.

    Returns
    -------
    PIL.Image
        An RGB image containing the rendered form.
    """
    # Create a white background image
    img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    # Use a lighter border colour for rectangles.  This produces a
    # subtler border on the printed PDF akin to the sample form.  A
    # tuple of three equal RGB values yields a shade of grey.
    border_color = (150, 150, 150)
    # Draw top horizontal bar
    bar_height = 4
    draw.rectangle([(0, 40), (PAGE_WIDTH, 40 + bar_height)], fill=(230, 230, 230))

    # Baseline for the first row
    y = 70

    # Helper to draw a label and its value box with text
    def draw_row(label: str, value: str, y_pos: int, field_width: int = 362, x_label: int = 36, x_field: int = 200, height: int = 24, small_box: bool = False):
        # label
        draw.text((x_label, y_pos), label, font=fonts["label"], fill=(0, 0, 0))
        # field rectangle
        box_height = height
        box_width = field_width if not small_box else 80
        # adjust x_field for small boxes if specified
        field_x = x_field if not small_box else x_field
        draw.rectangle([
            (field_x, y_pos - 6),
            (field_x + box_width, y_pos - 6 + box_height),
        ], outline=border_color, width=1)
        # value text
        text_offset_y = y_pos - 6 + 4
        draw.text((field_x + 4, text_offset_y), value, font=fonts["value"], fill=(0, 0, 0))
        return y_pos + 40

    # Row: Order # (small box) and Amount Supporting (two-column row)
    # Draw Order # label and field
    draw.text((36, y), "Order #", font=fonts["label"], fill=(0, 0, 0))
    order_field_x = 110
    order_field_width = 80
    draw.rectangle(
        [
            (order_field_x, y - 6),
            (order_field_x + order_field_width, y - 6 + 24),
        ],
        outline=border_color,
        width=1,
    )
    draw.text((order_field_x + 4, y - 6 + 4), record.get("order_no", ""), font=fonts["value"], fill=(0, 0, 0))
    # Draw Amount Supporting label and field
    amt_label_x = 230
    draw.multiline_text((amt_label_x, y), "Amount Supporting\nBSA Troop 1865", font=fonts["label"], fill=(0, 0, 0), spacing=2)
    amt_field_x = 430
    amt_field_width = 100
    draw.rectangle(
        [
            (amt_field_x, y - 6),
            (amt_field_x + amt_field_width, y - 6 + 24),
        ],
        outline=border_color,
        width=1,
    )
    draw.text((amt_field_x + 4, y - 6 + 4), record.get("amount_support", ""), font=fonts["value"], fill=(0, 0, 0))
    y += 40

    # Delivery Customer
    y = draw_row("Delivery Customer", record.get("customer", ""), y)
    # Delivery City
    y = draw_row("Delivery City", record.get("city", ""), y)
    # Delivery Address
    y = draw_row("Delivery Address", record.get("address", ""), y)
    # Buyer's Email
    y = draw_row("Buyer's Email", record.get("email", ""), y)
    # Bags (small box)
    y = draw_row("Bags", record.get("bags", ""), y, field_width=362, small_box=True)

    # Special Instructions
    # Label
    draw.text((36, y), "Special Instructions", font=fonts["label"], fill=(0, 0, 0))
    instructions_y = y - 6
    instructions_x = 200
    instructions_width = PAGE_WIDTH - instructions_x - 36
    instructions_height = 180
    # Draw the instruction box
    draw.rectangle(
        [
            (instructions_x, instructions_y),
            (instructions_x + instructions_width, instructions_y + instructions_height),
        ],
        outline=border_color,
        width=1,
    )
    # Wrap and draw instructions text
    instructions = record.get("instructions", "")
    if instructions:
        # Simple word wrap: break text into lines that fit within the box
        words = instructions.split()
        lines: List[str] = []
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            # measure width using textbbox if available, otherwise fallback to font.getsize
            try:
                bbox = draw.textbbox((0, 0), test, font=fonts["value"])
                w_width = bbox[2] - bbox[0]
            except AttributeError:
                w_width, _ = fonts["value"].getsize(test)
            if w_width < instructions_width - 8:
                line = test
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        # Draw each line within the instructions box
        text_y = instructions_y + 4
        for ln in lines:
            draw.text((instructions_x + 4, text_y), ln, font=fonts["value"], fill=(0, 0, 0))
            text_y += 16
    y = y + instructions_height + 40

    # Route and ID row
    draw.text((36, y), "Route", font=fonts["label"], fill=(0, 0, 0))
    route_field_x = 100
    route_field_width = 140
    draw.rectangle(
        [
            (route_field_x, y - 6),
            (route_field_x + route_field_width, y - 6 + 24),
        ],
        outline=border_color,
        width=1,
    )
    draw.text((route_field_x + 4, y - 6 + 4), record.get("route", ""), font=fonts["value"], fill=(0, 0, 0))
    # ID placed to the right of the route field
    id_label_x = route_field_x + route_field_width + 40
    draw.text((id_label_x, y), "ID", font=fonts["label"], fill=(0, 0, 0))
    id_field_x = id_label_x + 30
    id_field_width = 60
    draw.rectangle(
        [
            (id_field_x, y - 6),
            (id_field_x + id_field_width, y - 6 + 24),
        ],
        outline=border_color,
        width=1,
    )
    draw.text((id_field_x + 4, y - 6 + 4), str(record.get("id", "")), font=fonts["value"], fill=(0, 0, 0))
    # Stop number on the route's single pass, to the right of the ID
    if record.get("stop"):
        stop_label_x = id_field_x + id_field_width + 40
        draw.text((stop_label_x, y), "Stop", font=fonts["label"], fill=(0, 0, 0))
        stop_field_x = stop_label_x + 40
        stop_field_width = 80
        draw.rectangle(
            [
                (stop_field_x, y - 6),
                (stop_field_x + stop_field_width, y - 6 + 24),
            ],
            outline=border_color,
            width=1,
        )
        draw.text((stop_field_x + 4, y - 6 + 4), record["stop"], font=fonts["value"], fill=(0, 0, 0))
    y += 40

    # Bottom line: static text
    bottom_text = "For delivery questions or issues email troop1865mulch@gmail.com"
    # Measure width of the bottom text using textbbox or font.getsize
    try:
        bbox2 = draw.textbbox((0, 0), bottom_text, font=fonts["small"])
        text_width = bbox2[2] - bbox2[0]
    except AttributeError:
        text_width, _ = fonts["small"].getsize(bottom_text)
    draw.text((36, PAGE_HEIGHT - 40), bottom_text, font=fonts["small"], fill=(100, 100, 100))
    return img


def route_groups(
    records: List[Dict[str, Any]], stops: Optional[Dict[int, Any]] = None
) -> "OrderedDict[str, List[Dict[str, Any]]]":
    """Group records by delivery route, in the order their pages are printed.

    With ``stops`` (see ``route_order.load_stop_order``) each route's
    records are in stop order and get their ``"stop"`` ("3 of 7").
    """
    groups: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
    for rec in records:
        groups.setdefault(rec.get("route", "") or "", []).append(rec)
    for route_key, group in groups.items():
        groups[route_key] = in_stop_order(group, lambda r: r.get("row"), stops)
        for rec in groups[route_key]:
            rec["stop"] = stop_label(rec.get("row"), stops)
    return groups


def save_order_forms(
    records: List[Dict[str, Any]], output_dir: str, stops: Optional[Dict[int, Any]] = None
) -> None:
    """Generate and save order form PDFs grouped by delivery route.

    Parameters
    ----------
    records : list[dict]
        Parsed records with fields to populate.
    output_dir : str
        Directory where the PDFs will be saved.  Created if missing.
    stops : dict | None
        Stop order (``route_order.load_stop_order``); pages are printed in
        stop order and numbered "Stop 3 of 7".

    Notes
    -----
    Records are grouped by ``Delivery Route``.  Each route produces one
    combined PDF containing all order form pages for that route, named
    after the route (e.g. ``Fairfax_12B.pdf``).
    """
    fonts = load_fonts()
    os.makedirs(output_dir, exist_ok=True)
    for route_key, group in route_groups(records, stops).items():
        base_name = re.sub(r"[^A-Za-z0-9]+", "_", route_key.strip()) if route_key else "orders"
        if not base_name:
            base_name = "orders"
        out_path = os.path.join(output_dir, f"{base_name}.pdf")
        # Write all pages in one go.  Merging one single-page PDF per order
        # with PyPDF2 mixed up pages (some orders printed twice, others
        # missing) because every page's objects have the same numbers.
        images = [draw_order_form(rec, fonts) for rec in group]
        images[0].save(out_path, format="PDF", save_all=True, append_images=images[1:])
        print(f"Wrote {len(group)} page(s) to '{out_path}'.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate order form PDFs from the season spreadsheet, grouped by "
        "Delivery Route.  One combined PDF per route, named after the route."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the season spreadsheet (.xlsx) or a CSV export of it.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Directory to write the order form PDFs.",
    )
    parser.add_argument(
        "--sheet",
        help="Worksheet to read from an .xlsx input (default: the first sheet).",
    )
    parser.add_argument(
        "--stop-order",
        help="Stop order file from route_order.py: print each route's forms in that order.",
    )
    args = parser.parse_args()
    records = parse_order_records(args.input, args.sheet)
    if not records:
        print("No records found in the input file.")
        return
    stops = load_stop_order(args.stop_order) if args.stop_order else None
    save_order_forms(records, args.output, stops)


if __name__ == "__main__":
    main()