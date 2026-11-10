#!/usr/bin/env python3
"""Refit before re-render (app/core/garment_source.py, user decision
2026-11-10): new base images refit an own-mesh piece from its last accepted
source on the CPU; only a refused refit renders the chain again.

Usage:
    ./.venv/bin/python scripts/smoke_garment_refit_source.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. The fixture and the stubs are the ones of
smoke_garment_chain.py (imported from it: the hair item on the edit chain,
head sphere + torso cylinder, 1000 px per unit, images W 1024 x H 1200 on
grey 128, a recorder for every render, a mesh stub writing the hair cap,
decimate_to copying its input). The one change: every base gets its views
moved DOWN by ``dy`` px (grey fill above), and the render stub moves its
answer by the dy of the base it renders on, so the images of a base stay
consistent with it (the chain's gates pass on every base).

Hand-derived numbers. The base mask: head disc centre row 200 + torso rows
[300, 1100) -> rows [100, 1100), Hb = 1000 px. Trunk (``TRUNK_HALF`` 0.08):
the head row 100 + 0.05 x 1000 = 150 has the disc's columns centred on 512,
so the trunk is cols [432, 592] of both masks. Moving a base by dy moves
the whole trunk by dy: ``garment_gates.register`` finds shift_px [dy, 0]
(row, col), scale 1.0, shift_abs dy / 1000 Hb; the caps allow 0.04 Hb.
  B1 dy 0, B2 dy 20, B3 dy 80.
  B1 -> B2: shift 20 px = 0.02 Hb  -> within the caps: refit accepted.
  B2 -> B3: shift 60 px = 0.06 Hb  -> beyond the caps: FrameRefused.

[1] Full run on B1 (F1): 4 renders, 1 mesh call; the group F1 keeps the
    base views of B1 (``ensure_current``): source_of(F1).bsig = B1,
    base_images = the sha256 of B1's two views; fit record refitted False,
    source.fsig F1.
[2] New profile image -> B2 (dy 20): after_base_model -> 0 renders, 0 mesh
    calls, 1 decimation (the low tier of the new fit; the prepared mesh is a
    copy); fit record F2 accepted on B2, refitted True, source {fsig F1,
    bsig B1, materialized_from F1}, frame.registered True with
    registration.shift_px [20, 0], scale 1.0, shift_abs 0.02; the haired
    front of F2 is marked copied_from F1; garment_info.refit = {source_bsig
    B1, source_fsig F1, materialized_from F1, registration {shift 0.02,
    scale 1.0}, first_step "haired"}.
[3] GC (explicit, after [2]): the group F1 (old base, not current, not the
    newest accepted fit) is an orphan; the group F2 — which holds the copied
    source — is not, and its copies are still on disk afterwards; F1's fit
    and base copy are gone; no base copy is an "unknown" file (the image name
    pattern covers ``{item}_{fsig}_base_{view}.png``).
[4] Manual Re-render (explicit run of "haired", force): the copies go,
    the chain renders: 4 renders, 1 mesh call; fit record refitted False,
    source.fsig F2 (its own base copy of B2); garment_info.refit None.
[5] B3 (dy 80): the refit from F2 is refused (0.06 Hb > 0.04) -> the same
    run renders the chain: 4 renders, 1 mesh call, ok; fit record F3
    refitted False, source.fsig F3; no file of F3 carries copied_from.
[6] The piece's own inputs changed (hair colour; base unchanged): no
    source names the current inputs -> no refit: 4 renders, 1 mesh call.
[7] Arms (garment_source.arm_numbers / arm_gate on synthetic geometry).
    Body: per side an arm cylinder r 0.030 along +-x at y 1.4, z 0, rings
    of 24 points every 5 mm from |x| 0.100 to 0.750; weights by |x|:
    Shoulder below 0.18, Arm to 0.43, ForeArm to 0.67, Hand beyond, the
    rings AT 0.18 / 0.43 / 0.67 half and half -> shoulder (0.18, 1.4, 0),
    elbow (0.43, 1.4, 0), wrist (0.67, 1.4, 0) (ring means), both limb
    radii 0.030 (every dominant ring point lies on r). A torso block at
    |x| < 0.09 weighted Spine. Joint order Hips, Spine, LeftShoulder, LeftArm,
    LeftForeArm, LeftHand, Right…: a tie goes to the lower index, so the
    0.18 ring is the Shoulder's.
    Sleeve = rings of 36 points, r 0.045 (excess 0.015 < 0.04), every 5 mm
    from |x| 0.120 to x_end. On the arm (nearest body ring = same x, the same
    angles on every ring): the rings 0.185 .. x_end.
    LONG  x_end 0.66: 96 rings, 3456 values, the p99 index 0.99 x 3455 =
          3420.45 lies in the last ring (3420 .. 3455) -> reach_fore =
          (0.66 - 0.43) / 0.24 = 0.9583; off_fore 0.0.
    SHORT x_end 0.55: 74 rings, p99 index 2636.37 in the last ring (2628 ..
          2663) -> reach_fore 0.5; drop 0.4583 > 0.04: refused "short".
    HANG  LONG with the rings beyond x 0.43 moved 0.05 down: a point of such a
          ring at angle phi (y = -0.05 + 0.045 cos phi, z = 0.045 sin phi) is
          d^2 = 0.004525 - 0.0045 cos phi from the forearm axis; d > 0.07
          (r + 4 cm) for cos phi < -0.0833, i.e. phi 100 .. 260 deg = 17 of 36
          points; the forearm set = the rings 0.43 .. 0.66 = 47 rings, 46 of them
          moved -> off_fore = 46 x 17 / (47 x 36) = 0.4622 (> 0 + 0.10):
          refused "off the forearm"; reach unchanged 0.9583.
    LONG against itself: ok.
[8] Wiring: a refit whose source has sleeves (source_arms stubbed to the LONG
    numbers) and whose fit is SHORT (arm_numbers stubbed): B4 (dy 60; from the
    [6] group on B3, dy 80: shift -20 px = 0.02 Hb, inside the caps) -> the arm
    gate refuses the refit, the same run renders the chain: ok, 4 renders,
    1 mesh call, the fit refitted False, no file carries copied_from.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_garment_chain as sc  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def moved(arr, dy):
    """``arr`` moved down by dy px, grey above."""
    if not dy:
        return arr
    out = np.full_like(arr, 128)
    out[dy:] = arr[:-dy]
    return out


ARM_JOINTS = ["Hips", "Spine"] + [f"{s}{b}" for s in ("Left", "Right") for b in ("Shoulder", "Arm", "ForeArm", "Hand")]


def arm_body():
    """[7]'s body: two arm cylinders + a torso block (docstring)."""
    from app.core.glb_mesh import BodyMesh
    P, J, W = [], [], []
    angles = np.radians(np.arange(24) * 15.0)

    def add(point, joints, weights):
        P.append(point)
        J.append(list(joints) + [0] * (4 - len(joints)))
        W.append(list(weights) + [0.0] * (4 - len(weights)))

    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        idx = {b: ARM_JOINTS.index(side + b) for b in ("Shoulder", "Arm", "ForeArm", "Hand")}
        for k in range(131):
            x = round(0.100 + 0.005 * k, 3)
            if x < 0.18:
                jw = ([idx["Shoulder"]], [1.0])
            elif x == 0.18:
                jw = ([idx["Shoulder"], idx["Arm"]], [0.5, 0.5])
            elif x < 0.43:
                jw = ([idx["Arm"]], [1.0])
            elif x == 0.43:
                jw = ([idx["Arm"], idx["ForeArm"]], [0.5, 0.5])
            elif x < 0.67:
                jw = ([idx["ForeArm"]], [1.0])
            elif x == 0.67:
                jw = ([idx["ForeArm"], idx["Hand"]], [0.5, 0.5])
            else:
                jw = ([idx["Hand"]], [1.0])
            for a in angles:
                add([sign * x, 1.4 + 0.03 * np.cos(a), 0.03 * np.sin(a)], *jw)
    for x in np.linspace(-0.08, 0.08, 9):
        for y in np.linspace(1.0, 1.5, 11):
            for z in (-0.08, 0.08):
                add([x, y, z], [ARM_JOINTS.index("Spine")], [1.0])
    return BodyMesh(positions=np.asarray(P, np.float64), faces=np.zeros((0, 3), np.int64),
                    uvs=np.zeros((len(P), 2)), joints=np.asarray(J, np.int64), weights=np.asarray(W, np.float64),
                    joint_names=["mixamorig:" + n for n in ARM_JOINTS])


def sleeves(x_end, hang=0.0):
    """[7]'s sleeves: rings of 36 points, r 0.045, from |x| 0.120 to x_end; ``hang`` moves the rings beyond
    |x| 0.43 down."""
    out = []
    angles = np.radians(np.arange(36) * 10.0)
    for sign in (1.0, -1.0):
        for k in range(int(round((x_end - 0.12) / 0.005)) + 1):
            x = round(0.12 + 0.005 * k, 3)
            dy = -hang if x > 0.43 else 0.0
            for a in angles:
                out.append([sign * x, 1.4 + dy + 0.045 * np.cos(a), 0.045 * np.sin(a)])
    return np.asarray(out, np.float64)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-refit-source-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.blender import refine
        from app.core import (artefact_graph, base_body, expression_regen, garment_assembly, garment_hair,
                              garment_source, garments, sync_topics)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # --- stubs (smoke_garment_chain's, the renders moved by the base's dy) ----
        RENDERS, MESHES, DECIMATES = [], [], []
        state = {"dy": 0}
        charmod.run_rembg = sc.rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            RENDERS.append((g["step"], g["view"], g["fsig"]))
            arr = moved(sc.HAIRED if g["step"] == "haired" else sc.GHOST, state["dy"])
            side = kw["override_width"]
            canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(sc.png(canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        class FakeService:
            def generate_mesh(self, **kw):
                MESHES.append(kw)
                Path(kw["output_path"]).write_bytes(sc.hair_glb())
                return {"ok": True, "path": kw["output_path"], "backend": "FakeMesh",
                        "routing": {"occasion": kw.get("occasion")}}

            def upscale_image(self, data, **kw):
                raise RuntimeError("no upscaler in the smoke")

            def list_upscale_backends(self):
                return []

            def list_face_retexture_backends(self):
                return []

        service.get_image_service = lambda: FakeService()

        def decimate_to(path_in, target_tris, out, merge_vertices=False):
            data = Path(path_in).read_bytes()
            DECIMATES.append(Path(out).parent.name)
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(data)
            return {"ok": True, "path": str(out), "tris_before": 1, "tris": 1, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: True
        sync_topics.changed_at = lambda *a, **k: None

        # --- fixture -----------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        for i in (1, 2, 3, 4):
            (images / f"Demo_{i}.png").write_bytes(sc.solid_png((50, 60, 69 + i), 7 + i))
        refs = get_character_dir("Demo") / "model_refs"
        mdir = get_character_dir("Demo") / "model3d"

        def use_profile_image(n):
            stored = get_character_profile("Demo")
            stored["profile_image"] = f"Demo_{n}.png"
            check(f"profile image {n}", save_character_profile("Demo", stored), True)
            return base_body.base_signature("Demo")

        def write_base(bsig, dy):
            refs.mkdir(parents=True, exist_ok=True)
            for v in base_body.BASE_VIEWS:
                stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
                (refs / f"{stem}.png").write_bytes(sc.png(moved(sc.BASE, dy)))
                (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
            unrigged, rigged = sc.base_bodies()
            (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
            (mdir / "unrigged" / f"{bsig}.glb").write_bytes(unrigged)
            (mdir / f"{bsig}.glb").write_bytes(rigged)
            (mdir / f"{bsig}.json").write_text(json.dumps({
                "base": True, "rig": "mixamo", "signature": bsig, "format": "glb", "source": "generated"}))
            state["dy"] = dy

        b1 = use_profile_image(1)
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        write_base(b1, 0)

        def counts():
            return len(RENDERS), len(MESHES), len(DECIMATES)

        def delta(before):
            now = counts()
            return tuple(n - b for n, b in zip(now, before))

        def fit_record(fsig):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "fit").with_suffix(".json"))

        def view_shas(bsig):
            return garment_source.current_base_images("Demo", bsig)

        # --- [1] ---------------------------------------------------------------------
        print("[1] full run on B1")
        f1 = gs.garment_fsig("Demo", hid)
        before = counts()
        res = garments.run_garment("Demo", hid)
        check("ok", (res.get("ok"), res.get("fsig")), (True, f1))
        check("4 renders, 1 mesh", delta(before)[:2], (4, 1))
        src = garment_source.source_of("Demo", hid, f1)
        check("F1 keeps B1's views", (src.get("bsig"), src.get("base_images")), (b1, view_shas(b1)))
        rec1 = fit_record(f1)
        check("fit F1 own", (rec1.get("accepted"), rec1.get("refitted"), (rec1.get("source") or {}).get("fsig")),
              (True, False, f1))

        # --- [2] ---------------------------------------------------------------------
        print("[2] new base images (B2, dy 20) -> refit, no job")
        b2 = use_profile_image(2)
        check("bsig changed", b2 != b1, True)
        write_base(b2, 20)
        f2 = gs.garment_fsig("Demo", hid)
        check("fsig changed", f2 != f1, True)
        before = counts()
        check("after_base_model starts", garments.after_base_model("Demo"), True)
        check("idle", garments.wait_idle(120), True)
        check("0 renders, 0 mesh, 1 decimation (low)", delta(before), (0, 0, 1))
        rec2 = fit_record(f2)
        source = rec2.get("source") or {}
        check("fit F2 on B2, refitted", (rec2.get("accepted"), rec2.get("base_signature"), rec2.get("refitted")),
              (True, b2, True))
        check("source", (source.get("fsig"), source.get("bsig"), source.get("materialized_from")), (f1, b1, f1))
        frame = rec2.get("frame") or {}
        reg = frame.get("registration") or {}
        check("registered", frame.get("registered"), True)
        check("shift_px [20, 0]", [round(v) for v in reg.get("shift_px") or []], [20, 0])
        check("scale 1.0, shift_abs 0.02", (round(reg.get("scale", 0), 3), round(reg.get("shift_abs", 0), 3)),
              (1.0, 0.02))
        copied = gs.garment_path("Demo", hid, f2, "image", step="haired", view="front")
        check("haired front copied", gs.read_record(copied.with_suffix(".json")).get("copied_from"), f1)
        info = garments.garment_info("Demo", hid)
        refit = info.get("refit") or {}
        check("garment_info.refit", (refit.get("source_bsig"), refit.get("source_fsig"),
                                     refit.get("materialized_from"), refit.get("first_step")),
              (b1, f1, f1, "haired"))
        check("garment_info.refit registration",
              {k: round(v, 3) for k, v in (refit.get("registration") or {}).items()}, {"shift": 0.02, "scale": 1.0})

        # --- [3] ---------------------------------------------------------------------
        print("[3] GC keeps the used source (the copies in F2), removes the unused group F1")
        report = artefact_graph.collect("Demo", explicit=True, reason="smoke")
        orphans = {o["key"] for o in report["orphans"]}
        check("F1 group orphan", f"garment:{hid}_{f1}" in orphans, True)
        check("F2 group kept", f"garment:{hid}_{f2}" in orphans, False)
        check("F2 copies on disk", (copied.is_file(), garment_source.base_copy("Demo", hid, f2, "front").is_file(),
                                    gs.garment_path("Demo", hid, f2, "prepared").is_file()), (True, True, True))
        check("F1 files gone (fit, base copy)", (gs.garment_path("Demo", hid, f1, "fit").is_file(),
                                                 garment_source.base_copy("Demo", hid, f1, "front").is_file()),
              (False, False))
        check("base copies are known files", [u for u in report["unknown"] if "_base_" in u], [])

        # --- [4] ---------------------------------------------------------------------
        print("[4] manual Re-render: the chain runs")
        before = counts()
        res = garments.run_garment("Demo", hid, steps=refit.get("first_step") or "haired", force=True)
        check("ok", res.get("ok"), True)
        check("4 renders, 1 mesh", delta(before)[:2], (4, 1))
        rec4 = fit_record(f2)
        check("fit F2 own", (rec4.get("accepted"), rec4.get("refitted"), (rec4.get("source") or {}).get("fsig"),
                             (rec4.get("source") or {}).get("bsig")), (True, False, f2, b2))
        check("haired front rendered", gs.read_record(copied.with_suffix(".json")).get("copied_from"), None)
        check("garment_info.refit None", garments.garment_info("Demo", hid).get("refit"), None)

        # --- [5] ---------------------------------------------------------------------
        print("[5] B3 (dy 80): refit refused -> full chain in the same run")
        b3 = use_profile_image(3)
        write_base(b3, 80)
        f3 = gs.garment_fsig("Demo", hid)
        check("fsig changed", f3 not in (f1, f2), True)
        before = counts()
        res = garments.run_garment("Demo", hid)
        check("ok, whole chain", (res.get("ok"), res.get("ran")), (True, ["haired", "ghost", "cutout", "mesh", "fit"]))
        check("4 renders, 1 mesh", delta(before)[:2], (4, 1))
        rec5 = fit_record(f3)
        check("fit F3 own", (rec5.get("accepted"), rec5.get("refitted"), (rec5.get("source") or {}).get("fsig")),
              (True, False, f3))
        marked = [p.name for p in gs.stored_groups("Demo").get((hid, f3), [])
                  if p.suffix == ".png" and gs.read_record(p.with_suffix(".json")).get("copied_from")]
        check("no copied file in F3", marked, [])
        check("status idle", (gs.status("Demo", hid)["running_step"], gs.status("Demo", hid)["failed"]),
              (None, None))

        # --- [6] ---------------------------------------------------------------------
        print("[6] the piece's own inputs changed -> no refit")
        stored = get_character_profile("Demo")
        stored["body_slots"]["hair"]["color"] = "black"
        check("hair colour", save_character_profile("Demo", stored), True)
        check("bsig unchanged", base_body.base_signature("Demo"), b3)
        before = counts()
        res = garments.run_garment("Demo", hid)
        check("ok", res.get("ok"), True)
        check("4 renders, 1 mesh", delta(before)[:2], (4, 1))

        # --- [7] ---------------------------------------------------------------------
        print("[7] arms on synthetic geometry")
        body = arm_body()
        long_ = garment_source.arm_numbers(sleeves(0.66), body)
        short = garment_source.arm_numbers(sleeves(0.55), body)
        hang = garment_source.arm_numbers(sleeves(0.66, hang=0.05), body)
        for side in ("left", "right"):
            check(f"{side} LONG", (round(long_[side]["reach_fore"], 4), long_[side]["off_fore"]), (0.9583, 0.0))
            check(f"{side} SHORT reach", round(short[side]["reach_fore"], 4), 0.5)
            check(f"{side} HANG", (round(hang[side]["reach_fore"], 4), hang[side]["off_fore"]), (0.9583, 0.4622))
        check("LONG vs LONG ok", garment_source.arm_gate(long_, long_)["ok"], True)
        gate = garment_source.arm_gate(short, long_)
        check("SHORT refused for reach", (gate["ok"], ["short of the source" in r for r in gate["reasons"]]),
              (False, [True, True]))
        gate = garment_source.arm_gate(hang, long_)
        check("HANG refused off the forearm", (gate["ok"], ["off the forearm" in r for r in gate["reasons"]]),
              (False, [True, True]))
        check("a sleeve the source has, gone", garment_source.arm_gate({"left": None, "right": None}, long_)["ok"],
              False)
        check("sleeveless source: nothing checked", garment_source.arm_gate(short, {"left": None, "right": None})["ok"],
              True)

        # --- [8] ---------------------------------------------------------------------
        print("[8] a refit with a short sleeve is refused -> the chain renders")
        real_source_arms, real_arm_numbers = garment_source.source_arms, garment_source.arm_numbers
        garment_source.source_arms = lambda *a, **k: long_
        garment_source.arm_numbers = lambda *a, **k: short
        try:
            b4 = use_profile_image(4)
            write_base(b4, 60)
            f4 = gs.garment_fsig("Demo", hid)
            before = counts()
            res = garments.run_garment("Demo", hid)
        finally:
            garment_source.source_arms, garment_source.arm_numbers = real_source_arms, real_arm_numbers
        check("ok, whole chain", (res.get("ok"), res.get("ran")), (True, ["haired", "ghost", "cutout", "mesh", "fit"]))
        check("4 renders, 1 mesh", delta(before)[:2], (4, 1))
        rec8 = fit_record(f4)
        check("fit F4 own", (rec8.get("accepted"), rec8.get("refitted"), (rec8.get("source") or {}).get("fsig")),
              (True, False, f4))
        marked = [p.name for p in gs.stored_groups("Demo").get((hid, f4), [])
                  if p.suffix == ".png" and gs.read_record(p.with_suffix(".json")).get("copied_from")]
        check("no copied file in F4", marked, [])

    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
