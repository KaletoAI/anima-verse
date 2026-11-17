#!/usr/bin/env python3
"""Smoke: backfill_clip_turn --write refuses a running server and replaces sidecars atomically.

Usage: ./.venv/bin/python scripts/smoke_backfill_clip_turn.py

No Blender, no world: both clip libraries are temp dirs (ANIMATION_CLIPS_DIR /
ANIMATION_CLIPS_LICENSED_DIR) and ``runner.run`` is replaced by a fake that measures
turn_deg = 12.5. One sidecar ``walk.json`` (mode 0o644) with root_motion
{"mode": "keep", "turn_deg": 0}.

By hand:
[1] ``--write`` while config_history._server_running says True -> argparse error
    (SystemExit 2) BEFORE any measurement: the fake runner was never called, the
    sidecar bytes are unchanged.
[2] ``--write`` with no server -> exit 0; walk.json's turn_deg is 12.5, its mode is
    still 0o644, it is a NEW inode (replaced, not truncated in place — the old code's
    write_text kept the inode, so a concurrent reader could see a half-written file),
    and no ``.walk.json.*.tmp`` sibling is left.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="backfill-turn-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(TMP / "licensed")
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_clip_turn as bf  # noqa: E402
import config_history  # noqa: E402

FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
        print("FAIL:", msg)


(TMP / "clips").mkdir()
(TMP / "licensed").mkdir()
side = TMP / "clips" / "walk.json"
side.write_text(json.dumps({"kind": "walk", "geometry": {"root_motion": {"mode": "keep", "turn_deg": 0}}}))
os.chmod(side, 0o644)
(TMP / "clips" / "walk.fbx").write_bytes(b"FBX")
before = side.read_bytes()
calls = []


def fake_run(name, **kw):
    calls.append(name)
    return {"ok": True, "data": {"turn_deg": 12.5}}


# [1]
with patch.object(config_history, "_server_running", return_value=True), \
        patch.object(bf.runner, "run", fake_run), patch.object(sys, "argv", ["backfill", "--write"]):
    try:
        bf.main()
        check(False, "[1] --write ran although the server is up")
    except SystemExit as e:
        check(e.code == 2, f"[1] exit code {e.code}")
check(calls == [], f"[1] measured although refused: {calls}")
check(side.read_bytes() == before, "[1] sidecar changed although refused")

# [2] (reset first, so [2] stands on its own even where [1] wrote)
side.write_bytes(before)
inode = side.stat().st_ino
with patch.object(config_history, "_server_running", return_value=False), \
        patch.object(bf.runner, "run", fake_run), patch.object(sys, "argv", ["backfill", "--write"]):
    rc = bf.main()
check(rc == 0, f"[2] rc {rc}")
meta = json.loads(side.read_text())
check(meta["geometry"]["root_motion"]["turn_deg"] == 12.5, f"[2] turn_deg {meta}")
check(side.stat().st_mode & 0o777 == 0o644, f"[2] mode {oct(side.stat().st_mode & 0o777)}")
check(side.stat().st_ino != inode, "[2] sidecar rewritten in place (same inode)")
check(not list((TMP / "clips").glob(".walk.json.*")), "[2] staged temp left behind")

print("FAILED" if FAIL else "OK backfill_clip_turn refuses a running server, replaces sidecars atomically")
sys.exit(1 if FAIL else 0)
