#!/usr/bin/env python3
"""Exercise kit routes against temporary storage without any LLM or mesh service.

Run outside the Codex sandbox: its FastAPI TestClient transport can hang.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="furnish-kit-routes-") as temporary:
        root = Path(temporary)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        from app.server import app
        from fastapi.testclient import TestClient
        from app.core import furniture_kits, props, room_furnish, users
        from app.models.world import (
            GROUND_ROOM_ID, _load_world_data, _save_world_data,
            add_location, get_location_by_id, get_room_by_id,
        )

        users.create_user("kit-admin", "smoke-password", role="admin")
        client = TestClient(app)
        assert client.post("/auth/login", json={
            "username": "kit-admin", "password": "smoke-password"}).status_code == 200
        location = add_location("Kit house", "A furnishing fixture", rooms=[{
            "id": "kit-bedroom", "name": "Bedroom", "description": "",
            "indoor": "indoor", "activities": []}])
        data = _load_world_data()
        for entry in data["locations"]:
            if entry["id"] == location["id"]:
                entry["map3d"] = {"plan_width_m": 8.0, "storey_height_m": 3.0}
                room = next(r for r in entry["rooms"] if r["id"] == "kit-bedroom")
                room["layout"] = {
                    "x": 0.0, "y": 0.0, "w": 4.5, "d": 4.0, "level": 0,
                    "openings": [{"edge": 2, "at": 0.5, "width_m": 0.9,
                                  "height_m": 2.1, "type": "door"}]}
        _save_world_data(data)
        ids = {}
        for role, dims in {
            "bed": (1.4, 2.0, 0.6), "nightstand": (0.4, 0.4, 0.5),
            "rug": (1.8, 2.4, 0.02), "wardrobe": (0.8, 0.5, 1.8),
            "ceiling_light": (0.3, 0.3, 0.2),
        }.items():
            ids[role] = props.create_prop(
                name=role, category="furniture", width_m=dims[0],
                depth_m=dims[1], height_m=dims[2],
                mount="ceiling" if role == "ceiling_light" else "floor",
                tags=["kit:rustic", f"role:{role}"])["id"]
        base = "/world/rooms/kit-bedroom/furnish"
        body = {"kit": "rustic", "room_type": "bedroom"}

        def ready():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                status = room_furnish.get_status("kit-bedroom")
                if status and status["state"] in ("review_ready", "error") and not status["running"]:
                    assert status["state"] == "review_ready", status
                    return status
                time.sleep(0.02)
            raise AssertionError("Kit job did not reach review_ready")

        def room_props():
            room = get_room_by_id(get_location_by_id(location["id"]), "kit-bedroom")
            return room["layout"].get("props") or []

        with patch.object(room_furnish, "_llm_json", side_effect=AssertionError("Kit called LLM")) as llm:
            yard = room_furnish.ground_job_id(location["id"])
            for target, request in (
                (yard, body), (GROUND_ROOM_ID, body),
                ("kit-bedroom", {**body, "kit": "unknown"}),
                ("kit-bedroom", {**body, "room_type": "unknown"}),
                ("kit-bedroom", {**body, "kit": "modern"}),
            ):
                response = client.post(f"/world/rooms/{target}/furnish/kit", json=request)
                assert response.status_code == 400, response.text
                assert room_furnish._get_row(target) is None

            assert client.post(base + "/kit", json=body).status_code == 200
            status = ready()
            assert status["placements"]["placed"]
            used = {p["prop_id"] for p in status["placements"]["placed"]}
            used.update(p["name"] for p in status["placements"]["unplaced"])
            assert {n["prop_id"] for n in status["proposal"]["needs"]} == used
            assert set(status["placements"]) == {"placed", "unplaced", "phase_counts", "missing_roles"}
            assert client.post(base + "/kit", json=body).status_code == 409
            before = room_props()
            prop_count = len(props.list_props())
            response = client.post(base + "/accept")
            assert response.status_code == 200, response.text
            accepted = response.json()
            assert accepted["generating"] == 0
            assert len(room_props()) == len(before) + len(status["placements"]["placed"])
            assert room_props()[:len(before)] == before
            assert len(props.list_props()) == prop_count
            assert room_furnish.get_status("kit-bedroom") is None

            # Persist a placing job with stale prop ids: resume must use the
            # current library and atomically refresh needs with placements.
            loc, room = room_furnish._load_room("kit-bedroom")
            geom = room_furnish._geometry(loc, room)
            planned = furniture_kits.plan_room(**body, geom=geom,
                library=room_furnish._library(), room_id="kit-bedroom")
            planned["needs"][0]["prop_id"] = "stale-prop"
            room_furnish._insert_row("kit-bedroom", location["id"])
            room_furnish._update_row("kit-bedroom", state="placing", proposal={
                "needs": planned["needs"], "surfaces": None, "dropped": [], "kit": body})
            assert room_furnish._resume_phase(room_furnish._get_row("kit-bedroom")) == "place"
            library = room_furnish._library()
            library.pop(ids["rug"])
            with patch.object(room_furnish, "_library", return_value=library):
                room_furnish.resume("kit-bedroom")
                status = ready()
            placements = status["placements"]
            assert placements["missing_roles"] == ["rug"], placements
            used = {p["prop_id"] for p in placements["placed"]}
            used.update(p["name"] for p in placements["unplaced"])
            assert ids["rug"] not in used
            assert {n["prop_id"] for n in status["proposal"]["needs"]} == used
            assert status["proposal"]["kit"] == body
            assert all(not n["build"] for n in status["proposal"]["needs"])
            assert room_props()[:len(before)] == before
            room_furnish.discard("kit-bedroom")
            building = add_location("Kit building", "Bulk fixture", rooms=[
                {"id": "bulk-bedroom", "name": "Bedroom"},
                {"id": "bulk-kitchen", "name": "Kitchen"},
                {"id": "bulk-untyped", "name": "Raum 3"},
                {"id": "bulk-job", "name": "Bedroom"},
                {"id": "bulk-no-layout", "name": "Bedroom"},
            ])
            data = _load_world_data()
            for loc in data["locations"]:
                if loc["id"] != building["id"]:
                    continue
                for room in loc["rooms"]:
                    if room["id"].startswith("bulk-") and room["id"] != "bulk-no-layout":
                        room["layout"] = {"x": 0, "y": 0, "w": 6, "d": 6, "level": 0}
                    if room["id"] == "bulk-kitchen":
                        room["layout"]["props"] = [{"prop_id": ids["bed"], "at": [1, 1]}]
            _save_world_data(data)
            location_url = f"/world/locations/{building['id']}"
            saved = get_location_by_id(building["id"])
            get_room_by_id(saved, "bulk-bedroom")["room_type"] = "study"
            response = client.put(location_url, json=saved)
            assert response.status_code == 200, response.text
            saved = get_location_by_id(building["id"])
            assert get_room_by_id(saved, "bulk-bedroom")["room_type"] == "study"
            get_room_by_id(saved, "bulk-bedroom")["room_type"] = ""
            response = client.put(location_url, json=saved)
            assert response.status_code == 200, response.text
            saved = get_location_by_id(building["id"])
            assert get_room_by_id(saved, "bulk-bedroom")["room_type"] == ""
            assert furniture_kits.room_type_of(get_room_by_id(saved, "bulk-bedroom")) == "bedroom"
            room_furnish._insert_row("bulk-job", building["id"])
            bulk_url = location_url + "/furnish-kit"
            snapshot = get_location_by_id(building["id"])
            response = client.post(bulk_url, json={"kit": "rustic", "dry_run": True})
            assert response.status_code == 200, response.text
            preview = response.json()
            assert [r["room_id"] for r in preview["rooms"]] == ["bulk-bedroom"]
            assert preview["rooms"][0]["placed"] > 0
            assert get_location_by_id(building["id"]) == snapshot
            expected = {"bulk-kitchen": "has_furniture", "bulk-untyped": "no_room_type",
                        "bulk-job": "job_open", "bulk-no-layout": "no_layout"}
            assert {r["room_id"]: r["reason"] for r in preview["skipped"]} == expected
            response = client.post(bulk_url, json={"kit": "rustic", "dry_run": False})
            assert response.status_code == 200, response.text
            written = response.json()
            assert written == preview
            saved = get_location_by_id(building["id"])
            assert get_room_by_id(saved, "bulk-bedroom")["layout"]["props"] == written["rooms"][0]["placements"]
            assert get_room_by_id(saved, "bulk-kitchen") == get_room_by_id(snapshot, "bulk-kitchen")
            response = client.post(bulk_url, json={"kit": "rustic", "dry_run": False})
            assert response.status_code == 200, response.text
            assert response.json()["rooms"] == []
            assert {r["room_id"]: r["reason"] for r in response.json()["skipped"]} == {
                **expected, "bulk-bedroom": "has_furniture"}
            assert client.post(bulk_url, json={"kit": "unknown"}).status_code == 400
            assert client.post("/world/locations/missing/furnish-kit", json={"kit": "rustic"}).status_code == 404
            room_furnish.discard("bulk-job")
            llm.assert_not_called()
        client.close()
    print("all kit route checks passed")


if __name__ == "__main__":
    main()
