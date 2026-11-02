#!/usr/bin/env python3
"""Renderer-only horizontal clip shifts; no Blender, real clips or world DB.

Usage: ./.venv/bin/python scripts/smoke_clip_orient_shift.py

Hand derivation: [25,-40] + [-5,10] = [20,-30] cm. Adding [-20,30]
removes the correction. A pair has ONE common correction, never a change
to its authored root separation or partner_shift_cm. Dummy FBX bytes make
an accidental Blender invocation fail. Invalid/zero edits must write nothing.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="clip-orient-shift-") as tmp:
        root = Path(tmp)
        for name in ("free", "licensed", "world"):
            (root / name).mkdir()
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "free")
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "unused.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import animation_clips as ac
        from app.routes import assets
        from fastapi import HTTPException
        from starlette.requests import Request

        def fixture(stem, meta):
            p = root / "free" / f"{stem}.fbx"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"never rewrite this FBX")
            p.with_suffix(".json").write_text(json.dumps(meta))
            return p

        async def request(rel, body):
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            req = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
            return await assets.post_animation_clip_orient("free", rel, req, _={})

        def apply(rel, value):
            return asyncio.run(request(rel, {"shift_cm": value}))["clips"]

        solo = fixture("rest", {"geometry": {"root_motion": {"mode": "strip"}}})
        original = solo.read_bytes()
        # The core API and route must both preserve non-baked shifts.
        rows = ac.orient_clip("free", "rest.fbx", shift_cm=[25, -40])
        assert rows[0]["orientation"]["shift_cm"] == [25, -40]
        assert apply("rest.fbx", [-5, 10])[0]["orientation"]["shift_cm"] == [20, -30]
        apply("rest.fbx", [-20, 30])
        assert "shift_cm" not in json.loads(solo.with_suffix(".json").read_text())["geometry"]
        assert solo.read_bytes() == original

        roles = {"a": {"start_xz_m": [.1, .2]}, "b": {"start_xz_m": [.7, .2]}}
        fixture("pair__a", {"geometry": {"shift_cm": [99, 99]}})
        fixture("pair__b", {"geometry": {"shift_cm": [-99, -99]}})
        shared = root / "free/pair.json"
        shared.write_text(json.dumps({"pair": True, "geometry": {
            "roles": roles, "partner_shift_cm": [5, 0, -10], "root_distance_m": .6}}))
        rows = apply("pair__b.fbx", [25, -40])
        assert len(rows) == 2 and all(r["orientation"]["shift_cm"] == [25, -40] for r in rows)
        data = json.loads(shared.read_text())["geometry"]
        assert data["roles"] == roles and data["partner_shift_cm"] == [5, 0, -10]
        assert data["root_distance_m"] == .6
        listing = assets.list_animation_clips()["clips"]
        assert all(r["orientation"]["shift_cm"] == [25, -40] for r in listing if r["kind"] == "pair")
        fixture("female/rest", {"geometry": {}})
        assert apply("female/rest.fbx", [200, -200])[0]["orientation"]["shift_cm"] == [200, -200]
        assert apply("female/rest.fbx", [200, -200])[0]["orientation"]["shift_cm"] == [400, -400]

        invalid = [[0, 0], [], [1], [1, 2, 3], [True, 1], ["2", 1], [201, 0],
                   [0, -201], [float("nan"), 0], [float("inf"), 0], [10**1000, 0], "bad"]
        for value in invalid:
            before = {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
            try:
                apply("rest.fbx", value)
            except HTTPException as error:
                assert error.status_code == 400, (value, error)
            else:
                raise AssertionError(f"accepted invalid shift: {value}")
            assert before == {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
        for value in invalid[1:]:
            try:
                ac.orient_clip("free", "rest.fbx", shift_cm=value)
            except ac.ClipLibraryError:
                pass
            else:
                raise AssertionError(f"core accepted invalid shift: {value}")
        print("OK: cumulative shift, pair/shared sidecar, sets, unchanged roots/FBX, boundaries and validation")


if __name__ == "__main__":
    main()
