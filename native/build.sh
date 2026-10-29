#!/usr/bin/env bash
# Build the native client spike and export the "Linux" preset.
#
#   native/build.sh [out_dir]        (default: native/export/)
#
# Steps: the gdCEF link (link_cef.sh, once — only when native/cef_artifacts/ is
# missing and the artifacts exist), dotnet build (the Godot project plus its
# ProjectReference native/Core = AnimaNative.Core.dll; the csproj target also
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
# Exported by Godot's dotnet publish as well as the build below. The assembly
# metadata and the launcher sidecar must describe the same source snapshot.
ANIMA_BUILD_VERSION="$(bash "$here/version.sh")"
export ANIMA_BUILD_VERSION
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
# The Godot-free core is its own assembly; the export's dotnet publish must have
# carried it along, or the client dies at the first core type it touches.
[ -f "$out/data_AnimaNative_linuxbsd_x86_64/AnimaNative.Core.dll" ] \
  || { echo "export lacks data_AnimaNative_linuxbsd_x86_64/AnimaNative.Core.dll" >&2; exit 1; }

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
  [ -f "$out/gdCefRenderProcess" ] && [ -f "$out/libcef.so" ] && [ -f "$out/libgdcef.so" ] \
    || { echo "gdCEF artifacts incomplete in $out" >&2; exit 1; }
  # CEF issue #3912: Chromium changes the stack canary in forked helpers, and gdCEF 0.20.0's helper main() still
  # checks the old one on return, so every helper (e.g. a component-update utility) aborts with
  # __stack_chk_fail after finishing its work — a crash report at each start, nothing lost. gdCEF exposes no
  # Chromium switches, so the real helper becomes gdCefRenderProcess.bin behind a wrapper that appends
  # --change-stack-guard-on-fork=disable (the last value of a Chromium switch wins). Upstream report:
  # https://github.com/Lecrapouille/gdcef/issues/107 — drop the wrapper once a gdCEF
  # release marks the helper's main() NO_STACK_PROTECTOR.
  rm -f "$out/gdCefRenderProcess.bin"
  # It may be hard-linked to the host's artifacts: detach (copy) before chmod, never chmod the host file.
  cp "$out/gdCefRenderProcess" "$out/gdCefRenderProcess.bin"
  chmod +x "$out/gdCefRenderProcess.bin"
  rm -f "$out/gdCefRenderProcess"
  cat > "$out/gdCefRenderProcess" <<'HELPER'
#!/bin/sh
# gdCEF helper wrapper (CEF issue #3912): see native/build.sh.
exec "$(dirname "$0")/gdCefRenderProcess.bin" "$@" --change-stack-guard-on-fork=disable
HELPER
  chmod +x "$out/gdCefRenderProcess"
fi

chmod +x "$out/anima-native.x86_64"
[ -x "$out/anima-native.x86_64" ] || { echo "export did not produce $out/anima-native.x86_64" >&2; exit 1; }
printf '%s\n' "$ANIMA_BUILD_VERSION" > "$out/version.txt"

# run.sh: a network share may drop the executable bits (the binary AND gdCEF's
# subprocess — without the latter the HUD silently never starts), and the
# engine log should land next to the build where the build host can read it.
cat > "$out/run.sh" <<'RUN'
#!/bin/sh
# Usage: sh run.sh [--server=http://HOST:8000] [--user=NAME] [--goto=LOCATION] [--bench [--quit-after-bench]] ...
# Every flag is optional: without --server/--user the login screen offers the
# server and user name of the last successful login (user://launcher.json).
here="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -eq 1 ] && [ "$1" = --version ]; then cat "$here/version.txt"; exit 0; fi
chmod +x "$here/anima-native.x86_64" "$here/gdCefRenderProcess" "$here/gdCefRenderProcess.bin" 2>/dev/null
mkdir -p "$here/logs"
exec "$here/anima-native.x86_64" --log-file "$here/logs/native-$(date +%Y%m%d-%H%M%S).log" -- "$@"
RUN
chmod +x "$out/run.sh"
echo "== done: $out/anima-native.x86_64 -- [--server=http://HOST:8000] [--user=NAME] [--goto=LOCATION] [--no-hud] [--bench [--scatter] [--quit-after-bench] [--size=WxH]]"
