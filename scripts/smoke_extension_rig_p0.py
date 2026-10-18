"""Check P0 in isolated storage.

Usage: .venv/bin/python scripts/smoke_extension_rig_p0.py

P0 requires 52 base joints. A two-link group allows 54 or 52, never 53.
Spec defaults: f=2.2, zeta=.15, gravity=.35, m=1, gain=1, max_deg=25,
squash=[.6,1.4], rest=0, rest_max=90, flatten=spill=0. The static limit
inherits declared max_deg: omitted sag_max_deg with max_deg=42 yields 42.
Changing flatten to .5 or sag_max_deg to 40 changes effective motion/rev,
while mesh identity hashes only operation geometry and stays unchanged.
Equal motion content gives equal motion rev; package deletion restores strict validation.
An extension parent must be a skin joint, not just a same-named scene node.
Slot and rig conditions are both AND filters without rig.templates; an explicit
rig selector replaces package/slot applicability without activating prompt content. A tier's creation/deletion or
same-size atomic replacement changes model_rev; polls never read mesh bytes.
"""
import copy
import json
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def check(condition, label):
    assert condition, label
    print("PASS", label)


def glb(names, extra_parents=None, second_skin=None, outside_parent=False, mutate=None):
    """Small container with named skin joints and an embedded PNG header."""
    nodes = [{"name": name} for name in names]
    for bone, parent in (extra_parents or {}).items():
        nodes[names.index(parent)].setdefault("children", []).append(names.index(bone))
    if outside_parent:
        nodes[0].pop("children", None)
        nodes.append({"name": names[0], "children": [len(names) - 2]})
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 8, 8)
    skins = [{"joints": list(range(len(names)))}]
    if second_skin is not None:
        skins.append({"joints": second_skin})
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "skins": skins,
           "buffers": [{"byteLength": len(png)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
           "images": [{"bufferView": 0, "mimeType": "image/png"}],
           "meshes": [{"primitives": []}]}
    if mutate:
        mutate(doc)
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    binary = png + b"\0" * (-len(png) % 4)
    chunks = struct.pack("<II", len(body), 0x4E4F534A) + body
    chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def run_async(coroutine):
    """Keep executor completions observable in restricted smoke environments.

    Some runners do not wake a blocked selector on a worker's self-pipe write;
    a bounded selector wait also services completions without changing the app.
    """
    import asyncio
    import selectors
    class SmokeSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.05 if timeout is None else min(timeout, .05))
    with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(SmokeSelector())) as runner:
        return runner.run(coroutine)


def main():
    with tempfile.TemporaryDirectory(prefix="extension-p0-") as tmp:
        root = Path(tmp)
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({
            "packages": {"enabled": "example_a,example_bad,example_b"},
        }))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import db
        db.init_schema()
        from app.core.extension_rig import (extension_bone_names, extension_metadata,
                                           motion_payload, rig_groups_for)
        from app.core.model_validate import validate_glb
        from app.core.rig_contract import BASE_JOINT_NAMES
        from app.plugins import registry
        from app.plugins.loader import discover_packages
        from app.plugins.registry import RigSpec
        from app.core import model3d, world_ops
        from app.models.character import get_character_dir, save_character_profile
        import yaml

        base = ["mixamorig:" + name for name in BASE_JOINT_NAMES]
        check(len(base) == 52, "52 canonical base joints")
        rig = {"id": "example_group", "op": "example_operation",
               "chains": [[{"bone": "ExampleBone1", "parent": base[0]},
                           {"bone": "ExampleBone2", "parent": "ExampleBone1"}]],
               "params": {"opaque": {"value": [1, 2]}},
               "applies_to": {"example_profile": ["enabled"],
                              "attributes.example_attribute": ["enabled"]}}
        manifest = {"name": "Example package", "apply_to": "*", "body_slots": [
            {"id": "example_slot", "attributes": {"example_attribute": {"type": "str"}},
             "prompt": {"always": "example fixture marker"}, "covered_by": ["example_cover"],
             "rigs": [rig]}]}
        plugins = root / "plugins"
        package = plugins / "example_a"
        package.mkdir(parents=True)
        (package / "plugin.yaml").write_text(yaml.safe_dump(manifest))
        discover_packages(plugins, force=True)
        profile = {"template": "demo", "example_profile": "enabled",
                   "body_slots": {"example_slot": {"example_attribute": "enabled"}}}
        context = extension_bone_names("demo", profile)
        extended = base + ["ExampleBone1", "ExampleBone2"]
        parents = {"ExampleBone1": base[0], "ExampleBone2": "ExampleBone1"}
        data = glb(extended, parents)
        for label, contents in (("valid base", glb(base)), ("valid extended", data),
                                ("normalized base", glb([n.replace("mixamorig:", "").upper() for n in base]))):
            verdict = validate_glb(contents, extension_names=context)
            check(verdict["ok"] and verdict["rig"] == "mixamo", label)
        cases = {
            "foreign 52-joint rig": glb(["ForeignBone" + str(i) for i in range(52)]),
            "missing base": glb(base[1:]),
            "duplicate": glb(base + [base[0]]),
            "foreign": glb(base + ["ForeignBone"]),
            "partial group": glb(base + ["ExampleBone1"], {"ExampleBone1": base[0]}),
            "wrong parent": glb(extended, {**parents, "ExampleBone2": base[0]}),
            "parent outside skin": glb(extended, parents, outside_parent=True),
            "secondary duplicate skin": glb(base, second_skin=[0, 0]),
        }
        for label, mutate in (
                ("null secondary skin", lambda d: d["skins"].append(None)),
                ("non-list secondary joints", lambda d: d["skins"].append({"joints": 3})),
                ("unhashable secondary joint", lambda d: d["skins"].append({"joints": [{}]})),
                ("null first skin", lambda d: d["skins"].__setitem__(0, None)),
                ("non-list first joints", lambda d: d["skins"][0].update(joints=3)),
                ("non-integer child", lambda d: d["nodes"][0].update(children=["1"])),
                ("unhashable child", lambda d: d["nodes"][0].update(children=[{}])),
                ("non-list children", lambda d: d["nodes"][0].update(children=3))):
            cases[label] = glb(base, mutate=mutate)
        for label, contents in cases.items():
            check(not validate_glb(contents, extension_names=context)["ok"], "reject " + label)
        check(rig_groups_for("demo", profile)[0]["params"] == rig["params"], "opaque params")
        for key in ("example_profile", "example_attribute"):
            changed = copy.deepcopy(profile)
            if key == "example_profile":
                changed[key] = "disabled"
            else:
                changed["body_slots"]["example_slot"][key] = "disabled"
            check(rig_groups_for("demo", changed) == [], "applicability " + key)
        slot = registry.get_package("example_a").body_slots[0]
        for condition in ("example_profile", "example_attribute", "attributes.example_attribute"):
            slot.applies_to = {condition: ["disabled"]}
            check(rig_groups_for("demo", profile) == [], "slot applicability " + condition)
            slot.applies_to = {condition: ["ENABLED"]}
            check(len(rig_groups_for("demo", profile)) == 1, "slot case-insensitive " + condition)
        for target in (slot, slot.rigs[0]):
            saved_conditions = target.applies_to
            target.applies_to = {"optional": [None]}
            for value in ({}, {"optional": None}):
                check(len(rig_groups_for("demo", {**profile, **value})) == 1,
                      "null condition matches missing/explicit null")
            for value in ("", "none"):
                check(rig_groups_for("demo", {**profile, "optional": value}) == [],
                      "null differs from literal string")
            target.applies_to = saved_conditions
        slot.applies_to = {}
        # Rig template selection must not activate its owner's prompt or coverage.
        from app.core.body_slots import slots_for_character, prompt_fragments
        pkg = registry.get_package("example_a")
        saved_selector = pkg.apply_to
        pkg.apply_to = ["demo"]
        slot.rigs[0].templates = ["npc-temporary"]
        saved_conditions = slot.rigs[0].applies_to
        slot.rigs[0].applies_to = {"gender": ["female"]}
        npc = {"template": "npc-temporary", "gender": "female"}
        check(len(rig_groups_for("demo", npc)) == 1, "rig template bypasses package selector")
        check(slots_for_character("demo", profile=npc) == [], "rig selector leaves slot attributes and coverage inactive")
        check(prompt_fragments("demo", profile=npc) == {"general": [], "exposed": []},
              "rig selector leaves slot prompts inactive")
        from app.routes.characters import get_body_slots
        check(save_character_profile("sample", npc, create_new=True), "rig-only NPC profile")
        check(get_body_slots("sample")["slots"] == [], "body slots coverage API stays empty for rig-only NPC")
        check(prompt_fragments("sample") == {"general": [], "exposed": []}, "stored NPC prompt isolation")
        check(rig_groups_for("demo", {**npc, "gender": "male"}) == [], "rig gender condition still filters")
        slot.rigs[0].templates = {"feature": "humanoid"}
        check(len(rig_groups_for("demo", npc)) == 1, "rig feature template selector")
        slot.rigs[0].templates = "*"
        check(len(rig_groups_for("demo", npc)) == 1, "rig wildcard template selector")
        slot.rigs[0].templates = None
        slot.rigs[0].applies_to = saved_conditions
        pkg.apply_to = saved_selector
        motion = motion_payload("demo", profile)
        expected = {"scale_axis": "centroid", "bones": ["ExampleBone1", "ExampleBone2"], "freq_hz": 2.2,
                    "zeta": 0.15, "gravity": 0.35, "gravity_scale": 1.0, "stretch": 0.0, "spread": 0.5, "flatten_floor": .6, "length": 1.0, "girth": 1.0, "spill": 0.0, "flatten": 0.0, "translate": 0.0, "sag_max_deg": 25.0, "spill_max_deg": 25.0, "head_sag": 1.0, "gain": 1.0, "max_deg": 25.0,
                    "axis_gain": [1, 1, 1], "squash": [0.6, 1.4], "rest_deg": 0, "rest_max_deg": 90.0, "straighten_deg": 0.0, "freetext_clothing_gain": 1.0}
        check(motion["groups"] == {"example_group": expected}, "motion defaults")
        check(motion == motion_payload("demo", copy.deepcopy(profile)), "stable motion rev")
        check(motion["rev"] != motion_payload("demo", {})["rev"], "resolved content changes rev")
        slot.rigs[0].gain = 0.5
        changed_motion = motion_payload("demo", profile)
        check(changed_motion["rev"] != motion["rev"] and
              changed_motion["groups"]["example_group"]["gain"] == 0.5,
              "package defaults change motion independently")
        slot.rigs[0].gain = 1.0
        slot.rigs[0].spill = .5
        spill_motion = motion_payload("demo", profile)
        check(spill_motion["groups"]["example_group"]["spill"] == .5 and spill_motion["rev"] != motion["rev"],
              "package spill changes payload and revision")
        slot.rigs[0].spill = 0.0
        fingerprint = extension_metadata("demo", profile)["fingerprint"]
        for key, value in (("straighten_deg", 60), ("freetext_clothing_gain", .25), ("spread", .2), ("stretch", .8), ("flatten_floor", .15), ("translate", .6), ("flatten", .5), ("sag_max_deg", 40), ("axis_gain", [.5, 1, .15])):
            original = getattr(slot.rigs[0], key)
            setattr(slot.rigs[0], key, value)
            changed = motion_payload("demo", profile)
            check(changed["groups"]["example_group"][key] == value and changed["rev"] != motion["rev"]
                  and extension_metadata("demo", profile)["fingerprint"] == fingerprint,
                  key + " changes motion revision without mesh fingerprint")
            setattr(slot.rigs[0], key, original)
        check(extension_metadata("demo", profile)["status"] == "not_found", "reserved status")
        check(RigSpec.parse({**rig, "axis_gain": [0, .5, 1]}).axis_gain == [0, .5, 1],
              "axis_gain inclusive bounds and package round trip")
        for bad in (None, "1,1,1", [], [1, 1], [1, 1, 1, 1], [True, 1, 1],
                    [0, -0.1, 1], [1.1, 1, 1], [float("nan"), 1, 1], [1, float("inf"), 1]):
            try:
                RigSpec.parse({**rig, "axis_gain": bad})
            except ValueError:
                pass
            else:
                raise AssertionError("accepted invalid axis_gain")
        try:
            RigSpec.parse({**rig, "attribute_profiles": {"a": {"v": {"axis_gain": 1}}}})
        except ValueError:
            check(True, "axis_gain excluded from attribute multipliers")
        else:
            raise AssertionError("axis_gain accepted in attribute multipliers")
        for key, value in (("templates", None), ("templates", []), ("templates", "demo"),
                           ("templates", {"feature": True}), ("templates", [1]),
                           ("templates", {"feature": "humanoid", "extra": 1}), ("apply_to", "*"),
                           ("straighten_deg", -1), ("straighten_deg", 181), ("straighten_deg", True),
                           ("straighten_deg", float("nan")), ("freetext_clothing_gain", -.1),
                           ("freetext_clothing_gain", 1.1), ("freetext_clothing_gain", True),
                           ("freetext_clothing_gain", float("inf")), ("freq_hz", 0), ("gain", 1.1), ("spill", -0.1), ("spill", 1.1), ("spill", float("nan")), ("zeta", -1),
                           ("gravity", float("nan")), ("max_deg", 181),
                           ("translate", -.1), ("translate", 1.1), ("translate", True), ("translate", float("nan")), ("flatten", -.1), ("flatten", 1.1), ("flatten", True),
                           ("sag_max_deg", -1), ("sag_max_deg", 181), ("sag_max_deg", float("nan")),
                           ("attribute_profiles", []), ("attribute_profiles", {"a": {"v": {"gain": -1}}}),
                           ("attribute_profiles", {"a": {"v": {"freq_hz": 0}}}),
                           ("attribute_profiles", {"a": {"v": {"gain": True}}}),
                           ("attribute_profiles", {"a": {"v": {"squash": 1}}}),
                           ("rest_max_deg", -1), ("squash", [1.2, 1.4]),
                           ("params", []), ("op", "")):
            malformed = {**rig, key: value}
            try:
                RigSpec.parse(malformed)
            except ValueError:
                pass
            else:
                raise AssertionError("accepted invalid " + key)
        check(True, "physics and declaration range validation")
        check(RigSpec.parse({**rig, "max_deg": 42}).sag_max_deg == 42,
              "static limit defaults to declared dynamic limit")
        try:
            RigSpec.parse({**rig, "attribute_profiles": {"undeclared": {"v": {"gain": .5}}}},
                          attributes={"example_attribute": {"type": "str"}})
        except ValueError:
            check(True, "attribute profile keys validated against slot declarations")
        else:
            raise AssertionError("undeclared attribute profile accepted")
        malformed_manifest = copy.deepcopy(manifest)
        malformed_manifest["body_slots"][0]["rigs"][0]["chains"][0][0]["parent"] = "ForeignBone"
        bad = plugins / "example_bad"
        bad.mkdir()
        (bad / "plugin.yaml").write_text(yaml.safe_dump(malformed_manifest))
        from unittest import TestCase
        with TestCase().assertLogs("plugin_loader", level="WARNING") as logged:
            discover_packages(plugins, force=True)
        check(any("rig dropped" in line for line in logged.output), "malformed rig emits warning")
        check(registry.get_package("example_bad").body_slots[0].rigs == [],
              "malformed rig dropped, slot retained")
        shutil.rmtree(bad)
        duplicate = plugins / "example_b"
        duplicate.mkdir()
        duplicate_manifest = copy.deepcopy(manifest)
        duplicate_manifest["body_slots"][0]["rigs"][0]["id"] = "another_group"
        (duplicate / "plugin.yaml").write_text(yaml.safe_dump(duplicate_manifest))
        for conflict in ("normalized bones", "group id"):
            declaration = copy.deepcopy(duplicate_manifest)
            other_rig = declaration["body_slots"][0]["rigs"][0]
            if conflict == "normalized bones":
                other_rig["chains"][0][0]["bone"] = "mixamorig:EXAMPLEBONE1"
                other_rig["chains"][0][1]["parent"] = "mixamorig:EXAMPLEBONE1"
            else:
                other_rig["id"] = rig["id"]
                other_rig["chains"] = [[{"bone": "DifferentBone", "parent": base[0]}]]
            for reverse in (False, True):
                left, right = (declaration, manifest) if reverse else (manifest, declaration)
                (package / "plugin.yaml").write_text(yaml.safe_dump(left))
                (duplicate / "plugin.yaml").write_text(yaml.safe_dump(right))
                with TestCase().assertLogs("plugin_loader", level="ERROR") as logged:
                    discover_packages(plugins, force=True)
                check(all(registry.get_package(owner).body_slots[0].rigs == []
                          for owner in ("example_a", "example_b")),
                      f"reject every {conflict} owner reverse={reverse}")
                check(any("example_a" in line and "example_b" in line for line in logged.output),
                      "conflict error names all owners")
        shutil.rmtree(duplicate)
        (package / "plugin.yaml").write_text(yaml.safe_dump(manifest))
        discover_packages(plugins, force=True)

        check(save_character_profile("demo", profile, create_new=True), "temporary profile saved")
        check(model3d._validator_for("mixamo", "demo")(data)["ok"], "refine validator context")
        from app.models.character import set_character_pos
        set_character_pos("demo", 0.0, 0.0)
        model_dir = get_character_dir("demo") / "model3d"
        model_dir.mkdir()
        mesh = model_dir / "example.glb"
        mesh.write_bytes(data)
        from unittest.mock import patch
        # REAL selector: equally similar neutral candidates, newest wins.
        sidecar = {"pieces": {}, "items": []}
        other = model_dir / "other.glb"
        other.write_bytes(data)
        for candidate in (mesh, other):
            candidate.with_suffix(".json").write_text(json.dumps(sidecar))
        os.utime(mesh, ns=(mesh.stat().st_atime_ns, other.stat().st_mtime_ns + 1000000))
        check(model3d.find_model3d_serving("demo")[0] == mesh, "real selector first candidate")
        def row():
            return next(c for c in world_ops.build_worldmap_payload(show_all=True)["characters"]
                        if c["name"] == "demo")
        initial = row()
        check(initial["motion"] == motion and initial["model_sig"] == "example" and bool(initial["model_rev"]),
              "worldmap motion and model revision")
        dir_mtime = model_dir.stat().st_mtime_ns
        other.write_bytes(data[:-1] + b"x")
        os.utime(other, ns=(other.stat().st_atime_ns, mesh.stat().st_mtime_ns + 1000000))
        check(model_dir.stat().st_mtime_ns == dir_mtime, "in-place writer leaves directory unchanged")
        check(model3d.find_model3d_serving("demo")[0] == other and row()["model_sig"] == "other",
              "cached selection follows real newest candidate")
        original_revision = model3d.model_revision(other)
        time.sleep(0.02)  # allow filesystem timestamp granularity
        other.write_bytes(data)
        check(model3d.model_revision(other) != original_revision, "real in-place write changes revision")
        revision = model3d.model_revision(other)
        staged = model_dir / "replacement.tmp"
        staged.write_bytes(data[:-1] + b"x")
        os.replace(staged, other)
        check(model3d.model_revision(other) != revision, "same-size atomic replacement changes revision")
        with patch.object(Path, "open", side_effect=AssertionError("mesh content read")):
            check(bool(model3d.model_revision(other)), "revision uses stat only")
        previous = other.read_bytes()
        real_replace = os.replace
        def inspect_publication(source, target):
            check(Path(source).parent == Path(target).parent, "atomic stage in destination directory")
            check(other.read_bytes() == previous, "old mesh intact until publication")
            check(Path(source).read_bytes() == data, "complete new mesh staged")
            real_replace(source, target)
        with patch.object(os, "replace", side_effect=inspect_publication):
            model3d._publish_model_bytes(other, data)
        check(other.read_bytes() == data, "atomic publication exposes complete mesh")
        low = model_dir / "low"
        low.mkdir()
        tier_file = low / other.name
        revision = row()["model_rev"]
        tier_file.write_bytes(data)
        check(row()["model_rev"] != revision, "tier creation changes worldmap revision")
        revision = model3d.model_revision(other)
        time.sleep(0.02)
        tier_file.write_bytes(data[:-1] + b"x")
        check(model3d.model_revision(other) != revision, "in-place tier rewrite changes revision")
        revision = model3d.model_revision(other)
        staged = low / "replacement.tmp"
        staged.write_bytes(data)
        os.replace(staged, tier_file)
        check(model3d.model_revision(other) != revision, "same-size atomic tier replacement")
        from app.routes.characters import get_character_model_meta
        admin = get_character_model_meta("demo")
        check(admin["motion"] == motion and admin["model_rev"] == row()["model_rev"],
              "admin and cached worldmap agree")
        check(admin["extension_rig"]["status"] == "not_found", "admin reserved metadata")
        revision = row()["model_rev"]
        tier_file.unlink()
        check(row()["model_rev"] != revision, "tier deletion changes worldmap revision")
        other.with_suffix(".json").write_text("{}")
        check(model3d.find_model3d_serving("demo")[0] == mesh and row()["model_sig"] == "example",
              "cached selection follows sidecar rewrite")

        # Reference-sidecar fallback participates in the same selection token.
        refs = model_dir.parent / "model_refs"
        refs.mkdir(exist_ok=True)
        fallback = refs / "tpose_other.json"
        fallback.write_text(json.dumps(sidecar))
        os.utime(other, ns=(other.stat().st_atime_ns, mesh.stat().st_mtime_ns + 1000000))
        check(model3d.find_model3d_serving("demo")[0] == other and row()["model_sig"] == "other",
              "cached selection follows fallback sidecar creation")
        time.sleep(0.02)
        fallback.write_text("{}")
        check(model3d.find_model3d_serving("demo")[0] == mesh and row()["model_sig"] == "example",
              "cached selection follows fallback sidecar rewrite")

        import asyncio
        from app.routes.characters import upload_character_model3d

        class MemoryUpload:
            filename = "example.glb"

            def __init__(self):
                self.remaining = data

            async def read(self, size):
                chunk, self.remaining = self.remaining[:size], self.remaining[size:]
                return chunk

        class UploadRequest:
            headers = {}

            async def form(self):
                return {"file": MemoryUpload()}

        with patch.object(model3d, "_auto_retexture"), patch.object(model3d, "_auto_normalize"), \
                patch.object(model3d, "_auto_extension_rig"), \
                patch.object(model3d, "_attach_measurement"), patch.object(model3d, "request_lod"):
            uploaded = run_async(upload_character_model3d("demo", UploadRequest()))
        check(uploaded["rig"] == "mixamo" and uploaded["extension_rig"]["status"] == "not_found",
              "upload context and reserved sidecar")
        uploaded_sidecar = model_dir / (uploaded["signature"] + ".json")
        check(json.loads(uploaded_sidecar.read_text())["extension_rig"]["status"] == "not_found",
              "sidecar persisted without applied status")

        shutil.rmtree(package)
        discover_packages(plugins, force=True)
        check(rig_groups_for("demo", profile) == [] and extension_bone_names("demo", profile) == {},
              "package deletion removes groups")
        check(validate_glb(glb(base))["ok"] and not validate_glb(data)["ok"], "deletion restores strict base contract")
        check(extension_metadata("demo", profile)["status"] == "none_applicable", "deletion metadata")
        print("PASS extension rig P0: all checks")


if __name__ == "__main__":
    main()
