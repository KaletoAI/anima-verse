"""World-plane props — single authored props OUTSIDE any location.

A landmark rock at a crossing, a signpost on a ridge, a bench in the
wilderness: one prop from the library, placed by hand at ONE point in world
metres. Until now the world plane only accepted DENSITY (``meta.scatter`` on
a painted terrain area, ``app/models/terrain.py``) — a scattered wood is a
statistic, and a statistic cannot say "this rock, here, turned that way".

The storage pattern is the painted area's, one table with the same
validate-on-write discipline: the readers downstream fail closed on malformed
numbers, so junk must never reach the DB. What differs is the geometry — a
placement is a POINT plus a yaw, not a polygon.

**Deco only, v1.** A world prop blocks nothing: it is not in the nav grid, it
does not push a figure aside and it never hides under fog — the payload block
is handed out unfiltered (decision E2.1). Something that must be walked around
is a location footprint or a painted area, not a prop.

**Soft cap** :data:`MAX_WORLD_PROPS`: a create beyond it is refused, and the
editor warns from :data:`WARN_WORLD_PROPS` on. Every placement is its own
draw call in both renderers (instancing the rest is parked), so the ceiling is
a rendering budget, not a storage one.

**Which mesh a placement shows** is :func:`variant_index` — the ONE formula,
resolved on the server exactly like the scattered copies of a room placement
(``props.scatter_variant_index``, § B2 addendum). Renderers read the number,
they never derive it.
"""

import hashlib
import json
import math
import secrets
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.timeutils import utc_now_iso

#: World coordinates a placement may carry, in metres — the same box the
#: painted areas live in (``terrain.MAX_COORD``).
MAX_COORD = 100_000.0
#: How far a placement may be lifted off (or sunk into) the ground it stands
#: on, in metres. A knob for a rock that should sit half-buried, not a second
#: elevation system — the terrain height under the point is sampled by the
#: renderer, never authored here.
MAX_OFFSET_Y = 50.0
#: How many world props ONE world may carry. A hard refusal, not a hint: each
#: placement is its own mesh in both renderers today.
MAX_WORLD_PROPS = 500
#: From here on the editor warns. Everything still works — this is the number
#: at which "a few landmarks" has turned into a budget question.
WARN_WORLD_PROPS = 200


def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _coord(value: Any, what: str) -> float:
    """One world-metre coordinate, validated and rounded to centimetres.

    isfinite first: every NaN comparison is False, so a plain range check
    would wave NaN through and poison every later JSON response (Starlette
    encodes with allow_nan=False → 500)."""
    num = _finite(value)
    if num is None:
        raise ValueError(f"{what} must be a finite number")
    if abs(num) > MAX_COORD:
        raise ValueError(f"{what} out of range")
    return round(num, 2)


def variant_index(placement_id: str, count: Any) -> int:
    """WHICH active variant a placement with NO authored index shows:
    ``md5(placement_id)[:8] mod count``.

    The world-prop counterpart of ``props.scatter_variant_index`` and the same
    contract (§ B2 addendum, § A9a): the SERVER resolves the index, the
    renderers execute it — so the same rock shows the same mesh in the 3D
    client, in a smoke and after every reload.

    The placement id is the seed because it is the only stable number a
    single placement has (a scattered copy has its area seed plus its instance
    number; a hand-placed one has neither). It is drawn from the id's MD5
    rather than from ``hash()``, which is salted per process and would give
    the same rock a different mesh on every restart.

    ``count`` 0 or less has nothing to choose from and answers 0.
    """
    try:
        n = int(count)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    digest = hashlib.md5(str(placement_id or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % n


def sanitize_world_prop(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one placement; raises ValueError on junk.

    ``prop_id`` must name a prop this world HAS — a dangling reference is an
    authoring mistake worth a 400, not a row that renders nothing forever.
    ``variant`` is optional: absent (or ``null``) means "let the formula
    decide" (:func:`variant_index`), a number means "this mesh, always".
    """
    from app.core import props as prop_store
    if not isinstance(raw, dict):
        raise ValueError("world prop must be an object")
    prop_id = prop_store.safe_prop_id(str(raw.get("prop_id") or ""))
    if not prop_id or not prop_store.read_sidecar(prop_id):
        raise ValueError(f"unknown prop: {raw.get('prop_id')!r}")
    placement_id = str(raw.get("id") or "").strip() or f"wp_{secrets.token_hex(4)}"
    yaw = _finite(raw.get("yaw_deg")) or 0.0
    offset = _finite(raw.get("offset_y")) or 0.0
    out: Dict[str, Any] = {
        "id": placement_id,
        "prop_id": prop_id,
        "x": _coord(raw.get("x"), "x"),
        "z": _coord(raw.get("z"), "z"),
        # A full turn is the same turn: the yaw wraps instead of being
        # refused, so a chip that keeps adding 15° never runs into a 400.
        "yaw_deg": round(yaw % 360, 1),
        # Clamped rather than refused — a lift is a knob, not a form.
        "offset_y": round(min(max(offset, -MAX_OFFSET_Y), MAX_OFFSET_Y), 3),
        "variant": None,
    }
    variant = raw.get("variant")
    if variant is not None and f"{variant}".strip() != "":
        try:
            idx = int(variant)
        except (TypeError, ValueError):
            raise ValueError("variant must be an integer index")
        if idx < 0:
            raise ValueError("variant must be an integer index")
        out["variant"] = idx
    return out


def _row(r: Any) -> Dict[str, Any]:
    return {"id": r[0], "prop_id": r[1],
            "x": float(r[2]), "z": float(r[3]),
            "yaw_deg": float(r[4] or 0.0), "offset_y": float(r[5] or 0.0),
            "variant": None if r[6] is None else int(r[6])}


def list_world_props() -> List[Dict[str, Any]]:
    """Every placement in authoring order (rowid = insert order, which an
    update keeps)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, prop_id, x, z, yaw_deg, offset_y, variant FROM world_props "
        "ORDER BY created_at ASC, rowid ASC").fetchall()
    return [_row(r) for r in rows]


def count_world_props() -> int:
    """How many placements the world carries — the number behind the cap and
    behind the editor's badge, without reading the rows."""
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM world_props").fetchone()
    return int(row[0] if row else 0)


def world_prop_exists(placement_id: str) -> bool:
    """True when a placement with this id is stored.

    :func:`save_world_prop` is an upsert, so the PUT route needs this ONE
    cheap lookup to answer 404 instead of resurrecting a just-deleted
    placement under its old id."""
    placement_id = (placement_id or "").strip()
    if not placement_id:
        return False
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM world_props WHERE id=?",
                       (placement_id,)).fetchone()
    return row is not None


def save_world_prop(raw: Any) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one placement; returns the
    sanitized entry. Raises ValueError when it is not usable — including the
    cap, which is checked on CREATE only: moving or re-aiming an existing
    placement must stay possible in a world that is already at the ceiling.
    """
    entry = sanitize_world_prop(raw)
    now = utc_now_iso()
    with transaction() as conn:
        row = conn.execute("SELECT 1 FROM world_props WHERE id=?",
                           (entry["id"],)).fetchone()
        if row is None:
            n = conn.execute("SELECT COUNT(*) FROM world_props").fetchone()[0]
            if int(n) >= MAX_WORLD_PROPS:
                raise ValueError(
                    f"at most {MAX_WORLD_PROPS} world props per world")
        conn.execute(
            "INSERT INTO world_props (id, prop_id, x, z, yaw_deg, offset_y, "
            "variant, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET prop_id=excluded.prop_id, "
            "x=excluded.x, z=excluded.z, yaw_deg=excluded.yaw_deg, "
            "offset_y=excluded.offset_y, variant=excluded.variant, "
            "updated_at=excluded.updated_at",
            (entry["id"], entry["prop_id"], entry["x"], entry["z"],
             entry["yaw_deg"], entry["offset_y"], entry["variant"], now, now))
    return entry


def delete_world_prop(placement_id: str) -> bool:
    """Remove one placement; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM world_props WHERE id=?",
                           ((placement_id or "").strip(),))
        return cur.rowcount > 0


def delete_world_props_of(prop_id: str) -> int:
    """Remove every placement of ONE prop and report how many went — what a
    deleted prop leaves behind. A placement whose prop is gone renders nothing
    and can never be repaired; keeping it would only keep the cap busy."""
    from app.core import props as prop_store
    pid = prop_store.safe_prop_id(prop_id)
    if not pid:
        return 0
    with transaction() as conn:
        cur = conn.execute("DELETE FROM world_props WHERE prop_id=?", (pid,))
        return int(cur.rowcount or 0)


# ── Payload ─────────────────────────────────────────────────────────────

def _prop_facts(prop_id: str) -> Dict[str, Any]:
    """What ONE prop contributes to every placement of it (§ A9a) — out of one
    library read: the scale number OF EACH ACTIVE VARIANT, the orientation fix
    and their tier maps.

    ``max_list[i]`` is the largest REAL edge in metres of the variant at
    payload position ``i``, and the row's ``max_m`` is the entry of the variant
    that row shows — a variant may override the prop's dims (2026-08-24), so
    the scale belongs to the mesh, not to the record. ``measure`` is ``xyz``,
    the very scale law the scene props run on (§ B2, ``place()``), so a bench
    outside a house is the same size as the same bench inside it. The mesh's
    own extent says nothing: normalisation destroyed it.

    ``{}`` when the prop is gone or carries no mesh at all — then there is
    nothing to render and the placement is dropped from the block.
    """
    from app.core import props as prop_store
    from app.core.model_store import variant_urls
    meta = prop_store.read_sidecar(prop_id)
    if not meta:
        return {}
    entries = prop_store.active_variant_tiers(prop_id)
    if not entries:
        return {}
    base = f"/assets/props/{prop_id}/model"
    maps: List[Dict[str, str]] = []
    for pos, entry in enumerate(entries):
        idx = int(entry.get("variant") or 0)
        # The PRIMARY variant (list position 0) keeps the bare URL it has
        # always had, whatever its store index — that identity is what keeps
        # existing client caches valid (§ B2 addendum).
        maps.append(variant_urls(base if pos == 0 else f"{base}?variant={idx}",
                                 entry.get("tiers") or []))
    rot = meta.get("rotation") if isinstance(meta.get("rotation"), dict) else {}
    # ONE scale number per published variant, in the same order as the URL maps
    # (2026-08-24): a variant may override the prop's dims, and a placement
    # that shows the sapling variant must be scaled to the sapling. The
    # library resolved override-or-inherit when it built the entries.
    max_list = [round(max(_finite(entry.get("dims", {}).get(k)) or 0.0
                          for k in ("width_m", "height_m", "depth_m")) or 1.0, 3)
                for entry in entries]
    return {
        "name": str(meta.get("name") or prop_id),
        "max_list": max_list,
        "fix_euler": {a: _finite(rot.get(a)) or 0.0 for a in ("x", "y", "z")},
        "variant_maps": maps,
        # How deep the OBJECT stands in the ground, wherever it stands — the
        # client seats a world prop itself (`heightAt(x, z) + offset_y`), so
        # this is the third term of that sum and travels with the row.
        "ground_offset_m": prop_store.ground_offset_of(meta),
    }


def payload_rows() -> List[Dict[str, Any]]:
    """The ``world_props`` block of the worldmap payload (§ A9a) — one row per
    RENDERABLE placement, unfiltered by fog or knowledge (deco is always
    visible).

    Placements whose prop is gone or has no mesh are DROPPED: a row with no
    model is a hole in every renderer's loop, and the editor's own list
    (``GET /world/world-props``) is where a dangling placement shows up as
    something to fix.

    Facts about the PROP (scale, orientation fix, tier maps) are derived here
    instead of being frozen into the DB, exactly like the scatter entries
    next door (``terrain.with_scatter_props``): a corrected size or a newly
    generated low mesh reaches a client on the next poll. One library read per
    DISTINCT prop, however many placements name it.
    """
    cache: Dict[str, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for row in list_world_props():
        pid = row["prop_id"]
        if pid not in cache:
            cache[pid] = _prop_facts(pid)
        facts = cache[pid]
        if not facts:
            continue
        maps: List[Dict[str, str]] = facts["variant_maps"]
        idx = (row["variant"] if row["variant"] is not None
               else variant_index(row["id"], len(maps)))
        # MODULO, never clamped: the variant count moves when an admin adds or
        # deletes a mesh, and a stored index must not make a placement vanish.
        idx = idx % len(maps) if maps else 0
        spec: Dict[str, Any] = {
            "id": row["id"],
            "prop_id": pid,
            "name": facts["name"],
            "x": row["x"], "z": row["z"],
            "yaw_deg": row["yaw_deg"],
            "offset_y": row["offset_y"],
            # The scale of the variant THIS row shows (2026-08-24) — same
            # index, same list, so a placement can never be scaled to a mesh
            # it is not drawing.
            "max_m": facts["max_list"][idx],
            "measure": "xyz",
            "fix_euler": facts["fix_euler"],
            # The PRIMARY variant's tier map — unchanged for every prop that
            # has one variant, which is every prop until an admin adds a
            # second one.
            "variants": maps[0],
        }
        # Only a prop that really HAS more than one variant says so: a
        # one-element list beside an identical `variants` map would be the
        # same fact twice in every payload of every world.
        if len(maps) > 1:
            spec["model_variants"] = maps
            spec["variant"] = idx
        # The prop's own sink, and only when it is not the default 0.0 (the
        # payload law of the scatter entries next door): absent = stands on the
        # ground. `offset_y` above stays the per-placement trim.
        if facts["ground_offset_m"]:
            spec["ground_offset_m"] = facts["ground_offset_m"]
        out.append(spec)
    return out


#: How much clear ground a placed prop keeps around its own edges, in metres —
#: added to BOTH half-extents of every box. A bench whose slats end exactly
#: where the grass begins reads as a bench in a hedge; a hand's width of bare
#: ground around it reads as a bench. It is deliberately ONE number for every
#: prop: a per-prop margin would be a second size dial next to the real dims,
#: authored nowhere and explainable to nobody.
PROP_BOX_MARGIN_M = 0.25


def prop_boxes() -> List[Dict[str, Any]]:
    """The GROUND BOX of every placed prop — what the scatter must not stand
    in (§ A9b, user finding 2026-08-23).

    A landmark rock, a signpost, a bench in the wilderness is placed by hand at
    one point, and until now the scatter grew straight through it: the sampler
    knew placed LOCATIONS (``scatter.ScatterFootprint``) and nothing else. One
    row per placement, and the renderers turn it into the very same footprint
    shape a location contributes — no new rule in the sampler, only a new
    source.

    One row is ``{id, x, z, yaw_deg, half_w, half_d}``: the placement's own
    anchor and turn, plus half the REAL width and depth of the VARIANT this
    placement shows (``props.prop_ground_extent``, resolved through the same
    :func:`variant_index` the payload row runs on) with
    :data:`PROP_BOX_MARGIN_M` on top. A variant may override the prop's dims
    (2026-08-24), and the ground a placement keeps clear is the ground its own
    mesh covers — the sapling variant of a pine claims less than the grown one.
    The half-extents run along the PROP's axes, so the box is a rotated
    rectangle and the consumers map its four corners through the one § A1.1
    transform.

    TWO KINDS OF PLACEMENT ARE LEFT OUT:

    * one whose prop this world has no record for — it has no size and renders
      nothing, so there is no box to keep clear. A prop that HAS a record but
      no mesh yet does get its box: the author placed it, and the ground it
      will stand on is already spoken for.
    * one standing inside a placed location's boundary — that outline already
      excludes the scatter over its whole area (``boundary_contains``), and a
      second, smaller shape inside it would be the same answer twice in every
      payload of every world.

    Scattered copies are never in here. Only what somebody placed by hand is
    "placed": every area's instances, its own and its neighbours', are sampled
    around these boxes.
    """
    from app.core.props import active_variant_tiers, prop_ground_extent
    from app.core.world_geometry import boundary_contains
    from app.models.world import list_locations

    rows = list_world_props()
    if not rows:
        return []
    locations = list_locations()
    # Per prop: the store indices it publishes (in payload position order) and
    # the primary extent. A prop with a record but NO mesh publishes nothing
    # and keeps its ground clear at the primary size — the author placed it,
    # and the mesh is what is still missing, not the claim on the ground.
    published: Dict[str, List[int]] = {}
    extents: Dict[Tuple[str, Optional[int]], Dict[str, float]] = {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        pid = row["prop_id"]
        if pid not in published:
            published[pid] = [int(e.get("variant") or 0)
                              for e in active_variant_tiers(pid)]
        store = published[pid]
        if store:
            pos = (row["variant"] if row["variant"] is not None
                   else variant_index(row["id"], len(store)))
            variant: Optional[int] = store[pos % len(store)]
        else:
            variant = None
        if (pid, variant) not in extents:
            extents[(pid, variant)] = prop_ground_extent(pid, variant)
        dims = extents[(pid, variant)]
        if not dims:
            continue
        x = row["x"]
        z = row["z"]
        if any(boundary_contains(loc, x, z) for loc in locations):
            continue
        out.append({
            "id": row["id"],
            "x": x,
            "z": z,
            "yaw_deg": row["yaw_deg"],
            "half_w": round(dims["width_m"] / 2 + PROP_BOX_MARGIN_M, 3),
            "half_d": round(dims["depth_m"] / 2 + PROP_BOX_MARGIN_M, 3),
        })
    return out


def world_props_sig(rows: Optional[List[Dict[str, Any]]] = None) -> str:
    """10-char signature over the FINISHED block — bumps whenever a placement
    moves, a prop is re-sized or a new mesh lands, and never otherwise.

    Hashed over the emitted rows rather than over the table, because the rows
    carry the derived half too: a low mesh generated in the background changes
    no DB row and still has to reach a running client.
    """
    basis = json.dumps(payload_rows() if rows is None else rows,
                       sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]
