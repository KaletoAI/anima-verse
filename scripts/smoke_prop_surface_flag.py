#!/usr/bin/env python3
"""Smoke: prop storage-surface flag (surface.height_m), clamp, validation, auth and lean listing.

Usage:
    ./.venv/bin/python scripts/smoke_prop_surface_flag.py

Runs without the server: STORAGE_DIR and INSTANCE_DIR are pointed at a temp directory
before importing any app module or app.server. Never touches worlds/ or instance/.

Hand-derived expectations:
[a] POST /world/props/{id} with {"surface": {"height_m": 0.75}} as admin returns 200.
    get_prop(id)["surface"] == {"height_m": 0.75}; prop_surface(prop) == 0.75 when the
    variant height is 0.8 m (0.75 <= 0.8, no clamp).
[b] For a prop/variant whose height is 0.6 m with surface height 0.75 m,
    prop_surface(prop) == 0.6 (clamped to variant height_m).
[c] POST /world/props/{id} with {"surface": null} as admin returns 200;
    prop_surface(prop) is None, get_prop(id)["surface"] is None, and the sidecar
    JSON no longer contains the "surface" key.
[d] POST /world/props/{id} with {"surface": {"height_m": -1}} and {"surface": "x"}
    returns 400 each time and leaves the stored sidecar unchanged.
[e] POST /world/props/{id} as a non-admin player returns 403.
[f] The lean listing record from list_props(full=False) carries "surface"
    ({"height_m": 0.75} when set, None when cleared).
"""
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    status = "OK  " if ok else "FAIL"
    print(f"  {status} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="prop-surface-flag-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")

        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)

        from app.core.db import init_schema
        init_schema()

        from app.core import props

        # Create a 0.8 m tall table prop and a 0.6 m tall low-table prop.
        created = props.create_prop(
            name="Oak Table",
            category="table",
            width_m=1.2,
            depth_m=0.8,
            height_m=0.8,
        )
        prop_id = created["id"]

        created_low = props.create_prop(
            name="Low Coffee Table",
            category="table",
            width_m=1.0,
            depth_m=0.6,
            height_m=0.6,
        )
        low_id = created_low["id"]

        logging.disable(logging.INFO)
        from app.server import app as server_app
        from app.core import auth_dependency
        from app.core.users import create_user, get_user_by_id
        from fastapi.testclient import TestClient

        player_id = create_user("player_smoke", "smoke-password", allowed_characters=[])

        def session_user(request):
            who = request.headers.get("x-test-user", "")
            if who == "admin":
                return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
            if who == "player":
                return get_user_by_id(player_id)
            return None

        with patch.object(auth_dependency, "_get_session_user", side_effect=session_user):
            client = TestClient(server_app)

            # [a] Admin sets surface height 0.75 on 0.8 m prop
            print("[a] Admin sets surface {height_m: 0.75} on 0.8 m prop")
            r_set = client.post(
                f"/world/props/{prop_id}",
                json={"surface": {"height_m": 0.75}},
                headers={"x-test-user": "admin"},
            )
            check("[a] POST status", r_set.status_code, 200)
            rec = props.get_prop(prop_id)
            check("[a] read back surface", rec["surface"], {"height_m": 0.75})
            check("[a] prop_surface (0.8 m variant)", props.prop_surface(rec), 0.75)

            # [f] Lean listing carries "surface" while set
            print("[f] Lean listing record carries surface")
            lean_set = next(p for p in props.list_props(full=False) if p["id"] == prop_id)
            check("[f] lean listing surface when set", lean_set.get("surface"), {"height_m": 0.75})
            check("[f] lean listing has key", "surface" in lean_set, True)

            # [b] Clamp to 0.6 m variant height
            print("[b] Clamp surface height to 0.6 m variant height")
            r_low = client.post(
                f"/world/props/{low_id}",
                json={"surface": {"height_m": 0.75}},
                headers={"x-test-user": "admin"},
            )
            check("[b] POST low prop status", r_low.status_code, 200)
            low_rec = props.get_prop(low_id)
            check("[b] prop_surface clamped to 0.6", props.prop_surface(low_rec), 0.6)

            # [d] Invalid payloads -> 400 and sidecar unchanged
            print("[d] Invalid payloads rejected with 400, sidecar unchanged")
            before_sidecar = props.read_sidecar(prop_id, read_only=True)
            r_neg = client.post(
                f"/world/props/{prop_id}",
                json={"surface": {"height_m": -1}},
                headers={"x-test-user": "admin"},
            )
            check("[d] negative height_m -> 400", r_neg.status_code, 400)
            check("[d] sidecar unchanged after -1", props.read_sidecar(prop_id, read_only=True), before_sidecar)

            r_str = client.post(
                f"/world/props/{prop_id}",
                json={"surface": "x"},
                headers={"x-test-user": "admin"},
            )
            check("[d] string 'x' -> 400", r_str.status_code, 400)
            check("[d] sidecar unchanged after 'x'", props.read_sidecar(prop_id, read_only=True), before_sidecar)

            # [e] Player -> 403
            print("[e] Player POST refused with 403")
            r_player = client.post(
                f"/world/props/{prop_id}",
                json={"surface": {"height_m": 0.5}},
                headers={"x-test-user": "player"},
            )
            check("[e] player POST -> 403", r_player.status_code, 403)
            check("[e] sidecar unchanged after player", props.read_sidecar(prop_id, read_only=True), before_sidecar)

            # [c] Null clears flag and removes key from sidecar
            print("[c] Clear surface with null")
            r_clear = client.post(
                f"/world/props/{prop_id}",
                json={"surface": None},
                headers={"x-test-user": "admin"},
            )
            check("[c] POST clear status", r_clear.status_code, 200)
            cleared_rec = props.get_prop(prop_id)
            check("[c] prop_surface is None", props.prop_surface(cleared_rec), None)
            check("[c] get_prop surface is None", cleared_rec["surface"], None)
            cleared_sidecar = props.read_sidecar(prop_id, read_only=True)
            check("[c] no 'surface' key in sidecar", "surface" not in cleared_sidecar, True)

            lean_cleared = next(p for p in props.list_props(full=False) if p["id"] == prop_id)
            check("[f] lean listing surface when cleared", lean_cleared.get("surface"), None)
            check("[f] lean listing still has key when cleared", "surface" in lean_cleared, True)

    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
