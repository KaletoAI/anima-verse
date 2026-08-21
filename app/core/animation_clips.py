"""Shared animation clips — layout and discovery (core, route-free).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). The
layout is ``[<set>/]<kind>[_<n>].<ext>``:

* the KIND is the semantic category an activity maps to (walk, sit, …) and
  is the WHOLE file name without its extension — only a trailing ``_<number>``
  is cut off, because that is the numbering of several clips of one kind;
* the SET is the figure the clip was authored for (female, male, animal,
  lady, …) and comes from the DIRECTORY: one level of subdirectories below
  the clips root, one directory per set. Clips lying in the root itself are
  the neutral ones (set "").

A PAIR clip — two files recorded together, one per partner — carries the
ROLE as a ``__a`` / ``__b`` suffix of the stem: ``handshake__a.fbx`` and
``handshake__b.fbx`` are the two halves of the kind ``handshake``. The double
underscore is the role separator and nothing else (a single ``_`` stays part
of the kind). A pair kind has no solo file; it is played by two figures at a
shared anchor, in lockstep. Next to the files a ``<kind>.json`` SIDECAR
(written by ``scripts/clip_import_cmu.py``) holds duration, frame rate and
the anchor geometry; ``clip_meta()`` reads it.

Both vocabularies are OPEN — a new kind is just a new file, a new set just a
new directory, nothing is hardcoded. Which set a character uses (and the
fallback chain when its set lacks a kind) is ``app/core/animation_sets.py``.

TWO libraries, same layout (``app.core.paths``): ``shared/models/clips`` is
the FREE one — redistributable clips (CMU-derived), tracked in git — and
``shared/models/clips-licensed`` the LICENSED one — Mixamo downloads and
bought packs, usable in the game but not redistributable, gitignored, per
installation. Every entry carries ``source`` (``free``/``licensed``) and the
same ``[<set>/]<file>`` in both libraries resolves to the LICENSED file: whoever
installs a premium pack wants it played. A licensed clip's ``url`` carries a
``licensed/`` prefix, which is how the route tells the two apart.

This module is the ONE place that scans the clip directories; the assets
route, the animation sets and the pose presets all read from here.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.paths import get_animation_clips_dir, get_animation_clips_dirs

CLIP_EXTS = (".fbx", ".glb", ".gltf")
PAIR_ROLES = ("a", "b")
ROLE_SEPARATOR = "__"


def parse_clip_name(filename: str) -> str:
    """The clip KIND from a file name — the whole stem, lowercased, minus a
    trailing ``_<number>``.

    ONLY that numbering suffix is decoration; hyphens and inner underscores
    belong to the kind. Splitting at them was the bug of 2026-08-13: it filed
    ``swim-idle.fbx`` under "swim" (two clips of one kind, the wrong one played
    while moving) and ``treading-water.fbx`` under "treading", so the kind an
    author writes into ``idle_anim`` existed nowhere. The set is NOT read from
    the name (it is the directory).

        walk.fbx             -> "walk"
        walk_02.fbx          -> "walk"
        swim-idle.fbx        -> "swim-idle"
        treading-water.fbx   -> "treading-water"
        spell_casting.fbx    -> "spell_casting"
        Sit_A.fbx            -> "sit_a"
    """
    return parse_clip_role(filename)[0]


def parse_clip_role(filename: str) -> Tuple[str, str]:
    """``(kind, role)`` from a file name — role ``"a"``/``"b"`` for the half of
    a pair clip (``kiss__b.fbx`` → ``("kiss", "b")``), ``""`` for a solo clip.
    The numbering suffix is cut BEFORE the role is read, so ``hug__a_02.fbx``
    is a second take of the A half."""
    stem = Path(filename).stem.strip().lower()
    stem = re.sub(r"_\d+$", "", stem) or stem
    head, sep, tail = stem.rpartition(ROLE_SEPARATOR)
    if sep and head and tail in PAIR_ROLES:
        return head, tail
    return stem, ""


def clip_entries() -> List[Dict[str, Any]]:
    """Every clip of both libraries as ``{kind, role, set, source, rel, path}``.

    Per library: the root (set "") plus exactly ONE level of subdirectories
    (the directory name, lowercased, is the set). Hidden files and
    directories (``.`` prefix) are skipped, as is anything without a clip
    extension. ``rel`` is ``[<set>/]<file>``; the same ``rel`` in both
    libraries yields ONE entry, the licensed one.
    """
    def _files_of(directory: Path, cset: str, source: str) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(directory.iterdir()):
            if p.name.startswith(".") or not p.is_file():
                continue
            if p.suffix.lower() not in CLIP_EXTS:
                continue
            kind, role = parse_clip_role(p.name)
            rel = f"{cset}/{p.name}" if cset else p.name
            out.append({"kind": kind, "role": role, "set": cset,
                        "source": source, "rel": rel, "path": p})
        return out

    by_rel: Dict[str, Dict[str, Any]] = {}
    for root, source in get_animation_clips_dirs():
        if not root.exists():
            continue
        found = _files_of(root, "", source)
        for d in sorted(root.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            found.extend(_files_of(d, d.name.strip().lower(), source))
        for e in found:
            # free is scanned first; a licensed twin replaces it
            by_rel[e["rel"]] = e
    return sorted(by_rel.values(), key=lambda e: (e["set"], e["rel"]))


def clip_files() -> List[Path]:
    """Every clip file in the shared directory (all sets), sorted."""
    return [e["path"] for e in clip_entries()]


def clip_kinds() -> List[str]:
    """The animation kinds that actually exist right now."""
    return sorted({e["kind"] for e in clip_entries()} - {""})


def pair_kinds() -> List[str]:
    """Kinds that exist as a COMPLETE pair (both halves present in one set)."""
    halves: Dict[Tuple[str, str], set] = {}
    for e in clip_entries():
        if e["role"]:
            halves.setdefault((e["set"], e["kind"]), set()).add(e["role"])
    return sorted({k for (_s, k), roles in halves.items() if roles >= set(PAIR_ROLES)})


def clip_meta(kind: str, cset: str = "") -> Optional[Dict[str, Any]]:
    """The ``<kind>.json`` sidecar of a clip (duration, fps, pair geometry),
    None when there is none. Looked up in the set directory, then the root."""
    candidates = []
    # licensed first — the sidecar belongs to the file that wins
    for root, _source in reversed(get_animation_clips_dirs()):
        if cset:
            candidates.append(root / cset / f"{kind}.json")
        candidates.append(root / f"{kind}.json")
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            return data if isinstance(data, dict) else None
    return None


def clip_sets() -> List[str]:
    """The sets that actually have clips — i.e. the non-empty subdirectories."""
    return sorted({e["set"] for e in clip_entries()} - {""})
