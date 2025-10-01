"""
generate_order_forms.py
=======================

This script generates an order form PDF for each row in a CSV input file,
mirroring the layout of a provided sample form.  It reads values from
named columns such as ``Comment``, ``Support Troop Amount``, ``LastName``,
``FirstName``, ``Town``, ``Street Address``, ``EmailAddress``, ``Number of
Bags`` and ``Delivery Route``.  The resulting forms are saved as PDF
files in a specified output directory, one file per record.

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
* **ID** – a sequential identifier based on the record's position in the input.
* **Special Instructions** – the ``Delivery Instructions`` column, if present.

Usage
-----

Run the script from a command prompt.  It requires the Pillow library
(available by default in this environment).  Example:

    python generate_order_forms.py --input new-data.csv --output forms

This creates a directory called ``forms`` (if it does not already exist)
and writes one PDF per row using the naming convention ``form_<ID>.pdf``.
The ID field corresponds to the sequential order of the records.

"""

import argparse
import csv
import os
import re
from typing import List, Dict, Any, Optional

from PIL import Image, ImageDraw, ImageFont

# Page dimensions in points (1 pt = 1/72 in).  8.5×11 in page.
PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def parse_order_records(path: str) -> List[Dict[str, Any]]:
    """Parse relevant fields from the CSV input file.

    Parameters
    ----------
    path : str
        Path to the CSV file.

    Returns
    -------
    list[dict]
        A list of dictionaries containing the extracted fields for each
        record.  The order of the records is preserved.
    """
    records: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            record: Dict[str, Any] = {}
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
            # ID (sequential)
            record["id"] = idx
            # Special instructions
            record["instructions"] = row.get("Delivery Instructions", "").strip()
            records.append(record)
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
        draw.rectangle([ (field_x, y_pos - 6), (field_x + box_width, y_pos - 6 + box_height) ], outline=(0, 0, 0), width=1)
        # value text
        text_offset_y = y_pos - 6 + 4
        draw.text((field_x + 4, text_offset_y), value, font=fonts["value"], fill=(0, 0, 0))
        return y_pos + 40

    # Row: Order # (small box) and Amount Supporting (two-column row)
    # Draw Order # label and field
    draw.text((36, y), "Order #", font=fonts["label"], fill=(0, 0, 0))
    order_field_x = 110
    order_field_width = 80
    draw.rectangle([(order_field_x, y - 6), (order_field_x + order_field_width, y - 6 + 24)], outline=(0, 0, 0), width=1)
    draw.text((order_field_x + 4, y - 6 + 4), record.get("order_no", ""), font=fonts["value"], fill=(0, 0, 0))
    # Draw Amount Supporting label and field
    amt_label_x = 230
    draw.multiline_text((amt_label_x, y), "Amount Supporting\nBSA Troop 1865", font=fonts["label"], fill=(0, 0, 0), spacing=2)
    amt_field_x = 430
    amt_field_width = 100
    draw.rectangle([(amt_field_x, y - 6), (amt_field_x + amt_field_width, y - 6 + 24)], outline=(0, 0, 0), width=1)
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
    draw.rectangle([(instructions_x, instructions_y), (instructions_x + instructions_width, instructions_y + instructions_height)], outline=(0, 0, 0), width=1)
    # Wrap and draw instructions text
    instructions = record.get("instructions", "")
    if instructions:
        # Simple word wrap: break text into lines that fit within the box
        words = instructions.split()
        lines: List[str] = []
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            # measure width: use textbbox or fallback to font.getsize() for compatibility
            try:
                # textbbox returns (x0, y0, x1, y1)
                bbox = draw.textbbox((0, 0), test, font=fonts["value"])
                w_width = bbox[2] - bbox[0]
            except AttributeError:
                # Fallback for older Pillow versions: use font.getsize
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
    draw.rectangle([(route_field_x, y - 6), (route_field_x + route_field_width, y - 6 + 24)], outline=(0, 0, 0), width=1)
    draw.text((route_field_x + 4, y - 6 + 4), record.get("route", ""), font=fonts["value"], fill=(0, 0, 0))
    # ID placed to the right of the route field
    id_label_x = route_field_x + route_field_width + 40
    draw.text((id_label_x, y), "ID", font=fonts["label"], fill=(0, 0, 0))
    id_field_x = id_label_x + 30
    id_field_width = 60
    draw.rectangle([(id_field_x, y - 6), (id_field_x + id_field_width, y - 6 + 24)], outline=(0, 0, 0), width=1)
    draw.text((id_field_x + 4, y - 6 + 4), str(record.get("id", "")), font=fonts["value"], fill=(0, 0, 0))
    y += 40

    # Bottom line: static text
    bottom_text = "For delivery questions or issues email troop1865mulch@gmail.com"
    # Measure width of bottom text using textbbox or fallback
    try:
        bbox = draw.textbbox((0, 0), bottom_text, font=fonts["small"])
        text_width = bbox[2] - bbox[0]
    except AttributeError:
        text_width, _ = fonts["small"].getsize(bottom_text)
    draw.text((36, PAGE_HEIGHT - 40), bottom_text, font=fonts["small"], fill=(100, 100, 100))
    return img


def save_order_forms(records: List[Dict[str, Any]], output_dir: str) -> None:
    """Generate and save order form PDFs for all records.

    Parameters
    ----------
    records : list[dict]
        Parsed records with fields to populate.
    output_dir : str
        Directory where the PDFs will be saved.  Created if missing.
    """
    fonts = load_fonts()
    os.makedirs(output_dir, exist_ok=True)
    for rec in records:
        img = draw_order_form(rec, fonts)
        file_name = f"form_{rec['id']}.pdf"
        out_path = os.path.join(output_dir, file_name)
        # Save as PDF.  Pillow will convert the RGB image to a single-page PDF.
        img.save(out_path, "PDF")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate individual order form PDFs from a CSV input.")
    parser.add_argument("--input", required=True, help="Path to the CSV file containing order data.")
    parser.add_argument("--output", required=True, help="Directory to write the order form PDFs.")
    args = parser.parse_args()
    records = parse_order_records(args.input)
    if not records:
        print("No records found in the input file.")
        return
    save_order_forms(records, args.output)
    print(f"Generated {len(records)} order form(s) in '{args.output}'.")


if __name__ == "__main__":
    main()