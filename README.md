# Print Google Maps to PDF

Small Python utility that reads a CSV of Google Maps links (one URL per
row), opens each location in headless Chrome, captures a PDF snapshot
using Chrome DevTools `printToPDF`, and merges the pages into a single
landscape PDF.

Key files
- `src/generate_maps_pdf.py` — primary, documented implementation used by
  the provided wrapper script.
- `generate_maps_pdf.py` — top-level variant (same core logic). Either may
  be used; the wrapper calls the `src/` copy by default.
- `scripts/run_generate_maps_pdf.sh` — convenience wrapper that accepts a
  single positional `input` CSV and sensible defaults for output and
  driver path.
- `input/` — sample CSVs to try locally.

Quick start
1. Install Python 3.7+.
2. Install required packages into the Python interpreter you will use:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install selenium PyPDF2
```

3. Ensure Chrome/Chromium is installed and download a matching
   ChromeDriver binary. Put it on `PATH` or pass its path to the script.

Run the wrapper (recommended):

```bash
./scripts/run_generate_maps_pdf.sh input/map-print-test-Spring-2025-2-lines.csv
```

Or run the script directly:

```bash
python3 src/generate_maps_pdf.py \
  --input input/map-print-test-Spring-2025-2-lines.csv \
  --output output/output_maps.pdf \
  --driver-path lib/chromedriver \
  --wait 5 --limit 10 --paper-width 11 --paper-height 8.5
```

Notes & troubleshooting
- If you see "No module named 'PyPDF2'": the interpreter used to run the
  script doesn't have PyPDF2 installed. Fix by installing into that same
  interpreter: `python3 -m pip install PyPDF2 selenium` (use the same
  `python3` binary you will run the script with).
- ChromeDriver version mismatch is a common failure mode. Download a
  matching driver: https://chromedriver.chromium.org and make it
  executable: `chmod +x lib/chromedriver`.
- The script supports two display modes: coordinate-based (default) and
  original link mode (`--use-original`). Coordinate mode builds URLs like

  `https://maps.google.com/maps?q={lat},{lon}&ll={lat},{lon}&z={zoom}`

  to remove the place card and still show a marker.

Where to look when changing behavior
- `print_map_pages(...)` in `src/generate_maps_pdf.py` constructs the
  Chrome `Page.printToPDF` options (`paperWidth`, `paperHeight`, `scale`,
  `headerTemplate`). Edit that dict to tweak PDF layout.
- Pure helpers `extract_coordinates`, `extract_zoom`, `extract_address`
  live in the same module and are good targets for unit tests.

If you want, I can add a `requirements.txt`, a tiny unit test for the
parsing helpers, or make the wrapper auto-detect a virtualenv Python.
