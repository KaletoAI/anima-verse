#!/usr/bin/env python3
"""Smoke: the READMEs under shared/models/ agree with code, routes and git.

Usage:  ./.venv/bin/python scripts/smoke_docs_model_libraries.py

Seven directories, seven READMEs, and each of them makes three kinds of claim
that rot silently:

  * it names FILES and MODULES (`scripts/clip_import_cmu.py`,
    `app/core/fbx_import.py`, `app/blender/scripts/rig_export.py`),
  * it names ROUTES the server serves them through,
  * it makes a LICENCE statement — "this library travels with the repository,
    that one does not" — which is only true as long as `.gitignore` says so.

The third one is why this check exists: the free library is redistributable
CMU material and IS tracked, the licensed library, the CMU originals, the
trial archive and the import inbox must never be. A README that says
"gitignored" about a directory git is happily tracking is a licence problem,
not a typo.

Pure text and git work: no server, no world DB, nothing from `app` is
imported (the module names are checked as FILES, not by importing them).

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) Every repo-relative path a README mentions in a code span exists.
   Expected value = the filesystem.

B) Every `/assets/...` route a README names is declared in
   `app/routes/assets.py`. Expected value = the `@router` decorators.

C) The tracking statements against `git ls-files`: `shared/models/clips/**`
   has tracked binaries, the four per-installation directories have nothing
   tracked but their README, and `shared/models/rig/reference.fbx` — the one
   pipeline binary that travels — is tracked and says so.

D) The rig README's bone count is the number of distinct `mixamorig:` bone
   names in `reference.fbx` itself (the names are plain ASCII in the FBX, so
   counting them needs no parser).

E) The clip libraries' env overrides are the ones `app/core/paths.py`
   implements (`ANIMATION_CLIPS_DIR`, `ANIMATION_RIG_FILE`).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "shared" / "models"
READMES = ["clips", "clips-inbox", "clips-licensed", "clips-trial", "figure",
           "mocap-src", "rig"]

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def tracked(prefix):
    out = subprocess.run(["git", "ls-files", prefix], cwd=REPO,
                         capture_output=True, text=True).stdout
    return [l for l in out.split("\n") if l.strip()]


#: Paths that are examples rather than files ("<kind>.json", "walk.fbx"), or
#: directories named with a trailing slash. Only concrete repo paths count.
PATH_RE = re.compile(r"`((?:app|scripts|shared|client3d|packages|frontend)/"
                     r"[A-Za-z0-9_./-]*[A-Za-z0-9_])`")


def main():
    texts = {}
    for name in READMES:
        p = MODELS / name / "README.md"
        check(f"{name}/README.md exists", p.is_file())
        if p.is_file():
            texts[name] = p.read_text(encoding="utf-8")

    print("\nA) every repo path a README names exists")
    for name, text in texts.items():
        missing = sorted({m for m in PATH_RE.findall(text)
                          if not (REPO / m).exists()
                          and "*" not in m and "<" not in m})
        check(f"{name}: no dangling path", not missing, str(missing))

    print("\nB) every /assets route a README names is declared")
    assets = (REPO / "app" / "routes" / "assets.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'@router\.\w+\("(/[^"]*)"', assets))
    # the router carries the /assets prefix; strip it off what the READMEs say
    declared = {"/assets" + r for r in declared}

    def norm(route):
        """`/assets/clip-catalog/{take}/import` -> the decorator's spelling."""
        return re.sub(r"\{[^}]*\}", "{}", route.rstrip("/"))

    decl_norm = {norm(r) for r in declared}
    for name, text in texts.items():
        named = set(re.findall(r"(/assets/[A-Za-z0-9_{}/<>-]+)", text))
        bad = sorted(r for r in named
                     if norm(re.sub(r"<[^>]*>", "{}", r)) not in decl_norm)
        check(f"{name}: every /assets route exists", not bad, str(bad))

    print("\nC) the tracking statements against git")
    free = tracked("shared/models/clips")
    check("the FREE clip library is tracked (binaries, not just the README)",
          len([f for f in free if f.endswith(".fbx")]) > 5,
          f"{len(free)} files")
    for d in ("clips-licensed", "clips-trial", "mocap-src", "clips-inbox"):
        files = tracked(f"shared/models/{d}")
        check(f"{d}: nothing tracked but the README",
              files == [f"shared/models/{d}/README.md"], str(files))
        check(f"{d}/README.md says so",
              re.search(r"not in git|gitignored|ignored|untracked", texts.get(d, ""),
                        re.I) is not None)
    fig = tracked("shared/models/figure")
    check("figure: no binary tracked",
          not [f for f in fig if not f.endswith(".md")], str(fig))
    rig = tracked("shared/models/rig")
    check("rig/reference.fbx IS tracked",
          "shared/models/rig/reference.fbx" in rig, str(rig))
    check("the rig README says it is tracked",
          "TRACKED in git" in texts.get("rig", ""))

    print("\nD) the rig's bone count")
    fbx = (MODELS / "rig" / "reference.fbx")
    if fbx.is_file():
        blob = fbx.read_bytes()
        bones = {m.group(0) for m in
                 re.finditer(rb"mixamorig:[A-Za-z0-9_]+", blob)}
        stated = re.search(r"(\d+)\s+bones", texts.get("rig", ""))
        check("the rig README states a bone count", stated is not None)
        if stated:
            check(f"the stated count is the file's ({len(bones)})",
                  int(stated.group(1)) == len(bones),
                  f"README says {stated.group(1)}, file has {len(bones)}")
    else:
        check("reference.fbx present (otherwise D is skipped)", False)

    print("\nE) the env overrides are the ones paths.py implements")
    paths_py = (REPO / "app" / "core" / "paths.py").read_text(encoding="utf-8")
    for var, where in (("ANIMATION_CLIPS_DIR", "clips"),
                       ("ANIMATION_RIG_FILE", "rig")):
        check(f"{var} exists in paths.py", var in paths_py)
        check(f"{where}/README.md names {var}", var in texts.get(where, ""))

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
