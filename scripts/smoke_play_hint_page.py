#!/usr/bin/env python3
"""/play is a hint page for the native client; the fallback model pool lives outside client3d.

Usage: ./.venv/bin/python scripts/smoke_play_hint_page.py

Runs without the server: `app.server` is imported with STORAGE_DIR and INSTANCE_DIR set to temp
directories and driven through a TestClient without lifespan (no session cookie, so every request
is anonymous).

Expected by hand (plan E3 task 12; spec 8: the browser 3D scene is retired, the native client is the
only player client):

[P1] GET /play without a session -> 200, text/html, Cache-Control no-cache, and the body says the
     game runs in the "native client" (it is a plain English page, no 3D shell: no reference to
     /static/client3d/).
[P2] GET /static/fallback-models/manifest.json anonymously -> 200 (/static/* is on the anonymous
     allowlist of auth_dependency). The manifest's first model "Soldier.glb" is relative to the
     manifest, so /static/fallback-models/Soldier.glb -> 200 as well (the native FigureManager
     resolves pool URLs against PoolBase = "/static/fallback-models/").
[P3] The old pool directory static/client3d/models no longer exists in the repository (moved with
     git mv, no copy left behind that a stale client could still read).
[P4] An anonymous HTML navigation to a player route (/world/locations) still gets 302 to /play with
     its path in ?return= (auth_dependency.login_redirect_target is unchanged; /play is now the
     hint page).
[P5] The HUD page the native client loads stays where it is: GET /static/hud/hud.html -> 200 (this
     check and P4 come from the retired scripts/smoke_play_shell.py, whose 3D-shell checks are gone
     with the shell).
"""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    failures = []

    def check(label, ok, detail=""):
        print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(label)

    with TemporaryDirectory(prefix="smoke-play-hint-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        os.chdir(ROOT)  # static mounts and the play route resolve relative to the repo root
        from app.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)  # No context manager: no lifespan services.
        try:
            r = client.get("/play", follow_redirects=False)
            check("[P1] /play 200 without a session", r.status_code == 200, str(r.status_code))
            check("[P1] /play is text/html", r.headers.get("content-type", "").startswith("text/html"),
                  r.headers.get("content-type", ""))
            check("[P1] /play Cache-Control no-cache", r.headers.get("cache-control") == "no-cache",
                  str(r.headers.get("cache-control")))
            check("[P1] /play names the native client", "native client" in r.text, r.text[:200])
            check("[P1] /play is no 3D shell", "/static/client3d/" not in r.text, r.text[:200])

            manifest_url = "/static/fallback-models/manifest.json"
            m = client.get(manifest_url)
            check("[P2] fallback manifest anonymous 200", m.status_code == 200, str(m.status_code))
            if m.status_code == 200:
                model_url = urljoin(manifest_url, m.json()["models"][0]["url"])
                check("[P2] first pool model is /static/fallback-models/Soldier.glb",
                      model_url == "/static/fallback-models/Soldier.glb", model_url)
                check("[P2] first pool model anonymous 200", client.get(model_url).status_code == 200, model_url)

            check("[P3] static/client3d/models is gone", not (ROOT / "static/client3d/models").exists())

            r = client.get("/world/locations", headers={"Accept": "text/html"}, follow_redirects=False)
            check("[P4] anonymous navigation 302", r.status_code == 302, str(r.status_code))
            if r.status_code == 302:
                target = urlsplit(r.headers["location"])
                check("[P4] redirect to /play with return", target.path == "/play"
                      and parse_qs(target.query) == {"return": ["/world/locations"]}, r.headers["location"])
            r = client.get("/static/hud/hud.html")
            check("[P5] /static/hud/hud.html 200", r.status_code == 200, str(r.status_code))
        finally:
            client.close()

    if failures:
        print(f"FAIL: {len(failures)} check(s) failed")
        return 1
    print("OK — /play hint page, fallback pool at /static/fallback-models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
