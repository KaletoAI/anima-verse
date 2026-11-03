#!/usr/bin/env python3
"""The server places a group's members where the clients draw them.

Usage: ./.venv/bin/python scripts/smoke_group_role_points.py

``interaction_engine.start_interaction_at`` writes every member's game-state
position as ``anchor + _rotate(anchor_xz_m of its role, yaw)`` (§ A8a). The
clients draw each figure at the same point from the same root
(``client3d/scripts/smoke_group_role_points.mjs``, whose docstring derives the
numbers by hand). This reads the SAME vector file,
``shared/test-vectors/group_role_points.json``, and checks every x/z case
against the server's rotation: three roles at yaw 90°, five at yaw 180°.
No world, no server — ``_rotate`` is pure.
"""
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.interaction_engine import _rotate  # noqa: E402


def main():
    doc = json.loads((REPO / "shared/test-vectors/group_role_points.json").read_text())
    base = doc["fixtures"]["group"]
    checked = 0
    for case in doc["cases"]:
        ref, field = case["args"]
        if field not in ("x", "z"):
            continue
        data = dict(base, **ref.get("$with", {}))
        anchor, root = data["anchor"], data["root"]
        dx, dz = _rotate(float(root["x"]), float(root["z"]), float(anchor["yaw"]))
        got = anchor["x"] + dx if field == "x" else anchor["z"] + dz
        assert math.isclose(got, case["expect"], abs_tol=case.get("eps", 1e-9)), (case["label"], got)
        checked += 1
    assert checked >= 16, checked
    print(f"PASS: the server's member points match {checked} client vector cases")


if __name__ == "__main__":
    main()
