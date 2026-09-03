"""The import inbox for FOREIGN animation files (core, route-free).

A user drops an FBX into ``shared/models/clips-inbox`` (``paths.get_clips_inbox_dir``)
or uploads it in the Poses tab; this module is everything that happens between
that file and a playable clip:

* :func:`inbox_entries` lists what is waiting, each with a :func:`probe_fbx`
  result — which skeleton family the file carries, whether it has fingers and
  whether it looks like a reference pose. The probe runs WITHOUT Blender: an
  FBX (binary or ASCII) keeps its node names as plain ASCII in the byte
  stream, so the printable runs are enough to recognise a rig. That keeps the
  listing instant and honest — an unknown rig is refused before a Blender run
  is ever started.
* :func:`pair_suggestion` and :func:`rest_suggestion` propose what the two
  extra slots of the converter want: the partner file of a pair recording and
  a reference-pose export of the same rig.
* :func:`import_fbx` hands the files to ``app/blender/scripts/fbx_clip.py``
  (through :mod:`app.blender.runner`) and writes ``<kind>.fbx`` — or
  ``<kind>__a`` + ``<kind>__b`` for a pair — plus the ``<kind>.json`` sidecar
  into one of the two clip libraries.

TARGET: the LICENSED library is the default and the safe answer — a foreign
file is licensed material until its owner says otherwise. The free (tracked,
redistributable) library is reachable only by passing ``redistributable=True``
explicitly, which is the caller stating that the licence allows it.

The signature table below MIRRORS ``fbx_clip.SIGNATURES`` / ``BONE_MAPS`` on
purpose: that module imports ``bpy`` and can only be read inside Blender, so a
server-side probe cannot import it. A new family there needs a line here too.
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.blender import runner
from app.core import cmu_import
from app.core.animation_clips import clip_entries
from app.core.clip_catalog import ClipKindExists, existing_kinds
from app.core.cmu_import import ClipImportError
from app.core.log import get_logger
from app.core.paths import (get_animation_clips_dir, get_clips_inbox_dir,
                            get_licensed_clips_dir)

logger = get_logger(__name__)

#: Only FBX for now — the ASF/AMC path is the CMU catalog, BVH is not written.
INBOX_EXTS = (".fbx",)

#: Printable ASCII runs of at least three characters — an FBX node name.
_TOKEN_RE = re.compile(rb"[\x20-\x7e]{3,}")

#: How much of a file is scanned for node names. The skeleton is written long
#: before the animation curves, so a cap keeps a 300 MB export cheap.
MAX_PROBE_BYTES = 32 * 1024 * 1024

#: A file whose name says "this is a pose, not a movement" — the reference
#: pose the converter can take the real bone twist from.
REST_MARKERS = ("tpose", "t-pose", "t_pose", "apose", "a-pose", "rest", "bind")


def _unity_humanoid_bones() -> Tuple[str, ...]:
    """The node names ``fbx_clip._unity_humanoid()`` maps — mirror of that
    table, without the ``bpy`` import that makes the original unreadable
    outside Blender."""
    names = [
        "Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
        "Left_Shoulder", "Left_UpperArm", "Left_LowerArm", "Left_Hand",
        "Right_Shoulder", "Right_UpperArm", "Right_LowerArm", "Right_Hand",
        "Left_UpperLeg", "Left_LowerLeg", "Left_Foot", "Left_Toes",
        "Right_UpperLeg", "Right_LowerLeg", "Right_Foot", "Right_Toes",
    ]
    for side in ("Left", "Right"):
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            for part in ("Proximal", "Intermediate", "Distal"):
                names.append(f"{side}_{finger}{part}")
    return tuple(names)


def _mixamo_noprefix_bones() -> Tuple[str, ...]:
    """The node names ``fbx_clip._mixamo_noprefix()`` maps — the Mixamo bone
    names without the ``mixamorig:`` prefix (MocapOnline / MotusMan). The
    rig's ``Root``, ``hand_*_wep`` sockets and ``Leaf*Roll1`` twist helpers are
    deliberately absent: the converter discards them."""
    names = [
        "Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
        "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
        "RightShoulder", "RightArm", "RightForeArm", "RightHand",
        "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
        "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase",
        "LeftToe_End", "RightToe_End",
    ]
    for side in ("Left", "Right"):
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            for n in (1, 2, 3, 4):
                names.append(f"{side}Hand{finger}{n}")
    return tuple(names)


#: family → the node names that must ALL be present (mirror of
#: ``fbx_clip.SIGNATURES``; "auto" picks the first family that matches).
SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "unity-humanoid": ("Hips", "Left_UpperLeg", "Left_UpperArm", "Chest"),
    "mixamo-noprefix": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine2"),
}

#: family → token fragments that DISQUALIFY it (mirror of
#: ``fbx_clip.EXCLUDE_PREFIXES``). The unprefixed Mixamo names are a substring
#: of the prefixed ones, so a plain Mixamo export must not be read as
#: "mixamo-noprefix".
EXCLUDE_FRAGMENTS: Dict[str, Tuple[str, ...]] = {
    "mixamo-noprefix": ("mixamorig:",),
}

#: family → every node name the bone map knows (mirror of ``fbx_clip.BONE_MAPS``),
#: used for the bone count and the finger check.
BONE_NAMES: Dict[str, Tuple[str, ...]] = {
    "unity-humanoid": _unity_humanoid_bones(),
    "mixamo-noprefix": _mixamo_noprefix_bones(),
}

#: family → node names that only exist when the rig has fingers.
FINGER_NAMES: Dict[str, Tuple[str, ...]] = {
    "unity-humanoid": ("Left_IndexProximal", "Right_IndexProximal"),
    "mixamo-noprefix": ("LeftHandIndex1", "RightHandIndex1"),
}

#: name → (mtime_ns, size, probe); a probe is pure file content, so the mtime
#: pair is a complete cache key.
_probe_cache: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}


def is_rest_name(name: str) -> bool:
    """Does the FILE NAME say "reference pose"? (tpose / t-pose / rest / bind)"""
    low = Path(name).stem.lower()
    return any(marker in low for marker in REST_MARKERS)


def probe_fbx(path: Path) -> Dict[str, Any]:
    """What rig does this file carry — ``{skeleton_family, bone_count,
    has_fingers, is_rest_candidate}`` plus ``error`` when the file cannot be
    read at all.

    ``skeleton_family`` is ``""`` when no signature matches: an unknown rig,
    which the importer refuses (the retargeter has no bone map for it).
    """
    path = Path(path)
    out: Dict[str, Any] = {"skeleton_family": "", "bone_count": 0,
                           "has_fingers": False,
                           "is_rest_candidate": is_rest_name(path.name)}
    try:
        with path.open("rb") as fh:
            data = fh.read(MAX_PROBE_BYTES)
    except OSError as e:
        out["error"] = str(e)
        return out
    tokens = {m.group().decode("ascii", "ignore") for m in _TOKEN_RE.finditer(data)}
    for family, signature in SIGNATURES.items():
        if not all(name in tokens for name in signature):
            continue
        if any(frag in tok for frag in EXCLUDE_FRAGMENTS.get(family, ()) for tok in tokens):
            continue
        out["skeleton_family"] = family
        out["bone_count"] = sum(1 for n in BONE_NAMES.get(family, ()) if n in tokens)
        out["has_fingers"] = any(n in tokens for n in FINGER_NAMES.get(family, ()))
        break
    return out


def _cached_probe(path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
    except OSError as e:
        return {"skeleton_family": "", "bone_count": 0, "has_fingers": False,
                "is_rest_candidate": is_rest_name(path.name), "error": str(e)}
    hit = _probe_cache.get(path.name)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    probe = probe_fbx(path)
    _probe_cache[path.name] = (st.st_mtime_ns, st.st_size, probe)
    return probe


def safe_inbox_name(raw: Any) -> str:
    """A plain file name inside the inbox — no directory, no traversal, only a
    clip extension. Raises ``ClipImportError`` on anything else.

    This is the ONE gate between a request and the file system here: the whole
    API talks in bare names, never in paths.
    """
    name = str(raw or "").strip()
    if not name:
        raise ClipImportError("file name must not be empty")
    if "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        raise ClipImportError(f"not a plain file name: {name!r}")
    if Path(name).name != name:
        raise ClipImportError(f"not a plain file name: {name!r}")
    if Path(name).suffix.lower() not in INBOX_EXTS:
        raise ClipImportError(f"only {', '.join(INBOX_EXTS)} files can be imported")
    return name


def inbox_path(name: str) -> Path:
    """The file behind a validated inbox name — existence is NOT checked."""
    return get_clips_inbox_dir() / safe_inbox_name(name)


def inbox_files() -> List[Path]:
    """Every importable file lying in the inbox, flat and sorted. A missing
    directory is the normal empty state."""
    root = get_clips_inbox_dir()
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir()
                   if p.is_file() and not p.name.startswith(".")
                   and p.suffix.lower() in INBOX_EXTS),
                  key=lambda p: p.name.lower())


def inbox_entries() -> List[Dict[str, Any]]:
    """The inbox as the admin sees it: ``{name, size, mtime, probe}`` per file."""
    out = []
    for p in inbox_files():
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size,
                    "mtime": st.st_mtime, "probe": _cached_probe(p)})
    return out


#: Name patterns of a recorded PAIR: one prefix pair and three suffix pairs.
#: Longest suffix first — ``__a`` must win over ``_a``.
PAIR_PREFIXES = (("female_", "male_"),)
PAIR_SUFFIXES = (("__a", "__b"), ("_a", "_b"), ("_l", "_r"))


def partner_names(name: str) -> List[str]:
    """Every file name that WOULD be the partner half of ``name`` — lowercase
    candidates, whether or not such a file exists."""
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    low = stem.lower()
    out: List[str] = []
    for a, b in PAIR_PREFIXES:
        for first, second in ((a, b), (b, a)):
            if low.startswith(first):
                out.append(second + low[len(first):] + ext)
    for a, b in PAIR_SUFFIXES:
        match = next(((f, s) for f, s in ((a, b), (b, a)) if low.endswith(f)), None)
        if match:
            first, second = match
            out.append(low[: -len(first)] + second + ext)
            break            # the LONGEST matching suffix decides ("__a", not "_a")
    return out


def pair_suggestion(name: str) -> str:
    """The partner file of ``name`` — but only when it really lies in the
    inbox. ``""`` when nothing matches; a suggestion that names a missing file
    would be a broken import waiting to happen."""
    have = {p.name.lower(): p.name for p in inbox_files()}
    for candidate in partner_names(name):
        hit = have.get(candidate)
        if hit and hit.lower() != name.lower():
            return hit
    return ""


def rest_suggestion() -> str:
    """The first file in the inbox that looks like a reference pose, ``""``
    when there is none."""
    for p in inbox_files():
        if is_rest_name(p.name):
            return p.name
    return ""


def delete_inbox(name: str) -> bool:
    """Removes one inbox file. False when it was not there — deleting twice is
    not an error, the file is gone either way."""
    path = inbox_path(name)
    _probe_cache.pop(path.name, None)
    if not path.is_file():
        return False
    path.unlink()
    return True


def preview_dir() -> Path:
    """Where a probe conversion lands (inside the inbox, hidden, overwritten
    by the next probe)."""
    return get_clips_inbox_dir() / ".preview"


def preview_clip_path(name: str) -> Optional[Path]:
    """A probe clip by file name — only the names the probe writes."""
    if name not in ("preview.fbx", "preview__a.fbx", "preview__b.fbx"):
        return None
    p = preview_dir() / name
    return p if p.is_file() else None


def target_dir(target: str) -> Path:
    """The clip library an import writes into."""
    return get_animation_clips_dir() if target == "free" else get_licensed_clips_dir()


def import_fbx(kind: str, files: List[str], *, rest_file: Optional[str] = None,
               clip_set: str = "", start_s: float = 0.0,
               end_s: Optional[float] = None, loop_s: Optional[float] = None,
               in_place: bool = False, overwrite: bool = False,
               offset_b_m: Optional[List[float]] = None,
               loops: Optional[bool] = None, speed: float = 1.0,
               target: str = "licensed", redistributable: bool = False,
               out_dir: Optional[Path] = None, rig: Optional[Path] = None,
               fps: int = 30, timeout_s: int = 900,
               preview: bool = False) -> Dict[str, Any]:
    """Retargets one inbox file (or a pair) onto the library rig and writes the
    clip into the chosen library.

    ``files`` is one name, or two — the A half first; ``rest_file`` is an
    optional reference-pose export of the SAME rig, which gives the bones their
    real twist instead of a positional reconstruction. ``in_place`` is
    meaningless for a pair (the two roots carry the contact geometry) and is
    ignored there, exactly as in the CMU import.

    Everything refusable raises ``ClipImportError``; "the kind is already
    there" raises ``ClipKindExists`` so a route can answer 409.

    ``preview`` runs the very same conversion into the inbox's ``.preview``
    folder (kind ``preview``), touches no library and no cache, and returns
    the URLs a viewer plays — so the offset, window and reference pose can be
    judged BEFORE anything is imported.
    """
    kind = cmu_import.validate_kind(kind)
    target = str(target or "licensed").strip().lower()
    if target not in ("free", "licensed"):
        raise ClipImportError("target must be 'free' or 'licensed'")
    if target == "free" and not redistributable:
        raise ClipImportError(
            "the free library is redistributable — tick 'redistributable' to "
            "confirm the licence allows it, or import into the licensed library")

    names = [safe_inbox_name(f) for f in (files or [])]
    if not 1 <= len(names) <= 2:
        raise ClipImportError("an import takes one file, or two for a pair")
    if len(names) == 2 and names[0].lower() == names[1].lower():
        raise ClipImportError("a pair needs two DIFFERENT files")
    paths_in: List[Path] = []
    src_family = ""
    for name in names:
        p = inbox_path(name)
        if not p.is_file():
            raise ClipImportError(f"no such file in the inbox: {name}")
        family = _cached_probe(p).get("skeleton_family")
        if not family:
            raise ClipImportError(
                f"{name}: unknown rig — no bone map matches its node names "
                f"(known: {', '.join(sorted(SIGNATURES))})")
        if src_family and family != src_family:
            raise ClipImportError(
                f"{name} carries a {family} rig, the other half is "
                f"{src_family} — both halves of a pair have to come from the "
                "same rig")
        src_family = src_family or family
        paths_in.append(p)

    rest_path: Optional[Path] = None
    if rest_file:
        rest_path = inbox_path(rest_file)
        if not rest_path.is_file():
            raise ClipImportError(f"no such reference pose in the inbox: {rest_file}")
        # The reference pose is read on the SOURCE rig — a file from another
        # rig family carries different bones in different places, and the
        # delta it produces is nonsense that no later stage can notice.
        # `is_rest_name` is a NAME heuristic, so the picker happily offered a
        # Unity `Tpose.fbx` for the Mixamo-named MOB1 packs; measured, that put
        # a constant offset of up to -174 deg into every frame of the affected
        # clips.
        rest_family = _cached_probe(rest_path).get("skeleton_family")
        if rest_family and src_family and rest_family != src_family:
            raise ClipImportError(
                f"{rest_file} carries a {rest_family} rig, but the clip is "
                f"{src_family} — a reference pose has to come from the SAME "
                "rig as the animation")

    cset = str(clip_set or "").strip().lower()
    if cset and ("/" in cset or "\\" in cset or cset in (".", "..")):
        raise ClipImportError("set must be a plain directory name")
    if not preview and not overwrite and kind in existing_kinds(cset, target):
        raise ClipKindExists(
            f"'{kind}' already exists in the {target} library"
            f"{f' (set {cset})' if cset else ''} — tick overwrite to replace it")

    rig = Path(rig) if rig else cmu_import.default_rig()
    if not rig.is_file():
        raise ClipImportError(f"rig not found: {rig} "
                              "— see shared/models/rig/README.md")

    inputs: Dict[str, Path] = {"rig": rig}
    if len(paths_in) == 2:
        inputs["src_a"], inputs["src_b"] = paths_in
    else:
        inputs["src"] = paths_in[0]
    if rest_path is not None:
        inputs["rest"] = rest_path

    params = {"kind": kind, "fps": int(fps), "start_s": float(start_s or 0.0),
              "end_s": end_s, "anchor_s": None,
              "in_place": bool(in_place) and len(paths_in) == 1,
              "loop_s": loop_s if len(paths_in) == 1 else None,
              # declared cycle: the caller's word, else the file name's
              # ("…_Loop0.fbx" is how packs mark their cycles)
              "loops": bool(loops) if loops is not None
              else any("loop" in Path(f).name.lower() for f in files),
              "offset_b_m": [float(v) for v in (offset_b_m or (0, 0, 0))][:3],
              "speed": float(speed or 1.0),
              "bone_map": "auto", "source_name": names}

    st = runner.status()
    if not st["executable"]:
        raise ClipImportError("no Blender executable found "
                              "(image_generation.blender_executable)")
    if preview:
        params["kind"] = "preview"
        out = preview_dir()
        out.mkdir(parents=True, exist_ok=True)
        for stale in out.glob("preview*"):
            stale.unlink()
        res = runner.run("fbx_clip", inputs=inputs, params=params, out_dir=out,
                         timeout_s=timeout_s)
        if not res["ok"]:
            raise ClipImportError(str(res.get("error") or "blender run failed"))
        base = "/assets/clips-inbox/preview-clip/"
        urls = ({"a": base + "preview__a.fbx", "b": base + "preview__b.fbx"}
                if len(paths_in) == 2 else {"solo": base + "preview.fbx"})
        return {"preview": True, "pair": len(paths_in) == 2, "urls": urls,
                "sidecar": res.get("data") or {}, "seconds": res.get("seconds") or 0.0}

    out = Path(out_dir) if out_dir else target_dir(target)
    if cset:
        out = out / cset
    out.mkdir(parents=True, exist_ok=True)
    res = runner.run("fbx_clip", inputs=inputs, params=params, out_dir=out,
                     timeout_s=timeout_s)
    if not res["ok"]:
        raise ClipImportError(str(res.get("error") or "blender run failed"))

    # The pose dropdown and the animation-set fallback read from the preset
    # caches — a fresh kind has to be selectable at once, not after a restart.
    try:
        from app.core import expression_pose_maps as epm
        epm.reload_presets()
    except Exception as e:                                   # pragma: no cover
        logger.warning("preset reload after clip import failed: %s", e)

    entry = next((e for e in clip_entries()
                  if e["kind"] == kind and e["set"] == cset and e["source"] == target),
                 None)
    logger.info("fbx clip imported: %s -> %s%s (%s, %.1fs)", ", ".join(names),
                f"{cset}/" if cset else "", kind, target, res.get("seconds") or 0.0)
    return {
        "kind": kind,
        "set": cset,
        "target": target,
        "pair": len(paths_in) == 2,
        "files": names,
        "rest_file": rest_path.name if rest_path is not None else "",
        "sidecar": res.get("data") or {},
        "outputs": [Path(p).name for p in (res.get("outputs") or {}).values()],
        "seconds": res.get("seconds") or 0.0,
        "clip": None if entry is None else {
            "kind": entry["kind"], "role": entry["role"], "set": entry["set"],
            "source": entry["source"], "filename": entry["path"].name,
            "url": "/assets/animation-clips/"
                   + ("licensed/" if entry["source"] == "licensed" else "")
                   + entry["rel"],
        },
    }
