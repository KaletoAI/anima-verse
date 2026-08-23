"""Painted terrain areas (Seamless World, E1).

A terrain area is one painted polygon on the free world map: a ``kind``
from the terrain-type catalog plus its outline in world metres. Areas may
overlap; ``z_order`` (then paint order) decides which one answers a point
query — the topmost wins, mirroring how the editor paints.

An area drawn with the LINE tool carries its recipe in ``meta.stroke`` — the
clicked centre line, the width of the ribbon it became and how that line is
bent on the way (straight/jagged/wavy). The polygon stays the truth; the
recipe only lets the editor put its handles back on the line.

An area also declares what GROWS on it: ``meta.scatter`` is a LIST of prop
scatters (model, density, target height), authored per area since finding
B17 — a forest with two kinds of tree and a clearing without any is one
painted shape each, and a terrain TYPE cannot say that.

A painted area may also shape the GROUND ITSELF: ``meta.relief_amplitude_m`` /
``meta.relief_wave_m`` bake random small hills into the world heightfield
wherever the area lies (§ A16.2) — which is why the writers here ring
``models.heightfield.note_world_write``. Since 2026-08-23 those two numbers
belong to the AREA and not to its kind: relief is a property of the shape
somebody painted, so two areas of one kind may be a rolling upland and a flat
pasture. There is no kind-level default and no fallback reader — an area that
authors nothing is flat.

Everything is validated ON WRITE: the readers downstream
(``world_geometry.point_in_polygon``) fail closed on malformed vertices
without a word in the log, so junk must never reach the DB in the first
place.
"""

import hashlib
import json
import math
import secrets
from typing import Any, Dict, List

from app.core.db import get_connection, transaction
from app.core.timeutils import utc_now_iso

#: Vertices ONE polygon may carry — the outline of a painted area, and by
#: mirror (``app.models.heightfield``) of a height area.
#:
#: It is the LINE TOOL that sets the number. A line drawn ``wavy`` is sampled
#: every 3 m so that its sine reads as a curve instead of a chain of corners
#: (``mapMath.decorateStroke``), which a kilometre of river spends 335 centre
#: points on; the mitred ribbon around a centre line is ``2n`` points wide, so
#: the budget is ``2 · MAX_DECORATED_POINTS + 2`` = 2050 — the centre-line cap
#: (1024) doubled, plus the two points one bevelled join adds.
#:
#: What the raise costs, measured where it is spent: the terrain masks are
#: baked by a SCANLINE (``core.terrain_layers.rank_grid``), i.e. O(rows × ring)
#: and not O(texels × ring), so a 670-point river costs 2.6× a 256-point one
#: on a bake that is cached by signature; ``pointInRing`` in the scatter
#: sampler is O(ring) per candidate, some 120 candidates per 64 m cell. The one
#: place the raise does NOT pay for itself is the O(n²) self-intersection
#: WARNING of the map-apply, which is why that one skips oversized rings
#: (``core.map_layout_apply.SELF_INTERSECT_MAX_POINTS``).
MAX_POINTS = 2050
#: Points the CENTRE LINE of a stroke recipe may carry (``meta.stroke``). The
#: editor's own gesture cap is far lower (100 clicks); this is the ceiling the
#: decorated line is budgeted against.
MAX_STROKE_POINTS = 1024
MAX_COORD = 100_000.0
MAX_Z_ORDER = 10_000
#: Scatter entries one area may carry. What GROWS on a painted area is
#: authored per area since finding B17 — several props on one meadow are the
#: point of the move, an unbounded list is a payload every client parses.
MAX_SCATTER_ENTRIES = 8
#: Longest ``model`` URL a scatter entry may name. Truncating one would only
#: produce a 404 that looks like a configured model.
MODEL_URL_MAX = 300
#: Widest gap a scatter row may keep between its own instances, in metres.
#: 100 m is a whole scatter cell and a half (``SCATTER_CELL_M`` = 64), so
#: anything above it can no longer be met inside the cell it is sampled in —
#: a bigger number would not thin the wood any further, it would only make the
#: rejection loop run out of tries.
MIN_SPACING_MAX_M = 100.0
#: How a stroke recipe bends its centre line before it is widened. The same
#: three the editor offers (``mapMath.STROKE_STYLES``); absent means straight,
#: which is what every line drawn before the styles existed is.
STROKE_STYLES = ("straight", "jagged", "wavy")
#: Roughly how far apart the deflections of a decorated line sit, in metres.
#: Below the lower bound a line is a saw blade nobody can see the shape of,
#: above the upper one the deflections are further apart than most lines are
#: long.
STROKE_SPACING_MIN_M = 2.0
STROKE_SPACING_MAX_M = 100.0
#: How far those deflections swing to either side of the line, in metres —
#: from "a hand-drawn wobble" to "a river delta".
STROKE_AMPLITUDE_MIN_M = 0.5
STROKE_AMPLITUDE_MAX_M = 30.0

#: MICRO-RELIEF, how high the random small hills of THIS PAINTED AREA stand, in
#: metres, as a half-swing around the authored level (the noise runs in
#: [-1, 1)). The upper clamp is a WALKABILITY limit, not a taste one: two
#: neighbouring support points may differ by at most 2*amp over one grid step,
#: i.e. atan(2*2.0 / 2.0) = 63 deg at the maximum on the tile grid the rules
#: read. The lower clamp is the smallest swing that is still visible at all;
#: anything below it means "no relief", and that is written by leaving the key
#: out.
#:
#: IT IS A PROPERTY OF THE AREA, NOT OF THE KIND (decision 2026-08-23). It used
#: to live on the terrain TYPE, which meant every meadow in the world was
#: exactly as bumpy as every other one: a rolling upland and a flat pasture
#: could not both be "grass". The two numbers moved here without a fallback
#: reader — a kind carries no relief any more, and an area that authors none is
#: flat.
RELIEF_AMPLITUDE_MIN_M, RELIEF_AMPLITUDE_MAX_M = 0.05, 2.0
#: How wide ONE swell of that relief is, in metres — the edge length of the
#: noise lattice. The lower clamp is 2 x ``heightfield.TILE_STEP_M``: NYQUIST.
#: A wave shorter than two support points cannot be carried by the grid at all,
#: it would only alias into a different, coarser pattern that changes whenever
#: the raster step doubles. It follows the TILE step, never the overview's —
#: the tiles are the raster every rule reads.
RELIEF_WAVE_MIN_M, RELIEF_WAVE_MAX_M = 4.0, 200.0
#: The wave an area with an amplitude but no authored wave gets — a swell every
#: 32 m, eight cells wide at the default overview step: gentle rolling, not a
#: choppy field. Read by ``core.heightfield.relief_params``, never stored.
DEFAULT_RELIEF_WAVE_M = 32.0


def _finite(value: Any) -> Any:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _sanitize_scatter_entry(raw: Any) -> Dict[str, Any]:
    """One entry of ``meta.scatter``, whitelisted to EXACTLY the four fields
    the renderers read (``packages/scene-render/src/scatter.ts`` and the
    editor's preview + area dialog).

    * ``density_per_100m2`` — instances per 100 m2 of the painted area. Always
      present: a junk, negative or absent density means "scatter nothing"
      (0.0), which is how both renderers read it.
    * ``height_m`` — TARGET height of the placed prop in metres: the model is
      scaled uniformly until its bounding box is this tall, and the built-in
      tuft is built this high. Only a value > 0 is a height; anything else
      loses the key, and then the RENDERER's default applies (2 m for a model,
      0.8 m for the tuft) — never the model's authored size, which says
      nothing in a world measured in metres.
    * ``model`` — URL of the prop mesh to instance (``/assets/props/<id>/model``,
      the very URL ``props.model_url`` hands out). A non-string, blank or
      over-long value loses the key and the tuft stands in its place.
    * ``min_spacing_m`` — the least distance THIS entry's own instances keep
      from each other, in metres. Only a value > 0 is a spacing; junk, 0 and
      anything negative lose the key, and then the sampler places as it always
      did. Clamped to ``MIN_SPACING_MAX_M`` (never refused: the field is a
      knob, like every other metre in this module) and kept to two decimals —
      a scatter is not authored in millimetres, and the number travels to
      every client.

    Raises ValueError when the entry is not an object at all — a list of junk
    is an authoring mistake worth a 400, not something to silently drop.
    """
    if not isinstance(raw, dict):
        raise ValueError("scatter entry must be an object")
    density = _finite(raw.get("density_per_100m2"))
    out: Dict[str, Any] = {
        "density_per_100m2": round(density, 3) if density and density > 0 else 0.0,
    }
    height = _finite(raw.get("height_m"))
    if height is not None and height > 0:
        out["height_m"] = round(height, 3)
    spacing = _finite(raw.get("min_spacing_m"))
    if spacing is not None and spacing > 0:
        out["min_spacing_m"] = round(min(spacing, MIN_SPACING_MAX_M), 2)
    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        url = model.strip()
        if len(url) <= MODEL_URL_MAX:
            out["model"] = url
    return out


def _sanitize_scatter_list(raw: Any) -> List[Dict[str, Any]]:
    """``meta.scatter`` as a whitelisted LIST — what this ground grows.

    The rest of ``meta`` stays free-form: a foreign key next to ``scatter``
    survives untouched. ``scatter`` does not, because it is a rendering
    contract — a stray key or a NaN density would travel from the editor to
    every client.

    Anything that is not a list at all raises: the field moved from the
    terrain TYPE to the area with finding B17 and it moved as a LIST, so a
    single object here is an old client, not an entry to be guessed at.
    """
    if not isinstance(raw, list):
        raise ValueError("meta.scatter must be a list of entries")
    if len(raw) > MAX_SCATTER_ENTRIES:
        raise ValueError(f"at most {MAX_SCATTER_ENTRIES} scatter entries")
    return [_sanitize_scatter_entry(entry) for entry in raw]


def _sanitize_points(raw: Any, minimum: int, what: str,
                     maximum: int = MAX_POINTS) -> List[List[float]]:
    """A list of ``[x, z]`` world metres, whitelisted and rounded — the outline
    of an area (``minimum`` 3, up to :data:`MAX_POINTS`) and the centre line of
    a stroke recipe (``minimum`` 2, up to :data:`MAX_STROKE_POINTS`) are the
    same kind of list under two names, and only the ceiling differs: the line
    is what the outline is GENERATED from, so it is half the outline's."""
    if not isinstance(raw, list) or not minimum <= len(raw) <= maximum:
        raise ValueError(f"{what} needs {minimum}..{maximum} points")
    pts: List[List[float]] = []
    for pt in raw:
        # A vertex may be any 2-element sequence of numbers. Everything else
        # is junk — including dicts, which raise KeyError on pt[0], and huge
        # integer literals (a JSON body may carry 400 digits), which raise
        # OverflowError. Both would otherwise escape as a 500 instead of a 400.
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            raise ValueError(f"{what} points must be [x, z] numbers")
        # isfinite first: every NaN comparison is False, so a plain range
        # check would wave NaN through and poison every later JSON response
        # (Starlette encodes with allow_nan=False -> 500).
        if not (math.isfinite(x) and math.isfinite(z)):
            raise ValueError(f"{what} coordinate must be a finite number")
        if abs(x) > MAX_COORD or abs(z) > MAX_COORD:
            raise ValueError(f"{what} coordinate out of range")
        pts.append([round(x, 2), round(z, 2)])
    return pts


def _sanitize_polygon(raw: Any) -> List[List[float]]:
    return _sanitize_points(raw, 3, "polygon")


def _sanitize_stroke(raw: Any) -> Dict[str, Any]:
    """``meta.stroke`` as a whitelist — the RECIPE of an area that was drawn as
    a line (``frontend/src/tabs/map/mapMath.decorateStroke`` →
    ``strokeToPolygon``).

    It is a recipe and nothing more: ``polygon`` stays the truth for every
    point query and every renderer, and an area whose recipe is dropped is
    simply an ordinary painted area again. That is exactly why it is
    whitelisted — the editor regenerates the polygon FROM these fields, so a
    stray key or a NaN spacing would reshape ground on the next edit.

    * ``points`` / ``width_m`` — the clicked centre line (2..1024 points, the
      same rounding and the same range as an outline) and the width of the
      ribbon it becomes. Both are required: without them there is nothing to
      regenerate, and a half-recipe would put the editor's handles where the
      shape is not.
    * ``style`` — ``straight`` (the line as clicked), ``jagged`` (triangular
      spikes across the line) or ``wavy`` (a soft sine). Anything else loses
      the key, and a missing style IS straight — the state every stroke drawn
      before the styles existed is in.
    * ``spacing_m`` — roughly how far apart the deflections sit, clamped to
      2..100 m; ``amplitude_m`` — how far they swing to either side, clamped
      to 0.5..30 m. Junk loses the key and the client's own default applies;
      clamping rather than refusing, because they are knobs, not a form.

    Raises ValueError when the recipe is not an object or its line is junk —
    a client that sends one at all is the editor, and a broken one is a defect
    worth a 400, not a shape to guess at.
    """
    if not isinstance(raw, dict):
        raise ValueError("meta.stroke must be an object")
    width = _finite(raw.get("width_m"))
    if width is None or width <= 0:
        raise ValueError("meta.stroke needs a positive width_m")
    out: Dict[str, Any] = {
        "points": _sanitize_points(raw.get("points"), 2, "meta.stroke",
                                   MAX_STROKE_POINTS),
        "width_m": round(width, 2),
    }
    style = raw.get("style")
    if isinstance(style, str) and style.strip() in STROKE_STYLES:
        out["style"] = style.strip()
    spacing = _finite(raw.get("spacing_m"))
    if spacing is not None:
        out["spacing_m"] = round(min(max(spacing, STROKE_SPACING_MIN_M),
                                     STROKE_SPACING_MAX_M), 2)
    amplitude = _finite(raw.get("amplitude_m"))
    if amplitude is not None:
        out["amplitude_m"] = round(min(max(amplitude, STROKE_AMPLITUDE_MIN_M),
                                       STROKE_AMPLITUDE_MAX_M), 2)
    return out


def _sanitize_water(meta: Dict[str, Any]) -> None:
    """What a painted area authors about its own WATER, in place (§ A16.3, W1).

    A water polygon is the one painted shape that changes the GROUND without
    being a height area: the bake sinks its bed under the mirror
    (``core.heightfield.HeightModel._carve``), which is what makes "distant
    terrain pokes through the water" impossible in the DATA instead of
    impossible in a shader. The fields are:

    * ``water_level`` — the mirror of STILL water, as a world y in metres. NO
      DEFAULT IS INVENTED HERE: an absent level means "not settled yet", and
      :func:`save_area` fills it in from the landscape (the median height along
      the rim) so it is a stored number from then on and stops moving when
      somebody paints a hill next to the lake. Only a finite number survives.
    * ``water_level_up`` / ``water_level_down`` — the two ends of a FLOWING
      water's tilted mirror, same units, same "absent = derive it" rule. Each
      overrides its own end of the profile; a plain ``water_level`` sets both.
    * ``flow_dir_deg`` — which way the water flows, 0…360, wrapped not clamped
      (``heightfield.sanitize_flow_dir``). It is what turns one level into a
      profile — and it is the same bearing the ripples scroll along. It is the
      field of POLYGON water: an area that was drawn as a LINE has an axis of
      its own and ``flow_along`` below wins over it.
    * ``flow_along`` — ``"forward"`` (the drawing order of ``meta.stroke``),
      ``"reverse"`` or absent (still): which way an area drawn as a LINE flows
      along that line (W4a). Anything else loses the key, which is the same
      "no flow" state as absent — a river follows its own bends, and one
      bearing cannot say where a meander runs.
    * ``flow_speed_m_s`` — HOW FAST this one water runs, in metres per second,
      0…2 (finding 2026-08-23: "the river now moves too slowly"). It is an
      OVERRIDE like the two widths: absent, the SURFACE KIND's ``flow_speed``
      dial answers (``core.surface_textures``), so a world tunes all its rivers
      in one place and only the odd torrent says its own number. It reaches the
      renderer as the LENGTH of the per-vertex flow attribute
      (``client3d/src/scene/waterPlane.ts``), never as a uniform — one material
      still serves every water of a kind. It changes NOTHING about the bake:
      the carve, the mirror and the flow AXIS are untouched, so it is not part
      of ``heightfield.WaterMeta``.
    * ``water_depth_m`` — how far the bed lies under the mirror once the shore
      ramp is done. Clamped, never refused: an authoring slip should make a
      shallow lake, not lose the shape somebody drew.
    * ``shore_ramp_m`` — how far INSIDE the rim that full depth is reached. 0
      is legal and means a step, the walled basin.
    * ``bed_kind`` — which ground the layer bake paints UNDER this water
      (§ A16.7). A terrain-kind id, unvalidated here for the reason
      ``surface`` is unvalidated on a type: a catalog is a living thing and a
      reference must survive the kind being renamed into existence later.

    THE MIRROR IS THE AREA'S ALONE, because two lakes in one world stand at two
    heights. THE TWO WIDTHS ARE ONLY AN OVERRIDE since W1: absent, the KIND's
    own defaults apply (``terrain_types.water_kind_defaults``), which is why
    they are dropped rather than defaulted when they are junk — a stored default
    would silently outrank the kind forever. Whether a kind is water at all is
    the catalog's answer (``terrain_types.is_water_kind``), never the name's.
    """
    from app.core.heightfield import (FLOW_ALONG_VALUES, WATER_DEPTH_MAX_M,
                                      WATER_DEPTH_MIN_M,
                                      WATER_SHORE_RAMP_MAX_M,
                                      WATER_SHORE_RAMP_MIN_M,
                                      sanitize_flow_dir)
    # SERVER OUTPUT NEVER COMES BACK IN. ``water_level_effective`` and
    # ``water_profile`` are computed on the read path
    # (``core.heightfield.with_effective_water_level``) so the editor can show
    # what the carve really used; ``meta`` is a full replace on every write, so
    # a client that round-trips what it read would otherwise store them. They
    # are dropped here, once.
    meta.pop("water_level_effective", None)
    meta.pop("water_profile", None)
    for key in ("water_level", "water_level_up", "water_level_down"):
        if key not in meta:
            continue
        level = _finite(meta.get(key))
        if level is None:
            meta.pop(key, None)
        else:
            meta[key] = round(level, 3)
    if "flow_dir_deg" in meta:
        flow = sanitize_flow_dir(meta.get("flow_dir_deg"))
        if flow is None:
            meta.pop("flow_dir_deg", None)
        else:
            meta["flow_dir_deg"] = flow
    if "flow_along" in meta:
        along = str(meta.get("flow_along") or "").strip().lower()
        if along in FLOW_ALONG_VALUES:
            meta["flow_along"] = along
        else:
            meta.pop("flow_along", None)
    if "flow_speed_m_s" in meta:
        # The SAME range the kind's dial has (`surface_textures._MATERIAL_RANGES`
        # `flow_speed`), so an area can say anything the kind could have said and
        # nothing more. Two decimals: a centimetre per second is finer than any
        # eye can tell on a ripple, and it keeps the stored number short.
        # Junk DROPS the key rather than storing 0 — 0 m/s is a legible authored
        # state (a frozen river) and must not be what a typo means.
        speed = _finite(meta.get("flow_speed_m_s"))
        if speed is None:
            meta.pop("flow_speed_m_s", None)
        else:
            meta["flow_speed_m_s"] = round(min(max(speed, 0.0), 2.0), 2)
    for key, low, high in (
            ("water_depth_m", WATER_DEPTH_MIN_M, WATER_DEPTH_MAX_M),
            ("shore_ramp_m", WATER_SHORE_RAMP_MIN_M, WATER_SHORE_RAMP_MAX_M)):
        if key not in meta:
            continue
        value = _finite(meta.get(key))
        if value is None:
            # NOT the module default: an unreadable override is no override,
            # and the KIND is the one that answers then.
            meta.pop(key, None)
        else:
            meta[key] = round(min(max(value, low), high), 3)
    if "bed_kind" in meta:
        bed = str(meta.get("bed_kind") or "").strip()[:40]
        if bed:
            meta["bed_kind"] = bed
        else:
            meta.pop("bed_kind", None)


def _sanitize_relief(meta: Dict[str, Any]) -> None:
    """The two MICRO-RELIEF numbers of one area, IN PLACE (§ A16.2).

    THE SHAPE RULE of every optional number in this world: a value that says
    nothing — absent, junk, non-finite, zero, negative — leaves NO key behind,
    so no reader ever has to tell "authored as 0" from "not authored". Anything
    else is CLAMPED rather than refused (an authoring slip should move the
    ground to the limit, not lose the whole area) and rounded to two decimals,
    the precision the editor offers. A number that only ROUNDS to zero says
    nothing either, hence the second test after the rounding.

    Whitelisted for EVERY area, not only for the kinds that used to carry
    relief: the kind has no say in this any more, and two areas of one kind are
    exactly the case the move was made for — a rolling upland and a flat
    pasture, both "grass".
    """
    for key, low, high in (
            ("relief_amplitude_m", RELIEF_AMPLITUDE_MIN_M,
             RELIEF_AMPLITUDE_MAX_M),
            ("relief_wave_m", RELIEF_WAVE_MIN_M, RELIEF_WAVE_MAX_M)):
        if key not in meta:
            continue
        num = _finite(meta.get(key))
        if num is None or num <= 0:
            meta.pop(key, None)
            continue
        value = round(min(max(num, low), high), 2)
        if value <= 0:
            meta.pop(key, None)
        else:
            meta[key] = value


def sanitize_area(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one area; raises ValueError on junk."""
    from app.core.terrain_types import effective_catalog
    if not isinstance(raw, dict):
        raise ValueError("terrain area must be an object")
    kind = str(raw.get("kind") or "").strip()
    if kind not in effective_catalog():
        raise ValueError(f"unknown terrain kind: {kind!r}")
    area_id = str(raw.get("id") or "").strip() or f"ta_{secrets.token_hex(4)}"
    # OverflowError included: stdlib json accepts the `Infinity` literal, and
    # int(inf) raises it — that happens BEFORE the clamp below, so without the
    # catch the body would 500 instead of falling back to the default layer.
    try:
        z_order = int(raw.get("z_order") or 0)
    except (TypeError, ValueError, OverflowError):
        z_order = 0
    # Clamped so an absurd layer number cannot blow past SQLite's 64-bit
    # INTEGER on insert.
    z_order = min(max(z_order, -MAX_Z_ORDER), MAX_Z_ORDER)
    meta = dict(raw.get("meta")) if isinstance(raw.get("meta"), dict) else {}
    # The ONE key of `meta` this module owns (finding B17). An empty list is
    # not "no scatter authored" but "authored to nothing", and it costs one
    # pair of brackets — so it is kept as sent rather than dropped.
    if "scatter" in meta:
        meta["scatter"] = _sanitize_scatter_list(meta["scatter"])
    # The other key this module owns: the recipe of a line-drawn area. The
    # polygon next to it stays the truth — this only has to survive well
    # enough for the editor to regenerate it.
    if "stroke" in meta:
        meta["stroke"] = _sanitize_stroke(meta["stroke"])
    # …and the three numbers of a WATER area (E1, § G4). They are whitelisted
    # for every area rather than only for a water kind: a kind may be flagged
    # as water AFTER a shape was painted with it, and a number that survived
    # that edit is one the author already set.
    _sanitize_water(meta)
    # …and the two MICRO-RELIEF numbers (§ A16.2). They live on the AREA since
    # 2026-08-23 — the kind carries no relief at all any more — and they are
    # whitelisted for every area for the same reason the water numbers are:
    # what a shape says about its own ground is the author's, whatever kind it
    # happens to wear at the moment.
    _sanitize_relief(meta)
    return {"id": area_id, "kind": kind,
            "polygon": _sanitize_polygon(raw.get("polygon")),
            "z_order": z_order,
            "meta": meta}


def with_scatter_props(areas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add what the PROP knows to every scatter entry naming one — ``variants``,
    ``model_variants``, ``prop_height_m``, ``sway_factor`` and
    ``ground_offset_m``, PAYLOAD ONLY, never stored (§ A9).

    The stored entry keeps its exactly four authored fields; every addition is
    a fact about the PROP, not about the painting, so they are derived when the
    areas are handed out instead of being frozen into the DB (a low variant
    generated afterwards, a corrected height, or a boulder later told to stand
    still would otherwise never reach a client).

    ``variants`` is ``{tier: "/assets/props/<id>/model?tier=<tier>"}`` for the
    tiers the prop HAS — the same map and the same ``pickVariant`` rule the
    scene payload uses for props and buildings; it stays away when the prop
    carries no mesh.

    ``model_variants`` is one such map per ACTIVE variant WITH a mesh, in the
    prop's own order, and it rides along ONLY when the prop really has more
    than one (§ B2 addendum) — exactly the rule of the scene payload
    (``scene_recipe._prop_models``) and of the world props next door
    (``world_props.payload_rows``). Element 0 IS ``variants``, the primary
    variant, so a consumer that never heard of the field renders what it always
    rendered, and the primary variant keeps its query-less URL, which is what
    keeps every client cache valid.

    WHICH variant a given instance shows is NOT resolved here, and that is the
    one place the terrain scatter differs from every other placement: its
    instances do not exist on the server. They are sampled client-side in a
    camera window (``@anima/scene-render scatterCellInstances``), so the server
    ships the LIST and the renderers run the one shared formula
    (``scatterVariantIndex``: ``(hash(cell seed) + candidate) mod count``) over
    the cell seed the sampler already uses. Same world, same cell, same mix, in
    every client and after every reload.

    ``prop_height_m`` is the prop's REAL height in metres from its library
    record — the target height a client falls back to when the entry authors
    none. A tree is a tree because the library says it is 8 m tall; the flat
    default only ever meant "nobody asked", and it made every wood
    avatar-high.

    ``ground_offset_m`` is how deep the prop stands in the ground — the SAME
    number its hand-set copies use in a room or on the world plane, because it
    belongs to the object. The instances of a painted scatter are seated by the
    client on its own height sampler (§ A9), so the value has to travel with
    the entry: the client adds it to ``heightAt(x, z)``. Like the wind factor
    it rides along ONLY when it is not the default 0.0.

    ``sway_factor`` is how much of its ground's wind this prop takes part in —
    the multiplier on the terrain kind's ``meta.sway_m``. It rides along ONLY
    when it is not the default 1.0, so an absent key means "bends fully" for
    every reader: a plain tuft entry without a prop behind it, a prop nobody
    has touched, and a foreign URL all read the same.

    No key at all when there is no model or when the URL is not the canonical
    prop URL (a foreign or absolute one names a mesh this world has no record
    for); a client without them behaves exactly as before.

    The areas are enriched IN PLACE (``list_areas`` builds fresh dicts per
    call) and handed back. All lookups touch the prop directory, so they are
    cached together per call: one read per DISTINCT prop, however many areas
    name it.
    """
    from app.core.model_store import variant_urls
    from app.core import props as _props

    cache: Dict[str, Dict[str, Any]] = {}
    for area in areas:
        meta = area.get("meta")
        scatter = meta.get("scatter") if isinstance(meta, dict) else None
        if not isinstance(scatter, list):
            continue
        for entry in scatter:
            if not isinstance(entry, dict):
                continue
            prop_id = _props.prop_id_from_model_url(entry.get("model"))
            if not prop_id:
                continue
            if prop_id not in cache:
                facts = _props.prop_scatter_facts(prop_id)
                base = f"/assets/props/{prop_id}/model"
                maps: List[Dict[str, str]] = []
                for pos, variant in enumerate(
                        _props.active_variant_tiers(prop_id)):
                    idx = int(variant.get("variant") or 0)
                    # The PRIMARY variant (list position 0) keeps the bare URL
                    # it has always had, whatever its store index — that
                    # identity is what keeps existing client caches valid.
                    maps.append(variant_urls(
                        base if pos == 0 else f"{base}?variant={idx}",
                        variant.get("tiers") or []))
                cache[prop_id] = {
                    "variants": maps,
                    "height": facts.get("height_m", 0.0),
                    "sway_factor": facts.get(
                        "sway_factor", _props.SWAY_FACTOR_DEFAULT),
                    "ground_offset_m": facts.get(
                        "ground_offset_m", _props.GROUND_OFFSET_DEFAULT),
                }
            known = cache[prop_id]
            if known["variants"]:
                entry["variants"] = dict(known["variants"][0])
                # Only a prop that really HAS more than one variant says so: a
                # one-element list beside an identical `variants` map would be
                # the same fact twice in every payload of every world.
                if len(known["variants"]) > 1:
                    entry["model_variants"] = [dict(m) for m in known["variants"]]
            # 0.0 is "no such prop", never "no height authored" — a record
            # always has one (see props.prop_scatter_facts).
            if known["height"] > 0:
                entry["prop_height_m"] = known["height"]
            # The default travels as ABSENCE, exactly as it is stored: sending
            # a 1.0 would make "no factor" and "the full factor" two payload
            # shapes for one and the same behaviour.
            if known["sway_factor"] != _props.SWAY_FACTOR_DEFAULT:
                entry["sway_factor"] = known["sway_factor"]
            # …and the very same law for the ground offset, whose default is
            # 0.0: a prop that stands ON the ground ships no key at all.
            if known["ground_offset_m"] != _props.GROUND_OFFSET_DEFAULT:
                entry["ground_offset_m"] = known["ground_offset_m"]
    return areas


def list_areas() -> List[Dict[str, Any]]:
    """All areas bottom-to-top: z_order, then paint order (rowid = insert
    order, which an update keeps). The LAST entry is drawn on top."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, kind, polygon, z_order, meta FROM terrain_areas "
        "ORDER BY z_order ASC, created_at ASC, rowid ASC").fetchall()
    out = []
    for r in rows:
        try:
            polygon = json.loads(r[2])
            meta = json.loads(r[4] or "{}")
        except (TypeError, ValueError):
            continue
        out.append({"id": r[0], "kind": r[1], "polygon": polygon,
                    "z_order": int(r[3] or 0),
                    "meta": meta if isinstance(meta, dict) else {}})
    return out


def area_exists(area_id: str) -> bool:
    """True when an area with this id is stored.

    ``save_area`` is an upsert, so the PUT route needs this ONE cheap lookup
    to answer 404 instead of resurrecting a just-deleted area under its old id.
    """
    area_id = (area_id or "").strip()
    if not area_id:
        return False
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM terrain_areas WHERE id=?",
                       (area_id,)).fetchone()
    return row is not None


def _note_relief_write() -> None:
    """A painted area may have moved the WORLD HEIGHTFIELD — check, then act.

    An area may carry random small hills of its own (:func:`_sanitize_relief`,
    per AREA since 2026-08-23), and they are baked into the world grid wherever
    it lies (``app/core/heightfield``, § A16.2) — as may a water polygon, which
    carves its bed. So painting is an authoring act on the RELIEF too, and the
    same hook that answers a moved location answers it: ``note_world_write``
    compares the signature of the cached field against the current one and only
    pays for a raster when the ground really moved. Painting a flat, dry area —
    the normal case — costs that comparison and nothing more.
    """
    from app.models.heightfield import note_world_write
    note_world_write()


def settle_water_level(area: Dict[str, Any]) -> Dict[str, Any]:
    """Freeze a WATER area's derived mirror into the stored meta (§ A16.3).

    THE DEFAULT IS A MEDIAN NATURAL HEIGHT ALONG THE RIM, and it is written
    down HERE, at save time, rather than being recomputed on every bake. The
    difference matters: a computed default follows the landscape, so painting a
    hill beside a lake would raise the lake — and a lake that moves when its
    neighbourhood is edited is exactly the kind of hidden coupling this plan
    exists to remove. Once stored it is a number the author owns and can drag.

    WHICH FIELD IS FROZEN FOLLOWS THE PROFILE (W1). Still water settles
    ``water_level``, one number. FLOWING water settles ``water_level_up`` and
    ``water_level_down`` — freezing a river into a single ``water_level`` would
    flatten the very tilt the author asked for the moment they saved. Each end
    is only written when the author left it open; a half-authored river keeps
    its authored end exactly.

    WHAT "FLOWING" MEANS IS THE BAKE'S ANSWER (``heightfield.is_flowing``, W4a),
    not a second reading of the fields here: an area drawn as a line and flowed
    along it (``flow_along``) is a river even without a ``flow_dir_deg``, and
    settling it as one still level would be exactly the flattening this rule
    exists to prevent. Only the two ENDS are frozen — the inner knots of a drawn
    line stay derived, because the line may be redrawn.

    A non-water kind and a world whose height model cannot be built (no DB in a
    smoke run) leave the area untouched: the bake derives the same numbers on
    the fly in that case, so nothing is lost but the stability.
    """
    from app.core.terrain_types import (effective_catalog, is_water_kind,
                                        water_kind_defaults)
    meta = area.get("meta")
    if not isinstance(meta, dict):
        return area
    kind = str(area.get("kind") or "")
    catalog = effective_catalog()
    if not is_water_kind(kind, catalog):
        return area
    from app.core.heightfield import build_model, is_flowing, water_meta
    from app.models import heightfield as store
    parsed = water_meta(area, water_kind_defaults(kind, catalog))
    if not is_flowing(parsed):
        if parsed.level is not None:
            return area
        keys = ("water_level",)
    else:
        keys = tuple(key for key, value in (("water_level_up",
                                             parsed.level_up),
                                            ("water_level_down",
                                             parsed.level_down))
                     if value is None and parsed.level is None)
        if not keys:
            return area
    if len(area.get("polygon") or []) < 3:
        return area
    model = build_model(store.list_height_areas(), (), list_areas(), catalog)
    # THE ONE DERIVATION, asked of the bake itself rather than re-spelled here:
    # the profile the model builds IS what the carve will use, so the number
    # frozen into the area is the number the ground already has.
    profile = model.water_profile_for(area.get("polygon"), parsed)
    for key in keys:
        meta[key] = round(profile.level_up if key != "water_level_down"
                          else profile.level_down, 3)
    return area


def save_area(raw: Any) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one area; returns the
    sanitized entry. Raises ValueError when the area is not usable."""
    area = settle_water_level(sanitize_area(raw))
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO terrain_areas (id, kind, polygon, z_order, meta, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, "
            "polygon=excluded.polygon, z_order=excluded.z_order, "
            "meta=excluded.meta, updated_at=excluded.updated_at",
            (area["id"], area["kind"],
             json.dumps(area["polygon"], ensure_ascii=False), area["z_order"],
             json.dumps(area["meta"], ensure_ascii=False), now, now))
    _note_relief_write()
    return area


def delete_area(area_id: str) -> bool:
    """Remove one area; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM terrain_areas WHERE id=?",
                           ((area_id or "").strip(),))
        deleted = cur.rowcount > 0
    if deleted:
        _note_relief_write()
    return deleted


def terrain_sig() -> str:
    """10-char signature over areas + the EFFECTIVE type catalog — bumps
    whenever the painted world changes, so polling clients know when to
    refetch (and the nav-grid cache key inherits it).

    The effective catalog, not the world rows alone (round 2 of the E8
    acceptance): the shared seed ``shared/terrain/types.json`` is half the
    answer every consumer gets, so a seed edit that changes a passability, a
    speed factor or a ``move_anim`` has to reach a running client and a
    running router the same way a world row does. It used to sit outside the
    signature, which meant a seed change was invisible until a restart while
    ``GET /play/terrain`` already served the new numbers under the old
    ``sig``.

    AND THE CUT CODE (``terrain_layers.LAYER_CUT_VERSION``): the masks a client
    draws are a function of the cut code as much as of the polygons, and this
    is the signature the worldmap poll carries — bumping the constant has to
    reach a running client, not only the mask caches inside this process.
    """
    from app.core.terrain_layers import LAYER_CUT_VERSION
    from app.core.terrain_types import effective_catalog
    from app.models.world_props import prop_boxes
    # The ENRICHED block, not the stored rows (2026-08-20, same doctrine as
    # the seed catalog above and the same fix world_props_sig applied): the
    # scatter enrichment (variant tier maps, prop heights) is half of what a
    # client consumes, and a prop gaining a variant or a low mesh has to
    # reach a running client the same way a painted row does. Hashing the
    # stored rows alone kept the old sig while /play/terrain already served
    # the new maps.
    #
    # AND THE PLACED PROPS' BOXES (2026-08-23), by the very same doctrine:
    # ``/play/terrain`` serves them (§ A9b) and the scatter is sampled around
    # them, so moving a bench one metre has to reach a running client — this
    # is the signature its ground hangs on, and nothing else in the poll
    # covers a world prop's geometry.
    basis = json.dumps({"code_version": LAYER_CUT_VERSION,
                        "areas": with_scatter_props(list_areas()),
                        "prop_boxes": prop_boxes(),
                        "types": effective_catalog()},
                       sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]
