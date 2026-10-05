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
#
# Before generating, src/check_workbook.py checks the workbook (bag totals,
# order count vs BasicOrderStats, map links vs Street Address) and stops the
# run if anything is off.  Afterwards it checks the PDFs have one page per
# order.
#
# Examples:
#   ./run_generate_maps_pdf.sh "input/Mulch Sales - Fall 2026.xlsx"
#   ./run_generate_maps_pdf.sh --maps "input/Mulch Sales - Fall 2026.xlsx" output/maps
#   ./run_generate_maps_pdf.sh --orders "input/Mulch Sales - Fall 2026.xlsx" output/forms

RUN_MAPS=false
RUN_ORDERS=false
SKIP_CHECKS=false

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
    -h|--help)
      echo "Usage: $0 [--maps|--orders|--all] <input-file> [output-dir] [driver-path]"
      echo ""
      echo "Options:"
      echo "  --maps   Run generate_maps_pdf.py only (map PDFs per delivery route)"
      echo "  --orders Run generate_order_forms.py only (order form PDFs per route)"
      echo "  --all    Run both scripts (default)"
      echo "  --skip-checks  Generate even if the workbook checks fail (not recommended)"
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
  if [[ -n "$DRIVER_PATH" ]]; then
    python3 src/generate_maps_pdf.py \
      --input "$INPUT" \
      --output "$MAPS_OUTPUT" \
      --driver-path "$DRIVER_PATH" \
      --use-original
  else
    python3 src/generate_maps_pdf.py \
      --input "$INPUT" \
      --output "$MAPS_OUTPUT" \
      --use-original
  fi
fi

if $RUN_ORDERS; then
  mkdir -p "$ORDERS_OUTPUT"
  echo ""
  echo "Running generate_order_forms.py"
  echo "  input:  $INPUT"
  echo "  output: $ORDERS_OUTPUT"
  python3 src/generate_order_forms.py \
    --input "$INPUT" \
    --output "$ORDERS_OUTPUT"
fi

echo ""
echo "Checking the generated PDFs"
CHECK_ARGS=(--input "$INPUT")
if $RUN_MAPS; then CHECK_ARGS+=(--maps-dir "$MAPS_OUTPUT"); fi
if $RUN_ORDERS; then CHECK_ARGS+=(--orders-dir "$ORDERS_OUTPUT"); fi
python3 src/check_workbook.py "${CHECK_ARGS[@]}"

echo ""
echo "Done."
