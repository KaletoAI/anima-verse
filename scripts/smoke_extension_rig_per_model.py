#!/usr/bin/env python3
"""Per-model extension switches, without Blender or real storage.

Hand-derived expectations: G defaults to enabled=True, flip=False. Disabling G
on A changes only A's groups and hash input; B keeps the default groups/hash.
A matching attempted sidecar requires zero Blender calls, in both tiers.
The info reader uses the served signature even when the current outfit differs;
the rebuild checker accepts distinct matching A/B hashes and rejects a stale B.
Replacement preserves B; an empty map removes only A. Missing, unsafe, unknown,
low-only and state-fork signatures and non-bool flags are invalid (route: 400).
Migration copies the identical flat map to A.glb and B.fbx only, excluding low,
prerig and state forks, plus the current outfit signature L when a legacy
model/ store is still waiting for its import (which runs after it at boot). Identical hash inputs preserve both fingerprints.
The old key disappears; a second run writes zero profiles. A failed save raises
and leaves the old map available for retry. Empty legacy maps are removed too.
Usage: .venv/bin/python scripts/smoke_extension_rig_per_model.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rejects(call, error=ValueError):
    try:
        call()
    except error as exc:
        return exc
    raise AssertionError(f"Expected {error.__name__}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(Path(tmp) / "reference.fbx")
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / "instance")
        from app.core import db, extension_rig, model3d
        from app.core.keyed_lock import keyed_lock
        from app.models.character import get_character_dir, get_character_profile, save_character_profile
        db.init_schema()
        get_character_dir("demo").mkdir(parents=True, exist_ok=True)
        with keyed_lock("character_profile", "demo"):
            assert save_character_profile("demo", {"name": "demo"})
        directory = model3d.get_model3d_dir("demo")
        for relative in ("A.glb", "B.glb", "B.fbx", "A-sold.glb", "low/A.glb", "low/C.glb", "prerig/D.glb"):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        group = {"id": "G", "op": "appendage_chain", "chains": [], "params": {}}
        disabled = {"G": {"enabled": False}}
        with patch.object(extension_rig, "rig_groups_for", return_value=[group]):
            model3d.set_model3d_options("demo", {"signature": "A", "extension_rig": disabled})
            profile = get_character_profile("demo")
            assert extension_rig.resolved_extension_groups("demo", profile, "A")[0]["enabled"] is False
            b = extension_rig.resolved_extension_groups("demo", profile, "B")[0]
            assert b["enabled"] is True and b["flip"] is False
            default = extension_rig.extension_rig_fingerprint([group])
            a_fp = extension_rig.extension_metadata("demo", profile, "A")["fingerprint"]
            assert a_fp != default
            assert extension_rig.extension_metadata("demo", profile, "B")["fingerprint"] == default
            assert extension_rig.resolved_extension_groups("demo", {"model3d_opts": {"extension_rig": disabled}}, "A")[0]["enabled"] is True
            with patch.object(model3d, "current_outfit_state", return_value=({}, [], "unknown")), \
                    patch.object(model3d, "find_model3d_serving", return_value=(directory / "A.glb", "nearest")), \
                    patch.object(model3d, "required_rig", return_value="mixamo"), \
                    patch.object(extension_rig, "motion_payload", return_value={"groups": {}}), \
                    patch("app.imagegen.service.get_image_service", return_value=MagicMock()), \
                    patch("app.imagegen.routing.explain_occasion", return_value={}), \
                    patch.object(model3d, "list_mesh_backends", return_value={}), \
                    patch.object(model3d, "list_rig_backends", return_value=[]):
                info = model3d.get_model3d_info("demo")
                assert info["model"]["signature"] == "A"
                assert info["model"]["extension_rig"]["fingerprint"] == a_fp
            from app.core.improvements.base import Candidate
            from app.core.improvements.types.extension_rig_rebuild import ExtensionRigRebuild
            checker = ExtensionRigRebuild()
            for signature, fingerprint in (("A", a_fp), ("B", default)):
                (directory / f"{signature}.json").write_text(json.dumps({"extension_rig": {
                    "attempted": True, "status": "none_applicable", "fingerprint": fingerprint}}))
            candidate = Candidate("character:demo", "demo")
            assert checker.is_done(candidate, {"character": "demo"})
            (directory / "B.json").write_text(json.dumps({"extension_rig": {
                "attempted": True, "status": "none_applicable", "fingerprint": a_fp}}))
            assert not checker.is_done(candidate, {"character": "demo"})
            meta = {"rig": "mixamo", "extension_rig": {"attempted": True, "status": "applied", "fingerprint": a_fp}}
            for path in (directory / "A.glb", directory / "low/A.glb"):
                path.with_suffix(".json").write_text(json.dumps(meta))
            from app.blender import refine
            with patch.object(refine, "apply_script", side_effect=AssertionError("Unexpected Blender call")) as blender:
                for path in (directory / "A.glb", directory / "low/A.glb"):
                    assert model3d._auto_extension_rig("demo", path, model3d._read_sidecar(path))["noop"]
                blender.assert_not_called()
            for updates in ({"extension_rig": disabled}, {"signature": "unknown", "extension_rig": disabled},
                            {"signature": "../A", "extension_rig": disabled}, {"signature": 1, "extension_rig": disabled},
                            {"signature": "C", "extension_rig": disabled}, {"signature": "A-sold", "extension_rig": disabled},
                            {"signature": "A", "extension_rig": {"G": {"enabled": 0}}}):
                rejects(lambda: model3d.set_model3d_options("demo", updates))
            from app.routes.characters import _set_character_model3d_options_sync
            from fastapi import HTTPException
            for signature in (None, 1, "../A", "unknown"):
                exc = rejects(lambda: _set_character_model3d_options_sync("demo", {"signature": signature, "extension_rig": disabled}), HTTPException)
                assert exc.status_code == 400
            exc = rejects(lambda: _set_character_model3d_options_sync("demo", {
                "signature": "A", "extension_rig": {"G": {"flip": "true"}}}), HTTPException)
            assert exc.status_code == 400
            _set_character_model3d_options_sync("demo", {"signature": "B", "extension_rig": {"G": {"flip": True}}})
            model3d.set_model3d_options("demo", {"signature": "A", "extension_rig": {"G": {"flip": True}}})
            assert model3d.get_model3d_options("demo")["extension_rig_models"]["A"] == {"G": {"flip": True}}
            model3d.set_model3d_options("demo", {"signature": "A", "extension_rig": {}})
            assert model3d.get_model3d_options("demo")["extension_rig_models"] == {"B": {"G": {"flip": True}}}
            with patch("app.models.character.save_character_profile", return_value=False):
                rejects(lambda: model3d.set_model3d_options("demo", {"signature": "A", "extension_rig": disabled}), RuntimeError)
            with keyed_lock("character_profile", "demo"):
                profile = get_character_profile("demo")
                profile["model3d_opts"] = {"extension_rig": disabled, "auto_generate": True,
                                           "extension_motion": {"G": {"bounce": 0.5}},
                                           "extension_rig_models": {"gone": {"G": {"flip": True}}}}
                assert save_character_profile("demo", profile)
            before = extension_rig.extension_rig_fingerprint([group], disabled)
            with patch("app.models.character.save_character_profile", return_value=False):
                rejects(extension_rig.migrate_extension_rig_models_once, RuntimeError)
            assert get_character_profile("demo")["model3d_opts"]["extension_rig"] == disabled
            legacy = get_character_dir("demo") / "model" / "model.glb"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_bytes(b"fixture")
            with patch("app.core.model_refs.current_outfit_state", return_value=({}, [], "L")):
                extension_rig.migrate_extension_rig_models_once()
            legacy.unlink()
            legacy.parent.rmdir()
            profile = get_character_profile("demo")
            opts = profile["model3d_opts"]
            assert "extension_rig" not in opts
            assert set(opts["extension_rig_models"]) == {"A", "B", "L", "gone"}
            assert opts["auto_generate"] is True and opts["extension_motion"] == {"G": {"bounce": 0.5}}
            for signature in ("A", "B", "L"):
                assert opts["extension_rig_models"][signature] == disabled
                assert extension_rig.extension_metadata("demo", profile, signature)["fingerprint"] == before
            with patch("app.models.character.save_character_profile", side_effect=AssertionError("Idempotent migration wrote")):
                extension_rig.migrate_extension_rig_models_once()
            assert get_character_profile("demo") == profile
            with keyed_lock("character_profile", "demo"):
                profile = get_character_profile("demo")
                profile["model3d_opts"]["extension_rig"] = {}
                assert save_character_profile("demo", profile)
            extension_rig.migrate_extension_rig_models_once()
            assert "extension_rig" not in get_character_profile("demo")["model3d_opts"]
        print("PASS: per-model groups, fingerprints, noops, setter/route validation, migration and save failures")


if __name__ == "__main__":
    main()
