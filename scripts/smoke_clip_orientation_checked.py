#!/usr/bin/env python3
"""The place check of the Library preview, stored in the clip sidecar
(Ruling A110 D3/D4): ``orientation.checked = {at, prop, place, dyaw, dpos}``,
written only when every figure reads green and cleared by the next bake.
No Blender, no real clips, no world DB.

Usage: ./.venv/bin/python scripts/smoke_clip_orientation_checked.py

Hand derivation (D4 green = |dyaw| <= 3 deg and dpos <= 2 cm):
  [1] {dyaw 2.96, dpos 1.6}      -> stored, rounded 2.96 / 1.6, `at` set
      {dyaw -3.0, dpos 2.0}      -> stored (the bounds are inclusive)
      {dyaw 3.1}  / {dpos 2.01} / {dpos NaN} / no prop -> 400, nothing written
  [2] a check alone (all dials 0) through the orient route -> sidecar
      geometry.checked == the check, the listing's orientation.checked too,
      the FBX bytes untouched (dummy bytes make a Blender call fail)
  [3] a shift-only orient WITHOUT a check -> geometry.checked is gone
      (shift [5, 0] + [0, 0] -> shift_cm [5, 0]); the same orient WITH a
      check -> the new check is stored by that one write, shift [10, 0].
  [4] a pair: the check lands in the shared <kind>.json, addressed through
      either half.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix="clip-orient-checked-") as tmp:
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
            if meta is not None:
                p.with_suffix(".json").write_text(json.dumps(meta))
            return p

        async def request(rel, body):
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            req = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
            return await assets.post_animation_clip_orient("free", rel, req, _={})

        def post(rel, body):
            return asyncio.run(request(rel, body))

        def refused(rel, body):
            try:
                post(rel, body)
            except HTTPException as e:
                return e.status_code
            return None

        def geometry(p):
            return json.loads(p.read_text())["geometry"]

        print("[1] validation")
        got = ac.validate_orientation_check({"prop": "bench", "place": "p/m1 A", "dyaw": 2.96, "dpos": 1.6})
        check("green stored", got["dyaw"] == 2.96 and got["dpos"] == 1.6 and got["prop"] == "bench", str(got))
        check("`at` set", isinstance(got.get("at"), str) and "T" in got["at"], str(got.get("at")))
        edge = ac.validate_orientation_check({"prop": "b", "place": "A", "dyaw": -3.0, "dpos": 2.0})
        check("bounds inclusive", edge["dyaw"] == -3.0 and edge["dpos"] == 2.0)
        solo = fixture("rest", {"geometry": {"root_motion": {"mode": "strip"}}})
        before = solo.with_suffix(".json").read_text()
        for bad in ({"prop": "b", "place": "A", "dyaw": 3.1, "dpos": 0},
                    {"prop": "b", "place": "A", "dyaw": 0, "dpos": 2.01},
                    {"prop": "b", "place": "A", "dyaw": 0, "dpos": math.nan},
                    {"place": "A", "dyaw": 0, "dpos": 0}):
            code = refused("rest.fbx", {"checked": bad})
            check(f"refused {bad}", code == 400, str(code))
        check("nothing written on refusal", solo.with_suffix(".json").read_text() == before)

        print("[2] a check alone")
        original = solo.read_bytes()
        rows = post("rest.fbx", {"checked": {"prop": "bench", "place": "A", "dyaw": 1.2, "dpos": 0.8}})["clips"]
        g = geometry(solo.with_suffix(".json"))
        check("sidecar geometry.checked", g.get("checked", {}).get("place") == "A" and g["checked"]["dyaw"] == 1.2,
              str(g.get("checked")))
        check("answer orientation.checked", rows[0]["orientation"]["checked"] == g["checked"])
        listed = [c for c in assets.list_animation_clips()["clips"] if c["kind"] == "rest"]
        check("listing orientation.checked", listed and listed[0]["orientation"]["checked"] == g["checked"])
        check("FBX untouched", solo.read_bytes() == original)

        print("[3] the next bake clears it")
        post("rest.fbx", {"shift_cm": [5, 0]})
        g = geometry(solo.with_suffix(".json"))
        check("cleared by a bake without a check", "checked" not in g, str(g.get("checked")))
        check("shift [5, 0]", g.get("shift_cm") == [5, 0], str(g.get("shift_cm")))
        rows = post("rest.fbx", {"shift_cm": [5, 0],
                                 "checked": {"prop": "sofa", "place": "B", "dyaw": -0.4, "dpos": 1.1}})["clips"]
        g = geometry(solo.with_suffix(".json"))
        check("new check stored with the bake", g.get("checked", {}).get("prop") == "sofa", str(g.get("checked")))
        check("shift [10, 0]", g.get("shift_cm") == [10, 0], str(g.get("shift_cm")))
        check("a listing view without a check reads None",
              ac.clip_view({"kind": "x", "role": "", "set": "", "source": "free", "rel": "x.fbx",
                            "path": fixture("x", None)})["orientation"]["checked"] is None)

        print("[4] a pair: the shared sidecar")
        fixture("pair__a", None)
        fixture("pair__b", None)
        shared = root / "free/pair.json"
        shared.write_text(json.dumps({"pair": True, "geometry": {"roles": {}}}))
        post("pair__b.fbx", {"checked": {"prop": "bench", "place": "A+B", "dyaw": 0, "dpos": 0}})
        check("shared <kind>.json", geometry(shared).get("checked", {}).get("place") == "A+B")
    print(f"{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'smoke_clip_orientation_checked: all OK'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
