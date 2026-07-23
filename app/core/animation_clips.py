"""Shared animation clips — layout and discovery (core, route-free).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). The
layout is ``[<set>/]<kind>[_<n>].<ext>``:

* the KIND is the semantic category an activity maps to (walk, sit, …) and
  comes from the FILE NAME — the first token of the stem;
* the SET is the figure the clip was authored for (female, male, animal,
  lady, …) and comes from the DIRECTORY: one level of subdirectories below
  the clips root, one directory per set. Clips lying in the root itself are
  the neutral ones (set "").

Both vocabularies are OPEN — a new kind is just a new file, a new set just a
new directory, nothing is hardcoded. Which set a character uses (and the
fallback chain when its set lacks a kind) is ``app/core/animation_sets.py``.

This module is the ONE place that scans the clips directory; the assets
route, the animation sets and the pose presets all read from here.
"""
import re
from pathlib import Path
from typing import Any, Dict, List

from app.core.paths import get_animation_clips_dir

CLIP_EXTS = (".fbx", ".glb", ".gltf")


def parse_clip_name(filename: str) -> str:
    """The clip KIND from a file name — the first token of the stem, lowercased.

    Everything after it is decoration: trailing numbers distinguish several
    clips of the same kind, any other token is ignored. The set is NOT read
    from the name (it is the directory).

        walk.fbx      -> "walk"
        walk_02.fbx   -> "walk"
        Sit_A.fbx     -> "sit"
    """
    stem = Path(filename).stem.strip().lower()
    tokens = [t for t in re.split(r"[\s_\-.]+", stem) if t]
    return tokens[0] if tokens else stem


def clip_entries() -> List[Dict[str, Any]]:
    """Every clip in the shared directory as ``{kind, set, path}``, sorted.

    Scans the root (set "") plus exactly ONE level of subdirectories (the
    directory name, lowercased, is the set). Hidden files and directories
    (``.`` prefix) are skipped, as is anything without a clip extension.
    """
    root = get_animation_clips_dir()
    if not root.exists():
        return []

    def _files_of(directory: Path, cset: str) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(directory.iterdir()):
            if p.name.startswith(".") or not p.is_file():
                continue
            if p.suffix.lower() not in CLIP_EXTS:
                continue
            out.append({"kind": parse_clip_name(p.name), "set": cset, "path": p})
        return out

    entries = _files_of(root, "")
    for d in sorted(root.iterdir()):
        if d.name.startswith(".") or not d.is_dir():
            continue
        entries.extend(_files_of(d, d.name.strip().lower()))
    return entries


def clip_files() -> List[Path]:
    """Every clip file in the shared directory (all sets), sorted."""
    return [e["path"] for e in clip_entries()]


def clip_kinds() -> List[str]:
    """The animation kinds that actually exist right now."""
    return sorted({e["kind"] for e in clip_entries()} - {""})


def clip_sets() -> List[str]:
    """The sets that actually have clips — i.e. the non-empty subdirectories."""
    return sorted({e["set"] for e in clip_entries()} - {""})
