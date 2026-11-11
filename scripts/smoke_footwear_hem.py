#!/usr/bin/env python3
"""Boots plan Task 10: the hem mode — trousers tucked into a boot or layered over its shaft, per outfit
(app/core/outfit_options.py, app/core/garment_layers.py, app/core/footwear_cut.py ``plane_cut``,
app/core/garment_assembly.py, app/routes/characters.py ``/outfit-options``, app/models/character.py saved outfits;
spec docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md § 8, § 20).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_hem.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no Blender, no server. Stubs as in smoke_footwear_assembly.py (image service, LOD, the
permissive validator for the seven-joint fixture rig, ``decimate_to`` copies, ``schedule`` records); the boot fit,
the cut, the layering, the plane cut, the assembly, the routes and the outfit store are REAL.

Fixture (metres, the rigged bind space). Body = ``foot_body_glb(leg_cell=0.01)``: the box feet (Foot joint at
y 0.08, the sole on y = 0) and a leg column x in [-0.03, 0.03], z in zc +- 0.03 (zc = -0.10 left), y in [0.10,
0.45], Leg 1.0, in 1-cm cells. Boot item ``boots`` = ``flat_boot(shaft=0.16, shaft_to=0.12)``: the clog whose
walls over raw x in [0, 0.12] rise to 0.16, fitted on the CPU (smoke_footwear_split.py [B1]: k 1.023599, lift
0.010236, y_split 0.090236, width factor 1.0380, split, no push — the shin stands 12.5 mm inside). In BODY space
the shaft's walls stand at |z - zc| = 0.04 k x 1.0380 = 0.0425 exactly (k cancels: the factor is 0.085 / (0.08 k)),
its back wall at x = -0.071136 (raw 0 -> frame 0 -> body x = frame - 0.071136) and its front wall at x = 0.12 k
- 0.071136 = 0.051696; the shaft's top row (raw 0.16) at body y = 0.16 k - lift = 0.153540 = ``top_m``.
Trousers item ``trousers`` (slot bottom, own mesh): a synthetic fit = the rigged body + a WELDED tube around the
left leg column's axis (x = 0, z = zc), radius r, rings every 1 cm from y 0.02 to 0.60 (59 rings x 64 segments =
3776 vertices, 58 x 128 = 7424 triangles; quad (a, b on ring i; c, d above) -> (a, c, b), (a, d, c), the diagonal
a-c), skinned by ``garment_fit.clothing_weights``, record ``report.skirt`` False. The bare outfit model OSIG =
the base bytes with pieces {feet: boots, bottom: trousers}, mesh_items [boots, trousers].

Expected, by hand:
[H1] ``boot_hem(profile)`` -> "over" for a missing / null / unknown key; ``set_boot_hem("tucked")`` stores
     equipped_options.boot_hem; POST /characters/Demo/outfit-options {boot_hem: "tucked"} -> 200 {boot_hem
     "tucked", applicable {...}}, "sideways" -> 400, null -> 200 boot_hem None; GET -> the stored value.
     ``hem_applicable``: False before the boot is fitted ("no boot"), False with the trousers' fit record saying
     skirt, False for a painted (not own-mesh) bottom piece, True with the own-mesh tube fit (boot_item boots,
     trousers_item trousers). TOO_WIDE_WARNING = the spec's "{trousers}: too wide to tuck into {boot} — worn over it".
[H2] tucked, r 0.035 (inside the shaft everywhere: 0.035 < 0.0425 at the sides, < 0.051696 at the front, < 0.071136
     at the back): assemble -> the trousers' layered file (layers/trousers_<F>_<lsig>.glb) with record hem {mode
     tucked, built tucked, plane_m 0.153540 - 0.03 = 0.123540 (+- 1e-6: the shaft top is read from the fit GLB's
     float32 positions), tucked_poke 0, fallback None}. The cut: rings 0.02 .. 0.12 (11) go — 10 bands removed
     whole (1280 faces), the band 0.12 -> 0.13 bisected (128 faces, 3 triangles per quad = 192, 128 new vertices:
     64 verticals + 64 diagonals), the 47 bands 0.13 .. 0.60 stay whole (6016) -> 6016 + 192 = 6208 faces, 3776 -
     704 + 128 = 3200 vertices; every new vertex at y = plane_m (within float32 of the layered GLB, 1e-7; the
     secant root of a linear g is exact), the lowest vertex of the node = the plane, nothing below; the 64 vertical
     cut points keep r 0.035, the 64 diagonal ones lie on the chord at the fraction t = (plane - 0.12) / 0.01 =
     0.354: r 0.035 sqrt((1 - t)^2 + t^2 + 2 t (1 - t) cos 5.625 deg) = 0.034961 (+- 1e-6); every other vertex at
     r 0.035 (tucked over nothing else: no layering before the cut). tucked_poke: the vertices between the plane
     and the top — rings 0.13 / 0.14 / 0.15 (192) + the cut ring (128) = 320, all inside the shaft's rectangle -> 0.
     lsig = layer_sig({boots: shaft_sha}, mode "tucked", plane_m 0.12354) != the over lsig; a plain
     ``layer_sig(inner)`` is byte-identical to the Task-2 payload (smoke_garment_layering [3] pins it).
[H3] tucked, r 0.05: the tube crosses the shaft's +-z walls (0.05 > 0.0425) but not its ends (0.05 < 0.051696,
     0.05 < 0.071136). Outside = |0.05 sin theta| > 0.0425, |sin theta| > 0.85, theta in (58.21, 121.79) deg and
     the mirror: the ring columns at 5.625 j deg -> j 11 .. 21 = 11 per side, 22 per ring; the cut ring's 64
     verticals are the same columns (22) and its 64 diagonal points lie at the fraction t = (0.12354 - 0.12) /
     0.01 = 0.354 along the chord j -> j + 1: radius 0.05 sqrt(0.646^2 + 0.354^2 + 2 x 0.646 x 0.354 cos 5.625) =
     0.049940, angle 5.625 j + atan2(0.354 sin 5.625, 0.646 + 0.354 cos 5.625) = 5.625 j + 1.99 deg -> outside
     iff |sin| > 0.0425 / 0.049940 = 0.85103, theta in (58.32, 121.68): j 11 (63.86) .. 21 (120.11) = 11 per
     side (j 10 at 58.24 deg stands 0.04 mm INSIDE) -> 22. tucked_poke = (3 x 22 + 22 + 22) / 320 = 110 / 320 =
     0.34375 > TUCKED_POKE_MAX 0.01 -> the record says fallback "too_wide", built "over", and the geometry under
     the tucked lsig is the OVER one (no vertex removed: 3776 vertices / 7424 faces); ``_state`` carries hem
     {mode tucked, lsig, fallback too_wide}.
[H4] over, r 0.035: ``layer_over`` with the two shaft nodes as inners. Beside the column's +-z faces the shaft
     stands h = 0.0425 - 0.03 = 0.0125 above the body, so a trouser vertex there must stand 0.0125 + LAYER_CLEAR_M
     0.0119 = 0.0244 above it: |z - zc| >= 0.0544 (the voxel EDT beyond the exact band reads up to 0.6 voxel
     short, so up to ~2 mm further, never more than 0.5 mm less) for the vertices with |x| <= 0.015 (their feet
     lie on the z faces) and y in [0.11, 0.15]; behind the column the back wall stands 0.071136 - 0.03 = 0.0411
     above the back face -> x <= -(0.03 + 0.0411 + 0.0119) = -0.083 for |z - zc| <= 0.015, y in [0.11, 0.15];
     in front x >= 0.03 + 0.0217 + 0.0119 = 0.0636 (measured 0.05498 / -0.08304 / 0.06345). Above the shaft top
     the push's six smoothing passes carry a displacement that halves per 1-cm ring (10.1 / 6.0 / 3.3 / 1.7 / 0.8
     / 0.4 mm at y 0.20 .. 0.25) and is under MOVED_EPS_M from 0.26 on -> rings y >= 0.30 unmoved (pinned with
     margin). The foot part is NOT an inner piece (structural: the record's ``inner`` names the boot alone with
     ``shaft`` True, ``shaft_meshes`` returns the two shaft nodes with the record's 1372 faces each, never the
     2456-face foot parts). The rings beside the foot box DO move on this fixture (6-17 mm at y 0.02 .. 0.06): the
     shaft's band rows (body y from 0.06) have their feet on the box top 4 cm below, so the tube above the box is
     lifted by their height — the band is part of the shaft node by design; a real ankle's skin is right there.
     The over lsig != the tucked lsig; ``_state`` hem {mode over, lsig, fallback None}.
[H5] ``_state`` with tucked != ``_state`` with over -> after a toggle ``_current`` is False and ``served`` hands
     out the bare file + schedule. The boot refitted with other shaft bytes (prepared.glb replaced by
     flat_boot(shaft=0.15 / 0.14 / 0.13, shaft_to=0.12), the same ssig and fsig) -> a new shaft_sha, a new lsig
     per refit (over); the layered files of (trousers, F) are swept to LAYER_KEEP 4 by mtime: after the third
     refit the five lsigs (over-0.16 built first in this section, tucked-0.16 rebuilt after it, over-0.15 / -0.14
     / -0.13) leave the four newest — the over-0.16 file is gone, the tucked-0.16 one stays.
[H6] saved outfit: add_character_outfit({name, pieces [boots, trousers], options {boot_hem: tucked}}) ->
     apply-outfit-set (the route's body) sets equipped_options.boot_hem "tucked"; a row written WITHOUT options
     (an old set; ``get_character_outfits`` reads it with options {}) applies null; a new set saved without
     options stores the live value ("over" after the null).
[H7] (Task 11) the Wardrobe and the overview read the hem: in the [H3] state (tucked, r 0.05, too wide)
     ``garment_assembly.hem_state`` -> {boot boots, trousers trousers, mode tucked, fallback too_wide, pending
     False}; ``garment_set.wardrobe(...)["hem"]`` -> applicable True, boot_item boots, trousers_item trousers, mode
     tucked, fallback too_wide; the model overview's footwear entry adds boot_class "ankle" (the insole class of
     the 0.16 shaft) and hem {mode tucked, fallback too_wide}, its row reads "… · ankle boot · trousers over (too
     wide to tuck) · …". With over (r 0.035) the fallback is None and the row reads "trousers over"; with the
     painted bottom piece worn ``wardrobe`` says applicable False, fallback None. The saved set's preview
     (GET …/outfit-sets/{id}) carries boot_hem "tucked" ([H6]).
(On 02a2ff7a — Task 9 — ``app.core.outfit_options`` does not exist: [H1] fails on the import.)
(On 193321cf — Task 10 fix — ``garment_assembly.hem_state`` does not exist: [H7] fails on the attribute.)
"""
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []
NSEG = 64
ZC = -0.10


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want} ± {tol}"))
    if not ok:
        FAILS.append(label)


def within(label, value, lo, hi):
    ok = value is not None and lo <= value <= hi
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {value!r} in [{lo}, {hi}]")
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png_bytes(colour) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), colour).save(buf, format="PNG")
    return buf.getvalue()


def tube(radius: float, body, *, y0: float = 0.02, y1: float = 0.60):
    """A welded tube around the left leg column's axis (module docstring), skinned by clothing_weights."""
    from app.core.garment_fit import clothing_weights
    from app.core.glb_mesh import GarmentMesh
    nrings = int(round((y1 - y0) / 0.01)) + 1
    ys = np.linspace(y0, y1, nrings)
    P, U = [], []
    for i, y in enumerate(ys):
        for j in range(NSEG):
            a = j * 2 * math.pi / NSEG
            P.append((radius * math.cos(a), y, ZC + radius * math.sin(a)))
            U.append((j / NSEG, i / (nrings - 1)))
    F = []
    for i in range(nrings - 1):
        for j in range(NSEG):
            a, b = i * NSEG + j, i * NSEG + (j + 1) % NSEG
            c, d = (i + 1) * NSEG + (j + 1) % NSEG, (i + 1) * NSEG + j
            F += [(a, c, b), (a, d, c)]
    P = np.array(P, float)
    radial = (P - np.array([0.0, 0.0, ZC])) * np.array([1.0, 0.0, 1.0])
    N = radial / np.linalg.norm(radial, axis=1, keepdims=True)
    J, W = clothing_weights(P, body, skirt=False)
    return GarmentMesh(positions=P, normals=N, uvs=np.array(U, float), indices=np.array(F, np.int64),
                       joints=np.asarray(J, np.int64), weights=np.asarray(W, float), joint_names=list(body.joint_names),
                       image=png_bytes((40, 90, 160)), mime="image/png", material={"name": "cloth"})


def radii(P):
    P = np.asarray(P, float)
    return np.hypot(P[:, 0], P[:, 2] - ZC)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-hem-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.blender import refine
        from app.core import (base_body, collision, footwear_insole, footwear_source as fs, garment_assembly as ga,
                              garment_footwear as gf, garment_layers as gl, garment_store as gs, garments,
                              glb_delivery, glb_mesh, model3d, model_refs, outfit_options as oo, sync_topics)
        from app.imagegen import routing, service
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_dir, get_character_outfits,
                                          get_character_profile, save_character_outfits, save_character_profile)

        HUB, SCHEDULED = [], []

        class _NoBackends:
            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []

            def __getattr__(self, name):
                HUB.append(name)
                raise RuntimeError(f"never the image service ({name})")
        service.get_image_service = lambda: _NoBackends()
        model3d.list_mesh_backends = lambda *a, **k: {}
        model3d.list_rig_backends = lambda *a, **k: []
        routing.explain_occasion = lambda *a, **k: {}
        model_refs.schedule_outfit_render = lambda *a, **k: None
        ga.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model3d.request_lod = lambda name, path: False
        glb_delivery.delivery_path = lambda path, source=None: path
        collision.ensure_path = lambda *a, **k: None
        sync_topics.changed_at = lambda name, *a, **k: None
        model3d._validator_for = lambda rig, name: (lambda data: {"ok": True, "errors": []})

        def decimate(src, target, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return {"ok": True, "tris": target, "ratio": 1.0}
        refine.decimate_to = decimate

        # --- fixture ----------------------------------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        def boot_source(iid, mesh):
            ssig = fs.current_ssig(iid)
            d = fs.source_dir(iid, ssig)
            d.mkdir(parents=True, exist_ok=True)
            for n, c in (("upscaled.png", (1, 1, 1)), ("empty.png", (2, 2, 2)), ("cutout.png", (3, 3, 3))):
                (d / n).write_bytes(png_bytes(c))
            P, F = mesh()
            prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
            (d / "raw.glb").write_bytes(prepared)
            (d / "prepared.glb").write_bytes(prepared)
            insole = footwear_insole.analyse(prepared)
            gs.write_record(d / "insole.json", insole)
            steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                     for s in fs.ITEM_STEPS}
            steps["insole"]["version"] = footwear_insole.INSOLE_VERSION
            gs.write_record(d / "record.json", {"steps": steps})
            return insole
        boots = inventory.add_item(name="Boots", category="outfit_piece", item_id="boots", prompt_fragment="boots",
                                   outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        folder = inventory._get_item_dir(boots, create=True)
        (folder / "image.png").write_bytes(png_bytes((20, 20, 20)))
        check("boots image", inventory.set_item_image(boots, "image.png"), True)
        inventory.add_to_inventory("Demo", boots)
        insole_b = boot_source(boots, lambda: fx.flat_boot(shaft=0.16, shaft_to=0.12))
        check("boot insole ok, class ankle", (insole_b["gates"]["ok"], insole_b["shaft"]["class"]), (True, "ankle"))
        trousers = inventory.add_item(name="Trousers", category="outfit_piece", item_id="trousers",
                                      prompt_fragment="trousers",
                                      outfit_piece={"slots": ["bottom"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        painted = inventory.add_item(name="Painted", category="outfit_piece", item_id="painted", prompt_fragment="jeans",
                                     outfit_piece={"slots": ["bottom"], "outfit_types": ["casual"]})["id"]
        for iid in (trousers, painted):
            inventory.add_to_inventory("Demo", iid)

        cdir = get_character_dir("Demo")
        mdir = cdir / "model3d"
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "low").mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        base_glb = fx.foot_body_glb(leg_cell=0.01)
        (mdir / f"{bsig}.glb").write_bytes(base_glb)
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        (mdir / "unrigged" / f"{bsig}.glb").write_bytes(base_glb)
        base_sha = hashlib.sha256(base_glb).hexdigest()
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        body = glb_mesh.body_arrays(base_glb)

        profile = get_character_profile("Demo")
        profile["equipped_pieces"] = {"feet": boots, "bottom": trousers}
        check("wear boots + trousers", save_character_profile("Demo", profile), True)
        profile = get_character_profile("Demo")

        osig = model_refs.current_outfit_state("Demo")[2]
        bare = mdir / f"{osig}.glb"
        bare_low = mdir / "low" / f"{osig}.glb"
        bare.write_bytes(base_glb)
        bare_low.write_bytes(base_glb)
        bare_low.with_suffix(".json").write_text(json.dumps({"rig": "mixamo", "tier": "low", "signature": osig}))

        def write_bare_meta(unpainted, *, pieces):
            meta = {"rig": "mixamo", "format": "glb", "signature": osig, "source": "base_body",
                    "base_signature": bsig, "base_model_sha256": base_sha, "pieces": pieces,
                    "items": list(unpainted),
                    "mesh_items": {"intended": list(unpainted), "effective": list(unpainted),
                                   "unpainted": list(unpainted), "mode": "retexture", "missing": {},
                                   "warnings": []}}
            bare.with_suffix(".json").write_text(json.dumps(meta))
            return meta
        write_bare_meta([boots, trousers], pieces={"feet": boots, "bottom": trousers})

        FT = gs.garment_fsig("Demo", trousers)

        def write_trousers(r: float, *, skirt: bool = False):
            fit = gs.garment_path("Demo", trousers, FT, "fit")
            fit.parent.mkdir(parents=True, exist_ok=True)
            g = tube(r, body)
            blob = glb_mesh.graft(base_glb, g, name=f"garment_clothing_{trousers}",
                                  extras={"kind": "clothing", "item_id": trousers, "fsig": FT})
            fit.write_bytes(blob)
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": "clothing", "item_id": trousers, "fsig": FT, "base_signature": bsig,
                "base_model_sha256": base_sha, "report": {"skirt": skirt}})
            gs.garment_path("Demo", trousers, FT, "low").unlink(missing_ok=True)
            return fit, g
        asm = mdir / "assembled" / f"{osig}.glb"
        asm_low = mdir / "assembled" / "low" / f"{osig}.glb"
        layers_dir = cdir / "garments" / "layers"

        def layer_files():
            return sorted(p.name for p in layers_dir.glob(f"{trousers}_{FT}_*.glb")) if layers_dir.is_dir() else []

        def layer_record(lsig):
            return gs.read_record(gs.garment_path("Demo", trousers, FT, "layer", lsig=lsig).with_suffix(".json"))

        def trousers_node(glb: bytes):
            return glb_mesh.garment_arrays(glb, node_prefix=f"garment_clothing_{trousers}")

        # --- [H1] ------------------------------------------------------------------------------------------
        print("[H1] the mode: default over, stored tucked, the route, applicability")
        check("boot_hem(None) over", oo.boot_hem(None), "over")
        check("boot_hem(missing key) over", oo.boot_hem(profile), "over")
        check("boot_hem(null) over", oo.boot_hem({"equipped_options": {"boot_hem": None}}), "over")
        check("boot_hem(unknown) over", oo.boot_hem({"equipped_options": {"boot_hem": "sideways"}}), "over")
        check("HEM_MODES", oo.HEM_MODES, ("tucked", "over"))
        check("TOO_WIDE_WARNING (spec § 8.1)", oo.TOO_WIDE_WARNING.format(trousers="Trousers", boot="Boots"),
              "Trousers: too wide to tuck into Boots — worn over it")
        check("set_boot_hem tucked", oo.set_boot_hem("Demo", "tucked"), True)
        check("stored", (get_character_profile("Demo").get("equipped_options") or {}).get("boot_hem"), "tucked")
        check("boot_hem(profile) tucked", oo.boot_hem(get_character_profile("Demo")), "tucked")
        try:
            oo.set_boot_hem("Demo", "sideways")
            check("set_boot_hem sideways raises", "no", "ValueError")
        except ValueError:
            check("set_boot_hem sideways raises", "ValueError", "ValueError")
        app_ = oo.hem_applicable("Demo", profile=get_character_profile("Demo"))
        check("applicable before the boot fit: False, no boot", (app_["applicable"], "no boot" in app_["reason"]), (False, True))

        FB = gs.garment_fsig("Demo", boots)
        res = garments.run_garment("Demo", boots)
        check("boots fitted on the CPU", (res.get("ok"), res.get("ran"), res.get("fit"), HUB), (True, ["fit"], "accepted", []))
        brec = gs.read_record(gs.garment_path("Demo", boots, FB, "fit").with_suffix(".json"))
        check("boot record: split, class ankle", (brec["split"]["is_boot"], brec["shaft"]["class"]), (True, "ankle"))
        near("boot k", brec["scale"]["k_m_per_unit"], 1.023599, 2e-5)
        near("boot lift", brec["root_lift_m"], 0.010236, 1e-5)
        app_ = oo.hem_applicable("Demo", profile=get_character_profile("Demo"))
        check("applicable without a trousers fit: False (painted)", (app_["applicable"], app_["boot_item"], "painted" in app_["reason"]),
              (False, boots, True))
        write_trousers(0.035, skirt=True)
        app_ = oo.hem_applicable("Demo", profile=get_character_profile("Demo"))
        check("applicable with a skirt record: False", (app_["applicable"], "skirt" in app_["reason"]), (False, True))
        fit_t, tube_035 = write_trousers(0.035)
        check("tube 3776 vertices / 7424 faces", (len(tube_035.positions), len(tube_035.indices)), (3776, 7424))
        app_ = oo.hem_applicable("Demo", profile=get_character_profile("Demo"))
        check("applicable with the own-mesh tube: True", (app_["applicable"], app_["boot_item"], app_["trousers_item"], app_["mode"]),
              (True, boots, trousers, "tucked"))
        p2 = get_character_profile("Demo")
        p2["equipped_pieces"] = {"feet": boots, "bottom": painted}
        save_character_profile("Demo", p2)
        app_ = oo.hem_applicable("Demo", profile=get_character_profile("Demo"))
        check("applicable with a painted bottom piece: False", app_["applicable"], False)
        p2["equipped_pieces"] = {"feet": boots, "bottom": trousers}
        save_character_profile("Demo", p2)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import sessions, users
        from app.routes.characters import router
        uid = users.create_user("demo-admin", "temporary-smoke-password", users.ROLE_ADMIN, allowed_characters=["Demo"])
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=True)
        client.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(uid))
        SCHEDULED.clear()
        r = client.post("/characters/Demo/outfit-options", json={"boot_hem": "sideways"})
        check("route sideways 400", r.status_code, 400)
        r = client.post("/characters/Demo/outfit-options", json={"boot_hem": None})
        check("route null 200", (r.status_code, r.json().get("boot_hem")), (200, None))
        check("route null stored", (get_character_profile("Demo").get("equipped_options") or {}).get("boot_hem"), None)
        r = client.post("/characters/Demo/outfit-options", json={"boot_hem": "tucked"})
        check("route tucked 200", (r.status_code, r.json().get("boot_hem"), (r.json().get("applicable") or {}).get("applicable")),
              (200, "tucked", True))
        check("route schedules the assembly", SCHEDULED, [("Demo", None), ("Demo", None)])
        r = client.get("/characters/Demo/outfit-options")
        check("route GET", (r.status_code, r.json().get("boot_hem"), (r.json().get("applicable") or {}).get("trousers_item")),
              (200, "tucked", trousers))
        check("route unknown character 404", client.get("/characters/Nobody/outfit-options").status_code, 404)

        # --- [H2] tucked -----------------------------------------------------------------------------------
        print("[H2] tucked, r 0.035: the trouser leg is cut at the shaft top minus the reserve")
        top_m = 0.16 * brec["scale"]["k_m_per_unit"] - brec["root_lift_m"]
        near("shaft top in body space 0.153540", top_m, 0.153540, 2e-5)
        plane = top_m - gl.TUCK_RESERVE_M
        check("TUCK_RESERVE_M 0.03, TUCKED_POKE_MAX 0.01", (gl.TUCK_RESERVE_M, gl.TUCKED_POKE_MAX), (0.03, 0.01))
        wanted = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        tw = next(g for g in wanted if g["item_id"] == trousers)
        check("plan: trousers over the boot, tucked, pending", (sorted(tw["over"]["items"]), tw["over"]["pending"], tw["hem"]["mode"]),
              ([boots], True, "tucked"))
        res = ga.assemble("Demo", osig)
        check("assemble tucked", res, {"ok": True, "tiers": {"full": "assembled", "low": "assembled"}})
        wanted = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        tw = next(g for g in wanted if g["item_id"] == trousers)
        lsig_t = tw["over"]["lsig"]
        rec_t = layer_record(lsig_t)
        hem_t = rec_t.get("hem") or {}
        check("record hem mode / built / fallback", (hem_t.get("mode"), hem_t.get("built"), hem_t.get("fallback")),
              ("tucked", "tucked", None))
        near("record plane_m 0.123540", hem_t.get("plane_m"), 0.123540, 2e-5)
        near("record plane_m = top - 0.03 (float32 shaft top)", hem_t.get("plane_m"), plane, 1e-6)
        plane_rec = float(hem_t.get("plane_m"))
        check("record tucked_poke 0 over 320 vertices", (hem_t.get("tucked_poke"), hem_t.get("tucked_n"), hem_t.get("tucked_outside")), (0.0, 320, 0))
        check("record cut 1280 / 128 / 128", hem_t.get("cut"), {"removed_faces": 1280, "bisected_faces": 128, "new_vertices": 128})
        shafts = gl.shaft_meshes(gs.garment_path("Demo", boots, FB, "fit").read_bytes(), boots)
        check("two shaft nodes", len(shafts), 2)
        check("inner = {boots: shaft_sha}", rec_t.get("inner", {}).get(boots, {}).get("sha256"), gl.shaft_sha(shafts))
        check("lsig = layer_sig(inner, tucked, plane)", lsig_t, gl.layer_sig({boots: gl.shaft_sha(shafts)}, mode="tucked", plane_m=plane))
        check("plain layer_sig unchanged (Task 2 payload)", gl.layer_sig({"slip": "abc"}),
              hashlib.md5(json.dumps({"inner": {"slip": "abc"}, "version": 1}, sort_keys=True).encode()).hexdigest()[:12])
        node_t = trousers_node(asm.read_bytes())
        Pt = np.asarray(node_t.positions, float)
        check("tucked node 3200 vertices / 6208 faces", (len(Pt), len(node_t.indices)), (3200, 6208))
        near("lowest vertex = the plane (float32)", float(Pt[:, 1].min()), plane_rec, 1e-7)
        check("128 vertices ON the plane", int((np.abs(Pt[:, 1] - plane_rec) <= 1e-7).sum()), 128)
        check("nothing below the plane", bool(np.all(Pt[:, 1] >= plane_rec - 1e-7)), True)
        t_frac = (plane_rec - 0.12) / 0.01
        r_diag = 0.035 * math.sqrt((1 - t_frac) ** 2 + t_frac ** 2 + 2 * t_frac * (1 - t_frac) * math.cos(2 * math.pi / NSEG))
        near("diagonal cut points at r 0.034961", r_diag, 0.034961, 2e-6)
        rt = radii(Pt)
        check("tucked: 3136 vertices at r 0.035, the 64 diagonal cut points at 0.034961 (nothing layered)",
              (int((np.abs(rt - 0.035) <= 1e-6).sum()), int((np.abs(rt - r_diag) <= 1e-6).sum())), (3136, 64))
        side_full = ga.read_sidecar(asm)
        check("sidecar garments.trousers hem", side_full["garments"][trousers].get("hem"),
              {"mode": "tucked", "lsig": lsig_t, "fallback": None})
        check("sidecar garments.trousers over", side_full["garments"][trousers].get("over"), lsig_t)
        state_t = ga._state(wanted, "full")
        check("served = assembled", ga.served("Demo", bare, "full"), asm)

        # --- [H4] over ------------------------------------------------------------------------------------
        print("[H4] over, r 0.035: layered over the shaft nodes")
        check("toggle over", oo.set_boot_hem("Demo", "over"), True)
        wanted_o = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        state_o = ga._state(wanted_o, "full")
        check("[H5] state tucked != state over", state_t != state_o, True)
        check("[H5] _current False after the toggle", ga._current(asm, bare, state_o), False)
        SCHEDULED.clear()
        check("[H5] served = bare + schedule", (ga.served("Demo", bare, "full"), SCHEDULED), (bare, [("Demo", osig)]))
        res = ga.assemble("Demo", osig)
        check("assemble over", res["tiers"], {"full": "assembled", "low": "assembled"})
        wanted_o = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        tw = next(g for g in wanted_o if g["item_id"] == trousers)
        lsig_o = tw["over"]["lsig"]
        check("over lsig != tucked lsig", lsig_o != lsig_t, True)
        check("over lsig = layer_sig(inner, over)", lsig_o, gl.layer_sig({boots: gl.shaft_sha(shafts)}, mode="over"))
        rec_o = layer_record(lsig_o)
        check("record hem over", ((rec_o.get("hem") or {}).get("mode"), (rec_o.get("hem") or {}).get("built"),
                                  (rec_o.get("hem") or {}).get("fallback")), ("over", "over", None))
        node_o = trousers_node(asm.read_bytes())
        Po = np.asarray(node_o.positions, float)
        P0 = np.asarray(tube_035.positions, float)
        check("over: 3776 vertices (nothing cut)", len(Po), 3776)
        lat = np.abs(Po[:, 2] - ZC)
        beside_z = (np.abs(P0[:, 0]) <= 0.015) & (P0[:, 1] >= 0.11 - 1e-9) & (P0[:, 1] <= 0.15 + 1e-9)
        within("beside the z faces: min |z - zc| (>= 0.0544 - 0.0005)", float(lat[beside_z].min()), 0.0544 - 0.0005, 0.0544 + 0.0025)
        behind = (np.abs(P0[:, 2] - ZC) <= 0.015) & (P0[:, 0] < 0) & (P0[:, 1] >= 0.11 - 1e-9) & (P0[:, 1] <= 0.15 + 1e-9)
        within("behind the column: max x (<= -0.083 + 0.0005)", float(Po[behind, 0].max()), -0.083 - 0.0025, -0.083 + 0.0005)
        front = (np.abs(P0[:, 2] - ZC) <= 0.015) & (P0[:, 0] > 0) & (P0[:, 1] >= 0.11 - 1e-9) & (P0[:, 1] <= 0.15 + 1e-9)
        within("in front of the column: min x (>= 0.0636 - 0.0005)", float(Po[front, 0].min()), 0.0636 - 0.0005, 0.0636 + 0.0025)
        from app.core.garment_fit import MOVED_EPS_M
        high = P0[:, 1] >= 0.30 - 1e-9
        within("y >= 0.30 unmoved (max |dr|)", float(np.linalg.norm(Po[high] - P0[high], axis=1).max()), 0.0, MOVED_EPS_M)
        ring25 = np.abs(P0[:, 1] - 0.25) <= 1e-6
        within("the smoothing's tail at y 0.25 (0.3 .. 0.5 mm)", float(np.linalg.norm(Po[ring25] - P0[ring25], axis=1).max()), 0.0003, 0.0005)
        check("the foot part is no inner piece: inner = the boot's shaft alone",
              (sorted(rec_o.get("inner") or {}), (rec_o.get("inner") or {}).get(boots, {}).get("shaft")), ([boots], True))
        check("shaft_meshes = the two shaft nodes (1372 faces each, the record's parts.shaft), never the foot parts",
              ([len(s_.indices) for s_ in shafts], brec["sides"]["left"]["parts"]), ([1372, 1372], {"foot": 2456, "shaft": 1372}))
        low_rings = P0[:, 1] <= 0.06 + 1e-9
        within("the rings above the foot box are lifted by the shaft's band rows (fixture: 6 .. 17 mm)",
               float(np.linalg.norm(Po[low_rings] - P0[low_rings], axis=1).max()), 0.006, 0.02)
        check("sidecar hem over", ga.read_sidecar(asm)["garments"][trousers].get("hem"),
              {"mode": "over", "lsig": lsig_o, "fallback": None})
        check("both layered files kept (the cache)", layer_files(), sorted([f"{trousers}_{FT}_{lsig_t}.glb", f"{trousers}_{FT}_{lsig_o}.glb"]))
        check("back to tucked: current, no build", (oo.set_boot_hem("Demo", "tucked"), ga.assemble("Demo", osig)["tiers"]),
              (True, {"full": "assembled", "low": "assembled"}))
        check("tucked served again from the cached file", trousers_node(asm.read_bytes()).positions.shape[0], 3200)

        # --- [H3] too wide ---------------------------------------------------------------------------------
        print("[H3] tucked, r 0.05: too wide — the over geometry with the fallback")
        fit_t, tube_05 = write_trousers(0.05)
        res = ga.assemble("Demo", osig)
        check("assemble r 0.05 tucked", res["tiers"], {"full": "assembled", "low": "assembled"})
        wanted_w = ga._wanted("Demo", get_character_profile("Demo"), bare_meta=ga._read_json(bare.with_suffix(".json")))
        tw = next(g for g in wanted_w if g["item_id"] == trousers)
        lsig_w = tw["over"]["lsig"]
        check("the same tucked lsig (the inner and the plane did not change)", lsig_w, lsig_t)
        rec_w = layer_record(lsig_w)
        hem_w = rec_w.get("hem") or {}
        check("fallback too_wide, built over", (hem_w.get("mode"), hem_w.get("built"), hem_w.get("fallback")),
              ("tucked", "over", gl.HEM_FALLBACK_TOO_WIDE))
        check("tucked_poke 110 / 320 = 0.34375", (hem_w.get("tucked_n"), hem_w.get("tucked_outside")), (320, 110))
        near("tucked_poke value", hem_w.get("tucked_poke"), 0.34375, 1e-12)
        check("wanted hem fallback", tw["hem"]["fallback"], gl.HEM_FALLBACK_TOO_WIDE)
        check("_state hem", ga._state(wanted_w, "full")[trousers].get("hem"),
              {"mode": "tucked", "lsig": lsig_t, "fallback": gl.HEM_FALLBACK_TOO_WIDE})
        node_w = trousers_node(asm.read_bytes())
        Pw = np.asarray(node_w.positions, float)
        check("the over geometry: 3776 vertices / 7424 faces (nothing cut)", (len(Pw), len(node_w.indices)), (3776, 7424))
        P5 = np.asarray(tube_05.positions, float)
        beside_z = (np.abs(P5[:, 0]) <= 0.015) & (P5[:, 1] >= 0.11 - 1e-9) & (P5[:, 1] <= 0.15 + 1e-9)
        within("pushed over the shaft beside the z faces (>= 0.0544 - 0.0005)", float(np.abs(Pw[beside_z, 2] - ZC).min()),
               0.0544 - 0.0005, 0.0544 + 0.0025)
        check("tucked_poke on the cut r 0.05 tube by hand: 110 of 320",
              gl.tucked_poke(gl._prim_mesh(__import__("app.core.footwear_cut", fromlist=["plane_cut"]).plane_cut(
                  gl._mesh_prim(tube_05), y_m=plane)[0], tube_05), shafts, plane, top_m),
              {"tucked_poke": 110 / 320, "n": 320, "outside": 110})
        check("old layered fits of another body fit pruned (foreign)", layer_files(), [f"{trousers}_{FT}_{lsig_t}.glb"])

        # --- [H7] the Wardrobe + the overview read the hem (Task 11) --------------------------------------
        print("[H7] the Wardrobe payload and the overview row")
        from app.core import garment_set, model_overview as mo
        check("[H7] hem_state too wide", ga.hem_state("Demo"),
              {"boot": boots, "trousers": trousers, "mode": "tucked", "fallback": gl.HEM_FALLBACK_TOO_WIDE,
               "pending": False})
        hem_wr = garment_set.wardrobe("Demo")["hem"]
        check("[H7] wardrobe hem", {k: hem_wr.get(k) for k in ("applicable", "boot_item", "trousers_item", "mode",
                                                               "fallback")},
              {"applicable": True, "boot_item": boots, "trousers_item": trousers, "mode": "tucked",
               "fallback": gl.HEM_FALLBACK_TOO_WIDE})

        def boot_row():
            entries, _w = mo._assembled_garments("Demo", osig)
            boot = next(e for e in entries if e["item_id"] == boots)
            row = next(r for r in mo._garment_steps(entries, []) if r["id"] == f"garment_{boots}")
            return boot, row["detail"]
        boot_e, detail = boot_row()
        check("[H7] overview entry", (boot_e.get("boot_class"), boot_e.get("hem")),
              ("ankle", {"mode": "tucked", "fallback": gl.HEM_FALLBACK_TOO_WIDE}))
        check("[H7] overview row", "· ankle boot · trousers over (too wide to tuck) ·" in detail, True)
        write_trousers(0.035)
        check("[H7] over", oo.set_boot_hem("Demo", "over"), True)
        check("[H7] assemble over", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
        check("[H7] wardrobe fallback None over", garment_set.wardrobe("Demo")["hem"]["fallback"], None)
        boot_e, detail = boot_row()
        check("[H7] overview row over", (boot_e.get("hem"), "· ankle boot · trousers over ·" in detail),
              ({"mode": "over", "fallback": None}, True))
        p7 = get_character_profile("Demo")
        p7["equipped_pieces"] = {"feet": boots, "bottom": painted}
        check("[H7] wear the painted bottom", save_character_profile("Demo", p7), True)
        hem_p = garment_set.wardrobe("Demo")["hem"]
        check("[H7] painted: no control", (hem_p["applicable"], hem_p["fallback"]), (False, None))
        p7 = get_character_profile("Demo")
        p7["equipped_pieces"] = {"feet": boots, "bottom": trousers}
        check("[H7] trousers again", save_character_profile("Demo", p7), True)
        check("[H7] back to tucked", oo.set_boot_hem("Demo", "tucked"), True)
        check("[H7] assemble tucked r 0.035", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})

        # --- [H5] refits ----------------------------------------------------------------------------------
        print("[H5] a refitted boot: new shaft bytes, new lsig; LAYER_KEEP sweeps the oldest")
        check("over again", oo.set_boot_hem("Demo", "over"), True)
        check("assemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
        check("tucked", oo.set_boot_hem("Demo", "tucked"), True)
        check("assemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
        check("over", oo.set_boot_hem("Demo", "over"), True)
        check("assemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
        files_before = layer_files()
        check("two files: tucked-0.16, over-0.16", len(files_before), 2)
        lsigs = [lsig_t, lsig_o]
        ssig = fs.current_ssig(boots)
        src = fs.source_dir(boots, ssig)
        for shaft_h in (0.15, 0.14, 0.13):
            P, F = fx.flat_boot(shaft=shaft_h, shaft_to=0.12)
            prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
            (src / "prepared.glb").write_bytes(prepared)
            gs.write_record(src / "insole.json", footwear_insole.analyse(prepared))
            check(f"refit {shaft_h}", gf.fit("Demo", boots, FB, profile=get_character_profile("Demo")),
                  gs.garment_path("Demo", boots, FB, "fit"))
            shafts_n = gl.shaft_meshes(gs.garment_path("Demo", boots, FB, "fit").read_bytes(), boots)
            lsig_n = gl.layer_sig({boots: gl.shaft_sha(shafts_n)}, mode="over")
            check(f"refit {shaft_h}: a new lsig", lsig_n not in lsigs, True)
            lsigs.append(lsig_n)
            check(f"refit {shaft_h}: assemble", ga.assemble("Demo", osig)["tiers"], {"full": "assembled", "low": "assembled"})
            check(f"refit {shaft_h}: served under the new lsig", ga.read_sidecar(asm)["garments"][trousers].get("over"), lsig_n)
        check("LAYER_KEEP 4: the over-0.16 file (the oldest by mtime) is gone, the four newest stay", layer_files(),
              sorted(f"{trousers}_{FT}_{s_}.glb" for s_ in [lsigs[0]] + lsigs[2:]))

        # --- [H6] saved outfits ---------------------------------------------------------------------------
        print("[H6] saved outfits carry the hem")
        from app.routes.inventory import _apply_outfit_set_route_sync
        oid = add_character_outfit("Demo", {"name": "Boots day", "pieces": [boots, trousers], "options": {"boot_hem": "tucked"}})
        saved = next(o for o in get_character_outfits("Demo") if o["id"] == oid)
        check("stored options", saved.get("options"), {"boot_hem": "tucked"})
        from app.routes.inventory import preview_outfit_set_route
        check("[H7] the preview carries boot_hem", preview_outfit_set_route("Demo", oid, _admin=None).get("boot_hem"),
              "tucked")
        check("live over before the apply", oo.boot_hem(get_character_profile("Demo")), "over")
        res = _apply_outfit_set_route_sync("Demo", {"outfit_id": oid})
        check("apply: pieces equipped", (res["status"], sorted(get_character_profile("Demo")["equipped_pieces"].items())),
              ("ok", sorted({"feet": boots, "bottom": trousers}.items())))
        check("apply: boot_hem tucked", (get_character_profile("Demo").get("equipped_options") or {}).get("boot_hem"), "tucked")
        outfits = get_character_outfits("Demo")
        outfits.append({"id": "oldrow01", "name": "Old", "outfit": "", "pieces": [boots, trousers], "locations": [],
                        "activities": [], "excluded_locations": [], "image": ""})
        save_character_outfits("Demo", outfits)
        old = next(o for o in get_character_outfits("Demo") if o["id"] == "oldrow01")
        check("old row reads options {}", old.get("options"), {})
        _apply_outfit_set_route_sync("Demo", {"outfit_id": "oldrow01"})
        check("old row applies null", (get_character_profile("Demo").get("equipped_options") or {}).get("boot_hem"), None)
        check("null reads over", oo.boot_hem(get_character_profile("Demo")), "over")
        oid2 = add_character_outfit("Demo", {"name": "Plain", "pieces": [boots, trousers]})
        check("a new set without options stores the live value", next(o for o in get_character_outfits("Demo") if o["id"] == oid2).get("options"),
              {"boot_hem": "over"})
        check("no hub", HUB, [])
        client.close()

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
