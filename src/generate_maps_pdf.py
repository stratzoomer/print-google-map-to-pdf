"""
generate_maps_pdf.py
====================

This script reads a CSV file containing Google Map links (one per row),
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
import csv
import os
import re
import sys
import time
from io import BytesIO
from typing import List, Optional, Tuple

from PyPDF2 import PdfReader, PdfWriter

# Selenium imports are deferred so that the script's help can be printed
# without requiring the package to be installed.
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except ImportError as exc:  # pragma: no cover
    # When selenium isn't available we set these to None; this allows the
    # script to emit a helpful error at runtime rather than failing on import.
    webdriver = None  # type: ignore
    Options = None  # type: ignore
    Service = None  # type: ignore


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


def read_links_from_csv(path: str, max_links: Optional[int] = None) -> List[str]:
    """Read Google Maps links from a CSV file.

    The CSV is expected to have one URL per row.  Fields may be quoted,
    including embedded newlines; this function uses ``csv.reader`` to handle
    those cases correctly.

    Parameters
    ----------
    path : str
        Path to the CSV file containing the links.
    max_links : int | None, optional
        If given, only the first ``max_links`` rows will be returned.

    Returns
    -------
    list[str]
        A list of URLs.
    """
    links: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            link = row[0].strip()
            if not link:
                continue
            links.append(link)
            if max_links is not None and len(links) >= max_links:
                break
    return links


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
) -> List[bytes]:
    """Generate PDF pages for each map link.

    The driver navigates to each supplied link (or, if ``use_coordinates`` is
    true, constructs a coordinate URL with an explicit marker) and captures
    a PDF snapshot using Chrome's DevTools API.  When ``use_coordinates``
    is true the place summary card and associated buttons are omitted from
    the view.  A marker is added at the extracted latitude and longitude
    via the ``q`` parameter so that the resulting map clearly indicates
    the destination.  If ``include_header`` is true and the link contains
    an address segment, that address will be printed at the top of the
    page via the header template.

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
        if use_coordinates:
            coords = extract_coordinates(link)
            if coords is not None:
                lat, lon = coords
                zoom = extract_zoom(link)
                # Use the q parameter to place a marker at the coordinates.  The
                # ll parameter keeps the map centered on the marker and the z
                # parameter preserves the original zoom level.  Without q, the
                # map view will omit the marker entirely.  See discussion in
                # Stack Overflow: https://stackoverflow.com/a/42330709 and
                # https://stackoverflow.com/a/2660326
                load_url = (
                    f"https://maps.google.com/maps?q={lat},{lon}&ll={lat},{lon}&z={zoom}"
                )
        print(f"Loading map {idx}/{total}: {load_url}")
        driver.get(load_url)
        # allow some time for the page and map tiles to load
        time.sleep(page_wait)
        # Build print options.  Do not rotate the content; instead set the
        # paper size so that width > height for landscape.  Chrome will then
        # preserve the map's orientation without introducing extra white space.
        print_opts = {
            "landscape": False,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "printBackground": True,
        }
        # Header/footer handling
        if include_header:
            address = extract_address(link)
            if address:
                header_html = (
                    f'<div style="font-size:12px; margin-left:40px; ' \
                    f'margin-top:10px;">{address}</div>'
                )
                print_opts["displayHeaderFooter"] = True
                print_opts["headerTemplate"] = header_html
                print_opts["footerTemplate"] = ""
        # Apply custom paper size if provided.  Width/height are in inches.
        if paper_width is not None and paper_height is not None:
            print_opts["paperWidth"] = paper_width
            print_opts["paperHeight"] = paper_height
        # Apply scale if provided (allowed range is 0.1–2.0)
        if scale is not None:
            print_opts["scale"] = scale
        result = driver.execute_cdp_cmd("Page.printToPDF", print_opts)  # type: ignore
        pdf_data = base64.b64decode(result["data"])
        pdf_pages.append(pdf_data)
    return pdf_pages


def merge_pdf_pages(pages: List[bytes], output_path: str) -> None:
    """Merge multiple PDF pages into a single PDF file.

    Parameters
    ----------
    pages : list[bytes]
        A list where each element is a PDF document (containing one or more
        pages) in binary form.
    output_path : str
        Where to write the merged PDF.
    """
    writer = PdfWriter()
    for page_data in pages:
        reader = PdfReader(BytesIO(page_data))
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Google Maps links to a single PDF.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the CSV file containing Google Maps links (one per row).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the output PDF file.",
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
            "Do not include the address at the top of each page.  By default "
            "the script extracts the address from the URL and prints it as a "
            "header."
        ),
    )
    args = parser.parse_args()

    links = read_links_from_csv(args.input, max_links=args.limit)
    if not links:
        print("No links found in the input file.")
        sys.exit(1)

    # Initialize Chrome driver
    driver = get_chrome_driver(args.driver_path)
    # Set the browser window size to better reflect the on‑screen view.  A larger
    # viewport will produce a PDF that matches the zoom level you see when
    # visiting maps in a desktop browser.
    driver.set_window_size(args.window_width, args.window_height)
    try:
        pages = print_map_pages(
            links,
            driver,
            orientation_landscape=not args.portrait,
            page_wait=args.wait,
            paper_width=args.paper_width,
            paper_height=args.paper_height,
            scale=args.scale,
            use_coordinates=not args.use_original,
            include_header=not args.no_header,
        )
    finally:
        # Always quit the driver to release resources
        driver.quit()

    if not pages:
        print("No PDF pages were created; aborting.")
        sys.exit(1)

    # Merge pages into a single PDF
    merge_pdf_pages(pages, args.output)
    print(f"Successfully wrote {len(pages)} page(s) to '{args.output}'.")


if __name__ == "__main__":
    main()