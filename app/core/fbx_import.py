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
import struct
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

#: How much of a file is read AT A TIME while it is scanned for node names. In
#: an animation export the skeleton stands long before the curves, so the FIRST
#: chunk classifies almost every file and the scan stops there. A SKINNED
#: character export is the exception — its mesh comes first and its armature
#: can sit past any cap — so a file the first chunk cannot classify is read on,
#: chunk by chunk, rather than declared unknown (2026-09-05). That is not
#: cosmetic: `import_fbx` refuses a reference pose whose rig family it does not
#: know, and a skinned T-pose export is exactly the file an admin reaches for.
#:
#: Reading in chunks is what keeps the price of that: an inbox file has no size
#: cap (a 300 MB export is normal), and the scan never holds more than a
#: handful of these chunks (the one just read plus the copy that carries the
#: overlap into it) and the bounded name set of :func:`_tokens` — the peak does
#: not grow with the file. Measured at a 64 KiB window in
#: ``scripts/smoke_fbx_import.py``: 262 KiB for a 2 MiB file, against 21 MiB
#: for the same file read in one remainder.
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


def _meshy_biped_bones() -> Tuple[str, ...]:
    """The node names ``fbx_clip._meshy_biped()`` maps — Meshy AI's rigged
    biped. Mixamo's names except for the spine (numbered DOWNWARDS from the
    chest there, so ``Spine`` is the TOP segment) and a lowercase ``neck``.
    The rig's ``head_end`` and ``headfront`` are absent here for the same
    reason MotusMan's sockets are: the converter discards them."""
    return (
        "Hips", "Spine", "Spine01", "Spine02", "neck", "Head",
        "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
        "RightShoulder", "RightArm", "RightForeArm", "RightHand",
        "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
        "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase",
    )


def _autorig_pro_bones() -> Tuple[str, ...]:
    """The node names ``fbx_clip._autorig_pro()`` maps — a rig generated by
    Auto-Rig Pro, with ``.x``/``.l``/``.r`` side suffixes and ``*_stretch``
    limb names. The rig's ``Root`` null above the hips and its ``Jaw_ref.x`` /
    ``eyes_ref.x`` / ``eye_ref.L`` / ``eye_ref.R`` face controls are absent for
    the same reason MotusMan's sockets are: the converter discards them. There
    are three finger joints, not four — the rig carries no end sites."""
    names = [
        "root.x", "spine_01.x", "spine_02.x", "spine_03.x", "neck.x", "head.x",
        "shoulder.l", "arm_stretch.l", "forearm_stretch.l", "hand.l",
        "shoulder.r", "arm_stretch.r", "forearm_stretch.r", "hand.r",
        "thigh_stretch.l", "leg_stretch.l", "foot.l", "toes_01.l",
        "thigh_stretch.r", "leg_stretch.r", "foot.r", "toes_01.r",
    ]
    for side in ("l", "r"):
        for finger in ("thumb", "index", "middle", "ring", "pinky"):
            for n in (1, 2, 3):
                names.append(f"c_{finger}{n}.{side}")
    return tuple(names)


#: family → the node names that must ALL be present (mirror of
#: ``fbx_clip.SIGNATURES``; "auto" picks the first family that matches).
SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "unity-humanoid": ("Hips", "Left_UpperLeg", "Left_UpperArm", "Chest"),
    "mixamo-noprefix": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine2"),
    # ``Spine02`` vs ``Spine2`` is the whole difference between the two
    # Mixamo-shaped families — neither spelling appears in the other rig, so
    # the order these are tried in does not matter.
    "meshy-biped": ("Hips", "LeftUpLeg", "LeftForeArm", "Spine02"),
    # The side suffixes and the "_stretch" limb names share no token with any
    # Mixamo-shaped rig, so the order among the families does not matter here
    # either.
    "autorig-pro": ("root.x", "spine_01.x", "arm_stretch.l",
                    "thigh_stretch.l"),
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
    "meshy-biped": _meshy_biped_bones(),
    "autorig-pro": _autorig_pro_bones(),
}

#: family → node names that only exist when the rig has fingers.
FINGER_NAMES: Dict[str, Tuple[str, ...]] = {
    "unity-humanoid": ("Left_IndexProximal", "Right_IndexProximal"),
    "mixamo-noprefix": ("LeftHandIndex1", "RightHandIndex1"),
    # The Meshy biped has no finger joints at all — listed explicitly so the
    # empty answer reads as "checked", not as "family forgotten".
    "meshy-biped": (),
    "autorig-pro": ("c_index1.l", "c_index1.r"),
}

#: absolute path → (mtime_ns, size, probe); a probe is pure file content, so
#: the mtime pair is a complete cache key. Keyed by the full path, not the
#: file name: two subfolders of the inbox may well hold a ``walk.fbx`` each.
_probe_cache: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}

#: Same key, same reasoning, for the take listing of a multi-take file.
_takes_cache: Dict[str, Tuple[int, int, List[Dict[str, Any]]]] = {}


def is_rest_name(name: str) -> bool:
    """Does the FILE NAME say "reference pose"? (tpose / t-pose / rest / bind)"""
    low = Path(name).stem.lower()
    return any(marker in low for marker in REST_MARKERS)


#: Bytes of the previous chunk re-scanned with the next one, so a node name
#: cut in half by the read boundary is still seen whole. Any FBX node name is
#: far shorter than this.
_TOKEN_OVERLAP = 256


#: Every node name any table asks about — a signature name, a mapped bone or a
#: finger root. Nothing else can change an answer, so nothing else is kept.
_KNOWN_NAMES = frozenset(
    name
    for table in (SIGNATURES, BONE_NAMES, FINGER_NAMES)
    for names in table.values()
    for name in names)

#: Every fragment that DISQUALIFIES a family, flattened. A token carrying one
#: is remembered as the bare fragment: :func:`_match_family` looks for the
#: fragment INSIDE a token, and a fragment is inside itself.
_KNOWN_FRAGMENTS: Tuple[str, ...] = tuple(sorted(
    {frag for frags in EXCLUDE_FRAGMENTS.values() for frag in frags}))


def _tokens(data: bytes) -> set:
    """The printable ASCII runs of a byte block that CAN matter — an FBX keeps
    its node names in the clear, so these are the candidate rig names.

    Everything no table mentions is dropped on the spot. That is what makes a
    chunked scan bounded: what survives a block is at most one entry per known
    name, never one per printable run in the file (a 300 MB binary carries
    millions of those, and the set alone would dwarf the file).
    """
    out = set()
    for m in _TOKEN_RE.finditer(data):
        token = m.group().decode("ascii", "ignore")
        if token in _KNOWN_NAMES:
            out.add(token)
        for frag in _KNOWN_FRAGMENTS:
            if frag in token:
                out.add(frag)
    return out


def _match_family(tokens: set) -> str:
    """The first signature fully present in ``tokens`` and not disqualified by
    a fragment, ``""`` when none matches."""
    for family, signature in SIGNATURES.items():
        if not all(name in tokens for name in signature):
            continue
        if any(frag in tok for frag in EXCLUDE_FRAGMENTS.get(family, ()) for tok in tokens):
            continue
        return family
    return ""


#: FBX keeps time in these ticks per second — Kaydara's own unit, constant
#: across every binary version of the format.
_FBX_TICKS_PER_S = 46186158000

#: Node header layout: 64-bit offsets from version 7500, 32-bit before it.
_HDR_WIDE = struct.Struct("<QQQ")
_HDR_NARROW = struct.Struct("<III")


class FbxReadError(ValueError):
    """The file is not a binary FBX, or its node tree does not add up."""


def _node_header(fh, hdr: struct.Struct):
    """``(end_offset, num_props, prop_bytes, name)`` of the node at the cursor,
    or ``None`` at the null record that closes a nested list."""
    raw = fh.read(hdr.size)
    if len(raw) < hdr.size:
        return None
    end, nprops, propbytes = hdr.unpack(raw)
    if end == 0:
        return None
    name_len = fh.read(1)
    if not name_len:
        return None
    name = fh.read(name_len[0])
    return end, nprops, propbytes, name.decode("utf-8", "replace")


def _scalar_props(blob: bytes) -> List[Any]:
    """The SCALAR properties of one property blob, in order.

    Only what a take needs is decoded: integers, doubles and strings. An array
    property (the encoded curve data) is skipped by its own length — this
    walker never inflates one, which is the whole point of it.
    """
    out: List[Any] = []
    i = 0
    n = len(blob)
    while i < n:
        code = blob[i:i + 1].decode("ascii", "replace")
        i += 1
        if code == "Y":
            out.append(struct.unpack_from("<h", blob, i)[0]); i += 2
        elif code == "C":
            out.append(bool(blob[i])); i += 1
        elif code == "I":
            out.append(struct.unpack_from("<i", blob, i)[0]); i += 4
        elif code == "F":
            out.append(struct.unpack_from("<f", blob, i)[0]); i += 4
        elif code == "D":
            out.append(struct.unpack_from("<d", blob, i)[0]); i += 8
        elif code == "L":
            out.append(struct.unpack_from("<q", blob, i)[0]); i += 8
        elif code in ("S", "R"):
            ln = struct.unpack_from("<I", blob, i)[0]; i += 4
            raw = blob[i:i + ln]; i += ln
            out.append(raw.decode("utf-8", "replace") if code == "S" else b"")
        elif code in ("f", "d", "l", "i", "b"):
            _len, _enc, comp = struct.unpack_from("<III", blob, i)
            i += 12 + comp
            out.append(None)
        else:
            raise FbxReadError(f"unknown property code {code!r}")
    return out


def fbx_takes(path: Path) -> List[Dict[str, Any]]:
    """Every animation take of a binary FBX — ``[{index, name, duration_s}]``,
    in FILE ORDER.

    The INDEX is the contract with the converter, not the name: Blender caps
    an ID name at 63 characters and prefixes it with the object and layer, so
    a long take name arrives there truncated and cannot be matched back. The
    order, on the other hand, survives — Blender creates one action per stack
    as it reads them, so the n-th take here is the n-th action there.

    This is a SEEK walker, not a parser: every node that cannot contain a take
    is skipped by its own end offset, and the encoded curve arrays — the bulk
    of such a file — are never read, let alone inflated. A 87 MB file with 121
    takes and 60 984 curves is answered in well under a second, and the peak
    memory is one property blob.
    """
    path = Path(path)
    out: List[Dict[str, Any]] = []
    with path.open("rb") as fh:
        # "Kaydara FBX Binary  " + NUL, then two more bytes, then the version.
        if fh.read(20) != b"Kaydara FBX Binary  ":
            raise FbxReadError("not a binary FBX")
        fh.seek(23)
        version = struct.unpack("<I", fh.read(4))[0]
        hdr = _HDR_WIDE if version >= 7500 else _HDR_NARROW
        while True:
            head = _node_header(fh, hdr)
            if head is None:
                break
            end, nprops, propbytes, name = head
            if name != "Objects":
                fh.seek(end)
                continue
            # Inside Objects: read the stacks, skip everything else.
            fh.seek(fh.tell() + propbytes)
            while fh.tell() < end:
                child = _node_header(fh, hdr)
                if child is None:
                    break
                c_end, c_nprops, c_propbytes, c_name = child
                if c_name != "AnimationStack":
                    fh.seek(c_end)
                    continue
                props = _scalar_props(fh.read(c_propbytes)) if c_nprops else []
                take = ""
                for value in props:
                    if isinstance(value, str) and value:
                        take = value.split("\x00")[0]
                        break
                start = stop = 0
                while fh.tell() < c_end:
                    sub = _node_header(fh, hdr)
                    if sub is None:
                        break
                    s_end, s_nprops, s_propbytes, s_name = sub
                    if s_name != "Properties70":
                        fh.seek(s_end)
                        continue
                    fh.seek(fh.tell() + s_propbytes)
                    while fh.tell() < s_end:
                        pnode = _node_header(fh, hdr)
                        if pnode is None:
                            break
                        p_end, p_nprops, p_propbytes, _p_name = pnode
                        pv = _scalar_props(fh.read(p_propbytes)) if p_nprops else []
                        if pv and pv[0] == "LocalStart":
                            start = next((v for v in pv[1:] if isinstance(v, int)), 0)
                        elif pv and pv[0] == "LocalStop":
                            stop = next((v for v in pv[1:] if isinstance(v, int)), 0)
                        fh.seek(p_end)
                    fh.seek(s_end)
                out.append({"index": len(out), "name": take,
                            "duration_s": round(max(0, stop - start)
                                                / _FBX_TICKS_PER_S, 4)})
                fh.seek(c_end)
            break  # Objects is the only block that carries takes
    return out


def _cached_takes(path: Path) -> List[Dict[str, Any]]:
    """:func:`fbx_takes`, cached on the same key as the probe."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _takes_cache.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        takes = fbx_takes(path)
    except (FbxReadError, OSError, struct.error) as e:
        logger.debug("take listing failed for %s: %s", path.name, e)
        takes = []
    _takes_cache[key] = (st.st_mtime_ns, st.st_size, takes)
    return takes


def probe_fbx(path: Path) -> Dict[str, Any]:
    """What rig does this file carry — ``{skeleton_family, bone_count,
    has_fingers, is_rest_candidate, take_count}`` plus ``error`` when the file
    cannot be read at all.

    ``skeleton_family`` is ``""`` when no signature matches: an unknown rig,
    which the importer refuses (the retargeter has no bone map for it).

    The file is walked in ``MAX_PROBE_BYTES`` chunks and the walk STOPS at the
    chunk that identifies the family — an animation export is answered by its
    first chunk, a skinned character export (mesh first, armature last) is
    followed to wherever its armature sits, and neither costs more memory than
    the other. ``bone_count`` therefore counts the mapped names seen UP TO that
    chunk; the names of one armature are written as one block, so in practice
    that is all of them.

    ``take_count`` comes from :func:`fbx_takes`, a separate seek walk that
    reads no curve data — a pack file with a hundred animations costs about as
    much here as a single-take export.
    """
    path = Path(path)
    out: Dict[str, Any] = {"skeleton_family": "", "bone_count": 0,
                           "has_fingers": False,
                           "is_rest_candidate": is_rest_name(path.name),
                           "take_count": 0}
    tokens: set = set()
    family = ""
    try:
        with path.open("rb") as fh:
            carry = b""
            while True:
                chunk = fh.read(MAX_PROBE_BYTES)
                if not chunk:
                    break
                # A node name can straddle the read boundary; the tail of the
                # previous chunk is re-scanned with this one so the split
                # cannot swallow one.
                tokens |= _tokens(carry + chunk if carry else chunk)
                family = _match_family(tokens)
                if family:
                    break
                carry = chunk[-_TOKEN_OVERLAP:]
    except OSError as e:
        out["error"] = str(e)
        return out
    if family:
        out["skeleton_family"] = family
        out["bone_count"] = sum(1 for n in BONE_NAMES.get(family, ()) if n in tokens)
        out["has_fingers"] = any(n in tokens for n in FINGER_NAMES.get(family, ()))
    # How many animations the file holds. One is the ordinary case and needs no
    # choice; more than one means the caller MUST name a take, and the listing
    # is what tells a user that before they try.
    try:
        out["take_count"] = len(fbx_takes(path))
    except (FbxReadError, OSError, struct.error) as e:
        logger.debug("take count failed for %s: %s", path.name, e)
    return out


def file_spec(entry: Any) -> Tuple[str, Optional[int]]:
    """One source address → ``(relative name, take index or None)``.

    THE address form of this module: ``{"name": "pack.fbx", "take": 7}``. A
    file that holds a single animation passes ``take`` as null (or leaves it
    out); a pack file names which of its stacks it means. There is deliberately
    no second, shorter spelling — a bare string would have to mean "take 0",
    and "the first one" is exactly the guess that hands a user the wrong
    animation under the right name.
    """
    if not isinstance(entry, dict):
        raise ClipImportError(
            "a source is {name, take}, not " + type(entry).__name__)
    name = safe_inbox_name(entry.get("name"))
    raw = entry.get("take")
    if raw is None or raw == "":
        return name, None
    try:
        take = int(raw)
    except (TypeError, ValueError):
        raise ClipImportError(f"{name}: take must be a number, got {raw!r}")
    if take < 0:
        raise ClipImportError(f"{name}: take must not be negative")
    return name, take


def resolve_take(name: str, take: Optional[int]) -> Dict[str, Any]:
    """Checks one address against the file and returns what Blender needs —
    ``{take, take_count, take_name}``.

    A file with several animations MUST name one: picking silently would mean
    picking the first, which is what the FBX importer assigns and what nobody
    asked for. A file with one animation may name it or not.
    """
    takes = _cached_takes(inbox_path(name))
    count = len(takes)
    if take is None:
        if count > 1:
            raise ClipImportError(
                f"{name}: this file holds {count} animations — pick one")
        return {"take": None, "take_count": count, "take_name": ""}
    if not 0 <= take < max(count, 1):
        raise ClipImportError(f"{name}: no take {take} — the file has {count}")
    return {"take": take, "take_count": count,
            "take_name": takes[take]["name"] if takes else ""}


def inbox_takes(name: Any) -> List[Dict[str, Any]]:
    """Every take of ONE inbox file, addressed by its relative path.

    The list is what the import form offers as a choice; the ``index`` of the
    entry the user picks is what travels to the converter (see
    :func:`fbx_takes` on why the name cannot).
    """
    rel = safe_inbox_name(name)
    takes = _cached_takes(get_clips_inbox_dir() / rel)
    names = [t["name"] for t in takes]
    # ``pair`` is the partner's INDEX, so the picker can preselect the other
    # half the way it preselects a partner FILE for a single-take export.
    return [dict(t, pair=partner_take(t["name"], names)) for t in takes]


def _cached_probe(path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
    except OSError as e:
        return {"skeleton_family": "", "bone_count": 0, "has_fingers": False,
                "is_rest_candidate": is_rest_name(path.name), "take_count": 0,
                "error": str(e)}
    key = str(path)
    hit = _probe_cache.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    probe = probe_fbx(path)
    _probe_cache[key] = (st.st_mtime_ns, st.st_size, probe)
    return probe


def safe_inbox_name(raw: Any) -> str:
    """A file INSIDE the inbox as a relative POSIX path (``walk.fbx`` or
    ``pack/female/walk.fbx``) — no traversal, no absolute path, no hidden
    segment, only a clip extension. Raises ``ClipImportError`` on anything
    else and returns the normalised form (forward slashes, no empty segments).

    This is the ONE gate between a request and the file system here: the whole
    API talks in these relative paths and nothing else. Beyond the segment
    rules, the resolved path has to lie under the resolved inbox root — a
    symlink pointing out of the inbox is refused the same way ``..`` is.
    """
    name = str(raw or "").strip()
    if not name:
        raise ClipImportError("file name must not be empty")
    if "\\" in name or name.startswith("/"):
        raise ClipImportError(f"not a path inside the inbox: {name!r}")
    segments = [seg for seg in name.split("/") if seg]
    if not segments:
        raise ClipImportError(f"not a path inside the inbox: {name!r}")
    for seg in segments:
        # "." and ".." fall under "starts with a dot" — hidden segments (and
        # the `.preview` scratch folder) are never addressable.
        if seg.startswith(".") or Path(seg).name != seg:
            raise ClipImportError(f"not a path inside the inbox: {name!r}")
    if Path(segments[-1]).suffix.lower() not in INBOX_EXTS:
        raise ClipImportError(f"only {', '.join(INBOX_EXTS)} files can be imported")
    rel = "/".join(segments)
    root = get_clips_inbox_dir().resolve()
    resolved = (root / rel).resolve()
    if root not in resolved.parents:
        raise ClipImportError(f"not a path inside the inbox: {name!r}")
    return rel


def inbox_path(name: str) -> Path:
    """The file behind a validated inbox path — existence is NOT checked."""
    return get_clips_inbox_dir() / safe_inbox_name(name)


def inbox_rel(path: Path) -> str:
    """The relative POSIX path the API speaks for an inbox file."""
    return path.relative_to(get_clips_inbox_dir()).as_posix()


def _walk_inbox(directory: Path, root: Path) -> List[Path]:
    """Importable files under ``directory``, recursively; hidden files and
    hidden folders (``.preview`` among them) are skipped, and so is anything
    that resolves outside ``root`` (the resolved inbox) — a symlink pointing
    out would be listed but refused by the gate, a useless entry. Within one
    folder the files come first, then the subfolders — each sorted by name."""
    files: List[Path] = []
    subdirs: List[Path] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            if root not in child.resolve().parents:
                continue
        except OSError:
            continue
        if child.is_dir():
            subdirs.append(child)
        elif child.is_file() and child.suffix.lower() in INBOX_EXTS:
            files.append(child)
    files.sort(key=lambda p: p.name.lower())
    subdirs.sort(key=lambda p: p.name.lower())
    for sub in subdirs:
        files.extend(_walk_inbox(sub, root))
    return files


def inbox_files() -> List[Path]:
    """Every importable file lying in the inbox or one of its subfolders:
    the root's files first, then folder by folder. A missing directory is the
    normal empty state."""
    root = get_clips_inbox_dir()
    if not root.is_dir():
        return []
    return _walk_inbox(root, root.resolve())


def inbox_entries() -> List[Dict[str, Any]]:
    """The inbox as the admin sees it: ``{name, size, mtime, probe}`` per
    file, ``name`` being the relative path (``pack/walk.fbx``)."""
    out = []
    for p in inbox_files():
        st = p.stat()
        out.append({"name": inbox_rel(p), "size": st.st_size,
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


#: A take name in a pack names its ROLE before the scene it belongs to:
#: "Female[A]_Resting_Loop0" — a word for the kind of performer, an optional
#: slot letter when a scene has several of that kind, then the scene and phase.
_TAKE_ROLE_RE = re.compile(
    r"^(?P<who>[A-Za-z]+)(?P<slot>\[[A-Za-z0-9]+\])?[_-](?P<rest>.+)$")

#: The counterpart words, from the same table the file-name rule uses.
PAIR_ROLE_WORDS = tuple((a.strip("_-"), b.strip("_-")) for a, b in PAIR_PREFIXES)


def _take_role(name: str) -> Optional[Tuple[str, str, str]]:
    """``(role word, slot, scene)`` of a take name, all lowercase — or None
    when the name carries no role marker at all."""
    m = _TAKE_ROLE_RE.match(name.strip())
    if not m:
        return None
    return (m.group("who").lower(), (m.group("slot") or "").lower(),
            m.group("rest").lower())


def partner_take(name: str, names: List[str]) -> Optional[int]:
    """Index in ``names`` of the take that plays the OTHER half of the same
    scene as ``name`` — the take-level twin of :func:`pair_suggestion`.

    Both halves of a scene live in ONE pack file, so the partner is not
    another file but another take: the same scene and the same phase, played
    by the counterpart role. Preference is the counterpart word at the SAME
    slot first (a scene with three performers of one kind still pairs A with
    A), then the counterpart word at any slot.

    Returns None when nothing matches — a suggestion pointing at the wrong
    animation is worse than no suggestion, exactly as in
    :func:`pair_suggestion`.
    """
    me = _take_role(name)
    if me is None:
        return None
    mates = {b for a, b in PAIR_ROLE_WORDS if a == me[0]}
    mates |= {a for a, b in PAIR_ROLE_WORDS if b == me[0]}
    best: Optional[Tuple[int, int]] = None
    for i, other in enumerate(names):
        if other == name:
            continue
        o = _take_role(other)
        # Same scene AND same phase: the partner of a cycle is the partner's
        # cycle, never their climax.
        if o is None or o[2] != me[2]:
            continue
        if o[0] == me[0] and o[1] == me[1]:
            continue
        if o[0] in mates:
            score = 0 if o[1] == me[1] else 1
        else:
            continue
        if best is None or score < best[0]:
            best = (score, i)
    return None if best is None else best[1]


def pair_suggestion(name: str) -> str:
    """The partner file of ``name`` (a relative inbox path) — but only when it
    really lies in the SAME folder of the inbox. ``""`` when nothing matches;
    a suggestion that names a missing file would be a broken import waiting to
    happen."""
    have = {inbox_rel(p).lower(): inbox_rel(p) for p in inbox_files()}
    folder, _, base = name.rpartition("/")
    prefix = folder.lower() + "/" if folder else ""
    for candidate in partner_names(base):
        hit = have.get(prefix + candidate)
        if hit and hit.lower() != name.lower():
            return hit
    return ""


def rest_suggestion() -> str:
    """The first file in the inbox (root first, then the subfolders) that
    looks like a reference pose, as a relative path; ``""`` when there is
    none."""
    for p in inbox_files():
        if is_rest_name(p.name):
            return inbox_rel(p)
    return ""


def delete_inbox(name: str) -> bool:
    """Removes one inbox file. False when it was not there — deleting twice is
    not an error, the file is gone either way. An emptied subfolder is left
    in place: the user made it, the user removes it."""
    path = inbox_path(name)
    _probe_cache.pop(str(path), None)
    _takes_cache.pop(str(path), None)
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


def import_fbx(kind: str, files: List[Any], *, rest_file: Optional[Any] = None,
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

    ``files`` is one relative inbox path, or two — the A half first (see
    :func:`safe_inbox_name` for the form); ``rest_file`` is an
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

    specs = [file_spec(f) for f in (files or [])]
    names = [n for n, _t in specs]
    if not 1 <= len(specs) <= 2:
        raise ClipImportError("an import takes one source, or two for a pair")
    if len(specs) == 2 and (specs[0][0].lower(), specs[0][1]) == \
            (specs[1][0].lower(), specs[1][1]):
        raise ClipImportError(
            "a pair needs two DIFFERENT sources — one take cannot play both "
            "halves")
    paths_in: List[Path] = []
    take_specs: List[Dict[str, Any]] = []
    src_family = ""
    for name, take in specs:
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
        # Which animation of the file. Fails CLOSED when the file holds
        # several and the caller named none: Blender assigns only the FIRST
        # stack's action on import and the converter reads the range of
        # whatever is active, so guessing here converts the wrong take under
        # the right name.
        take_specs.append(resolve_take(name, take))
        paths_in.append(p)

    rest_path: Optional[Path] = None
    rest_spec: Dict[str, Any] = {}
    if rest_file:
        rest_name, rest_take = file_spec(rest_file)
        rest_path = inbox_path(rest_name)
        if not rest_path.is_file():
            raise ClipImportError(f"no such reference pose in the inbox: {rest_name}")
        # The reference pose is read on the SOURCE rig — a file from another
        # rig family carries different bones in different places, and the
        # delta it produces is nonsense that no later stage can notice.
        # `is_rest_name` is a NAME heuristic, so the picker happily offered a
        # Unity `Tpose.fbx` for the Mixamo-named MOB1 packs; measured, that put
        # a constant offset of up to -174 deg into every frame of the affected
        # clips.
        rest_family = _cached_probe(rest_path).get("skeleton_family")
        if not rest_family:
            # Fail CLOSED, exactly as an unclassifiable clip file does above: a
            # rest file the probe cannot place would otherwise slip past the
            # comparison below, and `bone_map: "auto"` would then have to place
            # it inside Blender — a late, ugly failure at best, and a silent
            # retarget against the wrong family at worst.
            raise ClipImportError(
                f"{rest_name}: unknown rig — the reference pose's rig family "
                f"could not be identified from its node names "
                f"(known: {', '.join(sorted(SIGNATURES))})")
        if rest_family != src_family:
            raise ClipImportError(
                f"{rest_name} carries a {rest_family} rig, but the clip is "
                f"{src_family} — a reference pose has to come from the SAME "
                "rig as the animation")
        # A pack ships its reference pose as one stack among the movements, so
        # the rest slot is addressed exactly like a source: file AND take.
        rest_spec = resolve_take(rest_name, rest_take)

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
        inputs["src_a"] = paths_in[0]
        # Both halves out of ONE pack file is the normal case for a scene, and
        # then the file travels once: the runner copies every input into the
        # job directory and Blender imports every path it is given, so naming
        # it twice would copy and import the same bytes twice.
        if paths_in[1] != paths_in[0]:
            inputs["src_b"] = paths_in[1]
    else:
        inputs["src"] = paths_in[0]
    # A reference pose that IS one of the sources travels as a take index, not
    # as a second copy of the same file: the runner copies every input into the
    # job directory, so passing it twice would copy a pack file twice and make
    # Blender import it twice — measured at 6.5 s and 850 MB per import.
    rest_from = ""
    if rest_path is not None:
        same = [key for key, val in inputs.items()
                if key != "rig" and val == rest_path]
        if same:
            rest_from = same[0]
        else:
            inputs["rest"] = rest_path

    params = {"kind": kind, "fps": int(fps), "start_s": float(start_s or 0.0),
              "end_s": end_s, "anchor_s": None,
              "in_place": bool(in_place) and len(paths_in) == 1,
              "loop_s": loop_s if len(paths_in) == 1 else None,
              # declared cycle: the caller's word, else what the source
              # CALLS itself — the take name for a pack file, the file name
              # for a single-take export ("…_Loop0" is how packs mark cycles).
              "loops": bool(loops) if loops is not None
              else any("loop" in (s["take_name"] or n).lower()
                       for s, n in zip(take_specs, names)),
              "takes": take_specs,
              "rest_take": rest_spec,
              "rest_from": rest_from,
              "rest_name": rest_path.name if rest_path is not None else "",
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
        "rest_file": inbox_rel(rest_path) if rest_path is not None else "",
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
