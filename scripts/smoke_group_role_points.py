#!/usr/bin/env python3
"""The server places a group's members where the clients draw them.

Usage: ./.venv/bin/python scripts/smoke_group_role_points.py

``interaction_engine.start_interaction_at`` writes every member's game-state
position as ``anchor + _rotate(anchor_xz_m of its role, yaw)`` (§ A8a). The
clients draw each figure at the same point from the same root (the hand
derivation of the numbers is the section below). This reads the SAME vector
file, ``shared/test-vectors/group_role_points.json``, and checks every x/z
case against the server's rotation: three roles at yaw 90°, five at yaw 180°.
No world, no server — ``_rotate`` is pure.

Hand derivation (moved from client3d/scripts/smoke_group_role_points.mjs @ 011cd048aa3cc2937186d7f35d2203af9491db8a),
word for word; the browser smoke still replays the whole vector, the native
PairVectorTests do too, this smoke checks the x/z cases against the server:

    /**
     * Group role points (G3, plan-gruppen-animationen.md; schnittstellen-3d.md § A8a):
     * where a figure of a 3- or 5-person clip stands — the shared vectors
     * `shared/test-vectors/group_role_points.json`, run through the full
     * `NpcManager` tick (the same adapter as the pair vectors).
     *
     * Usage: timeout 300 node client3d/scripts/smoke_group_role_points.mjs
     *
     * THE RULE (§ A8a). Every member plays ITS OWN half `<kind>__<role>` at the ONE
     * anchor of the group; its world point is anchor + R(yaw)·root, with
     *   x = ax + rx·cos(yaw) + rz·sin(yaw),   z = az − rx·sin(yaw) + rz·cos(yaw)
     * (`interaction_engine._rotate`, the server's own placement of the members —
     * `scripts/smoke_group_role_points.py` checks the server against these same
     * numbers). Height: without a place the ground under the figure (0.5 here),
     * on a place its slot height for EVERY role (the group holds one place).
     * Anchor (10, 22) in every case.
     *
     * [1] THREE, yaw = 90° (cos 0, sin 1): x = 10 + rz, z = 22 − rx. Roots at the
     *     anchor frame around the centroid: a (−0.6, 0), b (0.3, 0.52),
     *     c (0.3, −0.52) — they sum to 0. a -> (10, 22.6); b -> (10.52, 21.7);
     *     c -> (9.48, 21.7). The library stand-in answers a root ONLY for the case's
     *     own half, so a figure asking for another role's clip is not placed and
     *     the case fails — each role reads its own root.
     * [2] FIVE, yaw = 180° (cos −1, sin 0): x = 10 − rx, z = 22 − rz. a (−0.8, 0),
     *     b (0.4, 0), c (0, 0.5), d (0.2, −0.5), e (0.2, 0) — sum 0.
     *     a -> (10.8, 22); b -> (9.6, 22); c -> (10, 21.5); d -> (9.8, 22.5);
     *     e -> (9.8, 22). y = 0.5 for all (no place).
     * [3] The five on a place (place p1, slot height 0.45): role e stands at
     *     (9.8, 0.45, 22) — the slot height, not the ground's 0.5.
     */
"""
import json
import math
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# _rotate is pure, but its module reaches the world DB: point storage at a
# throwaway directory before importing it (smoke_scripts_storage_lint).
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="smoke_group_role_points_"))
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
