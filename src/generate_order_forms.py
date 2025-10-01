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
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from PyPDF2 import PdfReader, PdfWriter

# Import map printing utilities from generate_maps_pdf.  These functions
# provide the ability to create clean map PDF pages with headers and
# optional markers.  If generate_maps_pdf is not available on the
# import path, an ImportError will be raised at runtime.  Note that
# generate_maps_pdf itself imports optional dependencies (e.g. Selenium),
# so those must be installed when the combined PDF functionality is used.
try:
    import generate_maps_pdf as gmp  # type: ignore
except Exception:
    gmp = None  # type: ignore

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


def parse_input_records(path: str) -> List[Dict[str, Any]]:
    """Parse all relevant fields from the CSV file including map URL.

    This helper extends :func:`parse_order_records` by additionally extracting
    the Google Maps URL, delivery route label and bag count for each
    record.  It supports CSV files where column names correspond to the
    expected fields (e.g. ``"Map Link"``, ``"Delivery Route"``,
    ``"Number of Bags"``, etc.).  The function preserves the order of
    records and assigns a sequential ``id`` starting from 1.

    Parameters
    ----------
    path : str
        Path to the CSV input file.

    Returns
    -------
    list[dict]
        A list of dictionaries.  Each dictionary contains the fields
        returned by :func:`parse_order_records` plus ``map_url``,
        ``route`` (delivery route) and ``bags`` (bag count).
    """
    records: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            rec: Dict[str, Any] = {}
            # Extract map URL.  Look for known field names first; if none
            # match, fall back to the first column value.
            map_url = row.get("Map Link") or row.get("MapLink") or row.get("map link")
            if not map_url:
                # Fall back to positional index 0 if header missing
                values = list(row.values())
                map_url = values[0] if values else ""
            rec["map_url"] = map_url.strip()
            # Delivery route label
            route = row.get("Delivery Route") or row.get("DeliveryRoute") or row.get("delivery route") or row.get("deliveryroute")
            rec["route"] = route.strip() if route else ""
            # Bag count
            bags = row.get("Number of Bags") or row.get("Number of bags") or row.get("NumberOfBags") or row.get("number of bags")
            rec["bags"] = bags.strip() if bags else ""
            # Order number: extract digits following "Order " from the Comment field
            comment = row.get("Comment", "") or ""
            order_no = ""
            match = re.search(r"Order\s+(\d+)", comment)
            if match:
                order_no = match.group(1)
            rec["order_no"] = order_no
            # Amount supporting troop
            rec["amount_support"] = (row.get("Support Troop Amount", "") or "").strip()
            # Delivery customer: LastName, FirstName
            last = (row.get("LastName", "") or "").strip()
            first = (row.get("FirstName", "") or "").strip()
            rec["customer"] = ", ".join(filter(None, [last, first])) if (last or first) else ""
            # Delivery city
            rec["city"] = (row.get("Town", "") or "").strip()
            # Delivery address
            rec["address"] = (row.get("Street Address", "") or "").strip()
            # Buyer email
            rec["email"] = (row.get("EmailAddress", "") or "").strip()
            # Bags (duplicate of bag count for order form)
            rec["bags"] = rec["bags"] or (row.get("Number of Bags", "") or "").strip()
            # Route (duplicate of delivery route)
            rec["route"] = rec["route"] or (row.get("Delivery Route", "") or "").strip()
            # Sequential ID
            rec["id"] = idx
            # Special instructions
            rec["instructions"] = (row.get("Delivery Instructions", "") or "").strip()
            records.append(rec)
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
    # Measure width of the bottom text using textbbox or font.getsize
    try:
        bbox2 = draw.textbbox((0, 0), bottom_text, font=fonts["small"])
        text_width = bbox2[2] - bbox2[0]
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

    Notes
    -----
    This function preserves the previous behaviour of this script when run
    without map integration: each record produces its own PDF file named
    ``form_<ID>.pdf`` in the specified ``output_dir``.  When the script
    is invoked with the map-related options (see ``main``), the combined
    PDF generation is handled by a separate code path and this function
    is not called.
    """
    fonts = load_fonts()
    os.makedirs(output_dir, exist_ok=True)
    for rec in records:
        img = draw_order_form(rec, fonts)
        file_name = f"form_{rec['id']}.pdf"
        out_path = os.path.join(output_dir, file_name)
        # Save as PDF.  Pillow will convert the RGB image to a single-page PDF.
        img.save(out_path, "PDF")


def save_combined_forms_and_maps(
    records: List[Dict[str, Any]],
    output_dir: str,
    driver_path: Optional[str] = None,
    wait: float = 5.0,
    window_width: int = 1920,
    window_height: int = 1080,
    paper_width: float = 11.0,
    paper_height: float = 8.5,
    scale: Optional[float] = None,
    use_original: bool = False,
    no_header: bool = False,
    no_marker: bool = False,
) -> None:
    """Generate combined order form and map PDFs grouped by delivery route.

    This function produces PDF files containing both the order form and
    corresponding map for each record.  Pages are arranged such that the
    order form appears first (portrait orientation) followed by the map
    (landscape orientation) for each record.  Records sharing the same
    ``route`` value are grouped into a single PDF file named after the
    delivery route.  If the route is empty, a default name "maps" is
    used.

    Parameters
    ----------
    records : list[dict]
        Parsed records including map URLs and order form fields.
    output_dir : str
        Directory where the PDFs will be saved.  Created if missing.
    driver_path : str or None, optional
        Path to the ChromeDriver executable.  If ``None``, the default
        location is used by Selenium.
    wait : float, optional
        Seconds to wait for maps to load before printing each page.
    window_width : int, optional
        Width of the headless browser window in pixels.
    window_height : int, optional
        Height of the headless browser window in pixels.
    paper_width : float, optional
        Width of the PDF pages for maps in inches.  Default 11.0.
    paper_height : float, optional
        Height of the PDF pages for maps in inches.  Default 8.5.
    scale : float or None, optional
        Scale factor for map printing.  See ``generate_maps_pdf.print_map_pages``.
    use_original : bool, optional
        When True, load the original Google Maps URL instead of
        constructing a coordinate-based URL.
    no_header : bool, optional
        When True, suppress the header containing the address, route and
        bag count on the map pages.
    no_marker : bool, optional
        When True, do not inject a custom marker into the map pages.
    """
    if gmp is None:
        raise ImportError(
            "generate_maps_pdf module is not available. Ensure it is on the import path."
        )
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)
    # Load fonts once for all order forms
    fonts = load_fonts()
    # Initialise Chrome driver for printing maps
    driver = gmp.get_chrome_driver(driver_path)
    driver.set_window_size(window_width, window_height)
    try:
        # Group records by their delivery route
        idx = 0
        total_groups = 0
        while idx < len(records):
            current_route = records[idx].get("route") or None
            # Accumulate consecutive records with the same route
            group_records: List[Dict[str, Any]] = []
            group_links: List[str] = []
            group_labels: List[Optional[str]] = []
            group_bags: List[Optional[str]] = []
            while idx < len(records) and (records[idx].get("route") or None) == current_route:
                rec = records[idx]
                group_records.append(rec)
                group_links.append(rec.get("map_url", ""))
                group_labels.append(rec.get("route", ""))
                group_bags.append(rec.get("bags", ""))
                idx += 1
            # Generate map pages for this group
            map_pages: List[bytes] = gmp.print_map_pages(
                group_links,
                driver,
                orientation_landscape=True,
                page_wait=wait,
                paper_width=paper_width,
                paper_height=paper_height,
                scale=scale,
                use_coordinates=not use_original,
                include_header=not no_header,
                labels=group_labels,
                inject_marker=not no_marker,
                bag_counts=group_bags,
            )
            # Generate order form pages for this group
            order_pages: List[bytes] = []
            for rec in group_records:
                img = draw_order_form(rec, fonts)
                buf = BytesIO()
                img.save(buf, format="PDF")
                order_pages.append(buf.getvalue())
            # Merge pages: order form followed by map for each record
            writer = PdfWriter()
            num_records = len(group_records)
            for i in range(num_records):
                # Add order form page
                order_reader = PdfReader(BytesIO(order_pages[i]))
                for page in order_reader.pages:
                    writer.add_page(page)
                # Add corresponding map page (if available)
                if i < len(map_pages):
                    map_reader = PdfReader(BytesIO(map_pages[i]))
                    for page in map_reader.pages:
                        writer.add_page(page)
            # Construct a safe base name for the output file
            if current_route:
                base_name = re.sub(r"[^A-Za-z0-9]+", "_", current_route.strip())
                if not base_name:
                    base_name = "combined"
            else:
                base_name = "combined"
            out_path = os.path.join(output_dir, f"{base_name}.pdf")
            # Write out the combined PDF
            with open(out_path, "wb") as f:
                writer.write(f)
            print(f"Wrote {2 * num_records} page(s) to '{out_path}'.")
            total_groups += 1
        if total_groups == 0:
            print("No PDF files were created; aborting.")
    finally:
        # Always quit the driver to release resources
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate combined order form and map PDFs from a CSV input.  "
            "Each record produces a portrait order form page followed by a "
            "landscape map page.  Records sharing the same delivery route "
            "are grouped into a single PDF named after the route."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the CSV file containing order and map data.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Directory to write the grouped PDFs.",
    )
    # Map-related options (mirroring generate_maps_pdf.py)
    parser.add_argument(
        "--driver-path",
        default=None,
        help="Path to the ChromeDriver executable.  If omitted, Selenium uses the default.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=5.0,
        help="Seconds to wait for map to load before printing each page.",
    )
    parser.add_argument(
        "--window-width",
        type=int,
        default=1920,
        help="Width of the browser window in pixels.",
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=1080,
        help="Height of the browser window in pixels.",
    )
    parser.add_argument(
        "--paper-width",
        type=float,
        default=11.0,
        help="Width of the PDF pages (inches) for maps.  Default 11.0 (landscape Letter).",
    )
    parser.add_argument(
        "--paper-height",
        type=float,
        default=8.5,
        help="Height of the PDF pages (inches) for maps.  Default 8.5.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="Scale factor for map printing (0.1–2.0).",
    )
    parser.add_argument(
        "--use-original",
        action="store_true",
        help=(
            "Load and print the original Google Maps link instead of building "
            "a coordinate-based URL.  This includes the place card and photo."
        ),
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Do not include the address/route/bags header on map pages.",
    )
    parser.add_argument(
        "--no-marker",
        action="store_true",
        help="Do not inject a custom marker into coordinate-based maps.",
    )
    args = parser.parse_args()
    # Parse full records including map URL, route and bag count
    records = parse_input_records(args.input)
    if not records:
        print("No records found in the input file.")
        return
    # Generate combined PDFs grouped by delivery route
    save_combined_forms_and_maps(
        records,
        args.output,
        driver_path=args.driver_path,
        wait=args.wait,
        window_width=args.window_width,
        window_height=args.window_height,
        paper_width=args.paper_width,
        paper_height=args.paper_height,
        scale=args.scale,
        use_original=args.use_original,
        no_header=args.no_header,
        no_marker=args.no_marker,
    )


if __name__ == "__main__":
    main()