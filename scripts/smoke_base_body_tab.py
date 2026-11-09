#!/usr/bin/env python3
"""The base body has its own character tab, right before Pose.

User feedback 2026-11-09: the base-body section left the Pose tab for a tab of
its own. Expected values, derived by hand from that request and from how
Game-Admin builds field tabs (CharactersTab.tsx ``fieldTabs``: a tab owns the
sections whose ``column`` is in its ``columns``; a section whose
``visible_when.feature`` is false for the template is dropped, and a tab left
without sections vanishes):

[1] ``shared/templates/character/base-character.json`` has a tab
    ``base_body_tab`` with label "Base body" / label_de "Grundkörper", and it
    is the tab DIRECTLY before ``tpose_tab`` in the tab list.
[2] Its ``columns`` hold exactly one column, and no other tab claims it.
[3] The section ``base_body`` (special ``base_body``) sits in that column and
    carries ``visible_when: {feature: humanoid}``, like the hair section.
[4] The Pose tab keeps the pose refs: section ``model_refs`` sits in one of
    ``tpose_tab``'s columns, ``base_body`` does not.
[5] The resolved templates (``character_template.get_template``): for
    ``human-default`` the base_body section survives the feature filter
    (``humanoid`` not false), for ``animal-default`` it is dropped
    (``humanoid: false``) — so the tab shows for humanoids only.
[6] The hint in the Hair tab and the missing-images error name the new tab
    ("Base body tab"), never "Pose tab"; de.json carries the hint's
    translation with "Grundkörper".

Usage: ./.venv/bin/python scripts/smoke_base_body_tab.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_failures = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="smoke_base_body_tab_")
    from app.core import paths
    paths.init(tmp)

    raw = json.loads((ROOT / "shared/templates/character/base-character.json").read_text(encoding="utf-8"))
    tabs = raw.get("tabs") or []
    ids = [t.get("id") for t in tabs]
    tab = next((t for t in tabs if t.get("id") == "base_body_tab"), {})
    check("[1] base_body_tab label", tab.get("label") == "Base body", repr(tab))
    check("[1] base_body_tab label_de", tab.get("label_de") == "Grundkörper", repr(tab))
    check("[1] base_body_tab directly before tpose_tab",
          "base_body_tab" in ids and "tpose_tab" in ids
          and ids.index("tpose_tab") == ids.index("base_body_tab") + 1, repr(ids))
    cols = tab.get("columns") or []
    check("[2] one column", len(cols) == 1, repr(cols))
    others = [t.get("id") for t in tabs if t.get("id") != "base_body_tab"
              and set(t.get("columns") or []) & set(cols)]
    check("[2] no other tab claims it", not others, repr(others))

    sections = {s.get("id"): s for s in raw.get("sections") or []}
    sec = sections.get("base_body", {})
    check("[3] base_body section in the tab's column", sec.get("column") in cols, repr(sec))
    check("[3] base_body special", sec.get("special") == "base_body", repr(sec))
    check("[3] base_body humanoid only", sec.get("visible_when") == {"feature": "humanoid"}, repr(sec))
    pose_cols = next((t.get("columns") or [] for t in tabs if t.get("id") == "tpose_tab"), [])
    check("[4] model_refs stays in the Pose tab", sections.get("model_refs", {}).get("column") in pose_cols)
    check("[4] base_body left the Pose tab", sec.get("column") not in pose_cols)

    from app.models.character_template import get_template

    def survives(name):
        tmpl = get_template(name) or {}
        features = tmpl.get("features") or {}
        for s in tmpl.get("sections") or []:
            if s.get("id") == "base_body":
                f = (s.get("visible_when") or {}).get("feature")
                return not f or features.get(f) is not False
        return False

    check("[5] human-default shows the base body", survives("human-default"))
    check("[5] animal-default hides the base body", not survives("animal-default"))

    hair = (ROOT / "frontend/src/tabs/characters/FieldHair.tsx").read_text(encoding="utf-8")
    base = (ROOT / "app/core/base_body.py").read_text(encoding="utf-8")
    de = json.loads((ROOT / "shared/languages/de.json").read_text(encoding="utf-8")).get("translations") or {}
    hint = "Hair as its own mesh needs the base body pipeline — switch it on in the Base body tab"
    check("[6] hair hint names the Base body tab", hint in hair)
    check("[6] missing-images error names the Base body tab",
          "render them in the Base body tab" in base and "in the Pose tab" not in base)
    check("[6] de.json translates the hint with Grundkörper", "Grundkörper" in (de.get(hint) or ""),
          repr(de.get(hint)))

    print(f"\n{'OK' if not _failures else f'{len(_failures)} FAILED'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.exit(main())
