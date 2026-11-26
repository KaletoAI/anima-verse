#!/usr/bin/env bash
# Copy a built AppImage into a delivery directory, point AnimaNative-latest.AppImage
# at it (RELATIVE link, so it resolves on a mounted share too) and delete every
# older AnimaNative-*.AppImage there — only the current build is kept.
#
# Usage: native/deliver.sh <path/to/AnimaNative-...AppImage> [dir]   (dir default: ~/claude-out)
set -euo pipefail
src="${1:?usage: native/deliver.sh <AppImage> [dir]}"
dir="${2:-$HOME/claude-out}"
[ -s "$src" ] || { echo "no AppImage: $src" >&2; exit 1; }
name="$(basename "$src")"
case "$name" in AnimaNative-*.AppImage) ;; *) echo "not an AnimaNative AppImage: $name" >&2; exit 1 ;; esac
mkdir -p "$dir"
cp "$src" "$dir/$name.part" && mv "$dir/$name.part" "$dir/$name"
chmod +x "$dir/$name"
cd "$dir"
ln -sfn "$name" AnimaNative-latest.AppImage
for f in AnimaNative-*.AppImage; do
  [ "$f" = "$name" ] || [ "$f" = AnimaNative-latest.AppImage ] || rm -f -- "$f"
done
ls -lL AnimaNative-*.AppImage
