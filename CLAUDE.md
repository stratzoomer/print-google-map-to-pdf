# Notes for working on this project

Troop 1865 mulch sale: prints a map page and an order form per delivery.
See README.md for usage.

Tests: `python3 -m unittest discover tests` (in `.venv`). The fixture
`tests/fixtures/season_export.csv` is made-up data in the season sheet
format (the `.xlsx` tests build a workbook from it). Never copy real rows
from `input/` into it (customer names/emails).

`tests/test_season_workflows.py` runs every workflow (checks, stop order,
order forms, map page checks, the wrapper, the driver log analysis) on
`tests/fixtures/season_anonymized.xlsx`, an anonymized copy of the Fall
2026 workbook made by `tests/fixtures/anonymize_workbook.py` (made-up
names, addresses, locations, comments, instructions and drivers; it refuses
to save if a real value is left). That's the only way real data may go into
a fixture, and the repo is public: after regenerating it, check the copy
yourself before committing it. Regenerating it changes the expected numbers
in the tests.

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
4. Each order's `Conditional Delivery route` (column M, formula
   `=IF(Q>0,L,"")`) equals its `Delivery Route` (column L). The per-route
   order counts on `OrderDataByDeliveryRoute` count column M, so a row
   missing that formula drops out of its route's count. The season totals
   don't change, so checks 1–2 can't catch it.
5. Each route's `Orders` and `Bags` on `OrderDataByDeliveryRoute` match the
   orders on `Customers`.
6. Sometimes the delivery instructions can be incorrectly in the `Comment` field, as opposed to the `Delivery Instructions`. Report any that is found to the user.

The same check also lists **small routes** (at most 2 orders and 40 bags,
`SMALL_ROUTE_MAX_*` in `src/check_workbook.py`) with the routes of the same
family (e.g. Fairfax 01A and 01B) and the closest route. These are
suggestions, not errors; they don't stop the run. Before generating, show
them to the user, when asking for the API key, and ask whether they want to
fold any routes first. If they do, they change `Delivery Route` in the
spreadsheet and ask for a regeneration. Never suggest folding into
`Outlier`.

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

## After the delivery day

The drivers log each route on `OrderDataByDeliveryRoute`: `Driver(s):`,
`Time Out` (left the Sideburn Run lot) and `Time In` (back). Analyze it with
`.venv/bin/python src/analyze_deliveries.py --input "<workbook>" --csv-dir output/delivery_analysis`.
The miles of each trip (round trip from the lot) come from the season's
`output/stop_order.json` and `output/driving_distances.json`; without them
the typical trip time leaves the miles out, and far routes like `Outlier`
look slow.
It first checks that every route with bags has a `Time Out` and a `Time In`,
and that the `Time In` is later than the `Time Out`. If not, it lists those
rows and stops (exit 1): report them to the user to fix in the workbook
(don't reach for `--skip-checks` without asking). Routes one driver took
out at the same `Time Out` are one trip. A driver's routes that overlap
(one leaves before the trip is back) are expected, not a problem: drivers
add a route to a trip on the way for a more efficient delivery, so it's
one trip from the first `Time Out` to the last `Time In`. Report any other
log problems it lists with the rankings, since they change the per-minute
numbers.
