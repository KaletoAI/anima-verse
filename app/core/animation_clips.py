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
``handshake__b.fbx`` are the two halves of the kind ``handshake``. A GROUP
clip continues the letters up to ``__e`` (three to five people,
``CLIP_ROLES``; the sidecar's ``roles`` lists them). The double underscore is
the role separator and nothing else (a single ``_`` stays part of the kind).
A pair or group kind has no solo file; it is played by its figures at a
shared anchor, in lockstep. Next to the files a JSON SIDECAR (written by
``scripts/clip_import_cmu.py``) holds duration, frame rate and the anchor
geometry: for a file ``<stem>.fbx`` it is ``<stem>.json`` when that exists —
so a numbered variant may carry its own numbers — and the shared
``<kind>.json`` otherwise; ``clip_meta()`` reads it.

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
import hashlib
import json
from contextlib import nullcontext
from functools import wraps
import math
import os
import re
import shutil
import tempfile
import threading
import time
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from app.core.http_files import atomic_replace, content_version

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.paths import (get_animation_clips_dir, get_animation_clips_dirs,
                            get_config_dir, get_licensed_clips_dir,
                            get_rig_file)

logger = get_logger(__name__)

CLIP_EXTS = (".fbx", ".glb", ".gltf")
#: The role letters of a multi-person clip, in order: a pair has ``a``/``b``,
#: a group up to five (plan-gruppen-animationen.md). File ``<kind>__<role>``.
CLIP_ROLES = ("a", "b", "c", "d", "e")
ROLE_SEPARATOR = "__"
LIBRARIES = ("free", "licensed")
#: The cumulative orientation dials a clip sidecar records, in degrees —
#: what the import baked plus every later ``orient_clip``.
ORIENT_ANGLES = ("yaw_deg", "tilt_deg", "roll_deg")
#: Absolute renderer-only corrections for a 1.70 m reference figure, in cm.
HEIGHT_OFFSET_SURFACES = ("ground", "seat", "lie")
#: How an import treats the root's horizontal travel — the ONE list the routes
#: and the import core validate against. ``strip`` keeps the figure on the
#: spot, ``keep`` bakes the source's travel into the file, ``foot_lock``
#: rebuilds it from the planted feet. The Blender side keeps its own copy in
#: ``app/blender/scripts/_root_motion.py`` (bpy scripts do not import the app
#: package); ``scripts/smoke_root_motion_math.py`` checks the two are equal.
ROOT_MOTION_MODES = ("strip", "keep", "foot_lock")

# A kind is a file stem: lowercase, spaces allowed (they exist in the shipped
# library), but never the pair-role separator and never a path separator.
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9 _-]*$")
# A set is a DIRECTORY name — same alphabet without spaces; "" is the root.
SET_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# ``<kind>__<role>[~<alt>][_<n>]`` — the parts a rename has to keep apart; an
# ALT half keeps its ``~<alt>`` inside the role part.
_STEM_RE = re.compile(r"^(?P<kind>.*?)(?:__(?P<role>[a-e](?:~[a-z0-9][a-z0-9-]*)?))?(?P<num>_\d+)?$")
# An ALT half of a pair or group clip (plan-gruppen-animationen.md, G6): a
# replacement for ONE role, recorded in the scene's frame —
# ``<kind>__<role>~<alt>.fbx`` beside the scene's own halves, its names in
# the sidecar's ``alts: {role: [alt, …]}``.
ALT_SEPARATOR = "~"
ALT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# The variant numbering — cut from a file stem, refused inside a kind.
_NUM_SUFFIX_RE = re.compile(r"_\d+$")


class ClipLibraryError(Exception):
    """Bad input for a library operation (route: 400)."""


class ClipNotFound(ClipLibraryError):
    """The addressed clip does not exist (route: 404)."""


class ClipExists(ClipLibraryError):
    """The target name is already taken (route: 409)."""


def parse_clip_name(filename: str) -> str:
    """The clip KIND from a file name — the whole stem, lowercased, minus a
    trailing ``_<number>``.

    ONLY that numbering suffix is decoration; hyphens and inner underscores
    belong to the kind. Splitting at them was the bug of 2026-08-13: it filed
    ``swim-idle.fbx`` under "swim" (two clips of one kind, the wrong one played
    while moving) and ``treading-water.fbx`` under "treading", so the kind an
    author wrote for treading water existed nowhere. The set is NOT read from
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
    """``(kind, role)`` from a file name — role ``"a"``..``"e"`` for the half of
    a pair or group clip (``kiss__b.fbx`` → ``("kiss", "b")``), ``""`` for a
    solo clip.
    The numbering suffix is cut BEFORE the role is read, so ``hug__a_02.fbx``
    is a second take of the A half."""
    stem = Path(filename).stem.strip().lower()
    stem = _NUM_SUFFIX_RE.sub("", stem) or stem
    head, sep, tail = stem.rpartition(ROLE_SEPARATOR)
    role, _alt_sep, alt = tail.partition(ALT_SEPARATOR)
    if sep and head and role in CLIP_ROLES and (not _alt_sep or ALT_NAME_RE.match(alt)):
        return head, role
    return stem, ""


def parse_clip_alt(filename: str) -> str:
    """The ALT name of a role half (``kiss__b~wave.fbx`` → ``"wave"``), ``""``
    for every other file — a plain half, a solo clip, or a ``~`` that does not
    follow a role (then the whole stem is a solo kind, as before)."""
    stem = Path(filename).stem.strip().lower()
    stem = _NUM_SUFFIX_RE.sub("", stem) or stem
    head, sep, tail = stem.rpartition(ROLE_SEPARATOR)
    role, alt_sep, alt = tail.partition(ALT_SEPARATOR)
    if sep and head and role in CLIP_ROLES and alt_sep and ALT_NAME_RE.match(alt):
        return alt
    return ""


# ── The entry cache ──────────────────────────────────────────────────────
#
# ``clip_entries()`` is read on hot paths (every tool decision asks for the
# pair kinds, every partner pose for its clip), and a full scan of both
# libraries stats every file — 4 s on the event loop under GIL contention was
# measured. The scan result is therefore cached behind a FINGERPRINT that is
# cheap to take: the resolved library roots (so ``ANIMATION_CLIPS_DIR`` in a
# test is a different key) plus ``st_mtime_ns`` of each root and each set
# subdirectory. Adding, removing or renaming a file changes the mtime of the
# directory it lives in; that is the whole invalidation rule, plus
# ``reload_clip_caches()`` for everything an edit of this module does.
#
# The fingerprint is taken BEFORE the scan, so a file that appears during the
# scan makes the next fingerprint differ instead of being lost. A directory
# mtime younger than one second is not trusted (filesystem timestamp
# granularity: a second change inside the same tick would not move it) — such
# a result is returned but not cached, and the next call scans again.

_ENTRIES_LOCK = threading.Lock()
_ENTRIES_CACHE: Optional[Tuple[Any, List[Dict[str, Any]]]] = None
_MTIME_SETTLE_NS = 1_000_000_000


def _library_fingerprint(root: Path) -> Tuple[Any, ...]:
    """``(root mtime, ((set dir, mtime), …))`` of one library, ``("absent",)``
    when the root does not exist."""
    try:
        root_mtime = os.stat(root).st_mtime_ns
    except FileNotFoundError:
        return ("absent",)
    subdirs = []
    try:
        with os.scandir(root) as it:
            for de in it:
                if de.name.startswith("."):
                    continue
                try:
                    if de.is_dir():
                        subdirs.append((de.name, de.stat().st_mtime_ns))
                except OSError:
                    continue
    except OSError:
        return ("absent",)
    return (root_mtime, tuple(sorted(subdirs)))


def _fingerprint_is_settled(fingerprint: Tuple[Any, ...]) -> bool:
    """False when any directory mtime in it is younger than one second."""
    horizon = time.time_ns() - _MTIME_SETTLE_NS
    for _key, lib in fingerprint:
        if lib == ("absent",):
            continue
        root_mtime, subdirs = lib
        if root_mtime > horizon or any(m > horizon for _n, m in subdirs):
            return False
    return True


def _scan_library(root: Path, source: str) -> List[Dict[str, Any]]:
    """Every clip file of one library root: the root (set "") plus exactly ONE
    level of set subdirectories."""
    def _files_of(directory: Path, cset: str) -> List[Dict[str, Any]]:
        out = []
        with os.scandir(directory) as it:
            dir_entries = sorted(it, key=lambda de: de.name)
        for de in dir_entries:
            if de.name.startswith("."):
                continue
            try:
                if not de.is_file():
                    continue
            except OSError:
                continue
            p = Path(de.path)
            if p.suffix.lower() not in CLIP_EXTS:
                continue
            kind, role = parse_clip_role(p.name)
            rel = f"{cset}/{p.name}" if cset else p.name
            entry = {"kind": kind, "role": role, "set": cset,
                     "source": source, "rel": rel, "path": p}
            alt = parse_clip_alt(p.name)
            if alt:
                entry["alt"] = alt
            out.append(entry)
        return out

    found = _files_of(root, "")
    with os.scandir(root) as it:
        set_dirs = sorted((de for de in it
                           if not de.name.startswith(".") and de.is_dir()),
                          key=lambda de: de.name)
    for de in set_dirs:
        found.extend(_files_of(Path(de.path), de.name.strip().lower()))
    return found


def _scan_entries(libraries: List[Tuple[Path, str]]) -> List[Dict[str, Any]]:
    """The uncached scan behind ``clip_entries()``."""
    by_rel: Dict[str, Dict[str, Any]] = {}
    for root, source in libraries:
        if not root.exists():
            continue
        for e in _scan_library(root, source):
            # free is scanned first; a licensed twin replaces it
            by_rel[e["rel"]] = e
    return sorted(by_rel.values(), key=lambda e: (e["set"], e["rel"]))


def clip_entries() -> List[Dict[str, Any]]:
    """Every clip of both libraries as ``{kind, role, set, source, rel, path}``
    — without the ALT halves (:func:`alt_entries`): they replace a role only
    where a running interaction names them, and every other reader (pose
    dropdowns, role counts, transitions) keeps seeing exactly the scene.

    Per library: the root (set "") plus exactly ONE level of subdirectories
    (the directory name, lowercased, is the set). Hidden files and
    directories (``.`` prefix) are skipped, as is anything without a clip
    extension. ``rel`` is ``[<set>/]<file>``; the same ``rel`` in both
    libraries yields ONE entry, the licensed one.

    Cached behind a directory-mtime fingerprint (see above); every call gets
    its own copies, so a caller may modify what it receives.
    """
    return [e for e in _all_entries() if "alt" not in e]


def alt_entries() -> List[Dict[str, Any]]:
    """The ALT halves of both libraries: entries like :func:`clip_entries`'
    plus ``alt`` (the name), ``kind``/``role`` being the scene and the role
    they replace."""
    return [e for e in _all_entries() if "alt" in e]


def clip_alts(kind: str) -> Dict[str, List[str]]:
    """``{role: [alt, …]}`` — the alt halves of a pair or group clip that
    EXIST as files (any set, either library), in the order the sidecar lists
    them, unlisted files after it alphabetically. ``{}`` without any."""
    have: Dict[str, set] = {}
    for e in alt_entries():
        if e["kind"] == kind:
            have.setdefault(e["role"], set()).add(e["alt"])
    if not have:
        return {}
    listed = (clip_meta(kind) or {}).get("alts")
    listed = listed if isinstance(listed, dict) else {}
    out: Dict[str, List[str]] = {}
    for role in sorted(have):
        order = [n for n in (listed.get(role) or []) if n in have[role]]
        out[role] = order + sorted(have[role] - set(order))
    return out


def alt_label(alt: str) -> str:
    """How an alt reads in a menu: ``arm-down`` → ``Arm down``."""
    words = str(alt or "").replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def _all_entries() -> List[Dict[str, Any]]:
    """Every clip file, alts included — the cached scan behind both lists."""
    global _ENTRIES_CACHE
    libraries = [(Path(root), source) for root, source in get_animation_clips_dirs()]
    # Taken BEFORE the scan: a change during the scan shows up next time.
    fingerprint = tuple(
        ((str(root.resolve()), source), _library_fingerprint(root))
        for root, source in libraries)
    cached = _ENTRIES_CACHE
    if cached is not None and cached[0] == fingerprint:
        return [dict(e) for e in cached[1]]
    entries = _scan_entries(libraries)
    if _fingerprint_is_settled(fingerprint):
        with _ENTRIES_LOCK:
            # One atomic assignment of the (fingerprint, entries) pair — a
            # reader never sees a fingerprint with another scan's entries.
            _ENTRIES_CACHE = (fingerprint, entries)
    return [dict(e) for e in entries]


def _clear_entries_cache() -> None:
    global _ENTRIES_CACHE, _REVISION_CACHE, _REVISION_EPOCH
    _REVISION_EPOCH = object()
    _REVISION_CACHE = None
    with _ENTRIES_LOCK:
        _ENTRIES_CACHE = None


# Reuse the entry cache's directory fingerprint; own in-place writes clear both.
_REVISION_CACHE = None
_REVISION_EPOCH = object()


def _revision_files(libraries):
    """Stat clips and JSON sidecars in both libraries, including hidden twins."""
    rows = []
    for root, source in libraries:
        if not root.exists():
            continue
        directories = [root] + sorted(p for p in root.iterdir()
                                      if p.is_dir() and not p.name.startswith("."))
        for directory in directories:
            for path in directory.iterdir():
                if path.name.startswith(".") or path.suffix.lower() not in (*CLIP_EXTS, ".json"):
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if path.is_file():
                    rows.append((source, path.relative_to(root).as_posix(),
                                 stat.st_mtime_ns, stat.st_size))
    return sorted(rows)


def library_revision() -> str:
    """SHA1 of both libraries' file stats, shared seed mtime and world rules.

    Directory discovery is cheap; the full file-stat scan is cached by the
    same settled fingerprint as clip_entries. In-place library writers must
    call reload_clip_caches, as they already do for the pose caches.
    """
    global _REVISION_CACHE
    import sqlite3
    from app.core.db import get_connection
    libraries = [(Path(root), source) for root, source in get_animation_clips_dirs()]
    fingerprint = tuple(((str(root.resolve()), source), _library_fingerprint(root))
                        for root, source in libraries)
    # Capture invalidation before scanning: a concurrent reload must not let
    # an older file snapshot become the cached value of a newer publication.
    cache_key = (_REVISION_EPOCH, fingerprint)
    cached = _REVISION_CACHE
    if cached is not None and cached[0] == cache_key:
        files_digest = cached[1]
    else:
        files_digest = json.dumps(_revision_files(libraries), separators=(",", ":"))
        if _fingerprint_is_settled(fingerprint):
            _REVISION_CACHE = (cache_key, files_digest)
    try:
        seed_mtime = clip_transitions_path().stat().st_mtime_ns
    except FileNotFoundError:
        seed_mtime = None
    try:
        # The rows themselves (a small table): a deleted older rule changes
        # neither MAX(updated_at) nor anything else a cheaper stamp would see.
        world_stamp = get_connection().execute(
            "SELECT from_pose, to_pose, kind, accel FROM clip_transitions_world "
            "ORDER BY from_pose, to_pose").fetchall()
        world_stamp = [list(row) for row in world_stamp]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        world_stamp = None
    return hashlib.sha1(json.dumps((files_digest, seed_mtime, world_stamp),
                                   separators=(",", ":")).encode()).hexdigest()


def notify_library_changed() -> None:
    """Invalidate public library structure, never send library data.

    Safe under a writer lock: notify only queues topics and wakes the SSE
    loop via call_soon_threadsafe; it never reads clips or waits for a reader.
    In particular, do not compute the revision in this notification path.
    """
    from app.core import sync_topics
    sync_topics.notify("clips", to=sync_topics.Everyone())


def clip_files() -> List[Path]:
    """Every clip file in the shared directory (all sets), sorted."""
    return [e["path"] for e in clip_entries()]


def clip_kinds() -> List[str]:
    """The animation kinds that actually exist right now."""
    return sorted({e["kind"] for e in clip_entries()} - {""})


def pair_kinds() -> List[str]:
    """Kinds that exist as a COMPLETE pair (both halves present in one set)
    — exactly the roles ``a`` and ``b``: a group clip (``__c`` and on) is not
    a pair, playing two of its roles would leave the others out."""
    return sorted(k for k, n in role_counts().items() if n == 2)


def role_counts() -> Dict[str, int]:
    """Kind -> number of roles, for every kind that exists COMPLETE in one
    set: its role files are ``a`` up to some letter without a gap (a pair
    2, a group 3..5). A kind with a missing role is left out."""
    halves: Dict[Tuple[str, str], set] = {}
    for e in clip_entries():
        if e["role"]:
            halves.setdefault((e["set"], e["kind"]), set()).add(e["role"])
    out: Dict[str, int] = {}
    for (_s, kind), roles in halves.items():
        n = len(roles)
        if n >= 2 and roles == set(CLIP_ROLES[:n]):
            out[kind] = max(out.get(kind, 0), n)
    return out


def clip_meta(kind: str, cset: str = "",
              stem: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The sidecar of a clip (duration, fps, pair geometry), None when there is
    none. Looked up in the set directory, then the root.

    THE SIDECAR RULE: for a file ``<stem>.fbx`` the sidecar is ``<stem>.json``
    when that file exists, else the shared ``<kind>.json``. So a numbered
    variant may carry its OWN numbers (``idle_02.fbx`` + ``idle_02.json``) and
    only falls back to the numbers of its kind when it does not. Callers that
    know only a kind (the pair geometry of the listing, the interaction
    engine) pass no ``stem`` and get exactly the old behaviour.
    """
    names = [stem] if stem and stem != kind else []
    names.append(kind)
    candidates = []
    for name in names:
        # licensed first — the sidecar belongs to the file that wins
        for root, _source in reversed(get_animation_clips_dirs()):
            if cset:
                candidates.append(root / cset / f"{name}.json")
            candidates.append(root / f"{name}.json")
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


def _solo_kinds() -> set:
    """Kinds that exist as a SOLO clip (any set, either library) — a pair
    kind is played by two figures at a shared anchor and cannot be a
    solo transition clip."""
    return {e["kind"] for e in clip_entries() if not e["role"]}


# ── Transitions: the clip that has to play BETWEEN two clips ─────────────

#: Wildcard in a transition rule: "whatever comes next" on the ``to`` side is
#: an EXIT clip, "whatever came before" on the ``from`` side an ENTER clip.
TRANSITION_ANY = "*"


def clip_transitions_path() -> Path:
    """Shared seed for clip transition rules."""
    return get_config_dir() / "clip_transitions.json"


def _read_transitions_file(path: Path) -> List[Dict[str, Any]]:
    """The raw rule list; ``[]`` when the file is absent or junk — no
    transition is a working state, a crash here would take every figure's
    animation with it."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("clip transitions %s unreadable, ignoring: %s", path, e)
        return []
    rules = data.get("transitions") if isinstance(data, dict) else data
    return rules if isinstance(rules, list) else []


#: Pose groups a rule may name as ``@<group>`` (server-side only: a pose key
#: never equals one, so the clients' table matching is unaffected).
_RULE_GROUPS = ("stand", "seat", "ground", "lie")


def _validate_transition_group(src: str, dst: str) -> None:
    """Place groups are server-side ENTRY targets (``walking -> @seat``) and
    EXIT sources (``@seat -> *``), never general pose wildcards."""
    if src.startswith("@"):
        if src[1:] not in _RULE_GROUPS:
            raise ClipLibraryError(f"unknown place group '{src}'")
        if dst != TRANSITION_ANY:
            raise ClipLibraryError(
                f"place group allowed only as 'to' from 'walking' or as 'from' to '{TRANSITION_ANY}'")
        return
    if dst.startswith("@"):
        if dst[1:] not in _RULE_GROUPS:
            raise ClipLibraryError(f"unknown place group '{dst}'")
        if src != "walking":
            raise ClipLibraryError("place group target requires from == 'walking'")


def normalize_rule_kind(raw: Any) -> Any:
    """One bridge kind or a map of role to bridge; decode world JSON columns."""
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            raw = json.loads(raw)
        except ValueError:
            return ""
    if isinstance(raw, dict):
        roles = {r: str(raw.get(r) or "").strip().lower() for r in raw}
        roles = {r: k for r, k in roles.items() if k}
        return roles or ""
    return str(raw or "").strip().lower()


def rule_kind(rule: Optional[Dict[str, Any]], role: str = "") -> str:
    """The bridge clip ``rule`` plays for clip role ``role`` ("" = none). A
    per-role rule answers only for a named role."""
    kind = (rule or {}).get("kind") or ""
    return kind.get(role, "") if isinstance(kind, dict) else str(kind)


def rule_kinds(rule: Dict[str, Any]) -> List[str]:
    """Every bridge clip ``rule`` names."""
    kind = rule.get("kind") or ""
    return [k for k in (kind.values() if isinstance(kind, dict) else [kind]) if k]


def load_shared_transitions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The transition rules as ``[{from, to, kind}]``, junk entries dropped.

    Order is the file's own — :func:`resolve_transition` decides by
    specificity, not by position, so a hand-edited file cannot become
    order-dependent behind the editor's back.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in _read_transitions_file(path or clip_transitions_path()):
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from") or "").strip().lower()
        dst = str(raw.get("to") or "").strip().lower()
        kind = normalize_rule_kind(raw.get("kind"))
        if not src or not dst or not kind:
            continue
        try:
            _validate_transition_group(src, dst)
        except ClipLibraryError as exc:
            logger.warning("clip transition ignored: %s", exc)
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        out.append({"from": src, "to": dst, "kind": kind,
                    "accel": _accel(raw.get("accel"))})
    return out


def world_transitions() -> List[Dict[str, Any]]:
    """Read world rules in insertion order; a not-yet-created table is empty."""
    import sqlite3
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT from_pose, to_pose, kind, accel FROM clip_transitions_world ORDER BY rowid"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return []
    return [{"from": src, "to": dst, "kind": normalize_rule_kind(kind), "accel": _accel(accel)}
            for src, dst, kind, accel in rows]


def _write_world_transitions(rules: List[Dict[str, Any]]) -> None:
    """Replace the whole layer atomically, preserving unavailable bridges."""
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute("DELETE FROM clip_transitions_world")
        conn.executemany(
            "INSERT INTO clip_transitions_world (from_pose, to_pose, kind, accel, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(r["from"], r["to"], json.dumps(r["kind"], sort_keys=True) if isinstance(r["kind"], dict)
              else r["kind"], r["accel"], now) for r in rules])


def replace_world_transitions(rules: Any) -> List[Dict[str, Any]]:
    """Validate and replace the entire world layer."""
    out = _validate_transitions(rules)
    _write_world_transitions(out)
    return out


def load_transitions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Full editor/storage table, including unavailable world bridges.

    Shared file order, world replacements in place, world-only rows last.
    Runtime callers use :func:`effective_transitions` for availability fallback.
    """
    world = {(r["from"], r["to"]): r for r in world_transitions()}
    out = []
    for rule in load_shared_transitions(path):
        replacement = world.pop((rule["from"], rule["to"]), None)
        out.append(dict(replacement if replacement is not None else rule,
                        store="world" if replacement is not None else "shared"))
    out.extend(dict(rule, store="world") for rule in world.values())
    return out


def effective_transitions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Runtime table: unavailable world bridges leave shared rules in place.

    World-only rules with unavailable kinds are dropped; shared rules are
    retained regardless of clip availability.
    """
    solo = _solo_kinds()
    shared = {(r["from"], r["to"]): r for r in load_shared_transitions(path)}
    out = []
    for rule in load_transitions(path):
        if rule.get("store", "shared") == "world" and any(k not in solo for k in rule_kinds(rule)):
            fallback = shared.get((rule["from"], rule["to"]))
            if fallback is not None:
                out.append(dict(fallback, store="shared"))
        else:
            out.append(rule)
    return out


def _accel(raw: Any) -> float:
    """How fast the figure gets up to speed WHILE the bridge plays, as a
    fraction of its normal speed gained per second.

    ``0`` — the default — means it never gains any: the figure stays put for
    the whole clip, which is what standing up out of a seat looks like. ``1``
    reaches full speed after a second, ``0.5`` after two. Anything above 8
    would be indistinguishable from an instant start and is capped there.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not value > 0:
        return 0.0
    return round(min(value, 8.0), 3)


def resolve_transition(from_pose: Any, to_pose: Any,
                       rules: Optional[List[Dict[str, Any]]] = None
                       ) -> Optional[Dict[str, Any]]:
    """The RULE that applies when a figure goes from ``from_pose`` to
    ``to_pose`` — ``None`` when nothing is configured.

    The whole rule, not just its clip: what happens during the bridge depends
    on ``accel`` as much as on ``kind``, and two lookups for one answer is how
    the two start to disagree.

    With no explicit rules, use the effective runtime table: unavailable
    world bridges fall back to shared rules. Explicit rules are used as given;
    :func:`load_transitions` retains the full table for editing and storage.

    Most specific rule wins, and the order is fixed rather than the file's:

    1. both named — the transition between exactly these two,
    2. ``from`` named, ``to`` the wildcard — the EXIT clip of a state
       ("standing up after sitting, whatever comes next"),
    3. ``to`` named, ``from`` the wildcard — the ENTER clip of a state.

    A switch onto the SAME pose is never a transition: a figure that keeps
    walking must not stand up first.
    """
    src = str(from_pose or "").strip().lower()
    dst = str(to_pose or "").strip().lower()
    if not src or not dst or src == dst:
        return None
    table = effective_transitions() if rules is None else rules
    exact = wild_to = wild_from = None
    for r in table:
        rs, rd = r.get("from", ""), r.get("to", "")
        if rs == src and rd == dst:
            exact = r
            break
        if rs == src and rd == TRANSITION_ANY and wild_to is None:
            wild_to = r
        elif rs == TRANSITION_ANY and rd == dst and wild_from is None:
            wild_from = r
    return exact or wild_to or wild_from


def resolve_pose_transition(from_pose: Any, to_pose: Any) -> Optional[Dict[str, Any]]:
    """``resolve_transition``, then the pose GROUP rules on the side that has
    no rule of its own: entering a pose falls back to ``walking → @<group>``
    (sit-down onto any seat pose), leaving one to ``@<group> → *`` (get up
    from any seat pose). The pose's own rule always wins."""
    rule = resolve_transition(from_pose, to_pose)
    if rule:
        return rule
    from app.core.pose_catalog import get_catalog
    catalog = get_catalog("pose")

    def group(pose: Any) -> str:
        name = (catalog.get(str(pose or "").strip().lower()) or {}).get("group")
        return "@" + name if name in _RULE_GROUPS else ""

    to_group, from_group = group(to_pose), group(from_pose)
    if to_group:
        rule = resolve_transition(from_pose, to_group)
    if not rule and from_group:
        rule = resolve_transition(from_group, to_pose)
    return rule


def save_transitions(entries: Any,
                     path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Validate both stores before writing the shared seed and whole world layer."""
    with keyed_lock("clip_library", "write"):
        if not isinstance(entries, list):
            raise ClipLibraryError("a list of {from, to, kind} is expected")
        shared, world = [], []
        seen = {"shared": set(), "world": set()}
        solo = _solo_kinds()
        free = {e["kind"] for root, source in get_animation_clips_dirs()
                if source == "free" and root.exists()
                for e in _scan_library(root, source) if not e["role"]}
        # Validate each row with its original position for useful editor errors.
        for i, raw in enumerate(entries):
            rule = _validate_transitions([raw], offset=i, solo=solo)[0]
            store = raw.get("store", "shared")
            if store not in ("shared", "world"):
                raise ClipLibraryError(f"rule {i + 1}: store must be shared or world")
            licensed = [k for k in rule_kinds(rule) if k not in free]
            if store == "shared" and licensed:
                raise ClipLibraryError(
                    f"rule {i + 1}: bridge clip {licensed[0]} is licensed — it belongs to the world layer")
            layer = shared if store == "shared" else world
            pair = (rule["from"], rule["to"])
            if pair in seen[store]:
                raise ClipLibraryError(
                    f"rule {i + 1}: '{rule['from']}' to '{rule['to']}' is already ruled")
            seen[store].add(pair)
            layer.append(rule)
        # The editor sends the EFFECTIVE list, where a world rule hides the shared
        # rule of its pair. That hidden shared rule is not being deleted — keep it
        # in the seed (in its place), or every save would strip it from the repo.
        for rule in load_shared_transitions(path):
            pair = (rule["from"], rule["to"])
            if pair in seen["world"] and pair not in seen["shared"]:
                seen["shared"].add(pair)
                shared.append(rule)
        order = {(r["from"], r["to"]): n for n, r in enumerate(load_shared_transitions(path))}
        shared.sort(key=lambda r: order.get((r["from"], r["to"]), len(order)))
        _write_world_transitions(world)
        _write_transitions(shared, path)
        result = load_transitions(path)
        notify_library_changed()
        return result


def _validate_transitions(entries: Any, offset: int = 0,
                          solo: Optional[set] = None) -> List[Dict[str, Any]]:
    """Validate one layer; bridges must be solo clips in either library."""
    if not isinstance(entries, list):
        raise ClipLibraryError("a list of {from, to, kind} is expected")
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, raw in enumerate(entries, start=offset):
        if not isinstance(raw, dict):
            raise ClipLibraryError(f"rule {i + 1}: an object is expected")
        src = str(raw.get("from") or "").strip().lower()
        dst = str(raw.get("to") or "").strip().lower()
        if not src or not dst:
            raise ClipLibraryError(f"rule {i + 1}: 'from' and 'to' are required")
        try:
            _validate_transition_group(src, dst)
        except ClipLibraryError as exc:
            raise ClipLibraryError(f"rule {i + 1}: {exc}") from exc
        if src == TRANSITION_ANY and dst == TRANSITION_ANY:
            raise ClipLibraryError(
                f"rule {i + 1}: '{TRANSITION_ANY}' on both sides would fire on "
                "every clip change — name at least one side")
        for side, value in (("from", src), ("to", dst)):
            if value != TRANSITION_ANY:
                if "/" in value or "*" in value:
                    raise ClipLibraryError(f"rule {i + 1}: invalid pose key on {side}")
        kind = normalize_rule_kind(raw.get("kind"))
        if isinstance(kind, dict):
            roles = transition_roles(src, dst)
            if not roles:
                raise ClipLibraryError(
                    f"rule {i + 1}: a bridge per role needs a pair pose or group pose on either side")
            if any(r not in roles for r in kind):
                raise ClipLibraryError(f"rule {i + 1}: invalid bridge role for pose")
            kind = {r: validate_kind(k) for r, k in kind.items()}
        else:
            kind = validate_kind(kind)
        if solo is None:
            solo = _solo_kinds()
        for one in (kind.values() if isinstance(kind, dict) else [kind]):
            if one not in solo:
                raise ClipLibraryError(
                    f"rule {i + 1}: no solo clip of kind '{one}' in any library")
        if (src, dst) in seen:
            raise ClipLibraryError(
                f"rule {i + 1}: '{src}' to '{dst}' is already ruled")
        seen.add((src, dst))
        out.append({"from": src, "to": dst, "kind": kind,
                    "accel": _accel(raw.get("accel"))})

    return out


def _write_transitions(entries: List[Dict[str, Any]], path: Optional[Path] = None) -> None:
    """Persist rules; reference maintenance must preserve unavailable bridges."""
    target = path or clip_transitions_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"transitions": entries}, indent=2,
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("clip transitions saved: %d rule(s)", len(entries))


def _pose_kind_maps() -> Tuple[Dict[str, str], Dict[str, str]]:
    """``(played, shipped)`` pose key → clip kind, each catalog read ONCE per
    listing (the shipped one is a file read, and every rule names two poses)."""
    from app.core.pose_catalog import get_catalog
    from app.core.pose_catalog_edit import read_store
    played = {k: str(v.get("animation") or "") for k, v in get_catalog("pose").items()}
    shipped = {k: str((v or {}).get("animation") or "")
               for k, v in read_store("pose", "shared")["entries"].items()}
    return played, shipped


def _transition_pairs(rule: Dict[str, Any], maps: Tuple[Dict[str, str], Dict[str, str]]):
    """The clip pairs a pose rule stands for: played kinds before shipped
    ones, a pose this world does not know gives none, ``*`` stays ``*``."""
    return [(src, dst) for src, dst, _role in _transition_triples(rule, maps)]


def pose_roles(pose: str) -> Tuple[str, ...]:
    """The roles present for a multi-person pose's clip across library sets."""
    from app.core.pose_catalog import get_catalog
    entry = get_catalog("pose").get(pose) or {}
    if entry.get("participants", 1) == 1:
        return ()
    kind = str(entry.get("animation") or "")
    if not kind:
        return ()
    roles = {e["role"] for e in clip_entries() if e["kind"] == kind and e["role"]}
    return tuple(r for r in CLIP_ROLES if r in roles) if roles else tuple(_meta_roles(clip_meta(kind)))


def transition_roles(src: str, dst: str) -> Tuple[str, ...]:
    """A bridge between multi-person poses can only connect matching roles."""
    left, right = pose_roles(src), pose_roles(dst)
    return tuple(r for r in left if r in right) if left and right else left or right


def _transition_triples(rule: Dict[str, Any], maps,
                        leaving: Optional[Dict[str, List[Tuple[str, str]]]] = None):
    """Expand both pose sides to played clip roles; X only connects to X."""
    played, shipped = maps

    def kinds(key):
        if key == TRANSITION_ANY:
            return [(TRANSITION_ANY, "")]
        own = list(dict.fromkeys(k for k in (played.get(key, ""), shipped.get(key, "")) if k))
        roles = pose_roles(key)
        return [(f"{k}{ROLE_SEPARATOR}{r}", r) for k in own for r in roles] if roles else [(k, "") for k in own]

    sources = kinds(rule["from"])
    if leaving and rule["from"] in leaving:
        sources = list(dict.fromkeys(leaving[rule["from"]]))
    return [(src, dst, sr or dr) for src, sr in sources
            for dst, dr in kinds(rule["to"])
            if src != dst and (not sr or not dr or sr == dr)]


def _leaving_kinds(rules: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, str]]]:
    """``{pose: [(clip, role), …]}`` for the ``from`` poses of ``rules`` that
    play more than their own kind: a pair pose's halves (and its finale's),
    a solo pose's own kind plus its finale. Only poses the rules name."""
    from app.core.pose_catalog import get_catalog
    catalog = get_catalog("pose")
    out: Dict[str, List[Tuple[str, str]]] = {}
    for key in {r["from"] for r in rules}:
        entry = catalog.get(key)
        if not entry or not entry.get("animation"):
            continue
        finale = entry.get("finale_animation") or ""
        if not finale:
            try:
                from app.core.prop_action_engine import auto_finale
                finale = auto_finale(key, entry)
            except Exception:
                finale = ""
        own = [entry["animation"]] + ([finale] if finale and finale != entry["animation"] else [])
        if entry.get("participants", 1) == 1:
            if finale:
                out[key] = [(kind, "") for kind in own]
        else:
            out[key] = [(f"{kind}{ROLE_SEPARATOR}{role}", role) for kind in own for role in pose_roles(key)]
    return out


def client_transition_rules(rules=None) -> List[Dict[str, Any]]:
    """The pose rules translated into the CLIP rules the 3D client switches
    by (it knows clip kinds, not poses); the first rule to occupy a clip
    pair keeps it. A rule out of a multi-person pose names its halves as ``from``
    (the clients play ``<kind>__<role>``), each with the bridge of its role
    (``rule_kind``); a half without one is left out."""
    maps = _pose_kind_maps()
    table = effective_transitions() if rules is None else rules
    leaving = _leaving_kinds(table)
    out = []
    seen = set()
    for rule in table:
        for src, dst, role in _transition_triples(rule, maps, leaving):
            kind = rule_kind(rule, role) if role else rule_kind(rule)
            if not kind or (src, dst) in seen:
                continue
            seen.add((src, dst))
            out.append({"from": src, "to": dst, "kind": kind,
                        "accel": _accel(rule.get("accel"))})
    return out


def annotated_transitions(rules=None) -> List[Dict[str, Any]]:
    """The pose rules as the editor shows them: each side's played and
    shipped clip kind, whether the bridge clip exists in the FREE library
    (``bridge_public``) and whether an earlier rule already occupies one of
    its clip pairs (``conflict``)."""
    maps = _pose_kind_maps()
    played, shipped = maps
    free = {e["kind"] for root, source in get_animation_clips_dirs()
            if source == "free" and root.exists()
            for e in _scan_library(root, source) if not e["role"]}
    out = []
    seen = set()
    for rule in load_transitions() if rules is None else rules:
        pairs = _transition_pairs(rule, maps)
        row = dict(rule, store=rule.get("store", "shared"))
        for side in ("from", "to"):
            key = rule[side]
            row[side + "_kind"] = TRANSITION_ANY if key == TRANSITION_ANY else played.get(key, "")
            row[side + "_public_kind"] = (TRANSITION_ANY if key == TRANSITION_ANY
                                          else shipped.get(key, ""))
        row["bridge_public"] = all(k in free for k in rule_kinds(rule))
        row["conflict"] = any(pair in seen for pair in pairs)
        seen.update(pairs)
        out.append(row)
    return out


def rename_transition_pose(old: str, new: str) -> int:
    """Rename references in both layers, counting even hidden shared rules."""
    count = 0
    for rules, write in ((load_shared_transitions(), _write_transitions),
                         (world_transitions(), _write_world_transitions)):
        changed = 0
        for rule in rules:
            if old in (rule["from"], rule["to"]):
                changed += 1
                for side in ("from", "to"):
                    if rule[side] == old:
                        rule[side] = new
        if changed:
            write(rules)
        count += changed
    return count


def drop_transition_pose(key: str) -> int:
    """Remove references from both layers, including hidden shared rules."""
    count = 0
    for rules, write in ((load_shared_transitions(), _write_transitions),
                         (world_transitions(), _write_world_transitions)):
        kept = [r for r in rules if key not in (r["from"], r["to"])]
        removed = len(rules) - len(kept)
        if removed:
            write(kept)
        count += removed
    return count


# ── The library view: one clip as the listing (and the editor) sees it ────

def _origin(meta: Optional[Dict[str, Any]]) -> str:
    """Where the clip came from, in one word: ``cmu`` for a CMU-derived take,
    the generator (``unimate``, ``kimodo``, …) for a clip generated for a
    pose, ``studio`` for a clip the animation studio wrote as code
    (``source.format`` ``procedural``), otherwise the skeleton family
    the FBX import retargeted from
    (``unity-humanoid``, …), ``unknown`` without a sidecar."""
    src = (meta or {}).get("source")
    if not isinstance(src, dict):
        return "unknown"
    if src.get("format") == "procedural":
        return "studio"
    if src.get("generated_for_pose") and src.get("generator"):
        return str(src["generator"])
    database = str(src.get("database") or "")
    if "CMU" in database:
        return "cmu"
    return str(src.get("bone_map") or "") or "unknown"


def clip_loops(meta: Optional[Dict[str, Any]]) -> bool:
    """Does this clip REPEAT, or does it hold its last frame?

    The sidecar's own ``loop`` is the answer whenever it is there — including
    an explicit ``false`` against the ``geometry.loop`` the import measured:
    that flag is the ADMIN's decision, taken after the import in the Poses
    tab (plan-animationen-echtzeit-stehplatz.md E5), and a measurement must
    never overrule it. Only without it does the import's own finding count.
    """
    if not isinstance(meta, dict):
        return False
    if "loop" in meta:
        return bool(meta["loop"])
    geometry = meta.get("geometry")
    return bool(isinstance(geometry, dict) and geometry.get("loop"))


#: The largest repeat count a looped clip may carry (``loop_count``).
LOOP_COUNT_MAX = 99


def valid_loop_count(raw: Any) -> Optional[int]:
    """``raw`` as a repeat count — an integer 1..``LOOP_COUNT_MAX`` — or None
    (``None`` itself = endless). Anything else raises ``ClipLibraryError``:
    a bool, a float, a string, 0, 100."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ClipLibraryError("loop_count must be a whole number or null")
    if not 1 <= raw <= LOOP_COUNT_MAX:
        raise ClipLibraryError(f"loop_count must lie between 1 and {LOOP_COUNT_MAX}")
    return raw


def clip_loop_count(meta: Optional[Dict[str, Any]]) -> Optional[int]:
    """How many cycles a LOOPED clip plays before it holds its last frame:
    the sidecar's ``loop_count`` (1..``LOOP_COUNT_MAX``), None = endless.

    Only a clip that loops (:func:`clip_loops`) has a count — a one-shot
    plays once whatever its sidecar says, and a stored count that is not a
    valid one counts as none (endless), never as a guess."""
    if not clip_loops(meta):
        return None
    try:
        return valid_loop_count((meta or {}).get("loop_count"))
    except ClipLibraryError:
        return None


def clip_play_s(meta: Optional[Dict[str, Any]]) -> Optional[float]:
    """How long the clip plays before it holds its last frame, in seconds:
    its ``duration_s`` for a one-shot, ``duration_s × loop_count`` for a
    counted loop, None for an endless loop or a sidecar without a length."""
    try:
        duration = float((meta or {}).get("duration_s") or 0)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(duration) and duration > 0):
        return None
    if not clip_loops(meta):
        return duration
    count = clip_loop_count(meta)
    return duration * count if count else None


#: The genders a role can be assigned to — the two the profile field
#: ``gender`` names unambiguously (the same pair ``animation_sets`` derives).
ROLE_GENDERS = ("male", "female")


def _meta_roles(meta: Optional[Dict[str, Any]]) -> List[str]:
    """The role letters a sidecar names (``roles``), ``a``/``b`` for an old
    pair sidecar without the list."""
    raw = (meta or {}).get("roles") if isinstance(meta, dict) else None
    roles = [r for r in (raw or []) if r in CLIP_ROLES] if isinstance(raw, list) else []
    return roles or list(CLIP_ROLES[:2])


def clip_role_gender(meta: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Which gender plays which role of a pair or group clip:
    ``{"a": …, "b": …[, "c": …]}``.

    Written by the import from the take names, or by the admin in the Poses
    tab (``set_clip_role_gender``). Only a complete assignment counts —
    every role of the sidecar's ``roles`` male or female, and not all the
    same (a pair: one man, one woman) — anything else (no key, a role
    missing, an unknown word) is ``{}``: not assigned, and the initiator
    plays role A.
    """
    raw = (meta or {}).get("role_gender") if isinstance(meta, dict) else None
    if not isinstance(raw, dict):
        return {}
    out = {r: str(raw.get(r) or "").strip().lower() for r in _meta_roles(meta)}
    if all(g in ROLE_GENDERS for g in out.values()) and len(set(out.values())) > 1:
        return out
    return {}


def clip_root_motion(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The sidecar's ``geometry.root_motion`` block, or None (pairs, clips
    without sidecar)."""
    geo = (meta or {}).get("geometry")
    rm = geo.get("root_motion") if isinstance(geo, dict) else None
    return rm if isinstance(rm, dict) and rm.get("mode") in ROOT_MOTION_MODES else None


def clip_travel_m(kind: str, cset: str = "") -> Tuple[float, float]:
    """How far a clip carries its figure, clip frame (+Z forward, +X the
    figure's left), metres of the REFERENCE rig — (0, 0) for a clip that
    stays on the spot."""
    rm = clip_root_motion(clip_meta(kind, cset))
    if not rm or rm["mode"] == "strip":
        return (0.0, 0.0)
    try:
        x, z = (float(v) for v in rm.get("travel_m") or (0, 0))
    except (TypeError, ValueError):
        return (0.0, 0.0)
    return (x, z) if math.isfinite(x) and math.isfinite(z) else (0.0, 0.0)


def clip_turn_deg(kind: str, cset: str = "") -> float:
    """Measured pelvis turn, three.js yaw degrees — only for a ``foot_lock``
    clip, the one mode whose turn both clients take out of the hips and apply
    to the figure's root (native ``TemplateClips`` relocks with
    ``turn: !KeepFacing``; a ``keep`` clip keeps its turn inside the pose and
    the root keeps facing the seat). Zero for every other mode or unknown."""
    rm = clip_root_motion(clip_meta(kind, cset))
    if not rm or rm["mode"] != "foot_lock":
        return 0.0
    try:
        value = float(rm.get("turn_deg"))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def clip_ref_height_m(kind: str, cset: str = "") -> Optional[float]:
    """The standing height of the reference rig the travel was measured on,
    in metres — what ``clip_travel_m`` is scaled by for a taller or shorter
    figure. None when the sidecar does not say."""
    rm = clip_root_motion(clip_meta(kind, cset))
    try:
        v = float((rm or {}).get("ref_height_m"))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def clip_height_offsets(meta: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Read only finite, non-zero surface corrections from a sidecar."""
    raw = (meta or {}).get("height_offsets_cm")
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items()
            if key in HEIGHT_OFFSET_SURFACES
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and -50 <= value <= 50 and value != 0}


def validate_height_offsets(raw: Any) -> Dict[str, float]:
    """Validate a partial height patch completely before any library mutation."""
    if not isinstance(raw, dict):
        raise ClipLibraryError("height_offsets_cm must be an object")
    for key, value in raw.items():
        if key not in HEIGHT_OFFSET_SURFACES:
            raise ClipLibraryError(
                "height_offsets_cm keys must be ground, seat or lie")
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not -50 <= value <= 50):
            raise ClipLibraryError(
                f"height_offsets_cm.{key} must be a finite number from -50 to 50")
    return dict(raw)


def _height_meta(path: Path, kind: str, root: Path,
                 *, pair: bool = False) -> Optional[Dict[str, Any]]:
    """Resolve heights within the actual file's library, never another winner.

    A pair's shared sidecar is authoritative for both halves. Solo variants
    prefer their own sidecar, with the same set/root fallback as clip_meta.
    """
    names = [kind] if pair else list(dict.fromkeys((path.stem, kind)))
    for name in names:
        for directory in dict.fromkeys((path.parent, root)):
            sidecar = directory / f"{name}.json"
            if sidecar.is_file():
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
                return data if isinstance(data, dict) else None
    return None


def clip_view(entry: Dict[str, Any]) -> Dict[str, Any]:
    """One ``clip_entries()`` entry as the API delivers it — the file facts
    plus what its sidecar knows.

    The sidecar is looked up exactly the way playback looks it up
    (``clip_meta``: ``<stem>.json`` before the shared ``<kind>.json``, set
    directory before the library root, licensed before free), so a numbered
    variant reports its OWN numbers when it has a sidecar and those of its
    kind otherwise. Without any sidecar the numeric fields are ``None`` —
    that is a normal state, not an error.
    """
    path: Path = entry["path"]
    meta = clip_meta(entry["kind"], entry["set"], stem=path.stem)
    geometry = (meta or {}).get("geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    try:
        shift_meta = json.loads(_orient_sidecar(path, entry["kind"], bool(entry["role"])).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shift_meta = {}
    if not isinstance(shift_meta, dict):
        shift_meta = {}
    shift_geometry = (shift_meta or {}).get("geometry") or {}
    horizontal = read_clip_shift(shift_geometry.get("shift_cm") if isinstance(shift_geometry, dict) else None)
    rm = clip_root_motion(meta)
    source = (meta or {}).get("source")
    source = source if isinstance(source, dict) else {}
    return {
        "kind": entry["kind"],
        "role": entry["role"],
        "set": entry["set"],
        "source": entry["source"],
        "library": entry["source"],
        "rel": entry["rel"],
        "name": path.stem,
        "filename": path.name,
        # Percent-encoded PER SEGMENT: clip file names are free text and do
        # contain spaces ("standing wash-self.fbx"), so the raw rel is not a
        # usable URL. Clients take this string as it is — they never encode
        # it a second time and never rebuild it from name + set.
        "url": "/assets/animation-clips/"
               + ("licensed/" if entry["source"] == "licensed" else "")
               + "/".join(quote(seg) for seg in entry["rel"].split("/"))
               + f"?v={content_version(path)}",
        "size": path.stat().st_size,
        "has_sidecar": meta is not None,
        "origin": _origin(meta),
        "generator": str(source.get("generator") or ""),
        "license": str((meta or {}).get("license") or ""),
        "duration_s": (meta or {}).get("duration_s"),
        "fps": (meta or {}).get("fps"),
        "frames": (meta or {}).get("frames"),
        "loop": clip_loops(meta),
        # How many cycles a looped clip plays before it holds its last frame;
        # None = endless (and always None for a one-shot).
        "loop_count": clip_loop_count(meta),
        "height_offsets_cm": clip_height_offsets(_height_meta(
            path, entry["kind"], library_root(entry["source"]).resolve(),
            pair=bool(entry["role"]))),
        # Which gender plays which role — pair/group halves only, {} = not assigned.
        "role_gender": clip_role_gender(meta) if entry["role"] else {},
        # Saved orientation and renderer calibration. Angles and partner B
        # offsets are baked; the whole-clip shift is applied at placement.
        "orientation": {k: geometry.get(k) for k in
                        ORIENT_ANGLES + ("floor_shift_cm", "partner_shift_cm", "role_shift_cm")
                        } | {"shift_cm": horizontal},
        # How the import treated the root's travel, and where the clip ends
        # up (clip frame, metres) — None for a pair or a clip without block.
        "root_motion": ({"mode": rm["mode"], "travel_m": rm.get("travel_m")}
                        if rm else None),
    }


# ── Editing the libraries: delete, rename, move ──────────────────────────

def library_root(library: str) -> Path:
    """The directory of ``free`` / ``licensed``; anything else is an error."""
    lib = str(library or "").strip().lower()
    if lib == "free":
        return get_animation_clips_dir()
    if lib == "licensed":
        return get_licensed_clips_dir()
    raise ClipLibraryError(f"unknown library '{library}' (free|licensed)")


def resolve_clip(library: str, rel: str) -> Path:
    """``[<set>/]<file>`` inside one library → the file path.

    The same hardening as the serving route: at most one set segment, no empty
    segment, no ``.``/``..``, no backslash, only clip extensions, and the
    resolved path must stay inside the library (``resolve()`` on both sides,
    so a symlink pointing out is refused too). The file need not exist —
    that is the caller's 404.
    """
    base = library_root(library)
    segments = str(rel or "").split("/")
    if not 1 <= len(segments) <= 2:
        raise ClipLibraryError("path must be [<set>/]<file>")
    for seg in segments:
        if not seg or seg in (".", "..") or "\\" in seg:
            raise ClipLibraryError("invalid path segment")
    base = base.resolve()
    path = base.joinpath(*segments).resolve()
    if not path.is_relative_to(base):
        raise ClipLibraryError("path escapes the library")
    if path.suffix.lower() not in CLIP_EXTS:
        raise ClipLibraryError(f"not a clip file ({', '.join(CLIP_EXTS)})")
    return path


def _split_stem(stem: str) -> Tuple[str, str, str]:
    """``(kind, role, numbering)`` of a file stem — ``hug__a_02`` →
    ``("hug", "a", "_02")``. The three parts a rename recombines; an alt
    half's role carries its alt (``hug__b~wave`` → ``("hug", "b~wave", "")``)."""
    m = _STEM_RE.match(stem.strip().lower())
    if not m:                                                # pragma: no cover
        return stem.strip().lower(), "", ""
    return m.group("kind") or stem, m.group("role") or "", m.group("num") or ""


def _role_siblings(path: Path) -> List[Path]:
    """The other role files of a pair or group clip (``kiss__a`` → ``kiss__b``;
    ``x__b`` → ``x__a``, ``x__c``), in role order; ``[]`` for a solo clip.
    Only files that exist."""
    kind, role, num = _split_stem(path.stem)
    role = role.split(ALT_SEPARATOR)[0]
    if not role:
        return []
    out = []
    for other in CLIP_ROLES:
        if other == role:
            continue
        sibling = path.with_name(f"{kind}{ROLE_SEPARATOR}{other}{num}{path.suffix}")
        if sibling.is_file():
            out.append(sibling)
    return out


def _kind_files(directory: Path, kind: str) -> List[Path]:
    """Every clip file of one kind still lying in one directory — the numbered
    variants and both pair halves. Asked AFTER a delete or a move, so what it
    returns is what still needs the shared ``<kind>.json``."""
    if not directory.is_dir():
        return []
    return [p for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix.lower() in CLIP_EXTS
            and parse_clip_role(p.name)[0] == kind]


def _alt_files(path: Path) -> List[Path]:
    """The ALT halves of the pair or group clip ``path`` belongs to, in the
    same directory — they move, turn and go with the scene's own halves.
    ``[]`` for a solo clip."""
    kind, role = parse_clip_role(path.name)
    if not role:
        return []
    return [p for p in _kind_files(path.parent, kind) if parse_clip_alt(p.name)]


def finale_kinds_of(kind: str) -> List[str]:
    """The finale clip kinds of the poses that play ``kind``: a pose's own
    ``finale_animation``, else what a package derives for it
    (``prop_action_engine.auto_finale``). Unchecked against the files."""
    from app.core.pose_catalog import get_catalog
    from app.core.prop_action_engine import auto_finale
    out: List[str] = []
    for key, entry in get_catalog("pose").items():
        if (entry or {}).get("animation") != kind:
            continue
        finale = (entry.get("finale_animation") or auto_finale(key, entry) or "").strip().lower()
        if finale and finale != kind and finale not in out:
            out.append(finale)
    return out


def _finale_files(path: Path) -> List[Path]:
    """The finale clips that follow ``path``'s orientation and heights: those
    of :func:`finale_kinds_of` lying in the same directory (library and set)
    in the same shape — a pair's finale is a pair, one file names all its
    roles; a solo clip's finale variants each. ``[]`` when the pose catalog
    cannot be read (no world): the clip itself is still edited."""
    kind, role = parse_clip_role(path.name)
    try:
        finales = finale_kinds_of(kind)
    except Exception as e:  # noqa: BLE001 — a missing catalog must not block the edit
        logger.warning("finale clips of %s not looked up: %s", kind, e)
        return []
    roles = len(_role_siblings(path)) + 1 if role else 0
    out: List[Path] = []
    for finale in finales:
        files = _kind_files(path.parent, finale)
        if role:
            first = next((f for f in files if parse_clip_role(f.name)[1] == "a"
                          and not parse_clip_alt(f.name)), None)
            if first is not None and len(_role_siblings(first)) + 1 == roles:
                out.append(first)
        else:
            out.extend(f for f in files if not parse_clip_role(f.name)[1])
    return out


def _rel_in(path: Path, library: str) -> str:
    """``[<set>/]<file>`` of a file inside one library."""
    return path.resolve().relative_to(library_root(library).resolve()).as_posix()


def _own_sidecar(path: Path) -> Optional[Path]:
    """The sidecar belonging to THIS file alone — ``walk_02.json`` next to
    ``walk_02.fbx``. None when the stem IS the kind (then the sidecar is the
    shared ``<kind>.json``, which the kind rules own) or when there is none."""
    if path.stem.strip().lower() == parse_clip_role(path.name)[0]:
        return None
    sidecar = path.with_suffix(".json")
    return sidecar if sidecar.is_file() else None


def validate_kind(raw: Any) -> str:
    """The normalised kind (stripped, lowercased) or ClipLibraryError — the
    ONE rule every name that becomes a clip file stem goes through (library
    renames/imports and the animation studio's publish)."""
    kind = str(raw or "").strip().lower()
    if ROLE_SEPARATOR in kind:
        raise ClipLibraryError(
            f"kind must not contain '{ROLE_SEPARATOR}' (the pair role separator)")
    if _NUM_SUFFIX_RE.search(kind):
        # A kind ending in _<n> would be parsed back as the kind without it:
        # renaming to "walk_02" produces "walk_02.fbx", which the layout reads
        # as the second variant of "walk". The numbering is not nameable.
        raise ClipLibraryError(
            "kind must not end in '_<number>' — that suffix is the numbering "
            "of several clips of one kind, not part of the kind itself")
    if not KIND_RE.match(kind):
        raise ClipLibraryError(
            "kind must be lowercase letters, digits, space, '-' or '_'")
    return kind


def _validate_set(raw: Any) -> str:
    cset = str(raw or "").strip().lower()
    if not cset:
        return ""                                    # the neutral root
    if not SET_RE.match(cset):
        raise ClipLibraryError(
            "set must be lowercase letters, digits, '-' or '_'")
    return cset


def reload_clip_caches() -> None:
    """Re-read what caches the clip vocabulary: the clip entry cache and the
    preset caches the pose dropdown and the animation-set fallback read from —
    an edited library has to be visible at once, not after a restart (the
    clip imports call this too). ``reload_presets`` already reloads the pose
    catalogs, so they are not cleared a second time here."""
    _clear_entries_cache()
    try:
        from app.core import expression_pose_maps as epm
        epm.reload_presets()
    except Exception as e:                                   # pragma: no cover
        logger.warning("preset reload after clip library change failed: %s", e)
    notify_library_changed()


def library_write_lock(destination: Path):
    """Serialize library writes; staging and previews do not mutate a library.

    Lock order: clip_library/write BEFORE any pose catalog transaction.
    The shared RLock also permits nested library writers on the same thread.
    """
    destination = Path(destination).resolve()
    if any(destination.is_relative_to(Path(root).resolve())
           for root in (get_animation_clips_dir(), get_licensed_clips_dir())):
        return keyed_lock("clip_library", "write")
    return nullcontext()


def _library_writer(fn):
    @wraps(fn)
    def write(*args, **kwargs):
        with keyed_lock("clip_library", "write"):
            return fn(*args, **kwargs)
    return write


@_library_writer
def delete_clip(library: str, rel: str) -> Dict[str, Any]:
    """Removes one clip from one library — every role file of a pair or group.

    A sidecar that belongs to THIS file alone (``walk_02.json`` next to
    ``walk_02.fbx``) goes with it. The shared ``<kind>.json`` goes only when NO
    file of that kind is left in the same directory: numbered variants without
    an own sidecar share it, and the last one takes it along. A set directory
    that lost its last file is no set any more and is removed with it (never a
    library root).
    """
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    kind, _role = parse_clip_role(path.name)
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""

    targets = [path] + _role_siblings(path) + _alt_files(path)
    sidecars_removed = []
    for p in targets:
        own = _own_sidecar(p)
        p.unlink(missing_ok=True)
        if own is not None:
            own.unlink(missing_ok=True)
            sidecars_removed.append(own.name)

    sidecar = path.parent / f"{kind}.json"
    sidecar_removed = False
    if sidecar.is_file() and not _kind_files(path.parent, kind):
        sidecar.unlink(missing_ok=True)
        sidecar_removed = True
        sidecars_removed.append(sidecar.name)

    if cset and path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()

    reload_clip_caches()
    deleted = sorted(f"{cset}/{p.name}" if cset else p.name for p in targets)
    logger.info("clip deleted: %s (%s library)", ", ".join(deleted), library)
    return {"deleted": deleted, "kind": kind, "set": cset, "library": library,
            "sidecar_removed": sidecar_removed,
            "sidecars_removed": sorted(sidecars_removed)}


@_library_writer
def rename_clip(library: str, rel: str, *, kind: Optional[str] = None,
                cset: Optional[str] = None,
                to_library: Optional[str] = None,
                overwrite: bool = False) -> List[Dict[str, Any]]:
    """Renames a clip and/or moves it to another set or library.

    A pair or group moves whole (every role file), a numbered variant keeps its
    ``_<n>``. The sidecars follow: one belonging to a single file
    (``walk_02.json``) travels with that file and is renamed with it, the
    shared ``<kind>.json`` MOVES when nothing of the old kind stays behind and
    is COPIED when other variants still need it. The ``kind`` field is
    rewritten with the new name in both cases. An existing sidecar at the
    target is left untouched — it belongs to the variants already there.

    A name already taken at the target is a ``ClipExists`` — unless
    ``overwrite`` says the admin answered the question with "Replace": then
    the file lying there is deleted before the move, together with the sidecar
    belonging to it ALONE, for every role file alike (``_clear_replaced``).

    Returns the moved clips as listing views.
    """
    src = resolve_clip(library, rel)
    if not src.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    src_root = library_root(library).resolve()
    old_set = src.parent.name if src.parent.resolve() != src_root else ""
    old_kind, _role, _num = _split_stem(src.stem)

    new_kind = validate_kind(kind) if kind is not None else old_kind
    new_set = _validate_set(cset) if cset is not None else old_set
    new_library = str(to_library or library).strip().lower()
    if new_library not in LIBRARIES:
        raise ClipLibraryError(f"unknown library '{to_library}' (free|licensed)")

    dest_dir = library_root(new_library).resolve() / new_set if new_set \
        else library_root(new_library).resolve()

    sources = [src] + _role_siblings(src) + _alt_files(src)

    moves: List[Tuple[Path, Path]] = []
    replaced: List[Path] = []
    for p in sources:
        _k, role, num = _split_stem(p.stem)
        name = new_kind + (f"{ROLE_SEPARATOR}{role}" if role else "") + num + p.suffix
        dest = dest_dir / name
        if dest.resolve() == p.resolve():
            continue                                  # nothing to do for this half
        if dest.exists():
            if not overwrite:
                raise ClipExists(
                    f"{new_set + '/' if new_set else ''}{name} already exists "
                    f"in the {new_library} library")
            replaced.append(dest)
        moves.append((p, dest))
    if not moves:
        return [_view_of(src, new_set, new_library)]        # nothing changed

    dest_dir.mkdir(parents=True, exist_ok=True)
    if replaced:
        gone = _clear_replaced(replaced, dest_dir, new_kind)
        logger.info("clip replaced at the target: %s (%s%s, %s library)",
                    ", ".join(gone), f"{new_set}/" if new_set else "",
                    new_kind, new_library)
    # A pair always depends on its shared metadata (geometry and heights),
    # even when both halves also carry sidecars of their own. Solo variants
    # with own sidecars do not need to drag the shared kind sidecar along.
    needs_shared = bool(_role)
    for source, dest in moves:
        own = _own_sidecar(source)
        needs_shared = needs_shared or own is None
        fd, name = tempfile.mkstemp(dir=dest.parent, suffix=".clip-tmp")
        os.close(fd)
        stage = Path(name)
        try:
            shutil.copy2(source, stage)
            atomic_replace(stage, dest)
            source.unlink()
        finally:
            stage.unlink(missing_ok=True)
        if own is not None:
            _take_own_sidecar(own, dest.with_suffix(".json"), new_kind)

    _move_sidecar(src.parent, old_kind, dest_dir, new_kind, needed=needs_shared)

    # A set directory that lost its last file is no set any more.
    if old_set and src.parent.is_dir() and not any(src.parent.iterdir()):
        src.parent.rmdir()

    reload_clip_caches()
    logger.info("clip renamed: %s%s (%s) -> %s%s (%s)",
                f"{old_set}/" if old_set else "", old_kind, library,
                f"{new_set}/" if new_set else "", new_kind, new_library)
    return [_view_of(dest, new_set, new_library) for _s, dest in moves]


def _write_kind_flag(library: str, rel: str, what: str, mutate) -> List[Dict[str, Any]]:
    """Applies ``mutate(data)`` to the shared ``<kind>.json`` of the clip at
    ``rel`` and to every variant's OWN sidecar of that kind in that set —
    the playback flags belong to the KIND in its set, not to a single file.
    ``what`` names the flag in the error. Returns the touched clips as
    listing views."""
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    kind, _role = parse_clip_role(path.name)
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""
    sidecar = path.parent / f"{kind}.json"
    if not sidecar.is_file():
        raise ClipLibraryError(
            f"'{kind}' has no sidecar {sidecar.name} — the {what} is stored "
            "there, so the clip has to be (re-)imported first")
    files = _kind_files(path.parent, kind)
    targets = [sidecar] + [s for s in (_own_sidecar(p) for p in files)
                           if s is not None]
    for target in targets:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ClipLibraryError(f"{target.name} is not readable: {e}")
        if not isinstance(data, dict):
            raise ClipLibraryError(f"{target.name} is not an object")
        mutate(data)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    reload_clip_caches()
    return [_view_of(p, cset, library) for p in files]


@_library_writer
def set_clip_loop(library: str, rel: str, loop: bool) -> List[Dict[str, Any]]:
    """Writes the LOOP flag of a clip — the admin's decision after the import
    (E5): loop = repeat the clip, no loop = hold its last frame.

    The flag belongs to the KIND in its set, not to a single file: it is
    written into the shared ``<kind>.json`` beside the clip, so both halves of
    a pair (``hug__a`` / ``hug__b``) and every numbered variant of the kind
    play the same way. A variant carrying a sidecar of its OWN is written too
    — otherwise it would be the one file in the set that ignores the switch.

    Without a shared sidecar there is nowhere to put it: a clip whose numbers
    were never written cannot be given a flag (``ClipLibraryError``). Returns
    the touched clips as listing views.
    """
    views = _write_kind_flag(library, rel, "loop flag",
                             lambda data: data.__setitem__("loop", bool(loop)))
    logger.info("clip loop flag: %s (%s) -> %s", rel, library, bool(loop))
    return views


@_library_writer
def set_clip_loop_count(library: str, rel: str, loop_count: Any) -> List[Dict[str, Any]]:
    """Writes how many cycles a LOOPED clip plays before it holds its last
    frame (``loop_count``, 1..``LOOP_COUNT_MAX``); ``None`` removes the
    count — the loop is endless again. Same place and reach as the loop flag
    (:func:`set_clip_loop`): the shared ``<kind>.json`` and every variant's
    own sidecar. A count on a clip without loop is stored but has no effect
    (:func:`clip_loop_count`) — it comes back with the loop switch.
    ``ClipLibraryError`` for anything but an integer in range or None."""
    count = valid_loop_count(loop_count)

    def mutate(data: Dict[str, Any]) -> None:
        if count is None:
            data.pop("loop_count", None)
        else:
            data["loop_count"] = count

    views = _write_kind_flag(library, rel, "repeat count", mutate)
    logger.info("clip loop count: %s (%s) -> %s", rel, library,
                count if count is not None else "endless")
    return views


@_library_writer
def set_clip_role_gender(library: str, rel: str,
                         role_gender: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Writes which gender plays which role of a PAIR or GROUP clip.

    ``role_gender`` is ``{"a": "male", "b": "female"}`` (or the other way
    round; a group names every role of its sidecar's ``roles``); ``None`` /
    ``{}`` removes the assignment, so the initiator plays role A again. Like
    the loop flag it belongs to the KIND in its set and lives in the shared
    ``<kind>.json`` — every role file reads the same answer.

    Refused (``ClipLibraryError``): a solo clip (it has no roles), a kind
    without a shared sidecar, and an incomplete assignment (a role missing,
    an unknown word, everybody the same gender — see ``clip_role_gender``).
    Returns the touched clips as listing views.
    """
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    kind, role = parse_clip_role(path.name)
    if not role:
        raise ClipLibraryError(
            f"'{kind}' is a solo clip — only the halves of a pair have roles")
    if role_gender and not isinstance(role_gender, dict):
        raise ClipLibraryError("role_gender must be an object {a, b, …}")
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""
    sidecar = path.parent / f"{kind}.json"
    if not sidecar.is_file():
        raise ClipLibraryError(
            f"'{kind}' has no sidecar {sidecar.name} — the roles are stored "
            "there, so the clip has to be (re-)imported first")
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ClipLibraryError(f"{sidecar.name} is not readable: {e}")
    if not isinstance(data, dict):
        raise ClipLibraryError(f"{sidecar.name} is not an object")
    value: Dict[str, str] = {}
    if role_gender:
        value = clip_role_gender({**data, "role_gender": role_gender})
        if not value:
            raise ClipLibraryError(
                "role_gender needs every role ("
                + ", ".join(_meta_roles(data)) + ") male or female, not all the same")
    if value:
        data["role_gender"] = value
    else:
        data.pop("role_gender", None)
    sidecar.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    reload_clip_caches()
    logger.info("clip role genders: %s%s (%s) -> %s", f"{cset}/" if cset else "",
                kind, library, value or "not assigned")
    return [_view_of(p, cset, library) for p in _kind_files(path.parent, kind)]


@_library_writer
def set_clip_height_offsets(library: str, rel: str,
                            height_offsets_cm: Any, *,
                            with_finales: bool = True) -> List[Dict[str, Any]]:
    """Merge absolute per-surface corrections without touching animation bytes.

    ``with_finales``: the same corrections go to the clip's finale clips
    (:func:`_finale_files`) — a finale that starts at another height jumps.

    Solo variants use their own sidecar when present, otherwise the shared
    kind sidecar. Inheriting a root variant sidecar creates a local own
    sidecar, so the write wins the same lookup without touching siblings.
    Every role file of a pair or group uses the shared map; existing role sidecars receive it
    too. All input and sidecar reads are validated before writing. Zero
    removes only the addressed key.
    """
    patch = validate_height_offsets(height_offsets_cm)
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    root = library_root(library).resolve()
    kind, role = parse_clip_role(path.name)
    cset = path.parent.name if path.parent != root else ""
    files = [path] + _role_siblings(path)
    sidecar = _orient_sidecar(path, kind, bool(role))
    # An exact-stem sidecar (including original filename case) wins the
    # lookup. Write its local owner, or materialize a root-inherited variant.
    if (not role and path.stem != kind
            and (path.with_suffix(".json").is_file()
                 or (root / f"{path.stem}.json").is_file())):
        sidecar = path.with_suffix(".json")
    targets = [sidecar]
    if role:
        targets.extend(s for s in (_own_sidecar(p) for p in files)
                       if s is not None and s != sidecar)
    inherited = _height_meta(path, kind, root, pair=bool(role)) or {}
    corrections = clip_height_offsets(inherited)
    for key, value in patch.items():
        if value == 0:
            corrections.pop(key, None)
        else:
            corrections[key] = value
    updates = []
    for target in targets:
        if not target.resolve().is_relative_to(root):
            raise ClipLibraryError("sidecar escapes the library")
        data = dict(inherited)
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ClipLibraryError(f"{target.name} is not readable: {error}")
            if not isinstance(data, dict):
                raise ClipLibraryError(f"{target.name} is not an object")
        if corrections:
            data["height_offsets_cm"] = dict(corrections)
        else:
            data.pop("height_offsets_cm", None)
        updates.append((target, data))
    for target, data in updates:
        fd, name = tempfile.mkstemp(dir=target.parent, suffix=".clip-tmp")
        os.close(fd)
        stage = Path(name)
        try:
            stage.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
            atomic_replace(stage, target)
        finally:
            stage.unlink(missing_ok=True)
    reload_clip_caches()
    # A shared solo sidecar also affects its variants; report all of them.
    if not role and sidecar.name == f"{kind}.json":
        files = _kind_files(path.parent, kind)
    views = [_view_of(p, cset, library) for p in files]
    if with_finales:
        for finale in _finale_files(path):
            views += set_clip_height_offsets(library, _rel_in(finale, library), patch,
                                             with_finales=False)
    return views


# ── Turning a clip AFTER the import (plan-clip-library-…-ausrichtung U2) ──

def validate_clip_shift(value: Optional[Sequence[float]]) -> List[float]:
    """Strict edit delta, never boolean, non-finite or outside the UI range."""
    if value is None:
        return [0.0, 0.0]
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or abs(v) > 200 or not math.isfinite(v) for v in value)):
        raise ClipLibraryError("shift_cm must be [side, forward] numbers from -200 to 200")
    return [float(v) for v in value]


def read_clip_shift(value: Any) -> List[float]:
    """Saved cumulative values can exceed the per-edit range; invalid data means zero."""
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   for v in value)):
        return [0.0, 0.0]
    try:
        result = [float(v) for v in value]
    except OverflowError:
        return [0.0, 0.0]
    return result if all(math.isfinite(v) for v in result) else [0.0, 0.0]


def _orient_sidecar(path: Path, kind: str, pair: bool) -> Path:
    """The sidecar an orientation writes into.

    A PAIR always uses the shared ``<kind>.json``: the role geometry
    (``geometry.roles.a/b``) lives there and nowhere else. A solo file uses
    its OWN sidecar when it has one (``walk_02.json``) — its numbers are its
    own and must not be attributed to the whole kind — and the shared
    ``<kind>.json`` otherwise.
    """
    own = None if pair else _own_sidecar(path)
    return own if own is not None else path.parent / f"{kind}.json"


_root_motion_module = None


def _root_motion_mod():
    """The bpy-free root-motion maths the Blender scripts use, loaded from the
    scripts directory (not a package on purpose — Blender's Python imports it
    by path too). ``rotate_travel`` lives there and only there."""
    global _root_motion_module
    if _root_motion_module is None:
        import importlib.util
        path = (Path(__file__).resolve().parents[1] / "blender" / "scripts"
                / "_root_motion.py")
        spec = importlib.util.spec_from_file_location("_root_motion", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _root_motion_module = mod
    return _root_motion_module


def _bump_angle(geometry: Dict[str, Any], field: str, delta: float) -> None:
    """Adds ``delta`` degrees to a cumulative dial, 0.1 deg resolution; a dial
    that comes out at 0 is dropped, the way the import omits an unturned one."""
    total = round(float(geometry.get(field) or 0.0) + delta, 1)
    if abs(total) < 0.05:
        geometry.pop(field, None)
    else:
        geometry[field] = total


@_library_writer
def orient_clip(library: str, rel: str, *, yaw_deg: float = 0.0,
                tilt_deg: float = 0.0, roll_deg: float = 0.0,
                height_cm: float = 0.0,
                partner_shift_cm: Optional[Sequence[float]] = None,
                role_shift_cm: Optional[Dict[str, Sequence[float]]] = None,
                shift_cm: Optional[Sequence[float]] = None,
                with_finales: bool = True) -> List[Dict[str, Any]]:
    """Turns and lifts a clip IN THE FILE — the import dial, after the fact.

    ``yaw_deg`` / ``tilt_deg`` / ``roll_deg`` are the rigid rotation
    ``Ry(yaw) · Rx(tilt) · Rz(roll)`` about the origin of the clip frame on
    the floor, ``height_cm`` the lift after it (``app/blender/scripts/
    clip_orient.py`` writes out the convention). A PAIR or GROUP is turned
    whole: every role file goes into ONE Blender run with the same numbers,
    so their shared anchor survives.

    There is no second truth: the FBX is rewritten (temp file, then
    ``os.replace``) and the sidecar follows it — the three angles add up
    cumulatively, ``floor_shift_cm`` moves by the lift, a solo clip's
    ``root_motion.travel_m`` turns by the same rotation, and a pair's
    ``roles.*.start_xz_m`` / ``anchor_xz_m`` and ``root_distance_m`` are
    RE-MEASURED on the written file instead of being predicted, because that
    root path is what the clients read.

    ``partner_shift_cm`` is ``[side, up, forward]`` in the clip frame (+X =
    the clip's left, +Y up, +Z forward), centimetres: it moves the B half of
    a PAIR against the A half — the import's ``offsets_m``, after the fact,
    for a pack whose halves turn out misaligned. It is applied before the
    turn (``clip_orient.py``), so it lives in the frame the dials turn, and
    adds up in ``geometry.partner_shift_cm``. A solo clip refuses it, and so
    does a group (three roles and more): which role should move is not
    one answer there — a group names it.

    ``role_shift_cm`` is that answer for a GROUP: ``{role: [side, up,
    forward]}`` centimetres per role (``a``..``e``, any of them, −100..100),
    the import's ``offsets_m`` after the fact. Each role's files — its own
    half and its alt halves — move by its shift, before the turn like the
    partner shift, and the totals add up per role in
    ``geometry.role_shift_cm`` (a role back at zero drops out). A pair
    refuses it (``partner_shift_cm`` is the pair's), so does a solo clip.

    ``shift_cm`` is a cumulative renderer-only [side, forward] correction,
    -200..200 cm per edit, shared by both pair halves. It is applied after
    placement in the horizontal clip frame, independent of height and lean.
    Root retargeting strips authored XZ, so this must never be baked.

    All dials at 0 is a no-op (no Blender start). Returns the touched
    clips as listing views.

    ``with_finales``: the clip's finale clips (:func:`_finale_files`) get the
    same dials in the same call — the finale continues the pose, and a pose
    turned without its finale switched into a finale standing 90° or 180°
    off (2026-11-03). A finale that fails after the clip was written raises,
    naming both, so the mismatch is never silent.
    """
    from app.blender import runner

    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    yaw, tilt, roll = float(yaw_deg or 0.0), float(tilt_deg or 0.0), float(roll_deg or 0.0)
    height = float(height_cm or 0.0)
    shift = [float(v) for v in (partner_shift_cm or (0.0, 0.0, 0.0))]
    if len(shift) != 3 or not all(math.isfinite(v) and abs(v) <= 100 for v in shift):
        raise ClipLibraryError("partner_shift_cm must be three numbers from -100 to 100")
    horizontal = validate_clip_shift(shift_cm)
    per_role: Dict[str, List[float]] = {}
    for r, v in (role_shift_cm or {}).items():
        vals = [float(x) for x in (v or ())] if isinstance(v, (list, tuple)) else []
        if r not in CLIP_ROLES or len(vals) != 3 or not all(math.isfinite(x) and abs(x) <= 100 for x in vals):
            raise ClipLibraryError("role_shift_cm must be {role a..e: three numbers from -100 to 100}")
        if any(abs(x) > 1e-9 for x in vals):
            per_role[r] = vals
    kind, _role = parse_clip_role(path.name)
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""
    if not per_role and not any(abs(v) > 1e-9 for v in (yaw, tilt, roll, height, *shift, *horizontal)):
        return [_view_of(path, cset, library)]               # nothing dialled

    siblings = _role_siblings(path)
    if not siblings and any(abs(v) > 1e-9 for v in shift):
        raise ClipLibraryError(f"'{kind}' is a solo clip — only a pair has a partner to move")
    if len(siblings) > 1 and any(abs(v) > 1e-9 for v in shift):
        raise ClipLibraryError(
            f"'{kind}' is a group clip — move its roles with role_shift_cm")
    if per_role and len(siblings) < 2:
        raise ClipLibraryError(
            f"'{kind}' is not a group clip — only a group moves single roles"
            + (" (a pair moves partner B)" if siblings else ""))
    present = {_split_stem(p.stem)[1] for p in [path] + siblings}
    if set(per_role) - present:
        raise ClipLibraryError(f"'{kind}' has no role {', '.join(sorted(set(per_role) - present))}")
    sidecar = _orient_sidecar(path, kind, bool(siblings))
    if not sidecar.is_file():
        raise ClipLibraryError(
            f"'{kind}' has no sidecar {sidecar.name} — the baked angles are "
            "stored there, so the clip has to be (re-)imported first")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ClipLibraryError(f"{sidecar.name} is not readable: {e}")
    if not isinstance(meta, dict):
        raise ClipLibraryError(f"{sidecar.name} is not an object")
    geometry = meta.get("geometry")
    if not isinstance(geometry, dict):
        geometry = {}
        meta["geometry"] = geometry

    # The alt halves turn with the scene — they live in its frame.
    targets = [path] + siblings + (_alt_files(path) if siblings else [])
    slots = {f"src_{i}": p for i, p in enumerate(targets)}
    baked = bool(per_role) or any(abs(v) > 1e-9 for v in (yaw, tilt, roll, height, *shift))
    data: Dict[str, Any] = {}
    shifted: Dict[str, Any] = {}
    if baked:
        inputs: Dict[str, Path] = {"rig": get_rig_file()}
        inputs.update(slots)
        # Only the B half moves; the addressed file may be either half. In a
        # group every named role moves, with its alt halves.
        shifted = {slot: shift for slot, target in slots.items()
                   if any(abs(v) > 1e-9 for v in shift)
                   and _split_stem(target.stem)[1].split(ALT_SEPARATOR)[0] == "b"}
        shifted.update({slot: per_role[base] for slot, target in slots.items()
                        if (base := _split_stem(target.stem)[1].split(ALT_SEPARATOR)[0]) in per_role})
        with tempfile.TemporaryDirectory(prefix="clip-orient-") as tmp:
            res = runner.run("clip_orient", inputs=inputs, params={
                "yaw_deg": yaw, "tilt_deg": tilt, "roll_deg": roll,
                "height_cm": height, "fps": int(meta.get("fps") or 30),
                "anchor_frame": int(geometry.get("anchor_frame") or 0),
                "slot_shift_cm": shifted,
            }, out_dir=Path(tmp), timeout_s=900)
            if not res["ok"]:
                raise ClipLibraryError(str(res.get("error") or "the Blender run failed"))
            written = res.get("outputs") or {}
            missing = [s for s in slots if not Path(written.get(s) or "").is_file()]
            if missing:
                raise ClipLibraryError("the Blender run declared no file for "
                                       + ", ".join(slots[s].name for s in missing))
            # Every role file is staged beside its target first: a pair or group
            # must never end up with one turned and one untouched file.
            staged = []
            try:
                for slot, target in slots.items():
                    fd, name = tempfile.mkstemp(dir=target.parent, prefix="." + target.name + ".", suffix=".tmp")
                    os.close(fd)
                    stage = Path(name)
                    staged.append((stage, target))
                    shutil.copy2(written[slot], stage)
                for stage, target in staged:
                    atomic_replace(stage, target)
            finally:
                for stage, _target in staged:
                    if stage.exists():
                        stage.unlink(missing_ok=True)
        data = (res["data"] or {}).get("clips") or {}
    for field, delta in zip(ORIENT_ANGLES, (yaw, tilt, roll)):
        if abs(delta) > 1e-9:
            _bump_angle(geometry, field, delta)
    if abs(height) > 1e-9:
        geometry["floor_shift_cm"] = round(
            float(geometry.get("floor_shift_cm") or 0.0) + height, 2)
    if shifted and any(abs(v) > 1e-9 for v in shift):
        total = [round(float(a) + b, 1) for a, b in
                 zip(geometry.get("partner_shift_cm") or (0.0, 0.0, 0.0), shift)]
        if any(abs(v) >= 0.05 for v in total):
            geometry["partner_shift_cm"] = total
        else:
            geometry.pop("partner_shift_cm", None)
    if per_role:
        book = geometry.get("role_shift_cm")
        book = dict(book) if isinstance(book, dict) else {}
        for r, vals in per_role.items():
            total = [round(float(a) + b, 1) for a, b in zip(book.get(r) or (0.0, 0.0, 0.0), vals)]
            if any(abs(v) >= 0.05 for v in total):
                book[r] = total
            else:
                book.pop(r, None)
        if book:
            geometry["role_shift_cm"] = {r: book[r] for r in CLIP_ROLES if r in book}
        else:
            geometry.pop("role_shift_cm", None)
    # A solo clip's travel is a direction in the clip frame — it turns with
    # the file (a lift moves nothing horizontal).
    rm = geometry.get("root_motion")
    if baked and not siblings and isinstance(rm, dict) and rm.get("travel_m"):
        tx, tz = _root_motion_mod().rotate_travel(tuple(rm["travel_m"]), yaw, tilt, roll)
        rm["travel_m"] = [round(tx, 3), round(tz, 3)]
    if siblings and baked:
        roles = geometry.get("roles")
        if not isinstance(roles, dict):
            roles = {}
            geometry["roles"] = roles
        for slot, target in slots.items():
            _k, role, _num = _split_stem(target.stem)
            # an alt half's root is kept apart from the scene's roles
            book = roles
            if ALT_SEPARATOR in role:
                book = geometry.get("alts")
                if not isinstance(book, dict):
                    book = geometry["alts"] = {}
            entry = book.get(role)
            if not isinstance(entry, dict):
                entry = {}
                book[role] = entry
            d = data.get(slot) or {}
            entry["start_xz_m"] = _xz_m(d.get("root_after"))
            entry["anchor_xz_m"] = _xz_m(d.get("root_after_anchor"))
        a, b = (roles.get(r) or {} for r in CLIP_ROLES[:2])
        if a.get("anchor_xz_m") and b.get("anchor_xz_m"):
            geometry["root_distance_m"] = round(
                math.dist(a["anchor_xz_m"], b["anchor_xz_m"]), 3)
    if any(horizontal):
        total = [round(a + b, 2) for a, b in
                 zip(read_clip_shift(geometry.get("shift_cm")), horizontal)]
        if any(total):
            geometry["shift_cm"] = total
        else:
            geometry.pop("shift_cm", None)
    sidecar.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    reload_clip_caches()
    logger.info("clip oriented: %s%s (%s) yaw %+.1f tilt %+.1f roll %+.1f "
                "height %+.1f cm partner %s cm roles %s cm shift %s cm -> %s; lowest point now %s cm",
                f"{cset}/" if cset else "", kind, library, yaw, tilt, roll,
                height, shift if any(abs(v) > 1e-9 for v in shift) else "-", per_role or "-",
                horizontal, ", ".join(p.name for p in targets),
                (data.get("src_0") or {}).get("floor_min_cm_after"))
    views = [_view_of(p, cset, library) for p in targets]
    if with_finales:
        for finale in _finale_files(path):
            try:
                views += orient_clip(library, _rel_in(finale, library), yaw_deg=yaw, tilt_deg=tilt,
                                     roll_deg=roll, height_cm=height,
                                     partner_shift_cm=shift if any(abs(v) > 1e-9 for v in shift) else None,
                                     role_shift_cm=per_role or None,
                                     shift_cm=horizontal, with_finales=False)
            except ClipLibraryError as e:
                raise ClipLibraryError(
                    f"'{kind}' was changed, but its finale '{parse_clip_role(finale.name)[0]}' "
                    f"was not: {e}") from e
    return views


def _xz_m(xyz: Any) -> List[float]:
    """The XZ of a clip-space position in metres, as the sidecar stores it."""
    if not isinstance(xyz, (list, tuple)) or len(xyz) < 3:
        return [0.0, 0.0]
    return [round(float(xyz[0]) / 100, 3), round(float(xyz[2]) / 100, 3)]


def _view_of(path: Path, cset: str, library: str) -> Dict[str, Any]:
    """The listing view of one file that was just written — built from the
    path, not from a rescan: a free clip shadowed by a licensed twin would
    otherwise not appear in ``clip_entries()`` at all."""
    kind, role = parse_clip_role(path.name)
    rel = f"{cset}/{path.name}" if cset else path.name
    return clip_view({"kind": kind, "role": role, "set": cset,
                      "source": library, "rel": rel, "path": path})


def _move_sidecar(src_dir: Path, old_kind: str, dest_dir: Path,
                  new_kind: str, *, needed: bool = True) -> None:
    """Takes the shared ``<kind>.json`` along with the files that just moved.

    It MOVES when no file of the old kind is left in the source directory and
    COPIES when there still are numbered variants sharing it. A sidecar
    already sitting at the target wins — those are the numbers of the clips
    that were there first.

    ``needed`` is False only for solo variants that all brought sidecars of
    their OWN. The shared one then moves only when it would otherwise dangle
    at the source. Pairs always need the shared geometry and height map.
    """
    sidecar = src_dir / f"{old_kind}.json"
    if not sidecar.is_file():
        return
    orphaned = not _kind_files(src_dir, old_kind)
    if not needed and not orphaned:
        return
    target = dest_dir / f"{new_kind}.json"
    if target.exists() and target.resolve() != sidecar.resolve():
        if orphaned:
            sidecar.unlink(missing_ok=True)
        return
    if orphaned:
        shutil.move(str(sidecar), str(target))
    else:
        shutil.copy2(str(sidecar), str(target))
    if new_kind != old_kind:
        _rewrite_sidecar_kind(target, new_kind)


def _clear_replaced(targets: List[Path], dest_dir: Path, kind: str) -> List[str]:
    """Clears the way for an OVERWRITING move — the admin's "Replace".

    Every file being replaced goes with the sidecar that belongs to it alone
    (``walk_02.json``), one half of a pair like the other. The shared
    ``<kind>.json`` beside them goes only when NO file of that kind is left in
    the target directory after the deletions: while other variants remain it
    is theirs, not the replaced file's, and the incoming sidecar must not
    overwrite their numbers.

    Returns the names removed, for the log line of the caller.
    """
    removed: List[str] = []
    for dest in targets:
        own = _own_sidecar(dest)
        dest.unlink(missing_ok=True)
        removed.append(dest.name)
        if own is not None:
            own.unlink(missing_ok=True)
            removed.append(own.name)
    shared = dest_dir / f"{kind}.json"
    if shared.is_file() and not _kind_files(dest_dir, kind):
        shared.unlink(missing_ok=True)
        removed.append(shared.name)
    return removed


def _take_own_sidecar(sidecar: Path, target: Path, new_kind: str) -> None:
    """Moves the sidecar of ONE file (``walk_02.json``) to the name that file
    now has (``stroll_02.json``) and rewrites its ``kind``. A sidecar already
    lying at the target wins — it belongs to the file that was there first."""
    if target.exists() and target.resolve() != sidecar.resolve():
        return
    if target.resolve() != sidecar.resolve():
        shutil.move(str(sidecar), str(target))
    _rewrite_sidecar_kind(target, new_kind)


def _rewrite_sidecar_kind(target: Path, new_kind: str) -> None:
    """Puts the new kind into a sidecar that was just moved or copied."""
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict) and data.get("kind") != new_kind:
        data["kind"] = new_kind
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")


_UNSAFE_KIND_CHARS = re.compile(r"[^a-z0-9 _-]+")


def _kind_base(raw: str) -> str:
    base = _UNSAFE_KIND_CHARS.sub("-", str(raw or "").strip().lower())
    base = re.sub(r"-{2,}", "-", base).strip("-") or "pose"
    base = _NUM_SUFFIX_RE.sub(lambda m: "-" + m.group(0).lstrip("_"), base)
    return validate_kind(base)


def _owned_by(kind: str, pose_key: str) -> bool:
    try:
        meta = json.loads((get_animation_clips_dir() / f"{kind}.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return False
    src = meta.get("source") if isinstance(meta, dict) else None
    return isinstance(src, dict) and src.get("generated_for_pose") == pose_key


def reserve_kind(base: str, *, pose_key: str) -> str:
    """Kind for a generated clip: the pose key unless another clip owns that
    name anywhere (both libraries, every set, pair halves), then -u, -u2, ..."""
    _clear_entries_cache()
    taken = {e["kind"] for e in clip_entries()}
    kind = _kind_base(base)
    if kind not in taken or _owned_by(kind, pose_key):
        return kind
    n = 1
    while True:
        cand = f"{kind}-u" if n == 1 else f"{kind}-u{n}"
        if cand not in taken or _owned_by(cand, pose_key):
            return cand
        n += 1
