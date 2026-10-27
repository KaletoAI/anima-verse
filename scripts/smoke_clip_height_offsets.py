#!/usr/bin/env python3
"""Independent per-surface clip heights, without Blender or real libraries.

Usage: ./.venv/bin/python scripts/smoke_clip_height_offsets.py

The reference figure is 1.70 m. Literal corrections lie=12, seat=-7 and
ground=3 cm must survive independent updates; resetting lie to zero removes
only lie. They are absolute sidecar values, not FBX transformations. This
smoke catches lost partial updates, cross-set/library metadata leakage,
pair-half disagreement, invalid-request partial writes, and rename metadata
loss. Dummy FBX bytes deliberately cannot be processed by Blender.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clip-heights-") as tmp:
        root = Path(tmp)
        free, licensed, world = (root / name for name in ("free", "licensed", "world"))
        for directory in (free, licensed, world):
            directory.mkdir()
        os.environ["ANIMATION_CLIPS_DIR"] = str(free)
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(licensed)
        os.environ["ANIMATION_RIG_FILE"] = str(root / "unused-reference.fbx")
        from app.core import paths
        paths.init(world)
        paths.init_instance(root / "instance")
        from app.core import animation_clips as ac
        from app.routes import assets
        from fastapi import HTTPException
        from starlette.requests import Request

        def fixture(rel: str, data=None, library=free) -> Path:
            path = library / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("unchanged:" + rel).encode())
            if data is not None:
                path.with_suffix(".json").write_text(json.dumps(data), encoding="utf-8")
            return path

        async def call_patch(rel: str, body: dict):
            payload = json.dumps(body).encode()
            async def receive():
                return {"type": "http.request", "body": payload, "more_body": False}
            request = Request({"type": "http", "method": "PATCH", "path": "/", "headers": []}, receive)
            return await assets.patch_animation_clip("free", rel, request, _={})

        def patch(rel: str, values: dict):
            return asyncio.run(call_patch(rel, {"height_offsets_cm": values}))["clips"]

        def view(rel: str, library="free") -> dict:
            return next(v for v in assets.list_animation_clips()["clips"]
                        if v["rel"] == rel and v["library"] == library)

        base = fixture("rest.fbx", {"kind": "rest", "geometry": {"floor_shift_cm": 9}})
        original = base.read_bytes()
        patch("rest.fbx", {"lie": 12, "seat": -7, "ground": 3})
        assert view("rest.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7, "ground": 3}
        patch("rest.fbx", {"lie": 15})
        assert view("rest.fbx")["height_offsets_cm"] == {"lie": 15, "seat": -7, "ground": 3}
        patch("rest.fbx", {"lie": 0})
        assert view("rest.fbx")["height_offsets_cm"] == {"seat": -7, "ground": 3}
        data = json.loads(base.with_suffix(".json").read_text())
        assert "lie" not in data["height_offsets_cm"]
        assert data["geometry"]["floor_shift_cm"] == 9
        assert base.read_bytes() == original

        # Each actual set/library resolves its own correction, not a nominal kind.
        fixture("rest.fbx", {"height_offsets_cm": {"lie": 40}}, licensed)
        fixture("female/rest.fbx", {"height_offsets_cm": {"lie": 12}})
        fixture("male/rest.fbx", {"height_offsets_cm": {"lie": -5}})
        fixture("bare.fbx")
        assert view("female/rest.fbx")["height_offsets_cm"] == {"lie": 12}
        assert view("male/rest.fbx")["height_offsets_cm"] == {"lie": -5}
        patch("female/rest.fbx", {"seat": -7})
        assert view("female/rest.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert view("rest.fbx", "licensed")["height_offsets_cm"] == {"lie": 40}
        patch("bare.fbx", {"ground": 3})
        assert view("bare.fbx")["height_offsets_cm"] == {"ground": 3}

        # Numbered files honor an own sidecar, otherwise the shared kind sidecar.
        fixture("step.fbx", {"kind": "step", "height_offsets_cm": {"ground": 3}})
        fixture("step_02.fbx", {"kind": "step", "height_offsets_cm": {"seat": -7}})
        fixture("step_03.fbx")
        patch("step_02.fbx", {"lie": 12})
        assert view("step_02.fbx")["height_offsets_cm"] == {"seat": -7, "lie": 12}
        assert view("step.fbx")["height_offsets_cm"] == {"ground": 3}
        assert view("step_03.fbx")["height_offsets_cm"] == {"ground": 3}
        # A kind-wide loop edit must not retarget heights to the first variant.
        asyncio.run(call_patch(
            "step_02.fbx", {"loop": True, "height_offsets_cm": {"lie": 14}}))
        assert view("step_02.fbx")["height_offsets_cm"] == {"seat": -7, "lie": 14}
        assert view("step.fbx")["height_offsets_cm"] == {"ground": 3}
        assert view("step_03.fbx")["height_offsets_cm"] == {"ground": 3}
        patch("step_02.fbx", {"lie": 12})

        # An inherited ROOT variant outranks a set's shared kind metadata.
        # Save a local OWN sidecar instead of an invisible write to the shared one.
        fixture("walk_02.fbx", {"kind": "walk", "height_offsets_cm": {"lie": 12}})
        fixture("female/walk.fbx", {"kind": "walk", "height_offsets_cm": {"ground": 3}})
        fixture("female/walk_02.fbx")
        shared_before = (free / "female/walk.json").read_bytes()
        root_before = (free / "walk_02.json").read_bytes()
        assert view("female/walk_02.fbx")["height_offsets_cm"] == {"lie": 12}
        result = patch("female/walk_02.fbx", {"seat": -7})
        assert result[0]["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert view("female/walk_02.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert (free / "female/walk_02.json").is_file()
        assert (free / "female/walk.json").read_bytes() == shared_before
        assert (free / "walk_02.json").read_bytes() == root_before
        assert view("female/walk.fbx")["height_offsets_cm"] == {"ground": 3}

        # Exact-stem sidecars may retain case even though the kind is lowercase.
        uppercase = fixture(
            "female/Walk.fbx", {"kind": "walk", "height_offsets_cm": {"lie": 12}})
        uppercase_bytes = uppercase.read_bytes()
        result = patch("female/Walk.fbx", {"seat": -7})
        assert result[0]["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert view("female/Walk.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert json.loads((free / "female/Walk.json").read_text())["height_offsets_cm"] == {"lie": 12, "seat": -7}
        assert (free / "female/walk.json").read_bytes() == shared_before
        assert uppercase.read_bytes() == uppercase_bytes
        moved = ac.rename_clip("free", "step_02.fbx", kind="stride", cset="female")
        assert moved[0]["height_offsets_cm"] == {"seat": -7, "lie": 12}
        assert (free / "female/stride_02.json").is_file()
        combined = asyncio.run(call_patch(
            "bare.fbx", {"kind": "floor", "set": "female",
                         "height_offsets_cm": {"seat": -7}}))
        assert combined["clips"][0]["rel"] == "female/floor.fbx"
        assert view("female/floor.fbx")["height_offsets_cm"] == {"ground": 3, "seat": -7}
        ac.rename_clip("free", "female/floor.fbx", kind="bare", cset="")

        # Both halves, including half-specific metadata, receive one correction.
        a = fixture("hug__a.fbx", {"kind": "hug", "height_offsets_cm": {"lie": 4}})
        b = fixture("hug__b.fbx", {"kind": "hug", "height_offsets_cm": {"lie": -2}})
        (free / "hug.json").write_text(json.dumps({"kind": "hug", "pair": True}), encoding="utf-8")
        pair_bytes = (a.read_bytes(), b.read_bytes())
        clips = patch("hug__b.fbx", {"lie": 12, "seat": -7, "ground": 3})
        assert {c["role"] for c in clips} == {"a", "b"}
        assert view("hug__a.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7, "ground": 3}
        assert view("hug__b.fbx")["height_offsets_cm"] == {"lie": 12, "seat": -7, "ground": 3}
        patch("hug__a.fbx", {"seat": 0})
        assert view("hug__a.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert view("hug__b.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert (a.read_bytes(), b.read_bytes()) == pair_bytes

        # Own half sidecars do not make a pair independent of its shared map.
        # Another numbered pair remains behind, so the shared map must COPY.
        fixture("hug__a_02.fbx")
        fixture("hug__b_02.fbx")
        moved_pair = ac.rename_clip("free", "hug__a.fbx", kind="embrace", cset="female")
        assert {c["role"] for c in moved_pair} == {"a", "b"}
        assert all(c["height_offsets_cm"] == {"lie": 12, "ground": 3} for c in moved_pair)
        assert view("female/embrace__a.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert view("female/embrace__b.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert view("hug__a_02.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert view("hug__b_02.fbx")["height_offsets_cm"] == {"lie": 12, "ground": 3}
        assert (free / "female/embrace.json").is_file()
        assert ((free / "female/embrace__a.fbx").read_bytes(),
                (free / "female/embrace__b.fbx").read_bytes()) == pair_bytes

        # Invalid maps fail before a valid key (or combined rename) can mutate.
        invalid = [None, [], 12, {"stand": 2}, {"lie": True}, {"lie": "12"},
                   {"lie": float("nan")}, {"lie": float("inf")},
                   {"lie": -51}, {"lie": 51}, {"ground": 8, "seat": False}]
        for values in invalid:
            before = {str(p.relative_to(free)): p.read_bytes() for p in free.rglob("*") if p.is_file()}
            try:
                asyncio.run(call_patch("bare.fbx", {"kind": "changed", "height_offsets_cm": values}))
            except HTTPException as error:
                assert error.status_code == 400, (values, error)
            else:
                raise AssertionError(f"invalid correction accepted: {values}")
            after = {str(p.relative_to(free)): p.read_bytes() for p in free.rglob("*") if p.is_file()}
            assert before == after, values

        # Sidecar readers sanitize hand-edited data; API writes remain strict.
        fixture("dirty.fbx", {"height_offsets_cm": {"lie": 12, "seat": True, "ground": float("inf"), "other": 9}})
        assert view("dirty.fbx")["height_offsets_cm"] == {"lie": 12}
        # The combined rename above added seat=-7; ground edits must retain it.
        for value in (-50, 50):
            patch("bare.fbx", {"ground": value})
            assert view("bare.fbx")["height_offsets_cm"] == {"ground": value, "seat": -7}
        patch("bare.fbx", {"ground": 0})
        assert view("bare.fbx")["height_offsets_cm"] == {"seat": -7}
        patch("bare.fbx", {"seat": 0})
        assert view("bare.fbx")["height_offsets_cm"] == {}

        async def old_orient():
            async def receive():
                return {"type": "http.request", "body": b'{"height_cm": 12}', "more_body": False}
            request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
            return await assets.post_animation_clip_orient("free", "bare.fbx", request, _={})
        try:
            asyncio.run(old_orient())
        except HTTPException as error:
            assert error.status_code == 400 and "height_offsets_cm" in str(error.detail)
        else:
            raise AssertionError("public orientation still accepts baked height")
        print("OK: independent clip surface heights, sets, variants, pairs, rename, validation and unchanged FBX bytes")


if __name__ == "__main__":
    main()
