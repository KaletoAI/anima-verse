#!/usr/bin/env python3
"""Smoke run for the view vocabulary shared by props and locations
(app/core/view_prompts.py) and the building-type migration.

No world, no DB, no server. Expectations are worked out by hand from the
design (docs/superpowers/specs/2026-09-02-multiview-props-locations-design.md):

  1. Four views exist: front, back, left, right. Anything else is not a view.
  2. A view picks the use case of a mesh-input render: the FRONT keeps the
     base use case, the BACK gets "<base>_back", LEFT and RIGHT share
     "<base>_side" (the T-pose precedent tpose/tpose_back/tpose_side). This
     holds for every base — prop, building, building_outdoor, room_model,
     room_model_outdoor — with no special case per base.
  3. The front has NO subject prefix; back/left/right each have one, and the
     left and right phrases differ (they share a use case, so the prefix is
     the only thing that tells the mesher's left from its right).
  4. Gallery image types of a location model source are "building-<view>";
     "building" alone is NOT one of them any more (it is migrated away).
  5. The migration rewrite turns every image_types value "building" into
     "building-front", leaves every other value alone, reports whether it
     changed anything, and a second run changes nothing.
  6. A prop's extra views live next to its variant's front image:
     stem "model" -> "source_back.png", stem "model-v2" -> "source-v2_left.png";
     the front keeps its historic name ("source.png" / "source-v2.png").

Expected results:

  (a) view_use_case("prop", "front") == "prop"
      view_use_case("prop", "back") == "prop_back"
      view_use_case("room_model_outdoor", "left") == "room_model_outdoor_side"
      view_use_case("building", "right") == "building_side"
      view_use_case("building", "top") -> ValueError
  (b) view_prefix("front") == "" ; view_prefix(v) != "" for the other three;
      view_prefix("left") != view_prefix("right")
      view_subject("front", "a chair") == "a chair"
      view_subject("back", "a chair") == view_prefix("back") + ", a chair"
  (c) building_type("back") == "building-back"; building_view("building-left") == "left";
      building_view("building") == ""; building_view("day") == ""; is_view("front") is True;
      is_view("building-front") is False
  (d) rewrite_building_types({"image_types": {"a.png": "building", "b.png": "day",
      "c.png": "building-back"}}) -> True and the dict becomes
      {"a.png": "building-front", "b.png": "day", "c.png": "building-back"};
      a second call returns False; a meta without image_types returns False.
      The content-pack location import calls it too: a pack exported before
      2026-09-02 carries the bare type in its `gallery_meta.json`, and the boot
      migration only runs at the NEXT start — so `import_location_from_zip` in
      `app/core/content_io.py` must name `rewrite_building_types` in the same
      block that remaps the rooms. That one is a SOURCE check: the import needs
      a world DB and a ZIP, which this smoke deliberately has neither of.
  (e) view_source_name("model", "back") == "source_back.png"
      view_source_name("model-v2", "left") == "source-v2_left.png"
      view_source_name("model", "front") == "source.png"
      view_source_name("model-v2", "front") == "source-v2.png"
      view_source_name("bogus", "back") == ""

Usage:  ./.venv/bin/python scripts/smoke_view_types.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          f"{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


from app.core.view_prompts import (BUILDING_TYPES, EXTRA_VIEWS, VIEWS,  # noqa: E402
                                   building_type, building_view, is_view,
                                   view_prefix, view_subject, view_use_case)

print("\n(a) view -> use case")
check("front keeps the base", view_use_case("prop", "front") == "prop")
check("back gets _back", view_use_case("prop", "back") == "prop_back")
check("left of an outdoor room is _side",
      view_use_case("room_model_outdoor", "left") == "room_model_outdoor_side")
check("right of a building is _side",
      view_use_case("building", "right") == "building_side")
try:
    view_use_case("building", "top")
    check("unknown view raises ValueError", False)
except ValueError:
    check("unknown view raises ValueError", True)
check("VIEWS is front/back/left/right",
      VIEWS == ("front", "back", "left", "right"), str(VIEWS))
check("EXTRA_VIEWS is back/left/right",
      EXTRA_VIEWS == ("back", "left", "right"), str(EXTRA_VIEWS))

print("\n(b) subject prefix")
check("front has no prefix", view_prefix("front") == "")
check("back/left/right have one",
      all(view_prefix(v) for v in EXTRA_VIEWS))
check("left and right differ", view_prefix("left") != view_prefix("right"))
check("front subject untouched", view_subject("front", "a chair") == "a chair")
check("back subject is prefixed",
      view_subject("back", "a chair") == f"{view_prefix('back')}, a chair")

print("\n(c) building image types")
check("building_type(back)", building_type("back") == "building-back")
check("building_view(building-left)", building_view("building-left") == "left")
check("plain 'building' is no view type", building_view("building") == "")
check("day is no view type", building_view("day") == "")
check("BUILDING_TYPES lists the four",
      BUILDING_TYPES == ("building-front", "building-back",
                         "building-left", "building-right"), str(BUILDING_TYPES))
check("is_view(front)", is_view("front") is True)
check("is_view(building-front) is False", is_view("building-front") is False)

print("\n(d) migration rewrite")
try:
    from app.models.world import rewrite_building_types
    meta = {"image_types": {"a.png": "building", "b.png": "day",
                            "c.png": "building-back"}}
    changed = rewrite_building_types(meta)
    check("first run reports a change", changed is True)
    check("building -> building-front, others untouched",
          meta["image_types"] == {"a.png": "building-front", "b.png": "day",
                                  "c.png": "building-back"},
          str(meta["image_types"]))
    check("second run changes nothing", rewrite_building_types(meta) is False)
    check("meta without image_types is a no-op",
          rewrite_building_types({"rooms": {}}) is False)
except ImportError as e:
    check("rewrite_building_types importable", False, str(e))

# The content-pack import is the second caller and cannot be reached without a
# world DB and a ZIP, so it is checked at the SOURCE: the gallery_meta block of
# `import_location_from_zip` has to name the rewrite. Without it an imported
# pack keeps the bare `building` type until the next server start.
src = (Path(__file__).resolve().parents[1]
       / "app/core/content_io.py").read_text(encoding="utf-8")
i = src.find("def import_location_from_zip(")
block = src[i:] if i >= 0 else ""
j = block.find("gallery_meta.json")
block = block[j:j + 2000] if j >= 0 else ""
wired = bool(block) and "rewrite_building_types(" in block
check("the content-pack import rewrites the bare building type", wired,
      "" if wired else "not named in the gallery_meta block")

print("\n(e) prop view file names")
try:
    from app.core.props import view_source_name
    check("model/back", view_source_name("model", "back") == "source_back.png")
    check("model-v2/left", view_source_name("model-v2", "left") == "source-v2_left.png")
    check("model/front is the historic name",
          view_source_name("model", "front") == "source.png")
    check("model-v2/front is the historic name",
          view_source_name("model-v2", "front") == "source-v2.png")
    check("bogus stem -> ''", view_source_name("bogus", "back") == "")
except ImportError as e:
    check("view_source_name importable", False, str(e))

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all view-type checks passed")
