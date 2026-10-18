"""Hull HTTP contract and one-call proposal, without a running server.

The fixture has two levels and a 10 by 8 metre ground outline: prompt facts
must therefore be 2 storeys, length 10, depth 8. Unknown styles are 400,
oversize hulls 400, missing records 404, missing outlines and busy jobs 409, absent Blender 503.
Usage: ./.venv/bin/python scripts/smoke_hull_routes.py
"""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    """Exercise real routes, persistence, authentication and proposal fallback."""
    with tempfile.TemporaryDirectory(prefix="hull-routes-") as temporary:
        root = Path(temporary)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        from app.server import app
        from fastapi.testclient import TestClient
        from app.core import hull_model, hull_styles, users
        from app.models.world import upsert_location
        from _hull_fixtures import stepped_house, without_outline

        users.create_user("hull-admin", "smoke-password", role="admin")
        users.create_user("hull-player", "smoke-password", role="user")
        client, player = TestClient(app), TestClient(app)
        for session, username in ((client, "hull-admin"), (player, "hull-player")):
            assert session.post("/auth/login", json={
                "username": username, "password": "smoke-password"}).status_code == 200
        location = stepped_house()
        location["name"] = "Hull route house"
        assert upsert_location(location, sync_world=False)
        empty = without_outline()
        empty["id"] = "no-outline"
        assert upsert_location(empty, sync_world=False)
        base = f"/world/locations/{location['id']}/hull"
        assert client.get(base).json()["styles"]
        assert client.get("/world/locations/missing/hull").status_code == 404
        assert client.get("/world/locations/no-outline/hull").json()["error"] == "no_outline"
        assert player.get(base).status_code == 200
        detail = "This location has no building outline — draw one in the floor plan editor first."
        for action in ("propose", "generate"):
            response = client.post(f"/world/locations/no-outline/hull/{action}", json={"description": {}})
            assert (response.status_code, response.json()["detail"]) == (409, detail)
            assert client.post(f"/world/locations/missing/hull/{action}", json={"description": {}}).status_code == 404
        with patch("app.core.llm_router.llm_call", side_effect=RuntimeError("unrouted")) as call:
            proposal = client.post(base + "/propose").json()
            assert proposal["description_json"]["style"] in hull_styles.load_styles()
            assert proposal["description_json"]["overrides"] == {"ornament_density": 0.5}
            assert proposal["llm"] is False
            assert call.call_count == 1
        with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(
                content='{"style":"burg","overrides":{"pitch_deg":999}}')) as call:
            proposal = hull_model.propose_hull(location["id"])
            assert proposal["llm"] is True
            assert proposal["description_json"]["overrides"]["pitch_deg"] == 60
            assert 0 <= proposal["description_json"]["seed"] < 2**31
            assert call.call_count == 1 and call.call_args.kwargs["task"] == "hull_design"
            prompt = call.call_args.kwargs["user_prompt"]
            assert "10.0" in prompt and "8.0" in prompt and "2 storey" in prompt
        for content in ("nonsense", "[]", '{"style":"nope","overrides":{}}'):
            with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(content=content)):
                assert hull_model.propose_hull(location["id"])["llm"] is False
        with patch("app.core.prompt_templates.render_task", side_effect=ValueError("broken template")), \
                patch("app.core.llm_router.llm_call") as call:
            assert hull_model.propose_hull(location["id"])["llm"] is False
            call.assert_not_called()
        from app.core.llm_router import fallback_parent
        assert fallback_parent("hull_design") is None
        for style in ("nope", [], 7):
            assert client.post(base + "/generate", json={"description": {"style": style}}).status_code == 400
        for body in ([], {}, {"description": "invalid"}):
            assert client.post(base + "/generate", json=body).status_code == 400
        with patch("app.blender.runner.is_available", return_value=False):
            assert client.post(base + "/generate", json={"description": {"style": "burg"}}).status_code == 503
        with patch("app.blender.runner.is_available", return_value=True):
            from app.core import hull_geometry
            with patch.dict(hull_geometry.TRI_BUDGET, {"full": 0, "low": 0}), \
                    patch.object(hull_model, "trigger_hull_generation") as trigger:
                response = client.post(base + "/generate", json={"description": {"style": "burg"}})
                assert response.status_code == 400 and response.json()["detail"] == "too_large"
                trigger.assert_not_called()
            for started, status in ((False, 409), (True, 200)):
                with patch.object(hull_model, "trigger_hull_generation", return_value=started) as trigger:
                    response = client.post(base + "/generate", json={"description": {"style": "burg"}})
                    assert response.status_code == status
                    assert trigger.call_count == 1
                    if started:
                        assert response.json() == {"ok": True, "started": True}
        styles = client.get("/world/hull-styles").json()["styles"]
        assert styles and all(style["origin"] == "shared" for style in styles)
        response = client.put("/world/hull-styles/burg", json={"name": "Override", "shutters": 5})
        assert response.json()["origin"] == "world" and response.json()["shutters"] == 1
        assert client.put("/world/hull-styles/nope", json={}).status_code == 404
        assert client.delete("/world/hull-styles/burg").json()["ok"] is True
        assert hull_styles.get_style("burg")["origin"] == "shared"
        for method, url in (("put", "/world/hull-styles/burg"),
                            ("delete", "/world/hull-styles/burg"),
                            ("post", base + "/propose"), ("post", base + "/generate")):
            assert getattr(player, method)(url).status_code == 403
    print("smoke_hull_routes: all checks passed")


if __name__ == "__main__":
    main()
