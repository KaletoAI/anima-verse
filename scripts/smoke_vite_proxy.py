#!/usr/bin/env python3
"""Smoke: neither Vite dev server can answer a backend path itself.

Usage:  ./.venv/bin/python scripts/smoke_vite_proxy.py

Pure text work plus a few `node` calls: the FastAPI decorators under `app/`,
`packages/dev-proxy-rule/index.js` and the two per-app bindings are read,
nothing is started, no world DB is touched, no dev server and no backend are
needed.

WHY THIS CHECK EXISTS

Both `frontend/vite.config.ts` and `client3d/vite.config.ts` used to forward an
explicit LIST of backend prefixes. A prefix missing from that list does not
404 — the dev server answers the API call with its own HTML and a 200,
`res.json()` fails, and the component blows up far from the cause. The
frontend's list had ten entries against the ~38 route prefixes the two pages
call, and two of them (`/activities`, `/scheduler`) had no route behind them
any more; client3d's had sixteen, one of them (`/state`) equally dead, while
~14 prefixes its own code and the shared panels call were missing. The rule is
inverted now and it is ONE rule for both apps:
`packages/dev-proxy-rule/index.js` names the few paths VITE owns, everything
else goes to the backend. Each app binds it to its own pages in its own
`dev-proxy-rule.js` — which is the module this guard imports, so the guard
checks the very function the dev server uses. A list would rot again, an
inverted rule can only be broken on purpose.

WHAT IS CHECKED, and where every expected value comes from

A) Every route the backend serves is FORWARDED, by BOTH apps. Expected value =
   the routes collected from the FastAPI decorators (the collector of
   `scripts/smoke_docs_readme.py` is imported, so both guards see the same
   routes): each `app/routes/*.py`'s `APIRouter(prefix=…)` plus its
   `@router.<verb>("…")`, plus `app/server.py`'s `@app.<verb>("…")` and
   `app.mount("…")`. A `{param}` segment is filled with a sample value.
   Hand-derived exceptions — the paths that are a PAGE in production and a
   Vite HTML entry in dev:

       frontend  /              the backend redirects it to /play; in dev it is
                                the Game-Admin entry (index.html), which is
                                what http://localhost:5173/ has always opened
       frontend  /play          the player shell; in dev it is play.html
       frontend  /game-admin    the admin shell; in dev it is index.html
       client3d  /              the world map (index.html)

   client3d has no `play.html` and no Game-Admin, so `/play` and `/game-admin`
   are plain API/pages of the backend there.

B) The paths VITE must keep, hand-derived from what a dev server serves:
   its own namespaces (`/@…`, `/__…`), the source tree (`/src/…`), the
   dependencies (`/node_modules/…`), the HTML entries and `public/`.

C) The page/API collision, the reason this is not a one-line prefix rule:
   `/play` is the PAGE and `/play/…` is the API. Hand-derived verdicts per app
   in `TABLE_FRONTEND` / `TABLE_CLIENT3D` below.

D) Every backend prefix the 3D client and the shared player panels CALL is
   forwarded. Expected value = the prefixes extracted from `client3d/src` and
   `packages/player-ui/src` (string literals starting with `/segment`, comment
   lines skipped) — the same sweep the old `proxied` list was kept by hand
   from. One hand-derived exception: `/models/…` is `client3d/public/models/`
   (the manifest and the test meshes) and has no backend route, so it stays
   Vite's.

E) No explicit prefix list remains in either config. `server.proxy` must have
   exactly one key, the catch-all `'^/'`. Any second key would be a list
   starting to grow back. Both configs must use the SHARED rule — a private
   copy is how the two dev servers drifted apart in the first place.

F) The frontend's `base` must be conditional on the command. `/static/…` is a
   backend path (the theme CSS and the favicon both HTML entries link), so the
   dev server cannot also serve its own files under `/static/game_admin/`.

G) One environment-variable convention for the backend address: both
   `frontend/vite.config.ts` and `client3d/vite.config.ts` read `ANIMA_API`.

H) Each app's rule knows exactly the HTML entries its build declares
   (`build.rollupOptions.input`) — an entry added to the build but not to the
   rule would be answered by the backend in dev.

Exit code 0 = every check passed.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
CLIENT3D = REPO / "client3d"
SHARED_RULE = REPO / "packages" / "dev-proxy-rule" / "index.js"

sys.path.insert(0, str(REPO / "scripts"))
from smoke_docs_readme import real_routes  # noqa: E402  (same route collector)

# The production PAGE paths that are a Vite HTML entry in dev, per app (A).
PAGES_FRONTEND = {"/": "/index.html", "/play": "/play.html", "/game-admin": "/index.html"}
PAGES_CLIENT3D = {"/": "/index.html"}

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


# ---------------------------------------------------------------------------
# Evaluating the rule itself — node imports the very module Vite imports
# ---------------------------------------------------------------------------

_DRIVER = """
import { readFileSync } from 'node:fs'
const { viteDevTarget } = await import(process.env.RULE_URL)
const urls = JSON.parse(readFileSync(0, 'utf8'))
process.stdout.write(JSON.stringify(urls.map((u) => viteDevTarget(u))))
"""


class App:
    """One dev server: its directory, its rule module and its page paths."""

    def __init__(self, name, directory, pages):
        self.name = name
        self.dir = directory
        self.rule = directory / "dev-proxy-rule.js"
        self.config = directory / "vite.config.ts"
        self.pages = pages

    def targets(self, urls):
        """For each URL: the path Vite serves, or None when it is forwarded."""
        env = dict(os.environ, RULE_URL=self.rule.as_uri())
        p = subprocess.run(["node", "--input-type=module", "-e", _DRIVER],
                           cwd=str(self.dir), env=env, input=json.dumps(urls),
                           capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stderr.strip())
            raise SystemExit(f"node could not evaluate {self.rule.relative_to(REPO)}")
        return json.loads(p.stdout)


APP_FRONTEND = App("frontend", FRONTEND, PAGES_FRONTEND)
APP_CLIENT3D = App("client3d", CLIENT3D, PAGES_CLIENT3D)
APPS = [APP_FRONTEND, APP_CLIENT3D]


def concrete(route):
    """`/play/item/{item_id}` -> `/play/item/sample` — a real request path."""
    return re.sub(r"\{[^}]*\}", "sample", route)


# ---------------------------------------------------------------------------
# A) every backend route is forwarded
# ---------------------------------------------------------------------------

def check_routes_forwarded():
    routes = sorted(real_routes())
    check(f"routes collected from the decorators ({len(routes)})", len(routes) >= 100)

    for app in APPS:
        wanted = [r for r in routes if r not in app.pages]
        kept = [(r, t) for r, t in zip(wanted, app.targets([concrete(r) for r in wanted]))
                if t is not None]
        check(f"{app.name}: every backend route is forwarded ({len(wanted)} routes)",
              not kept, str(kept[:10]))

        pages = sorted(app.pages)
        got = app.targets(pages)
        bad = [(p, g) for p, g in zip(pages, got) if g != app.pages[p]]
        check(f"{app.name}: the page paths are served as their HTML entry ({len(pages)})",
              not bad, str(bad))


# ---------------------------------------------------------------------------
# B) + C) hand-derived verdict tables
# ---------------------------------------------------------------------------

# None = forwarded to the backend, a string = the path Vite serves.
TABLE_FRONTEND = [
    # B) what Vite owns
    ("/", "/index.html"),
    ("/index.html", "/index.html"),
    ("/play.html", "/play.html"),
    ("/src/main.tsx", "/src/main.tsx"),
    ("/src/player/main.tsx", "/src/player/main.tsx"),
    ("/@vite/client", "/@vite/client"),
    ("/@react-refresh", "/@react-refresh"),
    ("/@fs/repo/packages/player-ui/src/api.ts", "/@fs/repo/packages/player-ui/src/api.ts"),
    ("/@id/vite/preload-helper", "/@id/vite/preload-helper"),
    ("/node_modules/.vite/deps/react.js", "/node_modules/.vite/deps/react.js"),
    ("/__open-in-editor", "/__open-in-editor"),
    ("/silhouette.svg", "/silhouette.svg"),          # frontend/public/
    # C) the page/API collision
    ("/play", "/play.html"),
    ("/play/", "/play.html"),
    ("/play?return=%2Fplay", "/play.html?return=%2Fplay"),
    ("/play/scene", None),
    ("/play/say", None),
    ("/play/locations/7/scene", None),
    ("/game-admin", "/index.html"),
    ("/game-admin/settings", None),
    ("/static/themes/base.css", None),
    ("/static/favicon.svg", None),
    ("/activities", None),
    ("/scheduler", None),
    # the prefixes the old list was missing
    ("/characters/sample", None),
    ("/events/image-stream", None),
    ("/queue/status", None),
    ("/api/sample", None),
    ("/improvements", None),
    ("/intents", None),
    ("/notifications", None),
    ("/npc/sample", None),
    ("/poses", None),
    ("/secrets", None),
    ("/chat/sample", None),
    ("/diary", None),
    ("/instagram", None),
    ("/tts/voices", None),
    ("/assets/sample", None),
    ("/thumbs/sample", None),
]

TABLE_CLIENT3D = [
    # B) what Vite owns — the three entries of the multi-page build, its
    # namespaces, the source tree, the dependencies and public/
    ("/", "/index.html"),
    ("/index.html", "/index.html"),
    ("/figure-test.html", "/figure-test.html"),
    ("/figure-test", "/figure-test.html"),
    ("/figure-test?model=demo&clip=idle", "/figure-test.html?model=demo&clip=idle"),
    ("/floorplan.html", "/floorplan.html"),
    ("/floorplan", "/floorplan.html"),
    ("/floorplan?location=7", "/floorplan.html?location=7"),
    ("/src/main.ts", "/src/main.ts"),
    ("/src/style.css", "/src/style.css"),
    ("/@vite/client", "/@vite/client"),
    ("/@fs/repo/packages/scene-render/src/place.ts", "/@fs/repo/packages/scene-render/src/place.ts"),
    ("/node_modules/.vite/deps/three.js", "/node_modules/.vite/deps/three.js"),
    ("/__open-in-editor", "/__open-in-editor"),
    ("/models/manifest.json", "/models/manifest.json"),   # client3d/public/models/
    ("/models/Xbot.glb", "/models/Xbot.glb"),
    # C) no player page and no Game-Admin page here: both are the backend's
    ("/play", None),
    ("/play/scene", None),
    ("/play/say", None),
    ("/game-admin", None),
    ("/static/game_admin/silhouette.svg", None),
    # the dead entry of the old list — the rule is generic, so it simply
    # stops mattering: there is no /state route, the backend answers 404
    ("/state", None),
    ("/state/x", None),
    # prefixes the old list was missing
    ("/thumbs/sample", None),
    ("/admin/settings", None),
    ("/characters/sample/model3d", None),
    ("/world/map", None),
    ("/auth/login", None),
    ("/account", None),
    ("/assets/sample", None),
    ("/events/image-stream", None),
    ("/notifications", None),
    ("/poses", None),
    ("/npc/sample", None),
]


def check_tables():
    for app, table in ((APP_FRONTEND, TABLE_FRONTEND), (APP_CLIENT3D, TABLE_CLIENT3D)):
        got = app.targets([u for u, _ in table])
        bad = [(u, want, g) for (u, want), g in zip(table, got) if g != want]
        check(f"{app.name}: the hand-derived verdict table holds ({len(table)} paths)",
              not bad, str(bad))


# ---------------------------------------------------------------------------
# D) the prefixes the client code really calls
# ---------------------------------------------------------------------------

# A string literal that starts a URL path: `'/play/…'`, "`/characters/${n}`".
_CALL_RE = re.compile(r"""['"`](/[a-z][a-zA-Z0-9_-]*)(?=[/?'"`$])""")
# Hand-derived: served from client3d/public/models/, no backend route exists.
CALL_EXCEPTIONS = {"/models"}


def called_prefixes(root):
    """Every `/prefix` a string literal under `root` addresses (comments out)."""
    out = set()
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("//", "*", "/*")):
                continue                      # a comment is not a call site
            out |= {m.group(1) for m in _CALL_RE.finditer(line)}
    return out


def check_called_prefixes():
    prefixes = called_prefixes(CLIENT3D / "src") | called_prefixes(REPO / "packages" / "player-ui" / "src")
    check(f"prefixes extracted from client3d/src + packages/player-ui/src ({len(prefixes)})",
          len(prefixes) >= 10, str(sorted(prefixes)))
    wanted = sorted(prefixes - CALL_EXCEPTIONS)
    got = APP_CLIENT3D.targets([p + "/sample" for p in wanted])
    kept = [(p, t) for p, t in zip(wanted, got) if t is not None]
    check(f"client3d: every called backend prefix is forwarded ({len(wanted)})",
          not kept, str(kept))


# ---------------------------------------------------------------------------
# E) + F) + G) + H) the configs
# ---------------------------------------------------------------------------

def proxy_keys(src):
    """The keys of the `server.proxy` object literal."""
    i = src.index("proxy: {")
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    block = src[j + 1:k]
    # Only the keys at depth 0 of the block are proxy contexts.
    keys, depth = [], 0
    for line in block.splitlines():
        if depth == 0:
            m = re.match(r"\s*'([^']+)'\s*:", line)
            if m:
                keys.append(m.group(1))
        depth += line.count("{") - line.count("}")
    return keys


def build_entries(src):
    """The HTML files of `build.rollupOptions.input`."""
    m = re.search(r"input:\s*\{(.*?)\}", src, re.S)
    return sorted(re.findall(r"'([^']+\.html)'", m.group(1))) if m else []


def rule_entries(app):
    """The HTML entries `dev-proxy-rule.js` binds the shared rule to."""
    src = app.rule.read_text(encoding="utf-8")
    m = re.search(r"ENTRIES\s*=\s*\[(.*?)\]", src, re.S)
    return sorted(re.findall(r"'([^']+\.html)'", m.group(1))) if m else []


def check_configs():
    check("the shared rule exists", SHARED_RULE.is_file(), str(SHARED_RULE))

    for app in APPS:
        src = app.config.read_text(encoding="utf-8")
        keys = proxy_keys(src)
        check(f"{app.name}: server.proxy has exactly the catch-all key '^/'",
              keys == ["^/"], str(keys))
        check(f"{app.name}: the config uses its dev-proxy-rule binding",
              "./dev-proxy-rule.js" in src)
        check(f"{app.name}: that binding uses the SHARED rule, not a copy",
              "packages/dev-proxy-rule/index.js" in app.rule.read_text(encoding="utf-8"))
        check(f"{app.name}: reads the backend address from ANIMA_API",
              "process.env.ANIMA_API" in src)

    src = APP_FRONTEND.config.read_text(encoding="utf-8")
    check("frontend: base is decided per command (dev '/' vs the built base)",
          re.search(r"base:\s*command === 'serve'", src) is not None)

    linked = set()
    for page in ("index.html", "play.html"):
        linked |= set(re.findall(r'(?:href|src)="(/static/[^"]+)"',
                                 (FRONTEND / page).read_text(encoding="utf-8")))
    check(f"frontend: the HTML entries link backend /static files ({len(linked)})",
          len(linked) >= 2, str(sorted(linked)))

    # H) build entries == rule entries, per app
    for app in APPS:
        built = build_entries(app.config.read_text(encoding="utf-8"))
        ruled = rule_entries(app)
        check(f"{app.name}: the rule knows every HTML entry of the build ({len(built)})",
              built and built == ruled, f"build={built} rule={ruled}")
        for html in ruled:
            check(f"{app.name}: `{html}` exists", (app.dir / html).is_file())


def main():
    print("A) every backend route is forwarded")
    check_routes_forwarded()
    print("B/C) the hand-derived verdict tables")
    check_tables()
    print("D) the prefixes the client code calls")
    check_called_prefixes()
    print("E/F/G/H) the configs")
    check_configs()
    print()
    if _failures:
        print(f"FAILED {len(_failures)} of {_checks} checks:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"OK — {_checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
