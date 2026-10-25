#!/usr/bin/env bash
# Build the native client spike and export the "Linux" preset.
#
#   native/build.sh [out_dir]        (default: native/export/)
#
# Steps: the gdCEF link (link_cef.sh, once — only when native/cef_artifacts/ is
# missing and the artifacts exist), dotnet build (its csproj target also
# compiles the vendored meshoptimizer into native/bin/libmeshoptimizer.so), a
# headless import, the Godot export (which copies libgdcef.so + libcef.so next
# to the binary), then libmeshoptimizer.so and the remaining gdCEF artifacts
# (gdCefRenderProcess, *.pak, icudtl.dat, locales/, …) are put next to the
# binary — hard links where the file system allows, copies otherwise.
#
# Build tooling only, not app config: the Godot binary comes from $GODOT if
# set, else `godot` on PATH; dotnet from PATH (DOTNET_ROOT as usual); the gdCEF
# artifacts from $GDCEF_DIR if set (see link_cef.sh for the default).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-$here/export}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
godot="${GODOT:-godot}"
command -v "$godot" >/dev/null 2>&1 || { echo "Godot not found: set GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64" >&2; exit 1; }
command -v dotnet >/dev/null 2>&1 || { echo "dotnet (8.0 SDK) not found on PATH" >&2; exit 1; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1

cef="$here/cef_artifacts"
if [ ! -f "$cef/gdcef.gdextension" ]; then
  if [ -f "${GDCEF_DIR:-/home/dev/tools/gdcef/gdcef/cef_artifacts}/gdcef.gdextension" ]; then
    echo "== link gdCEF artifacts"
    "$here/link_cef.sh"
  else
    echo "== gdCEF artifacts not found (set GDCEF_DIR or run link_cef.sh): building WITHOUT the HUD"
  fi
fi

echo "== dotnet build"
(cd "$here" && dotnet build -nologo -v quiet)

echo "== import"
code=0
"$godot" --headless --path "$here" --import || code=$?
if [ "$code" -ne 0 ]; then
  # Godot 4.7.2 + gdcef 0.20.0: the editor-mode import segfaults (139) while the
  # process exits, AFTER the import is done — only with the extension linked. The
  # export below scans the project again and fails on its own if anything is missing.
  if [ "$code" -eq 139 ] && [ -f "$cef/gdcef.gdextension" ]; then
    echo "   (import: exit-time crash with gdCEF loaded ignored, see README)"
  else
    exit "$code"
  fi
fi

echo "== export Linux -> $out"
"$godot" --headless --path "$here" --export-release Linux "$out/anima-native.x86_64"
cp "$here/bin/libmeshoptimizer.so" "$out/"

if [ -f "$cef/gdcef.gdextension" ]; then
  # gdCEF looks for its subprocess and resources in the folder of libgdcef.so —
  # next to the binary in an export.
  echo "== gdCEF artifacts -> $out"
  for link in "$cef/linux/"*; do
    name="$(basename "$link")"
    real="$(readlink -f "$link")"
    rm -rf "${out:?}/$name"
    if [ -d "$real" ]; then
      cp -al "$real" "$out/$name" 2>/dev/null || cp -a "$real" "$out/$name"
    else
      ln -f "$real" "$out/$name" 2>/dev/null || cp -f "$real" "$out/$name"
    fi
  done
  [ -x "$out/gdCefRenderProcess" ] && [ -f "$out/libcef.so" ] && [ -f "$out/libgdcef.so" ] \
    || { echo "gdCEF artifacts incomplete in $out" >&2; exit 1; }
fi

[ -x "$out/anima-native.x86_64" ] || { echo "export did not produce $out/anima-native.x86_64" >&2; exit 1; }
echo "== done: $out/anima-native.x86_64 -- --server=http://HOST:8000 [--user=NAME] [--goto=LOCATION] [--no-hud] [--bench [--scatter] [--quit-after-bench] [--size=WxH]]"
