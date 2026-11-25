#!/usr/bin/env python3
"""Smoke: Regenerate ONE view of the worn body shape (round 2026-11-25, Henrik's naked back —
``POST /characters/{c}/figure/shape-view {view}``, ``base_body.start_shape_view``, ``GET
/characters/{c}/figure/shape/{key}/views/{view}``, ``figure_build._shape_views``).

Usage:
    ./.venv/bin/python scripts/smoke_shape_view_regenerate.py

Throwaway STORAGE_DIR / INSTANCE_DIR (no real world, no server, no hub). The routes run through the real router
behind the real auth gate; the session lookup reads the role from a header (as in smoke_figure_stored_delete.py).
The render itself (``base_body.render_shape_views``) is a stub that records its call and waits on an event, so the
run can be seen while it goes; the wanted figure is fixed (``figure.wanted_figure``).

Expected, derived by hand from the spec (henrik.md, Vorschlag B):
[1] Image jobs of one forced render: front 1 (the edit), back 2 (the turn and the draft, Ruling A175).
[2] Admin POST {view: "back"}, shape SHAPE = ob00000001 with its front stored -> 202 {status "started", shape SHAPE,
    view "back", jobs 2}; while the stub waits: base_steps_running = ["Body shape back view render"] (a Build does
    not start beside it: ``figure_build.start`` of a click answers "base_busy" naming it), a second POST -> 409
    ``SHAPE_VIEW_RUNNING``; the stub got exactly ([back], force True) for SHAPE. After it ends: no step runs,
    ``shape_view_state`` last = {shape SHAPE, view back, ok True, error ""}.
[3] Refusals: view "top" -> 400; a Build running (``figure_build.running`` True) -> 409 ``VIEWS_BUILD_RUNNING`` and
    nothing registered afterwards; the figure on the plain body (shape ``base…``) -> 409 ``SHAPE_VIEW_PLAIN``; the
    shape without its front, view back -> 409 ``SHAPE_VIEW_FRONT_FIRST``; media generation off -> 409.
[4] Auth: a player session -> 403, anonymous -> 401 (POST and the picture GET); the stub is not called.
[5] GET …/figure/shape/SHAPE/views/back -> 200 with the stored bytes, then 304 with its ETag; an unknown view -> 400;
    a key that is no body shape ("..", "base1234abcd") -> 400; a shape without that view -> 404.
[6] ``figure_build._shape_views(Demo, SHAPE)`` with front + back stored, the back an EMPTY composite while the front
    record says region 0.812 -> [{front: exists, empty False, lost_clothing False, jobs 1}, {back: exists, empty True,
    lost_clothing True, jobs 2}].
"""
import json
import os
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" (want {want!r})"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="shape-view-") as tmp:
        base = Path(tmp)
        os.environ["STORAGE_DIR"] = str(base / "world")
        os.environ["INSTANCE_DIR"] = str(base / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(base / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(base / "reference.fbx")
        from app.core import paths
        paths.init(base / "world")
        paths.init_instance(base / "instance")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=base / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        from app.core import base_body, figure, figure_build
        from app.imagegen import base as imagegen_base
        from app.models.character import get_character_dir, save_character_profile
        figure_build.request = lambda *a, **k: False
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female",
                                                             "age": 30}, create_new=True), True)
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        SHAPE = "ob00000001"
        base_body.is_base_pipeline = lambda *a, **k: True
        imagegen_base.media_generation_enabled = lambda: True
        wanted = types.SimpleNamespace(shape=SHAPE, bsig="base00000001")
        figure.wanted_figure = lambda *a, **k: wanted
        gate = threading.Event()
        calls = []

        def render(character_name, fig, views, *, items=None, force=True):
            calls.append((character_name, fig.shape, list(views), force))
            gate.wait(10)
            return {"ok": True, "error": ""}
        base_body.render_shape_views = render

        print("[1] jobs")
        check("front / back", (base_body.shape_view_jobs_of("front"), base_body.shape_view_jobs_of("back")), (1, 2))

        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import figure as figure_route
        users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Demo"]},
                 "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-test-user", ""))
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(figure_route.router)
        client = TestClient(app)
        admin = {"x-test-user": "admin"}
        url = "/characters/Demo/figure/shape-view"

        print("[2] a run")
        (refs / f"tpose_{SHAPE}.png").write_bytes(b"front")
        r = client.post(url, json={"view": "back"}, headers=admin)
        check("202", (r.status_code, r.json()), (202, {"status": "started", "shape": SHAPE, "view": "back", "jobs": 2}))
        check("a step for the Build", base_body.base_steps_running("Demo"), ["Body shape back view render"])
        check("a Build click waits", (figure_build.start("Demo", reason="manual").get("status")), "base_busy")
        r = client.post(url, json={"view": "back"}, headers=admin)
        check("a second POST", (r.status_code, r.json().get("detail")), (409, base_body.SHAPE_VIEW_RUNNING))
        gate.set()
        for _ in range(100):
            if not base_body.shape_view_state("Demo")["running"]:
                break
            threading.Event().wait(0.05)
        check("the render", calls, [("Demo", SHAPE, ["back"], True)])
        last = base_body.shape_view_state("Demo")["last"] or {}
        check("ended", (base_body.base_steps_running("Demo"), last.get("shape"), last.get("view"), last.get("ok"),
                        last.get("error")), ([], SHAPE, "back", True, ""))

        print("[3] refusals")
        calls.clear()
        check("unknown view", client.post(url, json={"view": "top"}, headers=admin).status_code, 400)
        real_running = figure_build.running
        figure_build.running = lambda name: True
        r = client.post(url, json={"view": "back"}, headers=admin)
        check("a Build runs", (r.status_code, r.json().get("detail")), (409, figure_build.VIEWS_BUILD_RUNNING))
        check("nothing left registered", base_body.base_steps_running("Demo"), [])
        figure_build.running = real_running
        wanted.shape = "base00000001"
        r = client.post(url, json={"view": "back"}, headers=admin)
        check("plain body", (r.status_code, r.json().get("detail")), (409, base_body.SHAPE_VIEW_PLAIN))
        wanted.shape = "ob00000002"
        r = client.post(url, json={"view": "back"}, headers=admin)
        check("no front", (r.status_code, r.json().get("detail")), (409, base_body.SHAPE_VIEW_FRONT_FIRST))
        wanted.shape = SHAPE
        imagegen_base.media_generation_enabled = lambda: False
        check("media off", client.post(url, json={"view": "back"}, headers=admin).status_code, 409)
        imagegen_base.media_generation_enabled = lambda: True
        check("no render", calls, [])

        print("[4] auth")
        pic = f"/characters/Demo/figure/shape/{SHAPE}/views/front"
        for method, path in (("POST", url), ("GET", pic)):
            kw = {"json": {"view": "back"}} if method == "POST" else {}
            check(f"player {method}", client.request(method, path, headers={"x-test-user": "user"}, **kw).status_code,
                  403)
            check(f"anonymous {method}", client.request(method, path, **kw).status_code, 401)
        check("no render", calls, [])

        print("[5] the picture")
        back = refs / f"tpose_back_{SHAPE}.png"
        back.write_bytes(b"back-bytes")
        r = client.get(f"/characters/Demo/figure/shape/{SHAPE}/views/back", headers=admin)
        check("200", (r.status_code, r.content), (200, b"back-bytes"))
        r2 = client.get(f"/characters/Demo/figure/shape/{SHAPE}/views/back",
                        headers={**admin, "If-None-Match": r.headers.get("etag", "")})
        check("304", r2.status_code, 304)
        check("unknown view", client.get(f"/characters/Demo/figure/shape/{SHAPE}/views/top", headers=admin)
              .status_code, 400)
        for key in ("..", "base1234abcd"):
            check(f"key {key}", client.get(f"/characters/Demo/figure/shape/{key}/views/back", headers=admin)
                  .status_code in (400, 404), True)
        check("base key -> 400", client.get("/characters/Demo/figure/shape/base1234abcd/views/back", headers=admin)
              .status_code, 400)
        check("missing view", client.get("/characters/Demo/figure/shape/ob00000002/views/back", headers=admin)
              .status_code, 404)

        print("[6] the thumbnails' record")
        (refs / f"tpose_{SHAPE}.json").write_text(json.dumps({"edit_composite": {"coverage": {"region": 0.812}}}))
        back.with_suffix(".json").write_text(json.dumps({"fit": "composite", "composite": "empty"}))
        got = [{k: v for k, v in e.items() if k != "stamp"} for e in figure_build._shape_views("Demo", SHAPE)]
        check("front + back", got, [{"view": "front", "exists": True, "empty": False, "lost_clothing": False, "jobs": 1},
                                    {"view": "back", "exists": True, "empty": True, "lost_clothing": True, "jobs": 2}])
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
