#!/usr/bin/env python3
"""Smoke: the mood suggestion list exists exactly once.

Usage:  ./.venv/bin/python scripts/smoke_mood_catalog.py

Covers review finding DS-5. ``shared/config/moods.json`` was read by no line
of code; two hand-maintained React copies stood in for it and had already
drifted (``chatting`` was missing from ``EffectsEditor.FALLBACK_MOODS``). The
file is the source now and ``GET /admin/shared-lists/moods`` hands it out.

Nothing here needs a server or a world: ``paths.init`` is pointed at a
throwaway directory before anything from ``app`` is imported, the loader reads
a JSON file, and the React side is checked as text.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) THE LOADER — ``app.routes.shared_lists.load_moods``. Expected values are
   read from ``shared/config/moods.json`` in this script (the file IS the
   specification; pinning the 12 names here would be the third copy this
   finding is about). Derived by hand from the loader's contract:

     - returns the ids of ``moods[]``, in FILE ORDER (the file's order is the
       display order, not alphabetical)
     - no blanks, no duplicates
     - a missing file yields ``[]`` — never an exception, because the mood
       field stays usable without suggestions

B) THE ROUTE — ``GET /admin/shared-lists/moods`` is declared, its payload is
   ``{"moods": [...]}`` with exactly the loader's list, and it is admin-gated.
   Two independent facts are asserted for the gate, both derived by hand from
   ``app/core/auth_dependency.py``: the path lies under the ``/admin``
   blanket prefix (``is_admin_only_path`` says True for GET), and the route
   itself depends on ``require_admin``. The route function is called with the
   user argument passed in, so no session machinery runs.

C) NO SECOND LIST — the two React components must not carry a mood list of
   their own any more and must take it from the shared hook. Derived by hand
   from the fix: both files import ``useMoods``, neither mentions
   ``FALLBACK_MOODS`` or ``MOODS =``, and no mood id of the catalog appears
   as a quoted literal in either of them.

D) LOCALIZATION — every mood id has a key in ``shared/languages/de.json``.
   That is the ``<field>_<lang>`` convention's other half: the UI shows the
   id, and the i18n layer localizes it, so a mood without a key would render
   English inside a German page. (The optional ``label_de`` in moods.json is
   reference only; it is checked against de.json so the two cannot drift.)

FAILS BEFORE / PASSES AFTER
---------------------------
A and B fail on the old tree by import error (``app/routes/shared_lists.py``
did not exist). C fails on the old tree on all three of its counts: both
components declared their own list. Confirmed by running the C-part against
``git show 74693e4f: (the pinned pre-fix revision — HEAD would compare the file with itself once this is committed) frontend/src/components/EffectsEditor.tsx`` — see the output.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Throwaway storage BEFORE anything from app is imported: auth_dependency
# pulls in sessions/users, which open a world DB (scripts/smoke_scripts_storage_lint.py).
_TMP = tempfile.mkdtemp(prefix="smoke_mood_catalog_")
os.environ.setdefault("ANIMATION_CLIPS_DIR", str(Path(_TMP) / "clips"))
from app.core import paths  # noqa: E402
paths.init(_TMP)

from app.core import auth_dependency  # noqa: E402
from app.routes import shared_lists  # noqa: E402

MOODS_JSON = REPO / "shared" / "config" / "moods.json"
DE_JSON = REPO / "shared" / "languages" / "de.json"
EFFECTS_TSX = REPO / "frontend" / "src" / "components" / "EffectsEditor.tsx"
PLACEMENT_TSX = REPO / "frontend" / "src" / "tabs" / "characters" / "PlacementEditor.tsx"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def expected_ids():
    data = json.loads(MOODS_JSON.read_text(encoding="utf-8"))
    return [e["id"] for e in data["moods"]]


def no_mood_list_in(text, ids):
    """(imports the hook, no own constant, no quoted mood literal)."""
    has_hook = "useMoods" in text
    own_const = bool(re.search(r"\b(FALLBACK_MOODS|MOODS)\s*(:|=)", text))
    literals = sorted(i for i in ids if f"'{i}'" in text or f'"{i}"' in text)
    return has_hook, own_const, literals


def main():
    ids = expected_ids()

    print("A) loader")
    got = shared_lists.load_moods()
    check("load_moods() == the ids of moods.json, in file order", got == ids,
          f"{got} != {ids}")
    check("no blank and no duplicate id",
          all(i.strip() for i in got) and len(set(got)) == len(got), str(got))
    missing_dir = Path(_TMP) / "no-such-shared"
    real_shared = paths.get_shared_dir
    try:
        paths.get_shared_dir = lambda: missing_dir       # type: ignore[assignment]
        check("a missing moods.json yields [] instead of raising",
              shared_lists.load_moods() == [])
    finally:
        paths.get_shared_dir = real_shared               # type: ignore[assignment]

    print("B) route")
    routes = {r.path: r for r in shared_lists.router.routes}
    path = "/admin/shared-lists/moods"
    check(f"{path} is declared", path in routes, str(sorted(routes)))
    if path in routes:
        route = routes[path]
        check("it is a GET", "GET" in route.methods, str(route.methods))
        payload = shared_lists.get_moods(_user={"role": "admin"})
        check("payload is {'moods': <the loader's list>}",
              payload == {"moods": ids}, str(payload))
        deps = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
        check("the route depends on require_admin", "require_admin" in deps, str(deps))
    check("the auth gate classifies the path as admin-only",
          auth_dependency.is_admin_only_path(path, "GET"))

    print("C) no second list in the React components")
    for tsx in (EFFECTS_TSX, PLACEMENT_TSX):
        text = tsx.read_text(encoding="utf-8")
        has_hook, own_const, literals = no_mood_list_in(text, ids)
        name = tsx.name
        check(f"{name} imports useMoods", has_hook)
        check(f"{name} declares no mood constant of its own", not own_const)
        check(f"{name} contains no quoted mood id", not literals, str(literals))

    print("D) localization")
    de = json.loads(DE_JSON.read_text(encoding="utf-8")).get("translations", {})
    absent = [i for i in ids if i not in de]
    check("every mood id has a key in shared/languages/de.json", not absent, str(absent))
    data = json.loads(MOODS_JSON.read_text(encoding="utf-8"))
    drifted = [e["id"] for e in data["moods"]
               if e.get("label_de") and e["label_de"] != de.get(e["id"])]
    check("label_de agrees with de.json where it is present", not drifted, str(drifted))

    print("E) the C-part against the PREVIOUS revision of EffectsEditor.tsx "
          "(must find the old list)")
    try:
        old = subprocess.run(
            ["git", "show", "74693e4f:frontend/src/components/EffectsEditor.tsx"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show 74693e4f: (the pinned pre-fix revision — HEAD would compare the file with itself once this is committed) EffectsEditor.tsx", False, str(e))
    else:
        has_hook, own_const, literals = no_mood_list_in(old, ids)
        check("the old file had its own mood constant", own_const)
        check("the old file quoted mood ids", bool(literals), str(literals))
        check("the old file did NOT use the hook", not has_hook)
        check("the old file was already missing 'chatting'", "'chatting'" not in old)

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
