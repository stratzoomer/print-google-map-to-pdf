# Print Google Maps to PDF

Python utilities that read a CSV of order data with Google Maps links:
one script generates order form PDFs (receipts); another captures map
PDFs using headless Chrome.

Key files
- `src/generate_order_forms.py` — generates order form PDFs grouped by
  Delivery Route. One combined PDF per route (e.g. `Fairfax_12B.pdf`).
  Requires Pillow and PyPDF2.
- `src/generate_maps_pdf.py` — generates map PDFs from Google Maps links.
- `run_generate_maps_pdf.sh` — convenience wrapper. Runs maps and/or order
  forms via `--maps`, `--orders`, or `--all` (default). Creates `.venv`,
  installs dependencies automatically.
- `requirements.txt` — Python dependencies (selenium, PyPDF2, Pillow).
- `input/` — sample CSVs.

Quick start

1. Install Python 3.7+.

2. **Order forms only** (no Chrome needed):

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install Pillow

python3 src/generate_order_forms.py --input input.csv --output output/forms
```

Creates one PDF per delivery route (e.g. `Fairfax_12B.pdf`), each
containing all order forms for that route.

3. **Wrapper script** — runs both, or either, with venv and deps handled:

```bash
./run_generate_maps_pdf.sh input/data.csv              # both (maps + orders)
./run_generate_maps_pdf.sh --maps input/data.csv       # maps only
./run_generate_maps_pdf.sh --orders input/data.csv     # order forms only
```

Maps require Chrome/Chromium. Order forms do not. With `--all` (default),
output goes to `output/maps/` and `output/orders/`. Pass a second arg for a
custom output dir. Use a third arg for a custom ChromeDriver path.

generate_order_forms.py — CSV format
- Expects columns: `Comment`, `Support Troop Amount`, `LastName`, `FirstName`,
  `Town`, `Street Address`, `EmailAddress`, `Number of Bags`, `Delivery Route`,
  `Delivery Instructions`. Order # is parsed from `Comment` when it matches
  "Order 12345".

Notes & troubleshooting
- `generate_order_forms.py` requires Pillow and PyPDF2: `pip install -r requirements.txt`
  or `pip install Pillow PyPDF2`.
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

