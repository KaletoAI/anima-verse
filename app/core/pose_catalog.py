"""Pose/expression catalog - the finite render-key axes (plan-pose-katalog.md).

The catalog entry key is the ONLY key under which 2D image variants are
cached and 3D animation clips are resolved. Free text never reaches a
render path; it survives only as sanitized "flavor" prompt text.
"""
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("pose_catalog")

class PairPoseWithoutPartner(ValueError):
    """A two-person pose (catalog ``solo: false``) was set on a character that
    is not bound to a running pair interaction.

    Such a pose describes what TWO people do; written on one profile alone it
    is an invalid state — no partner, no anchor, no second half of the clip.
    The one legitimate writer is ``interaction_engine.start_interaction``,
    which binds the pair FIRST and only then sets the pose. Every other
    caller gets this exception so it can redirect (a skill), map it to a
    status code (a route) or discard the pose (a chat extraction).
    """


AXES = ("pose", "expression")
_FILES = {
    "pose": ("pose", "pose_catalog.json"),
    "expression": ("expression", "expression_catalog.json"),
}
_FALLBACK_DEFAULT = {"pose": "standing", "expression": "neutral"}

_lock = threading.Lock()
_cache: Dict[str, Dict[str, dict]] = {}
_groups_cache: Dict[str, dict] = {}
#: (st_mtime_ns, st_size) of each axis' shared file when its cache was
#: filled — an edit from OUTSIDE the server (the animation studio's publish,
#: a hand edit) is noticed on the next read instead of after a restart.
_stamps: Dict[str, Optional[tuple]] = {}
#: Bumped whenever a cache is dropped (file change or reload). The alias
#: embedding warm-up runs outside ``_lock``; it only parks its vectors when
#: the generation it started on is still current, so a map embedded from the
#: OLD catalog never outlives the drop.
_generation = 0


#: Where an entry or a place type lives — the two layers of the catalog,
#: the same shape as the terrain types (``terrain_types.py``): ``shared`` is
#: the curated, TRACKED catalog file that travels with the repository, the
#: seed every world starts from; ``world`` is the world's own layer in its
#: ``world.db`` (table ``pose_catalog_world``). A world row REPLACES the shared
#: entry or group of the same key (override-replace, per key) or adds one the
#: shared file does not carry; dropping the row brings the shared one back.
#:
#: The world layer exists because the catalog is the only way a clip becomes
#: reachable in the game (``interaction_engine.partner_poses`` iterates it and
#: nothing else), while a clip imported from licensed or adult material must
#: not put its name into a tracked file. Without a second layer the choice was
#: "unusable clip" or "uncommittable edit", and the second one has already
#: gone wrong once. Until 2026-09-08 that layer was a gitignored overlay FILE
#: beside the shared one (``<axis>_catalog.local.json``, per installation, not
#: per world); it moved into the world so the catalog follows the one
#: shared/world concept the rest of the app has, and
#: :func:`migrate_catalog_overlay_once` carries an existing overlay across.
STORES = ("shared", "world")

#: The world layer's table (``world_db_schema``): one row per entry or place
#: type, the document as JSON.
WORLD_TABLE = "pose_catalog_world"


def catalog_path(axis: str) -> Path:
    """File the CURATED catalog of this axis lives in — the tracked one.
    Raises KeyError on an unknown axis."""
    from app.core.paths import get_shared_dir
    sub, name = _FILES[axis]
    return get_shared_dir() / "templates" / sub / name


def _file_stamp(axis: str) -> Optional[tuple]:
    try:
        st = catalog_path(axis).stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _drop_if_changed(axis: str) -> None:
    """Call with ``_lock`` held. One ``os.stat`` per read — microseconds.

    Drops the merged catalog of the axis, every alias-embedding map of it
    (``_embed_cache`` is keyed ``(axis, model id)``) and, for ``pose``, the
    place types that live in the same file."""
    global _generation
    stamp = _file_stamp(axis)
    previous = _stamps.get(axis, "unset")
    if previous != stamp:
        _cache.pop(axis, None)
        for key in [k for k in _embed_cache if k[0] == axis]:
            del _embed_cache[key]
        if axis == "pose":
            _groups_cache.clear()
        _stamps[axis] = stamp
        # Only a REAL change invalidates a warm-up in flight. The first read
        # after start or after reload_catalogs() (no stamp yet) just records
        # one — reload_catalogs() bumped the generation itself, and bumping
        # here too would keep the warm-up right after it from caching.
        if previous != "unset":
            _generation += 1


@contextmanager
def catalog_file_lock(axis: str) -> Iterator[None]:
    """Exclusive advisory lock on the shared file of an axis, across
    PROCESSES: the Poses tab (server) and the animation studio's publish
    both read-modify-write the same file. A separate ``.lock`` file,
    because the catalog itself is replaced atomically (``os.replace``).
    NOT re-entrant: a second acquisition in the same process, even on the
    same thread, blocks forever — take it once per critical section, never
    nested."""
    import fcntl
    path = catalog_path(axis)
    lock = path.with_name(path.name + ".lock")
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_shared_document(axis: str, data: dict) -> None:
    """Writes the shared catalog file ATOMICALLY: a temp file in the same
    directory, then ``os.replace``.

    An in-place ``open(path, "w")`` truncates the catalog before writing it:
    a crash, a full disk or a reader arriving mid-write would see a truncated
    or empty document — and this file is the render key of every pose and
    expression. ``os.replace`` is atomic within one filesystem, which is why
    the temp file is created in the catalog's OWN directory. The mode is
    carried over from the file being replaced (``mkstemp`` creates 0600, the
    catalog is a tracked file). Format: ``json.dump(..., ensure_ascii=False,
    indent=2)``, no trailing newline. The caller drops the caches."""
    import tempfile
    path = catalog_path(axis)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def legacy_overlay_path(axis: str) -> Path:
    """Where the pre-2026-09-08 overlay file of an axis sat — DERIVED from the
    curated path, so a harness that redirects ``catalog_path`` redirects the
    migration's source with it. Only :func:`migrate_catalog_overlay_once`
    reads it; nothing writes it any more."""
    path = catalog_path(axis)
    return path.with_name(path.name.replace(".json", ".local.json"))


def _read_shared(axis: str) -> dict:
    """The raw shared catalog document — ``{}`` when it is absent or
    unreadable (logged)."""
    try:
        data = json.loads(catalog_path(axis).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        logger.warning("catalog %s unreadable: %s", axis, e)
        return {}
    return data if isinstance(data, dict) else {}


def _world_rows(axis: str, kind: str) -> Dict[str, dict]:
    """The world layer's documents of one kind (``entry`` / ``group``), keyed.

    A world without the table yet — a harness that reads the catalog before
    ``init_schema``, a script that runs without a world — simply has an EMPTY
    world layer; that is what the shared seed is for. Any other database
    error propagates: a world whose layer cannot be read must not silently
    fall back to the seed and serve poses its author replaced.
    """
    import sqlite3
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            f"SELECT key, doc FROM {WORLD_TABLE} WHERE axis=? AND kind=?",
            (axis, kind)).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
        return {}
    out: Dict[str, dict] = {}
    for key, doc in rows:
        try:
            parsed = json.loads(doc or "{}")
        except ValueError:
            logger.warning("world catalog row %s/%s/%s unreadable", axis, kind, key)
            continue
        if isinstance(parsed, dict):
            out[str(key)] = parsed
    return out


def world_entries(axis: str) -> Dict[str, dict]:
    """The raw entries of the WORLD layer of an axis, keyed — what the editor
    reads before it writes the layer back as a whole."""
    return _world_rows(axis, "entry")


def world_groups() -> Dict[str, dict]:
    """The raw place types of the WORLD layer (pose axis), keyed."""
    return _world_rows("pose", "group")


def _replace_world_rows(axis: str, kind: str, docs: Dict[str, dict]) -> None:
    """Make the world layer of one kind exactly ``docs``: rows for keys not
    in it are deleted, every key in it is upserted — one transaction, so a
    reader never sees the layer half replaced."""
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    now = utc_now_iso()
    keys = list(docs)
    with transaction() as conn:
        if keys:
            conn.execute(
                f"DELETE FROM {WORLD_TABLE} WHERE axis=? AND kind=? AND key NOT IN "
                f"({','.join('?' * len(keys))})", (axis, kind, *keys))
        else:
            conn.execute(f"DELETE FROM {WORLD_TABLE} WHERE axis=? AND kind=?",
                         (axis, kind))
        for key, doc in docs.items():
            conn.execute(
                f"INSERT INTO {WORLD_TABLE} (axis, kind, key, doc, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(axis, kind, key) DO UPDATE SET doc=excluded.doc, "
                "updated_at=excluded.updated_at",
                (axis, kind, key, json.dumps(doc, ensure_ascii=False), now))


def replace_world_entries(axis: str, entries: Dict[str, dict]) -> None:
    """Write the WORLD layer's entries of an axis as a whole (see
    :func:`_replace_world_rows`). The caller drops the caches."""
    _replace_world_rows(axis, "entry", entries)


def replace_world_groups(groups: Dict[str, dict]) -> None:
    """Write the WORLD layer's place types as a whole."""
    _replace_world_rows("pose", "group", groups)


def migrate_catalog_overlay_once() -> Dict[str, int]:
    """One-time boot migration (2026-09-08): the gitignored overlay file of
    each axis (``<axis>_catalog.local.json``, the per-installation layer of
    2026-09-07) becomes the WORLD layer of the world being started.

    Every entry and every group of the overlay is inserted into the world
    layer unless the world already carries that key (``INSERT OR IGNORE`` —
    a world edited since keeps its own row); the file is then renamed to
    ``*.migrated`` so this runs once per file. A world started later finds
    no file and migrates nothing: the overlay was per installation, so it
    lands in the FIRST world that boots after the change — the one the
    machine was running when the overlay was written.

    Returns ``{"entries": n, "groups": n}`` (zeros when nothing was found).
    """
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    counts = {"entries": 0, "groups": 0}
    for axis in AXES:
        path = legacy_overlay_path(axis)
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("catalog overlay %s unreadable, left in place: %s", path, e)
            continue
        if not isinstance(doc, dict):
            doc = {}
        now = utc_now_iso()
        with transaction() as conn:
            for kind, block_key in (("entry", "entries"), ("group", "groups")):
                block = doc.get(block_key) or {}
                if not isinstance(block, dict):
                    continue
                for key, spec in block.items():
                    if not isinstance(spec, dict):
                        continue
                    cur = conn.execute(
                        f"INSERT OR IGNORE INTO {WORLD_TABLE} "
                        "(axis, kind, key, doc, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (axis, kind, str(key).strip().lower(),
                         json.dumps(spec, ensure_ascii=False), now))
                    counts[block_key] += cur.rowcount
        path.rename(path.with_name(path.name + ".migrated"))
        logger.info("catalog overlay %s migrated into the world layer", path.name)
    reload_catalogs()
    return counts


def _load(axis: str) -> Dict[str, dict]:
    """Every entry of an axis, the world layer laid over the shared file.

    A key present in both is the world's — override-replace per key. Each
    entry carries the store it came from in ``_store``, so the editor writes
    it back where it belongs instead of promoting a world entry into the
    tracked file on the next save.
    """
    entries: Dict[str, dict] = {}
    origin: Dict[str, str] = {}
    shared = _read_shared(axis).get("entries") or {}
    for store, block in (("shared", shared), ("world", world_entries(axis))):
        if not isinstance(block, dict):
            continue
        for key, entry in block.items():
            entries[key] = entry
            origin[key] = store
    out: Dict[str, dict] = {}
    for key, entry in entries.items():
        solo = bool(entry.get("solo", True))
        norm = {
            "prompt": str(entry.get("prompt") or ""),
            "synonyms": [str(s).strip().lower() for s in (entry.get("synonyms") or []) if str(s).strip()],
            "animation": str(entry.get("animation") or ""),
            "solo": solo,
            "_default": bool(entry.get("_default", False)),
            "_store": origin.get(key, "shared"),
        }
        if axis == "pose":
            # Place types are POSE vocabulary — an expression has no place.
            # plan-posen-plaetze.md § 3.2: the PLACE TYPE the pose needs.
            norm["group"] = str(entry.get("group") or "").strip().lower()
            # pair poses only: slots of the anchor marker the pair consumes,
            # and how the clip frame (+X = A->B) turns against the marker
            # facing. A solo pose occupies exactly one place and never turns.
            norm["places"] = (1 if solo
                              else max(1, min(2, int(entry.get("places") or 2))))
            norm["yaw_offset"] = (0.0 if solo
                                  else float(entry.get("yaw_offset") or 0.0))
            norm["_stray_pair_fields"] = solo and ("places" in entry
                                                   or "yaw_offset" in entry)
        out[str(key).strip().lower()] = norm
    return out


def _load_groups() -> Dict[str, dict]:
    """Place types of the pose axis (plan-platztypen.md): the finite
    vocabulary a MARKER speaks. A place type is a BODY SHAPE, not a kind of
    furniture — one lies on the floor, on a couch and in a bed, so ``lie``
    covers all three and the marker says where.

    ``root_drop`` x figure height is how far a figure's root sinks below the
    marked surface; ``default`` the pose a "sit here" click sets;
    ``needs_place`` (default True) says whether the group's poses need a
    marker at all — a False group is offered "anywhere here", gets no place
    assigned and its spot is never named.

    Where the numbers come from — the CONTACT POINT of the body meets the
    marked surface S (decision 2026-08-29, folded in on 2026-09-08). Measured
    headless on the 1.70 m reference figure against the clips in
    ``shared/models/clips`` (the files that are served for these kinds —
    the licensed library shadows none of them), through the project's own
    chain (``scripts/smoke_prop_marker_place.mjs`` E5)::

        posed hips   = S - rootOffset - clipHipsDrop + hipsBindY
        clipHipsDrop = hipsBindY x (1 - median / standRef)
        standRef     = 113.032, the REST hips height of the reference rig
                       every clip is retargeted onto
                       (``shared/models/rig/reference.fbx``) — what
                       ``standingHipsRef`` of @anima/scene-render answers
                       with a rig served, in the 3D client and in every
                       admin preview alike
        hipsBindY    = 0.98013
        contact      = how far the body point that meets the surface lies
                       BELOW the hip joint in the posed clip (median over 17
                       frames): for ``sit`` the buttocks = the lowest vertex
                       skinned to the hips bone, for ``laying`` the lowest
                       vertex of the whole body
        root_drop    = (hipsBindY - clipHipsDrop - contact) / 1.70

        rig rest        113.032  drop 0        contact   —      —
        idle    median 110.179  drop 0.02474  contact   —      stand 0
        sit     median  65.961  drop 0.40816  buttocks 0.1741  seat  0.234
        laying  median  20.368  drop 0.80351  lowest   0.1754  lie   0.001

        sit:    0.98013 x (1 - 65.961 / 113.032) = 0.98013 x 0.416440 = 0.40816
        laying: 0.98013 x (1 - 20.368 / 113.032) = 0.98013 x 0.819803 = 0.80351
        seat: (0.98013 - 0.40816 - 0.1741) / 1.70 = 0.39787 / 1.70 = 0.23404
        lie:  (0.98013 - 0.80351 - 0.1754) / 1.70 = 0.00122 / 1.70 = 0.00072

    ``stand`` stays 0: a standing spot's figure keeps its feet on the mark,
    and the idle clip's own drop (bent knees, 2.47 cm below the rig rest) is
    the clip term, not the place's.

    The payload rounds ``root_drop x 1.70`` to millimetres: seat 0.3978 ->
    0.398, lie 0.0017 -> 0.002. What a client then draws on the bench
    S = 0.587: a seated body's buttocks at S - 0.0001 (hips S + 0.1740), a
    lying body's lowest point at S - 0.0008 (hips S + 0.1746). A lying clip
    is authored on the floor, which is why ``lie`` is all but zero: the
    clip's own hips height already puts the body on its surface.

    History, so nobody re-derives an old number as the new one. Until
    2026-09-26 ``standRef`` was the idle clip's hips median (110.179, drops
    sit 0.39335 / laying 0.79894), which gave seat 0.243 / lie 0.003 — but
    the idle clip stands on bent knees, its median 2.853 rig units (2.5 % of
    the rest: 1 - 110.179 / 113.032 = 0.0252) below the straight-legged
    rest, and that denominator lifted every figure by hipsBindY x (m / 110.179
    - m / 113.032), clip by clip: idle 2.47 cm, sit 1.48 cm, laying 0.46 cm
    on the 1.70 m reference figure. Since then the rig rest is the reference
    everywhere and these values were re-derived against it. Until
    the morning of 2026-09-08 the target was the HIP JOINT (seat 0.320 / lie
    0.075, hips at S + 0.043 / S + 0.054): a seated body sat 0.131 m in the
    cushion and a lying one 0.122 m in the mattress. Before that (0.314 /
    0.051) the same values were read against the clip library ``a605c5a7``
    replaced. ``bed`` carried 0.631 until the place types became body
    shapes — calibrated for the Mixamo ``sleep`` clip, gone since
    ``c2eb166d``; against the clips it shipped with (laying median 15.81,
    drop 0.84033) that put every sleeper's hips 0.93 m under the mattress,
    re-read against today's clips and reference it is 0.90 m — two readings
    of one retired value. ``sleeping`` and ``lying`` name the same
    ``laying`` clip today, so one value serves both.

    Still open, its own strand: the number belongs to the CLIP, not to the
    place type. A set's own clip measures differently — ``male/sit.fbx``
    (median 60.011, drop 0.45976 against the rig rest, buttocks 0.1751)
    wants 0.203, so a figure playing it sits 0.053 m into the cushion under
    this catalog value.
    """
    raw: Dict[str, dict] = {}
    origin: Dict[str, str] = {}
    shared = _read_shared("pose").get("groups") or {}
    for store, block in (("shared", shared), ("world", world_groups())):
        if not isinstance(block, dict):
            continue
        for key, spec in block.items():
            raw[key] = spec
            origin[key] = store
    out: Dict[str, dict] = {}
    for key, spec in raw.items():
        k = str(key).strip().lower()
        if not k or not isinstance(spec, dict):
            continue
        try:
            drop = float(spec.get("root_drop") or 0.0)
        except (TypeError, ValueError):
            drop = 0.0
        out[k] = {"label": str(spec.get("label") or k),
                  "root_drop": round(max(0.0, min(1.0, drop)), 3),
                  "default": str(spec.get("default") or "").strip().lower(),
                  # A place type normally demands a marker — only a group
                  # that says otherwise gets by without one.
                  "needs_place": bool(spec.get("needs_place", True)),
                  # Which layer the effective group comes from, so the editor
                  # writes it back there (the entries carry the same key).
                  "_store": origin.get(key, "shared")}
    return out


def get_groups() -> Dict[str, dict]:
    """All place types, keyed by group id."""
    with _lock:
        _drop_if_changed("pose")
        if not _groups_cache:
            _groups_cache.update(_load_groups())
        return dict(_groups_cache)


def get_catalog(axis: str) -> Dict[str, dict]:
    with _lock:
        _drop_if_changed(axis)
        if axis not in _cache:
            _cache[axis] = _load(axis)
        return _cache[axis]


def reload_catalogs() -> None:
    global _generation
    with _lock:
        _cache.clear()
        _groups_cache.clear()
        _embed_cache.clear()
        _stamps.clear()
        _generation += 1


def get_default_key(axis: str) -> str:
    for key, entry in get_catalog(axis).items():
        if entry["_default"]:
            return key
    return _FALLBACK_DEFAULT[axis]


def group_of(pose_key: str) -> str:
    """Place type a pose needs ("" = unknown key or ungrouped entry)."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    return (entry or {}).get("group", "")


def needs_place(group: str) -> bool:
    """Does a pose of this place type need a MARKER? False = it is a body
    shape one can strike anywhere (standing, kneeling): the pose is offered
    under "anywhere here", no place is assigned and the spot is never named.

    An unknown group counts as needing one — a marker speaking a group the
    catalog no longer knows is a defect, and naming it is the louder
    failure than silently swallowing it.
    """
    spec = get_groups().get((group or "").strip().lower())
    return True if spec is None else bool(spec.get("needs_place", True))


def placeless_groups() -> List[str]:
    """Ids of the groups whose poses need no marker, in catalog order."""
    return [g for g, spec in get_groups().items() if not spec.get("needs_place", True)]


def poses_without_place() -> List[str]:
    """Every pose that needs no marker — the "anywhere here" menu. Group by
    group in catalog order, each group's default first (:func:`poses_in_group`)."""
    out: List[str] = []
    for g in placeless_groups():
        out += [k for k in poses_in_group(g) if k not in out]
    return out


def poses_in_group(group: str) -> List[str]:
    """Keys of the group, the group's default first, the rest alphabetical."""
    g = (group or "").strip().lower()
    default = (get_groups().get(g) or {}).get("default", "")
    keys = sorted(k for k, e in get_catalog("pose").items() if e.get("group") == g)
    if default in keys:
        keys.remove(default)
        keys.insert(0, default)
    return keys


def pose_places(pose_key: str) -> int:
    """Marker slots the pose consumes: 1 for a solo pose, else its ``places``."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower()) or {}
    return 1 if entry.get("solo", True) else int(entry.get("places") or 2)


def pose_yaw_offset(pose_key: str) -> float:
    """Degrees the pair clip's frame turns against the marker facing (0 solo)."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower()) or {}
    return 0.0 if entry.get("solo", True) else float(entry.get("yaw_offset") or 0.0)


def validate_catalog(axis: str) -> List[str]:
    """Returns human-readable problems; empty list = catalog is sound."""
    problems: List[str] = []
    catalog = get_catalog(axis)
    if not catalog:
        problems.append(f"{axis}: catalog is empty or unreadable")
        return problems
    seen: Dict[str, str] = {}
    defaults = 0
    pairs: set = set()
    if axis == "pose":
        try:
            from app.core.animation_clips import pair_kinds
            pairs = set(pair_kinds())
        except Exception:
            pairs = set()
    for key, entry in catalog.items():
        if not entry["prompt"]:
            problems.append(f"{axis}/{key}: empty prompt")
        if axis == "pose" and not entry["animation"]:
            problems.append(f"{axis}/{key}: missing animation kind")
        if axis == "pose" and entry["animation"] in pairs and entry["solo"]:
            # A pair clip has no solo half — the pose needs a partner.
            problems.append(f"{axis}/{key}: '{entry['animation']}' is a pair "
                            f"animation, the pose must not be solo")
        if entry["_default"]:
            defaults += 1
        for alias in [key] + entry["synonyms"]:
            if alias in seen and seen[alias] != key:
                problems.append(f"{axis}: alias '{alias}' claimed by both '{seen[alias]}' and '{key}'")
            seen[alias] = key
    if defaults != 1:
        problems.append(f"{axis}: expected exactly 1 _default entry, found {defaults}")
    if axis == "pose":
        groups = get_groups()
        for g, spec in groups.items():
            d = spec["default"]
            # A place type only just added has no poses yet — and a pose can
            # only name a type that already EXISTS, so the empty default of a
            # poseless group is legal; without that the block could never grow.
            # A default is demanded as soon as the group has its first pose.
            if not d and not any(e.get("group") == g for e in catalog.values()):
                continue
            if d not in catalog or catalog[d].get("group") != g:
                problems.append(f"pose group '{g}': default '{d}' is not a pose of this group")
        for key, entry in catalog.items():
            if entry.get("group", "") not in groups:
                problems.append(f"{axis}/{key}: unknown place type '{entry.get('group', '')}'")
            if entry.get("_stray_pair_fields"):
                problems.append(f"{axis}/{key}: places/yaw_offset only make sense on a pair pose")
    return problems


# ── Resolution: free text → catalog key ──────────────────────────────────
# Matching threshold: cosine similarity below which a free text is treated as
# "not in the catalog" and logged as a candidate. 0.60, because catalog entries
# are short verb phrases: cross-phrasing similarity is lower than
# same-pose-different-words similarity.
# Constant, not a world setting: the world knob pose.catalog_match_threshold
# never had a UI (rule "feature = backend + UI"), so it froze at this default
# anyway — removed with the pose-variant teardown (Aug 2026).
CATALOG_THRESHOLD = 0.60


# Cosine similarity lives with the vectors it compares (app/core/embedding.py)
# — the situational memory block is a second consumer since Aug 2026.
from app.core.embedding import cosine_similarity  # noqa: E402


def _alias_index(axis: str) -> Dict[str, str]:
    """alias (key or synonym, lowercased) -> entry key."""
    index: Dict[str, str] = {}
    for key, entry in get_catalog(axis).items():
        for alias in [key] + entry["synonyms"]:
            index.setdefault(alias, key)
    return index


# (axis, model id) -> {alias: vector}. Keyed by the MODEL too: vectors of two
# embedding models are not comparable, and the admin can switch the model
# (or the external route) while the server runs.
_embed_cache: Dict[Tuple[str, str], Dict[str, list]] = {}


def _embed_model_key(embed_fn) -> str:
    """Which model's vectors ``embed_fn`` produces. The real ``embed`` answers
    with ``embedding.current_model_id()``; any other function (a test double)
    is its own model."""
    from app.core import embedding
    if embed_fn is embedding.embed:
        return embedding.current_model_id()
    return f"fn:{id(embed_fn)}"


def _alias_embeddings(axis: str, embed_fn) -> Dict[str, list]:
    # Resolve the aliases BEFORE taking _lock: _alias_index() -> get_catalog()
    # takes the same (non-reentrant) lock and would deadlock on itself.
    # The generation is read BEFORE the aliases: a drop between the two reads
    # then only costs one uncached lookup, never a stale cached map.
    with _lock:
        generation = _generation
    aliases = _alias_index(axis)
    key = (axis, _embed_model_key(embed_fn))
    with _lock:
        cached = _embed_cache.get(key)
    if cached is not None:
        return cached
    # The warm-up runs OUTSIDE the lock: with an external embedding backend it
    # is one HTTP call per alias, and _lock is the same lock every catalog
    # reader takes. Two threads racing here just embed twice — harmless.
    vecs = {}
    for alias in aliases:
        v = embed_fn(alias)
        if v:
            vecs[alias] = v
    if not vecs:
        # Nothing came back (no model, endpoint down): do NOT cache the empty
        # map — that would pin "no embeddings" until the next catalog reload.
        return vecs
    with _lock:
        if generation != _generation:
            # The catalog was dropped while this map was embedded (external
            # file edit, reload): these aliases may be stale — hand them out
            # once, cache nothing, the next lookup embeds the new catalog.
            return vecs
        return _embed_cache.setdefault(key, vecs)


def prewarm_alias_embeddings() -> None:
    """Embed every alias of both catalogs once, so the first pose/expression
    match of a chat turn does not pay one embedding call per alias on the
    event loop. Meant for a background thread at server start (the lifespan
    runs it after the provider manager is up, so an external route resolves).
    Never raises."""
    try:
        from app.core.embedding import embed
        for axis in ("expression", "pose"):
            vecs = _alias_embeddings(axis, embed)
            logger.info("Alias embeddings warmed: %s (%d aliases)", axis, len(vecs))
    except Exception as e:
        logger.warning("Alias embedding warm-up failed: %s", e)


def resolve_to_catalog(text: str, axis: str, _embed=None) -> Tuple[str, str]:
    """Maps free text onto a catalog key. Never raises, never returns an
    unknown key. `_embed` overrides the embedding function (tests).

    Order: exact alias → decision model (plan-decision-models.md § 4.2,
    only when its point is active) → embedding → default."""
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return get_default_key(axis), "empty"
    index = _alias_index(axis)
    if cleaned in index:
        return index[cleaned], "exact"
    picked, point, dkey = _decide_catalog_key(cleaned, axis)
    if picked is not None:
        return picked
    key, how = _resolve_by_embedding(cleaned, axis, index, _embed)
    if dkey:
        _record_catalog_outcome(point, dkey, axis, key, how)
    return key, how


def _decide_catalog_key(cleaned: str, axis: str) -> Tuple[Optional[Tuple[str, str]], str, str]:
    """Ask the decision point of this axis. Returns (result or None, point, key);
    never raises — any failure means the usual path."""
    try:
        from app.core import decision, decision_points
        point = decision_points.CATALOG_POINTS.get(axis, "")
        if not point or not decision.is_active(point):
            return None, "", ""
        dkey = f"{axis}:{uuid.uuid4().hex[:8]}"
        questions, then = decision_points.catalog_questions(axis)
        d = decision.decide(point, {"text": cleaned}, questions, key=dkey, then=then)
        entry = d.answers.get("entry") if d else None
        if entry is None:
            return None, point, dkey
        if entry.value == decision_points.NONE_KEY:
            decision.mark_taken(point, dkey)
            record_candidate(axis, cleaned, "", None)
            return (get_default_key(axis), "decision_none"), point, dkey
        if entry.value in get_catalog(axis):
            decision.mark_taken(point, dkey)
            return (entry.value, "decision"), point, dkey
        return None, point, dkey
    except Exception as e:
        logger.debug("decision catalog match failed (%s): %s", axis, e)
        return None, "", ""


def _record_catalog_outcome(point: str, dkey: str, axis: str, key: str, how: str) -> None:
    """What the usual path chose — the shadow comparison (fallback counts as none)."""
    try:
        from app.core import decision, decision_points
        actual = {"entry": key if how == "embedding" else decision_points.NONE_KEY}
        if how == "embedding" and axis == "pose":
            g = group_of(key)
            if g:
                actual["group"] = g
        decision.record_outcome(point, dkey, actual)
    except Exception as e:
        logger.debug("decision catalog outcome failed (%s): %s", axis, e)


def _resolve_by_embedding(cleaned: str, axis: str, index: Dict[str, str],
                          _embed=None) -> Tuple[str, str]:
    """The embedding match (unchanged behaviour since the pose catalog)."""
    if _embed is None:
        from app.core.embedding import embed as _embed
    query = _embed(cleaned)
    if query:
        best_alias, best_score = "", 0.0
        for alias, vec in _alias_embeddings(axis, _embed).items():
            score = cosine_similarity(query, vec)
            if score > best_score:
                best_alias, best_score = alias, score
        if best_alias and best_score >= CATALOG_THRESHOLD:
            # A catalog edit racing the embedding warm-up can leave the alias
            # embeddings holding aliases this fresh index no longer knows —
            # fall through to the fallback rather than break "never raises".
            hit = index.get(best_alias)
            if hit:
                return hit, "embedding"
        record_candidate(axis, cleaned, index.get(best_alias, ""), 1.0 - best_score)
        return get_default_key(axis), "fallback"
    # no embedding available at all: fall back, still record the miss
    record_candidate(axis, cleaned, "", None)
    return get_default_key(axis), "fallback"


def split_key_detail(text: str, axis: str = "pose") -> Tuple[str, str]:
    """``"<alias>: <detail>"`` → ``(key, detail)`` — the shape every LLM
    producer hands over since the key/detail split (plan-pose-key-detail.md).

    The head before the FIRST colon must be a catalog alias (key or synonym,
    case and padding tolerated) and is canonicalised to its key. A text that
    is an alias as a whole is ``(key, "")``. Anything else is ``("", text)``
    — the whole text stays the detail, a head that is not an alias is not a
    key the caller may trust. Never raises."""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    index = _alias_index(axis)
    head, sep, tail = raw.partition(":")
    if sep:
        key = index.get(head.strip().lower(), "")
        if key:
            return key, tail.strip()
    key = index.get(raw.lower(), "")
    if key:
        return key, ""
    return "", raw


# ── Candidates: free text the catalog could not absorb ───────────────────
def record_candidate(axis: str, raw_text: str, nearest_key: str,
                     distance: Optional[float]) -> None:
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    now = utc_now_iso()
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO pose_candidates (axis, raw_text, nearest_key, distance, "
                " count, status, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, 1, 'open', ?, ?) "
                "ON CONFLICT(axis, raw_text) DO UPDATE SET "
                " count = count + 1, last_seen = excluded.last_seen",
                (axis, raw_text[:200], nearest_key or "", distance, now, now),
            )
    except Exception as e:
        logger.debug("record_candidate failed: %s", e)


def list_candidates(axis: str, status: str = "open") -> List[dict]:
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT raw_text, nearest_key, distance, count, first_seen, last_seen "
            "FROM pose_candidates WHERE axis=? AND status=? "
            "ORDER BY count DESC, last_seen DESC", (axis, status)).fetchall()
        return [{"raw_text": r[0], "nearest_key": r[1], "distance": r[2],
                 "count": r[3], "first_seen": r[4], "last_seen": r[5]} for r in rows]
    except Exception as e:
        logger.debug("list_candidates failed: %s", e)
        return []


def delete_candidate(axis: str, raw_text: str) -> bool:
    """Removes a candidate row for good.

    Used when a candidate was APPROVED into the catalog: the text now resolves
    exactly, so it will not come back — and if the approval was imperfect (a
    synonym that still misses), the miss has to surface as a fresh candidate
    instead of hiding behind a terminal status.
    """
    from app.core.db import transaction
    try:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM pose_candidates WHERE axis=? AND raw_text=?",
                (axis, raw_text))
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("delete_candidate failed: %s", e)
        return False


def set_candidate_status(axis: str, raw_text: str, status: str) -> bool:
    from app.core.db import transaction
    try:
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE pose_candidates SET status=? WHERE axis=? AND raw_text=?",
                (status, axis, raw_text))
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("set_candidate_status failed: %s", e)
        return False


def dismiss_all_candidates(axis: str) -> int:
    """Marks every OPEN candidate of ``axis`` as dismissed; returns how many
    rows changed. The reset after a producer change: rows recorded under the
    old free-text rules describe nothing about the new ones."""
    from app.core.db import transaction
    try:
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE pose_candidates SET status='dismissed' "
                "WHERE axis=? AND status='open'", (axis,))
            return int(cur.rowcount or 0)
    except Exception as e:
        logger.warning("dismiss_all_candidates failed: %s", e)
        return 0


# ── Flavor: what survives of the free text next to the catalog key ───────
_FLAVOR_MAX_CHARS = 120


# First-person words in a flavor: the flavor is what a BYSTANDER sees, third
# person, and an RP line copied over verbatim ("ich greife nach meiner Tasche")
# reads as "<name> is ich greife …" in every prompt. "I" is case-sensitive
# (the lowercase letter is no pronoun); the rest is matched in any case.
_FIRST_PERSON_UPPER_I = re.compile(r"\bI\b")
_FIRST_PERSON_WORDS = re.compile(
    r"\b(ich|mich|mir|mein(e[mnrs]?)?|wir|uns|unser(e[mnrs]?)?"
    r"|my|me|we|us|our)\b", re.IGNORECASE)


def is_first_person(text: str) -> bool:
    """Whether ``text`` speaks in the first person (I/my/ich/mein/wir/…)."""
    t = text or ""
    return bool(_FIRST_PERSON_UPPER_I.search(t) or _FIRST_PERSON_WORDS.search(t))


def sanitize_flavor(text: str) -> str:
    """Sanitized 'flavor' prompt text: quoted speech removed, character names
    removed (exact stored names only - NO first/last-name resolution, standing
    directive), first sentence, hard cap 120 chars. A first-person sentence
    (``is_first_person``) yields ``""`` — the caller keeps the key and drops
    the detail."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # German pairs are „…“ — the closing class must contain “ as well.
    raw = re.sub(r'["“„][^"“”„]*["”“]', "", raw)
    try:
        from app.models.character import list_available_characters
        names = list_available_characters()
    except Exception:
        names = []
    for name in sorted(names, key=len, reverse=True):
        if name:
            raw = re.sub(rf"\b{re.escape(name)}\b", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s{2,}", " ", raw).strip(" ,;:-")
    first = re.split(r"(?<=[.!?])\s", raw, maxsplit=1)[0].strip()
    if is_first_person(first):
        return ""
    return first[:_FLAVOR_MAX_CHARS].strip()
