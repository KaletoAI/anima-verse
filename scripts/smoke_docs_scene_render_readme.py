#!/usr/bin/env python3
"""Smoke: packages/scene-render/README.md lists exactly what the package exports.

Usage:  ./.venv/bin/python scripts/smoke_docs_scene_render_readme.py

`@anima/scene-render` is the ONE place the geometry of the scene contract
lives, and its README is the map a reader of either renderer starts from. It
listed eight of the twenty-five modules until 2026-09-21 — `scatter`,
`layerCut`, `worldHeight`, `materials`, `stroke`, the whole water and clip
machinery were simply absent, which made the package look smaller than it is
and invited a ninth private copy of a routine that was already in here.

Pure text work: two files are read and compared. No server, no world DB,
nothing from `app` is imported, `three` is never loaded.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) EVERY export of `src/index.ts` appears in the README. Expected value = the
   names in the `export { … } from './module'` statements of the index; the
   index is what a consumer can import, so it is the specification and the
   README is the copy.

B) EVERY name in the EXPORTS cell of a table row exists as an export. A
   README that promises a routine nobody can import is worse than one that
   omits it. Only that cell is read — the purpose cell quotes payload field
   names, which are contract vocabulary and not exports.

C) Every module file under `src/` is re-exported by the index and has a row
   in the table — a module that nothing re-exports is dead weight, and one
   without a row is invisible.

D) The § references in the table resolve in `docs/schnittstellen-3d.md`
   (same rule as `scripts/smoke_docs_schnittstellen_3d.py`).

FAILS BEFORE / PASSES AFTER
---------------------------
Against the revision before the rework:

    git show f6816edf:packages/scene-render/README.md > /tmp/sr_old.md
    ./.venv/bin/python scripts/smoke_docs_scene_render_readme.py /tmp/sr_old.md

reports 5 of 7 checks passed: 207 of the 222 exports were not mentioned
at all and not one of the 25 modules had a row (the old table was keyed by
export name, not by module).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "packages" / "scene-render"
INDEX = PKG / "src" / "index.ts"
README = Path(sys.argv[1]) if len(sys.argv) > 1 else PKG / "README.md"
CONTRACT = REPO / "docs" / "schnittstellen-3d.md"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def index_exports():
    """{module: [name, …]} out of `export { … } from './module'`."""
    src = re.sub(r"/\*.*?\*/", "", INDEX.read_text(encoding="utf-8"), flags=re.S)
    out = {}
    for m in re.finditer(r"export\s+(?:type\s+)?\{(.*?)\}\s*from\s*'\./([A-Za-z]+)'",
                         src, re.S):
        names = [n.strip() for n in m.group(1).replace("\n", " ").split(",")
                 if n.strip()]
        out.setdefault(m.group(2), []).extend(names)
    return out


def table_rows(text):
    """The rows of the content table: {module: names in its EXPORTS cell}.

    Only the last cell is read. The "Zweck" cell names payload fields
    (`anchor`, `cut_plane`, `base_y`) that are contract vocabulary, not
    exports of this package, and they must not be mistaken for promises."""
    rows = {}
    for line in text.split("\n"):
        m = re.match(r"^\|\s*`([A-Za-z]+)\.ts`\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        rows[m.group(1)] = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`",
                                          cells[-1] if cells else ""))
    return rows


def main():
    readme = README.read_text(encoding="utf-8")
    exports = index_exports()
    all_names = {n for names in exports.values() for n in names}
    check("index.ts still re-exports modules", len(exports) > 10,
          str(sorted(exports)))

    print(f"\nA) every export is named in the README ({len(all_names)} exports)")
    missing = sorted(n for n in all_names
                     if not re.search(r"`%s`" % re.escape(n), readme))
    check("no export missing from the README", not missing,
          f"{len(missing)}: {missing[:12]}")

    print("\nB) the README promises nothing that does not exist")
    rows = table_rows(readme)
    modules = {p.stem for p in (PKG / "src").glob("*.ts")} - {"index"}
    invented = sorted(n for names in rows.values() for n in names
                      if n not in all_names and n not in modules)
    check("every identifier in the table is an export", not invented,
          str(invented))

    print("\nC) every module has a row and is re-exported")
    check("no module without a table row", not (modules - set(rows)),
          str(sorted(modules - set(rows))))
    check("no module the index does not re-export",
          not (modules - set(exports)), str(sorted(modules - set(exports))))
    check("the table invents no module", not (set(rows) - modules),
          str(sorted(set(rows) - modules)))

    print("\nD) the § references resolve in the contract")
    contract = CONTRACT.read_text(encoding="utf-8")
    heads, infence = set(), False
    for line in contract.split("\n"):
        if line.startswith("```"):
            infence = not infence
            continue
        if infence:
            continue
        m = re.match(r"^#{1,6}\s+([ABC]\d+[a-z]?(?:\.\d+)?)[.)\s]", line)
        if m:
            heads.add(m.group(1))
    refs = set(re.findall(r"§\s*([ABC]\d+[a-z]?(?:\.\d+)?)", readme))
    check(f"no dead § reference ({len(refs)} referenced)",
          not (refs - heads), str(sorted(refs - heads)))

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
