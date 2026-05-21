#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT_DIR="$SCRIPT_DIR/inputs"
OUTPUT_DIR="$SCRIPT_DIR/output"
BACKEND="vlm-auto-engine"
mkdir -p "$OUTPUT_DIR"

total_start=$(date +%s)
total_files=0
total_failed=0

echo "========================================"
echo "MinerU vlm-transformers batch run"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Input:   $INPUT_DIR"
echo "Output:  $OUTPUT_DIR"
echo "========================================"

for pdf in "$INPUT_DIR"/*.pdf; do
    [ -f "$pdf" ] || continue
    name=$(basename "$pdf")
    total_files=$((total_files + 1))

    echo ""
    echo "----------------------------------------"
    echo "[$total_files] $name"
    echo "  Start:  $(date '+%H:%M:%S')"
    file_start=$(date +%s)

    if mineru -p "$pdf" -o "$OUTPUT_DIR" --backend "$BACKEND" 2>&1; then
        file_end=$(date +%s)
        elapsed=$((file_end - file_start))
        echo "  End:    $(date '+%H:%M:%S')"
        printf "  Time:   %dm %ds\n" $((elapsed / 60)) $((elapsed % 60))
        echo "  Status: OK"
    else
        file_end=$(date +%s)
        elapsed=$((file_end - file_start))
        total_failed=$((total_failed + 1))
        echo "  End:    $(date '+%H:%M:%S')"
        printf "  Time:   %dm %ds\n" $((elapsed / 60)) $((elapsed % 60))
        echo "  Status: FAILED"
    fi
done

total_end=$(date +%s)
total_elapsed=$((total_end - total_start))
total_ok=$((total_files - total_failed))

echo ""
echo "========================================"
echo "SUMMARY"
echo "  Finished:   $(date '+%Y-%m-%d %H:%M:%S')"
printf "  Total time: %dm %ds\n" $((total_elapsed / 60)) $((total_elapsed % 60))
echo "  Files:      $total_files"
echo "  OK:         $total_ok"
echo "  Failed:     $total_failed"
echo "  Output dir: $OUTPUT_DIR"
echo "========================================"
