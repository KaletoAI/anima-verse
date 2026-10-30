#!/usr/bin/env bash
# Export, assemble a complete AppDir, and pack it with the official appimagetool.
# Usage: native/package.sh [--publish] [out_dir] (default: native/export/appimage)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
publish=false
out=""
for arg in "$@"; do
  case "$arg" in
    --publish) publish=true ;;
    -h|--help) echo 'Usage: native/package.sh [--publish] [out_dir]'; exit 0 ;;
    --*) echo "Unknown option: $arg" >&2; exit 2 ;;
    *) [ -z "$out" ] || { echo 'Only one output directory is allowed' >&2; exit 2; }; out="$arg" ;;
  esac
done
version="$(bash "$here/version.sh")"
if "$publish" && [[ "$version" == *-dirty ]]; then
  echo 'Publish requires a clean worktree (including untracked source files)' >&2
  exit 1
fi
# appimagetool is host tooling, never a dependency stored in this repository.
tool="${APPIMAGETOOL:-/home/dev/tools/appimagetool/appimagetool-x86_64.AppImage}"
if [ -z "${APPIMAGETOOL:-}" ] && [ ! -x "$tool" ]; then
  mkdir -p "$(dirname "$tool")"
  download="$(mktemp "$(dirname "$tool")/.download-XXXXXX")"
  trap 'rm -f "$download"' EXIT
  echo '== downloading official AppImage/appimagetool release 1.9.1'
  curl --fail --location --retry 3 --connect-timeout 15 \
    https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    --output "$download"
  chmod +x "$download"
  mv "$download" "$tool"
  trap - EXIT
fi
command -v "$tool" >/dev/null 2>&1 || { echo "appimagetool not found: $tool" >&2; exit 1; }
out="${out:-$here/export/appimage}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
work="$(mktemp -d "$out/.package-XXXXXX")"
trap 'rm -rf "$work"' EXIT
appdir="$work/AnimaNative.AppDir"
mkdir -p "$appdir/usr/bin"
bash "$here/build.sh" "$appdir/usr/bin"
[ "$(cat "$appdir/usr/bin/version.txt")" = "$version" ] || { echo 'Source version changed during export' >&2; exit 1; }
for file in libgdcef.so libcef.so libanima_mallinfo.so gdCefRenderProcess libmeshoptimizer.so icudtl.dat; do
  [ -s "$appdir/usr/bin/$file" ] || { echo "AppImage requires gdCEF and meshoptimizer: missing $file" >&2; exit 1; }
done
[ -d "$appdir/usr/bin/locales" ] || { echo 'AppImage requires gdCEF locales/' >&2; exit 1; }
# Avoid chmod on build.sh's hard links: do not mutate the host's CEF artifacts.
for file in anima-native.x86_64 gdCefRenderProcess; do
  cp --remove-destination "$appdir/usr/bin/$file" "$work/$file"
  chmod +x "$work/$file"
  mv "$work/$file" "$appdir/usr/bin/$file"
done
# The exported offline check reads fixture files with System.IO. Repository
# references still resolve through the caller's PWD, as in the unpacked export.
cp -a "$here/fixtures" "$appdir/usr/bin/fixtures"
cp "$here/AppRun" "$appdir/AppRun"
chmod +x "$appdir/AppRun"
cat > "$appdir/anima-native.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Anima Native
Exec=AppRun
Icon=anima-native
Categories=Game;
Terminal=false
DESKTOP
cp "$here/icon.svg" "$appdir/anima-native.svg"
ln -s anima-native.svg "$appdir/.DirIcon"
file="AnimaNative-$version-x86_64.AppImage"
ARCH=x86_64 VERSION="$version" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream --comp zstd "$appdir" "$work/$file"
[ -s "$work/$file" ] || { echo 'appimagetool produced no AppImage' >&2; exit 1; }
chmod +x "$work/$file"
# Godot's first import creates missing script UID sidecars. They were not part
# of the source snapshot; still reject edits to tracked files or new sources.
if [[ "$version" != *-dirty ]]; then
  git -C "$root" diff --quiet HEAD -- . \
    || { echo 'Tracked sources changed during packaging' >&2; exit 1; }
  [ -z "$(git -C "$root" ls-files --others --exclude-standard -- . ':(exclude,glob)native/**/*.cs.uid')" ] \
    || { echo 'Untracked sources appeared during packaging' >&2; exit 1; }
fi
mv "$work/$file" "$out/$file"
if "$publish"; then
  python3 "$here/tools/publish_appimage.py" "$out/$file" "$version" "$root/static/native"
fi
printf '== AppImage: %s (%s bytes)\n' "$out/$file" "$(stat -c %s "$out/$file")"
