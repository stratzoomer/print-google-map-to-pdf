#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run generate_maps_pdf.py and/or generate_order_forms.py.
# Creates/uses .venv and installs dependencies automatically.
#
# Usage: $0 [--maps|--orders|--all] <input-file> [output-dir] [driver-path]
#
# Options:
#   --maps   Run generate_maps_pdf.py only (map PDFs per delivery route)
#   --orders Run generate_order_forms.py only (order form PDFs per route)
#   --all    Run both scripts (default)
#   --skip-checks  Generate even if the workbook checks fail (not recommended)
#   --no-route-order  Don't order the stops (and don't ask for an API key)
#
# Before generating, src/check_workbook.py checks the workbook (bag totals,
# order count vs BasicOrderStats, map links vs Street Address) and stops the
# run if anything is off.
#
# Then, with a Google Maps API key, src/route_order.py puts each route's stops
# in the order for a single pass by the delivery truck (shortest driving
# distance from the Sideburn Run parking lot), saved as
# <output-dir>/stop_order.json; maps and order forms are printed in that order
# and numbered "Stop n of N".  The key is read from GOOGLE_MAPS_API_KEY, or
# asked for (hidden) when run in a terminal; it is never saved.  Without a
# key, each route's pages stay in spreadsheet order (the same order for maps
# and order forms) with no stop numbers.
#
# Afterwards it checks the PDFs have one page per order, in the right order.
#
# Examples:
#   ./run_generate_maps_pdf.sh "input/Mulch Sales - Fall 2026.xlsx"
#   ./run_generate_maps_pdf.sh --maps "input/Mulch Sales - Fall 2026.xlsx" output/maps
#   ./run_generate_maps_pdf.sh --orders "input/Mulch Sales - Fall 2026.xlsx" output/forms

RUN_MAPS=false
RUN_ORDERS=false
SKIP_CHECKS=false
ROUTE_ORDER=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --maps)
      RUN_MAPS=true
      shift
      ;;
    --orders)
      RUN_ORDERS=true
      shift
      ;;
    --all)
      RUN_MAPS=true
      RUN_ORDERS=true
      shift
      ;;
    --skip-checks)
      SKIP_CHECKS=true
      shift
      ;;
    --no-route-order)
      ROUTE_ORDER=false
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--maps|--orders|--all] <input-file> [output-dir] [driver-path]"
      echo ""
      echo "Options:"
      echo "  --maps   Run generate_maps_pdf.py only (map PDFs per delivery route)"
      echo "  --orders Run generate_order_forms.py only (order form PDFs per route)"
      echo "  --all    Run both scripts (default)"
      echo "  --skip-checks  Generate even if the workbook checks fail (not recommended)"
      echo "  --no-route-order  Don't order the stops (and don't ask for an API key)"
      echo ""
      echo "Stops are ordered by driving distance when a Google Maps API key is given"
      echo "in GOOGLE_MAPS_API_KEY or typed at the prompt (it is never saved)."
      echo ""
      echo "Examples:"
      echo "  $0 'input/Mulch Sales - Fall 2026.xlsx'            # run both (maps + orders)"
      echo "  $0 --maps 'input/Mulch Sales - Fall 2026.xlsx'     # maps only"
      echo "  $0 --orders 'input/Mulch Sales - Fall 2026.xlsx'   # order forms only"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--maps|--orders|--all] <input-file> [output-dir] [driver-path]"
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

# Default to both if no mode specified
if ! $RUN_MAPS && ! $RUN_ORDERS; then
  RUN_MAPS=true
  RUN_ORDERS=true
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 [--maps|--orders|--all] <input-file> [output-dir] [driver-path]"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create and activate venv; install dependencies
if [[ ! -d .venv ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

if [[ ! -f requirements.txt ]]; then
  echo "Error: requirements.txt not found." >&2
  exit 4
fi
echo "Ensuring dependencies are installed..."
pip install -q -r requirements.txt

INPUT="$1"
OUTPUT_BASE="${2:-output}"
DRIVER_PATH="${3:-}"

if [[ ! -f "$INPUT" ]]; then
  echo "Error: input file '$INPUT' does not exist." >&2
  exit 3
fi

# When running both, use subdirs to avoid overwriting (both produce route-named PDFs)
if $RUN_MAPS && $RUN_ORDERS; then
  MAPS_OUTPUT="${OUTPUT_BASE}/maps"
  ORDERS_OUTPUT="${OUTPUT_BASE}/orders"
else
  MAPS_OUTPUT="$OUTPUT_BASE"
  ORDERS_OUTPUT="$OUTPUT_BASE"
fi

echo ""
echo "Checking the workbook before generating"
if ! python3 src/check_workbook.py --input "$INPUT"; then
  if $SKIP_CHECKS; then
    echo "Continuing anyway (--skip-checks)."
  else
    echo "Stopping: fix the workbook, or rerun with --skip-checks." >&2
    exit 5
  fi
fi

# Order each route's stops for a single pass by the delivery truck, if there
# is an API key.  The key is only passed to route_order.py, never saved.
mkdir -p "$OUTPUT_BASE"
STOP_ORDER="${OUTPUT_BASE}/stop_order.json"
rm -f "$STOP_ORDER"
API_KEY="${GOOGLE_MAPS_API_KEY:-}"
unset GOOGLE_MAPS_API_KEY
if $ROUTE_ORDER && [[ -z "$API_KEY" ]] && [[ -t 0 ]]; then
  echo ""
  read -r -s -p "Google Maps API key to order the stops (press Enter to skip): " API_KEY
  echo ""
fi
MAPS_ARGS=(--input "$INPUT" --output "$MAPS_OUTPUT" --use-original)
ORDERS_ARGS=(--input "$INPUT" --output "$ORDERS_OUTPUT")
CHECK_ARGS=(--input "$INPUT")
echo ""
if $ROUTE_ORDER && [[ -n "$API_KEY" ]]; then
  echo "Ordering the stops of each delivery route by driving distance"
  ROUTE_ARGS=(--input "$INPUT" --output "$STOP_ORDER" --cache "${OUTPUT_BASE}/driving_distances.json")
  if [[ -n "$DRIVER_PATH" ]]; then ROUTE_ARGS+=(--driver-path "$DRIVER_PATH"); fi
  if ! GOOGLE_MAPS_API_KEY="$API_KEY" python3 src/route_order.py "${ROUTE_ARGS[@]}"; then
    echo "Stopping: the stops could not be ordered. Check the API key, or rerun with --no-route-order." >&2
    exit 6
  fi
  MAPS_ARGS+=(--stop-order "$STOP_ORDER")
  ORDERS_ARGS+=(--stop-order "$STOP_ORDER")
  CHECK_ARGS+=(--stop-order "$STOP_ORDER")
else
  echo "Not ordering the stops (no API key): each route's pages stay in spreadsheet order."
fi
API_KEY=""
if [[ -n "$DRIVER_PATH" ]]; then MAPS_ARGS+=(--driver-path "$DRIVER_PATH"); fi

# Remove PDFs from an earlier run so the output only has this run's PDFs.
if $RUN_MAPS; then rm -f "$MAPS_OUTPUT"/*.pdf; fi
if $RUN_ORDERS; then rm -f "$ORDERS_OUTPUT"/*.pdf; fi

if $RUN_MAPS; then
  mkdir -p "$(dirname "$MAPS_OUTPUT")"
  echo ""
  echo "Running generate_maps_pdf.py"
  echo "  input:  $INPUT"
  echo "  output: $MAPS_OUTPUT"
  [[ -n "$DRIVER_PATH" ]] && echo "  driver: $DRIVER_PATH" || echo "  driver: (auto - Selenium Manager)"
  python3 src/generate_maps_pdf.py "${MAPS_ARGS[@]}"
fi

if $RUN_ORDERS; then
  mkdir -p "$ORDERS_OUTPUT"
  echo ""
  echo "Running generate_order_forms.py"
  echo "  input:  $INPUT"
  echo "  output: $ORDERS_OUTPUT"
  python3 src/generate_order_forms.py "${ORDERS_ARGS[@]}"
fi

echo ""
echo "Checking the generated PDFs"
if $RUN_MAPS; then CHECK_ARGS+=(--maps-dir "$MAPS_OUTPUT"); fi
if $RUN_ORDERS; then CHECK_ARGS+=(--orders-dir "$ORDERS_OUTPUT"); fi
python3 src/check_workbook.py "${CHECK_ARGS[@]}"

echo ""
echo "Done."
