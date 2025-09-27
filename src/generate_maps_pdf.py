"""
generate_maps_pdf.py
====================

This script reads a CSV file containing Google Map links (one per row), extracts
the geographic coordinates from each link, loads an uncluttered map view for
those coordinates, and prints that view to PDF.  All individual PDF pages are
combined into a single, landscape‑oriented PDF.

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
* Because the script opens a bare map centered on the extracted latitude and
  longitude (using the ``ll`` parameter), there is no place summary panel to
  collapse.  This replicates the effect of collapsing the side panel in
  an interactive session.
"""

import argparse
import base64
import csv
import os
import re
import sys
import time
from io import BytesIO

from PyPDF2 import PdfReader, PdfWriter

# Selenium imports are deferred so that the script's help can be printed
# without requiring the package to be installed.
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError as exc:  # pragma: no cover
    webdriver = None  # type: ignore
    Options = None  # type: ignore


def extract_coordinates(link: str) -> tuple[float, float] | None:
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


def read_links_from_csv(path: str, max_links: int | None = None) -> list[str]:
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


def get_chrome_driver(chromedriver_path: str | None) -> webdriver.Chrome:
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
    driver = webdriver.Chrome(executable_path=chromedriver_path, options=chrome_options)
    return driver


def print_map_pages(
    links: list[str],
    driver: webdriver.Chrome,
    orientation_landscape: bool = True,
    page_wait: float = 5.0,
) -> list[bytes]:
    """Generate PDF pages for each map link.

    Each link is converted into a bare map view (without the place card) by
    extracting its coordinates and zoom level and constructing a URL of the
    form ``https://maps.google.com/maps?ll=lat,lon&z=zoom``.  The driver
    navigates to this URL and uses the Chrome DevTools API to capture a
    PDF snapshot.

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

    Returns
    -------
    list[bytes]
        A list containing the PDF data (as bytes) for each map page.
    """
    pdf_pages: list[bytes] = []
    for idx, link in enumerate(links, start=1):
        coords = extract_coordinates(link)
        if coords is None:
            print(f"[WARN] Could not extract coordinates from link {idx}: {link}")
            continue
        lat, lon = coords
        zoom = extract_zoom(link)
        map_url = f"https://maps.google.com/maps?ll={lat},{lon}&z={zoom}"
        print(f"Loading map {idx}/{len(links)}: {map_url}")
        driver.get(map_url)
        # allow some time for map tiles to load
        time.sleep(page_wait)
        # Use the Chrome DevTools Protocol to print to PDF
        print_opts = {
            "landscape": orientation_landscape,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "printBackground": True,
        }
        result = driver.execute_cdp_cmd("Page.printToPDF", print_opts)  # type: ignore
        pdf_data = base64.b64decode(result["data"])
        pdf_pages.append(pdf_data)
    return pdf_pages


def merge_pdf_pages(pages: list[bytes], output_path: str) -> None:
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
        help="Print pages in portrait orientation instead of landscape.",
    )
    args = parser.parse_args()

    links = read_links_from_csv(args.input, max_links=args.limit)
    if not links:
        print("No links found in the input file.")
        sys.exit(1)

    # Initialize Chrome driver
    driver = get_chrome_driver(args.driver_path)
    try:
        pages = print_map_pages(
            links,
            driver,
            orientation_landscape=not args.portrait,
            page_wait=args.wait,
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