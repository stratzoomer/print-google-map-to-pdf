#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run generate_maps_pdf.py and/or generate_order_forms.py.
# Creates/uses .venv and installs dependencies automatically.
#
# Usage: $0 [--maps|--orders|--all] <input-csv> [output-dir] [driver-path]
#
# Options:
#   --maps   Run generate_maps_pdf.py only (map PDFs per delivery route)
#   --orders Run generate_order_forms.py only (order form PDFs per route)
#   --all    Run both scripts (default)
#
# Examples:
#   ./run_generate_maps_pdf.sh input/data.csv
#   ./run_generate_maps_pdf.sh --maps input/data.csv output/maps
#   ./run_generate_maps_pdf.sh --orders input/data.csv output/forms

RUN_MAPS=false
RUN_ORDERS=false

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
    -h|--help)
      echo "Usage: $0 [--maps|--orders|--all] <input-csv> [output-dir] [driver-path]"
      echo ""
      echo "Options:"
      echo "  --maps   Run generate_maps_pdf.py only (map PDFs per delivery route)"
      echo "  --orders Run generate_order_forms.py only (order form PDFs per route)"
      echo "  --all    Run both scripts (default)"
      echo ""
      echo "Examples:"
      echo "  $0 input/data.csv              # run both (maps + orders)"
      echo "  $0 --maps input/data.csv       # maps only"
      echo "  $0 --orders input/data.csv     # order forms only"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--maps|--orders|--all] <input-csv> [output-dir] [driver-path]"
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
  echo "Usage: $0 [--maps|--orders|--all] <input-csv> [output-dir] [driver-path]"
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
echo "Done."
