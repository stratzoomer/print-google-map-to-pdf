"""
generate_maps_pdf.py
====================

This script reads the season spreadsheet (.xlsx) or a CSV file containing
Google Map links (one per row),
extracts the geographic coordinates from each link, loads an uncluttered
map view for those coordinates with a marker, and prints that view to
PDF.  All individual PDF pages are combined into a single,
landscape‑oriented PDF.

Usage
-----

Run this script from a command prompt.  It requires Python 3.7 or later,
``selenium`` and ``PyPDF2`` packages as well as a recent Chrome/Chromium
installation with a matching driver.  On first execution you may need to
install the required packages:

    pip install selenium PyPDF2

You must also download the ChromeDriver executable that matches your
browser version from https://chromedriver.chromium.org and ensure that it
is on your ``PATH`` or supply its location via the ``--driver-path`` option.

Example:

    python generate_maps_pdf.py --input links.csv --output maps.pdf --driver-path /path/to/chromedriver

The script will silently skip rows that do not look like Google Map links
and will display progress as it generates each page.

Limitations
-----------

* Printing relies on Chrome's headless ``printToPDF`` devtools API, which
  usually works without launching a window.  Nonetheless, network or API
  changes from Google may affect the results.
  * Because the script opens a clean map centered on the extracted
  latitude and longitude (using the ``q`` and ``ll`` parameters), there
  is no place summary panel to collapse.  A marker indicates the
  location on the map.  This replicates the effect of collapsing the
  side panel in an interactive session while still showing the place
  marker.
"""

import argparse
import base64
import os
import re
import sys
import tempfile
import time
from io import BytesIO
from typing import List, Optional, Tuple, Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import html

from PyPDF2 import PdfReader, PdfWriter, PdfMerger

from addresses import same_street_address
from sheet_reader import read_rows

# (map link, delivery route, number of bags, special-action note, street address)
Record = Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]

# Selenium imports are deferred so that the script's help can be printed
# without requiring the package to be installed.
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import WebDriverException
except ImportError as exc:  # pragma: no cover
    # When selenium isn't available we set these to None; this allows the
    # script to emit a helpful error at runtime rather than failing on import.
    webdriver = None  # type: ignore
    Options = None  # type: ignore
    Service = None  # type: ignore
    WebDriverWait = None  # type: ignore
    WebDriverException = Exception  # type: ignore


def extract_address(link: str) -> Optional[str]:
    """Extract a human‑readable address from a Google Maps place URL.

    Google place URLs generally have the form
    ``https://www.google.com/maps/place/<address>/<more>`` where the
    ``<address>`` segment uses ``+`` as a space separator and ``%2C`` for
    commas.  This function decodes that segment into a more readable form.

    Parameters
    ----------
    link : str
        A Google Maps URL.

    Returns
    -------
    Optional[str]
        The extracted address, or ``None`` if it cannot be determined.
    """
    match = re.search(r"/place/([^/@]+)", link)
    if not match:
        return None
    segment = match.group(1)
    # Decode plus signs and percent‑encoded commas
    addr = segment.replace("+", " ").replace("%2C", ",")
    return addr


def extract_coordinates(link: str) -> Optional[Tuple[float, float]]:
    """Extract latitude and longitude from a Google Maps link.

    The function first looks for an ``@lat,lon`` pattern and falls back to
    the ``!3dlat!4dlon`` pattern if the former is not found.

    Parameters
    ----------
    link : str
        A Google Maps URL.

    Returns
    -------
    tuple[float, float] | None
        A tuple of (latitude, longitude) if both are found, otherwise ``None``.
    """
    # Match @lat,lon,zoomz or @lat,lon,
    match_at = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", link)
    if match_at:
        lat = float(match_at.group(1))
        lon = float(match_at.group(2))
        return lat, lon
    # Match !3dlat!4dlon
    match_3d = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", link)
    if match_3d:
        lat = float(match_3d.group(1))
        lon = float(match_3d.group(2))
        return lat, lon
    return None


def extract_zoom(link: str, default: int = 16) -> int:
    """Extract zoom level from a Google Maps link.

    Zoom levels are specified as ``<zoom>z`` in the URL (e.g., ``16z``).  If no
    zoom is found, a default is returned.

    Parameters
    ----------
    link : str
        A Google Maps URL.
    default : int, optional
        The zoom level to return if none is found in the URL, by default 16.

    Returns
    -------
    int
        The extracted or default zoom level.
    """
    match = re.search(r",(\d+(?:\.\d+)?)z", link)
    if match:
        try:
            # Zoom may be a float in the URL (e.g., 16.55z); convert to int
            return int(round(float(match.group(1))))
        except ValueError:
            return default
    return default


def _strip_auth_params(url: str) -> str:
    """Remove auth/session query params that can cause a blank map in headless.

    Links copied while signed into Google (e.g. authuser=1, g_ep=...) can render
    blank or redirect when opened in an unauthenticated browser.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return url
    params = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("authuser", "g_ep", "entry"):
        params.pop(key, None)
    new_query = urlencode(params, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


# The logo at the top left of Google Maps' print layout.
GOOGLE_MAPS_PRINT_LOGO = (
    "https://www.google.com/images/branding/lockups/1x/lockup_maps_color_131x24dp.png"
)


def _preload_image(driver: "webdriver.Chrome", url: str, timeout: float = 3.0) -> None:
    """Load an image into the browser cache so it is ready when printing."""
    try:
        driver.execute_script(
            "window.__preload = new Image(); window.__preload.src = arguments[0];", url
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if driver.execute_script("return window.__preload.complete;"):
                return
            time.sleep(0.1)
    except Exception:
        pass  # Not essential; the page prints without the logo


def _loaded_place_name(driver: "webdriver.Chrome") -> Optional[str]:
    """Return the name of the place Google Maps loaded (e.g. "100 Maple Ct")."""
    try:
        name = driver.execute_script(
            "var h = document.querySelector('h1'); return h ? h.textContent.trim() : null;"
        )
        return name or None
    except Exception:
        return None


def _is_map_ready(driver: "webdriver.Chrome") -> bool:
    """Return True if the page has a large map canvas (map has rendered)."""
    try:
        return bool(
            driver.execute_script(
                """
                var canvases = document.querySelectorAll('canvas');
                for (var i = 0; i < canvases.length; i++) {
                    if (canvases[i].width > 200 && canvases[i].height > 200)
                        return true;
                }
                return false;
                """
            )
        )
    except Exception:
        return False


def _wait_for_map_ready(driver: "webdriver.Chrome", timeout: float = 20.0) -> None:
    """Wait until the map canvas is rendered so the PDF capture is not blank."""
    if WebDriverWait is None:
        return

    try:
        WebDriverWait(driver, timeout=timeout).until(_is_map_ready)
    except Exception:
        pass  # Proceed anyway after timeout; fixed sleep may still help


def special_note(comment: str) -> Optional[str]:
    """Return the special-action note from a ``Comment`` cell, if any.

    In the season sheet, comments typed in red flag something that needs
    special action (e.g. "Need one pallet").  This is the fallback for CSV
    exports, which drop the text colour: any comment other than the usual
    "Order 12345" is treated as a special-action note.  For ``.xlsx``
    input the red text itself is used instead.
    """
    comment = comment.strip()
    if not comment or re.fullmatch(r"Order\s+\d+", comment):
        return None
    return comment


def read_records(
    path: str, max_records: Optional[int] = None, sheet: Optional[str] = None
) -> List[Record]:
    """Read map links and optional labels from the season spreadsheet.

    The input is the ``.xlsx`` workbook (``sheet``, default the first
    sheet) or a CSV file.  This helper function supports two layouts:

    1. **Positional format** – each row contains the map URL in the first
       column and an optional label in the second column.  Any additional
       columns are ignored.
    2. **Header format** – the first row contains column names.  When the
       header row contains ``"Map Link"`` and ``"Delivery Route"`` (case
       insensitive), those fields are used to extract the URL and label.

    In both cases, rows with an empty or missing URL are skipped, and the
    returned label is ``None`` when absent.

    Parameters
    ----------
    path : str
        Path to the ``.xlsx`` workbook or CSV file.
    max_records : int | None, optional
        If given, only the first ``max_records`` records are returned.
    sheet : str | None, optional
        Worksheet name for Excel input; defaults to the first sheet.

    Returns
    -------
    list[tuple[str, Optional[str], Optional[str], Optional[str]]]
        A list of ``(url, label, bags, note, street)`` tuples.  ``label``,
        ``bags``, ``note`` and ``street`` (the ``Street Address`` column) may
        be ``None`` if not provided.  ``note`` is the red
        text in ``Comment`` for Excel input (see ``special_note`` for CSV).
    """
    records: List[Record] = []
    # Read all rows first so that we can inspect the header row.
    rows, red_text = read_rows(path, sheet)
    if not rows:
        return records
    # Known field names for map link, label and bag count
    link_field_names = {"map link", "maplink", "map_link"}
    label_field_names = {"delivery route", "deliveryroute", "delivery_route", "label"}
    bags_field_names = {"number of bags", "numberofbags", "number_of_bags", "bags"}
    # Find the header row: scan the first few rows in case there is a title
    # row (e.g. "Spring 2026") before the column names.
    max_header_search = min(10, len(rows))
    header_row_idx = 0
    for i in range(max_header_search):
        candidate = [cell.strip() for cell in rows[i]]
        candidate_lower = [c.lower() for c in candidate]
        if any(name in candidate_lower for name in link_field_names):
            header_row_idx = i
            break
    header = [cell.strip() for cell in rows[header_row_idx]]
    header_lower = [h.lower() for h in header]
    has_header = any(name in header_lower for name in link_field_names)
    link_index: Optional[int] = None
    label_index: Optional[int] = None
    bags_index: Optional[int] = None
    comment_index: Optional[int] = None
    street_index: Optional[int] = None
    start_idx = 0
    if has_header:
        start_idx = header_row_idx + 1
        # Identify the indices of the link and label fields (case insensitive)
        for i, h in enumerate(header_lower):
            if h in link_field_names and link_index is None:
                link_index = i
            if h in label_field_names and label_index is None:
                label_index = i
            if h in bags_field_names and bags_index is None:
                bags_index = i
            if h == "comment" and comment_index is None:
                comment_index = i
            if h == "street address" and street_index is None:
                street_index = i
        # If we don't find a link index in the header, treat the first
        # column as the link.
        if link_index is None:
            link_index = 0
    else:
        # Positional format: first column is link, second column is label
        link_index = 0
        label_index = 1
        bags_index = 2
    # Process each data row starting from start_idx
    for row_idx in range(start_idx, len(rows)):
        row = rows[row_idx]
        if not row:
            continue
        # Extract URL
        url = ""
        if link_index is not None and link_index < len(row):
            url = row[link_index].strip()
        if not url:
            continue
        # When there is a bag count column, only rows with a positive bag
        # count are orders (the season export is the full customer list).
        if has_header and bags_index is not None:
            bags_cell = row[bags_index].strip() if bags_index < len(row) else ""
            if not re.fullmatch(r"\d+", bags_cell) or int(bags_cell) == 0:
                continue
        # Extract label, if any
        label: Optional[str] = None
        if label_index is not None and label_index < len(row):
            label_raw = row[label_index].strip()
            if label_raw:
                label = label_raw
        # Extract number of bags, if any
        bags: Optional[str] = None
        if bags_index is not None and bags_index < len(row):
            bags_raw = row[bags_index].strip()
            if bags_raw:
                bags = bags_raw
        # Extract special-action note from the comment, if any
        note: Optional[str] = None
        if comment_index is not None and comment_index < len(row):
            if red_text is None:
                note = special_note(row[comment_index])
            else:
                note = red_text.get((row_idx, comment_index)) or None
        street: Optional[str] = None
        if street_index is not None and street_index < len(row):
            street = row[street_index].strip() or None
        records.append((url, label, bags, note, street))
        if max_records is not None and len(records) >= max_records:
            break
    return records


def group_by_label(
    records: List[Record],
) -> "dict[Optional[str], List[Record]]":
    """Group records by label (delivery route), in order of first appearance.

    The input is not necessarily sorted by route, so rows for the same
    route may be spread throughout the file.
    """
    groups: dict = {}
    for rec in records:
        groups.setdefault(rec[1], []).append(rec)
    return groups


def get_chrome_driver(chromedriver_path: Optional[str]) -> webdriver.Chrome:
    """Create a headless Chrome driver configured for PDF printing.

    Parameters
    ----------
    chromedriver_path : str | None
        The path to the ChromeDriver executable.  If ``None``, Selenium will
        attempt to find it on ``PATH``.

    Returns
    -------
    selenium.webdriver.Chrome
        A configured Chrome WebDriver.
    """
    if webdriver is None or Options is None:
        raise ImportError(
            "Selenium is not installed.  Install it with `pip install selenium`."
        )
    chrome_options = Options()
    # Use a unique user-data-dir to avoid "already in use" when multiple
    # Chrome processes or repeated runs share the default directory.
    tmpdir = tempfile.mkdtemp(prefix="chrome_userdata_")
    chrome_options.add_argument(f"--user-data-dir={tmpdir}")
    # Use the new headless mode for better compatibility
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Improve performance of PDF printing
    chrome_options.add_argument("--print-to-pdf-no-header")
    # Selenium 4 removed the ``executable_path`` argument from the
    # ``webdriver.Chrome`` constructor in favour of the ``Service`` class.
    # If the caller provided a driver path, we create a Service for it; otherwise
    # the default Service will look up ``chromedriver`` on the PATH.
    if Service is None:
        raise ImportError(
            "Selenium is not installed.  Install it with `pip install selenium`."
        )
    if chromedriver_path:
        service = Service(executable_path=chromedriver_path)
    else:
        service = Service()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def print_map_pages(
    links: List[str],
    driver: webdriver.Chrome,
    orientation_landscape: bool = True,
    page_wait: float = 5.0,
    paper_width: Optional[float] = None,
    paper_height: Optional[float] = None,
    scale: Optional[float] = None,
    use_coordinates: bool = True,
    include_header: bool = True,
    labels: Optional[List[Optional[str]]] = None,
    inject_marker: bool = True,
    bag_counts: Optional[List[Optional[str]]] = None,
    notes: Optional[List[Optional[str]]] = None,
    expected_streets: Optional[List[Optional[str]]] = None,
    mismatches: Optional[List[str]] = None,
) -> List[bytes]:
    """Generate PDF pages for each map link.

    The driver navigates to each supplied link and captures a PDF
    snapshot using Chrome's DevTools API.  When ``use_coordinates`` is
    true the script extracts latitude, longitude and zoom from the link
    and constructs a clean coordinate‑based URL to avoid the place card,
    photo and action buttons.  The script may inject its own marker in
    this mode (see module documentation for details).  If ``include_header``
    is true and the link contains an address segment, that address will
    be printed at the top of the page.  When ``labels`` are provided,
    each label is displayed on the right side of the header for its
    corresponding page.

    Parameters
    ----------
    links : list[str]
        A list of Google Maps URLs.
    driver : selenium.webdriver.Chrome
        A configured Chrome WebDriver instance.
    orientation_landscape : bool, optional
        Whether to print pages in landscape orientation, by default True.
    page_wait : float, optional
        Seconds to wait after loading each map before printing, by default 5.0.
    paper_width : float or None, optional
        Width of the PDF page in inches.  If ``None``, the default paper size
        is used by Chrome.  When provided together with ``paper_height`` this
        controls how the map is scaled on the page.
    paper_height : float or None, optional
        Height of the PDF page in inches.  See ``paper_width``.
    scale : float or None, optional
        A scaling factor between 0.1 and 2.0 used by the Chrome ``printToPDF``
        command.  Increasing the scale zooms in on the content, decreasing
        zooms out.  If ``None``, Chrome chooses a default.

    use_coordinates : bool, optional
        If true (default), the script attempts to extract latitude, longitude
        and zoom level from each link and loads a clean coordinate‑based map
        (``https://maps.google.com/maps?ll=lat,lon&z=zoom``).  This removes
        the place card, photo and action buttons.  If false, the original
        link is loaded.

    labels : list[Optional[str]] | None, optional
        An optional sequence of labels corresponding one‑to‑one with
        ``links``.  Each label (if provided) is printed on the right side
        of the header on its respective page along with the number of bags.
        Use ``None`` for entries that should omit the label.

    bag_counts : list[Optional[str]] | None, optional
        Optional sequence of bag counts corresponding one‑to‑one with
        ``links``.  Each entry may be ``None`` if the bag count is not
        provided.  When present, the bag count is displayed after the
        delivery route in the header as ``Number of Bags: <count>``.

    notes : list[Optional[str]] | None, optional
        Optional sequence of special-action notes corresponding one‑to‑one
        with ``links``.  When present, the note is printed in red below the
        delivery route and bag count in the header.

    expected_streets : list[Optional[str]] | None, optional
        Optional sequence of street addresses (from the sheet) corresponding
        one‑to‑one with ``links``.  Before printing, the place Google Maps
        actually loaded is compared with it; each mismatch is printed as a
        warning and appended to ``mismatches`` (when given).

    inject_marker : bool, optional
        When ``True`` (default), a simple marker is injected into coordinate‑based
        maps.  This marker consists of a small red dot with a white border
        positioned at the centre of the viewport.  Setting this to ``False``
        suppresses marker injection, which may be useful when the marker is
        distracting or undesired.

    Returns
    -------
    list[bytes]
        A list containing the PDF data (as bytes) for each map page.
    """
    pdf_pages: List[bytes] = []
    total = len(links)
    for idx, link in enumerate(links, start=1):
        # Determine which URL to load.  If use_coordinates is enabled and the
        # link yields valid coordinates, build a bare map URL to eliminate
        # the place card.  Otherwise fall back to the original link.
        load_url = link
        coords: Optional[Tuple[float, float]] = None
        zoom: int = 16
        if use_coordinates:
            coords = extract_coordinates(link)
            if coords is not None:
                lat, lon = coords
                zoom = extract_zoom(link)
                load_url = f"https://maps.google.com/maps?ll={lat},{lon}&z={zoom}"
        load_url = _strip_auth_params(load_url)
        print(f"Loading map {idx}/{total}: {load_url}")
        driver.get(load_url)
        _wait_for_map_ready(driver, timeout=20.0)
        time.sleep(page_wait)
        # Check the place Google loaded is the address on the order.
        expected = expected_streets[idx - 1] if expected_streets and idx - 1 < len(expected_streets) else None
        if expected:
            loaded = _loaded_place_name(driver)
            if not loaded or not same_street_address(loaded, expected):
                msg = f"map for '{expected}' shows '{loaded or 'no place'}'"
                print(f"WARNING: {msg}.")
                if mismatches is not None:
                    mismatches.append(msg)
        # Inject a simple marker at the map centre when using coordinate view.
        if inject_marker and use_coordinates and coords is not None:
            try:
                script = """
                    (function() {
                        if (document.getElementById('custom-map-marker')) return;
                        var marker = document.createElement('div');
                        marker.id = 'custom-map-marker';
                        marker.style.position = 'absolute';
                        marker.style.width = '16px';
                        marker.style.height = '16px';
                        marker.style.backgroundColor = '#d9534f';
                        marker.style.border = '2px solid white';
                        marker.style.borderRadius = '50%';
                        marker.style.top = '50%';
                        marker.style.left = '50%';
                        marker.style.transform = 'translate(-50%, -50%)';
                        marker.style.zIndex = '10000';
                        marker.style.pointerEvents = 'none';
                        document.body.appendChild(marker);
                    })();
                """
                driver.execute_script(script)
            except Exception:
                pass
        # Build print options.
        print_opts = {
            "landscape": False,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "printBackground": True,
        }
        if include_header:
            address = extract_address(link)
            label: Optional[str] = None
            bag: Optional[str] = None
            if labels is not None and idx - 1 < len(labels):
                label = labels[idx - 1]
            if bag_counts is not None and idx - 1 < len(bag_counts):
                bag = bag_counts[idx - 1]
            note: Optional[str] = None
            if notes is not None and idx - 1 < len(notes):
                note = notes[idx - 1]
            # Google's print layout shows the Google Maps logo at the top
            # left and the street only (e.g. "100 Maple Ct") as a centred
            # title.  Hide that title when printing; our header shows the
            # full address (with town and zip code) in its place instead.
            # Google only fetches its logo when the page is printed, and it
            # often isn't loaded in time, so load it beforehand.
            _preload_image(driver, GOOGLE_MAPS_PRINT_LOGO)
            if address:
                try:
                    driver.execute_script(
                        "var st = document.createElement('style');"
                        "st.textContent = '@media print { h1 { visibility: hidden !important; } }';"
                        "document.head.appendChild(st);"
                    )
                except Exception:
                    pass
            if address or label or bag or note:
                safe_addr = html.escape(address) if address else ""
                right_parts: List[str] = []
                if label:
                    safe_label = html.escape(label)
                    right_parts.append("Delivery Route: " + safe_label)
                if bag:
                    safe_bag = html.escape(bag)
                    right_parts.append("Number of Bags: " + safe_bag)
                right_text = "&nbsp;&nbsp;".join(right_parts) if right_parts else ""
                if note:
                    right_text += (
                        '<div style="color:#d00000; font-weight:bold; margin-top:4px;">'
                        + html.escape(note) + '</div>'
                    )
                # Three columns: the left is kept clear for Google's logo.
                header_html = (
                    '<div style="font-size:12px; margin-top:10px; display:grid; '
                    'grid-template-columns:1fr auto 1fr; width:100%;">'
                    '<span></span>'
                    '<span style="text-align:center; font-family:Arial, Helvetica, sans-serif; '
                    'font-size:16px; margin-top:4px;">' + safe_addr + '</span>'
                    '<div style="margin-right:40px; text-align:right;">' + right_text + '</div>'
                    '</div>'
                )
                print_opts["displayHeaderFooter"] = True
                print_opts["headerTemplate"] = header_html
                print_opts["footerTemplate"] = ""
        if paper_width is not None and paper_height is not None:
            print_opts["paperWidth"] = paper_width
            print_opts["paperHeight"] = paper_height
        if scale is not None:
            print_opts["scale"] = scale
        result = driver.execute_cdp_cmd("Page.printToPDF", print_opts)  # type: ignore
        pdf_data = base64.b64decode(result["data"])
        pdf_pages.append(pdf_data)
    return pdf_pages


def merge_pdf_pages(pages: List[bytes], output_path: str) -> None:
    """Merge multiple PDF pages into a single PDF file.

    Uses PdfMerger with temporary files to ensure each source PDF's
    indirect objects are fully isolated and don't cross-contaminate.

    Parameters
    ----------
    pages : list[bytes]
        A list where each element is a PDF document (containing one or more
        pages) in binary form.
    output_path : str
        Where to write the merged PDF.
    """
    tmp_files: List[str] = []
    try:
        for page_data in pages:
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".pdf", prefix="map_page_"
            )
            tmp.write(page_data)
            tmp.close()
            tmp_files.append(tmp.name)
        merger = PdfMerger()
        for tmp_path in tmp_files:
            merger.append(tmp_path)
        merger.write(output_path)
        merger.close()
    finally:
        for tmp_path in tmp_files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Google Maps links to a single PDF.")
    parser.add_argument(
        "--input",
        required=True,
        help=(
            "Path to the season spreadsheet (.xlsx) or a CSV file containing "
            "Google Maps links.  With a header row, the Map Link, Delivery "
            "Route, Number of Bags and Comment columns are used.  Otherwise "
            "each row should contain a Google Maps URL in the first column.  "
            "A second column may contain a label that will appear on the right "
            "side of the header for that map."
        ),
    )
    parser.add_argument(
        "--sheet",
        help="Worksheet to read from an .xlsx input (default: the first sheet).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Path to the output directory.  The script will produce one PDF "
            "per unique label found in the input file, using the label as "
            "the file name.  If the directory does not exist it will be "
            "created."
        ),
    )
    parser.add_argument(
        "--driver-path",
        default=None,
        help="Path to the ChromeDriver executable.  If omitted, Selenium will use the default.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of links to process (useful for testing).  If omitted, all links are processed.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=5.0,
        help="Seconds to wait for map to load before printing each page.",
    )
    parser.add_argument(
        "--portrait",
        action="store_true",
        help=(
            "Deprecated: orientation is now controlled by paperWidth and "
            "paperHeight.  This flag no longer has any effect."
        ),
    )
    parser.add_argument(
        "--window-width",
        type=int,
        default=1920,
        help="Width of the browser window in pixels (affects map framing).",
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=1080,
        help="Height of the browser window in pixels (affects map framing).",
    )
    parser.add_argument(
        "--paper-width",
        type=float,
        default=11.0,
        help=(
            "Width of the PDF pages in inches. Default 11.0 (landscape Letter). "
            "Use together with --paper-height."
        ),
    )
    parser.add_argument(
        "--paper-height",
        type=float,
        default=8.5,
        help=(
            "Height of the PDF pages in inches. Default 8.5 (landscape Letter). "
            "Use together with --paper-width."
        ),
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help=(
            "Scale factor for printing (0.1–2.0).  Adjust this if maps appear "
            "too zoomed in or out in the PDF."
        ),
    )
    parser.add_argument(
        "--use-original",
        action="store_true",
        help=(
            "Load and print the original Google Maps link instead of building "
            "a coordinate‑based URL.  Use this if you want to include the "
            "place summary card and action buttons.  Default is to omit the "
            "place card by using the coordinate view."
        ),
    )

    parser.add_argument(
        "--no-header",
        action="store_true",
        help=(
            "Do not include the address or label at the top of each page.  "
            "By default the script extracts the address from the URL and any "
            "label from the CSV and prints them as a header."
        ),
    )
    parser.add_argument(
        "--no-marker",
        action="store_true",
        help=(
            "Do not inject a custom marker into coordinate‑based maps.  "
            "When this flag is supplied, the script will still use a "
            "coordinate‑based URL to suppress the place card but will not "
            "overlay its own marker."
        ),
    )
    args = parser.parse_args()

    # Read links and optional labels from the input file.  Each row may
    # contain a URL in the first column and a label in the second column.  Any
    # additional columns are ignored.  Labels may be None if absent.
    records = read_records(args.input, max_records=args.limit, sheet=args.sheet)
    if not records:
        print("No valid links found in the input file.")
        sys.exit(1)
    links: List[str] = [rec[0] for rec in records]
    labels_list: List[Optional[str]] = [rec[1] for rec in records]
    bags_list: List[Optional[str]] = [rec[2] for rec in records]

    # Prepare the output directory.  If the provided output path is not an
    # existing directory, attempt to create it.  This directory will hold
    # one PDF per unique label (or "maps" for unlabeled rows).
    output_dir = args.output
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Compute window dimensions to match the paper aspect ratio so
    # the viewport fills the page without empty space at top/bottom.
    paper_ratio = args.paper_width / args.paper_height
    win_height = args.window_height
    win_width = int(win_height * paper_ratio)

    # Create a single shared Chrome driver for all pages.
    driver = get_chrome_driver(args.driver_path)
    driver.set_window_size(win_width, win_height)
    try:
        # Group records by their label.  The input is not necessarily
        # sorted by route, so collect all rows for each label (in order of
        # first appearance) and produce one PDF for each.
        total_groups = 0
        mismatches: List[str] = []
        for current_label, group in group_by_label(records).items():
            group_links = [rec[0] for rec in group]
            group_labels = [rec[1] for rec in group]
            group_bags = [rec[2] for rec in group]
            group_notes = [rec[3] for rec in group]
            group_streets = [rec[4] for rec in group]
            # Chrome occasionally crashes mid-run; restart it and retry the
            # route once rather than losing the rest of the run.
            for attempt in (1, 2):
                group_mismatches: List[str] = []
                try:
                    pages = print_map_pages(
                        group_links,
                        driver,
                        orientation_landscape=not args.portrait,
                        page_wait=args.wait,
                        paper_width=args.paper_width,
                        paper_height=args.paper_height,
                        scale=args.scale,
                        use_coordinates=not args.use_original,
                        include_header=not args.no_header,
                        labels=group_labels,
                        inject_marker=not args.no_marker,
                        bag_counts=group_bags,
                        notes=group_notes,
                        expected_streets=group_streets,
                        mismatches=group_mismatches,
                    )
                    mismatches.extend(group_mismatches)
                    break
                except WebDriverException as exc:
                    if attempt == 2:
                        raise
                    print(f"Chrome failed on '{current_label}' ({exc.msg}); restarting and retrying.")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = get_chrome_driver(args.driver_path)
                    driver.set_window_size(win_width, win_height)
            if pages:
                if current_label:
                    base_name = re.sub(r"[^A-Za-z0-9]+", "_", current_label.strip())
                    if not base_name:
                        base_name = "maps"
                else:
                    base_name = "maps"
                output_path = os.path.join(output_dir, f"{base_name}.pdf")
                merge_pdf_pages(pages, output_path)
                print(f"Successfully wrote {len(pages)} page(s) to '{output_path}'.")
                total_groups += 1
        if mismatches:
            print(f"MAP CHECK: {len(mismatches)} map(s) not for the order's Street Address:")
            for msg in mismatches:
                print(f"  - {msg}")
        else:
            print(f"MAP CHECK: all {len(records)} map(s) are for the order's Street Address.")
        if total_groups == 0:
            print("No PDF pages were created; aborting.")
            sys.exit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()