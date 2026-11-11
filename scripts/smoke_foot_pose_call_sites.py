#!/usr/bin/env python3
"""Smoke: every clip path of the two renderers dresses a shod figure's clips.

Usage:  ./.venv/bin/python scripts/smoke_foot_pose_call_sites.py

A pure SOURCE check (text scan) — it imports nothing of the app, loads no
three, opens no DB. The spec (docs/superpowers/specs/2026-11-10-footwear-
rigid-shoes-design.md § 6.2) asks for a smoke that enumerates the call sites
of the clip paths, as ``smoke_imports_resolve`` does for imports: the fitted
shoe's extension (``applyFootPose``) and the per-frame plant
(``plantFootPose``, footPlant.ts) must run on EVERY path that gives a shod
figure a clip, right after the retarget / bind-relative step — a path that
forgets them shows the figure standing in its shoes with bare-foot tracks,
the heel 5 cm under the floor, and nothing says why.

WHAT IS CHECKED, derived by hand from the two source trees
---------------------------------------------------------------------------
The three clip-path primitives are ``bindRelativeClip(``, ``adaptExternalClips(``
and ``retargetClips(``. Every CALL of one of them under ``client3d/src`` and
``frontend/src`` (definitions, ``export`` lines, comments and docstrings are
not calls) must sit inside a function from the LISTED SET below, and that
function's body must either call ``applyFootPose(`` itself or forward a
``footPose`` / ``shoes`` to the primitive. The set, by file and enclosing
function (a function's block runs from its declaration line to the first
later ``}`` at the declaration's own indentation — the sources are
consistently indented; a sibling whose block closed before the call is not
its enclosing function):

  client3d/src/scene/figures.ts
    adaptExternalClips   — the library path: calls ``prepareShoes`` → ``applyFootPose``
                           + ``plantFootPose`` on every surviving clip
    retargetClips        — the borrow path: the same step, no corrections
    buildModel           — the model's own embedded clips, the third path
                           (``prepareShoes`` straight on ``model.clips``)
    fitLibraryAsync      — calls ``adaptExternalClips`` and forwards ``shoes``
    loadManifestModels   — calls ``retargetClips`` and forwards ``footPose``
  frontend/src/tabs/characters/Model3DViewer.tsx
    useEffect            — the main viewer's load effect (anonymous; the scan
                           names it after the hook call at the component's
                           member indentation): ``applyFootPose(…bindRelativeClip(…))``,
                           the plant behind it
    rebuildOverlay       — the marker figures of the floor-plan overlay: the same

A NEW call site anywhere else fails [1]; a listed site whose body lost the
pose fails [2]. [3] pins the definitions themselves: ``adaptExternalClips``
and ``retargetClips`` in figures.ts contain ``prepareShoes(`` (the one shoe
step), the step contains ``applyFootPose(``, ``plantFootPose(`` and
``transplantedRestPose(``, and ``buildModel`` dresses the embedded clips.
[4] the viewer: both ``bindRelativeClip(`` calls are wrapped by
``applyFootPose(`` and followed by ``plantFootPose(``.

FAILS BEFORE / PASSES AFTER — against the sources before Task 19:

    d=$(mktemp -d); git archive a5e6043c client3d/src frontend/src | tar -x -C "$d"
    SMOKE_REPO="$d" ./.venv/bin/python scripts/smoke_foot_pose_call_sites.py

reports 10 failures: [2] for ``fitLibraryAsync`` (no ``shoes`` forwarded, both
calls) and ``loadManifestModels`` (no pose at all), [3] for both definitions,
the missing ``prepareShoes`` step and the embedded path, [4] for the plant
the viewer did not have yet.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

#: ``SMOKE_REPO`` points the scan at another checkout (the "fails before"
#: proof below runs it on a ``git archive`` of the pre-Task-19 sources).
REPO = Path(os.environ.get("SMOKE_REPO") or Path(__file__).resolve().parents[1])

PRIMITIVES = ("bindRelativeClip(", "adaptExternalClips(", "retargetClips(")

#: file → enclosing functions allowed to call a primitive. The viewer's
#: sites live in anonymous effect callbacks: their enclosing named scope
#: is the component itself.
ALLOWED: dict[str, set[str]] = {
    "client3d/src/scene/figures.ts": {
        "adaptExternalClips", "retargetClips", "buildModel", "fitLibraryAsync", "loadManifestModels",
    },
    "frontend/src/tabs/characters/Model3DViewer.tsx": {"useEffect", "rebuildOverlay"},
}

SCAN_DIRS = ("client3d/src", "frontend/src")

_FUNCTION = re.compile(r"^(?P<indent>\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\(")
_ARROW = re.compile(r"^(?P<indent>\s*)(?:export\s+)?(?:const|let)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>")
#: a class member: at the member indentation (2) only, so a call statement
#: deeper inside a body never reads as a declaration
_METHOD = re.compile(r"^(?P<indent>  )(?:private\s+|public\s+|protected\s+|static\s+|readonly\s+)*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\(")

_NOISE = {"if", "for", "while", "switch", "catch", "return", "else", "constructor"}

_failures: list[str] = []
_checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)


def is_call(line: str, prim: str) -> bool:
    """A real call of `prim` on this line: not a definition, export, import,
    comment or docstring line."""
    stripped = line.strip()
    if stripped.startswith(("*", "//", "/*", "export ", "import ")):
        return False
    if re.search(r"\bfunction\s+" + re.escape(prim[:-1]) + r"\s*\(", line):
        return False
    return prim in line


def declaration(line: str) -> tuple[str, str] | None:
    """(indent, name) when `line` opens a named function, arrow const or
    class method (the signature may continue on later lines)."""
    stripped = line.strip()
    if stripped.startswith(("*", "//", "/*")) or stripped.endswith(";"):
        return None
    for rx in (_FUNCTION, _ARROW, _METHOD):
        m = rx.match(line)
        if m and m.group("name") not in _NOISE:
            return m.group("indent"), m.group("name")
    return None


def block_end(lines: list[str], start: int, indent: str) -> int:
    """The line index where the block opened at `start` closes: the first
    later line that starts with a `}` at the declaration's own indentation
    (the sources are consistently indented); a one-line arrow function
    (`=> expr`, no brace) closes on its own line."""
    if "=>" in lines[start] and not lines[start].rstrip().endswith(("{", "(", ",")):
        return start
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(indent + "}") and not lines[j].startswith(indent + " "):
            return j
    return len(lines)


def enclosing(lines: list[str], at: int) -> tuple[str | None, int, int]:
    """(name, start, end) of the innermost named function whose block holds
    line `at` — a declaration above it whose block has not closed before it;
    siblings that closed earlier are skipped."""
    call_indent = len(lines[at]) - len(lines[at].lstrip())
    for i in range(at - 1, -1, -1):
        d = declaration(lines[i])
        if not d:
            continue
        indent, name = d
        if len(indent) >= call_indent:
            continue
        end = block_end(lines, i, indent)
        if end < at:
            continue
        return name, i, end
    return None, 0, len(lines)


def body_forwards(body: str) -> bool:
    return "applyFootPose(" in body or "footPose" in body or "shoes" in body


def main() -> int:
    print("[1]/[2] every call of a clip-path primitive sits in a listed function that forwards the pose")
    sites: list[tuple[str, int, str, str | None, bool]] = []
    for base in SCAN_DIRS:
        for path in sorted((REPO / base).rglob("*.ts*")):
            rel = path.relative_to(REPO).as_posix()
            if "/node_modules/" in rel or rel.endswith(".d.ts"):
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for n, line in enumerate(lines):
                for prim in PRIMITIVES:
                    if not is_call(line, prim):
                        continue
                    name, start, end = enclosing(lines, n)
                    body = "\n".join(lines[start:end])
                    sites.append((rel, n + 1, prim, name, body_forwards(body)))
    check("at least the five known call sites exist", len(sites) >= 5, f"{len(sites)} calls found")
    for rel, ln, prim, name, forwards in sites:
        allowed = name in ALLOWED.get(rel, set())
        check(f"{rel}:{ln} {prim[:-1]} in {name or '<module>'} — listed", allowed)
        check(f"{rel}:{ln} {prim[:-1]} in {name or '<module>'} — forwards the pose", forwards)

    print("[3] the definitions: one shoe step, extension + plant")
    figures = (REPO / "client3d/src/scene/figures.ts").read_text(encoding="utf-8")
    lines = figures.splitlines()

    def body_of(fn: str) -> str:
        for i, line in enumerate(lines):
            d = declaration(line)
            if d and d[1] == fn:
                return "\n".join(lines[i:block_end(lines, i, d[0]) + 1])
        return ""

    for fn in ("adaptExternalClips", "retargetClips"):
        check(f"figures.ts::{fn} calls prepareShoes(", "prepareShoes(" in body_of(fn))
    step = body_of("prepareShoes")
    check("figures.ts::prepareShoes applies the extension", "applyFootPose(" in step)
    check("figures.ts::prepareShoes bakes the plant", "plantFootPose(" in step)
    check("figures.ts::prepareShoes carries the transplanted rest", "transplantedRestPose(" in step)
    check("figures.ts::buildModel dresses the embedded clips", "prepareShoes(" in body_of("buildModel"))

    print("[4] the viewer: both bind-relative sites wrapped, the plant behind them")
    viewer = (REPO / "frontend/src/tabs/characters/Model3DViewer.tsx").read_text(encoding="utf-8")
    wrapped = len(re.findall(r"applyFootPose\(THREE,\s*(?:bindRelativeClip\(|bare\w*,)", viewer))
    check("two applyFootPose sites over bindRelativeClip", wrapped == 2, f"{wrapped} found")
    check("two plantFootPose sites", viewer.count("plantFootPose(") == 2, f"{viewer.count('plantFootPose(')} found")

    print()
    if _failures:
        print(f"FAIL: {len(_failures)} of {_checks} checks failed")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {_checks} checks passed — every clip path dresses the shod figure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
