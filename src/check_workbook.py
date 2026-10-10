"""
check_workbook.py
=================

Checks to run just before, and right after, generating the maps and
order forms from the season workbook.

Before generating (``--input`` only):

1. The bags of all orders add up to the ``Totals`` row at the bottom of
   ``Number of Bags`` (column Q) on the ``Customers`` sheet, and to
   ``Total Bags`` (column B) on the ``BasicOrderStats`` sheet.
2. The number of orders matches ``Orders`` on ``BasicOrderStats``, and
   every order has a ``Map Link`` (so there will be one map per order).
3. Each order's ``Map Link`` is for its ``Street Address``.

It also lists small routes (``route_suggestions``) that might be folded
into an adjacent route.  Those are suggestions for the user, not problems.

After generating (``--maps-dir`` and/or ``--orders-dir``): the PDFs have
one page per order in total and per delivery route, and each page is for
the right order: each order form page is compared with the form drawn
for that order, and each map page's title must be that order's address.
With ``--stop-order`` (from ``route_order.py``), every order must be a
stop on its own route, and the pages must be in stop order.

The ``BasicOrderStats`` checks are skipped for CSV input, which has only
one sheet.  Exits with status 1 if any check fails.

Usage::

    python check_workbook.py --input "Mulch Sales - Fall 2026.xlsx"
    python check_workbook.py --input "..." --maps-dir output/maps --orders-dir output/orders \
        --stop-order output/stop_order.json
"""

import argparse
import collections
import contextlib
import glob
import io
import json
import math
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from addresses import same_street_address
from generate_maps_pdf import extract_address, extract_coordinates
from generate_order_forms import draw_order_form, is_order_row, load_fonts, parse_order_records, route_groups
from route_order import in_stop_order, load_stop_order, pin_coordinates, stop_label
from sheet_reader import read_rows

STATS_SHEET = "BasicOrderStats"

# A route with at most this many orders and bags may be worth folding into an
# adjacent route.  Larger orders may need a truck to themselves.
SMALL_ROUTE_MAX_ORDERS = 2
SMALL_ROUTE_MAX_BAGS = 40
# Orders far from the rest go on this route; never suggest folding into it.
OUTLIER_ROUTE = "Outlier"


def load_orders(path: str, sheet: Optional[str] = None) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Return the order rows (as dicts) and the ``Totals`` bag count, if any."""
    rows, _ = read_rows(path, sheet)
    header_row_idx = 0
    for i, candidate in enumerate(rows[:10]):
        if "LastName" in [c.strip() for c in candidate]:
            header_row_idx = i
            break
    header = [c.strip() for c in rows[header_row_idx]] if rows else []
    orders: List[Dict[str, str]] = []
    totals_bags: Optional[str] = None
    for row_idx in range(header_row_idx + 1, len(rows)):
        row = {k: v.strip() for k, v in zip(header, rows[row_idx])}
        if is_order_row(row):
            row["_row"] = row_idx + 1  # the row number in the sheet
            orders.append(row)
        elif "Totals" in row.values() and totals_bags is None:
            totals_bags = row.get("Number of Bags", "") or None
    return orders, totals_bags


def load_stats(path: str) -> Optional[Dict[str, str]]:
    """Return ``BasicOrderStats`` as {label: value}, or None if there is none."""
    if not path.lower().endswith((".xlsx", ".xlsm")):
        return None
    try:
        rows, _ = read_rows(path, STATS_SHEET)
    except KeyError:
        return None
    return {r[0].strip(): r[1].strip() for r in rows if len(r) > 1 and r[0].strip()}


def route_file(route: str) -> str:
    """The PDF name both scripts use for a delivery route."""
    return (re.sub(r"[^A-Za-z0-9]+", "_", route.strip()) or "orders") if route else "orders"


def check_before(path: str, sheet: Optional[str] = None) -> List[str]:
    """Run checks 1-3 on the workbook; print a report and return the problems."""
    problems: List[str] = []
    orders, totals_bags = load_orders(path, sheet)
    stats = load_stats(path)
    bags = sum(int(o["Number of Bags"]) for o in orders)
    with_link = [o for o in orders if o.get("Map Link")]

    print(f"Orders: {len(orders)}  Bags: {bags}  With Map Link: {len(with_link)}")

    # 1. Bag totals
    if totals_bags is None:
        problems.append("No 'Totals' row found at the bottom of the Customers sheet.")
    elif totals_bags != str(bags):
        problems.append(f"Totals row says {totals_bags} bags, but the orders add up to {bags}.")
    if stats is not None:
        stat_bags = stats.get("Total Bags")
        if stat_bags != str(bags):
            problems.append(f"{STATS_SHEET} 'Total Bags' is {stat_bags}, but the orders add up to {bags}.")

    # 2. Number of orders, and a map for each
    if stats is not None:
        stat_orders = stats.get("Orders")
        if stat_orders != str(len(orders)):
            problems.append(f"{STATS_SHEET} 'Orders' is {stat_orders}, but there are {len(orders)} orders.")
    for o in orders:
        if not o.get("Map Link"):
            problems.append(f"{o.get('Street Address')} ({o.get('Delivery Route')}): no Map Link.")

    # 3. Map link is for the street address
    for o in with_link:
        link_address = extract_address(o["Map Link"])
        if link_address and not same_street_address(link_address, o.get("Street Address", "")):
            problems.append(
                f"{o.get('Street Address')} ({o.get('Delivery Route')}): "
                f"Map Link is for '{link_address}'."
            )

    _report("Before generating", problems)

    suggestions = route_suggestions(orders)
    if suggestions:
        print(f"Routes to consider folding into an adjacent route ({len(suggestions)}; not errors):")
        for s in suggestions:
            print(f"  - {s}")
    return problems


def _route_family(route: str) -> str:
    """``"Fairfax 01"`` for ``"Fairfax 01A"``, ``"Fairfax 01B"`` and ``"Fairfax 01"``."""
    return re.sub(r"(?<=\d)[A-Za-z]+$", "", route.strip())


def _straight_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def route_suggestions(orders: List[Dict[str, str]]) -> List[str]:
    """Small routes that might be folded into an adjacent route.

    A route is small with at most ``SMALL_ROUTE_MAX_ORDERS`` orders and
    ``SMALL_ROUTE_MAX_BAGS`` bags.  For each, list the routes of the same
    family (Fairfax 01A/01B/01C) and the closest other route (straight line
    between their nearest stops, from the map links' pins).
    """
    routes: "collections.OrderedDict[str, List[Dict[str, str]]]" = collections.OrderedDict()
    for o in orders:
        routes.setdefault(o.get("Delivery Route", ""), []).append(o)

    def where(o: Dict[str, str]) -> Optional[Tuple[float, float]]:
        link = o.get("Map Link", "")
        return pin_coordinates(link) or extract_coordinates(link)

    def size(route: str) -> str:
        group = routes[route]
        return f"{len(group)} order(s), {sum(int(o['Number of Bags']) for o in group)} bags"

    located = {r: [p for p in map(where, group) if p] for r, group in routes.items()}
    suggestions: List[str] = []
    for route, group in sorted(routes.items()):
        bags = sum(int(o["Number of Bags"]) for o in group)
        if route == OUTLIER_ROUTE or len(group) > SMALL_ROUTE_MAX_ORDERS or bags > SMALL_ROUTE_MAX_BAGS:
            continue
        parts = [f"{route} has {size(route)} ({', '.join(o.get('Street Address', '') for o in group)})."]
        family = [r for r in sorted(routes) if r != route and _route_family(r) == _route_family(route)]
        if family:
            parts.append("Same area: " + "; ".join(f"{r} ({size(r)})" for r in family) + ".")
        distances = [
            (min(_straight_km(a, b) for a in located[route] for b in located[r]), r)
            for r in routes
            if r not in (route, OUTLIER_ROUTE) and located[r] and located[route]
        ]
        if distances:
            km, closest = min(distances)
            parts.append(f"Closest route: {closest} ({size(closest)}), {km:.1f} km away.")
        suggestions.append(" ".join(parts))
    return suggestions


def check_after(
    path: str,
    sheet: Optional[str] = None,
    maps_dir: Optional[str] = None,
    orders_dir: Optional[str] = None,
    stop_order: Optional[str] = None,
) -> List[str]:
    """Check the generated PDFs have one page per order; return the problems."""
    from PyPDF2 import PdfReader

    problems: List[str] = []
    orders, _ = load_orders(path, sheet)
    stops = None
    if stop_order:
        stops = load_stop_order(stop_order)
        problems += _check_stop_order(stop_order, orders)
    stats = load_stats(path)
    expected_total = int(stats["Orders"]) if stats and stats.get("Orders", "").isdigit() else len(orders)
    for kind, out_dir, rows in (
        ("maps", maps_dir, [o for o in orders if o.get("Map Link")]),
        ("order forms", orders_dir, orders),
    ):
        if not out_dir:
            continue
        expected = collections.Counter(route_file(o.get("Delivery Route", "")) + ".pdf" for o in rows)
        actual = {
            os.path.basename(f): len(PdfReader(f).pages)
            for f in glob.glob(os.path.join(out_dir, "*.pdf"))
        }
        total = sum(actual.values())
        print(f"{kind}: {total} page(s) in {len(actual)} file(s) in {out_dir}")
        if kind == "maps":
            problems += _check_map_pages(out_dir, rows, stops)
        else:
            problems += _check_order_form_pages(out_dir, path, sheet, stops)
        if total != expected_total:
            problems.append(f"{kind}: {total} pages, but there are {expected_total} orders.")
        for name in sorted(set(expected) | set(actual)):
            if expected.get(name, 0) != actual.get(name, 0):
                problems.append(
                    f"{kind}: {name} has {actual.get(name, 0)} page(s), expected {expected.get(name, 0)}."
                )
    _report("After generating", problems)
    return problems


def _by_route(items, route_of) -> "collections.OrderedDict[str, list]":
    """Group items by route PDF name, in the order the scripts write pages."""
    groups: "collections.OrderedDict[str, list]" = collections.OrderedDict()
    for item in items:
        groups.setdefault(route_file(route_of(item)) + ".pdf", []).append(item)
    return groups


def _check_stop_order(stop_order: str, orders: List[Dict[str, str]]) -> List[str]:
    """Every order must be one stop, on its own route, in the stop order file."""
    with open(stop_order, encoding="utf-8") as f:
        routes = json.load(f)["routes"]
    route_of_row = {int(s["row"]): route for route, stops in routes.items() for s in stops}
    problems: List[str] = []
    for o in orders:
        route = route_of_row.pop(o["_row"], None)
        if route != o.get("Delivery Route", ""):
            problems.append(
                f"stop order: {o.get('Street Address')} ({o.get('Delivery Route')}) is "
                + (f"a stop on '{route}'." if route is not None else "not a stop on any route.")
                + " Rerun route_order.py."
            )
    for row, route in route_of_row.items():
        problems.append(f"stop order: row {row} ({route}) is not an order. Rerun route_order.py.")
    return problems


def _check_map_pages(
    out_dir: str, orders: List[Dict[str, str]], stops: Optional[Dict[int, Tuple[int, int]]] = None
) -> List[str]:
    """Each map page's title must be the address of the order for that page.

    With ``stops``, the page must also say that order's "Stop n of N".
    """
    from PyPDF2 import PdfReader

    problems: List[str] = []
    for name, group in _by_route(orders, lambda o: o.get("Delivery Route", "")).items():
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            continue
        group = in_stop_order(group, lambda o: o["_row"], stops)
        pages = PdfReader(path).pages
        for i, order in enumerate(group[: len(pages)]):
            title = extract_address(order["Map Link"]) or ""
            # Text extraction splits words oddly ("Stop 1 1 of 14"), so ignore spaces.
            squash = lambda t: re.sub(r"\s+", "", t).lower()
            text = squash(pages[i].extract_text() or "")
            if squash(title.split(",")[0]) not in text:
                problems.append(
                    f"maps: {name} page {i + 1} should be {order.get('Street Address')} "
                    f"('{title}') but isn't."
                )
            stop = stop_label(order["_row"], stops)
            if stop and squash(f"Stop {stop}") not in text:
                problems.append(f"maps: {name} page {i + 1} doesn't say 'Stop {stop}'.")
    return problems


def _page_image(page):
    """The single image an order form page consists of."""
    from PIL import Image

    xobjects = page["/Resources"]["/XObject"]
    data = xobjects[list(xobjects)[0]].get_object()._data
    return Image.open(io.BytesIO(data)).convert("L")


def _check_order_form_pages(
    out_dir: str, path: str, sheet: Optional[str], stops: Optional[Dict[int, Tuple[int, int]]] = None
) -> List[str]:
    """Each order form page must look like the form drawn for its order."""
    from PIL import ImageChops
    from PyPDF2 import PdfReader

    problems: List[str] = []
    with contextlib.redirect_stdout(io.StringIO()):  # warnings already shown
        records = parse_order_records(path, sheet)
    fonts = load_fonts()
    for route, group in route_groups(records, stops).items():
        name = route_file(route) + ".pdf"
        pdf = os.path.join(out_dir, name)
        if not os.path.exists(pdf):
            continue
        pages = PdfReader(pdf).pages
        for i, rec in enumerate(group[: len(pages)]):
            expected = draw_order_form(rec, fonts).convert("L")
            actual = _page_image(pages[i])
            # JPEG compression changes pixels a little; a different order
            # changes many pixels a lot.
            diff = ImageChops.difference(expected, actual.resize(expected.size))
            changed = sum(diff.point(lambda v: 255 if v > 100 else 0).histogram()[255:])
            if changed > 50:
                problems.append(
                    f"order forms: {name} page {i + 1} should be {rec.get('customer')}, "
                    f"{rec.get('address')} ({rec.get('bags')} bags) but isn't."
                )
    return problems


def _report(title: str, problems: List[str]) -> None:
    if problems:
        print(f"{title}: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"{title}: all checks passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the season workbook and the generated PDFs.")
    parser.add_argument("--input", required=True, help="Season spreadsheet (.xlsx) or CSV export.")
    parser.add_argument("--sheet", help="Customer sheet in an .xlsx input (default: the first sheet).")
    parser.add_argument("--maps-dir", help="Check the generated map PDFs in this directory.")
    parser.add_argument("--orders-dir", help="Check the generated order form PDFs in this directory.")
    parser.add_argument("--stop-order", help="Stop order file (route_order.py) the PDFs were made with.")
    args = parser.parse_args()
    if args.maps_dir or args.orders_dir:
        problems = check_after(args.input, args.sheet, args.maps_dir, args.orders_dir, args.stop_order)
    else:
        problems = check_before(args.input, args.sheet)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
