#!/usr/bin/env python3
"""Ruling A129: a pair's renderer-only partner-B turn ``partner_turn_deg`` [tilt, roll] — no Blender, no real clips,
no world DB.

Usage: ./.venv/bin/python scripts/smoke_clip_partner_turn.py

Hand derivation: [10, -5] + [-2.5, 1] = [7.5, -4] degrees (cumulative, like ``shift_cm``); adding [-7.5, 4] removes
the key. Both halves of the pair list the same value. A solo clip refuses a turn (400); a value beyond ±45 per edit,
a boolean, a string or a wrong length is a 400 and writes nothing. Dummy FBX bytes make an accidental Blender run fail,
and the FBX bytes stay unchanged.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="clip-partner-turn-") as tmp:
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

        def turn(rel, value):
            return asyncio.run(request(rel, {"partner_turn_deg": value}))["clips"]

        a = fixture("pair__a", {})
        fixture("pair__b", {})
        shared = root / "free/pair.json"
        shared.write_text(json.dumps({"pair": True, "geometry": {"partner_shift_cm": [5, 0, -10]}}))
        fbx = a.read_bytes()
        rows = turn("pair__a.fbx", [10, -5])
        assert len(rows) == 2 and all(r["orientation"]["partner_turn_deg"] == [10, -5] for r in rows), rows
        rows = turn("pair__b.fbx", [-2.5, 1])
        assert all(r["orientation"]["partner_turn_deg"] == [7.5, -4] for r in rows)
        geo = json.loads(shared.read_text())["geometry"]
        assert geo["partner_turn_deg"] == [7.5, -4] and geo["partner_shift_cm"] == [5, 0, -10]
        turn("pair__a.fbx", [-7.5, 4])
        assert "partner_turn_deg" not in json.loads(shared.read_text())["geometry"]
        assert a.read_bytes() == fbx
        fixture("solo", {})
        try:
            turn("solo.fbx", [5, 0])
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError("a solo clip accepted a partner turn")
        for value in ([46, 0], [0, -45.5], [True, 1], ["1", 2], [1], [1, 2, 3], "bad", [float("nan"), 0]):
            before = {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
            try:
                turn("pair__a.fbx", value)
            except HTTPException as e:
                assert e.status_code == 400, (value, e)
            else:
                raise AssertionError(f"accepted invalid turn {value}")
            assert before == {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
        assert ac.read_partner_turn("x") == [0.0, 0.0]
        print("OK: cumulative partner turn, shared pair sidecar, solo refused, validation, FBX untouched")


if __name__ == "__main__":
    main()
