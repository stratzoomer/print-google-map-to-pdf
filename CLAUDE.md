# Notes for working on this project

Troop 1865 mulch sale: prints a map page and an order form per delivery.
See README.md for usage.

Tests: `python3 -m unittest discover tests` (in `.venv`). The fixture
`tests/fixtures/season_export.csv` is made-up data in the season sheet
format (the `.xlsx` tests build a workbook from it). Never copy real rows
from `input/` into it (customer names/emails).

## Input: the season workbook

- The input is the season's Excel workbook, kept in Dropbox and copied
  into `input/` (e.g. `input/20260914 01 Mulch Sales - Fall 2026.xlsx`).
  Use its first sheet, `Customers`. The format stays the same from year to
  year: a title row ("Fall 2026"), then the column header row, then the
  full customer list. Several columns are formulas; the scripts use the
  values Excel cached when the file was last saved.
- A CSV export of the `Customers` sheet also works (usually cp1252
  encoded), but it loses the red text (see below).
- Only rows with a positive `Number of Bags` are orders for this season.
  Summary rows (Totals, Pallets, ...) sit at the bottom of the sheet.

## Known data conventions (don't flag these as problems)

- **United Methodist St George's** (4910 Ox Road) is the troop's benefactor.
  Their order has no `Support Troop Amount` because they don't pay. That's
  expected.
- **Mail-in orders** have no `Order #` (nothing in `Comment` matching
  "Order 12345") and usually have an odd `Batch Increment #`. That's expected.
- **Red text in `Comment`** marks something that needs special action
  (e.g. "Need one pallet"). With `.xlsx` input, exactly the red text is
  printed in red in the map page header, under the delivery route. With CSV
  input (no colours), any comment that isn't "Order 12345" is used instead.

## Stop order (single pass per delivery route)

The trucks start at the **Sideburn Run Recreation Association** parking lot,
10603 Zion Dr, Fairfax, VA 22032 (`START` in `src/route_order.py`). With a
Google Maps API key, the wrapper runs `src/route_order.py` after the checks
below pass. It puts each route's stops in the order with the shortest total
driving distance from there, using the Routes API (no traffic). The truck
doesn't return, so the pass can end at any stop. The result goes to
`output/stop_order.json`, and the distances are cached in
`output/driving_distances.json`. Maps and order forms are printed in that
order, and each page shows "Stop n of N". Links without a pin
(`!3d…!4d…`, only the map centre `@…`) are opened in Chrome to find the pin.
A route with stops far apart (e.g. `Outlier`) still gets an order, but it may
not be one trip.

**The API key:**
- At the start of every generation, ask the user for the Google Maps API key,
  or whether to skip route ordering. Don't reuse a key from earlier in the
  conversation without asking.
- Pass it only to that command, as an environment variable:
  `GOOGLE_MAPS_API_KEY='<key>' ./run_generate_maps_pdf.sh "<workbook>"`.
- Never write the key to a file, a commit, a log or a message, and never
  echo it back.
- If the user has no key or doesn't want ordering, run with
  `--no-route-order`. Each route's maps and order forms then stay in
  spreadsheet order (the same order in both), with no stop numbers.
- If the key is refused, the run stops (exit 6) with Google's reason. Report
  it, and ask whether to retry with another key or go on without ordering.

## Checks when generating the maps and order forms

Always generate with `./run_generate_maps_pdf.sh "<workbook>"` (see above
for the API key). It runs
`src/check_workbook.py` just before generating and stops if a check fails
(fix the workbook, don't reach for `--skip-checks` without asking):

1. The bags of all orders = the `Totals` value at the bottom of `Number of
   Bags` (column Q) on `Customers` = `Total Bags` (column B) on
   `BasicOrderStats`.
2. The number of orders = `Orders` (column B) on `BasicOrderStats`, and every
   order has a `Map Link`.
3. Each `Map Link` is for the order's `Street Address` (column H).
4. Sometimes the delivery instructions can be incorrectly in the `Comment` field, as opposed to the `Delivery Instructions`. Report any that is found to the user.

While printing, the maps script also compares the place Google Maps actually
loaded with `Street Address` for every map (`MAP CHECK` summary at the end).
After generating, the wrapper checks both `output/maps/` and
`output/orders/` have one page per order (total = `BasicOrderStats` Orders,
and per route), that every order is a stop on its own route in
`stop_order.json` (when the stops were ordered), and that every page is for
the right order, in stop order: each order form page (including its "Stop n of N") is compared with
the form drawn for that order, and each map page's title must be that
order's address. (Page counts alone are not enough: a
PDF-merging bug once printed some order forms twice and dropped others
while the page counts still matched.)

Then spot check at least 10% of the map pages and of the order form pages
(chosen at random, across routes) by rendering them and looking: the title
address, the pin, the route, the bag count, the stop number and any red note
on the maps, and the customer, address, bags, amount, instructions and stop
number on the order forms, must match that order's row and
`stop_order.json`.

Report any failures to the user with the rows involved.

## Before the final print

- St George's `Delivery Instructions` are "TBD" until the church provides
  them. They must be filled in before the final print. `generate_order_forms.py`
  prints a WARNING for any order whose instructions are still "TBD".
- Every order needs a `Map Link`, otherwise it gets no map page (also warned).
