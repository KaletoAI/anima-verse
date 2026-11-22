#!/usr/bin/env python3
"""Renderer-only horizontal clip shifts; no Blender, real clips or world DB.

Usage: ./.venv/bin/python scripts/smoke_clip_orient_shift.py

Hand derivation: [25,-40] + [-5,10] = [20,-30] cm. Adding [-20,30]
removes the correction. A pair has ONE common correction, never a change
to its authored root separation or role_shift_cm. Dummy FBX bytes make
an accidental Blender invocation fail. Invalid/zero edits must write nothing.

[M] THE BOOT MIGRATION migrate_partner_shift_roles (2026-11-22): a pair's
former geometry.partner_shift_cm is added to geometry.role_shift_cm.b and
removed, nothing re-baked (the FBX bytes stay):
    m1: partner [5, 0, -10], no role shifts        -> {"b": [5.0, 0.0, -10.0]}
    m2: partner [2, 0, 0],   b [-2, 0, 1], a [0, 1, 0]
        b = [-2 + 2, 0 + 0, 1 + 0] = [0, 0, 1]      -> {"a": [0, 1, 0], "b": [0.0, 0.0, 1.0]}
    m3: partner [1.5, 0, 0], b [-1.5, 0, 0]: b = [0, 0, 0] drops out, and with
        it the whole field                           -> no role_shift_cm
    m4: no partner_shift_cm                          -> untouched (not counted)
  The first run changes 3 files, the second 0 (idempotent). The listing's
  orientation has no partner_shift_cm key; POST …/orient with
  partner_shift_cm is a 400 that writes nothing.
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
            "roles": roles, "role_shift_cm": {"b": [5, 0, -10]}, "root_distance_m": .6}}))
        rows = apply("pair__b.fbx", [25, -40])
        assert len(rows) == 2 and all(r["orientation"]["shift_cm"] == [25, -40] for r in rows)
        data = json.loads(shared.read_text())["geometry"]
        assert data["roles"] == roles and data["role_shift_cm"] == {"b": [5, 0, -10]}
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
        # [M] the boot migration
        mig = root / "free" / "mig"
        mig.mkdir()
        cases = {"m1": ({"partner_shift_cm": [5, 0, -10]}, {"b": [5.0, 0.0, -10.0]}),
                 "m2": ({"partner_shift_cm": [2, 0, 0], "role_shift_cm": {"a": [0, 1, 0], "b": [-2, 0, 1]}},
                        {"a": [0, 1, 0], "b": [0.0, 0.0, 1.0]}),
                 "m3": ({"partner_shift_cm": [1.5, 0, 0], "role_shift_cm": {"b": [-1.5, 0, 0]}}, None),
                 "m4": ({"role_shift_cm": {"b": [1, 2, 3]}}, {"b": [1, 2, 3]})}
        for name, (geo, _want) in cases.items():
            for r in ("a", "b"):
                (mig / f"{name}__{r}.fbx").write_bytes(b"never rewrite this FBX")
            (mig / f"{name}.json").write_text(json.dumps({"pair": True, "geometry": dict(geo)}))
        fbx_before = {p.name: p.read_bytes() for p in mig.glob("*.fbx")}
        assert ac.migrate_partner_shift_roles() == 3
        for name, (_geo, want) in cases.items():
            g = json.loads((mig / f"{name}.json").read_text())["geometry"]
            assert "partner_shift_cm" not in g, (name, g)
            assert g.get("role_shift_cm") == want, (name, g)
        assert ac.migrate_partner_shift_roles() == 0
        assert fbx_before == {p.name: p.read_bytes() for p in mig.glob("*.fbx")}
        listing = assets.list_animation_clips()["clips"]
        assert all("partner_shift_cm" not in (r.get("orientation") or {}) for r in listing)
        before = {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
        try:
            asyncio.run(request("pair__a.fbx", {"partner_shift_cm": [5, 0, 0]}))
        except HTTPException as error:
            assert error.status_code == 400, error
        else:
            raise AssertionError("partner_shift_cm accepted")
        assert before == {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
        print("OK: cumulative shift, pair/shared sidecar, sets, unchanged roots/FBX, boundaries, validation, "
              "partner shift migration")


if __name__ == "__main__":
    main()
