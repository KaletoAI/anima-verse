#!/usr/bin/env python3
"""The Figure tab replaced the Base body, Outfit body and Hair tabs — what was
removed with them stays removed (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
Task 11; spec ruling 8: "the Figure tab replaces Base body, Outfit body and Hair").

Usage:
    ./.venv/bin/python scripts/smoke_figure_removed.py

Runs against a THROWAWAY storage + instance directory (``STORAGE_DIR`` /
``INSTANCE_DIR`` set before ``app.server`` is imported) — no world, no hub, no
server. Expected values, by hand from the plan's Task 11 file list:

[1] ``app.server.app.routes`` holds no path containing ``/outfit-bodies`` (the
    Outfit body tab's routes, ``app/routes/outfit_bodies.py``, are gone) and no
    GET ``/characters/{character_name}/base-body`` (folded into GET
    ``/figure?plain=1``). ``POST /characters/{character_name}/model3d/build-current``
    (the 3D tab's "Build current outfit", which lived in that file) is still
    routed, and so is GET ``/characters/{character_name}/figure``.
[2] Through the real app and a logged-in admin, with a character directory
    ``Demo`` present: GET ``/characters/Demo/base-body`` → 404 or 405 (no such
    route); GET ``/characters/Demo/outfit-bodies`` → 404 or 405; GET
    ``/characters/Demo/figure?plain=1`` → 200 with a ``plain_body`` dict
    carrying ``pipeline`` and ``humanoid`` (what the base-body GET answered);
    GET ``/characters/Demo/figure`` → 200 WITHOUT ``plain_body``.
[3] ``shared/templates/character/base-character.json`` has no tab id
    ``outfit_body_tab`` / ``hair_tab`` and no section with special
    ``outfit_body`` / ``hair``; tab ``figure_tab`` and section ``figure``
    (special ``figure``) are there. (Was: no ``base_body_tab`` / ``base_body``
    either — Task UI1 brought a NEW Base body tab back at the user's request,
    2026-11-13: tab ``base_body_tab`` with section ``base_body`` directly
    before ``figure_tab``, rendered by a new ``FieldBaseBody``.)
    Resolved (``app.models.character_template.get_template`` + the
    ``visible_when.feature`` rule of CharactersTab): ``human-default`` shows
    the ``figure`` section, ``animal-default`` hides it (``humanoid: false``).
[4] ``git grep`` in ``frontend/src``: 0 lines name ``FieldOutfitBody``,
    ``FieldHair`` (word) or ``useOutfitBodies``; those three files do not exist
    (``FieldBaseBody`` is Task UI1's new Base body tab — was: deleted too).
[5] ``git grep`` in ``app frontend/src docs README.md``: 0 lines name
    ``outfit_body_mode`` outside ``app/core/figure_migration.py`` (the boot
    migration that removes the key), and 0 lines use ``own_mesh`` as the
    removed boolean FLAG (``.own_mesh``, ``["own_mesh"]``, ``get("own_mesh"``,
    ``own_mesh: boolean`` / ``"own_mesh": true|false``). ``own_mesh`` as the
    VALUE of ``outfit_piece.mesh_mode`` (spec: modes ``own_mesh`` · ``painted`` ·
    ``in_body``) is the new model and stays — the plan's literal "0 own_mesh"
    would forbid the mode itself.
[6] No user-facing source names a removed tab: 0 lines in ``app``,
    ``frontend/src``, ``packages``, ``plugins``, ``static/admin`` name
    "Outfit body tab" or "Hair tab" (case-insensitive). (Was: "Base body tab"
    too — the tab exists again since Task UI1.)
[7] ``body_retexture.run_timeout_seconds`` (the painted-body run limit of the
    removed Outfit body tab runs) is no longer in ``config_schema``.
[8] Fails on the old code: at 223c629a the template has ``base_body_tab``,
    ``frontend/src`` names ``FieldBaseBody`` (>= 1 line) and
    ``app/routes/outfit_bodies.py`` exists.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = "223c629a"
FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def grep_lines(pattern: str, *paths: str, extended: bool = False, icase: bool = False) -> list:
    flags = ["grep", "-n", "-a"] + (["-E"] if extended else []) + (["-i"] if icase else [])
    out = git(*flags, pattern, "--", *paths)
    return [line for line in out.splitlines() if line.strip()]


def walk_routes(routes, prefix=""):
    """Flatten the app's route tree (``include_router`` wraps each router in an
    ``_IncludedRouter`` node — as ``smoke_admin_controls.walk_routes``)."""
    from fastapi.routing import _IncludedRouter
    for r in routes:
        if isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            yield from walk_routes(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(r, "path", None):
            yield prefix + r.path, r


def routes_part() -> None:
    from app.server import app

    pairs = [(p, sorted(getattr(r, "methods", None) or ())) for p, r in walk_routes(app.routes)]
    check("[1] the walk sees the app's endpoints (> 300)", len(pairs) > 300)
    check("[1] no /outfit-bodies route", [p for p, _m in pairs if "/outfit-bodies" in p], [])
    check("[1] no GET …/base-body",
          [p for p, m in pairs if p == "/characters/{character_name}/base-body" and "GET" in m], [])
    check("[1] build-current still routed",
          any(p == "/characters/{character_name}/model3d/build-current" and "POST" in m for p, m in pairs))
    check("[1] GET …/figure routed", any(p == "/characters/{character_name}/figure" and "GET" in m for p, m in pairs))

    from fastapi.testclient import TestClient
    from app.core import users
    from app.models.character import get_character_dir
    get_character_dir("Demo").mkdir(parents=True, exist_ok=True)
    users.create_user("figure-admin", "smoke-password", role="admin")
    client = TestClient(app)
    check("[2] admin login", client.post("/auth/login", json={"username": "figure-admin",
                                                             "password": "smoke-password"}).status_code, 200)
    check("[2] GET base-body gone", client.get("/characters/Demo/base-body").status_code in (404, 405))
    check("[2] GET outfit-bodies gone", client.get("/characters/Demo/outfit-bodies").status_code in (404, 405))
    r = client.get("/characters/Demo/figure?plain=1")
    check("[2] GET figure?plain=1 -> 200", r.status_code, 200)
    plain = (r.json() if r.status_code == 200 else {}).get("plain_body")
    check("[2] plain_body has pipeline + humanoid",
          isinstance(plain, dict) and "pipeline" in plain and "humanoid" in plain)
    r = client.get("/characters/Demo/figure")
    check("[2] GET figure without plain_body", r.status_code == 200 and "plain_body" not in r.json())

    raw = (ROOT / "app/core/config_schema.py").read_text(encoding="utf-8")
    check("[7] run_timeout_seconds gone from config_schema", "run_timeout_seconds" in raw, False)


def template_part() -> None:
    raw = json.loads((ROOT / "shared/templates/character/base-character.json").read_text(encoding="utf-8"))
    tab_ids = [t.get("id") for t in raw.get("tabs") or []]
    specials = [s.get("special") for s in raw.get("sections") or []]
    check("[3] removed tab ids", [t for t in tab_ids if t in ("outfit_body_tab", "hair_tab")], [])
    check("[3] removed specials", [s for s in specials if s in ("outfit_body", "hair")], [])
    check("[3] figure_tab + figure section", "figure_tab" in tab_ids and "figure" in specials)
    check("[3] Task UI1: base_body_tab right before figure_tab, section base_body",
          [tab_ids.index("base_body_tab") + 1 == tab_ids.index("figure_tab") if "base_body_tab" in tab_ids
           and "figure_tab" in tab_ids else False, "base_body" in specials], [True, True])
    from app.models.character_template import get_template
    for name, want in (("human-default", True), ("animal-default", False)):
        tmpl = get_template(name) or {}
        features = tmpl.get("features") or {}
        shown = any(s.get("special") == "figure"
                    and features.get((s.get("visible_when") or {}).get("feature") or "") is not False
                    for s in tmpl.get("sections") or [])
        check(f"[3] {name} shows the figure section", shown, want)


def grep_part() -> None:
    check("[4] frontend names none of the removed components",
          grep_lines(r"FieldOutfitBody\|FieldHair\b\|useOutfitBodies", "frontend/src"), [])
    for f in ("FieldOutfitBody.tsx", "FieldHair.tsx", "useOutfitBodies.ts"):
        check(f"[4] {f} deleted", (ROOT / "frontend/src/tabs/characters" / f).exists(), False)
    check("[4] app/routes/outfit_bodies.py deleted", (ROOT / "app/routes/outfit_bodies.py").exists(), False)
    mode = [line for line in grep_lines("outfit_body_mode", "app", "frontend/src", "docs", "README.md")
            if not line.startswith("app/core/figure_migration.py:")]
    check("[5] outfit_body_mode only in figure_migration.py", mode, [])
    flag = re.compile(r"""\.own_mesh\b|\[["']own_mesh["']\]|get\(["']own_mesh["']|own_mesh\??\s*:\s*boolean"""
                      r"""|["']own_mesh["']\s*:\s*(true|false|True|False)\b""")
    hits = [line for line in grep_lines("own_mesh", "app", "frontend/src", "docs", "README.md")
            if not line.startswith("app/core/figure_migration.py:") and flag.search(line.split(":", 2)[-1])]
    check("[5] own_mesh never used as the removed flag", hits, [])
    check("[6] no source names a removed tab",
          grep_lines("outfit body tab|hair tab", "app", "frontend/src", "packages", "plugins",
                     "static/admin", extended=True, icase=True), [])


def baseline_part() -> None:
    tmpl = git("show", f"{BASELINE}:shared/templates/character/base-character.json")
    check(f"[8] {BASELINE} template has base_body_tab", '"base_body_tab"' in tmpl)
    old = git("grep", "-c", "FieldBaseBody", BASELINE, "--", "frontend/src")
    check(f"[8] {BASELINE} frontend names FieldBaseBody (>= 1)",
          sum(int(x.rsplit(":", 1)[-1]) for x in old.splitlines() if x.strip()) >= 1)
    check(f"[8] {BASELINE} has app/routes/outfit_bodies.py",
          bool(git("cat-file", "-t", f"{BASELINE}:app/routes/outfit_bodies.py").strip()))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_figure_removed_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(tmp / "world")
    template_part()
    grep_part()
    baseline_part()
    routes_part()
    print("ALL OK" if not FAILS else f"FAILED: {len(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
