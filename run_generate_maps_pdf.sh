#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run generate_maps_pdf.py with sensible defaults.
# Creates/uses .venv and installs dependencies automatically.
# Usage: ./run_generate_maps_pdf.sh <input-csv> [output-pdf] [driver-path]
# Example:
#   ./run_generate_maps_pdf.sh input/input-2-lines-with-delivery-route.csv

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <input-csv> [output-pdf] [driver-path] [wait] [limit] [paper-width] [paper-height]"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create and activate venv; install dependencies
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

if [ ! -f requirements.txt ]; then
  echo "Error: requirements.txt not found." >&2
  exit 4
fi
echo "Ensuring dependencies are installed..."
pip install -q -r requirements.txt

INPUT="$1"
OUTPUT="${2:-output}"
DRIVER_PATH="${3:-}"
WAIT="${4:-5}"
LIMIT="${5:-10}"
PAPER_WIDTH="${6:-11}"
PAPER_HEIGHT="${7:-8.5}"

if [ ! -f "$INPUT" ]; then
  echo "Error: input file '$INPUT' does not exist." >&2
  exit 3
fi

mkdir -p "$(dirname "$OUTPUT")"

echo "Running generate_maps_pdf.py"
echo "  input: $INPUT"
echo "  output: $OUTPUT"
[ -n "$DRIVER_PATH" ] && echo "  driver: $DRIVER_PATH" || echo "  driver: (auto - Selenium Manager)"
#echo "  wait: $WAIT  limit: $LIMIT  paper: ${PAPER_WIDTH}x${PAPER_HEIGHT}"

if [ -n "$DRIVER_PATH" ]; then
  python3 src/generate_maps_pdf.py \
    --input "$INPUT" \
    --output "$OUTPUT" \
    --driver-path "$DRIVER_PATH" \
    --use-original
else
  python3 src/generate_maps_pdf.py \
    --input "$INPUT" \
    --output "$OUTPUT" \
    --use-original
fi

echo "Done. Output written to $OUTPUT"
