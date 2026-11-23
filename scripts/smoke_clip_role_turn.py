#!/usr/bin/env python3
"""Owner decisions 2026-11-23 on the server side of Auto-align: every role's renderer-only turn ``role_turn_deg``
{role: [tilt, roll, yaw]} (replacing partner B's ``partner_turn_deg`` / ``partner_yaw_deg``), its one-time boot
migration, the clip's rotation range ``align_turn_deg`` and the clip's alignment status ``align_status`` — no Blender,
no real clips, no world DB.

Usage: ./.venv/bin/python scripts/smoke_clip_role_turn.py

Hand derivation:
  [1] orient {b: [10, -5, 150]} then {b: [-2.5, 1, 60]}: tilt 10 − 2.5 = 7.5, roll −5 + 1 = −4, yaw 150 + 60 = 210 →
      wrapped −150 (each value cumulative and wrapped to (−180, 180]); both halves of the pair list the same book;
      {a: [0, 0, 90]} adds role a beside b; {a: [0, 0, -90]} removes a again (back at zero). The role shift beside it
      stays. Dummy FBX bytes make an accidental Blender run fail; they stay unchanged.
  [2] refused with 400 and nothing written: a solo clip; role c on a pair (no such half); 181 / −180.5 / a boolean /
      a string / two numbers / NaN / role "f"; and the gone fields partner_turn_deg and partner_yaw_deg.
  [3] the migration: geometry partner_turn_deg [3, 4] + partner_yaw_deg 200 → role_turn_deg.b [3, 4, −160]
      (200 wrapped); with role_turn_deg.b [1, 0, 0] already there → [4, 4, −160]; align_applied.turn_deg [1, 2] →
      align_applied.role_turn_deg.b [1, 2, 0]; the second run changes 0 files.
  [4] align_turn_deg: the default {deg 45, source default}; 60 → {60, clip}; 0 → {0, clip} (shift only); null → the
      default; 181, −1, true, "9" → 400.
  [5] align_status: relation k1 {auto_blocked, overlap, depth_mm [1, 2]} → summary auto_blocked; k2 auto_aligned beside
      it → still auto_blocked (the worst, ALIGN_STATE_ORDER); done true → done with a done_at; a later relations write
      (k1 → auto_improved) keeps done and done_at and the summary becomes auto_improved (k2 aligned is better); k1 null
      → only k2, summary auto_aligned; (owner rules of 2026-11-23 evening) k3 {auto_unchanged, notes [little_depth,
      no_change], stroke_mm 12.04} → summary auto_unchanged (worse than aligned), stored notes and stroke_mm 12.0; k4
      {auto_blocked, root_overlap, with "B", notes [shallower], shallower_mm 7, root_pulled true} → summary auto_blocked
      with "with" B; k5 {auto_blocked, root_support} stored; all three removed again → auto_aligned; refused: the gone reasons root_inside / nothing_to_gain, "with"
      on an overlap, a lower-case "b", an unknown note, a note twice, root_pulled "yes";
      a reason not of its state, an unknown state, depth_mm of one number → 400;
      after reloading the caches the listing still shows it; a solo clip has none (null).
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="clip-role-turn-") as tmp:
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

        def fixture(stem, meta=None):
            p = root / "free" / f"{stem}.fbx"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"never rewrite this FBX")
            if meta is not None:   # a pair's halves read their shared <kind>.json
                p.with_suffix(".json").write_text(json.dumps(meta))
            return p

        def call(fn, rel, body):
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            req = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
            return asyncio.run(fn("free", rel, req, _={}))["clips"]

        def orient(rel, body):
            return call(assets.post_animation_clip_orient, rel, body)

        def patch(rel, body):
            return call(assets.patch_animation_clip, rel, body)

        def refused(fn, rel, body):
            before = {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}
            try:
                fn(rel, body)
            except HTTPException as e:
                assert e.status_code == 400, (body, e)
            else:
                raise AssertionError(f"accepted {body}")
            assert before == {str(p): p.read_bytes() for p in (root / "free").rglob("*") if p.is_file()}, body

        # [1]
        a = fixture("pair__a")
        fixture("pair__b")
        shared = root / "free/pair.json"
        shared.write_text(json.dumps({"pair": True, "geometry": {"role_shift_cm": {"b": [5, 0, -10]}}}))
        fbx = a.read_bytes()
        rows = orient("pair__a.fbx", {"role_turn_deg": {"b": [10, -5, 150]}})
        assert len(rows) == 2 and all(r["orientation"]["role_turn_deg"] == {"b": [10, -5, 150]} for r in rows), rows
        rows = orient("pair__b.fbx", {"role_turn_deg": {"b": [-2.5, 1, 60]}})
        assert all(r["orientation"]["role_turn_deg"] == {"b": [7.5, -4, -150]} for r in rows), rows
        rows = orient("pair__a.fbx", {"role_turn_deg": {"a": [0, 0, 90]}})
        assert rows[0]["orientation"]["role_turn_deg"] == {"a": [0, 0, 90], "b": [7.5, -4, -150]}, rows
        orient("pair__a.fbx", {"role_turn_deg": {"a": [0, 0, -90]}})
        geo = json.loads(shared.read_text())["geometry"]
        assert geo["role_turn_deg"] == {"b": [7.5, -4, -150]} and geo["role_shift_cm"] == {"b": [5, 0, -10]}, geo
        assert a.read_bytes() == fbx
        # [2]
        fixture("solo", {})
        refused(orient, "solo.fbx", {"role_turn_deg": {"a": [5, 0, 0]}})
        for value in ({"c": [1, 0, 0]}, {"b": [181, 0, 0]}, {"b": [0, -180.5, 0]}, {"b": [True, 0, 0]},
                      {"b": ["1", 0, 0]}, {"b": [1, 2]}, {"b": [float("nan"), 0, 0]}, {"f": [1, 0, 0]}, [1, 2, 3]):
            refused(orient, "pair__a.fbx", {"role_turn_deg": value})
        refused(orient, "pair__a.fbx", {"partner_turn_deg": [1, 0]})
        refused(orient, "pair__a.fbx", {"partner_yaw_deg": 10})
        # [3]
        (root / "free/old").mkdir()
        old = root / "free/old/legacy.json"
        old.write_text(json.dumps({"pair": True, "geometry": {"partner_turn_deg": [3, 4], "partner_yaw_deg": 200},
                                   "align_applied": {"role_shift_cm": {"b": [1, 0, 0]}, "turn_deg": [1, 2]}}))
        both = root / "free/old/both.json"
        both.write_text(json.dumps({"pair": True, "geometry": {"partner_turn_deg": [3, 4], "partner_yaw_deg": 200,
                                                               "role_turn_deg": {"b": [1, 0, 0]}}}))
        assert ac.migrate_partner_turn_roles() == 2
        d = json.loads(old.read_text())
        assert d["geometry"] == {"role_turn_deg": {"b": [3, 4, -160]}}, d
        assert d["align_applied"] == {"role_shift_cm": {"b": [1, 0, 0]}, "role_turn_deg": {"b": [1, 2, 0]}}, d
        assert json.loads(both.read_text())["geometry"] == {"role_turn_deg": {"b": [4, 4, -160]}}
        assert ac.migrate_partner_turn_roles() == 0
        # [4]
        assert ac.clip_align_turn({}) == {"deg": 45.0, "source": "default"}
        rows = patch("pair__a.fbx", {"align_turn_deg": 60})
        assert all(r["align_turn"] == {"deg": 60, "source": "clip"} for r in rows), rows
        assert patch("pair__b.fbx", {"align_turn_deg": 0})[0]["align_turn"] == {"deg": 0, "source": "clip"}
        assert patch("pair__a.fbx", {"align_turn_deg": None})[0]["align_turn"] == {"deg": 45, "source": "default"}
        for value in (181, -1, True, "9"):
            refused(patch, "pair__a.fbx", {"align_turn_deg": value})
        # [5]
        rows = patch("pair__a.fbx", {"align_status": {"relations": {
            "a>b:mouth": {"state": "auto_blocked", "reason": "overlap", "depth_mm": [1, 2]}}}})
        st = rows[0]["align_status"]
        assert st["summary"] == "auto_blocked" and st["relations"]["a>b:mouth"]["depth_mm"] == [1, 2], st
        assert st["relations"]["a>b:mouth"]["at"] and st["done"] is False, st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"b>a:hand": {"state": "auto_aligned"}}}})[0]["align_status"]
        assert st["summary"] == "auto_blocked" and set(st["relations"]) == {"a>b:mouth", "b>a:hand"}, st
        st = patch("pair__b.fbx", {"align_status": {"done": True}})[0]["align_status"]
        assert st["done"] is True and st["done_at"], st
        done_at = st["done_at"]
        st = patch("pair__a.fbx", {"align_status": {"relations": {"a>b:mouth": {"state": "auto_improved"}}}})[0]["align_status"]
        assert st["done"] is True and st["done_at"] == done_at and st["summary"] == "auto_improved", st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"a>b:mouth": None}}})[0]["align_status"]
        assert set(st["relations"]) == {"b>a:hand"} and st["summary"] == "auto_aligned", st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"k3": {
            "state": "auto_unchanged", "notes": ["little_depth", "no_change"], "stroke_mm": 12.04}}}})[0]["align_status"]
        assert st["summary"] == "auto_unchanged", st
        assert st["relations"]["k3"]["notes"] == ["little_depth", "no_change"] and st["relations"]["k3"]["stroke_mm"] == 12.0, st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"k4": {
            "state": "auto_blocked", "reason": "root_overlap", "with": "B", "notes": ["shallower"], "shallower_mm": 7,
            "root_pulled": True}}}})[0]["align_status"]
        k4 = st["relations"]["k4"]
        assert st["summary"] == "auto_blocked" and k4["with"] == "B" and k4["root_pulled"] is True and k4["shallower_mm"] == 7.0, st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"k5": {"state": "auto_blocked", "reason": "root_support"}}}})[0]["align_status"]
        assert st["relations"]["k5"]["reason"] == "root_support", st
        st = patch("pair__a.fbx", {"align_status": {"relations": {"k3": None, "k4": None, "k5": None}}})[0]["align_status"]
        assert st["summary"] == "auto_aligned", st
        for value in ({"relations": {"k": {"state": "auto_blocked", "reason": "root_inside"}}},
                      {"relations": {"k": {"state": "auto_blocked", "reason": "nothing_to_gain"}}},
                      {"relations": {"k": {"state": "auto_blocked", "reason": "overlap", "with": "B"}}},
                      {"relations": {"k": {"state": "auto_blocked", "reason": "root_overlap", "with": "b"}}},
                      {"relations": {"k": {"state": "auto_improved", "notes": ["deep"]}}},
                      {"relations": {"k": {"state": "auto_improved", "notes": ["shallower", "shallower"]}}},
                      {"relations": {"k": {"state": "auto_improved", "root_pulled": "yes"}}},
                      {"relations": {"k": {"state": "auto_blocked", "reason": "no_place"}}},
                      {"relations": {"k": {"state": "great"}}},
                      {"relations": {"k": {"state": "auto_improved", "depth_mm": 3}}}, {"done": "yes"}, {"other": 1}):
            refused(patch, "pair__a.fbx", {"align_status": value})
        ac.reload_clip_caches()
        listed = [ac.clip_view(e) for e in ac.clip_entries() if e["kind"] == "pair"]
        assert len(listed) == 2, listed
        st = json.loads(shared.read_text())["align_status"]
        assert st["done"] is True and set(st["relations"]) == {"b>a:hand"}, st
        for r in listed:
            assert r["align_status"]["summary"] == "auto_aligned" and r["align_status"]["done"] is True, r
        refused(patch, "solo.fbx", {"align_status": {"done": True}})
        assert a.read_bytes() == fbx
        print(f"OK: role turns cumulative + wrapped, refusals, migration, rotation range, status "
              f"(listing rows checked: {len(listed)})")


if __name__ == "__main__":
    main()
