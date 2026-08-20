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

The ``low`` variant has a second, cheaper path: ``trigger_shrink`` reduces an
ALREADY STORED file mesh→mesh (``service.generate_mesh_variant``, gateway alias
``mesh-shrink``) instead of meshing the source image again. Same queue channel,
same pending flag; the result is a new gallery file selected for ``low``.
"""
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.model_store import (DEFAULT_TIER, ModelGallery, read_sidecar,
                                  write_sidecar)
from app.core.model_validate import MeshNotShrinkable, shrink_capability
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_STEM = "building"
# Tier a mesh→mesh reduction always writes into — a low variant IS the coarse
# resolution slot; there is nothing to choose.
LOW_TIER = "low"
# Marks a job key as a reduction, so a shrink and a fresh generation from the
# same-named input never collide in the double-click guard.
_SHRINK_KEY_PREFIX = "shrink:"

_lock = threading.Lock()
_generating: set = set()  # "<owner>:<stem>:<source image>" running job keys
# Subjects ("<owner>:<room_id>") whose distance mesh is being built right now.
_lod_building: set = set()
# Subjects whose distance-mesh build FAILED in this process. The automatic
# path skips them from then on: the demand comes from payload builds, so
# without this memory every poll would start the same doomed reduction again.
# The admin's explicit button ignores it and clears the entry on success. Not
# persisted — a restart (new Blender, new config) is a fair reason to retry.
# A FAILED button click lands in here too, and thereby also silences the
# automatic path for that subject: deliberate. The failure is an environment
# problem (Blender missing, mesh broken) — fix it and press the button again.
_lod_failed: set = set()


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
    source_file, rotation, tier, selected_for, tris, lod_ratio, shrinkable,
    shrink_reason, active}]``. ``tier`` is what the file was made for,
    ``selected_for`` the tiers it currently serves, ``source_file`` the stored
    model a low variant was reduced FROM, ``tris``/``lod_ratio`` what the CPU
    reduction left of it (0 = not a reduced model).

    ``shrinkable`` / ``shrink_reason`` come from the cheap capability probe
    (header + JSON chunk): a mesh without UVs/texture can never be reduced,
    and the row says so instead of offering a job that fails permanently."""
    owner = _owner_id(location_id)
    if not owner:
        return []
    gallery = _gallery(owner, room_id)
    active = find_building_model(location_id, room_id)
    out: List[Dict[str, Any]] = []
    for p in gallery.files():
        meta = read_sidecar(p)
        cap = shrink_capability(p)
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
            "source_file": meta.get("source_file", ""),
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
            "offset_y": float(meta.get("offset_y") or 0.0),
            "offset_x": float(meta.get("offset_x") or 0.0),
            "offset_z": float(meta.get("offset_z") or 0.0),
            "walk_y": float(meta.get("walk_y") or 0.0),
            "width_m": float(meta.get("width_m") or 0.0),
            # What the reduction actually cost this file (0 = not a reduced
            # model, or one from before these numbers were recorded).
            "tris": int(meta.get("tris") or 0),
            "lod_ratio": float(meta.get("lod_ratio") or 0.0),
            "shrinkable": bool(cap["shrinkable"]),
            "shrink_reason": cap["reason"],
            "active": bool(active and p.name == active.name),
            # A generated ROOF (docs/llm-blender-models.md): a building model
            # that is ONLY the roof and therefore does not replace the recipe
            # shell in the client. The row says so, because "the model" of a
            # location suddenly meaning "half of it" is exactly the kind of
            # thing a list has to state.
            "roof_only": bool(meta.get("roof_only")),
            "roof": meta.get("roof") or {},
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


def derive_plan_width_m(location_id: str, map3d: Any) -> float:
    """The location's width in METRES — the bounding box of its boundary, as
    ``world_ops._sanitize_map3d`` derived it; 0.0 when it has no area.

    ``has_scale_anchor`` went with contract v6 Nr. 2: room geometry carries
    its own metres, so there is no anchor left to require."""
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

    - the reference square is no longer a fixed 8 m. (The plot-share dial
      ``map3d.size`` that scaled the model against it is gone altogether with
      v6 Nr. 3 — a model scales through its declared ``width_m`` now, and an
      undeclared one fills the footprint, which is what the old default did.)
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
    stats = {"locations": 0, "plan_width": 0, "storey": 0, "sidecars": 0}
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


def _gen_key(owner_id: str, room_id: str = "", source_image: str = "",
             backend_glob: str = "", tier: str = "") -> str:
    """Job key: guards ONE generation per (target, source image, backend,
    tier) — several models from DIFFERENT images, and the SAME image through
    DIFFERENT backends or tiers, may run/queue concurrently (the backend GPU
    channel serializes them anyway); only a double-click of the identical job
    is rejected. Backend and tier are part of the key on purpose: comparing
    meshing methods on one picture means queueing that picture several times
    (bug report 2026-08-18 — the old image-only key swallowed every run after
    the first)."""
    return f"{owner_id}:{_stem(room_id)}:{source_image}:{backend_glob}:{tier}"


def claim_job(location_id: str, room_id: str = "", *, kind: str = "") -> bool:
    """Take the in-flight slot for a NON-meshing job on this subject.

    The mesh jobs key themselves by (image, backend, tier); a parametric build
    (the LLM-Blender roof) has none of the three, so it keys by its ``kind``
    alone — one roof build per location at a time. Same set as every other
    job, so ``is_pending`` and the admin panel's poll cover it without knowing
    it exists. False = one is already running.
    """
    owner = _owner_id(location_id)
    if not owner:
        return False
    key = _gen_key(owner, room_id, kind or "job")
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)
    return True


def release_job(location_id: str, room_id: str = "", *, kind: str = "") -> None:
    """Give the slot back — always in a ``finally``."""
    owner = _owner_id(location_id)
    if not owner:
        return
    with _lock:
        _generating.discard(_gen_key(owner, room_id, kind or "job"))


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
    default, blender}``. ``meta`` is the ACTIVE model's sidecar, ``models``
    the full list (newest first); ``backends`` = all available rig-'none' mesh
    backends, ``default`` = the admin default only when its rig is 'none';
    ``blender`` = the refinement runner's state, the gate for the CPU
    distance-mesh action (without a usable Blender the panel hides it instead
    of offering a button that always fails)."""
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
    # mesh→mesh aliases (the "Create low variant" action on a stored file) —
    # a separate list: they consume a MESH, so they must never show up in the
    # normal generate dialog.
    from app.core.model3d import list_shrink_backends
    out["shrink_backends"] = list_shrink_backends()["backends"]
    from app.blender import runner
    out["blender"] = runner.status()
    return out


def get_client_meta(location_id: str, room_id: str = "",
                    filename: str = "") -> Optional[Dict[str, Any]]:
    """Lean meta for the 3D client (``{format, rig, rotation, offset_y,
    tiers, signature}``) of the ACTIVE model, or None when there is none — no
    backend/model enumeration (that is the admin status's job). ``rotation``
    is the admin's persisted 90°-step orientation fix; the client applies it
    to the model root on load — and since v6 Nr. 10 it is the ONLY thing that
    turns a BUILDING mesh (the second dial ``map3d.rotation`` is gone). A
    ROOM diorama still has a placement yaw of its own in ``room.layout``,
    delivered via the scene recipe (see schnittstellen-3d.md).

    The placement dials come from the DEFAULT tier's sidecar: a low variant is
    the same object at a coarser resolution, so it inherits the orientation
    fix and the offsets rather than carrying dials of its own.

    ``filename`` picks ONE stored model instead of the active one — the admin
    preview of a non-active model needs the scene spec computed for the file
    it shows, or its placement dials write to a sidecar nobody renders
    (user finding 2026-08-19: Shift X/Z and walk height looked dead)."""
    owner = _owner_id(location_id)
    if not owner:
        return None
    gallery = _gallery(owner, room_id)
    p = (model_file_path(location_id, filename, room_id) if filename
         else gallery.find())
    if not p:
        return None
    meta = read_sidecar(p)
    tiers = gallery.tiers()
    # This meta IS the client payload's tier list (model/meta route and the
    # scene recipe's inputs), so it is where a missing distance mesh is
    # noticed and asked for — see :func:`_demand_low`.
    _demand_low(location_id, room_id, tiers, owner=owner)
    out = {"format": meta.get("format", p.suffix.lstrip(".").lower() or "glb"),
           "rig": meta.get("rig", "none"),
           "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
           # Real-size anchor of the model (0 = undeclared): the real width of
           # its largest side. THE scale law for rooms AND buildings since v6
           # Nr. 3 — undeclared, a building falls back to the location's own
           # width (map3d.plan_width_m); the former plot-share dial
           # (map3d.size) and the height/floors dials are gone.
           "width_m": float(meta.get("width_m") or 0.0),
           # The resolution tiers this subject HAS, each with its own change
           # key — the client asks for one with ?tier= and re-downloads that
           # file alone when its signature moves.
           "tiers": {t: {"signature": gallery.signature(t)}
                     for t in tiers},
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
    # The model is ONLY the roof (docs/llm-blender-models.md): it travels into
    # the scene spec as `roof_only`, and a renderer that reads it keeps the
    # recipe shell standing underneath instead of handing the far view over.
    # Absent = the model is the whole building, which is what it always was.
    if meta.get("roof_only"):
        out["roof_only"] = True
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
    ±500 — these are REAL metres of the location: an area model is scaled
    to its footprint edge, so a generated socle of 15 % on a 200 m location
    is a 30 m walk height, which the old ±25 could not express) on ONE
    model's sidecar (default: the active model). A MODEL property
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
        v = round(max(-500.0, min(500.0, v)), 3)
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
    """Persist a model's real-world width in metres — ROOM and BUILDING alike
    (sidecar; ``room_id`` picks the room model, empty the building one).

    THE scale dial since contract v6 Nr. 3: the model's largest side becomes
    this many metres, so a 15 m barn on a 40 m plot is a 15 m barn. The admin
    dials it against the reference figure instead of estimating a fraction of
    the plot. 0/empty = undeclared, and then the location's own width
    (``plan_width_m``, the boundary's bounding box) stands in — the number the
    retired ``map3d.size`` produced at its default 1, so nothing moves until
    someone declares a width. For a room the value additionally makes the
    CONTENT scale explicit (figures derive from it: 1.7 m × scale)."""
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
    if (tier or DEFAULT_TIER) == DEFAULT_TIER:
        request_low_tier(location_id, room_id, owner=owner)
    return meta


def save_roof_model(location_id: str, contents: bytes, *,
                    placement: Dict[str, Any],
                    description: Dict[str, Any]) -> Dict[str, Any]:
    """Store a GENERATED ROOF as the location's building model.

    The roof is built from numbers (``app/core/roof_model.py``), so its
    placement is not a dial anybody has to find: the sidecar is written with
    the width, the two plane offsets and the height offset the build itself
    computed, and the standard building placement (§ B2) then puts the mesh
    exactly on the vertices it was built from — scale 1, no calibration.

    ``roof_only`` is the display contract: this model is the roof and NOTHING
    else, so the client keeps the recipe shell underneath it instead of
    dropping it (docs/llm-blender-models.md).

    The file serves BOTH tiers. A roof is a handful of triangles — asking the
    distance-mesh path to decimate it would only risk destroying it, and
    leaving the ``low`` tier empty would make ``_demand_low`` try exactly that
    on every payload build.
    """
    owner = _owner_id(location_id)
    if not owner:
        raise ValueError("location not found")
    target = _gallery(owner).new_path()
    target.write_bytes(contents)
    meta = {
        "created_at": utc_now_iso(),
        "source": "roof_build",
        "format": "glb",
        "rig": "none",
        "tier": DEFAULT_TIER,
        "backend": "blender",
        "location": owner,
        "roof_only": True,
        "roof": dict(description or {}),
        "width_m": float(placement.get("width_m") or 0.0),
        "offset_x": float(placement.get("offset_x") or 0.0),
        "offset_z": float(placement.get("offset_z") or 0.0),
        "offset_y": float(placement.get("offset_y") or 0.0),
        "eaves_height_m": float(placement.get("eaves_height_m") or 0.0),
        "footprint_source": str(placement.get("footprint_source") or ""),
    }
    write_sidecar(target, meta)
    select_model(location_id, target.name, "", DEFAULT_TIER)
    select_model(location_id, target.name, "", LOW_TIER)
    logger.info("Roof model %s: %s (%d bytes, %s, width %.2f m)", owner,
                target.name, len(contents),
                (description or {}).get("form") or "?", meta["width_m"])
    return {**meta, "filename": target.name}


def _reduce_to_low(location_id: str, owner: str, room_id: str, src: Path,
                   ratio: float) -> Dict[str, Any]:
    """The reduction itself: Blender Decimate, then a NEW gallery file that
    becomes the ``low`` model. The caller holds the in-flight key.

    A failure is REMEMBERED (``_lod_failed``) and a success forgets it — that
    memory is what keeps the automatic path from grinding through the same
    broken model on every payload build."""
    from app.blender import refine
    key = f"{owner}:{room_id}"
    label = f"{owner}{f'/{room_id}' if room_id else ''}"
    out: Dict[str, Any] = {"ok": False, "tier": LOW_TIER, "ratio": ratio,
                           "tris": None, "tris_before": None, "size": 0,
                           "size_before": 0, "error": ""}
    res = refine.build_static_lod(src, ratio)
    if not res.get("ok"):
        _lod_failed.add(key)
        out["error"] = res.get("error") or "distance mesh not built"
        return out
    gallery = _gallery(owner, room_id)
    target = gallery.new_path()
    target.write_bytes(res["blob"])
    meta: Dict[str, Any] = {
        "created_at": utc_now_iso(),
        "source": "lod",
        "format": "glb",
        "rig": "none",
        "tier": LOW_TIER,
        "source_file": src.name,
        "lod_ratio": ratio,
        "tris": res.get("tris"),
        "tris_before": res.get("tris_before"),
        "location": owner,
    }
    if room_id:
        meta["room"] = room_id
    write_sidecar(target, meta)
    select_model(location_id, target.name, room_id, LOW_TIER)
    _lod_failed.discard(key)
    logger.info("Location model %s: distance mesh %s (%s -> %s tris)",
                label, target.name, res.get("tris_before"), res.get("tris"))
    out.update(ok=True, tris=res.get("tris"),
               tris_before=res.get("tris_before"),
               size=target.stat().st_size, size_before=src.stat().st_size)
    return out


def build_low_tier(location_id: str, room_id: str = "", ratio: float = 0.0,
                   force: bool = False) -> Dict[str, Any]:
    """Reduces the subject's full model to its distance mesh, BLOCKING (CPU).

    The result is a NEW gallery file selected as ``low`` — never an overwrite:
    the gallery keeps its history, so the previous low mesh stays selectable
    (or deletable). ``force`` is the admin's explicit rebuild; without it an
    existing low tier is left alone, which is what the automatic path wants.
    ``force`` also ignores the failure memory — the admin may have fixed the
    very thing that failed.

    ``ratio`` 0 takes the configured target for the subject kind (a room
    diorama tolerates far less reduction than a compact prop). One build per
    subject at a time, and the reduced mesh must pass the same static
    validation as a freshly delivered model. Returns ``{ok, tier, ratio, tris,
    tris_before, size, size_before, error}``.
    """
    from app.blender import refine
    ratio = float(ratio or refine.lod_ratio("room" if room_id else "building"))
    out: Dict[str, Any] = {"ok": False, "tier": LOW_TIER, "ratio": ratio,
                           "tris": None, "tris_before": None, "size": 0,
                           "size_before": 0, "error": ""}
    owner = _owner_id(location_id)
    if not owner:
        out["error"] = "no_model"
        return out
    g = _gallery(owner, room_id)
    src = g.find(DEFAULT_TIER, fallback=False)
    if not src or src.suffix.lower() != ".glb":
        out["error"] = "no_model"
        return out
    if LOW_TIER in g.tiers() and not force:
        out["error"] = "low tier already exists"
        return out
    key = f"{owner}:{room_id}"
    with _lock:
        if key in _lod_building:
            out["error"] = "a distance mesh of this subject is already being built"
            return out
        _lod_building.add(key)
    try:
        return _reduce_to_low(location_id, owner, room_id, src, ratio)
    finally:
        with _lock:
            _lod_building.discard(key)


def request_low_tier(location_id: str, room_id: str = "",
                     owner: str = "") -> None:
    """Builds the subject's missing distance mesh in the BACKGROUND (CPU), if
    switched on ("Build distance meshes on demand").

    The GPU route fills the low tier only when the alias delivered LOD stages
    (``lod_faces``); a generation without stages and every upload used to
    leave the tier to a batch run. Called wherever a payload lists this
    subject's tiers (see :func:`_demand_low`), so it runs on POLLED paths and
    every gate is ordered by COST: the config flag, the in-process sets and
    the global slot come first, the gallery read and the GLB probe only for a
    candidate that could start right now. With every slot busy a sweep over a
    whole world is therefore a set lookup per subject, not a GLB parse.

    ``owner`` is the gallery owner (clones share their template's gallery) and
    IS the key here — a caller that just resolved it hands it in, because
    resolving it costs a full location lookup and this runs on polled paths.

    The in-flight key is taken BEFORE the thread starts
    (``model3d.request_lod``'s pattern): two simultaneous payload builds must
    not start two reductions. Key and slot are both released again on EVERY
    way out — a rejected candidate, a failed thread start, or the build
    itself.

    Serving never waits and nothing is reported back — a distance mesh is an
    optimisation, and its absence is a fallback, not an error."""
    from app.blender import refine
    if not refine.auto_lod_enabled():
        return
    owner = owner or _owner_id(location_id)
    if not owner:
        return
    key = f"{owner}:{room_id}"
    if key in _lod_failed:
        return
    # An explicitly DESELECTED low tier is a decision, not a gap (user
    # finding 2026-08-20): the sentinel means "serve the full model at
    # distance", and refilling it here made the deselection impossible.
    if _gallery(owner, room_id).tier_declined(LOW_TIER):
        return
    with _lock:
        if key in _lod_building:
            return
        _lod_building.add(key)
    if not refine.take_lod_slot():
        with _lock:
            _lod_building.discard(key)
        return
    started = False
    try:
        g = _gallery(owner, room_id)
        src = g.find(DEFAULT_TIER, fallback=False)
        if not src or src.suffix.lower() != ".glb" or LOW_TIER in g.tiers():
            return
        # A model the store itself calls unreducible never becomes a low
        # variant; remembering it is what keeps the probe off the polled path.
        if not shrink_capability(src)["shrinkable"]:
            _lod_failed.add(key)
            return
        ratio = refine.lod_ratio("room" if room_id else "building")

        def _run() -> None:
            try:
                res = _reduce_to_low(location_id, owner, room_id, src, ratio)
                if not res.get("ok"):
                    logger.debug("Location model %s%s: distance mesh not "
                                 "built (%s)", owner,
                                 f"/{room_id}" if room_id else "",
                                 res.get("error"))
            except Exception as e:                          # noqa: BLE001
                _lod_failed.add(key)
                logger.warning("Location model %s: distance-mesh build "
                               "failed: %s", owner, e)
            finally:
                refine.free_lod_slot()
                with _lock:
                    _lod_building.discard(key)

        threading.Thread(target=_run, daemon=True,
                         name=f"locmodel-lod-{owner}").start()
        started = True
    finally:
        # Whatever ends this call without a running thread — a rejected
        # candidate or a refused thread start — gives both back. A leaked slot
        # would shrink the global limit for the rest of the process.
        if not started:
            refine.free_lod_slot()
            with _lock:
                _lod_building.discard(key)


def _demand_low(location_id: str, room_id: str, tiers: Any,
                owner: str = "") -> None:
    """A payload just listed this subject's resolution tiers — if ``low`` is
    missing while a full model exists, ask for it in the BACKGROUND.

    This is where the demand belongs, not on the serving route: every payload
    lists only the tiers a subject HAS, and every renderer picks from that
    list (``pickVariant``), so nobody ever requests a ``low`` that does not
    exist. The moment a client is TOLD there is no distance mesh is the moment
    to build one. ``owner`` travels with it — the caller resolved it to read
    the tiers in the first place."""
    if tiers and LOW_TIER not in tiers:
        request_low_tier(location_id, room_id, owner=owner)


def _store_lod_stages(gallery: ModelGallery, stages: List[Dict[str, Any]],
                      main_file: str, backend: str, owner: str,
                      room_id: str = "",
                      source_image: str = "",
                      texture_size: Any = None) -> str:
    """Store the LOD stages of ONE generation as their own gallery files and
    return the SMALLEST one's file name (the caller selects it as ``low``).

    A stage is a self-contained GLB baked from the same views as the main
    result (mesh-client-spec § 3.2) — a normal gallery file, not a companion.
    ``face_num`` is the REQUESTED count read from the delivered file name (the
    real one is only inside the GLB); ``source_file`` names this run's main
    mesh, so the pair is visible in the admin list. Further stages stay stored
    but unselected — the admin can promote any of them."""
    smallest = ""
    for stage in stages:
        blob = stage.get("blob") or b""
        if not blob:
            continue
        path = gallery.new_path(f".{stage.get('format') or 'glb'}")
        path.write_bytes(blob)
        meta: Dict[str, Any] = {
            "created_at": utc_now_iso(),
            "source": "lod",
            "format": stage.get("format") or "glb",
            "rig": "none",
            "tier": LOW_TIER,
            "backend": backend,
            "source_image": source_image,
            "source_file": main_file,
            "location": owner,
        }
        if stage.get("faces"):
            meta["face_num"] = int(stage["faces"])
        if texture_size:
            meta["texture_size"] = int(texture_size)
        if room_id:
            meta["room"] = room_id
        write_sidecar(path, meta)
        # The stages arrive sorted ascending, so the FIRST stored one is the
        # smallest — that is the one the distance view wants.
        if not smallest:
            smallest = path.name
    return smallest


def _generate(location_id: str, source_image: str, backend_glob: str,
              room_id: str = "", face_num: Any = None,
              texture_size: Any = None,
              tier: str = DEFAULT_TIER,
              lod_faces: Any = None) -> Dict[str, Any]:
    """Blocking mesh generation from a gallery image of the location. Runs on a
    worker thread (see trigger_generation). Adds a NEW model and selects it for
    ``tier`` — existing models stay (pick any of them in the admin panel).

    ``lod_faces`` asks the alias for reduced stages of the same bake
    (mesh-client-spec § 3.2); each becomes its own gallery file and the
    smallest is selected as the ``low`` variant, so ONE run leaves a complete
    full+low pair."""
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
        gallery = _gallery(owner, room_id)
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(gallery.new_path()),
            backend_glob=backend_glob,
            mesh_name=_stem(room_id) if room_id else owner,
            rig="none",
            face_num=face_num,
            texture_size=texture_size,
            lod_faces=lod_faces)
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
        low = _store_lod_stages(gallery, res.get("stages") or [], path.name,
                                res.get("backend", ""), owner, room_id,
                                source_image, texture_size)
        if low:
            select_model(location_id, low, room_id, LOW_TIER)
            logger.info("Location model %s: LOD stage %s selected as low "
                        "variant", owner, low)
        elif (tier or DEFAULT_TIER) == DEFAULT_TIER:
            # The alias delivered no stages — build the distance mesh locally
            # (CPU, seconds) instead of leaving the tier to a batch run.
            request_low_tier(location_id, room_id, owner=owner)
        return {"ok": True, "path": str(path), "meta": meta}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def _run(location_id: str, source_image: str, backend_glob: str,
         room_id: str = "", face_num: Any = None,
         texture_size: Any = None, tier: str = DEFAULT_TIER,
         lod_faces: Any = None) -> None:
    owner = _owner_id(location_id)
    try:
        _generate(location_id, source_image, backend_glob, room_id,
                  face_num=face_num, texture_size=texture_size, tier=tier,
                  lod_faces=lod_faces)
    except Exception as e:
        logger.error("Location model generation for %s failed: %s", owner, e)
    finally:
        with _lock:
            _generating.discard(_gen_key(owner, room_id, source_image,
                                         backend_glob, tier))


def trigger_generation(location_id: str, *, source_image: str,
                       backend_glob: str = "", room_id: str = "",
                       face_num: Any = None, texture_size: Any = None,
                       tier: str = DEFAULT_TIER,
                       lod_faces: Any = None) -> bool:
    """Start a building/room-model generation in the background. Generations
    from different source images run concurrently as far as the backend GPU
    channel allows (it serializes per backend); False only when THIS image
    is already being meshed for this target with THIS backend and tier
    (double-click guard — a different backend on the same image is a new,
    legitimate job). ``tier``
    says which resolution slot the result becomes (a low run is the same
    chain with a smaller face_num/texture_size).

    ``lod_faces`` asks the alias for reduced stages of the SAME bake — with it
    a single run fills both tiers instead of needing a second job."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    key = _gen_key(owner, room_id, source_image, backend_glob, tier)
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)
    threading.Thread(target=_run,
                     args=[location_id, source_image, backend_glob, room_id,
                           face_num, texture_size, tier, lod_faces],
                     daemon=True).start()
    return True


def _shrink(location_id: str, source_file: str, backend_glob: str,
            room_id: str = "", face_num: Any = None,
            texture_size: Any = None) -> Dict[str, Any]:
    """Blocking mesh→mesh reduction of ONE stored model. Runs on a worker
    thread (see trigger_shrink). Adds a NEW file to the same gallery and makes
    it the ``low`` variant — the source file stays untouched."""
    from app.imagegen.service import get_image_service
    owner = _owner_id(location_id)
    if not owner:
        return {"ok": False, "error": "location_not_found"}
    gallery = _gallery(owner, room_id)
    src = gallery.file(source_file)
    if not src:
        logger.warning("Location model %s: shrink source missing (%s)",
                       owner, source_file)
        return {"ok": False, "error": "source_model_missing"}

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
            "model3d_generation", f"Low variant: {label}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        res = get_image_service().generate_mesh_variant(
            source_model_path=str(src),
            output_path=str(gallery.new_path()),
            backend_glob=backend_glob,
            mesh_name=_stem(room_id) if room_id else owner,
            face_num=face_num,
            texture_size=texture_size)
        if not res.get("ok"):
            error = str(res.get("error") or "shrink failed")
            logger.error("Location model %s shrink failed: %s", owner, error)
            return {"ok": False, "error": error}

        path = Path(res["path"])
        meta = {
            "created_at": utc_now_iso(),
            "source": "shrink",
            "format": res.get("format", "glb"),
            "rig": "none",
            "tier": LOW_TIER,
            "backend": res.get("backend", ""),
            # Which stored file this variant was reduced FROM — the only way
            # to tell later which full mesh a low variant belongs to.
            "source_file": source_file,
            "location": owner,
        }
        if face_num:
            meta["face_num"] = int(face_num)
        if texture_size:
            meta["texture_size"] = int(texture_size)
        if room_id:
            meta["room"] = room_id
        write_sidecar(path, meta)
        select_model(location_id, path.name, room_id, LOW_TIER)
        logger.info("Location model %s: low variant %s (%d bytes, from %s)",
                    owner, path.name, path.stat().st_size, source_file)
        return {"ok": True, "path": str(path), "meta": meta}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def trigger_shrink(location_id: str, *, source_file: str,
                   backend_glob: str = "", room_id: str = "",
                   face_num: Any = None, texture_size: Any = None) -> bool:
    """Start a low-variant reduction of a STORED model in the background.
    False when this very file is already being reduced for this target
    (double-click guard) or the location is unknown. The result always lands
    in tier ``low`` — that is what the reduction is for.

    Raises ``MeshNotShrinkable`` when the source mesh brings no UVs/texture:
    the re-bake step of the gateway job has nothing to read, so the job would
    fail permanently. The UI disables the action; this is the second line."""
    owner = _owner_id(location_id)
    if not owner:
        return False
    src = _gallery(owner, room_id).file(source_file)
    if src:
        cap = shrink_capability(src)
        if not cap["shrinkable"]:
            raise MeshNotShrinkable(cap["reason"])
    key = _gen_key(owner, room_id, f"{_SHRINK_KEY_PREFIX}{source_file}")
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run() -> None:
        try:
            _shrink(location_id, source_file, backend_glob, room_id,
                    face_num=face_num, texture_size=texture_size)
        except Exception as e:
            logger.error("Location model shrink for %s failed: %s", owner, e)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
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
