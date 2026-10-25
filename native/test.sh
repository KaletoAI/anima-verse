#!/usr/bin/env bash
# All checks of the native client, no server, no display:
#
#   native/test.sh
#
#   1. dotnet test native/tests          — the xUnit tests of the Godot-free core
#   2. dotnet build native/               — the Godot project (+ core), so Godot runs the current code
#   3. godot --headless -- --check        — the offline self-test from native/fixtures
#
# Exits non-zero as soon as any step fails. Build tooling only, not app config:
# the Godot binary comes from $GODOT if set, else `godot` on PATH; dotnet from PATH.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
godot="${GODOT:-godot}"
command -v "$godot" >/dev/null 2>&1 || { echo "Godot not found: set GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64" >&2; exit 1; }
command -v dotnet >/dev/null 2>&1 || { echo "dotnet (8.0 SDK) not found on PATH" >&2; exit 1; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1

echo "== dotnet test native/tests"
dotnet test "$here/tests" -nologo

echo "== dotnet build native/"
(cd "$here" && dotnet build -nologo -v quiet)

if [ ! -d "$here/.godot" ]; then
  echo "== first import"
  code=0
  "$godot" --headless --path "$here" --import || code=$?
  # Same tolerance as build.sh: with gdCEF linked, Godot 4.7.2's editor-mode
  # import may segfault (139) while exiting, after the import has finished.
  if [ "$code" -ne 0 ] && ! { [ "$code" -eq 139 ] && [ -f "$here/cef_artifacts/gdcef.gdextension" ]; }; then
    exit "$code"
  fi
fi

echo "== godot --headless -- --check"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
code=0
"$godot" --headless --path "$here" -- --check 2>&1 | tee "$log" || code=$?
[ "$code" -eq 0 ] || { echo "check: exit $code" >&2; exit "$code"; }
grep -q '^CHECK ok' "$log" || { echo "check: no 'CHECK ok' line" >&2; exit 1; }
echo "== all native checks passed"
