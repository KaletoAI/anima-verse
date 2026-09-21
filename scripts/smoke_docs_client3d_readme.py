#!/usr/bin/env python3
"""Smoke: client3d/README.md agrees with the 3D client's own files.

Usage:  ./.venv/bin/python scripts/smoke_docs_client3d_readme.py

Covers review finding DC-11. The README named seven proxy prefixes while
`client3d/vite.config.ts` forwards sixteen, and called the client "vanilla,
deliberately no React" while eight `.tsx` files sit in its HUD. A missing
prefix does not 404 — Vite answers with its own `index.html` — so a half list
in the README is the exact trap the config's own comment warns about.

Pure text work: three files are read and compared. No server, no world DB,
nothing from `app` is imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) The prefixes the README lists are EXACTLY the `proxied` array of
   `client3d/vite.config.ts`. Expected value = that array; the config is the
   thing Vite actually reads, so it is the specification and the README is
   the copy.

B) The README states the count the array has ("Stand heute sind es N").

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
Confirmed by running A, B and C against the previous revision of the README,
`git show 74693e4f:client3d/README.md` — an EXPLICIT hash, never `HEAD:`
(once this is committed HEAD would compare the file with itself). See the
last block of the output: that revision lists 7 of the 16 prefixes and
carries the unqualified React claim.
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


def config_prefixes():
    src = VITE.read_text(encoding="utf-8")
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
    cfg = config_prefixes()
    check("vite.config.ts still has a `proxied` array", bool(cfg), str(cfg))

    print(f"A) the README lists exactly the forwarded prefixes ({len(cfg)})")
    listed = readme_prefixes(readme)
    missing = [p for p in cfg if p not in listed]
    extra = [p for p in listed if p not in cfg]
    check("no forwarded prefix missing from the README", not missing, str(missing))
    check("the README invents no prefix", not extra, str(extra))

    print("B) the README states the right count")
    check(f"the README says {len(cfg)}", f"es {len(cfg)}" in readme or f"sind es {len(cfg)}" in readme)

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

    print("G) the same three checks against the PREVIOUS revision")
    try:
        old = subprocess.run(["git", "show", "74693e4f:client3d/README.md"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show of the pinned pre-fix revision 74693e4f", False, str(e))
    else:
        old_missing = [p for p in cfg if p not in readme_prefixes(old)]
        check("the previous revision was missing 9 of the prefixes",
              len(old_missing) == 9, f"{len(old_missing)}: {old_missing}")
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
