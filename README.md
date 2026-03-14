# Print Google Maps to PDF

Python utilities that read a CSV of order data with Google Maps links,
generate order forms (receipts), and capture map PDFs using headless
Chrome. For delivery workflows, the preferred script produces combined
PDFs with an order form followed by the map for each address.

Key files
- `src/generate_order_forms.py` — **recommended**: generates order form +
  map PDFs combined, grouped by delivery route. One PDF per route with
  alternating order form (portrait) and map (landscape) pages per record.
- `src/generate_maps_pdf.py` — maps only.
- `run_generate_maps_pdf.sh` — convenience wrapper for maps-only output.
  Creates and uses a `.venv`, installs dependencies automatically.
- `requirements.txt` — Python dependencies (selenium, PyPDF2, Pillow).
- `input/` — sample CSVs. `new-data.csv` and `wait-list-4-records.csv`
  share the same format and work with both scripts.

Quick start

1. Install Python 3.7+ and ensure Chrome/Chromium is installed.

2. **Recommended — order form + map combined** (one PDF per delivery route):

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 src/generate_order_forms.py \
  --input input/wait-list-4-records.csv \
  --output output/combined \
  --use-original
```

Creates files like `output/combined/Fairfax_Station_12.pdf`, each containing
order form pages and map pages for every record on that route.

3. **Maps only** — no manual setup: the wrapper creates a venv and installs
   dependencies automatically:

```bash
./run_generate_maps_pdf.sh input/input-2-lines-with-delivery-route.csv
```

Or run the maps script directly (after activating the venv from step 2):

```bash
python3 src/generate_maps_pdf.py \
  --input input/input-2-lines-with-delivery-route.csv \
  --output output/output_maps.pdf \
  --use-original
```

By default, Selenium Manager auto-downloads a matching ChromeDriver; no
manual driver install is needed. To use a specific driver for maps:
`./run_generate_maps_pdf.sh input.csv output.pdf lib/chromedriver`.

generate_order_forms.py — CSV format and options
- Expects columns: `Map Link`, `Delivery Route`, `Number of Bags`, `Comment`,
  `Support Troop Amount`, `LastName`, `FirstName`, `Town`, `Street Address`,
  `EmailAddress`, `Delivery Instructions`. Order # is parsed from `Comment`
  when it matches "Order 12345".
- `new-data.csv` and `wait-list-4-records.csv` use the same format; both work.
- Options: `--use-original` (print original Google Maps link), `--no-header`,
  `--no-marker`, `--driver-path`, `--wait`, `--paper-width`, `--paper-height`.

Notes & troubleshooting
- If you see "No module named 'PyPDF2'" or "No module named 'PIL'" when running
  `generate_order_forms.py` directly: activate the venv
  (`source .venv/bin/activate`) and run `pip install -r requirements.txt`.
  The maps wrapper (`run_generate_maps_pdf.sh`) handles this automatically.
- ChromeDriver version mismatch: omit `--driver-path` to let Selenium
  Manager fetch the correct driver. If using a manual driver, download a
  version matching your Chrome from https://chromedriver.chromium.org and
  make it executable: `chmod +x lib/chromedriver`.
- Map display modes: coordinate-based (default) or original link
  (`--use-original`). With `--use-original`, the script prints the full
  Google Maps URL. Output is one PDF per delivery route (e.g.
  `output/combined/Fairfax_12B.pdf`).
- Empty space at bottom of maps: the script sets the browser window to match
  the paper aspect ratio (11×8.5 by default) to minimize this. If you still
  see excess space, try `--scale 1.05` (or up to 1.1) to zoom the content.

Where to look when changing behavior
- `print_map_pages(...)` in `src/generate_maps_pdf.py` constructs the
  Chrome `Page.printToPDF` options (`paperWidth`, `paperHeight`, `scale`,
  `headerTemplate`). Edit that dict to tweak PDF layout.
- Pure helpers `extract_coordinates`, `extract_zoom`, `extract_address`
  live in the same module and are good targets for unit tests.

