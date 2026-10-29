#!/usr/bin/env bash
# One-time step: make the gdCEF artifacts (CEF 156 + the gdcef GDExtension,
# ~560 MB, NOT committed) visible to the Godot project as res://cef_artifacts/.
#
#   native/link_cef.sh [gdcef_artifacts_dir]
#
# Source: the argument, else $GDCEF_DIR, else /home/dev/tools/gdcef-0.21.0/gdcef/cef_artifacts
# — the cef_artifacts/ folder of a gdcef release (v0.21.0-godot4, the folder
# that holds gdcef.gdextension and linux/). Build tooling only, like $GODOT.
#
# Result (native/cef_artifacts/ is gitignored):
#   cef_artifacts/gdcef.gdextension   a COPY (Godot must scan it to load the extension)
#   cef_artifacts/linux/              a real directory of SYMLINKS to every artifact
#   cef_artifacts/linux/.gdignore     keeps Godot's importer out of the 230 files
#                                     (the extension loads its libraries by path, the
#                                     export copies them by path — neither needs the scan)
# Re-running replaces the links. Without this step the client runs without the HUD.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="${1:-${GDCEF_DIR:-/home/dev/tools/gdcef-0.21.0/gdcef/cef_artifacts}}"
[ -f "$src/gdcef.gdextension" ] && [ -f "$src/linux/libgdcef.so" ] && [ -x "$src/linux/gdCefRenderProcess" ] \
  || { echo "not a gdcef cef_artifacts folder: $src (needs gdcef.gdextension, linux/libgdcef.so, linux/gdCefRenderProcess)" >&2; exit 1; }
src="$(cd "$src" && pwd)"

dst="$here/cef_artifacts"
rm -rf "$dst"
mkdir -p "$dst/linux"
cp "$src/gdcef.gdextension" "$dst/gdcef.gdextension"
[ -f "$src/VERSION" ] && cp "$src/VERSION" "$dst/VERSION"
for f in "$src/linux/"*; do
  ln -s "$f" "$dst/linux/$(basename "$f")"
done
touch "$dst/linux/.gdignore"
echo "linked $(ls "$src/linux" | wc -l) gdcef artifacts from $src -> $dst"
