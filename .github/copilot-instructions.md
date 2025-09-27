## Quick orientation

This repository is a small, single-purpose Python utility that converts a
CSV of Google Maps links into a single landscape PDF by driving Chrome
headlessly and using Chrome DevTools `printToPDF` to capture each map.

Key files
- `generate_maps_pdf.py` — the main, documented script. Study this file to
  understand the full runtime flow: CSV -> extract coords/zoom -> load map ->
  printToPDF -> merge PDFs.
- `input/` — sample input CSVs with one Google map url per line (e.g. `map-print-test-Spring-2025-10-lines.csv`).
- `lib/chromedriver` — a bundled driver used by developers (note: version must
  match local Chrome).

Runtime & dependencies (how to run)
- Requires Python 3.7+ and two PyPI packages: `selenium` and `PyPDF2`.
  Install with: `pip install selenium PyPDF2`.
- Chrome (or Chromium) and a matching ChromeDriver are required. The script
  accepts `--driver-path` or will look for `chromedriver` on PATH.
- Typical run (use the sample CSV in `input/` and bundled driver):

```bash
python3 generate_maps_pdf.py \
  --input input/map-print-test-Spring-2025-10-lines.csv \
  --output output/output_maps.pdf \
  --driver-path lib/chromedriver \
  --wait 5 --limit 10 --paper-width 11 --paper-height 8.5
```

Important code patterns and conventions (for AI agents)
- CSV reading: `read_links_from_csv(path, max_links)` expects one URL per
  *row* and uses the stdlib `csv` module — treat the first field as the URL.
- URL parsing helpers: `extract_coordinates(link)`, `extract_zoom(link)`, and
  `extract_address(link)` are the single-source-of-truth for interpreting
  Google Maps links. Unit tests should target these pure functions first.
- Coordinate mode vs original link: the script prefers building a
  coordinate-based URL (using `q` and `ll`) to hide the side panel while
  preserving a visible marker. See the `print_map_pages(..., use_coordinates=...)`
  call and the constructed URL:

```py
f"https://maps.google.com/maps?q={lat},{lon}&ll={lat},{lon}&z={zoom}"
```

- PDF printing: the driver calls Chrome DevTools `Page.printToPDF` via
  `driver.execute_cdp_cmd("Page.printToPDF", print_opts)`. `paperWidth` and
  `paperHeight` are specified in inches and are what controls landscape
  output (not `--portrait`). When altering print layout, edit the
  `print_opts` dict in `print_map_pages`.
- Header handling: `include_header` populates `print_opts['headerTemplate']`
  with a small HTML snippet using `extract_address(link)`. If adding richer
  HTML, sanitize input and keep it small — Chrome header templates are limited.
- Selenium import is intentionally deferred and guarded so the script still
  prints `--help` without `selenium` installed. Follow this pattern for
  optional heavy deps if you add similar tools.

Common pitfalls / gotchas (discovered in repo)
- ChromeDriver version mismatch is the most frequent runtime error. The
  repository includes `lib/chromedriver` for convenience — prefer matching
  local Chrome to that driver or supply your own via `--driver-path`.
- `printToPDF` options expect values in inches (`paperWidth`/`paperHeight`) and
  `scale` must be between 0.1 and 2.0. If a user reports layout issues,
  check the `window_width`/`window_height` parameters which affect framing.
- Network and Google Maps UI changes can silently break visual results —
  tests that assert only parsing helpers are reliable; end-to-end tests that
  hit maps are inherently brittle.

Where to start when making changes
- Small fixes: update `extract_*` helpers and add a unit test for them.
- Layout/printing tweaks: change `print_opts` in `print_map_pages` and test
  locally using the `--limit` option to avoid long runs.
- Adding CI: create minimal tests for `extract_coordinates`, `extract_zoom`,
  and `extract_address` (pure functions) before attempting headless runs in CI.

Files that show expected outputs
- `manual-print.pdf`, `script-print.pdf`, `output_maps.pdf` — these are
  example PDFs produced by the tool. Use them for visual diffs when adjusting
  print settings.

If anything above is unclear or you want the instructions tailored for a
particular agent persona (test-authoring, refactorer, or CI integrator), say
which focus you prefer and I'll iterate the file.
