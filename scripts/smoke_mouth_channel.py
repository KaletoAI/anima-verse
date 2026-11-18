#!/usr/bin/env python3
"""Smoke: the core mouth channel — its extension group, its channel declaration and its place in the extension
step (app/core/mouth_channel.py, collision_channels.py, model3d._auto_extension_rig; Ruling A203).

Usage:
    ./.venv/bin/python scripts/smoke_mouth_channel.py

No server, no Blender (the Blender run is mocked), a temp storage dir, no package loaded.

Before A203 (commit 0eded5388) ``app/core/mouth_channel.py`` did not exist and ``rig_groups_for`` of a character
without packages was empty; [0] proves that against that commit.

FIXTURE: the synthetic body of ``smoke_collision_capsules.make_body`` (Head joint (0, 1.6, 0), body frame side +x,
up +y, front +z).

[1] The group: every character gets ``{id "mouth_channel", op "mouth_part", chains [], params {}}``; with the
    stored override mouth = {offset_mm [1, 2, 3], radius_scale 1.5, depth_scale 0.5, cone_deg 40, tilt_deg 10} its
    params are {"override": the same without cone_deg} (the cone has no geometry). The extension fingerprint
    differs between the two (a saved override makes the extension step due) and changes with the op's build.
[2] wanted_channels on a humanoid model (rig "mixamo") lists the channel ``mouth`` first — bone Head, built True,
    from_rig mouth_channel, accepts attached_part + appendage_chain, depth 0.08, radius 0.02, cone 35, funnel
    0.03, min_length 0, compress_min 0.6, not exposed_only. Another rig, or no model path: not listed.
[3] resolve_channels with the build's opening {centre (0, 1.55, 0.1), axis (0, -0.6, -0.8), depth 0.06, radius
    0.03, open_height 0.0365, override {offset_mm [1, 2, 3], radius_scale 1.5, depth_scale 0.75, tilt_deg 10}} and the stored
    override of [1]: the record is the BUILT geometry — a_pos = the centre, b_pos = centre + axis x 0.06 =
    (0, 1.55 - 0.036, 0.1 - 0.048) = (0, 1.514, 0.052), r 0.03 (nothing applied on top: the stored depth scale 0.5
    and radius scale 1.5 would give 0.04 / 0.03 from the declaration and move the centre) — placement "rig",
    ``applied`` = the override the build used with the stored cone 40 (so the panel's preview starts from what
    is built), cone_deg 40, suppress contains the head capsule; the build's ``open_height`` 0.0365 (the opening's
    height with the shape key ``mouth_open`` at 1, part 2) is carried as it is.
    Without an opening (rig not built): no channel, skipped with "Rig mouth_channel is not built on this model".
[4] The extension step runs the mouth in its own isolated run, after the parts and before the extension bones:
    groups [capture, mouth, inset, attached] -> calls attached_part, inset_part, mouth_part, extension_bones;
    a failing mouth run restores the bytes before it (the model still gets the other groups: bytes A I C).
"""
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEFORE = "0eded5388"
failed = 0


def check(label, ok, got=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got})"))
    failed += 0 if ok else 1


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_mouth_channel_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    paths.init_instance(tmp / "instance")
    import importlib.util
    from app.core import collision, collision_channels, extension_rig, model3d, mouth_channel
    from app.blender import refine
    from app.plugins.loader import discover_packages
    (tmp / "plugins").mkdir()
    discover_packages(tmp / "plugins", force=True)

    print("[0] before A203")
    gone = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{BEFORE}:app/core/mouth_channel.py"],
                          capture_output=True)
    known = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{BEFORE}^{{commit}}"], capture_output=True)
    if known.returncode == 0:
        check(f"{BEFORE} has no mouth_channel.py", gone.returncode != 0)
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE}:app/core/extension_rig.py"],
                             capture_output=True, text=True).stdout
        check(f"{BEFORE}: rig_groups_for names no core group", "mouth_channel" not in old)
    else:
        print(f"SKIP {BEFORE} is not in this clone")

    print("[1] the group")
    stored = {"offset_mm": [1, 2, 3], "radius_scale": 1.5, "depth_scale": 0.5, "cone_deg": 40, "tilt_deg": 10}
    profile = {"model3d_opts": {"collision_channels": {"mouth": stored}}}
    plain = mouth_channel.group({})
    check("id, op, no chains, no params", (plain["id"], plain["op"], plain["chains"], plain["params"])
          == ("mouth_channel", "mouth_part", [], {}), plain)
    tuned = mouth_channel.group(profile)
    check("override without the cone", tuned["params"] == {"override": {
        "offset_mm": [1.0, 2.0, 3.0], "radius_scale": 1.5, "depth_scale": 0.5, "tilt_deg": 10.0}}, tuned["params"])
    groups = extension_rig.rig_groups_for("demo", profile={})
    check("rig_groups_for carries it for a character without packages", [g["id"] for g in groups] == ["mouth_channel"],
          [g["id"] for g in groups])
    a = extension_rig.extension_rig_fingerprint([plain])
    b = extension_rig.extension_rig_fingerprint([tuned])
    check("the override changes the fingerprint", a != b)
    with patch.dict(extension_rig.OP_BUILDS, {"mouth_part": extension_rig.OP_BUILDS["mouth_part"] + 1}):
        check("the build number changes the fingerprint", extension_rig.extension_rig_fingerprint([plain]) != a)
    check("no motion group", extension_rig.motion_payload("demo", profile={})["groups"] == {})

    print("[2] the declaration")
    opening = {"centre": [0, 1.55, 0.1], "axis": [0, -0.6, -0.8], "depth": 0.06, "radius": 0.03, "open_height": 0.0365,
               "override": {"offset_mm": [1, 2, 3], "radius_scale": 1.5, "depth_scale": 0.75, "tilt_deg": 10}}
    state = {"status": "applied", "groups": ["mouth_channel"], "metrics": {"mouth_channel": {"opening": opening}}}
    path = tmp / "model.glb"
    wanted, _sig = collision_channels.wanted_channels("demo", path, {"rig": "mixamo", "extension_rig": state},
                                                      profile=profile)
    first = wanted[0] if wanted else {}
    check("mouth listed first", first.get("id") == "mouth", [w["id"] for w in wanted])
    check("declared values", (first.get("bone"), first.get("built"), first.get("from_rig"), first.get("accepts"),
                              first.get("depth"), first.get("radius"), first.get("cone_deg"), first.get("funnel"),
                              first.get("min_length"), first.get("compress_min"), first.get("exposed_only"))
          == ("Head", True, "mouth_channel", ["attached_part", "appendage_chain"], 0.08, 0.02, 35.0, 0.03, 0.0, 0.6,
              False), first)
    other, _ = collision_channels.wanted_channels("demo", path, {"rig": "generic"}, profile=profile)
    check("another rig: not listed", other == [], other)
    none, _ = collision_channels.wanted_channels("demo", None, {}, profile=profile)
    check("no model: not listed", none == [], none)

    print("[3] the record")
    spec = importlib.util.spec_from_file_location("fixture", ROOT / "scripts/smoke_collision_capsules.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    body = fixture.make_body()
    fit = collision.fit_capsules(body)
    channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted, exposed=lambda e: True)
    rec = channels[0] if channels else {}
    check("nothing skipped", skipped == [], skipped)
    check("a_pos = the built centre", np.allclose(rec.get("a_pos", [9, 9, 9]), [0, 1.55, 0.1], atol=1e-4), rec.get("a_pos"))
    check("b_pos = centre + axis x built depth", np.allclose(rec.get("b_pos", [9, 9, 9]), [0, 1.514, 0.052], atol=1e-4),
          rec.get("b_pos"))
    check("r = the built radius", rec.get("r") == 0.03, rec.get("r"))
    check("placement rig, joint Head", (rec.get("placement"), rec.get("a")) == ("rig", "mixamorig:Head"), rec)
    check("applied = the build's override, the stored cone", rec.get("applied") == {
        "offset_mm": [1, 2, 3], "radius_scale": 1.5, "depth_scale": 0.75, "cone_deg": 40.0, "tilt_deg": 10.0},
        rec.get("applied"))
    check("open_height carried for the renderers", rec.get("open_height") == 0.0365, rec.get("open_height"))
    check("cone 40, head capsule suppressed", rec.get("cone_deg") == 40.0 and "head" in rec.get("suppress", []), rec)
    bare, _ = collision_channels.wanted_channels("demo", path, {"rig": "mixamo"}, profile={})
    channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], bare, exposed=lambda e: True)
    check("no opening: no channel, the reason listed", channels == [] and skipped == [
        {"id": "mouth", "reason": "Rig mouth_channel is not built on this model"}], (channels, skipped))
    info = collision_channels.declarations_info("demo", path, {"rig": "mixamo", "extension_rig": state,
                                                               "collision": {"channels": [rec]}}, profile=profile)
    check("the panel's row: built, placed", info and info[0]["built"] is True and info[0]["placement"] == "rig", info)

    print("[4] the extension step")
    from app.core.rig_contract import BASE_JOINT_NAMES
    from scripts.smoke_extension_rig_p0 import glb
    clean = glb(["mixamorig:" + name for name in BASE_JOINT_NAMES])
    source = tmp / "step/prerig/model.glb"
    source.parent.mkdir(parents=True)
    target = tmp / "step/model.glb"

    def group(name, op):
        return dict(id=name, op=op, params={}, chains=[], enabled=True)
    declared = [group("capture", "fixture"), group("mouth_channel", "mouth_part"), group("inset", "inset_part"),
                group("part", "attached_part")]
    letters = {"attached_part": b"A", "inset_part": b"I", "mouth_part": b"M", "extension_bones": b"C"}
    for failing, expected in ((None, b"AIMC"), ("mouth_part", b"AIC")):
        calls = []
        source.write_bytes(clean)
        target.write_bytes(b"stale")

        def run(staged, operation, params, **kwargs):
            calls.append(operation)
            if operation == failing:
                staged.write_bytes(b"garbage")
                raise RuntimeError("fixture failure")
            staged.write_bytes(staged.read_bytes() + letters[operation])
            return {"applied": True, "data": {"metrics": {}}}
        with ExitStack() as stack:
            stack.enter_context(patch("app.models.character.get_character_profile", return_value={}))
            stack.enter_context(patch.object(extension_rig, "rig_groups_for", return_value=declared))
            stack.enter_context(patch.object(extension_rig, "resolved_extension_groups", return_value=declared))
            stack.enter_context(patch.object(model3d, "_auto_normalize"))
            stack.enter_context(patch.object(model3d, "_validator_for",
                                             return_value=lambda blob: {"ok": blob.startswith(clean), "errors": []}))
            stack.enter_context(patch.object(refine, "apply_script", side_effect=run))
            meta = {"rig": "mixamo"}
            result = model3d._auto_extension_rig("fixture", target, meta)
        label = "a failing mouth run" if failing else "all runs"
        check(f"{label}: order attached, inset, mouth, bones",
              calls == ["attached_part", "inset_part", "mouth_part", "extension_bones"], calls)
        check(f"{label}: bytes {expected.decode()}", target.read_bytes() == clean + expected,
              target.read_bytes()[len(clean):])
        status = meta["extension_rig"]["metrics"]["mouth_channel"]["status"]
        check(f"{label}: mouth status", status == ("failed" if failing else "applied") and result["ok"], status)

    print("FAILED (%d)" % failed if failed else "ALL OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
