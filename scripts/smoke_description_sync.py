#!/usr/bin/env python3
"""Smoke run for the room-description sync (plan-furnish-v2.md § 2b B14b, E8).

No test framework, no LLM: ``room_description_sync._llm_text`` is replaced by a
canned answer, so one run walks the whole button — inventory, prompt, preview,
apply — against a throwaway world in a temp directory. Everything else is the
real path (template, validators, world model, room resolution).

Every expected number is derived by hand from the rule:

  * THE INVENTORY IS ONE LINE PER PIECE THAT STANDS THERE, grouped by prop and
    sorted by name. The study below holds two "Oak Table" placements, one
    "Wall Sconce", one "Clay Mug" that stands ON the first table and one
    placement of a prop the library does not know. So: 3 entries — Clay Mug 1
    (surface), Oak Table 2 (floor), Wall Sconce 1 (wall) — in that order
    ("clay" < "oak" < "wall"), the child counted ONCE like every other piece
    and the unknown id skipped (it has no name to put in a sentence).
  * A ``need:<key>`` id cannot occur in a stored layout — ``props.safe_prop_id``
    refuses the colon, so the layout sanitizer drops such a placement on the
    way in. The row below proves that: a layout written with one comes back
    without it, and the inventory therefore never has to skip it.
  * The rendered user prompt carries ONE line per entry ("- 2x Oak Table (on
    the floor)") plus the room's current description verbatim; the system
    prompt carries the language name the code resolved ("German" for "de",
    "English" for the empty default).
  * ``propose`` writes NOTHING: the room's description is byte-identical after
    the call, and the answer is the model's text, trimmed.
  * ``apply`` stores the text the admin hands back (not the proposal), an
    empty one is refused with 400, and an unknown room is 404 on both verbs.
  * The yard is a target like a room: its composite id ``__ground__@<loc>``
    resolves to the location's ground, whose one placement makes an inventory
    of one entry.

Usage:  ./.venv/bin/python scripts/smoke_description_sync.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="descsync-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import db, props, room_description_sync  # noqa: E402
from app.core.room_furnish import FurnishError  # noqa: E402
from app.core.world_ops import (  # noqa: E402
    _sanitize_room_layout, sanitize_ground_layout,
)
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    get_room_by_id,
)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def make_prop(name: str, mount: str = "") -> str:
    prop = props.create_prop(name=name, category="furniture", width_m=1.0,
                             depth_m=0.6, height_m=0.8, mount=mount)
    return prop["id"]


def fake_llm(answer: str):
    """Replace the module's plain-text LLM hop. Returns the call log so the
    rendered prompts can be inspected."""
    calls = []

    def _stub(task, system_prompt, user_prompt, label):
        calls.append({"task": task, "system": system_prompt,
                      "user": user_prompt, "label": label})
        return answer

    room_description_sync._llm_text = _stub
    return calls


def refused_with(fn, status: int, *args) -> bool:
    try:
        fn(*args)
    except FurnishError as e:
        return e.status == status
    return False


def main() -> int:
    db.init_schema()
    print(f"World: {WORLD}")

    table = make_prop("Oak Table")
    sconce = make_prop("Wall Sconce", mount="wall")
    mug = make_prop("Clay Mug", mount="surface")

    loc = add_location("Smoke House", "A test house", rooms=[
        {"id": "descroom", "name": "Study", "description": "A quiet study.",
         "activities": []}])
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] != loc["id"]:
            continue
        entry["map3d"] = {"plan_width_m": 8.0, "storey_height_m": 3.0,
                          "boundary": [[-5.0, -5.0], [5.0, -5.0],
                                       [5.0, 5.0], [-5.0, 5.0]]}
        # THROUGH THE REAL SANITIZER, like every write path: that is what makes
        # the "need:<key> cannot be stored" row below a statement about the
        # code and not about this script.
        entry["rooms"][0]["layout"] = _sanitize_room_layout({
            "x": -2.0, "y": -2.0, "w": 4.0, "d": 4.0, "level": 0,
            "props": [
                {"prop_id": table, "id": "tbl00001", "at": [1.0, 0.5]},
                {"prop_id": table, "at": [3.0, 0.5]},
                {"prop_id": sconce, "at": [0.2, 2.0]},
                {"prop_id": mug, "id": "mug00001", "at": [0.0, 0.0],
                 "on": "tbl00001"},
                {"prop_id": "ghost-prop-nobody-has", "at": [2.0, 3.0]},
                {"prop_id": "need:n1", "at": [2.5, 3.5]},
            ],
        })
        # The ground room is the location's own (every location has one, § A13);
        # it is filled here, never added a second time.
        ground = get_room_by_id(entry, GROUND_ROOM_ID)
        ground["description"] = "Open ground."
        ground["layout"] = sanitize_ground_layout(
            {"props": [{"prop_id": sconce, "at": [0.0, 0.0]}]})
    _save_world_data(data)
    location_id = loc["id"]
    yard_job = f"{GROUND_ROOM_ID}@{location_id}"

    # ── 1. The inventory ────────────────────────────────────────────────
    print("\n  inventory")
    stored = get_room_by_id({"rooms": _load_world_data()["locations"][0]["rooms"]},
                            "descroom")
    stored_ids = [p.get("prop_id") for p in (stored["layout"].get("props") or [])]
    check("a need: placeholder never survives the layout sanitizer",
          not any(str(pid).startswith("need:") for pid in stored_ids),
          ", ".join(str(p) for p in stored_ids))
    items = room_description_sync.inventory("descroom")
    check("one entry per prop, sorted by name",
          [e["name"] for e in items] == ["Clay Mug", "Oak Table", "Wall Sconce"],
          str([e["name"] for e in items]))
    check("two placements of one prop are 2x",
          [e["count"] for e in items] == [1, 2, 1],
          str([e["count"] for e in items]))
    check("a child on the table counts once, with its own mount",
          items[0] == {"name": "Clay Mug", "count": 1, "mount": "surface"},
          str(items[0]))
    check("an unclassified prop stands on the floor",
          items[1]["mount"] == "floor", items[1]["mount"])
    check("a prop the library does not know is skipped",
          len(items) == 3, str(len(items)))
    check("the yard is a target like a room",
          [e["name"] for e in room_description_sync.inventory(yard_job)]
          == ["Wall Sconce"])

    # ── 2. The proposal (preview only) ──────────────────────────────────
    print("\n  proposal")
    answer = "  Zwei eichene Tische stehen im Raum.  "
    calls = fake_llm(answer)
    result = room_description_sync.propose("descroom", "de")
    check("the answer is the model's text, trimmed",
          result["proposal"] == "Zwei eichene Tische stehen im Raum.",
          repr(result["proposal"]))
    check("the inventory travels with it",
          [e["name"] for e in result["inventory"]] == [e["name"] for e in items])
    check("exactly one call, on the right task",
          len(calls) == 1 and calls[0]["task"] == "room_description_sync",
          str([c["task"] for c in calls]))
    user = calls[0]["user"]
    check("every inventory entry is its own prompt line",
          "- 2x Oak Table (on the floor)" in user
          and "- 1x Clay Mug (on the surface)" in user
          and "- 1x Wall Sconce (on the wall)" in user, user)
    check("the current description is in the prompt",
          "A quiet study." in user)
    check("the language code becomes a language name",
          "in German" in calls[0]["system"], calls[0]["system"][-160:])
    calls2 = fake_llm(answer)
    room_description_sync.propose("descroom")
    check("the default language is English",
          "in English" in calls2[0]["system"], calls2[0]["system"][-160:])
    fresh = get_room_by_id({"rooms": _load_world_data()["locations"][0]["rooms"]},
                           "descroom")
    check("propose writes nothing",
          fresh.get("description") == "A quiet study.",
          str(fresh.get("description")))
    check("an empty answer is an error, not an empty description",
          refused_with(lambda: (fake_llm("   "),
                                room_description_sync.propose("descroom")),
                       502))

    # ── 3. Apply ────────────────────────────────────────────────────────
    print("\n  apply")
    edited = "Ein stiller Raum mit zwei eichenen Tischen und einer Wandleuchte."
    room_description_sync.apply("descroom", edited)
    saved = get_room_by_id({"rooms": _load_world_data()["locations"][0]["rooms"]},
                           "descroom")
    check("the ADMIN's text is stored, not the proposal",
          saved.get("description") == edited, str(saved.get("description")))
    check("an empty text is refused",
          refused_with(room_description_sync.apply, 400, "descroom", "   "))
    check("the yard's description is writable through its composite id",
          room_description_sync.apply(yard_job, "Trampled grass.")["status"]
          == "saved")
    yard = get_room_by_id({"rooms": _load_world_data()["locations"][0]["rooms"]},
                          GROUND_ROOM_ID)
    check("…and lands on the ground room",
          yard.get("description") == "Trampled grass.",
          str(yard.get("description")))

    # ── 4. Unknown room ─────────────────────────────────────────────────
    print("\n  unknown room")
    check("propose answers 404",
          refused_with(room_description_sync.propose, 404, "nosuchroom"))
    check("apply answers 404",
          refused_with(room_description_sync.apply, 404, "nosuchroom", "text"))
    check("inventory answers 404",
          refused_with(room_description_sync.inventory, 404, "nosuchroom"))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(WORLD, ignore_errors=True)
