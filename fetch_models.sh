#!/usr/bin/env bash
# Fetch large model files that are NOT committed to the repo (the model binaries
# under models/ are gitignored; their LICENSE/NOTICE are tracked).
#
# Currently: u2net.onnx — the rembg background-removal model used for outfit
# previews and map/world images (NOT face-swapping; that was removed).
#
# Idempotent: skips a model if it already exists with the expected checksum.
#
#   ./fetch_models.sh
set -euo pipefail
cd "$(dirname "$0")"

MODELS_DIR="models"

# --- u2net (rembg background removal) -----------------------------------------
# Apache-2.0. Upstream: https://github.com/xuebinqin/U-2-Net
# Distributed as ONNX by rembg: https://github.com/danielgatis/rembg
U2NET_DIR="$MODELS_DIR/u2net"
U2NET_FILE="$U2NET_DIR/u2net.onnx"
U2NET_URL="https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
# sha256 of the copy verified working in this project.
U2NET_SHA256="8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491"

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
    else shasum -a 256 "$1" | awk '{print $1}'; fi
}

fetch() {
    local url="$1" dest="$2" want="$3"
    if [ -f "$dest" ]; then
        local have; have="$(sha256_of "$dest")"
        if [ "$have" = "$want" ]; then
            echo "[ok]   $dest (checksum matches)"
            return 0
        fi
        echo "[warn] $dest exists but checksum differs (have $have) — re-downloading"
    fi
    mkdir -p "$(dirname "$dest")"
    echo "[get]  $url"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 -o "$dest.part" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$dest.part" "$url"
    else
        echo "ERROR: need curl or wget" >&2; exit 1
    fi
    local got; got="$(sha256_of "$dest.part")"
    if [ -n "$want" ] && [ "$got" != "$want" ]; then
        echo "ERROR: checksum mismatch for $dest" >&2
        echo "  expected $want" >&2
        echo "  got      $got" >&2
        echo "  (upstream may have updated the model; verify and update U2NET_SHA256)" >&2
        rm -f "$dest.part"; exit 1
    fi
    mv "$dest.part" "$dest"
    echo "[done] $dest"
}

fetch "$U2NET_URL" "$U2NET_FILE" "$U2NET_SHA256"
echo "All models present."
