"""THE EXTERIOR RENDER — a location's own geometry, photographed by Blender.

WHY THIS EXISTS. The building model of a location is meshed from a gallery
image of ``image_type "building-front"`` (``location_model3d``). A location
that never got such an image — drawn on the map, walls and storeys and all,
but never rendered — therefore has no model and no diorama, and the only ways
to get one were "generate a picture with an image backend" or "upload one". Yet
the building is already FULLY DESCRIBED: the scene recipe knows its walls, its
storeys and its floor plan, in metres. So Blender builds that volume and takes
a picture of it, and the picture goes into the gallery like any other.

    scene recipe  ->  volume model  ->  3/4 render  ->  gallery image
                                                        (image_type building-front)
                                                             |
                                          the EXISTING img2mesh pipeline

Nothing downstream learns a new word: the render is an ordinary gallery image,
so the 🧊 button on its tile meshes it, and the ordinary building-image
generation can use it as a REFERENCE if the user wants a styled variant first
(plan-blender-aussenansicht.md, decision of 2026-08-25: render -> image LLM ->
img2mesh, not a second model path).

THE DIVISION OF LABOUR is the one ``roof_model`` established: this module
DECIDES, ``app/blender/scripts/exterior.py`` EXECUTES. The script receives
finished vertices, faces, one material index per face and a camera; it computes
no geometry. Every number in the picture can therefore be traced back to a
function in here, and ``scripts/smoke_exterior_render.py`` checks the mesh by
hand WITHOUT a Blender binary.

WHERE THE GEOMETRY COMES FROM: ``scene_recipe.compose_scene`` and nowhere else
(CLAUDE.md — "geometry lives in exactly one place"). This module reads the
``walls`` and ``plates`` the composer already publishes and extrudes them; it
re-derives no wall, no storey height and no floor plan. The two things the
composer does NOT publish are added here and named:

* the GROUND PLATE. Since E5a storey 0 draws no plate — its floor is the
  terrain and its material is the layer bake. An isolated render has no
  terrain, so the volume would be a bottomless shell; this module lays the
  plate storey 0 used to have back down, at the composer's own constants
  (``LEVEL_PLATE_TOP`` / ``LEVEL_PLATE_THICKNESS``). A closed body also meshes
  better than an open one.
* the ROOF. The recipe's shell is open at the top on purpose (the far view
  wants to look in). :func:`roof_description` picks a form by the HEURISTIC
  the plan decided on — no new location field — and the body itself comes from
  ``roof_model.roof_geometry``, so a rendered roof and a BUILT roof (the
  parametric roof model) are the same geometry.

THE FRAME is the location's SCENE frame (origin at the anchor pin, x east,
y up, z south, metres). Blender is Z-up, so the job converts ONCE, here, with
the same mapping ``roof_model`` uses::

    (x, y, z)_scene  ->  (x, -z, y)_blender
"""
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

Vec2 = Tuple[float, float]

# ── The roof heuristic (plan-blender-aussenansicht.md, decision 2026-08-25) ──
#
# No new location field: the form follows from the footprint alone, and only
# two forms exist here. A house is gabled, a block is flat.
#
#: Footprint aspect (long side / short side) at or above which the roof is a
#: GABLE. The plan said "~1.3"; the threshold sits at 1.2 because a 10 x 8 m
#: house — aspect 1.25 — is a gabled house in every village this world has,
#: and rounding it into a flat-roofed block would be the wrong answer for the
#: most common plan there is.
ROOF_ASPECT_GABLE = 1.2
#: Footprint area at or above which the roof is FLAT whatever the aspect —
#: "sehr groß" from the plan, put at 400 m² (a 20 x 20 m block). It is also
#: what keeps ridges sane: a 35° gable over a deep building would stand
#: half its span above the eaves, and past this size that is a hall, not a
#: house.
ROOF_FLAT_AREA_M2 = 400.0
#: Roof pitch in degrees — the plan's "~35°", the middle of a normal domestic
#: range and the same default ``roof_model`` carries.
ROOF_PITCH_DEG = 35.0
#: Eaves overhang in metres (``roof_model.DEFAULT_OVERHANG_M``).
ROOF_OVERHANG_M = 0.4
#: The ridge runs ALONG the long side, so the two slopes face the two long
#: walls — what a builder does, and what ``roof_model`` calls ``auto``.
ROOF_RIDGE_AXIS = "auto"

# ── Materials: neutral volume, no textures ──────────────────────────────
#
# The render is MESH INPUT (the ``building`` use case's rules: isolated, plain
# neutral background, flat shadowless light). Textures on the volume would bake
# into the generated mesh as invented detail, so the body is painted in three
# flat tones that differ only enough to separate wall from roof from base from
# door.
WALL_TONE = "#d8d2c8"          # light warm grey — the wall surface
ROOF_TONE = "#6b5f57"          # darker — roof_model's own shingle default
PLATE_TONE = "#a8a29a"         # mid grey — floor plates and the ground plate
# The DOOR LEAF (§ B1 ``leaf``, 2026-08-25) is the FOURTH tone, and it is the
# reason a fourth exists at all: a door painted in WALL_TONE is a wall, and
# the mesher would rebuild a facade without doors from it. Same neutral,
# clearly darker — enough to read as a door, still no texture.
DOOR_TONE = "#5a4a3c"
#: One roughness for everything: a matte body has no highlights to bake in.
SURFACE_ROUGHNESS = 0.9

MATERIAL_WALL, MATERIAL_ROOF, MATERIAL_PLATE, MATERIAL_DOOR = 0, 1, 2, 3

# ── The camera (mesh-input rules, cf. app/core/model_refs.py) ───────────
#
#: Elevation above the horizon. High enough that the roof reads as a roof,
#: low enough that the facades keep their full height in frame.
CAM_ELEVATION_DEG = 35.0
#: Yaw off the front facade — a three-quarter view shows two sides at once,
#: which is what an image-to-3D pass needs to reconstruct a volume at all.
CAM_YAW_DEG = 35.0
#: "Orthographic-ish": a long lens at a long distance. A wide lens would
#: converge the verticals and the mesher would rebuild that convergence as
#: a tapered building.
CAM_LENS_MM = 85.0
CAM_SENSOR_MM = 36.0
#: How much larger than the body's bounding sphere the frame is — the margin
#: the ``building`` use case asks for ("with a margin around it").
CAM_FRAME_MARGIN = 1.15

RENDER_SIZE_PX = 1024
RENDER_SAMPLES = 64


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _r(v: float, nd: int = 4) -> float:
    return round(float(v) + 0.0, nd)


# ── Prisms: the one way a body is built here ────────────────────────────

def _shoelace2(poly: Sequence[Vec2]) -> float:
    """Twice the signed area of a polygon in the XZ plane."""
    total = 0.0
    for i, (x1, z1) in enumerate(poly):
        x2, z2 = poly[(i + 1) % len(poly)]
        total += x1 * z2 - x2 * z1
    return total


def prism(poly: Sequence[Vec2], y_lo: float, y_hi: float,
          base: int = 0) -> Tuple[List[List[float]], List[List[int]]]:
    """A closed body over ``poly`` between two heights, in the scene frame.

    THE WINDING is not a matter of taste — the renderers cull back faces, so a
    body wound inward is invisible. The orientation used here is the one
    ``roof_model``'s flat roof already proves outward
    (``smoke_roof_model.outward_normals``): the TOP cap runs in the direction
    that makes the shoelace NEGATIVE in the XZ plane, the bottom cap is its
    reverse, and each side quad closes top-to-bottom in that same order. The
    polygon is re-oriented here rather than trusted, because the plates come
    from author-drawn outlines whose winding nobody controls.

    ``base`` is the index the first vertex will have once the body is appended
    to a larger vertex list. Returns ``(vertices, faces)`` — an n-gon cap at
    either end plus one quad per edge, so a plate over an N-corner outline is
    2N vertices and N+2 faces. Blender tessellates the caps itself; a concave
    outline needs no triangulation on this side.
    """
    pts = [(float(x), float(z)) for x, z in poly]
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-9 \
            and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts = pts[:-1]                       # a closed ring repeats its first point
    if len(pts) < 3 or abs(y_hi - y_lo) < 1e-9:
        return [], []
    if _shoelace2(pts) > 0:
        pts = list(reversed(pts))
    n = len(pts)
    verts = [[_r(x), _r(y_hi), _r(z)] for x, z in pts]
    verts += [[_r(x), _r(y_lo), _r(z)] for x, z in pts]
    faces: List[List[int]] = [[base + i for i in range(n)],
                              [base + 2 * n - 1 - i for i in range(n)]]
    for i in range(n):
        j = (i + 1) % n
        faces.append([base + i, base + n + i, base + n + j, base + j])
    return verts, faces


def wall_rect(wall: Dict[str, Any]) -> List[Vec2]:
    """The four corners of ONE wall run, as a rectangle in the XZ plane.

    A recipe wall is a LINE with a thickness (``from``/``to`` on the wall's
    centre line, § B1), so the body is that line offset by half the thickness
    to either side. A degenerate run — the composer emits none, but a fixture
    might — returns no corners rather than a zero-width sliver.
    """
    a = [_num(v) for v in (wall.get("from") or [0.0, 0.0])]
    b = [_num(v) for v in (wall.get("to") or [0.0, 0.0])]
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz)
    if length < 1e-6:
        return []
    ux, uz = dx / length, dz / length
    half = max(_num(wall.get("thickness")), 1e-4) / 2.0
    nx, nz = -uz * half, ux * half
    return [(a[0] + nx, a[1] + nz), (b[0] + nx, b[1] + nz),
            (b[0] - nx, b[1] - nz), (a[0] - nx, a[1] - nz)]


# ── The roof: heuristic, then roof_model's own geometry ─────────────────

def roof_form(length_m: float, depth_m: float) -> str:
    """``"gable"`` or ``"flat"`` for a footprint — the whole heuristic.

    Pure and total: any footprint gets an answer, and the answer depends on
    nothing but the two numbers. See :data:`ROOF_ASPECT_GABLE` and
    :data:`ROOF_FLAT_AREA_M2` for why the thresholds sit where they do.

        area >= 400 m²            -> flat   (a hall, whatever its shape)
        length / depth >= 1.2     -> gable  (a house)
        otherwise                 -> flat   (square-ish: a block)
    """
    length, depth = abs(_num(length_m)), abs(_num(depth_m))
    if depth <= 1e-6 or length <= 1e-6:
        return "flat"
    if length * depth >= ROOF_FLAT_AREA_M2:
        return "flat"
    return "gable" if (length / depth) >= ROOF_ASPECT_GABLE else "flat"


def roof_description(rect: Dict[str, Any]) -> Dict[str, Any]:
    """The build description the heuristic produces, validated like any other.

    It goes through ``roof_model.validate_description`` on purpose: the roof in
    a render and the roof of a BUILT roof model are then provably the same
    object, clamps included.
    """
    from app.core import roof_model as rm
    return rm.validate_description({
        "form": roof_form(_num(rect.get("length")), _num(rect.get("depth"))),
        "pitch_deg": ROOF_PITCH_DEG,
        "overhang_m": ROOF_OVERHANG_M,
        "ridge_axis": ROOF_RIDGE_AXIS,
        "material": {"tone": ROOF_TONE, "kind": "shingle"},
    })


# ── The extractor: a location -> one mesh ───────────────────────────────

def _ground_outline(map3d: Dict[str, Any]) -> List[Vec2]:
    """The polygon the ground plate is laid over — the composer's own choice.

    ``_plates`` shapes a level plate as the drawn BUILDING contour where there
    is one and the drawn boundary otherwise; the ground plate uses exactly that
    fallback, so the foot of the render is the shape the recipe would have
    given storey 0 before E5a moved it into the terrain.
    """
    from app.core.scene_recipe import _drawn_boundary, _outline_world
    pts = _outline_world(map3d) or _drawn_boundary(map3d)
    return [(_num(p[0]), _num(p[1])) for p in pts if len(p) == 2]


def extract_geometry(location: Dict[str, Any], location_id: str = "",
                     ) -> Dict[str, Any]:
    """The location's exterior as ONE mesh in the SCENE frame.

    Pure: same location dict -> the same numbers, to the last decimal. Nothing
    here touches a store, a DB or a config; the smoke drives it with a literal
    dict.

    Returns ``{ok, vertices, faces, face_material, parts, roof, rect,
    bounds}``. ``parts`` counts what went in — walls (``doors`` says how many
    of them are door leaves), plates, whether a ground plate and a roof were
    added — so a caller can say WHY a body looks the way it does without
    re-deriving it. ``ok`` False means the location has no exterior at all
    (no wall, no plate, no footprint).
    """
    from app.core import roof_model as rm
    from app.core.location_model3d import derive_plan_width_m
    from app.core.scene_recipe import (LEVEL_PLATE_THICKNESS, LEVEL_PLATE_TOP,
                                       compose_scene)

    loc_id = location_id or str(location.get("id") or "")
    map3d = location.get("map3d") or {}
    scene = compose_scene(location,
                          plan_width_m=derive_plan_width_m(loc_id, map3d))

    verts: List[List[float]] = []
    faces: List[List[int]] = []
    face_material: List[int] = []

    def add(body_verts: List[List[float]], body_faces: List[List[int]],
            material: int) -> None:
        verts.extend(body_verts)
        faces.extend(body_faces)
        face_material.extend([material] * len(body_faces))

    # WALLS — every one the composer published, contour AND room. Not a
    # choice: where an indoor room hull runs on the building contour the
    # contour piece YIELDS to the room wall (§ B1, "one wall, one owner"), so
    # dropping the room walls would punch holes in the outer shell. The purely
    # interior ones are hidden by the roof from every angle this camera uses.
    #
    # A DOOR LEAF rides in as one of them — it is a `walls` entry like any
    # other, in the composer's own thin body — and only its MATERIAL differs
    # (§ B1 ``leaf``): dark, so the door is a door in the picture the mesher
    # gets. Nothing is filtered here and no leaf is derived here.
    wall_count = 0
    door_count = 0
    for wall in scene.get("walls") or []:
        rect_pts = wall_rect(wall)
        if not rect_pts:
            continue
        base_y = _num(wall.get("base_y"))
        body = prism(rect_pts, base_y, base_y + _num(wall.get("height")),
                     base=len(verts))
        if body[1]:
            leaf = bool(wall.get("leaf"))
            add(body[0], body[1], MATERIAL_DOOR if leaf else MATERIAL_WALL)
            wall_count += 1
            door_count += int(leaf)

    # PLATES — the floors of the DECLARED storeys (upper floors, basements).
    # A zero-thickness plate is a texture surface on the level below (§ B1,
    # outdoor zones), not a body, and is skipped.
    plate_count = 0
    for plate in scene.get("plates") or []:
        thickness = _num(plate.get("thickness"))
        if thickness <= 1e-6:
            continue
        top = _num(plate.get("top_y"))
        body = prism([(_num(p[0]), _num(p[1]))
                      for p in (plate.get("outline") or []) if len(p) == 2],
                     top - thickness, top, base=len(verts))
        if body[1]:
            add(body[0], body[1], MATERIAL_PLATE)
            plate_count += 1

    # THE GROUND PLATE — storey 0's floor, which the payload no longer carries
    # (E5a: the terrain is that floor). See the module header.
    ground = _ground_outline(map3d)
    ground_body = prism(ground, LEVEL_PLATE_TOP - LEVEL_PLATE_THICKNESS,
                        LEVEL_PLATE_TOP, base=len(verts))
    has_ground = bool(ground_body[1])
    if has_ground:
        add(ground_body[0], ground_body[1], MATERIAL_PLATE)

    # THE ROOF — the recipe's shell is open at the top by design.
    facts = rm.build_roof_description(loc_id, location)
    roof: Dict[str, Any] = {}
    if facts.get("ok"):
        desc = roof_description(facts["rect"])
        geo = rm.roof_geometry(desc, facts["rect"])
        base_y = _num(facts["roof_base_y"])
        roof_verts = [[v[0], _r(base_y + v[1]), v[2]] for v in geo["vertices"]]
        offset = len(verts)
        add(roof_verts, [[offset + i for i in f] for f in geo["faces"]],
            MATERIAL_ROOF)
        roof = {"form": desc["form"], "pitch_deg": desc["pitch_deg"],
                "overhang_m": desc["overhang_m"],
                "ridge_axis": desc["ridge_axis"],
                "base_y": _r(base_y),
                "ridge_y_world": _r(base_y + _num(geo["ridge_y"])),
                "vertices": len(roof_verts), "faces": len(geo["faces"])}

    if not faces:
        return {"ok": False, "error": "no_geometry", "location_id": loc_id,
                "vertices": [], "faces": [], "face_material": [],
                "parts": {"walls": 0, "doors": 0, "plates": 0,
                          "ground_plate": False, "roof": False}}

    return {
        "ok": True,
        "location_id": loc_id,
        "vertices": verts,
        "faces": faces,
        "face_material": face_material,
        "parts": {"walls": wall_count, "doors": door_count,
                  "plates": plate_count,
                  "ground_plate": has_ground, "roof": bool(roof)},
        "roof": roof,
        "rect": facts.get("rect") or {},
        "storeys": facts.get("storeys") or 0,
        "eaves_height_m": facts.get("eaves_height_m") or 0.0,
        "bounds": rm.bounds(verts),
    }


# ── The Blender job ─────────────────────────────────────────────────────

def build_job(location_id: str,
              location: Optional[Dict[str, Any]] = None,
              *, size: int = 0, samples: int = 0) -> Dict[str, Any]:
    """The finished job for ``app/blender/scripts/exterior.py``.

    Deterministic by construction — the same location produces a byte-identical
    job, which is what the smoke checks. The vertices leave this function in
    BLENDER's frame ((x, y, z)_scene -> (x, -z, y)); the script does no
    conversion of its own.
    """
    from app.core.roof_model import tone_to_linear
    if location is None:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id) or {}
    geo = extract_geometry(location, location_id)
    if not geo.get("ok"):
        return {"ok": False, "error": str(geo.get("error") or "no_geometry"),
                "location_id": location_id}

    materials = [
        {"name": "wall", "tone": WALL_TONE, "color": tone_to_linear(WALL_TONE),
         "roughness": SURFACE_ROUGHNESS},
        {"name": "roof", "tone": ROOF_TONE, "color": tone_to_linear(ROOF_TONE),
         "roughness": SURFACE_ROUGHNESS},
        {"name": "plate", "tone": PLATE_TONE,
         "color": tone_to_linear(PLATE_TONE), "roughness": SURFACE_ROUGHNESS},
        {"name": "door", "tone": DOOR_TONE, "color": tone_to_linear(DOOR_TONE),
         "roughness": SURFACE_ROUGHNESS},
    ]
    return {
        "ok": True,
        "kind": "exterior",
        "location_id": location_id,
        "name": str(location.get("name") or location_id),
        "mesh": {
            "name": "exterior",
            # Scene -> Blender, ONCE (the module header's conversion).
            "vertices": [[v[0], _r(-v[2]), v[1]] for v in geo["vertices"]],
            "faces": geo["faces"],
            "face_material": geo["face_material"],
        },
        "materials": materials,
        "camera": {
            "elevation_deg": CAM_ELEVATION_DEG, "yaw_deg": CAM_YAW_DEG,
            "lens_mm": CAM_LENS_MM, "sensor_mm": CAM_SENSOR_MM,
            "margin": CAM_FRAME_MARGIN,
        },
        "render": {
            "size": int(size or RENDER_SIZE_PX),
            "samples": int(samples or RENDER_SAMPLES),
            # The plain neutral ground the ``building`` use case asks for; it
            # is also the ambient fill, so the body is lit from every side and
            # nothing anywhere casts a shadow.
            "background": [0.55, 0.55, 0.55],
            "png": "exterior.png",
        },
        # What was asked for — the script reports what it built, and the two
        # are compared (§ B5a: numbers, not screenshots).
        "expect": {
            "vertices": len(geo["vertices"]),
            "faces": len(geo["faces"]),
            "parts": geo["parts"],
            "roof": geo["roof"],
            "bounds_scene": geo["bounds"],
            "storeys": geo["storeys"],
            "eaves_height_m": geo["eaves_height_m"],
        },
    }


# ── Running it ──────────────────────────────────────────────────────────

def _timeout_s() -> int:
    """A Cycles render is minutes, not seconds — the mesh-refinement timeout is
    the wrong order of magnitude here, so this one is its own number."""
    try:
        from app.core import config
        return int(config.get("image_generation.blender_render_timeout_s", 600)
                   or 600)
    except Exception:
        return 600


def generate_exterior(location_id: str,
                      location: Optional[Dict[str, Any]] = None,
                      ) -> Dict[str, Any]:
    """Render the exterior and file it as a ``building-front`` gallery image.

    Blocking (see :func:`trigger_exterior_render` for the background call).
    The image is stored on the ORDINARY gallery path — the same three calls
    ``world_ops`` makes after a generated render — so it appears in the gallery
    UI, carries the ``building`` type and can be meshed by the existing
    pipeline without anything downstream knowing where it came from. It is
    deliberately NOT flagged as a background image: building renders are mesh
    input, never room art (the same exclusion ``world_ops`` makes).

    Returns ``{ok, error, image, job, data}``.
    """
    from app.blender import runner
    from app.models.world import (get_gallery_dir, set_gallery_image_meta,
                                  set_gallery_image_type)

    if location is None:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id) or {}
    if not location:
        return {"ok": False, "error": "location_not_found"}
    job = build_job(location_id, location)
    if not job.get("ok"):
        return {"ok": False, "error": str(job.get("error") or "no_geometry")}
    if not runner.is_available():
        return {"ok": False, "error": "blender_unavailable"}

    loc_id = str(location.get("id") or location_id)
    with tempfile.TemporaryDirectory(prefix="av-exterior-") as tmp:
        tmp_dir = Path(tmp)
        job_file = tmp_dir / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False, sort_keys=True),
                            encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        result = runner.run("exterior", inputs={"job": job_file},
                            out_dir=out_dir, timeout_s=_timeout_s())
        if not result.get("ok"):
            logger.error("Exterior render for %s failed: %s", location_id,
                         result.get("error"))
            return {"ok": False,
                    "error": str(result.get("error") or "render failed")}
        png = Path((result.get("outputs") or {}).get("png") or "")
        if not png.is_file():
            return {"ok": False, "error": "no image produced"}
        data = result.get("data") or {}

        gallery_dir = get_gallery_dir(loc_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"{int(time.time())}.png"
        (gallery_dir / image_name).write_bytes(png.read_bytes())

    set_gallery_image_type(loc_id, image_name, "building-front")
    set_gallery_image_meta(loc_id, image_name, {
        "backend": "blender",
        "backend_type": "blender",
        "model": f"exterior {runner.version()}".strip(),
        "loras": [],
    })
    expect = job["expect"]
    logger.info("Exterior render for %s: %s (%d faces, roof %s, %.1fs)",
                location_id, image_name, int(expect["faces"]),
                (expect.get("roof") or {}).get("form") or "none",
                float(result.get("seconds") or 0.0))
    return {"ok": True, "error": "", "image": image_name, "job": job,
            "data": data}


def trigger_exterior_render(location_id: str) -> bool:
    """Start the render in the background; False = one is already running.

    Same shape as every other model job here (``roof_model``,
    ``location_model3d``): a daemon thread, a header task for visibility, and
    the pending flag the panel already polls (``location_model3d.is_pending``),
    so the button disables itself without anything new being invented.
    """
    import threading
    from app.core.location_model3d import claim_job, release_job
    if not claim_job(location_id, kind="exterior"):
        return False

    def _run() -> None:
        task_id = ""
        error = ""
        try:
            from app.core.task_queue import get_task_queue
            from app.models.world import get_location_by_id
            label = str((get_location_by_id(location_id) or {}).get("name")
                        or location_id)
            try:
                task_id = get_task_queue().track_start(
                    "model3d_generation", f"Exterior render: {label}",
                    start_running=True)
            except Exception:
                task_id = ""
            res = generate_exterior(location_id)
            error = "" if res.get("ok") else str(res.get("error") or "failed")
        except Exception as e:               # last resort — a thread dies silently
            error = str(e)
            logger.error("Exterior render for %s failed: %s", location_id, e)
        finally:
            if task_id:
                try:
                    from app.core.task_queue import get_task_queue
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    pass
            release_job(location_id, kind="exterior")

    threading.Thread(target=_run, daemon=True).start()
    return True
