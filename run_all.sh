#!/usr/bin/env bash
# Process every PDF in ../work/pdf/ using the shared glossary and rules.
# Output directories are named after each PDF stem under ./output/.

set -euo pipefail

WORK_DIR="$(cd "$(dirname "$0")/../work" && pwd)"
PDF_DIR="$WORK_DIR/pdf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "$PDF_DIR" ]]; then
    echo "PDF directory not found: $PDF_DIR" >&2
    exit 1
fi

shopt -s nullglob
pdfs=("$PDF_DIR"/*.pdf)
if [[ ${#pdfs[@]} -eq 0 ]]; then
    echo "No PDF files found in $PDF_DIR" >&2
    exit 1
fi

for pdf in "${pdfs[@]}"; do
    stem="$(basename "$pdf" .pdf)"
    output_dir="$SCRIPT_DIR/output/$stem"
    log_file="$SCRIPT_DIR/output/$stem.log"

    echo "=== Processing: $stem ==="
    echo "    output: $output_dir"
    echo "    log:    $log_file"

    mkdir -p "$(dirname "$log_file")"

    cd "$SCRIPT_DIR"
    uv run python -u main.py \
        --pdf "$pdf" \
        --output "$output_dir" \
        --config config.yaml \
        --resume \
        > "$log_file" 2>&1 &

    echo "    pid: $!"
done

echo ""
echo "All jobs launched. Monitor with:"
echo "    tail -f $SCRIPT_DIR/output/*.log"

wait
echo ""
echo "All jobs completed."
