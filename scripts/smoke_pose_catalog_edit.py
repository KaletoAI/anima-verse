#!/usr/bin/env python3
"""Generated catalog edits smoke.

Usage: ./.venv/bin/python scripts/smoke_pose_catalog_edit.py

Hand-derived expectations: shared edits touch shared, overrides touch both,
pairs fail with 400, the first seat pose becomes its group default, occupied
synonyms are dropped, occupied keys fail with 409, candidates disappear.
Storage uses a temporary world and a private shared catalog copy.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core import pose_catalog as pc
        from app.core.db import init_schema
        from app.core.pose_catalog_edit import apply_generated_entry as apply, CatalogEditError
        init_schema()
        original = pc.catalog_path
        real = original("pose")
        before_real = real.read_bytes()
        private = Path(tmp) / "pose_catalog.json"
        private.write_bytes(before_real)
        entries = {
            "standing": {"prompt": "standing", "synonyms": [], "animation": "standing", "solo": True, "group": "stand", "_default": True},
            "waving": {"prompt": "waving", "synonyms": ["winken"], "animation": "waving", "solo": True, "group": "stand"},
            "hug": {"prompt": "hug", "synonyms": [], "animation": "hug", "solo": False, "group": "stand", "places": 2, "yaw_offset": 0}}
        private.write_text(json.dumps({"groups": {
            "stand": {"label": "Stand", "default": "standing", "needs_place": False},
            "seat": {"label": "Seat", "default": "", "needs_place": True}}, "entries": entries}))
        pc.catalog_path = lambda axis: private if axis == "pose" else original(axis)
        pc.reload_catalogs()
        def document():
            return json.loads(private.read_text())
        def refused(status, **kwargs):
            before = private.read_bytes()
            try:
                apply(animation="waving-u", **kwargs)
            except CatalogEditError as error:
                assert error.status == status
                if kwargs["key"] == "hug":
                    assert error.detail == "pair poses cannot get a generated animation"
            else:
                raise AssertionError("Expected refusal")
            assert private.read_bytes() == before
        try:
            assert apply(mode="entry", animation="waving-u", key="waving") == {"key": "waving", "stores": ["shared"]}
            assert document()["entries"]["waving"]["animation"] == "waving-u"
            pc.replace_world_entries("pose", {"waving": dict(entries["waving"], animation="old-world")})
            pc.reload_catalogs()
            assert apply(mode="entry", animation="waving-u", key="waving")["stores"] == ["shared", "world"]
            assert document()["entries"]["waving"]["animation"] == "waving-u"
            assert pc.world_entries("pose")["waving"]["animation"] == "waving-u"
            refused(400, mode="entry", key="hug")
            world = pc.world_entries("pose")
            world["hug"] = dict(entries["hug"], solo=True, animation="solo-world")
            pc.replace_world_entries("pose", world)
            pc.reload_catalogs()
            before_world_hug = pc.world_entries("pose")["hug"]
            refused(400, mode="entry", key="hug")
            assert pc.world_entries("pose")["hug"] == before_world_hug
            del world["hug"]
            pc.replace_world_entries("pose", world)
            pc.reload_catalogs()
            assert apply(mode="free", animation="sweeping-u", key="sweeping", entry={"prompt": "sweeping", "group": "seat"})["stores"] == ["shared"]
            assert document()["entries"]["sweeping"]["solo"] is True
            assert document()["groups"]["seat"]["default"] == "sweeping"
            assert "_default" not in document()["entries"]["sweeping"]
            apply(mode="free", animation="dusting-u", key="dusting", entry={"prompt": "dusting", "group": "stand", "synonyms": ["winken"]})
            assert document()["entries"]["dusting"]["synonyms"] == []
            refused(409, mode="free", key="waving", entry={"prompt": "duplicate", "group": "stand"})
            pc.record_candidate("pose", "fegt den boden", "standing", 0.1)
            assert len(pc.list_candidates("pose", "open")) == 1
            apply(mode="candidate", animation="cleaning-u", key="cleaning", entry={"prompt": "cleaning", "group": "stand"}, raw_text="fegt den boden")
            assert document()["entries"]["cleaning"]["synonyms"] == ["fegt den boden"]
            assert pc.list_candidates("pose", "open") == []
            assert pc.validate_catalog("pose") == []
            refused(404, mode="entry", key="missing")
            refused(409, mode="free", key="winken", entry={"prompt": "collision", "group": "stand"})
            world = pc.world_entries("pose")
            world["world-only"] = dict(entries["waving"], synonyms=[])
            pc.replace_world_entries("pose", world)
            pc.reload_catalogs()
            before_shared = private.read_bytes()
            assert apply(mode="entry", animation="world-u", key="world-only")["stores"] == ["world"]
            assert pc.world_entries("pose")["world-only"]["animation"] == "world-u"
            assert private.read_bytes() == before_shared
        finally:
            pc.catalog_path = original
            pc.reload_catalogs()
            assert real.read_bytes() == before_real
    print("PASS: generated catalog edits (7 required cases)")


if __name__ == "__main__":
    main()
