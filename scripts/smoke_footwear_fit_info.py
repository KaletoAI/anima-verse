#!/usr/bin/env python3
"""Footwear, task 12: the Wardrobe info of a fitted shoe — ``fits`` per body, ``preview_url`` and ``foot_pose``
(plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 12; ``garment_footwear.info``).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_fit_info.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no fit, no server. The fit files are SYNTHETIC: a fit GLB (the base GLB's bytes plus one tag
byte block, so its sha differs) and a JSON record with hand-picked numbers, written where
``garment_store.garment_path`` names them. ``service.get_image_service`` raises and counts into HUB.

Fixture. Demo (human, on the base-body pipeline), base model = ``foot_body_glb()`` of
``scripts/_footwear_fixtures.py`` with its sidecar (``current_base`` = (bsig, sha(base))). Item ``heels``
(feet, own mesh); its current source folder holds ``prepared.glb`` (any bytes), ``insole.json`` and a step
record with every item step accepted (insole version = ``INSOLE_VERSION``) — so a record whose
``parents.source`` names sha(prepared.glb) and that version is ``accepted`` by ``fit_state``.

The base record (fsig F, on bsig / sha(base)) carries, by hand:
    scale {k_m_per_unit 0.9, length_m 0.254, width_factor 1.08, width_cap 1.1,
           width_needed {left 1.08, right 1.13}, slim_needed {left 0.0, right 1 - 1.10 / 1.13 = 0.026549}},
    sides.left {extension.deg 28.0, toe_room_mm 40.0}, sides.right {extension.deg 22.2, toe_room_mm 18.0},
    root_lift_m 0.052, gates {ball_placement_mm {value 1.2, limit 3.0, ok True, gating True}},
    foot_pose {version 1, bones {LeftFoot {axis [0, 0, 1], deg 28.0}}, root_lift_m 0.052, contacts {left [],
    right []}, source {item_id heels, fsig F, glb_sha256 sha(fit GLB)}}.
info copies these numbers through unchanged, so the expected values ARE the hand values above: metrics
width_factor 1.08, width_needed_right 1.13, slim_needed_right 0.026549, extension_deg_left 28.0,
extension_deg_right 22.2, toe_room_mm_right 18.0, root_lift_m 0.052, k_m_per_unit 0.9, length_m 0.254.

[I1] Retexture mode: ``fits`` = exactly one row, the base: {body_id bsig, base True, status accepted} and
     the same metrics as ``steps.fit``; ``preview_url`` = "/characters/Demo/garments/heels/model?v=" +
     content_version(fit GLB); ``foot_pose`` = the record's foot_pose (source.fsig F);
     ``preview_freshness.state`` "current"; ``garments.preview_path(Demo, heels)`` = the fit GLB (the model
     route serves what the URL names). HUB 0.
[I2] Mesh mode with three stored outfit bodies (model3d/<id>.glb, ids sorted A < B < C by construction:
     ``outfit_body_id`` of three texture signatures, then sorted): A carries an accepted record of F on
     sha(A) -> status accepted, metrics width_factor 1.05 (its own hand value); B has nothing -> missing;
     C has a recorded body failure of F on sha(C) (base_fit_sha "", the current fit version, error "fit refused — x")
     -> status refused, error "fit refused — x". ``fits`` = [base, then the three in sorted id order], each
     ``base`` False. A model3d/ file that is NOT an outfit body id (the base GLB, an outfit model "o…") is no
     row.
[I3] The base record's foot_pose.source.fsig rewritten to "000000000000" -> ``foot_pose`` None, the
     ``preview_url`` stays (the GLB is still the current fsig's fit; the pose of another fit is never
     handed out). The fit GLB removed -> ``preview_url`` None, ``foot_pose`` None, ``fits[0].status``
     "missing".
[I4] The boot view (boots spec 2026-11-11 § 15; ``_insole_view`` / ``_split_view`` / ``_fit_shaft_view``).
     A SHOE: insole.json with ``shaft {class "none", slabs []}`` and a fit record with ``split {is_boot False}``
     and ``sides.left.split.collar_above_ankle_mm -21.0`` -> ``insole.shaft`` None, no ``overlay.slabs``, the
     row's ``shaft`` None, ``split.is_boot`` False, ``split.sides.left.collar_above_ankle_mm`` -21.0.
     A BOOT: frame origin (0.1, 0, 0.2), x_axis (0, 0, 1), up (0, 1, 0), z_axis = x x up = (-1, 0, 0), so a
     frame point (x, y, z) sits at mesh (0.1 - z, y, 0.2 + x); k 0.5; shaft {class "ankle", collar_h_nominal
     0.14, top_raw 0.5, closed_share 0.95, cap_removed 12, slabs [s1 {y 0.5, x 0.1..0.3, z -0.05..0.05,
     closed}, s2 {y 0.4, x 0.12..0.28, z -0.04..0.04, open}, s3 {y 0.3, ranges None, open}]} ->
     ``insole.shaft`` = {class ankle, collar_h_m 0.14, top_m 0.5 * 0.5 = 0.25, closed_share 0.95,
     cap_removed 12, slabs 3, slabs_closed 1}; ``overlay.slabs`` = two rings (s3 cuts nothing), the first
     closed with the corners (x0,z0) (x1,z0) (x1,z1) (x0,z1) (x0,z0) at mesh (0.15, 0.5, 0.3) (0.15, 0.5, 0.5)
     (0.05, 0.5, 0.5) (0.05, 0.5, 0.3) (0.15, 0.5, 0.3), the second open; the round-1 ``insole`` / ``topline``
     overlay kept. The fit record ``split {is_boot True, band_m 0.02}``, ``sides.left {split {y_m 0.09,
     topline_m 0.17, collar_above_ankle_mm 72.5}, parts {foot 2200, shaft 1148}}``, ``shaft {class ankle,
     push_p95_m 0.0093, clip_m None, …}`` -> the row's ``split`` = {is_boot True, band_m 0.02, margin_m 0.01, sides.left {y_m
     0.09, topline_m 0.17, collar_above_ankle_mm 72.5, parts {foot 2200, shaft 1148}}, right {parts {}}} (the
     hand record's right side carries neither, so only an empty parts map), ``shaft`` = the
     numbers verbatim with ``class``, ``clip_m`` absent (None is no number).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol=1e-9):
    ok = got is not None and abs(float(got) - float(want)) <= tol
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r} (want {want} +- {tol})")
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-fit-info-") as tmp:
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
        from app.core import footwear_fit as ff
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, footwear_insole, footwear_source as fs, garment_store as gs, garments
        from app.core.http_files import content_version
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        HUB = []

        def no_hub(*a, **k):
            HUB.append("image_service")
            raise RuntimeError("the info must never reach the image service")
        service.get_image_service = no_hub

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)

        heels = inventory.add_item(name="Heels", category="outfit_piece", item_id="heels",
                                   prompt_fragment="black heels",
                                   outfit_piece={"slots": ["feet"], "outfit_types": ["casual"],
                                                 "own_mesh": True})["id"]
        inventory.add_to_inventory("Demo", heels)
        ssig = fs.current_ssig(heels)
        src = fs.source_dir(heels, ssig)
        src.mkdir(parents=True, exist_ok=True)
        (src / "prepared.glb").write_bytes(b"prepared shoe")
        gs.write_record(src / "insole.json", {"version": footwear_insole.INSOLE_VERSION, "gates": {"ok": True}})
        steps = {s: {"accepted": True, "gates": {}, "backend": "", "routing": {}, "created_at": "x"}
                 for s in fs.ITEM_STEPS}
        steps["insole"]["version"] = footwear_insole.INSOLE_VERSION
        gs.write_record(src / "record.json", {"steps": steps})

        mdir = get_character_dir("Demo") / "model3d"
        mdir.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        base_glb = fx.foot_body_glb()
        (mdir / f"{bsig}.glb").write_bytes(base_glb)
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        base_sha = hashlib.sha256(base_glb).hexdigest()
        check("current base", base_body.current_base("Demo"), (bsig, base_sha))
        F = gs.garment_fsig("Demo", heels)
        source_parents = {"ssig": ssig, "empty_sha256": "", "mesh_sha256": sha(src / "prepared.glb"),
                          "insole_version": footwear_insole.INSOLE_VERSION}

        def write_fit(body_id: str, body_sha: str, *, width_factor: float, on_base: bool,
                      extra: dict = None) -> Path:
            body = "" if on_base else body_id
            path = gs.garment_path("Demo", heels, F, "fit", body=body)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base_glb + body_id.encode())
            record = {
                "method": "shoe", "kind": "footwear", "item_id": heels, "fsig": F, "ssig": ssig, "version": ff.FOOTWEAR_FIT_VERSION,
                "fit_version": ff.FOOTWEAR_FIT_VERSION, "accepted": True, "body_id": body_id, "body_sha256": body_sha,
                "base_signature": bsig, "parents": {"body_id": body_id, "body_sha256": body_sha,
                                                    "base_signature": bsig, "source": source_parents},
                "scale": {"k_m_per_unit": 0.9, "length_m": 0.254, "width_factor": width_factor, "width_cap": 1.1,
                          "width_needed": {"left": 1.08, "right": 1.13},
                          "slim_needed": {"left": 0.0, "right": 0.026549}},
                "sides": {"left": {"extension": {"deg": 28.0}, "toe_room_mm": 40.0},
                          "right": {"extension": {"deg": 22.2}, "toe_room_mm": 18.0}},
                "root_lift_m": 0.052,
                "gates": {"ball_placement_mm": {"value": 1.2, "limit": 3.0, "ok": True, "gating": True}},
                "foot_pose": {"version": 1, "bones": {"LeftFoot": {"axis": [0, 0, 1], "deg": 28.0}},
                              "root_lift_m": 0.052, "contacts": {"left": [], "right": []},
                              "source": {"item_id": heels, "fsig": F, "glb_sha256": sha(path)}},
                "fitted_at": "2026-11-10T12:00:00Z", "created_at": "2026-11-10T12:00:00Z"}
            for key, value in (extra or {}).items():
                record[key] = {**record[key], **value} if isinstance(record.get(key), dict) else value
            if on_base:
                record["base_model_sha256"] = body_sha
                record["parents"]["base_model_sha256"] = body_sha
            gs.write_record(path.with_suffix(".json"), record)
            return path

        fit_path = write_fit(bsig, base_sha, width_factor=1.08, on_base=True)

        # --- [I1] -------------------------------------------------------------------------------------------
        print("[I1] retexture mode: the base row, the preview and its foot pose")
        info = garments.garment_info("Demo", heels)
        fits = info.get("fits") or []
        check("I1 one row", [(r.get("body_id"), r.get("base"), r.get("status")) for r in fits],
              [(bsig, True, "accepted")])
        m = fits[0]["metrics"] if fits else {}
        for key, want in (("width_factor", 1.08), ("width_cap", 1.1), ("width_needed_left", 1.08),
                          ("width_needed_right", 1.13), ("slim_needed_left", 0.0), ("slim_needed_right", 0.026549),
                          ("extension_deg_left", 28.0), ("extension_deg_right", 22.2), ("toe_room_mm_left", 40.0),
                          ("toe_room_mm_right", 18.0), ("root_lift_m", 0.052), ("k_m_per_unit", 0.9),
                          ("length_m", 0.254)):
            near(f"I1 metric {key}", m.get(key), want)
        check("I1 steps.fit = row", info["steps"]["fit"]["metrics"], m)
        check("I1 gates", fits[0]["gates"], {"ball_placement_mm": {"value": 1.2, "limit": 3.0, "ok": True,
                                                                   "gating": True}})
        check("I1 preview_url", info.get("preview_url"),
              f"/characters/Demo/garments/heels/model?v={content_version(fit_path)}")
        check("I1 foot_pose source", (info.get("foot_pose") or {}).get("source"),
              {"item_id": heels, "fsig": F, "glb_sha256": sha(fit_path)})
        check("I1 foot_pose bones", (info.get("foot_pose") or {}).get("bones"),
              {"LeftFoot": {"axis": [0, 0, 1], "deg": 28.0}})
        check("I1 preview freshness", (info.get("preview_freshness") or {}).get("state"), "current")
        check("I1 model route resolves the fit", garments.preview_path("Demo", heels), fit_path)

        # --- [I2] -------------------------------------------------------------------------------------------
        print("[I2] mesh mode: one row per stored outfit body")
        profile = get_character_profile("Demo")
        profile["outfit_body_mode"] = base_body.MESH_MODE
        check("I2 mesh mode", save_character_profile("Demo", profile), True)
        ids = sorted(base_body.outfit_body_id(f"tex{c * 12}") for c in "abc")
        A, B, C = ids
        shas = {}
        for body_id in ids:
            data = base_glb + b"body " + body_id.encode()
            (mdir / f"{body_id}.glb").write_bytes(data)
            shas[body_id] = hashlib.sha256(data).hexdigest()
        (mdir / "o0123456789ab.glb").write_bytes(b"an outfit model, no body")
        write_fit(A, shas[A], width_factor=1.05, on_base=False)
        gs.record_body_failure("Demo", heels, F, C, error="fit refused — x", body_sha=shas[C], base_fit_sha="",
                               fit_version=ff.FOOTWEAR_FIT_VERSION)
        info = garments.garment_info("Demo", heels)
        rows = [(r.get("body_id"), r.get("base"), r.get("status"), r.get("error")) for r in info.get("fits") or []]
        check("I2 rows", rows, [(bsig, True, "accepted", None), (A, False, "accepted", None),
                                (B, False, "missing", None), (C, False, "refused", "fit refused — x")])
        near("I2 A width factor", (info["fits"][1]["metrics"] if len(info["fits"]) > 1 else {}).get("width_factor"),
             1.05)
        check("I2 B no metrics", info["fits"][2]["metrics"] if len(info["fits"]) > 2 else None, {})

        # --- [I3] -------------------------------------------------------------------------------------------
        print("[I3] a pose of another fit is never handed out; no fit, no preview")
        rec = gs.read_record(fit_path.with_suffix(".json"))
        rec["foot_pose"]["source"]["fsig"] = "000000000000"
        gs.write_record(fit_path.with_suffix(".json"), rec)
        info = garments.garment_info("Demo", heels)
        check("I3 foot_pose of another fsig", (info.get("foot_pose"), info.get("preview_url") is not None), (None, True))
        fit_path.unlink()
        info = garments.garment_info("Demo", heels)
        check("I3 no fit", (info.get("preview_url"), info.get("foot_pose"), info.get("preview_freshness"),
                            info["fits"][0]["status"]), (None, None, None, "missing"))

        # --- [I4] -------------------------------------------------------------------------------------------
        print("[I4] the boot view: the insole's shaft block and slab rings, the fit's split and shaft")
        profile = get_character_profile("Demo")
        profile["outfit_body_mode"] = None
        check("I4 retexture mode", save_character_profile("Demo", profile), True)
        overlay = {"insole": [[0.0, 0.01, 0.0], [0.1, 0.01, 0.0]], "topline": [[0.0, 0.05, 0.0]]}
        frame = {"origin": [0.1, 0.0, 0.2], "x_axis": [0.0, 0.0, 1.0], "up": [0.0, 1.0, 0.0],
                 "z_axis": [-1.0, 0.0, 0.0], "length": 1.0}
        gs.write_record(src / "insole.json", {
            "version": footwear_insole.INSOLE_VERSION, "gates": {"ok": True}, "nominal": {"k": 0.5},
            "overlay": overlay, "frame": frame, "shaft": {"class": "none", "slabs": [], "cap_removed": 0}})
        write_fit(bsig, base_sha, width_factor=1.08, on_base=True, extra={
            "split": {"is_boot": False, "band_m": 0.02, "margin_m": 0.01},
            "sides": {"left": {"extension": {"deg": 28.0}, "toe_room_mm": 40.0,
                               "split": {"is_boot": False, "y_m": 0.06, "collar_above_ankle_mm": -21.0},
                               "parts": {"foot": 2000}}}})
        info = garments.garment_info("Demo", heels)
        row = info["fits"][0]
        check("I4 shoe status", row["status"], "accepted")
        check("I4 shoe insole shaft", info["insole"]["shaft"], None)
        check("I4 shoe no slab rings", "slabs" in (info["insole"]["overlay"] or {}), False)
        check("I4 shoe fit shaft", row.get("shaft"), None)
        check("I4 shoe split", row.get("split"), {"is_boot": False, "band_m": 0.02, "margin_m": 0.01, "sides": {
            "left": {"y_m": 0.06, "collar_above_ankle_mm": -21.0, "parts": {"foot": 2000}},
            "right": {"parts": {}}}})

        gs.write_record(src / "insole.json", {
            "version": footwear_insole.INSOLE_VERSION, "gates": {"ok": True}, "nominal": {"k": 0.5},
            "overlay": overlay, "frame": frame,
            "shaft": {"class": "ankle", "collar_h_nominal": 0.14, "collar_h_raw": 0.28, "top_raw": 0.5,
                      "vamp_top_raw": 0.2, "closed_share": 0.95, "cap_removed": 12, "slabs": [
                          {"y": 0.5, "x_min": 0.1, "x_max": 0.3, "z_min": -0.05, "z_max": 0.05, "closed": True},
                          {"y": 0.4, "x_min": 0.12, "x_max": 0.28, "z_min": -0.04, "z_max": 0.04, "closed": False},
                          {"y": 0.3, "x_min": None, "x_max": None, "z_min": None, "z_max": None,
                           "closed": False}]}})
        shaft_rec = {"class": "ankle", "cap_removed": 12, "closed_share": 0.95, "top_m": 0.17, "clip_m": None,
                     "knee_margin_m": None, "push_p95_m": 0.0093, "push_max_m": 0.0108, "inside_share": 0.0,
                     "seam_gap_p95_mm": 0.0, "seam_stretch_max": 13.0, "leg_follow_deg": 0.0}
        write_fit(bsig, base_sha, width_factor=1.08, on_base=True, extra={
            "split": {"is_boot": True, "band_m": 0.02, "margin_m": 0.01},
            "sides": {"left": {"extension": {"deg": 28.0}, "toe_room_mm": 40.0,
                               "split": {"is_boot": True, "y_m": 0.09, "band_m": 0.02, "margin_m": 0.01,
                                         "topline_m": 0.17, "collar_above_ankle_mm": 72.5},
                               "parts": {"foot": 2200, "shaft": 1148}, "shaft": {"push_p95_m": 0.0093}}},
            "shaft": shaft_rec})
        info = garments.garment_info("Demo", heels)
        row = info["fits"][0]
        check("I4 boot insole shaft", info["insole"]["shaft"], {
            "class": "ankle", "collar_h_m": 0.14, "top_m": 0.25, "closed_share": 0.95, "cap_removed": 12,
            "slabs": 3, "slabs_closed": 1})
        rings = (info["insole"]["overlay"] or {}).get("slabs") or []
        check("I4 boot rings", [r["closed"] for r in rings], [True, False])
        check("I4 boot ring 1", rings[0]["points"] if rings else None,
              [[0.15, 0.5, 0.3], [0.15, 0.5, 0.5], [0.05, 0.5, 0.5], [0.05, 0.5, 0.3], [0.15, 0.5, 0.3]])
        check("I4 boot round-1 overlay kept", {k: info["insole"]["overlay"].get(k) for k in ("insole", "topline")},
              overlay)
        check("I4 boot split", row.get("split"), {"is_boot": True, "band_m": 0.02, "margin_m": 0.01, "sides": {
            "left": {"y_m": 0.09, "topline_m": 0.17, "collar_above_ankle_mm": 72.5,
                     "parts": {"foot": 2200, "shaft": 1148}},
            "right": {"parts": {}}}})
        check("I4 boot fit shaft", row.get("shaft"),
              {"class": "ankle", **{k: v for k, v in shaft_rec.items() if k != "class" and v is not None}})
        check("HUB", HUB, [])
    print("PASS" if not FAILS else f"FAIL: {len(FAILS)} — {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
