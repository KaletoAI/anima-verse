"""Shared animation clips — naming and discovery (core, route-free).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). A clip
file is ``<kind>[_<set>][_<n>].<ext>``: the KIND is the semantic category an
activity maps to (walk, sit, …), the SET is the figure it was made for (lady,
man, dog, …). Both vocabularies are OPEN — a new kind or set is just a new
file, nothing is hardcoded.

This module is the ONE place that scans and parses the clips directory; the
assets route, the animation sets and the pose presets all read from here.
"""
import re
from pathlib import Path
from typing import List, Tuple

from app.core.paths import get_animation_clips_dir

CLIP_EXTS = (".fbx", ".glb", ".gltf")


def parse_clip_name(filename: str) -> Tuple[str, str]:
    """(kind, set) from the file name: ``<kind>[_<set>][_<n>].fbx``, lowercased.

    Numeric tokens are just variants of the same clip and carry no meaning.

        walk.fbx          -> ("walk", "")
        walk_lady.fbx     -> ("walk", "lady")
        Sit_Lady_02.fbx   -> ("sit", "lady")
        walk_02.fbx       -> ("walk", "")
    """
    stem = Path(filename).stem.strip().lower()
    tokens = [t for t in re.split(r"[\s_\-.]+", stem) if t]
    if not tokens:
        return (stem, "")
    kind = tokens[0]
    rest = [t for t in tokens[1:] if not t.isdigit()]
    return (kind, rest[0] if rest else "")


def clip_files() -> List[Path]:
    """Every clip file in the shared directory, sorted."""
    d = get_animation_clips_dir()
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in CLIP_EXTS)


def clip_kinds() -> List[str]:
    """The animation kinds that actually exist right now."""
    return sorted({parse_clip_name(p.name)[0] for p in clip_files()} - {""})


def clip_sets() -> List[str]:
    """The sets that actually have clips."""
    return sorted({parse_clip_name(p.name)[1] for p in clip_files()} - {""})
