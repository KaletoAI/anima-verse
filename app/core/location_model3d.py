"""Location building models + room models — the 3D models of a location.

Counterpart of ``app/core/model3d.py`` for locations. Since 2026-07-16 the
store keeps SEVERAL models per subject (like the image gallery): every
generation/upload adds a timestamped file, one of them is the ACTIVE model
the clients get. Keyed by the GALLERY OWNER id so clones share their
template's models. Stored parallel to the gallery images under
``locations/<owner_id>/model3d/``:

    building.glb / building_<ts>.glb   + matching .json sidecars
    room_<room_id>[_<ts>].glb          + matching .json sidecars
    selection.json                     — {"<stem>": {"<tier>": "<filename>"}}

The file mechanics themselves (timestamped files, per-file sidecars,
selection, ``__none__`` sentinel, resolution TIERS) live in
``app/core/model_store.py`` — the same gallery the prop store uses. Every
function here takes an optional ``tier`` (``full`` = the modelled quality and
the default, ``low`` = the overview mesh).

The un-timestamped names are the legacy single-model store — they stay valid
entries. Without a selection entry the NEWEST file is active; generation and
upload select their new file explicitly.

Rooms (AV3D-2) use the per-room stem in the same directory. Clone records
store ``rooms: []`` and inherit the template's room list on merge, so room
ids are template-identical — a room model automatically serves every placed
clone. Every function takes an optional ``room_id``; empty = building.

The source image is a gallery image of the location (an ``image_type="building"``
render — for rooms one assigned to the room, picked by the caller); generation
goes through ``service.generate_mesh(rig="none")`` on the backend queue
channel, as a background job with a pending flag — the same busy/serialization
contract as the character mesh.
"""
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.model_store import (DEFAULT_TIER, ModelGallery, read_sidecar,
                                  write_sidecar)
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_STEM = "building"

_lock = threading.Lock()
_generating: set = set()  # "<owner>:<stem>:<source image>" running job keys


def _stem(room_id: str = "") -> str:
    """File stem in the model dir: ``building`` or ``room_<room_id>``."""
    return f"room_{room_id}" if room_id else _STEM


def _owner_id(location_id: str) -> str:
    """The gallery owner id (clones redirect to their template) — the store key."""
    from app.models.world import _gallery_owner_id
    return _gallery_owner_id(location_id) or ""


def _model_dir(owner_id: str, *, create: bool = False) -> Path:
    """``locations/<owner_id>/model3d`` — created only on write paths (a read
    must not conjure a ghost directory)."""
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "locations" / owner_id / "model3d"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _gallery(owner_id: str, room_id: str = "") -> ModelGallery:
    """The shared gallery for one subject (location building or one room)."""
    return ModelGallery(_model_dir(owner_id), _stem(room_id))


def is_model_filename(filename: str, room_id: str = "") -> bool:
    """Route-level validation: the name belongs to this stem (also blocks
    path escapes and cross-stem deletes)."""
    return ModelGallery(Path("."), _stem(room_id)).matches(filename)


def _list_files(owner_id: str, room_id: str = "") -> List[Path]:
    """All stored model files of a stem, newest first."""
    return _gallery(owner_id, room_id).files()


# ── No mesh measurement (2026-07-28) ────────────────────────────────────
# Models used to be measured once at ingest (bounding box + the height of
# their "dominant walkable layer") so the composer could place a figure on a
# modelled floor without being told where it is. That is an automatic repair,
# and it failed exactly where it mattered: on the Bernstein Academy campus
# the roofs carry 0.38 of projected horizontal area against the ground's
# 0.67, so the heuristic called the ROOFS walkable and sank the whole model
# 7.7 real metres. The admin states the walk height (``walk_y``); nothing
# else may decide it. ``_MEASURED_KEYS`` are what a migration strips.
_MEASURED_KEYS = ("measured", "bbox_fixed", "walk_frac")


def find_building_model(location_id: str, room_id: str = "",
                        tier: str = "") -> Optional[Path]:
    """The ACTIVE model file of a location/room in ``tier`` (via the gallery
    owner), or None. A tier the subject does not have falls back to the best
    available one; the admin's "no model" sentinel suppresses all of them."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    return _gallery(owner, room_id).find(tier)


def select_model(location_id: str, filename: str, room_id: str = "",
                 tier: str = DEFAULT_TIER) -> bool:
    """Make ``filename`` the active model of the stem in ``tier``. An EMPTY
    filename deselects (user decision 2026-07-27): on the default tier the
    sentinel is persisted and nothing is rendered until another model is
    selected or generated, on any other tier that tier ceases to exist.
    False when a non-empty file does not belong to the stem or is missing."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    return _gallery(owner, room_id).select(filename, tier)


def list_models(location_id: str, room_id: str = "") -> List[Dict[str, Any]]:
    """All stored models of a stem for the admin UI, newest first:
    ``[{filename, format, created_at, backend, source, source_image,
    rotation, tier, selected_for, active}]``. ``tier`` is what the file was
    made for, ``selected_for`` the tiers it currently serves."""
    owner = _owner_id(location_id)
    if not owner:
        return []
    gallery = _gallery(owner, room_id)
    active = find_building_model(location_id, room_id)
    out: List[Dict[str, Any]] = []
    for p in gallery.files():
        meta = read_sidecar(p)
        out.append({
            "filename": p.name,
            "tier": gallery.tier_of(p),
            "selected_for": gallery.selected_for(p.name),
            "face_num": int(meta.get("face_num") or 0),
            "texture_size": int(meta.get("texture_size") or 0),
            "format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
            "created_at": meta.get("created_at", ""),
            "backend": meta.get("backend", ""),
            "source": meta.get("source", ""),
            "source_image": meta.get("source_image", ""),
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
            "offset_y": float(meta.get("offset_y") or 0.0),
            "offset_x": float(meta.get("offset_x") or 0.0),
            "offset_z": float(meta.get("offset_z") or 0.0),
            "walk_y": float(meta.get("walk_y") or 0.0),
            "width_m": float(meta.get("width_m") or 0.0),
            "active": bool(active and p.name == active.name),
        })
    return out


# ── Scale anchor ────────────────────────────────────────────────────────
# The detail view needs ONE real-world number: how many REAL metres the
# location's reference square spans. Since 2026-07-28 that is exactly
# ``map3d.plan_width_m`` and nothing else — the old second path (a model's
# declared height × the mesh's width-per-height ratio) died with the per-axis
# scaling it served. A mesh cannot state its own real size, so the anchor is
# a decision, not a measurement.

def _explicit_plan_width(map3d: Any) -> float:
    try:
        v = float((map3d or {}).get("plan_width_m") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return v if 0.5 <= v <= 500 else 0.0


def has_scale_anchor(location_id: str, map3d: Any) -> bool:
    """True when the location HAS a scale anchor (``map3d.plan_width_m``).
    ``location_id`` is kept for the callers' signature — no model is read."""
    return _explicit_plan_width(map3d) > 0


def derive_plan_width_m(location_id: str, map3d: Any) -> float:
    """The reference square's real width in METRES, 0.0 when unanchored."""
    return _explicit_plan_width(map3d)


# ── One-shot conversion to the one-frame / one-scale model ──────────────

# Bumped when the migration's CONTENT changes — the map3d part is idempotent,
# so a re-run only adds what the newer version cleans up.
_SCALE_FRAME_FLAG = "world.migration.scale_frame_v2"


def _legacy_plan_width(path: Path, meta: Dict[str, Any]) -> float:
    """The plan width the OLD chain derived from a building model:
    declared height × the mesh's width-per-height ratio. Only used to carry
    the value over — the derivation itself is gone."""
    try:
        height = float(meta.get("height_m") or 0)
    except (TypeError, ValueError):
        return 0.0
    if height <= 0 or path.suffix.lower() != ".glb":
        return 0.0
    from app.core.model_validate import glb_bounds
    from app.core.props import oriented_dims
    try:
        bounds = glb_bounds(path.read_bytes())
    except OSError:
        return 0.0
    if not bounds:
        return 0.0
    lo, hi = bounds
    od = oriented_dims([hi[i] - lo[i] for i in range(3)], meta.get("rotation"))
    if not od or od[1] <= 0:
        return 0.0
    return round(height * max(od[0], od[2]) / od[1], 3)


def migrate_scale_frame_once() -> Dict[str, int]:
    """Carry a world over to ONE frame and ONE scale factor (2026-07-28).

    What changed and therefore has to be converted once:

    - the reference square is no longer a fixed 8 m but ``map3d.extent_m``
      (default 10 = one map tile), and the model fills ``size × extent_m``
      instead of ``10 × 0.92 × size``. A ``size`` above 1 used to mean
      "overflow the tile" — that is now the job of ``extent_m``, so it moves
      there and ``size`` becomes 1.
    - ``plan_width_m`` is the ONLY scale anchor. Where it was derived from a
      model's ``height_m`` it is written out explicitly BEFORE that field
      disappears — otherwise the location would silently lose its scale.
    - the storey height is one dial in REAL metres (``storey_height_m``)
      instead of ``height_m / floors`` (real) or ``level_height`` (world).
    - ``walk_y`` counts in REAL metres now (it was world metres).
    - the cached auto-measurement (``bbox_fixed``/``walk_frac``) is dead
      weight: nothing decides the walk height any more except the admin.

    Idempotent via a world_kv flag; touches map3d in world.db and the model
    sidecars. Returns a small stats dict for the boot log.
    """
    from app.models.world import (_load_world_data, _save_world_data,
                                  get_world_setting, set_world_setting)
    if get_world_setting(_SCALE_FRAME_FLAG):
        return {}
    stats = {"locations": 0, "plan_width": 0, "storey": 0, "extent": 0,
             "sidecars": 0}
    wdata = _load_world_data()
    changed = False
    for loc in wdata.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        loc_id = str(loc.get("id") or "")
        map3d = loc.get("map3d")
        owner = _owner_id(loc_id) if loc_id else ""
        building = find_building_model(loc_id) if owner else None
        b_meta = read_sidecar(building) if building else {}

        if isinstance(map3d, dict) and map3d:
            plan_w = _explicit_plan_width(map3d)
            if plan_w <= 0 and building:
                plan_w = _legacy_plan_width(building, b_meta)
                if plan_w > 0:
                    map3d["plan_width_m"] = round(plan_w, 2)
                    stats["plan_width"] += 1
                    changed = True
            # k as it was BEFORE this migration — the old square was 8 m.
            k_old = 8.0 / plan_w if plan_w > 0 else 1.0
            if not map3d.get("storey_height_m"):
                storey_real = 0.0
                try:
                    floors = float(b_meta.get("floors") or 0)
                    height = float(b_meta.get("height_m") or 0)
                except (TypeError, ValueError):
                    floors = height = 0.0
                if floors > 0 and height > 0:
                    storey_real = height / floors
                elif map3d.get("level_height"):
                    # was WORLD metres — back to real
                    storey_real = float(map3d["level_height"]) / (k_old or 1.0)
                if storey_real > 0:
                    map3d["storey_height_m"] = round(
                        min(max(storey_real, 0.5), 50.0), 2)
                    stats["storey"] += 1
                    changed = True
            if map3d.pop("level_height", None) is not None:
                changed = True
            try:
                size = float(map3d.get("size") or 0)
            except (TypeError, ValueError):
                size = 0.0
            if size > 1:
                map3d["extent_m"] = round(min(10.0 * size, 40.0), 2)
                map3d["size"] = 1.0
                stats["extent"] += 1
                changed = True
            stats["locations"] += 1

        if not owner:
            continue
        # Sidecars: drop the two per-axis dials and the retired
        # auto-measurement, convert walk_y from world to real metres.
        room_ids = [str(r.get("id") or "") for r in (loc.get("rooms") or [])
                    if isinstance(r, dict) and r.get("id")]
        plan_w = _explicit_plan_width(loc.get("map3d"))
        k_old = 8.0 / plan_w if plan_w > 0 else 1.0
        for room_id in [""] + room_ids:
            for path in _list_files(owner, room_id):
                meta = read_sidecar(path)
                if not meta:
                    continue
                touched = False
                for dead in ("height_m", "floors", *_MEASURED_KEYS):
                    if meta.pop(dead, None) is not None:
                        touched = True
                walk = meta.get("walk_y")
                if walk is not None and float(walk or 0) > 0 and k_old > 0:
                    meta["walk_y"] = round(float(walk) / k_old, 3)
                    touched = True
                if touched:
                    write_sidecar(path, meta)
                    stats["sidecars"] += 1
    if changed:
        _save_world_data(wdata)
    set_world_setting(_SCALE_FRAME_FLAG, "done")
    return stats


def _gen_key(owner_id: str, room_id: str = "", source_image: str = "") -> str:
    """Job key: guards ONE generation per (target, source image) — several
    models from DIFFERENT images may run/queue concurrently (the backend
    GPU channel serializes them anyway); only a double-click of the same
    job is rejected."""
    return f"{owner_id}:{_stem(room_id)}:{source_image}"


def is_pending(location_id: str, room_id: str = "") -> bool:
    """True while ANY generation job for this target is running/queued."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    prefix = f"{owner}:{_stem(room_id)}:"
    with _lock:
        return any(k.startswith(prefix) for k in _generating)


def get_building_info(location_id: str, room_id: str = "") -> Dict[str, Any]:
    """Status for the admin UI: ``{exists, pending, meta, models, backends,
    default}``. ``meta`` is the ACTIVE model's sidecar, ``models`` the full
    list (newest first); ``backends`` = all available rig-'none' mesh
    backends, ``default`` = the admin default only when its rig is 'none'."""
    from app.core.model3d import list_mesh_backends
    owner = _owner_id(location_id)
    path = find_building_model(location_id, room_id)
    out: Dict[str, Any] = {
        "exists": bool(path),
        "pending": is_pending(location_id, room_id),
        "meta": read_sidecar(path) if (owner and path) else {},
        "models": list_models(location_id, room_id),
        # The admin explicitly chose "no model" — distinct from "no files":
        # the UI shows the None entry as the active choice.
        "none_selected": bool(owner and _gallery(owner, room_id).none_selected()),
        # Which resolution tiers the subject actually has (the admin marks a
        # missing one instead of the store inventing a placeholder).
        "tiers": sorted(_gallery(owner, room_id).tiers()) if owner else [],
    }
    out.update(list_mesh_backends("none"))  # {"backends": [...], "default": ""}
    return out


def get_client_meta(location_id: str, room_id: str = "") -> Optional[Dict[str, Any]]:
    """Lean meta for the 3D client (``{format, rig, rotation, offset_y,
    tiers, signature}``) of the ACTIVE model, or None when there is none — no
    backend/model enumeration (that is the admin status's job). ``rotation``
    is the admin's persisted 90°-step orientation fix; the client applies it
    to the model root on load. Map placement (yaw + tile size) is NOT here —
    that is ``map3d.rotation``/``map3d.size`` on the location (rooms:
    ``room.layout``), delivered via the worldmap/locations (see
    schnittstellen-3d.md).

    The placement dials come from the DEFAULT tier's sidecar: a low variant is
    the same object at a coarser resolution, so it inherits the orientation
    fix and the offsets rather than carrying dials of its own."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    gallery = _gallery(owner, room_id)
    p = gallery.find()
    if not p:
        return None
    meta = read_sidecar(p)
    out = {"format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
           "rig": meta.get("rig", "none"),
           "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
           # Real-size anchor of a ROOM model (0 = undeclared): the real
           # width of the model's largest side — the diorama scales from it
           # like a prop. Buildings have none: their size follows the
           # location's own extent (map3d.extent_m × map3d.size), and their
           # former height/floors dials went with the per-axis scaling
           # (2026-07-28).
           "width_m": float(meta.get("width_m") or 0.0),
           # The resolution tiers this subject HAS, each with its own change
           # key — the client asks for one with ?tier= and re-downloads that
           # file alone when its signature moves.
           "tiers": {t: {"signature": gallery.signature(t)}
                     for t in gallery.tiers()},
           # Changes whenever ANOTHER model file becomes active in ANY tier
           # (new generation, upload, selection) — a running client polls the
           # meta and re-downloads on a signature change (AV3D-2 addendum);
           # rotation/offset edits are visible in the meta itself. Covering
           # every tier is the point: a freshly generated low variant used to
           # leave the signature untouched and stayed invisible.
           "signature": gallery.signature()}
    if room_id:
        # Rooms: the height offset lives in the FLOOR PLAN
        # (layout.model_offset_y), not on the model — the sidecar offsets are
        # gone here (2026-07-24). What IS a model property: the height a
        # figure walks at inside the diorama, stated by the admin.
        if meta.get("walk_y") is not None:
            out["walk_y"] = float(meta.get("walk_y") or 0.0)
        return out
    # Buildings: vertical placement offset in metres (model property —
    # reliefs have different socket thicknesses; negative sinks the model
    # into the terrain, e.g. a park) plus the tile-plane shift in world
    # metres (after the yaw: +x = east, +z = south — a building need not sit
    # centred on its tile). Every client applies them on load.
    out["offset_y"] = float(meta.get("offset_y") or 0.0)
    out["offset_x"] = float(meta.get("offset_x") or 0.0)
    out["offset_z"] = float(meta.get("offset_z") or 0.0)
    # Walkable surface above the model's lower edge (REAL metres, admin dial,
    # absent = 0 = the lower edge). For an area location this is THE anchor:
    # the model hangs that far below the height offset. Nothing measures it.
    if meta.get("walk_y") is not None:
        out["walk_y"] = float(meta.get("walk_y") or 0.0)
    return out


def model_file_path(location_id: str, filename: str,
                    room_id: str = "") -> Optional[Path]:
    """Path of ONE stored model by filename (admin preview of non-active
    models). Validated against the stem; None when missing/foreign."""
    owner = _owner_id(location_id)
    if not owner or not is_model_filename(filename, room_id):
        return None
    p = _model_dir(owner) / filename
    return p if p.exists() else None


def set_rotation(location_id: str, rotation: Dict[str, Any],
                 room_id: str = "", filename: str = "") -> Dict[str, Any]:
    """Persist the admin's orientation fix ({x,y,z} in degrees, FREE values
    0..359 — meshes also come out slightly tilted, not just axis-swapped)
    on ONE model's sidecar (default: the active model). Nobody can compute
    which way is up — the admin dials it in the viewer, every client
    applies it on load. Returns the updated sidecar meta."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("no model")
    p = (model_file_path(location_id, filename, room_id) if filename
         else find_building_model(location_id, room_id))
    if not p:
        raise ValueError("no model")
    meta = read_sidecar(p)
    cur = meta.get("rotation") or {}
    rot: Dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            v = float(rotation.get(axis, cur.get(axis, 0)) or 0)
        except (TypeError, ValueError):
            try:
                v = float(cur.get(axis, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
        v = round(v % 360, 1)
        # Whole numbers stay ints in the sidecar (no 90.0 noise).
        rot[axis] = int(v) if float(v).is_integer() else v
    if rot != cur:
        # Leftovers of the retired auto-measurement: a changed fix invalidated
        # them, and nothing reads them any more.
        for key in _MEASURED_KEYS:
            meta.pop(key, None)
    meta["rotation"] = rot
    write_sidecar(p, meta)
    return meta


def set_offset_y(location_id: str, offset_y: Any = None,
                 filename: str = "",
                 offset_x: Any = None, offset_z: Any = None,
                 walk_y: Any = None) -> Dict[str, Any]:
    """Persist a BUILDING model's placement offsets (metres, ±, clamped to
    ±25) on ONE model's sidecar (default: the active model). A MODEL property
    like the orientation fix — generated reliefs come with different socket
    thicknesses, and a negative value sinks e.g. a park into the terrain —
    and ``offset_x``/``offset_z`` shift the model on the TILE PLANE (world
    axes, applied after the yaw: +x = east, +z = south; the building need
    not sit centred on its tile). ``walk_y`` is the walkable surface of the
    model in metres above its bottom edge — the stand height of overlay
    zones on an area location (plan-area-locations.md); figures stood on the
    model's LOWER edge before it existed. ``None`` leaves a field untouched.
    Every client applies them on load. Returns the updated sidecar meta.

    Buildings only (2026-07-24): a ROOM's height offset lives in the floor
    plan as ``layout.model_offset_y``, its walkable floor as ``walk_y``."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("no model")
    p = (model_file_path(location_id, filename) if filename
         else find_building_model(location_id))
    if not p:
        raise ValueError("no model")
    meta = read_sidecar(p)
    for key, raw in (("offset_y", offset_y), ("offset_x", offset_x),
                     ("offset_z", offset_z), ("walk_y", walk_y)):
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            v = float(meta.get(key) or 0.0)
        v = round(max(-25.0, min(25.0, v)), 3)
        # 0 is a VALUE for walk_y, not "unset": it says the walkable surface
        # is the model's lower edge. The old rule dropped it because 0 used
        # to mean "measure it yourself" — with the measurement gone that made
        # the dial look dead (user finding 2026-07-28).
        meta[key] = v
    write_sidecar(p, meta)
    return meta


def _set_sidecar_number(location_id: str, field: str, value: Any, *,
                        room_id: str = "", filename: str = "",
                        cast=float, lo: float = 0.0,
                        hi: float = 500.0) -> Dict[str, Any]:
    """Shared setter for numeric sidecar fields on ONE model (default: the
    active one). value ≤ 0 / unparseable-and-absent removes the field."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("no model")
    p = (model_file_path(location_id, filename, room_id) if filename
         else find_building_model(location_id, room_id))
    if not p:
        raise ValueError("no model")
    meta = read_sidecar(p)
    try:
        v = cast(value)
    except (TypeError, ValueError):
        v = cast(meta.get(field) or 0)
    if v > 0:
        meta[field] = min(max(v, lo), hi)
        if cast is float:
            meta[field] = round(meta[field], 2)
    else:
        meta.pop(field, None)
    write_sidecar(p, meta)
    return meta


def set_width_m(location_id: str, width_m: Any,
                room_id: str = "", filename: str = "") -> Dict[str, Any]:
    """Persist a ROOM model's real-world width in metres (sidecar — the
    admin estimates the largest side of the room from the source image,
    e.g. "this living room is about 6 m wide"). Placement is unchanged
    (the model keeps filling its floor-plan rectangle); the value makes
    the room's CONTENT scale explicit — rect world extent / width_m — and
    figures in the room derive from it automatically (1.7 m × scale).
    0/empty = undeclared (figures fall back to storey_height / 3)."""
    return _set_sidecar_number(location_id, "width_m", width_m,
                               room_id=room_id, filename=filename)


def set_walk_y(location_id: str, room_id: str, walk_y: Any = None,
               filename: str = "") -> Dict[str, Any]:
    """Persist a model's WALKABLE floor height (sidecar; rooms AND buildings).

    Modelled floors are not flat: a raised podium, a sunken lounge, a hole in
    the mesh, or an area model whose terrain sits well above its lower edge —
    none of that is measurable from outside. ``walk_y`` states it once, in
    REAL metres above the model's lower edge (the unit every other length in
    this contract uses, × k at render time; 0 = the lower edge itself,
    clamped to 0..50). The scene payload delivers the absolute result as
    ``walk_y_world``, and for a GROUND model it is what ``offset_y`` is
    measured against. The admin dials it against the reference figure, like
    every other anchor. ``None``/empty removes the value; unlike the other
    numeric setters 0 is a MEANINGFUL value here, not "unset"."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("no model")
    p = (model_file_path(location_id, filename, room_id) if filename
         else find_building_model(location_id, room_id))
    if not p:
        raise ValueError("no model")
    meta = read_sidecar(p)
    if walk_y is None or f"{walk_y}".strip() == "":
        meta.pop("walk_y", None)
    else:
        try:
            v = float(walk_y)
        except (TypeError, ValueError):
            v = float(meta.get("walk_y") or 0.0)
        meta["walk_y"] = round(min(max(v, 0.0), 50.0), 3)
    write_sidecar(p, meta)
    return meta


def save_uploaded_building(location_id: str, contents: bytes, *,
                           source_image: str = "",
                           backend: str = "",
                           room_id: str = "",
                           tier: str = DEFAULT_TIER) -> Dict[str, Any]:
    """Store an uploaded GLB as a NEW model of the location/room and make it
    the active one of its tier. Validation is the caller's job
    (validate_static_glb)."""
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("location not found")
    target = _gallery(owner, room_id).new_path()
    target.write_bytes(contents)
    meta = {
        "created_at": utc_now_iso(),
        "source": "upload",
        "format": "glb",
        "rig": "none",
        "tier": tier or DEFAULT_TIER,
        "source_image": source_image,
        "backend": backend,
        "location": owner,
    }
    if room_id:
        meta["room"] = room_id
    write_sidecar(target, meta)
    select_model(location_id, target.name, room_id, tier)
    logger.info("Location model %s%s: uploaded (%d bytes) -> %s", owner,
                f"/{room_id}" if room_id else "", len(contents), target.name)
    return meta


def _generate(location_id: str, source_image: str, backend_glob: str,
              room_id: str = "", face_num: Any = None,
              texture_size: Any = None,
              tier: str = DEFAULT_TIER) -> Dict[str, Any]:
    """Blocking mesh generation from a gallery image of the location. Runs on a
    worker thread (see trigger_generation). Adds a NEW model and selects it for
    ``tier`` — existing models stay (pick any of them in the admin panel)."""
    from app.models.world import get_gallery_dir
    from app.imagegen.service import get_image_service
    owner = _owner_id(location_id)
    if not owner:
        return {"ok": False, "error": "location_not_found"}
    # The caller passes a gallery FILE NAME — resolve it against the location's
    # gallery dir (same owner redirect) and reject path escapes.
    if not source_image or "/" in source_image or ".." in source_image:
        return {"ok": False, "error": "bad_source_image"}
    src = get_gallery_dir(location_id) / source_image
    if not src.exists():
        logger.warning("Location model %s: source image missing (%s)", owner, source_image)
        return {"ok": False, "error": "source_image_missing"}

    # Header visibility, like the character mesh ("model3d_generation"): this
    # wrapper is the ONE tracked header task — the queue-channel entry of the
    # actual GPU job lives in the queue panel, not the header task list.
    from app.core.task_queue import get_task_queue
    label = owner
    try:
        from app.models.world import get_location_by_id, get_room_by_id
        loc = get_location_by_id(location_id) or {}
        label = loc.get("name") or owner
        if room_id:
            room = get_room_by_id(loc, room_id) or {}
            label = f"{label} / {room.get('name') or room_id}"
    except Exception:
        pass
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation",
            f"{'Room' if room_id else 'Building'} model: {label}",
            start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(_gallery(owner, room_id).new_path()),
            backend_glob=backend_glob,
            mesh_name=_stem(room_id) if room_id else owner,
            rig="none",
            face_num=face_num,
            texture_size=texture_size)
        if not res.get("ok"):
            error = str(res.get("error") or "generation failed")
            logger.error("Location model %s failed: %s", owner, error)
            return {"ok": False, "error": error}

        path = Path(res["path"])
        meta = {
            "created_at": utc_now_iso(),
            "source": "generated",
            "format": res.get("format", path.suffix.lstrip(".").lower() or "glb"),
            "rig": res.get("rig", "none"),
            "tier": tier or DEFAULT_TIER,
            "source_image": source_image,
            "backend": res.get("backend", ""),
            "location": owner,
        }
        # What this run was made WITH — the numbers that separate a full from
        # a low variant. They belong to the FILE, not to the subject.
        if face_num:
            meta["face_num"] = int(face_num)
        if texture_size:
            meta["texture_size"] = int(texture_size)
        if room_id:
            meta["room"] = room_id
        write_sidecar(path, meta)
        select_model(location_id, path.name, room_id, tier)
        logger.info("Location model %s: %s (%d bytes, from %s)", owner, path.name,
                    path.stat().st_size, source_image)
        return {"ok": True, "path": str(path), "meta": meta}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _run(location_id: str, source_image: str, backend_glob: str,
         room_id: str = "", face_num: Any = None,
         texture_size: Any = None, tier: str = DEFAULT_TIER) -> None:
    owner = _owner_id(location_id)
    try:
        _generate(location_id, source_image, backend_glob, room_id,
                  face_num=face_num, texture_size=texture_size, tier=tier)
    except Exception as e:
        logger.error("Location model generation for %s failed: %s", owner, e)
    finally:
        with _lock:
            _generating.discard(_gen_key(owner, room_id, source_image))


def trigger_generation(location_id: str, *, source_image: str,
                       backend_glob: str = "", room_id: str = "",
                       face_num: Any = None, texture_size: Any = None,
                       tier: str = DEFAULT_TIER) -> bool:
    """Start a building/room-model generation in the background. Generations
    from different source images run concurrently as far as the backend GPU
    channel allows (it serializes per backend); False only when THIS image
    is already being meshed for this target (double-click guard). ``tier``
    says which resolution slot the result becomes (a low run is the same
    chain with a smaller face_num/texture_size)."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    with _lock:
        if _gen_key(owner, room_id, source_image) in _generating:
            return False
        _generating.add(_gen_key(owner, room_id, source_image))
    threading.Thread(target=_run,
                     args=[location_id, source_image, backend_glob, room_id,
                           face_num, texture_size, tier],
                     daemon=True).start()
    return True


def delete_building_model(location_id: str, room_id: str = "",
                          filename: str = "") -> bool:
    """Remove ONE stored model (+ sidecar) by filename, or ALL models of the
    stem when ``filename`` is empty. A selection pointing at a removed file
    moves to the newest remaining one (default tier) or is dropped (any other
    tier). True if anything was removed."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    return _gallery(owner, room_id).delete(filename)
