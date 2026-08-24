"""The EXPLORATION MEMORY — which patches of the world a character has been in.

The overview veil of the 3D client used to subtract the known LOCATIONS from
the world frame and nothing else: between two places the world stayed covered
forever, however often one walked through it (finding B14). This module is the
memory that was missing — the server's record of where somebody has actually
stood, so the veil can spare that ground too.

**THE VEIL IS BACK, AND IT IS TWO CONSUMERS** (2026-08-24,
``plan-fog-schleier-v2.md``; between 2026-08-19 and that day the memory ran
without a single reader, decision E1.3, and kept being written so that a world
played in the meantime would not start remembering only on the day the new
veil arrived):

  * the PICTURE — ``client3d/src/scene/fogVeil.ts`` hazes over every cell the
    avatar has not explored, fetched through ``GET /play/explored`` whenever
    ``explored_sig`` moves;
  * the FILTER — :func:`seen_cells` / :func:`point_explored` drop the FIGURES
    standing on that ground out of the player's worldmap payload
    (``core/world_ops.build_worldmap_payload``). The haze is not a curtain a
    client could pull aside: what is under it never leaves the server.

**THE UNIT IS A 64 m CELL, ANCHORED AT THE WORLD ORIGIN.** The same edge length
and the same anchor as the veil's own tiling (``FOG_TILE_M``) and the automatic
undergrowth (``UNDERGROWTH_CELL_M``): cell ``(cx, cz)`` covers
``[cx·64, (cx+1)·64)`` on x and the same on z, so ``cell_of`` is one floor
division and no two consumers can disagree about where a cell starts. Anchored
at the origin rather than at ``world_bounds`` for the reason the heightfield
lattice is (§ A16): a world that grows at its border must not move a single
cell somebody has already explored.

**MARKING IS 3×3.** Standing in a cell marks it AND its eight neighbours — the
near view, not the footprint of one's boots. A walker crossing a cell border
therefore never leaves a hard edge of cloud a metre beside the figure.

**TWO CALLERS, both where a point is actually written:**
  * ``routes/play.py`` ``POST /play/pos`` — the avatar's own report, AFTER it
    was accepted (a refused report moved nobody and must remember nothing),
  * ``core/travel_engine.advance_all_journeys`` — the travel ticker, for every
    character with a point (a journey, a scheduler jump, an admin move).

**THE IN-PROCESS CACHE IS WHAT MAKES THIS FREE.** A walking avatar reports up
to four times a second and would otherwise fire nine ``INSERT OR IGNORE``
statements per report for a cell it marked a quarter of a second ago.
:data:`_last_cell` remembers the cell each character was last marked in; while
the figure stays inside it, :func:`mark_explored` returns without touching the
DB at all. Process-local on purpose — it is a write-avoidance cache, not state:
a restart costs exactly one redundant 3×3 write per character.

**ADDITIVE ONLY.** Nothing here ever deletes a cell, and there is no UI to
(decision, v1). :func:`explored_sig` leans on that: see there.

SIZE. One cell is 4096 m² of world. A long-lived world can accumulate tens of
thousands of them — 60 000 cells is 245 km² of explored ground, and that is the
order of magnitude the payload of ``GET /play/explored`` was measured against
(see :func:`explored_cells`).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("exploration")

#: Edge length of one exploration cell in world metres. The veil's own tile
#: (``FOG_TILE_M``, while the veil existed) was the SAME number by intent: the
#: client spares whole cells out of the veil, and a cell that did not line up
#: with the tiling would have to be cut out of a quad instead of replacing one.
#: The automatic undergrowth (``UNDERGROWTH_CELL_M`` = 64 in
#: ``client3d/src/scene/scatterLod.ts``) still uses it, so the number keeps a
#: live twin.
EXPLORED_CELL_M = 64.0

#: How many cells in every direction around the character's own are marked.
#: 1 = the 3×3 block, which is the near view (see the module header).
MARK_RADIUS_CELLS = 1

#: The cell each character was last marked in — see the module header. Keyed by
#: character name, never persisted.
_last_cell: Dict[str, Tuple[int, int]] = {}


def cell_of(v: float) -> int:
    """The cell index a world coordinate falls into (floor division).

    Negative coordinates included: −1 m is cell −1, not cell 0, which is what
    makes the raster continuous across the origin instead of doubling the
    width of the cell that straddles it.
    """
    return int(math.floor(v / EXPLORED_CELL_M))


def cell_key(cx: int, cz: int) -> str:
    """Wire form of one cell: ``"cx,cz"`` — the same shape the heightfield tile
    index uses, and the key the client builds its lookup set from."""
    return f"{cx},{cz}"


def cells_around(x: float, z: float) -> List[Tuple[int, int]]:
    """The block of cells a character at (x, z) marks — pure, hand-checkable.

    ``MARK_RADIUS_CELLS`` in each direction around the cell of the point, so
    nine cells today. Deterministic order (cx ascending, cz ascending inside).
    """
    cx0, cz0 = cell_of(x), cell_of(z)
    r = MARK_RADIUS_CELLS
    return [(cx0 + dx, cz0 + dz)
            for dx in range(-r, r + 1)
            for dz in range(-r, r + 1)]


def mark_explored(character_name: str, x: float, z: float) -> int:
    """Record that ``character_name`` stands at (x, z). Returns how many cells
    were NEW — 0 means the memory already covered this spot.

    Cheap by construction: a non-finite point, an empty name or a character
    that has not left its cell since the last call returns before any DB work
    (see the module header on ``_last_cell``).
    """
    if not character_name:
        return 0
    if not (math.isfinite(x) and math.isfinite(z)):
        return 0
    here = (cell_of(x), cell_of(z))
    if _last_cell.get(character_name) == here:
        return 0
    from app.core.db import transaction
    added = 0
    try:
        with transaction() as conn:
            for cx, cz in cells_around(x, z):
                cur = conn.execute(
                    "INSERT OR IGNORE INTO explored_cells "
                    "(character_id, cx, cz) VALUES (?, ?, ?)",
                    (character_name, cx, cz))
                added += cur.rowcount or 0
    except Exception as e:
        # A memory is not worth refusing a movement over: the caller has
        # already written the position, and losing one 3×3 block only means the
        # veil covers ground somebody walked. The cache is NOT set in this
        # case, so the next report tries again.
        logger.warning("exploration mark failed for %s: %s", character_name, e)
        return 0
    _last_cell[character_name] = here
    if added:
        logger.debug("explored: %s +%d cell(s) around %s", character_name,
                     added, cell_key(*here))
    return added


def explored_cells(character_name: str) -> List[str]:
    """Every cell ``character_name`` has explored, as ``"cx,cz"`` keys.

    THE WHOLE LIST, in one answer. That is affordable because it is fetched
    ONCE per signature change and never on the poll: measured on a synthetic
    world, 60 000 cells (245 km² of explored ground — far more than any real
    world has) read in ~17 ms and serialise to roughly 600 kB of JSON. A
    payload that big arrives a handful of times per session, which is the same
    bargain ``GET /play/heightfield`` strikes.

    Sorted, so the answer is stable and diffable — the client builds a Set out
    of it and never cares about the order, but a smoke does.
    """
    if not character_name:
        return []
    from app.core.db import get_connection
    rows = get_connection().execute(
        "SELECT cx, cz FROM explored_cells WHERE character_id=? "
        "ORDER BY cx, cz", (character_name,)).fetchall()
    return [cell_key(r[0], r[1]) for r in rows]


def seen_cells(character_name: str,
               pos: Optional[Dict[str, float]] = None) -> Set[Tuple[int, int]]:
    """Every cell that counts as SEEN for the veil — the memory PLUS the near
    view of the point the character stands on right now.

    The union is the point of this function, and it is not a convenience: the
    memory is written by the two callers that persist a position
    (:func:`mark_explored`), so between "the avatar moved" and "the report was
    accepted" there is a window in which the ground under its own feet is not
    yet in the table. A filter that read the table alone would hide the
    neighbour standing next to the avatar for that window — a figure that
    blinks. The near view is exactly what :func:`mark_explored` will write, so
    the union anticipates it rather than inventing a second rule.

    ``pos`` is the character's own metre point or ``None`` (off the map, or a
    character with no point at all); without it the answer is the stored
    memory unchanged.

    WHAT IT COSTS, said out loud: ONE read of the whole memory per worldmap
    payload — i.e. per client per three-second poll. On the worlds this runs on
    that is well under a millisecond; the 17 ms measured in
    :func:`explored_cells` belongs to a synthetic 60 000-cell world (245 km² of
    walked ground) and is still smaller than the per-character profile loads
    the same payload does anyway. If such a world ever appears, the cheap fix
    is a memo keyed by :func:`explored_sig` — the signature IS the revision
    number of this table — and not a second, smaller filter beside this one.
    """
    cells = explored_cell_set(character_name)
    if pos:
        try:
            x, z = float(pos["x"]), float(pos["z"])
        except (KeyError, TypeError, ValueError):
            return cells
        if math.isfinite(x) and math.isfinite(z):
            cells.update(cells_around(x, z))
    return cells


def explored_cell_set(character_name: str) -> Set[Tuple[int, int]]:
    """The same rows as :func:`explored_cells`, as a lookup set of index pairs.

    The wire form is a string because the client builds a ``Set`` of strings
    out of it; the SERVER's own filter asks "is this point in an explored
    cell?" thousands of times per payload and would have to format a key per
    question. Same query, one representation each — never a parse of the
    other's.
    """
    if not character_name:
        return set()
    from app.core.db import get_connection
    rows = get_connection().execute(
        "SELECT cx, cz FROM explored_cells WHERE character_id=?",
        (character_name,)).fetchall()
    return {(r[0], r[1]) for r in rows}


def point_explored(cells: Set[Tuple[int, int]],
                   pos: Optional[Dict[str, float]]) -> bool:
    """Does ``pos`` lie in one of ``cells``?

    A point that does not exist is NOT hidden ground: a character the map does
    not place (an unplaced location's inhabitant) has no cell to be judged in,
    and answering ``False`` would make the veil's figure filter swallow it for
    a reason that has nothing to do with the veil. Same for a non-finite
    coordinate.
    """
    if not pos:
        return True
    try:
        x, z = float(pos["x"]), float(pos["z"])
    except (KeyError, TypeError, ValueError):
        return True
    if not (math.isfinite(x) and math.isfinite(z)):
        return True
    return (cell_of(x), cell_of(z)) in cells


def explored_sig(character_name: str) -> str:
    """Signature of one character's memory — rides on the worldmap poll.

    IT IS THE ROW COUNT, said out loud. The table is append-only (see the
    module header), so the count is a revision number: it moves when and only
    when a new cell is added, which is exactly what "refetch now" means. The
    alternatives were measured against the same synthetic 60 000-cell world:
    counting over the primary-key index costs ~1.4 ms, reading the cells
    themselves ~17 ms and hashing them far more — and ``MAX(rowid)`` is no
    cheaper here, because it too has to be filtered by ``character_id`` and
    therefore walks the same index range. 1.4 ms on a three-second poll of a
    world nobody has is nothing; a real world is two orders below it.

    **If a delete path is ever added, this has to change** — a cell removed and
    another added would leave the count where it was, and the client would keep
    a memory the server no longer has. That is the price of the simplest
    possible signature, and it is written down here rather than guarded for.

    An empty name (no avatar taken over) has no memory: empty signature, which
    can never equal a real one ("0" is what a character with no cells answers).
    """
    if not character_name:
        return ""
    from app.core.db import get_connection
    row = get_connection().execute(
        "SELECT COUNT(*) FROM explored_cells WHERE character_id=?",
        (character_name,)).fetchone()
    return str(row[0] if row else 0)


def reset_mark_cache() -> None:
    """Forget which cell everybody was last marked in — TEST HOOK.

    The cache is a write-avoidance device and the only way to observe it is to
    turn it off, which is what the red counter-check in
    ``scripts/smoke_exploration.py`` does.
    """
    _last_cell.clear()
