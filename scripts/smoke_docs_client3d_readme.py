#!/usr/bin/env python3
"""Smoke: client3d/README.md agrees with the 3D client's own files.

Usage:  ./.venv/bin/python scripts/smoke_docs_client3d_readme.py

Covers review finding DC-11. The README named seven proxy prefixes while
`client3d/vite.config.ts` forwarded sixteen, and called the client "vanilla,
deliberately no React" while eight `.tsx` files sit in its HUD. A missing
prefix does not 404 — Vite answers with its own `index.html` — so a half list
in the README is the exact trap the config's own comment warned about. The
list is gone since 2026-09-22: the dev proxy is the inverted rule of
`packages/dev-proxy-rule/`, and this guard now keeps BOTH free of a prefix
list (a list is what rots; `scripts/smoke_vite_proxy.py` checks the rule
itself).

Pure text work: three files are read and compared. No server, no world DB,
nothing from `app` is imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) `client3d/vite.config.ts` carries NO list of backend prefixes any more
   and gets its dev-proxy decision from `./dev-proxy-rule.js`. Expected value
   hand-derived from the rule that replaced the list: the config is the thing
   Vite reads, so a list reappearing there is the regression.

B) The README does not list proxy prefixes either, and names the rule module
   instead. Expected value: a code span of two or more single-segment
   `/name` items is what a prefix list looks like (see `readme_prefixes`) —
   there must be none.

C) The README does not claim the client has no React while React is a
   dependency: if `client3d/package.json` lists `react`, the phrase
   "kein React" may only appear qualified ("kein React" inside a sentence
   that also names the HUD). Checked concretely: the README must name
   `@anima/player-ui` and `src/hud/`, and must state the number of `.tsx`
   files that are really there.

E) Every HTML entry point of the build is documented and every page the
   README documents exists. Expected value = the `rollupOptions.input` map
   of `client3d/vite.config.ts` plus the files on disk — the two diagnostic
   pages (`figure-test.html`, `floorplan.html`) shipped undocumented until
   2026-09-21.

F) The two environment variables the client is steered with are named
   (`ANIMA_API` from `vite.config.ts`, `CLIENT3D_PORT` from `start.sh`), and
   the README's count of `client3d/scripts/smoke_*.mjs` matches the
   directory.

G) FAILS BEFORE / PASSES AFTER
---------------------------
Confirmed against two EXPLICIT revisions, never `HEAD:` (once this is
committed HEAD would compare the files with themselves): `git show
6e78bf17:client3d/vite.config.ts` still carries the 16-entry `proxied` array
that A now forbids, and `git show 74693e4f:client3d/README.md` typesets a
prefix list that B now forbids and carries the unqualified React claim. See
the last block of the output.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "client3d" / "README.md"
VITE = REPO / "client3d" / "vite.config.ts"
PKG = REPO / "client3d" / "package.json"
HUD = REPO / "client3d" / "src" / "hud"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def config_prefixes(src=None):
    """The `proxied` prefix list of a `vite.config.ts` — empty since it is gone."""
    src = VITE.read_text(encoding="utf-8") if src is None else src
    m = re.search(r"const proxied\s*=\s*\[(.*?)\]", src, re.S)
    if not m:
        return []
    return re.findall(r"'(/[a-zA-Z0-9_-]+)'", m.group(1))


_PREFIX_RE = re.compile(r"^/[a-z][a-z0-9_-]*$")


def readme_prefixes(text):
    """Every /prefix the README states AS A LIST.

    A code span counts only when it holds two or more whitespace-separated
    items and EVERY item is a single-segment `/name`. That is what a prefix
    list looks like, and it keeps out both `./start.sh` (not a prefix) and
    `/play/worldmap` (an endpoint, not a prefix) — whichever way the README
    happens to typeset the list (the previous revision used an inline span,
    this one a fenced block).
    """
    spans = re.findall(r"```(.*?)```", text, re.S) + re.findall(r"`([^`\n]+)`", text)
    out = []
    for span in spans:
        items = span.split()
        if len(items) >= 2 and all(_PREFIX_RE.match(i) for i in items):
            out += items
    return out


def main():
    readme = README.read_text(encoding="utf-8")

    print("A) the config decides by the inverted rule, not by a prefix list")
    cfg = config_prefixes()
    check("vite.config.ts has no `proxied` prefix list any more", not cfg, str(cfg))
    check("vite.config.ts uses ./dev-proxy-rule.js",
          "./dev-proxy-rule.js" in VITE.read_text(encoding="utf-8"))
    check("dev-proxy-rule.js binds the SHARED rule",
          "packages/dev-proxy-rule/index.js"
          in (REPO / "client3d" / "dev-proxy-rule.js").read_text(encoding="utf-8"))

    print("B) the README does not carry a prefix list either")
    listed = readme_prefixes(readme)
    check("the README lists no proxy prefixes", not listed, str(listed))
    check("the README names the rule module", "dev-proxy-rule.js" in readme)

    print("C) the React statement matches package.json and src/hud/")
    deps = json.loads(PKG.read_text(encoding="utf-8")).get("dependencies", {})
    has_react = "react" in deps
    tsx = sorted(p.name for p in HUD.glob("*.tsx"))
    check("react is a dependency of client3d (otherwise this check is moot)", has_react)
    check("the README names the HUD directory", "src/hud/" in readme)
    check("the README names the shared player package", "@anima/player-ui" in readme)
    check(f"the README states the number of HUD .tsx files ({len(tsx)})",
          re.search(r"(acht|neun|zehn|sieben|sechs|\b%d\b)" % len(tsx), readme) is not None,
          str(tsx))
    check("the README no longer claims 'vanilla, bewusst kein React'",
          "bewusst kein React" not in readme)

    print("E) the HTML entry points")
    vite_src = VITE.read_text(encoding="utf-8")
    m = re.search(r"input:\s*\{(.*?)\}", vite_src, re.S)
    entries = re.findall(r"'([^']+\.html)'", m.group(1)) if m else []
    check("vite.config.ts still declares its entry points", bool(entries),
          str(entries))
    for html in entries:
        check(f"the README documents `{html}`", html in readme)
        check(f"`{html}` exists", (REPO / "client3d" / html).is_file())

    print("F) env vars and the smoke count")
    check("the README names ANIMA_API", "ANIMA_API" in readme)
    check("ANIMA_API is what vite.config.ts reads",
          "process.env.ANIMA_API" in vite_src)
    start_sh = (REPO / "start.sh").read_text(encoding="utf-8")
    check("the README names CLIENT3D_PORT", "CLIENT3D_PORT" in readme)
    check("CLIENT3D_PORT is what start.sh reads",
          "CLIENT3D_PORT" in start_sh)
    smokes = sorted((REPO / "client3d" / "scripts").glob("smoke_*.mjs"))
    check(f"the README states the number of client smokes ({len(smokes)})",
          str(len(smokes)) in readme, str(len(smokes)))

    print("G) the same checks against the PINNED previous revisions")
    try:
        old_cfg = subprocess.run(["git", "show", "6e78bf17:client3d/vite.config.ts"],
                                 cwd=REPO, capture_output=True, text=True,
                                 check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show of the pinned pre-fix revision 6e78bf17", False, str(e))
    else:
        check("the previous config carried a 16-entry `proxied` list",
              len(config_prefixes(old_cfg)) == 16, str(config_prefixes(old_cfg)))
    try:
        old = subprocess.run(["git", "show", "74693e4f:client3d/README.md"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show of the pinned pre-fix revision 74693e4f", False, str(e))
    else:
        check("the previous README typeset a prefix list",
              len(readme_prefixes(old)) >= 2, str(readme_prefixes(old)))
        check("the previous revision carried the unqualified React claim",
              "bewusst kein React" in old)

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
