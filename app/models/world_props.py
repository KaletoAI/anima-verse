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
from typing import Any, Dict, List, Optional

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
    library read: the ONE scale number, the orientation fix and the tier maps
    of its ACTIVE variants.

    ``max_m`` is the largest REAL edge of the object in metres and
    ``measure`` is ``xyz`` — the very scale law the scene props run on
    (§ B2, ``place()``), so a bench outside a house is the same size as the
    same bench inside it. The mesh's own extent says nothing: normalisation
    destroyed it.

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
    dims = [_finite(meta.get(k)) or 0.0
            for k in ("width_m", "height_m", "depth_m")]
    return {
        "name": str(meta.get("name") or prop_id),
        "max_m": round(max(dims) or 1.0, 3),
        "fix_euler": {a: _finite(rot.get(a)) or 0.0 for a in ("x", "y", "z")},
        "variant_maps": maps,
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
            "max_m": facts["max_m"],
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
        out.append(spec)
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
