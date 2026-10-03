# Notes for working on this project

Troop 1865 mulch sale: prints a map page and an order form per delivery.
See README.md for usage.

Tests: `python3 -m unittest discover tests` (in `.venv`). The fixture
`tests/fixtures/season_export.csv` is made-up data in the season export
format. Never copy real rows from `input/` into it (customer names/emails).

## Input: the season sheet export

- Each season (e.g. `input/Fall-2026-*.csv`) is a CSV export of the Google
  Sheet, in a format that stays the same from year to year: a title row
  ("Fall 2026"), then the column header row, then the full customer list.
  Encoding is usually cp1252 (smart quotes).
- Only rows with a positive `Number of Bags` are orders for this season.
  Summary rows (Totals, Pallets, ...) sit at the bottom of the sheet.

## Known data conventions (don't flag these as problems)

- **United Methodist St George's** (4910 Ox Road) is the troop's benefactor.
  Their order has no `Support Troop Amount` because they don't pay. That's
  expected.
- **Mail-in orders** have no `Order #` (nothing in `Comment` matching
  "Order 12345") and usually have an odd `Batch Increment #`. That's expected.
- **Red text in `Comment`** marks something that needs special action
  (e.g. "Need one pallet"). The CSV export loses colour, so any comment that
  isn't "Order 12345" is treated as a special-action note and printed in red
  in the map page header, under the delivery route.

## Before the final print

- St George's `Delivery Instructions` are "TBD" until the church provides
  them. They must be filled in before the final print. `generate_order_forms.py`
  prints a WARNING for any order whose instructions are still "TBD".
- Every order needs a `Map Link`, otherwise it gets no map page (also warned).
