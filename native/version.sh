#!/usr/bin/env bash
# Version of the source worktree, independent of the caller's current directory.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stamp="$(git -C "$here" show -s --format=%ct HEAD)"
version="$(date -u -d "@$stamp" +%Y%m%d%H%M%S)-$(git -C "$here" rev-parse --short HEAD)"
if [ -n "$(git -C "$here" status --porcelain --untracked-files=normal)" ]; then
  version+="-dirty"
fi
printf '%s\n' "$version"
