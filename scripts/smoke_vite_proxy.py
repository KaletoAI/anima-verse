#!/usr/bin/env python3
"""Smoke: the Vite dev server can never answer a backend path itself.

Usage:  ./.venv/bin/python scripts/smoke_vite_proxy.py

Pure text work plus one `node` call: the FastAPI decorators under `app/` and
`frontend/dev-proxy-rule.js` are read, nothing is started, no world DB is
touched, no dev server and no backend are needed.

WHY THIS CHECK EXISTS

`frontend/vite.config.ts` used to forward an explicit LIST of backend prefixes
to :8000. A prefix missing from that list does not 404 — the dev server
answers the API call with its own HTML and a 200, `res.json()` fails, and the
component blows up far from the cause. The list had ten entries against the
~38 route prefixes the two pages call, and two of them (`/activities`,
`/scheduler`) had no route behind them any more. The rule is inverted now:
`dev-proxy-rule.js` names the few paths VITE owns, everything else goes to the
backend. This guard keeps it that way — a list would rot again, an inverted
rule can only be broken on purpose.

WHAT IS CHECKED, and where every expected value comes from

A) Every route the backend serves is FORWARDED. Expected value = the routes
   collected from the FastAPI decorators (the collector of
   `scripts/smoke_docs_readme.py` is imported, so both guards see the same
   routes): each `app/routes/*.py`'s `APIRouter(prefix=…)` plus its
   `@router.<verb>("…")`, plus `app/server.py`'s `@app.<verb>("…")` and
   `app.mount("…")`. A `{param}` segment is filled with a sample value.
   Hand-derived exceptions — the three paths that are a PAGE in production and
   a Vite HTML entry in dev:

       /              the backend redirects it to /play; in dev it is the
                      Game-Admin entry (index.html), which is what
                      http://localhost:5173/ has always opened
       /play          the player shell; in dev it is play.html
       /game-admin    the admin shell; in dev it is index.html

B) The paths VITE must keep, hand-derived from what a dev server serves:
   its own namespaces (`/@…`, `/__…`), the source tree (`/src/…`), the
   dependencies (`/node_modules/…`), the two HTML entries and `public/`.

C) The page/API collision, the reason this is not a one-line prefix rule:
   `/play` is the PAGE and `/play/…` is the API. Hand-derived verdicts:

       /play                     -> Vite   play.html
       /play/                    -> Vite   play.html
       /play?return=%2Fplay      -> Vite   play.html?return=%2Fplay
       /play/scene               -> backend
       /play/say                 -> backend
       /play/locations/7/scene   -> backend
       /game-admin               -> Vite   index.html
       /game-admin/settings      -> backend (no such route — an honest 404
                                   from the backend beats Vite's HTML)
       /static/themes/base.css   -> backend (both HTML entries link it)
       /activities, /scheduler   -> backend (the two dead list entries)

D) No explicit prefix list remains. `server.proxy` must have exactly one key,
   the catch-all `'^/'`. Any second key would be a list starting to grow back.

E) `base` must be conditional on the command. `/static/…` is a backend path
   (the theme CSS and the favicon both HTML entries link), so the dev server
   cannot also serve its own files under `/static/game_admin/`.

F) One environment-variable convention for the backend address: both
   `frontend/vite.config.ts` and `client3d/vite.config.ts` read `ANIMA_API`.

Exit code 0 = every check passed.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
CONFIG = FRONTEND / "vite.config.ts"
RULE = FRONTEND / "dev-proxy-rule.js"
CLIENT3D_CONFIG = REPO / "client3d" / "vite.config.ts"

sys.path.insert(0, str(REPO / "scripts"))
from smoke_docs_readme import real_routes  # noqa: E402  (same route collector)

# The three production PAGE paths that are a Vite HTML entry in dev (A).
PAGE_PATHS = {"/", "/play", "/game-admin"}

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


def vite_targets(urls):
    """For each URL: the path Vite serves, or None when it is forwarded."""
    import os
    env = dict(os.environ, RULE_URL=RULE.as_uri())
    p = subprocess.run(["node", "--input-type=module", "-e", _DRIVER],
                       cwd=str(FRONTEND), env=env, input=json.dumps(urls),
                       capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr.strip())
        raise SystemExit("node could not evaluate frontend/dev-proxy-rule.js")
    return json.loads(p.stdout)


def concrete(route):
    """`/play/item/{item_id}` -> `/play/item/sample` — a real request path."""
    return re.sub(r"\{[^}]*\}", "sample", route)


# ---------------------------------------------------------------------------
# A) every backend route is forwarded
# ---------------------------------------------------------------------------

def check_routes_forwarded():
    routes = sorted(real_routes())
    check(f"routes collected from the decorators ({len(routes)})", len(routes) >= 100)

    wanted = [r for r in routes if r not in PAGE_PATHS]
    kept = [(r, t) for r, t in zip(wanted, vite_targets([concrete(r) for r in wanted]))
            if t is not None]
    check(f"every backend route is forwarded ({len(wanted)} routes)", not kept,
          str(kept[:10]))

    pages = sorted(PAGE_PATHS)
    got = vite_targets(pages)
    expect = {"/": "/index.html", "/play": "/play.html", "/game-admin": "/index.html"}
    bad = [(p, g) for p, g in zip(pages, got) if g != expect[p]]
    check("the three page paths are served by Vite as their HTML entry", not bad, str(bad))


# ---------------------------------------------------------------------------
# B) + C) hand-derived verdict table
# ---------------------------------------------------------------------------

# None = forwarded to the backend, a string = the path Vite serves.
TABLE = [
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


def check_table():
    got = vite_targets([u for u, _ in TABLE])
    bad = [(u, want, g) for (u, want), g in zip(TABLE, got) if g != want]
    check(f"the hand-derived verdict table holds ({len(TABLE)} paths)", not bad, str(bad))


# ---------------------------------------------------------------------------
# D) + E) + F) the config itself
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


def check_config():
    src = CONFIG.read_text(encoding="utf-8")
    keys = proxy_keys(src)
    check("server.proxy has exactly the catch-all key '^/'", keys == ["^/"], str(keys))

    check("base is decided per command (dev '/' vs the built base)",
          re.search(r"base:\s*command === 'serve'", src) is not None)

    linked = set()
    for page in ("index.html", "play.html"):
        linked |= set(re.findall(r'(?:href|src)="(/static/[^"]+)"',
                                 (FRONTEND / page).read_text(encoding="utf-8")))
    check(f"the HTML entries link backend /static files ({len(linked)})", len(linked) >= 2,
          str(sorted(linked)))

    check("frontend reads the backend address from ANIMA_API",
          "process.env.ANIMA_API" in src)
    check("client3d uses the same ANIMA_API convention",
          "process.env.ANIMA_API" in CLIENT3D_CONFIG.read_text(encoding="utf-8"))


def main():
    print("A) every backend route is forwarded")
    check_routes_forwarded()
    print("B/C) the hand-derived verdict table")
    check_table()
    print("D/E/F) the config")
    check_config()
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
