#!/usr/bin/env python3
"""Numeric check of the LLM-BLENDER ROOF — schema, footprint, geometry, placement.

Usage:
    ./.venv/bin/python scripts/smoke_roof_model.py

No server, no world DB. The Blender section at the end runs only when a
Blender binary is available and says so loudly when it is not.

Design: `docs/llm-blender-models.md`. Every number below is derived BY HAND
from that document, never recorded from a run.

──────────────────────────────────────────────────────────────────────────
FIXTURE — a rectangular building contour with corners (0,0), (10,0), (10,8),
(0,8) in local metres, deliberately NOT centred on the anchor pin so a wrong
anchor shows up as an offset. Two storeys of 3 m. Roof: gable, pitch 30°,
overhang 0.40 m, ridge axis auto.

1. EAVES. Storeys are counted from the room levels ABOVE ground, so two rooms
   on levels 0 and 1 are 2 storeys:
       eaves (nominal) = 2 × 3.00 = 6.00 m
   The contour walls of the top storey really end at
       (S−1)·storey + plate top + wall height
     = 1·3.00 + 0.08 + max(0.6, 3.00 − 0.15) = 3.08 + 2.85 = 5.93 m,
   i.e. 0.07 m below the nominal eaves. The roof body is therefore dropped by
   EAVES_SINK 0.10:
       roof base plane = 6.00 − 0.10 = 5.90 m   (0.03 m INTO the wall head)

2. ORIENTED BOX. The contour is axis-aligned, so the minimum-area rectangle is
   the contour itself: centre (5, 4), length 10 (the long side), depth 8,
   angle 0°. `auto` runs the ridge along the LONG side → ridge ∥ x, span
   across z.

3. GABLE GEOMETRY, measured from the base plane (y = 0 at the wall line):
       slope   = tan 30° = 0.57735027
       ridge   = (8/2) · tan 30° = 4 · 0.57735027 = +2.309401 m
       eaves   = −0.40 · tan 30°                  = −0.230940 m
   (the pitch is the slope of the SURFACE; the surface passes through the wall
   line, so the overhang does not raise the ridge — it hangs the outer edge
   below the wall head.)
   Outset rectangle: (10 + 0.8) × (8 + 0.8) = 10.8 × 8.8, still centred (5, 4).
       vertices = 4 eaves corners + 2 ridge points          = 6
       faces    = 2 slopes + 2 gable ends + 1 underside     = 5
       AABB     x [−0.4, 10.4], z [−0.4, 8.4], y [−0.2309, 2.3094]
       body height = 2.309401 + 0.230940 = 2.540341 m

4. PLACEMENT (the metric law, § B2). The mesh is measured by its widest XZ
   side and centred on its own AABB centre, so the sidecar reads
       width_m  = max(10.8, 8.8) = 10.80   → scale = 10.80 / 10.80 = 1.000
       offset_x = 5.00, offset_z = 4.00    (the AABB centre)
       offset_y = base + AABB min y − LEVEL_PLATE_TOP
                = 5.90 + (−0.230940) − 0.08 = 5.589060
   (the anchor is the storey-0 floor plate since the § B2 addendum of
   2026-08-20 — a roof declares no walk_y, so its lower edge lands on
   ``bottom_y = LEVEL_PLATE_TOP + offset_y``)
   and the ridge lands at 5.90 + 2.309401 = 8.209401 m in the scene frame.

5. HIP over the same box: all four planes carry the same pitch, so the ridge
   is shortened by the hip run at both ends —
       ridge half-length = (10 − 8)/2 = 1.0  (the overhang outsets BOTH
       extents by 0.4 and cancels out of the difference)
   → 6 vertices, 5 faces, ridge height unchanged at +2.309401.
   Over an 8 × 8 box the ridge collapses to a point: a pyramid, 5 vertices.

6. SHED over the same box, pitch 30°: one plane rising across the 8 m span,
       high edge = (8 + 0.4) · tan 30° = 8.4 · 0.57735027 = +4.849742
       low edge  = −0.40 · tan 30°                        = −0.230940
   → 6 vertices, 5 faces, body height 5.080682 m.

7. FLAT: a slab of 0.12 m on the wall head — 8 vertices, 6 faces, height 0.12.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import roof_model as rm                              # noqa: E402
from app.core.scene_recipe import LEVEL_PLATE_TOP                  # noqa: E402

failures = []

TAN30 = 0.5773502691896257


def check(label, got, want, tol=0.0):
    ok = abs(float(got) - float(want)) <= tol if tol else got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def check_vec(label, got, want, tol):
    ok = len(got) == len(want) and all(abs(float(g) - float(w)) <= tol
                                       for g, w in zip(got, want))
    shown = [round(float(g), 4) for g in got]
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {shown}, want {want}")
    if not ok:
        failures.append(label)


def check_true(label, ok, note=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {note}' if note else ''}")
    if not ok:
        failures.append(label)


def outward_normals(geo):
    """Does every face point AWAY from the body? (worst dot, and its face)

    The renderers cull back faces, so a face wound the wrong way is simply
    invisible — a hole in the roof that no bounding box and no vertex count
    shows. The body is convex in all four forms, so "outward" has an exact
    test: the Newell normal of a face, dotted with the vector from the body's
    centroid to the face's centre, must be positive.
    """
    verts = geo["vertices"]
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    cz = sum(v[2] for v in verts) / len(verts)
    worst = (1e9, -1)
    for fi, face in enumerate(geo["faces"]):
        nx = ny = nz = 0.0
        for i in range(len(face)):
            a, b = verts[face[i]], verts[face[(i + 1) % len(face)]]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        fx = sum(verts[i][0] for i in face) / len(face) - cx
        fy = sum(verts[i][1] for i in face) / len(face) - cy
        fz = sum(verts[i][2] for i in face) / len(face) - cz
        dot = nx * fx + ny * fy + nz * fz
        if dot < worst[0]:
            worst = (dot, fi)
    return worst


OUTLINE = [[0, 0], [10, 0], [10, 8], [0, 8]]


def fixture_location(**over):
    """The 10 × 8 m, two-storey building of the docstring."""
    loc = {
        "id": "roof-demo",
        "name": "Demo House",
        "description": "A plain two-storey house.",
        "map3d": {"outline": list(OUTLINE), "storey_height_m": 3.0},
        "rooms": [
            {"id": "r0", "name": "Ground", "layout": {"x": 0, "y": 0, "w": 10,
                                                      "d": 8, "level": 0}},
            {"id": "r1", "name": "Upper", "layout": {"x": 0, "y": 0, "w": 10,
                                                     "d": 8, "level": 1}},
        ],
    }
    loc.update(over)
    return loc


def gable_desc(**over):
    d = {"form": "gable", "pitch_deg": 30, "overhang_m": 0.4,
         "ridge_axis": "auto", "material": {"tone": "#6b5f57",
                                            "kind": "shingle"}}
    d.update(over)
    return d


# ── [1] Schema: clamps and junk ─────────────────────────────────────────

def part_schema():
    print("\n[1] Build description — clamps, junk, defaults")
    empty = rm.validate_description(None)
    check("empty -> form", empty["form"], "gable")
    check("empty -> pitch", empty["pitch_deg"], 35.0)
    check("empty -> overhang", empty["overhang_m"], 0.4)
    check("empty -> ridge axis", empty["ridge_axis"], "auto")
    check("empty -> kind", empty["material"]["kind"], "shingle")
    check("empty -> tone", empty["material"]["tone"], "#6b5f57")

    high = rm.validate_description({"form": "hip", "pitch_deg": 80,
                                    "overhang_m": 5})
    check("pitch 80 clamped to max", high["pitch_deg"], 60.0)
    check("overhang 5 m clamped to max", high["overhang_m"], 1.0)
    low = rm.validate_description({"pitch_deg": 1, "overhang_m": -2})
    check("pitch 1 clamped to min", low["pitch_deg"], 5.0)
    check("overhang -2 clamped to min", low["overhang_m"], 0.0)

    junk = rm.validate_description({"form": "pagoda", "ridge_axis": "diagonal",
                                    "pitch_deg": "steep",
                                    "material": {"kind": "gold",
                                                 "tone": "reddish"}})
    check("unknown form -> default", junk["form"], "gable")
    check("unknown ridge axis -> auto", junk["ridge_axis"], "auto")
    check("unreadable pitch -> default", junk["pitch_deg"], 35.0)
    check("unknown kind -> default", junk["material"]["kind"], "shingle")
    check("unreadable tone -> kind default", junk["material"]["tone"], "#6b5f57")

    check("#rgb expanded",
          rm.validate_description({"material": {"tone": "#abc",
                                                "kind": "tile"}})["material"]["tone"],
          "#aabbcc")
    check("kind default tone (thatch)",
          rm.validate_description({"material": {"kind": "thatch"}})["material"]["tone"],
          "#b79a63")
    flat = rm.validate_description({"form": "flat", "pitch_deg": 40})
    check("flat has no pitch", flat["pitch_deg"], 0.0)
    check("gable_tone only where it means something",
          "gable_tone" in rm.validate_description(
              {"form": "hip", "gable_tone": "#123456"}), False)
    check("gable_tone kept on a gable",
          rm.validate_description({"form": "gable",
                                   "gable_tone": "#123456"})["gable_tone"],
          "#123456")
    # A tone is named in sRGB and fed to Blender in linear light.
    check_vec("tone #808080 -> linear", rm.tone_to_linear("#808080"),
              [0.215861, 0.215861, 0.215861], 1e-5)
    check_vec("tone #ffffff -> linear", rm.tone_to_linear("#ffffff"),
              [1.0, 1.0, 1.0], 1e-6)


# ── [2] Footprint precedence ────────────────────────────────────────────

def part_footprint():
    print("\n[2] Footprint — outline > boundary > room union")
    loc = fixture_location()
    loc["map3d"]["boundary"] = [[-20, -20], [20, -20], [20, 20], [-20, 20]]
    fp = rm.footprint(loc)
    check("drawn outline wins", fp["source"], "outline")
    check("outline points", len(fp["points"]), 4)

    no_outline = fixture_location()
    no_outline["map3d"] = {"boundary": [[-6, -6], [6, -6], [6, 6], [-6, 6]],
                           "storey_height_m": 3.0}
    check("boundary is the second source",
          rm.footprint(no_outline)["source"], "boundary")

    rooms_only = fixture_location()
    rooms_only["map3d"] = {"storey_height_m": 3.0}
    fp3 = rm.footprint(rooms_only)
    check("room union is the last source", fp3["source"], "rooms")
    check("room union covers both rooms (4 corners each)", len(fp3["points"]), 8)

    bare = {"id": "x", "name": "Nothing", "map3d": {}, "rooms": []}
    check("nothing to roof", rm.footprint(bare)["ok"], False)
    facts = rm.build_roof_description("x", bare)
    check("gathering says why", facts.get("error"), "no_footprint")

    # The rectangle: hand-read off the fixture.
    rect = rm.oriented_bbox([tuple(p) for p in OUTLINE])
    check_vec("oriented centre", rect["center"], [5.0, 4.0], 1e-6)
    check("oriented length (long side)", rect["length"], 10.0, 1e-6)
    check("oriented depth (short side)", rect["depth"], 8.0, 1e-6)
    # A 45°-turned square: side √2·… — the box must FOLLOW the turn, not grow.
    turned = rm.oriented_bbox([(0, -5), (5, 0), (0, 5), (-5, 0)])
    check("turned square: side", turned["length"], 7.071068, 1e-4)
    check("turned square: no growth", turned["depth"], 7.071068, 1e-4)


# ── [3] Storeys and the eaves plane ─────────────────────────────────────

def part_eaves():
    print("\n[3] Eaves — 2 storeys × 3 m")
    loc = fixture_location()
    check("storeys above ground", rm.storeys(loc), 2)
    check("storey height", rm.storey_height_m(loc), 3.0)
    check("nominal eaves height", rm.eaves_height_m(loc), 6.0, 1e-9)
    check("roof base plane (eaves − sink)", rm.roof_base_y(loc), 5.90, 1e-9)
    # The wall head the roof has to meet: plate top + wall height, top storey.
    wall_top = 1 * 3.0 + 0.08 + max(0.6, 3.0 - 0.15)
    check("top-storey wall head", wall_top, 5.93, 1e-9)
    check_true("roof base is INSIDE the wall head (overlap 0.03 m)",
               rm.roof_base_y(loc) < wall_top,
               f"{wall_top - rm.roof_base_y(loc):.2f} m overlap")

    cellar = fixture_location()
    cellar["rooms"] = [{"id": "c", "layout": {"x": 0, "y": 0, "w": 4, "d": 4,
                                              "level": -1}}]
    check("a basement does not raise the roof", rm.storeys(cellar), 1)
    none = fixture_location()
    none["rooms"] = []
    check("no room at all = one storey", rm.storeys(none), 1)


# ── [4] The gable body ──────────────────────────────────────────────────

def part_gable():
    print("\n[4] Gable — 10 × 8 m box, pitch 30°, overhang 0.40 m")
    rect = rm.oriented_bbox([tuple(p) for p in OUTLINE])
    geo = rm.roof_geometry(gable_desc(), rect)
    check("vertices", len(geo["vertices"]), 6)
    check("faces", len(geo["faces"]), 5)
    check("gable-end faces", len(geo["groups"]["gable"]), 2)
    check("ridge above the wall line", geo["ridge_y"], round(4 * TAN30, 4), 1e-4)
    check("eaves edge below the wall line", geo["eaves_y"],
          round(-0.4 * TAN30, 4), 1e-4)

    box = rm.bounds(geo["vertices"])
    check_vec("AABB min", box["min"], [-0.4, -0.2309, -0.4], 1e-4)
    check_vec("AABB max", box["max"], [10.4, 2.3094, 8.4], 1e-4)
    check_vec("AABB size", box["size"], [10.8, 2.5403, 8.8], 1e-4)
    check_vec("AABB centre", box["center"], [5.0, 1.0392, 4.0], 1e-4)

    # Every face must reference real vertices, and every vertex must be used —
    # a stray index is a broken GLB and a stray vertex is a silent AABB error.
    n = len(geo["vertices"])
    used = {i for f in geo["faces"] for i in f}
    check_true("face indices in range",
               all(0 <= i < n for f in geo["faces"] for i in f))
    check("every vertex used", len(used), n)
    worst, fi = outward_normals(geo)
    check_true("every face wound outward (back-face culling)", worst > 0,
               f"worst face {fi}, dot {worst:.3f}")

    # Pitch 0 is not reachable through the schema (min 5°), but the geometry
    # must stay sane at the ends of the range.
    steep = rm.roof_geometry(gable_desc(pitch_deg=60), rect)
    check("60° ridge", steep["ridge_y"], round(4 * 1.7320508, 4), 1e-4)
    shallow = rm.roof_geometry(gable_desc(pitch_deg=5), rect)
    check("5° ridge", shallow["ridge_y"], round(4 * 0.0874886, 4), 1e-4)
    # No overhang: the eaves edge sits exactly on the wall line.
    flush = rm.roof_geometry(gable_desc(overhang_m=0), rect)
    check("overhang 0 -> eaves on the wall line", flush["eaves_y"], 0.0, 1e-9)
    check_vec("overhang 0 -> AABB size", rm.bounds(flush["vertices"])["size"],
              [10.0, 2.3094, 8.0], 1e-4)
    # Forcing the ridge across turns the body by 90°: the span is now the LONG
    # side, so the ridge rises 5 · tan30 instead of 4 · tan30.
    across = rm.roof_geometry(gable_desc(ridge_axis="z"), rect)
    check("ridge forced along z -> ridge over the long span",
          across["ridge_y"], round(5 * TAN30, 4), 1e-4)


# ── [5] The other three forms ───────────────────────────────────────────

def part_forms():
    print("\n[5] Hip, shed, flat")
    rect = rm.oriented_bbox([tuple(p) for p in OUTLINE])
    hip = rm.roof_geometry(gable_desc(form="hip"), rect)
    check("hip vertices", len(hip["vertices"]), 6)
    check("hip faces", len(hip["faces"]), 5)
    check("hip ridge = gable ridge", hip["ridge_y"], round(4 * TAN30, 4), 1e-4)
    # The ridge run: (10 − 8)/2 = 1.0 either side of the centre, along x.
    ridge_pts = sorted(v[0] for v in hip["vertices"]
                       if abs(v[1] - hip["ridge_y"]) < 1e-6)
    check_vec("hip ridge ends (x)", ridge_pts, [4.0, 6.0], 1e-4)
    check_vec("hip AABB size", rm.bounds(hip["vertices"])["size"],
              [10.8, 2.3094 + 0.2309, 8.8], 1e-3)

    square = rm.oriented_bbox([(0, 0), (8, 0), (8, 8), (0, 8)])
    pyramid = rm.roof_geometry(gable_desc(form="hip"), square)
    check("hip over a square = pyramid (vertices)",
          len(pyramid["vertices"]), 5)
    check("pyramid faces", len(pyramid["faces"]), 5)

    shed = rm.roof_geometry(gable_desc(form="shed"), rect)
    check("shed vertices", len(shed["vertices"]), 6)
    check("shed faces", len(shed["faces"]), 5)
    check("shed high edge", shed["ridge_y"], round(8.4 * TAN30, 4), 1e-4)
    check("shed low edge", shed["eaves_y"], round(-0.4 * TAN30, 4), 1e-4)
    check("shed body height",
          rm.bounds(shed["vertices"])["size"][1], 5.080682, 1e-3)

    flat = rm.roof_geometry(rm.validate_description({"form": "flat"}), rect)
    check("flat vertices", len(flat["vertices"]), 8)
    check("flat faces", len(flat["faces"]), 6)
    check_vec("flat AABB size", rm.bounds(flat["vertices"])["size"],
              [10.8, 0.12, 8.8], 1e-4)

    # Every body, every form, every ridge choice: no face may face inward.
    for name, g in (("hip", hip), ("pyramid", pyramid), ("shed", shed),
                    ("flat", flat)):
        worst, fi = outward_normals(g)
        check_true(f"{name}: every face wound outward", worst > 0,
                   f"worst face {fi}, dot {worst:.3f}")
    turned = rm.oriented_bbox([(0, -5), (5, 0), (0, 5), (-5, 0)])
    for form in ("gable", "hip", "shed", "flat"):
        g = rm.roof_geometry(gable_desc(form=form), turned)
        worst, fi = outward_normals(g)
        check_true(f"{form} on a 45°-turned footprint: still outward",
                   worst > 0, f"worst face {fi}, dot {worst:.3f}")


# ── [6] Placement: the metric law ───────────────────────────────────────

def part_placement():
    print("\n[6] Placement — width_m, offsets, ridge in the scene frame")
    job = rm.build_job("roof-demo", gable_desc(), fixture_location())
    p = job["placement"]
    check("width_m = widest XZ side", p["width_m"], 10.8, 1e-4)
    check("scale factor", p["width_m"] / max(p["bbox_local"]["size"][0],
                                             p["bbox_local"]["size"][2]),
          1.0, 1e-9)
    check("offset_x = AABB centre x", p["offset_x"], 5.0, 1e-4)
    check("offset_z = AABB centre z", p["offset_z"], 4.0, 1e-4)
    check("offset_y = base + min y − storey-0 floor plate", p["offset_y"],
          round(5.90 - 0.4 * TAN30 - LEVEL_PLATE_TOP, 4), 1e-3)
    check("ridge in the scene frame", p["ridge_y_world"],
          round(5.90 + 4 * TAN30, 4), 1e-3)
    check("eaves height quoted", p["eaves_height_m"], 6.0, 1e-9)
    check("footprint source recorded", p["footprint_source"], "outline")
    check("vertex count recorded", p["vertex_count"], 6)
    check("face count recorded", p["face_count"], 5)

    # The Blender frame conversion, once: (x, y, z)_scene -> (x, −z, y).
    scene_ridge_v = max(rm.roof_geometry(gable_desc(),
                                         rm.oriented_bbox([tuple(q)
                                                           for q in OUTLINE])
                                         )["vertices"], key=lambda v: v[1])
    blender_v = max(job["mesh"]["vertices"], key=lambda v: v[2])
    check_vec("scene -> blender frame",
              blender_v,
              [scene_ridge_v[0], -scene_ridge_v[2], scene_ridge_v[1]], 1e-6)

    mats = job["materials"]
    check("one material by default", len(mats), 1)
    check("roughness follows the kind", mats[0]["roughness"], 0.80, 1e-9)
    two = rm.build_job("roof-demo", gable_desc(gable_tone="#334455"),
                       fixture_location())
    check("gable tone adds a second material", len(two["materials"]), 2)
    check("only the gable ends take it",
          sum(1 for m in two["mesh"]["face_material"] if m == 1), 2)
    metal = rm.build_job("roof-demo",
                         gable_desc(material={"tone": "#8f959b",
                                              "kind": "metal"}),
                         fixture_location())
    check("metal is the only smooth kind",
          metal["materials"][0]["roughness"], 0.35, 1e-9)


# ── [7] Determinism ─────────────────────────────────────────────────────

def part_determinism():
    print("\n[7] Determinism — same description, same job")
    import json
    a = json.dumps(rm.build_job("roof-demo", gable_desc(), fixture_location()),
                   sort_keys=True)
    b = json.dumps(rm.build_job("roof-demo", gable_desc(), fixture_location()),
                   sort_keys=True)
    check_true("two builds produce the identical job JSON", a == b)
    # …and a different pitch produces a different one (the check above must not
    # pass because both were empty).
    c = json.dumps(rm.build_job("roof-demo", gable_desc(pitch_deg=31),
                                fixture_location()), sort_keys=True)
    check_true("a changed pitch changes the job", a != c)
    check_true("the job carries the validated description, not the raw input",
               rm.build_job("roof-demo", {"form": "pagoda"},
                            fixture_location())["description"]["form"] == "gable")


# ── [8] Blender end to end ──────────────────────────────────────────────

def part_blender():
    print("\n[8] Blender end to end")
    from app.blender import runner
    st = runner.status()
    if not st["executable"] or not st["version"]:
        print("  SKIP ─────────────────────────────────────────────────────")
        print("  SKIP  no Blender binary found — the GLB is NOT built.")
        print("  SKIP  set image_generation.blender_executable or put one on")
        print("  SKIP  PATH to run this section.")
        print("  SKIP ─────────────────────────────────────────────────────")
        return
    print(f"  Blender: {st['executable']} {st['version']}")
    import json
    import tempfile

    job = rm.build_job("roof-demo", gable_desc(), fixture_location())
    with tempfile.TemporaryDirectory(prefix="av-roof-smoke-") as tmp:
        tmp_dir = Path(tmp)
        job_file = tmp_dir / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False),
                            encoding="utf-8")
        out_dir = tmp_dir / "out"
        out_dir.mkdir()
        res = runner.run("roof_build", inputs={"job": job_file},
                         out_dir=out_dir, timeout_s=180)
        check_true("build ok", bool(res.get("ok")), res.get("error", ""))
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        check("built vertices", data.get("vertices"), 6)
        check("built faces", data.get("faces"), 5)
        check("built materials", data.get("materials"), 1)
        # The bbox comes back in the BLENDER frame: (x, −z, y) of the scene.
        check_vec("built bbox (blender frame)", data.get("bbox") or [],
                  [-0.4, -8.4, -0.230940, 10.4, 0.4, 2.309401], 1e-3)
        glb = Path((res.get("outputs") or {}).get("glb") or "")
        check_true("GLB written", glb.is_file())
        if not glb.is_file():
            return
        from app.core.model_validate import parse_glb
        info = parse_glb(glb.read_bytes())
        check("GLB carries one mesh", len(info["gltf"].get("meshes") or []), 1)
        check("GLB carries no rig", info["joint_count"], 0)
        # …and the exporter's own axis conversion brings the scene frame back:
        # Blender (x, y, z) -> glTF (x, z, −y), so the glTF max y is the
        # scene's ridge height above the base plane.
        gltf = info["gltf"]
        mesh = gltf["meshes"][0]
        acc = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
        check_vec("glTF POSITION max = scene ridge",
                  acc.get("max") or [], [10.4, 2.309401, 8.4], 1e-3)
        check_vec("glTF POSITION min",
                  acc.get("min") or [], [-0.4, -0.230940, -0.4], 1e-3)


def main():
    part_schema()
    part_footprint()
    part_eaves()
    part_gable()
    part_forms()
    part_placement()
    part_determinism()
    part_blender()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
