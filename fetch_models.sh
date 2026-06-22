#!/usr/bin/env bash
# Fetch large model files that are NOT committed to the repo (the model binaries
# under models/ are gitignored; their LICENSE/NOTICE are tracked).
#
# Currently:
#   - u2net.onnx — the rembg background-removal model used for outfit previews
#     and map/world images (NOT face-swapping; that was removed).
#   - the built-in embedding model (fastembed) used for pose matching.
#
# Idempotent: skips a model if it already exists with the expected checksum
# (fastembed skips re-download when its cache is already populated).
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

# --- fastembed embedding model (built-in pose-matching embeddings) -------------
# MIT-licensed (BAAI/bge-small-en-v1.5). Downloaded via fastembed into its own
# HF cache layout under models/fastembed/ (gitignored). Must match the default
# in app/core/config_schema.py (embedding.internal_model). Other internal models
# auto-download on demand when selected in the admin UI.
FASTEMBED_MODEL="BAAI/bge-small-en-v1.5"
FASTEMBED_DIR="$MODELS_DIR/fastembed"

fetch_fastembed() {
    local py=""
    if [ -x ".venv/bin/python" ]; then py=".venv/bin/python";
    elif command -v python3 >/dev/null 2>&1; then py="python3";
    elif command -v python >/dev/null 2>&1; then py="python";
    else echo "[skip] fastembed model — no python interpreter found"; return 0; fi

    if ! "$py" -c "import fastembed" >/dev/null 2>&1; then
        echo "[skip] fastembed model — fastembed not installed yet"
        echo "       (run 'pip install -e .' first; the model otherwise"
        echo "        auto-downloads on first use)"
        return 0
    fi

    echo "[get]  fastembed model $FASTEMBED_MODEL -> $FASTEMBED_DIR"
    if "$py" - "$FASTEMBED_MODEL" "$FASTEMBED_DIR" <<'PY'
import sys
from fastembed import TextEmbedding
TextEmbedding(model_name=sys.argv[1], cache_dir=sys.argv[2])
PY
    then
        echo "[done] $FASTEMBED_DIR ($FASTEMBED_MODEL)"
    else
        echo "[warn] fastembed model download failed — it will auto-download on first use"
    fi
}

fetch_fastembed
echo "All models present."
