#!/usr/bin/env bash
# convert-all.sh — convert everything in sources/ to all presets, placed under samples/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$SCRIPT_DIR/conv2sgx.py"
SOURCES="$SCRIPT_DIR/sources"
SAMPLES="$SCRIPT_DIR/output"

mkdir -p "$SAMPLES/cpc" "$SAMPLES/msx" "$SAMPLES/msx2"

declare -A DITHERS=([F]=floyd-steinberg [A]=atkinson [N]=none [O]=ordered)

# preset → (flag  subdir  prefix  res-tag)
PRESETS=(
    "--cpc-m0    cpc   C0  L"
    "--cpc-m1    cpc   C1  L"
    "--cpc-m2    cpc   C2  H"
    "--msx       msx   M1  L"
    "--msx2-l-16 msx2  M5  L"
    "--msx2-l-4  msx2  M6  L"
    "--msx2-h-16 msx2  M7  H"
    "--msx2-h-4  msx2  M8  H"
)

shopt -s nullglob
sources=("$SOURCES"/*.png "$SOURCES"/*.jpg "$SOURCES"/*.jpeg)

if [ ${#sources[@]} -eq 0 ]; then
    echo "No source images found in $SOURCES" >&2
    exit 1
fi

echo "Found ${#sources[@]} source image(s). Converting..."

for src in "${sources[@]}"; do
    echo ""
    echo "=== $(basename "$src") ==="
    stem=$(basename "${src%.*}")
    name3="${stem:0:3}"

    for entry in "${PRESETS[@]}"; do
        read -r flag subdir prefix res_tag <<< "$entry"
        for d in F A N O; do
            dither="${DITHERS[$d]}"
            outname="${prefix}${name3}${d}${res_tag}.SGX"
            python3 "$TOOL" "$src" $flag -d "$dither" --preview \
                -o "$SAMPLES/$subdir/$outname"
        done
    done
done

echo ""
echo "Done. Output written to: $SAMPLES"
echo "  cpc/:  $(ls "$SAMPLES/cpc/"*.SGX 2>/dev/null | wc -l) SGX files"
echo "  msx/:  $(ls "$SAMPLES/msx/"*.SGX 2>/dev/null | wc -l) SGX files"
echo "  msx2/: $(ls "$SAMPLES/msx2/"*.SGX 2>/dev/null | wc -l) SGX files"
