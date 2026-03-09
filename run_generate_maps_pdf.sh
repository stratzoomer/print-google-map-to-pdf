#!/usr/bin/env bash
set -euo pipefail

# Simple wrapper to run generate_maps_pdf.py with sensible defaults.
# Usage: ./scripts/run_generate_maps_pdf.sh <input-csv> [output-pdf] [driver-path]
# Example:
#   ./scripts/run_generate_maps_pdf.sh input/map-print-test-Spring-2025-2-lines.csv

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <input-csv> [output-pdf] [driver-path] [wait] [limit] [paper-width] [paper-height]"
  exit 2
fi

INPUT="$1"
OUTPUT="${2:-output/output_maps.pdf}"
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
