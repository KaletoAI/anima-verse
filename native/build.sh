#!/usr/bin/env bash
# Build the native client spike and export the "Linux" preset.
#
#   native/build.sh [out_dir]        (default: native/export/)
#
# Steps: dotnet build (its csproj target also compiles the vendored
# meshoptimizer into native/bin/libmeshoptimizer.so), a headless import, the
# Godot export, then libmeshoptimizer.so is copied next to the binary.
#
# Build tooling only, not app config: the Godot binary comes from $GODOT if
# set, else `godot` on PATH; dotnet from PATH (DOTNET_ROOT as usual).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-$here/export}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
godot="${GODOT:-godot}"
command -v "$godot" >/dev/null 2>&1 || { echo "Godot not found: set GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64" >&2; exit 1; }
command -v dotnet >/dev/null 2>&1 || { echo "dotnet (8.0 SDK) not found on PATH" >&2; exit 1; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1

echo "== dotnet build"
(cd "$here" && dotnet build -nologo -v quiet)

echo "== import"
"$godot" --headless --path "$here" --import

echo "== export Linux -> $out"
"$godot" --headless --path "$here" --export-release Linux "$out/anima-native.x86_64"
cp "$here/bin/libmeshoptimizer.so" "$out/"

[ -x "$out/anima-native.x86_64" ] || { echo "export did not produce $out/anima-native.x86_64" >&2; exit 1; }
echo "== done: $out/anima-native.x86_64 -- --server=http://HOST:8000 [--user=NAME] [--goto=LOCATION] [--bench [--scatter] [--quit-after-bench] [--size=WxH]]"
