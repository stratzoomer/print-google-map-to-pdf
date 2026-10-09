"""
route_order.py
==============

Puts the stops of each delivery route in the order a truck should drive
them: the shortest single pass, by driving distance, that starts at the
trucks' starting point (``START``) and visits every stop of the route
once.  The truck doesn't come back, so the pass ends at whichever stop
makes it shortest.

Driving distances come from the Google Maps Routes API (Compute Route
Matrix, without traffic).  It needs an API key in the ``GOOGLE_MAPS_API_KEY``
environment variable.  The key is never written anywhere.  Distances
already fetched are kept in a cache file (``--cache``), so a rerun only
asks for routes whose stops changed.

The location of each stop is the pin in its ``Map Link``
(``!3d<lat>!4d<lng>``).  Some links only have the map's centre
(``@<lat>,<lng>``), which can be a few streets away from the house; those
links are opened in headless Chrome, and the pin is read from the address
Google Maps changes the page to.

The result is written to a JSON file that both generator scripts and the
checks read (``--stop-order``), so map page *n* and order form page *n* of
a route are always the same stop, labelled "Stop n of N".  Stops are
identified by their row number in the sheet.

Usage::

    GOOGLE_MAPS_API_KEY=... python route_order.py --input "Mulch Sales - Fall 2026.xlsx" \\
        --output output/stop_order.json --cache output/driving_distances.json
"""

import argparse
import itertools
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

LatLng = Tuple[float, float]
Matrix = List[List[float]]
T = TypeVar("T")

# Where the trucks start: the Sideburn Run Recreation Association parking lot.
START_NAME = "Sideburn Run Recreation Association, 10603 Zion Dr, Fairfax, VA 22032"
START: LatLng = (38.8099155, -77.3128345)

API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
ROUTES_API_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
# Request at most this many origins and this many destinations at a time
# (the API allows 50 origins + destinations and 625 pairs per request).
MAX_MATRIX_SIDE = 25

# Routes up to this many stops get the exact shortest order; longer ones
# (none so far) get a very good one (nearest neighbour, then 2-opt).
MAX_EXACT_STOPS = 15


class RouteOrderError(Exception):
    """The stops could not be ordered (e.g. the API key was refused)."""


def pin_coordinates(link: str) -> Optional[LatLng]:
    """The place pin in a Google Maps link (``!3d<lat>!4d<lng>``), if any."""
    matches = re.findall(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", link or "")
    if not matches:
        return None
    lat, lng = matches[-1]
    return float(lat), float(lng)


def path_length(dist: Matrix, order: Sequence[int]) -> float:
    """Length of the drive from the start (index 0 of ``dist``) through the
    stops in ``order`` (stop ``i`` is index ``i + 1`` of ``dist``)."""
    total, here = 0.0, 0
    for i in order:
        total += dist[here][i + 1]
        here = i + 1
    return total


def best_order(dist: Matrix) -> List[int]:
    """The shortest order to visit every stop, starting at the start.

    ``dist[a][b]`` is the distance from ``a`` to ``b``; index 0 is the start
    and index ``i + 1`` is stop ``i``.  Distances may differ by direction
    (one-way streets).  Returns the stop indexes (0-based) in order.
    """
    n = len(dist) - 1
    if n <= 1:
        return list(range(n))
    if n > MAX_EXACT_STOPS:
        return _two_opt(dist, _nearest_neighbour(dist))
    # Held-Karp: cost[mask][j] = shortest path from the start visiting the
    # stops in mask and ending at stop j.
    full = 1 << n
    cost = [[math.inf] * n for _ in range(full)]
    prev = [[-1] * n for _ in range(full)]
    for j in range(n):
        cost[1 << j][j] = dist[0][j + 1]
    for mask in range(1, full):
        row = cost[mask]
        for j in range(n):
            c = row[j]
            if c == math.inf:
                continue
            dj = dist[j + 1]
            for k in range(n):
                if mask & (1 << k):
                    continue
                nxt = mask | (1 << k)
                if c + dj[k + 1] < cost[nxt][k]:
                    cost[nxt][k] = c + dj[k + 1]
                    prev[nxt][k] = j
    mask = full - 1
    j = min(range(n), key=lambda k: cost[mask][k])
    order: List[int] = []
    while j != -1:
        order.append(j)
        mask, j = mask & ~(1 << j), prev[mask][j]
    return order[::-1]


def _nearest_neighbour(dist: Matrix) -> List[int]:
    left, order, here = set(range(len(dist) - 1)), [], 0
    while left:
        j = min(left, key=lambda k: dist[here][k + 1])
        order.append(j)
        left.remove(j)
        here = j + 1
    return order


def _two_opt(dist: Matrix, order: List[int]) -> List[int]:
    """Reverse stretches of the route while that makes it shorter."""
    best, improved = list(order), True
    while improved:
        improved = False
        for i, j in itertools.combinations(range(len(best)), 2):
            candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
            if path_length(dist, candidate) < path_length(dist, best) - 1e-9:
                best, improved = candidate, True
    return best


def _cache_key(a: LatLng, b: LatLng) -> str:
    return f"{a[0]:.7f},{a[1]:.7f}>{b[0]:.7f},{b[1]:.7f}"


def _request_matrix(origins: Sequence[LatLng], destinations: Sequence[LatLng], api_key: str) -> List[Dict]:
    """One Compute Route Matrix request; returns the API's elements."""
    def waypoint(p: LatLng) -> Dict:
        return {"waypoint": {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}}

    body = {
        "origins": [waypoint(p) for p in origins],
        "destinations": [waypoint(p) for p in destinations],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
    }
    request = urllib.request.Request(
        ROUTES_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "originIndex,destinationIndex,condition,distanceMeters,duration",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8"))
            if isinstance(error, list):  # the API wraps it in a list
                error = error[0]
            message = error["error"]["message"]
        except Exception:
            message = exc.reason
        raise RouteOrderError(f"Routes API refused the request (HTTP {exc.code}): {message}".replace(api_key, "***"))
    except urllib.error.URLError as exc:
        raise RouteOrderError(f"Could not reach the Routes API: {exc.reason}")


def driving_matrix(points: Sequence[LatLng], api_key: str, cache: Dict[str, Dict]) -> Matrix:
    """Driving distances (metres) between all ``points``, both directions.

    Uses ``cache`` ({"lat,lng>lat,lng": {"m": metres, "s": seconds}}) and
    adds what it fetches to it.
    """
    n = len(points)
    pairs = [(i, j) for i in range(n) for j in range(n) if i != j]
    if any(_cache_key(points[i], points[j]) not in cache for i, j in pairs):
        for oi in range(0, n, MAX_MATRIX_SIDE):
            for di in range(0, n, MAX_MATRIX_SIDE):
                origins = points[oi:oi + MAX_MATRIX_SIDE]
                destinations = points[di:di + MAX_MATRIX_SIDE]
                for el in _request_matrix(origins, destinations, api_key):
                    # Fields that are 0 are left out of the response.
                    i = oi + el.get("originIndex", 0)
                    j = di + el.get("destinationIndex", 0)
                    if i != j and el.get("condition") == "ROUTE_EXISTS":
                        cache[_cache_key(points[i], points[j])] = {
                            "m": el.get("distanceMeters", 0),
                            "s": int(str(el.get("duration", "0s")).rstrip("s") or 0),
                        }
    dist = [[0.0] * n for _ in range(n)]
    for i, j in pairs:
        found = cache.get(_cache_key(points[i], points[j]))
        if found is None:
            raise RouteOrderError(f"No driving route from {points[i]} to {points[j]}.")
        dist[i][j] = float(found["m"])
    return dist


def resolve_pins(links: Sequence[str], driver_path: Optional[str] = None) -> Dict[str, LatLng]:
    """Find the pin of each link that has none, by opening it in Chrome.

    Returns {link: (lat, lng)} for the links it could resolve.
    """
    from generate_maps_pdf import _strip_auth_params, _wait_for_map_ready, get_chrome_driver

    found: Dict[str, LatLng] = {}
    if not links:
        return found
    driver = get_chrome_driver(driver_path)
    driver.set_window_size(1400, 1080)
    try:
        for i, link in enumerate(links, start=1):
            print(f"Finding the pin {i}/{len(links)}: {link[:100]}", flush=True)
            try:
                driver.get(_strip_auth_params(link))
                _wait_for_map_ready(driver, timeout=20.0)
                for _ in range(20):
                    pin = pin_coordinates(driver.current_url)
                    if pin:
                        found[link] = pin
                        break
                    time.sleep(0.5)
            except Exception as exc:  # keep going; the caller falls back
                print(f"  could not load it ({exc.__class__.__name__}).")
    finally:
        driver.quit()
    return found


def plan_routes(
    orders: List[Dict[str, str]],
    pins: Dict[str, LatLng],
    matrix_for: Callable[[List[LatLng]], Matrix],
    start: LatLng = START,
) -> Tuple[Dict[str, List[Dict]], List[str]]:
    """Order the stops of every route; return (routes, warnings).

    ``orders`` are sheet rows (with ``_row``, the row number); ``pins`` the
    location of each Map Link; ``matrix_for(points)`` gives the distances
    (metres) between points.  Orders without a location go last, in sheet
    order.
    """
    from generate_maps_pdf import extract_coordinates

    by_route: Dict[str, List[Dict[str, str]]] = {}
    for o in orders:
        by_route.setdefault(o.get("Delivery Route", ""), []).append(o)
    routes: Dict[str, List[Dict]] = {}
    warnings: List[str] = []
    for route, group in by_route.items():
        located, unlocated = [], []
        for o in group:
            link = o.get("Map Link", "")
            where = pins.get(link) or pin_coordinates(link)
            if where is None and link:
                where = extract_coordinates(link)
                if where is not None:
                    warnings.append(
                        f"{o.get('Street Address')} ({route}): no pin found; used the map's centre instead."
                    )
            if where is None:
                warnings.append(f"{o.get('Street Address')} ({route}): no location; put last on the route.")
                unlocated.append(o)
            else:
                located.append((o, where))
        dist = matrix_for([start] + [w for _, w in located])
        stops: List[Dict] = []
        here = 0
        for i in best_order(dist):
            o, where = located[i]
            stops.append({
                "row": o["_row"],
                "street": o.get("Street Address", ""),
                "lat": where[0],
                "lng": where[1],
                "km_from_previous": round(dist[here][i + 1] / 1000, 2),
            })
            here = i + 1
        for o in unlocated:
            stops.append({"row": o["_row"], "street": o.get("Street Address", ""), "lat": None, "lng": None})
        routes[route] = stops
    return routes, warnings


def load_stop_order(path: str) -> Dict[int, Tuple[int, int]]:
    """Read a stop order file as {sheet row: (stop number, stops on route)}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    stops: Dict[int, Tuple[int, int]] = {}
    for route_stops in data["routes"].values():
        for n, stop in enumerate(route_stops, start=1):
            stops[int(stop["row"])] = (n, len(route_stops))
    return stops


def in_stop_order(items: List[T], row_of: Callable[[T], int], stops: Optional[Dict[int, Tuple[int, int]]]) -> List[T]:
    """``items`` (one route) sorted by stop number; unknown rows go last."""
    if not stops:
        return list(items)
    return sorted(items, key=lambda it: stops.get(row_of(it), (math.inf, 0))[0])


def stop_label(row: int, stops: Optional[Dict[int, Tuple[int, int]]]) -> Optional[str]:
    """``"Stop 3 of 7"`` for a sheet row, or None if it isn't in the file."""
    if not stops or row not in stops:
        return None
    n, total = stops[row]
    return f"{n} of {total}"


def main() -> None:
    from check_workbook import load_orders

    parser = argparse.ArgumentParser(
        description=f"Order the stops of each delivery route for a single pass, by driving "
        f"distance (needs a Google Maps API key in {API_KEY_ENV})."
    )
    parser.add_argument("--input", required=True, help="Season spreadsheet (.xlsx) or CSV export.")
    parser.add_argument("--sheet", help="Customer sheet in an .xlsx input (default: the first sheet).")
    parser.add_argument("--output", required=True, help="Where to write the stop order (JSON).")
    parser.add_argument("--cache", help="Driving distances fetched earlier (JSON); updated with new ones.")
    parser.add_argument("--driver-path", help="ChromeDriver path (default: Selenium Manager).")
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        print(f"No Google Maps API key: set {API_KEY_ENV} to order the stops by driving distance.")
        sys.exit(2)
    orders, _ = load_orders(args.input, args.sheet)
    if not orders:
        print("No orders found in the input file.")
        sys.exit(1)
    # Try the key with a single distance before the slower pin lookups.
    try:
        _request_matrix([START], [START], api_key)
    except RouteOrderError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    missing = sorted({o["Map Link"] for o in orders if o.get("Map Link") and not pin_coordinates(o["Map Link"])})
    print(f"{len(orders)} orders; {len(missing)} map link(s) without a pin to look up.", flush=True)
    pins = resolve_pins(missing, args.driver_path)

    cache: Dict[str, Dict] = {}
    if args.cache and os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)
    cached_before = len(cache)
    try:
        routes, warnings = plan_routes(orders, pins, lambda points: driving_matrix(points, api_key, cache))
    except RouteOrderError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        if args.cache and len(cache) > cached_before:
            with open(args.cache, "w", encoding="utf-8") as f:
                json.dump(cache, f)
    for w in warnings:
        print(f"WARNING: {w}")
    print(f"Driving distances: {cached_before} cached, {len(cache) - cached_before} fetched.")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"start": {"name": START_NAME, "lat": START[0], "lng": START[1]}, "routes": routes}, f, indent=1)
    print(f"Stop order for {len(routes)} route(s) written to '{args.output}'.")
    for route, stops in sorted(routes.items()):
        km = sum(s.get("km_from_previous", 0) for s in stops)
        print(f"  {route}: {len(stops)} stop(s), {km:.1f} km driving from the start")


if __name__ == "__main__":
    main()
