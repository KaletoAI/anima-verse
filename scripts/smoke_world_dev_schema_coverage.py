#!/usr/bin/env python3
"""Smoke: World Dev free mode — coverage of the removed schema modes.

Plan docs/superpowers/plans/2026-11-25-world-dev-free-remove-schema-modes.md,
Task 1. Before the schema modes (character / location / map / layout chat and
their preview/apply/snapshot routes, JSON import) are removed, every feature
they offered is either covered by a free-mode tool (proved by the smoke named
in the table) or LISTED as an intended difference (D4, D5, D11). No DB writes;
still a temp world (paths.init BEFORE any world-DB import), because importing
world_dev_tools pulls world modules. Usage:

    ./.venv/bin/python scripts/smoke_world_dev_schema_coverage.py

COVERAGE TABLE (schema feature -> free-mode tool -> behavioural proof)
----------------------------------------------------------------------

  covered:
  - character new: template pick, fields, soul, outfits, body slots, home,
    schedule (/chat character, /apply-character) -> describe_template,
    create_character -> smoke_world_dev_char_fields, _outfits, _schedule,
    _known_places, _body_slots (apply_character part)
  - profile patch (/apply-profile-patch) -> update_character{patch}
    -> smoke_world_dev_tools; the push: smoke_world_dev_sync
  - soul section (/apply-soul), incl. the linked shared-section refusal
    -> update_character{"soul:<field>"} -> smoke_world_dev_tools
  - add outfit (/apply-outfit) -> update_character{outfits}
    -> smoke_world_dev_outfits
  - location new/edit (/chat location, /apply) -> create_location,
    update_location, place_location -> smoke_world_dev_tools,
    _location_values, _placement
  - map new/edit, merge (/preview-map, /apply-map) -> add_terrain_area,
    update_terrain_area, add_height_area, update_height_area,
    add_terrain_type, place_world_prop, create_location + place_location
    (stubs) -> smoke_world_dev_map_parity
  - map replace_terrain -> delete_area{kind, id} per area
    -> smoke_world_dev_map_parity
  - map/layout snapshot undo (/map-snapshots, /map-restore,
    /layout-snapshots, /layout-restore) -> run Discard / per-turn undo
    (journal) -> smoke_world_dev_undo
  - floor plan (/preview-layout, /apply-layout) -> set_room_layout,
    furnish_rooms -> smoke_world_dev_layout, _furnish
  - context pickers (context_location_ids / context_character_names)
    -> world_overview, find_locations, get_location, find_characters,
    get_character -> smoke_world_dev_tools
  - background pause (/pause-all) -> the run freezes the world (routes kept,
    D1) -> smoke_world_dev_free_routes
  - template dropdown (/character-templates) -> describe_template
    -> smoke_world_dev_describe_template
  - Effort picker and the Claude default budget 65536 -> Task 2,
    smoke_world_dev_effort
  - profile push to clients (sync_topics.profile_patched in the patch route)
    -> update_character + its undo -> smoke_world_dev_sync

  listed (intended differences, NOT covered):
  - D4  replacing an EXISTING outfit (/apply-outfit with a taken name): the
        free mode refuses it so its undo stays exact.
  - D5  deterministic JSON import (/preview-json, /apply-json): paste the
        JSON into the free-mode task; the agent writes it through the
        journaled tools.
  - D11 the LLM validator pass (/validate-json, task world_dev_validate with
        its own model picker): the agent's own model plus the deterministic
        check_run / completeness check replace it (no parity).

WHAT IS CHECKED (read by hand from the @_tool(...) decorators in
app/core/world_dev_tools.py)
---------------------------------------------------------------

  (1) 14 write tools exist with write True: create_character,
      update_character, create_location, update_location, place_location,
      set_room_layout, furnish_rooms, add_terrain_area, update_terrain_area,
      add_height_area, update_height_area, add_terrain_type,
      place_world_prop, delete_area.
  (2) 8 read tools exist with write False: describe_template, check_run,
      world_overview, find_locations, get_location, find_characters,
      get_character, check_character (plan
      2026-11-25-world-dev-free-complete-characters-budget, Task 5).
  (3) TOOLS["update_character"].summary names "soul:", "outfits",
      "body_slots" and "schedule"; TOOLS["create_character"].signature
      names "home?", "schedule?" and "known_places?";
      TOOLS["delete_area"].signature == "delete_area{kind, id}".
  (4) This docstring carries the three listed rows D4, D5, D11.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_cov_clips_")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_cov_")
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_cov_inst_")

from app.core import paths  # noqa: E402

paths.init(Path(os.environ["STORAGE_DIR"]))

from app.core import world_dev_tools as wt  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


WRITE_TOOLS = ("create_character", "update_character", "create_location",
               "update_location", "place_location", "set_room_layout",
               "furnish_rooms", "add_terrain_area", "update_terrain_area",
               "add_height_area", "update_height_area", "add_terrain_type",
               "place_world_prop", "delete_area")
READ_TOOLS = ("describe_template", "check_run", "world_overview",
              "find_locations", "get_location", "find_characters",
              "get_character", "check_character")

check("(1) 14 write tools listed", len(WRITE_TOOLS) == 14)
for name in WRITE_TOOLS:
    spec = wt.TOOLS.get(name)
    check(f"(1) {name} is a write tool", spec is not None and spec.write is True,
          spec and spec.write)
check("(2) 8 read tools listed", len(READ_TOOLS) == 8)
for name in READ_TOOLS:
    spec = wt.TOOLS.get(name)
    check(f"(2) {name} is a read tool", spec is not None and spec.write is False,
          spec and spec.write)

upd = wt.TOOLS.get("update_character")
for word in ("soul:", "outfits", "body_slots", "schedule"):
    check(f"(3) update_character summary names {word!r}",
          upd is not None and word in upd.summary, upd and upd.summary)
crt = wt.TOOLS.get("create_character")
for word in ("home?", "schedule?", "known_places?"):
    check(f"(3) create_character signature names {word!r}",
          crt is not None and word in crt.signature, crt and crt.signature)
dla = wt.TOOLS.get("delete_area")
check("(3) delete_area signature", dla is not None
      and dla.signature == "delete_area{kind, id}", dla and dla.signature)

doc = __doc__ or ""
for row in ("D4 ", "D5 ", "D11 "):
    check(f"(4) docstring lists {row.strip()}", f"  - {row}" in doc)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
