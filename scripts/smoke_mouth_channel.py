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

[1] The group: every character gets ``{id "mouth_channel", op "mouth_part", chains [[Jaw under Head]], params
    {}}`` — the jaw is an extension bone: ``extension_bone_names`` names it, so the model validator accepts a model
    carrying it (53 joints) and refuses it without that context; no motion group drives it; with the
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
    height with the shape key ``mouth_open`` at 1, part 2) and ``teeth_gap`` 0.0251 (Ruling A206) are carried as
    they are.
    Without an opening (rig not built): no channel, skipped with "Rig mouth_channel is not built on this model".
[4] The extension step runs the mouth in its own isolated run, after the parts and before the extension bones:
    groups [capture, mouth, inset, attached] -> calls attached_part, inset_part, mouth_part, extension_bones;
    a failing mouth run restores the bytes before it (the model still gets the other groups: bytes A I C).
[5] A model WITHOUT package groups (review of A203: the mouth group must not drag it through the clean-source and
    normalising machinery). Fixture: model bytes X, no ``prerig/``; ``_auto_normalize`` raises when called.
    a. Blender off (``refine.unavailable_reason`` = "blender refinement is disabled"): ok, nothing applied, status
       none_applicable with reason "Mouth channel not built: blender refinement is disabled", the group's metric
       "unavailable"; bytes X, no prerig copy, no Blender call; the same call again is a no-op.
    b. Blender on, the mouth builds (the mock appends M): model X M, ``prerig/`` holds X exactly (not normalised),
       status applied, has_applied False. With a saved override (another fingerprint) the rebuild starts from the
       prerig copy: X M again, never X M M.
    c. No lip line (the script's answer: no output, data status not_found, reason "no lip line (contrast 0.010)"):
       bytes X, no prerig copy, status none_applicable, metric not_found with that reason; again = no-op.
    d. A script error ("timeout"): metric failed, status none_applicable; not forced = no-op (1 run), forced = a
       second run (the failed group makes the forced rebuild run).
    e. A model with a hair joint beside the 52 and no prerig: built like b (no "Clean prerig source is missing").
    f. The mouth group switched off after b: the model is X again.
[6] Extension bones that fail beside a mouth that builds (groups capture + mouth): the body is published with the
    mouth (X M) but the step is NOT "applied": status failed, ok False, the capture group failed; the same call
    again runs again (2 bone runs). Bones that find nothing (data status not_found): X M, status not_found, ok
    True; forced, it runs again.
[7] ``_extension_groups_for`` drops the mouth group for a model of another rig ("generic"); the group's light on a
    humanoid: metric not_found -> grey "Not built" with "No lip line was found on this face, so the mouth stays
    closed."; unavailable -> grey with the Blender sentence; failed -> red "Failed".
[9] A non-humanoid character (``model_refs.is_humanoid`` False; user decision 2026-11-18) has NO mouth: no group in
    ``rig_groups_for`` (so the fingerprint is the one of an empty list), no jaw in the validation context, no
    channel declaration, no light.
[8] The channel's reason carries the metric's: metric {status not_found, reason "no lip line"} -> skipped "Rig
    mouth_channel is not built on this model: no lip line". A step whose status is not_found (bones) with the
    mouth's own metric applied still places the channel.
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
    from app.core import db
    db.init_schema()
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
    check("id, op, the jaw chain, no params", (plain["id"], plain["op"], plain["chains"], plain["params"])
          == ("mouth_channel", "mouth_part", [[{"bone": "mixamorig:Jaw", "parent": "Head"}]], {}), plain)
    names = extension_rig.extension_bone_names("demo", profile={})
    check("the validator's context names the jaw", names == {
        "mixamorig:Jaw": {"parent": "Head", "group": "mouth_channel"}}, names)
    from app.core.model_validate import validate_glb
    from app.core.rig_contract import BASE_JOINT_NAMES
    from scripts.smoke_extension_rig_p0 import glb as fixture_glb
    base_names = ["mixamorig:" + name for name in BASE_JOINT_NAMES]
    with_jaw = fixture_glb(base_names + ["mixamorig:Jaw"], extra_parents={"mixamorig:Jaw": "mixamorig:Head"})
    check("a model with the jaw: refused without the context, accepted with it",
          (validate_glb(with_jaw)["ok"], validate_glb(with_jaw, extension_names=names)["ok"]) == (False, True),
          (validate_glb(with_jaw), validate_glb(with_jaw, extension_names=names)))
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
               "teeth_gap": 0.0251, "override": {"offset_mm": [1, 2, 3], "radius_scale": 1.5, "depth_scale": 0.75, "tilt_deg": 10}}
    state = {"status": "applied", "groups": ["mouth_channel"],
             "metrics": {"mouth_channel": {"status": "applied", "opening": opening}}}
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
    check("teeth_gap carried for the renderers (A206)", rec.get("teeth_gap") == 0.0251, rec.get("teeth_gap"))
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

    print("[5] a model without package groups")
    mouth = {**mouth_channel.group({}), "enabled": True}
    X = clean

    def scene(name, model_bytes=X):
        folder = tmp / name
        folder.mkdir()
        (folder / "model.glb").write_bytes(model_bytes)
        return folder / "model.glb"

    def step(model, meta, *, run, force=False, groups=None, blocked="", profile_groups=None):
        calls = []

        def apply(staged, operation, params, **kwargs):
            calls.append(operation)
            return run(staged, operation, params)
        declared = groups if groups is not None else [mouth]
        with ExitStack() as stack:
            stack.enter_context(patch("app.models.character.get_character_profile", return_value={}))
            stack.enter_context(patch.object(extension_rig, "rig_groups_for", return_value=profile_groups or declared))
            stack.enter_context(patch.object(extension_rig, "resolved_extension_groups", return_value=declared))
            stack.enter_context(patch.object(model3d, "_auto_normalize", side_effect=AssertionError("normalised")))
            stack.enter_context(patch.object(model3d, "_validator_for",
                                             return_value=lambda blob: {"ok": True, "errors": []}))
            stack.enter_context(patch.object(refine, "unavailable_reason", return_value=blocked))
            stack.enter_context(patch.object(refine, "apply_script", side_effect=apply))
            result = model3d._extension_rig_once("fixture", model, meta, force=force)
        return result, calls

    def builds(staged, operation, params):
        staged.write_bytes(staged.read_bytes() + b"M")
        return {"applied": True, "data": {"metrics": {"mouth_channel": {"opening": opening}}}}

    def no_line(staged, operation, params):
        found = {"status": "not_found", "reason": "no lip line (contrast 0.010)"}
        return {"ok": True, "applied": False, "error": "nothing to do",
                "data": {**found, "metrics": {"mouth_channel": dict(found)}}}

    def crashes(staged, operation, params):
        raise RuntimeError("timeout")

    model = scene("a")
    meta = {"rig": "mixamo"}
    result, calls = step(model, meta, run=builds, blocked="blender refinement is disabled")
    st = meta["extension_rig"]
    check("a: Blender off -> none_applicable with the reason, nothing run",
          (result["ok"], result["applied"], st["status"], st["reason"], calls,
           st["metrics"]["mouth_channel"]["status"]) ==
          (True, False, "none_applicable", "Mouth channel not built: blender refinement is disabled", [],
           "unavailable"), (result, st))
    check("a: bytes untouched, no prerig copy", model.read_bytes() == X and not (model.parent / "prerig").exists())
    again, calls = step(model, meta, run=builds, blocked="blender refinement is disabled")
    check("a: the same call again is a no-op", again.get("noop") is True and calls == [], again)

    model = scene("b")
    meta = {"rig": "mixamo"}
    result, calls = step(model, meta, run=builds)
    st = meta["extension_rig"]
    check("b: built -> X M, status applied, has_applied False",
          (model.read_bytes(), st["status"], st["has_applied"], result["applied"], calls) ==
          (X + b"M", "applied", False, True, ["mouth_part"]), (st, calls))
    check("b: the prerig copy is X as it was", (model.parent / "prerig/model.glb").read_bytes() == X)
    tuned_group = {**mouth, "params": {"override": {"offset_mm": [0, 1, 0]}}}
    result, calls = step(model, meta, run=builds, groups=[tuned_group])
    check("b: a rebuild starts from the prerig copy (X M, not X M M)",
          model.read_bytes() == X + b"M" and calls == ["mouth_part"], model.read_bytes()[len(X):])
    meta_b = meta

    model = scene("c")
    meta = {"rig": "mixamo"}
    result, calls = step(model, meta, run=no_line)
    st = meta["extension_rig"]
    check("c: no lip line -> not_found on the group, none_applicable on the step",
          (result["ok"], st["status"], st["metrics"]["mouth_channel"], model.read_bytes() == X,
           (model.parent / "prerig").exists()) ==
          (True, "none_applicable", {"status": "not_found", "reason": "no lip line (contrast 0.010)"}, True, False),
          st)
    again, calls = step(model, meta, run=no_line)
    check("c: again = no-op", again.get("noop") is True and calls == [])

    model = scene("d")
    meta = {"rig": "mixamo"}
    result, calls = step(model, meta, run=crashes)
    st = meta["extension_rig"]
    check("d: a script error -> failed on the group", (st["metrics"]["mouth_channel"], st["status"]) ==
          ({"status": "failed", "reason": "timeout"}, "none_applicable"), st)
    _again, calls_plain = step(model, meta, run=crashes)
    _forced, calls_forced = step(model, meta, run=crashes, force=True)
    check("d: not forced = no-op, forced = it runs again", (calls_plain, calls_forced) == ([], ["mouth_part"]),
          (calls_plain, calls_forced))

    hairy = glb(["mixamorig:" + name for name in BASE_JOINT_NAMES] + ["HairA"], extra_parents={"HairA": "mixamorig:Head"})
    model = scene("e", hairy)
    meta = {"rig": "mixamo"}
    result, calls = step(model, meta, run=builds)
    check("e: a hair joint and no prerig: built, no missing-source failure",
          (result["ok"], meta["extension_rig"]["status"], model.read_bytes()) == (True, "applied", hairy + b"M"),
          meta["extension_rig"])

    model = tmp / "b" / "model.glb"
    off = {**mouth, "enabled": False}
    result, calls = step(model, meta_b, run=builds, groups=[off])
    check("f: switched off -> the model is X again", model.read_bytes() == X and calls == [], model.read_bytes()[len(X):])

    print("[6] failing extension bones beside a built mouth")
    capture = dict(id="capture", op="fixture", params={}, chains=[], enabled=True)

    def bones(status):
        def run(staged, operation, params):
            if operation == "mouth_part":
                return builds(staged, operation, params)
            return {"ok": True, "applied": False, "error": "boom" if status == "failed" else "nothing to do",
                    "data": {"status": status, "reason": "boom" if status == "failed" else "no shape"}}
        return run

    def heavy(name):
        folder = tmp / name
        (folder / "prerig").mkdir(parents=True)
        (folder / "prerig/model.glb").write_bytes(X)
        (folder / "model.glb").write_bytes(X)
        return folder / "model.glb"

    def heavy_step(model, meta, run, force=False):
        calls = []

        def apply(staged, operation, params, **kwargs):
            calls.append(operation)
            return run(staged, operation, params)
        declared = [capture, mouth]
        with ExitStack() as stack:
            stack.enter_context(patch("app.models.character.get_character_profile", return_value={}))
            stack.enter_context(patch.object(extension_rig, "rig_groups_for", return_value=declared))
            stack.enter_context(patch.object(extension_rig, "resolved_extension_groups", return_value=declared))
            stack.enter_context(patch.object(model3d, "_auto_normalize"))
            stack.enter_context(patch.object(model3d, "_validator_for",
                                             return_value=lambda blob: {"ok": blob.startswith(X), "errors": []}))
            stack.enter_context(patch.object(refine, "unavailable_reason", return_value=""))
            stack.enter_context(patch.object(refine, "apply_script", side_effect=apply))
            result = model3d._extension_rig_once("fixture", model, meta, force=force)
        return result, calls

    model = heavy("g")
    meta = {"rig": "mixamo"}
    result, calls = heavy_step(model, meta, bones("failed"))
    st = meta["extension_rig"]
    check("failed bones: the mouth is published (X M)", model.read_bytes() == X + b"M" and result["applied"],
          model.read_bytes()[len(X):])
    check("failed bones: the step is failed, not applied",
          (st["status"], result["ok"], st["metrics"]["capture"]["status"], st["metrics"]["mouth_channel"]["status"])
          == ("failed", False, "failed", "applied"), st)
    _again, calls = heavy_step(model, meta, bones("failed"))
    check("failed bones: the next call tries again", calls == ["mouth_part", "extension_bones"], calls)

    model = heavy("h")
    meta = {"rig": "mixamo"}
    result, calls = heavy_step(model, meta, bones("not_found"))
    st = meta["extension_rig"]
    check("bones found nothing: X M, status not_found, ok",
          (model.read_bytes(), st["status"], result["ok"]) == (X + b"M", "not_found", True), st)
    again, calls_plain = heavy_step(model, meta, bones("not_found"))
    _forced, calls_forced = heavy_step(model, meta, bones("not_found"), force=True)
    check("bones found nothing: not forced = no-op, forced = runs again",
          (again.get("noop"), calls_plain, calls_forced) == (True, [], ["mouth_part", "extension_bones"]),
          (calls_plain, calls_forced))

    print("[7] other rigs and the group's light")
    check("another rig: the mouth group is not listed",
          [g["id"] for g in model3d._extension_groups_for({"rig": "generic"}, [capture, mouth])] == ["capture"])
    check("a humanoid lists it", [g["id"] for g in model3d._extension_groups_for({"rig": "mixamo"}, [capture, mouth])]
          == ["capture", "mouth_channel"])

    def light_of(metric):
        record = {"attempted": True, "status": "none_applicable", "group_ops": {"mouth_channel": "mouth_part"},
                  "metrics": {"mouth_channel": metric}}
        return model3d.extension_group_lights({}, {"rig": "mixamo"}, [mouth], record, "")["mouth_channel"]
    got = light_of({"status": "not_found", "reason": "no lip line (contrast 0.010)"})
    check("no lip line: grey, not built, the plain sentence", (got["light"], got["state"], got["reason"]) ==
          ("grey", "Not built", "No lip line was found on this face, so the mouth stays closed."), got)
    got = light_of({"status": "unavailable", "reason": "x"})
    check("no Blender: grey", (got["light"], got["reason"]) ==
          ("grey", "Blender is not available here, so the mouth was not built."), got)
    got = light_of({"status": "failed", "reason": "timeout"})
    check("a failed run: red", (got["light"], got["state"]) == ("red", "Failed"), got)

    print("[9] a non-humanoid has no mouth at all")
    with patch("app.core.model_refs.is_humanoid", return_value=False):
        check("no group", extension_rig.rig_groups_for("fox", profile={}) == [])
        check("the fingerprint is the one of no groups", extension_rig.extension_rig_fingerprint(
            extension_rig.rig_groups_for("fox", profile={})) == extension_rig.extension_rig_fingerprint([]))
        check("no jaw in the validation context", extension_rig.extension_bone_names("fox", profile={}) == {})
        check("no placeholder group", extension_rig.extension_metadata("fox", {})["groups"] == [])
        none, _ = collision_channels.wanted_channels("fox", path, {"rig": "mixamo", "extension_rig": state}, profile={})
        check("no channel declaration, even on a humanoid rig file", none == [], none)
        lights = model3d.extension_group_lights({}, {"rig": "generic"}, model3d._extension_groups_for(
            {"rig": "generic"}, extension_rig.rig_groups_for("fox", profile={})), {}, "")
        check("no light", lights == {}, lights)

    print("[8] the channel's reason")
    state_none = {"status": "none_applicable", "groups": ["mouth_channel"],
                  "metrics": {"mouth_channel": {"status": "not_found", "reason": "no lip line"}}}
    wanted_none, _ = collision_channels.wanted_channels("demo", path, {"rig": "mixamo", "extension_rig": state_none},
                                                        profile={})
    _channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted_none, exposed=lambda e: True)
    check("the metric's reason is passed on", skipped == [
        {"id": "mouth", "reason": "Rig mouth_channel is not built on this model: no lip line"}], skipped)
    state_mixed = {**state, "status": "not_found"}
    wanted_mixed, _ = collision_channels.wanted_channels("demo", path, {"rig": "mixamo", "extension_rig": state_mixed},
                                                         profile={})
    channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted_mixed, exposed=lambda e: True)
    check("bones not found, mouth built: the channel is placed", [c["id"] for c in channels] == ["mouth"] and not skipped,
          (channels, skipped))

    print("FAILED (%d)" % failed if failed else "ALL OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
