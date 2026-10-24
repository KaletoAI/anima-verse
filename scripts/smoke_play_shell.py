#!/usr/bin/env python3
"""Check the built 3D player shell without starting lifespan services.

Usage: ./.venv/bin/python scripts/smoke_play_shell.py

Expected by hand from Task 7: the public /play shell, each linked asset,
HUD, manifest and a manifest-relative model return 200. The shell references
/static/client3d/assets/ and no legacy play- bundle. An anonymous HTML world
navigation returns 302 to /play with its original path in the return parameter.
"""
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with TemporaryDirectory(prefix="smoke-play-shell-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)  # No context manager: do not start lifespan services.
        try:
            response = client.get("/play")
            assert response.status_code == 200, response.status_code
            assert 'src="/static/client3d/assets/' in response.text, "not the built 3D shell"
            assert "play-" not in response.text, "legacy 2D bundle"
            links = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', response.text)
            assert links, "shell has no assets"
            for link in links:
                assert client.get(link).status_code == 200, link
            assert client.get("/static/client3d/hud.html").status_code == 200
            manifest_url = "/static/client3d/models/manifest.json"
            manifest = client.get(manifest_url)
            assert manifest.status_code == 200
            model_url = urljoin(manifest_url, manifest.json()["models"][0]["url"])
            assert model_url.startswith("/static/client3d/models/"), model_url
            assert client.get(model_url).status_code == 200, model_url
            response = client.get("/world/locations", headers={"Accept": "text/html"}, follow_redirects=False)
            assert response.status_code == 302, response.status_code
            redirect = urlsplit(response.headers["location"])
            assert redirect.path == "/play", redirect
            assert parse_qs(redirect.query) == {"return": ["/world/locations"]}, redirect
            print(f"PASS: 3D shell, {len(links)} linked assets, HUD, manifest, model and login redirect")
        finally:
            client.close()


if __name__ == "__main__":
    main()
