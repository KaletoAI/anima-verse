#!/usr/bin/env python3
"""Smoke: quest item effects, remove_item_everywhere, item.discovered, and item_images core module.

Quest system stage 2, Task 6 (D5, D12, D16, Task 5 grant pending-row ruling). Throwaway storage
(`paths.init(<tmpdir>)` BEFORE any world-DB module), no server, no LLM, no media (the item image
renderer is stubbed by monkeypatching `app.core.item_images.generate_item_image_sync`).
`quest_engine.register()` is NOT called — this smoke drives `evaluate`, `tick`, and `pass_once`
directly.

Usage:
    ./.venv/bin/python scripts/smoke_quest_items.py

FIXTURE
    Locations: L1 ("Forest", rooms r1 = "Glade", r2 = "Hollow"), L2 ("Camp", room s1 = "Gate").
    Characters: A (avatar of user "demo", active_character A), B (second avatar), N (NPC) —
    all start in L2/s1.
    Discovery stat key: read from config `inventory.discovery_stat` (with schema default),
    never hardcoded.
    Game clock: Y0001-D010T12:00:00.

WHAT FOLLOWS BY HAND
 (a) create_item (non-blocking image render + placeholders + item fields):
     - Setup `[box: create_item name "Old tin box" category "tool" stat_bonuses "{\"<stat>\": 5}"
       bonus_when "carried" effects "{\"<stat>_change\": 2}" consumable True
       description "Found in {glade}"]` with renderer stub blocking on a `threading.Event`.
     - `pass_once()` returns immediately while the stub is still blocked; run state is already "open".
     - Object row is `("box", "item", "live")`, ref `item_id` matches `^item_q_[0-9a-f]{12}$`.
     - `get_item(iid)` has category "tool", consumable True, properties.stat_bonuses == {stat: 5},
       properties.bonus_when == "carried", effects == {f"{stat}_change": 2},
       description == "Found in Glade" (placeholder `{glade}` rendered), image is None.
     - Releasing the event and joining the thread shows the stub ran once with `raise_errors=True`
       on a thread whose name starts with `"quest-item-image-"`.
 (a2) MediaGenerationDisabled:
     - Renderer stub raises `MediaGenerationDisabled("off")`; `threading.excepthook` recorder
       captures `[]` (no uncaught thread exception); run opens; item image remains None.
 (b) Validation (`quest_engine.validate_template`):
     - `effects: "{bad"` -> `[("setup_effects.0.type", "bad_json")]`.
     - `stat_bonuses: "[1]"` -> `[("setup_effects.0.type", "bad_json")]`.
     - `stat_bonuses: "{\"<stat>\": 200}"` (outside -100..100) -> `[("setup_effects.0.type", "bad_param")]`.
     - Valid JSON for both -> no issue at `setup_effects.0.*`, and starting + `pass_once()` opens.
 (c) place_item + item.discovered:
     - Setup `[box: create_item, spot: place_item item "box" room "glade" hidden True difficulty 3]`.
     - Stored placement in L1/r1 has quantity 1, hidden True, discovery_difficulty = 3 * 10 = 30.
     - Fresh avatar A (discovery stat absent -> effective 0 < 30): `placement_visible_to` is False,
       0 `item.discovered` events.
     - Set A's discovery stat to 35 (35 >= 30): `placement_visible_to` is True, 1 `item.discovered`
       event `{character: "A", location_id: "L1", room_id: "r1", item_id: iid}`.
     - Calling `placement_visible_to` for A again returns True and emits no second event (still 1).
     - Character B with discovery stat 35: returns True and emits 1 event for B (total 2).
 (d) remove_item_everywhere:
     - World item (stackable, max_stack 10) carried by A (qty 2, equipped via `equip_item`) and
       N (qty 1), placed in L1/r1 (hidden, difficulty 0) and L1/r2, discovered by A in L1/r1.
     - Step 1-2 unequips A and removes qty 2 from A (delta -2) and qty 1 from N (delta -1).
     - Step 3 removes both room placements (`remove_item_from_room` clears L1/r1's discovery row
       when qty reaches 0), so step 4's leftover `DELETE FROM item_discoveries` deletes 0 rows.
     - Step 5 deletes the item row and media.
     - Returned dict: `found=True, deleted=True, shared=False, unequipped=["A"],
       inventories=["A", "N"], placements=[["L1", "r1"], ["L1", "r2"]], discoveries=0`.
     - Afterwards: `get_item` is None, 0 SQL rows in `inventory_items`, item absent from A's
       `equipped_items`, absent from both rooms' `get_room_items`, 0 SQL rows in `item_discoveries`.
     - `inventory.changed` recorded delta -2 for A and delta -1 for N.
     - Shared item (monkeypatched `is_shared_item` -> True): returns `shared=True, deleted=False`,
       item remains untouched.
 (e) Proof on the old code (`cd58910b6`):
     - `git show cd58910b6:app/models/inventory.py` (skipped if git unavailable): AST-extracted
       `delete_item` source is identical between old and current file; old file has no
       `def remove_item_everywhere`.
     - Calling current `delete_item` on an item placed in a room leaves the room placement behind
       (proving why `remove_item_everywhere` is required).
 (f) Run end (pickup + completion + permanent reward):
     - Setup `[box: create_item, spot: place_item box glade hidden False]`, step 0 `at_place` on
       `turnin` (L1/r2), rewards `[charm: create_item name "Lucky charm" stat_bonuses ...
       bonus_when "carried", charm_given: give_item item "charm"]` (both permanent True).
     - Open via `pass_once()`. A picks up `box` from L1/r1 via `inventory.pick_up_item`.
     - Two `quest_engine.tick()` calls keep run `"open"` with `issues == []` (a picked-up
       placement does not break its run).
     - Move A to L1/r2, `evaluate("A")` -> `"done"`. `pass_once()` + `pass_once()`:
       - `box` gone everywhere (`get_item` None, A qty 0, `inventory.changed` delta -1 for A).
       - `box` row `"reverted"`, `spot` row `"gone"` (placement was already picked up before cleanup).
       - `charm` still exists, A holds 1 charm, `charm` and `charm_given` rows remain `"live"` (permanent).
 (g) Cancel while open:
     - Same setup (`box` + `spot` in L1/r1); `cancel_run` + `pass_once()` -> item and placement
       both gone; cleanup runs in reverse creation order so `spot` removes the placement
       (`"reverted"`) and `box` deletes the item (`"reverted"`).
 (h) Admin deletes quest item by hand while run is open:
     - Setup `[box: create_item]`, open; `inventory.delete_item(box_id)` by hand.
     - Tick 1: still `"open"`, `issues == []` (two consecutive ticks required).
     - Tick 2: `"broken"` with issue `("objects.box", "object_gone")`.
     - Cleanup `pass_once()` marks `box` row `"gone"` with no error.
 (i) give_item pending row (Task 5 ruling):
     - Monkeypatch `inventory.add_to_inventory` to snapshot the run's object rows before calling
       the original: exactly 1 row `(kind="grant", status="pending", ref={"character": "A",
       "item_id": ..., "quantity": 1, "before": 0})` exists BEFORE the write.
     - After `pass_once()`, the row is `"live"` and its ref has NO `"before"` key.
     - Reconciliation (`quest_objects.get_kind("grant").exists` with pending ref `before=0, qty=1`):
       True when A holds 1, False when A holds 0, None when `get_item_quantity` raises.
     - Remove with `before`: A held 1 before and the add failed (`current=1, before=1`) ->
       `remove` returns `"gone"` and A still holds 1.
 (j) Static checks:
     - `app/core/item_images.py` has no `"app.routes"`.
     - `app/routes/inventory.py`'s `generate_item_image_sync` source contains `"item_images"`.
     - `app/core/improvements/types/subjects.py` and `app/skills/outfit_creation_skill.py`
       import `generate_item_image_sync` from `app.core.item_images`.
 (k) Cleanup order (effects reverse creation order, rows within one effect creation order):
     - Stub object kind `"t_two"` appends `ref["tag"]` to `REMOVED` and returns `"done"`; stub
       effect `"t.two"` (owner `"test"`) creates two `"t_two"` objects tagged
       `"<effect_key>.1"` and `"<effect_key>.2"`.
     - Setup `[first: t.two, second: t.two]`; open via `pass_once()`, then `cancel_run` +
       `pass_once()`: `second` was created after `first`, so `second`'s rows go first in creation
       order (`second.1`, `second.2`), followed by `first`'s rows in creation order (`first.1`,
       `first.2`) -> `REMOVED == ["second.1", "second.2", "first.1", "first.2"]`, all 4 `"reverted"`.
     - Direct unit check of `quest_effects._cleanup_order` on two runs' hand-built rows:
       `(R1, a)` has ids 1, 3 (`first_id=1`); `(R2, x)` has ids 2, 5 (`first_id=2`);
       `(R1, b)` has ids 4, 6 (`first_id=4`). Sorting by `(-first_id, id)` yields ids
       `[4, 6, 2, 5, 1, 3]` (group `first_id=4`, then `first_id=2`, then `first_id=1`, each
       preserving ascending `id` inside the effect).
 (l) Restart reconciliation strips `"before"` from promoted pending grant row:
     - Ready template with roles `hero` (character -> A) and `thing` (item -> existing item I),
       setup `[g: give_item item "thing" to "hero"]`; `start_run` -> `"preparing"`.
     - Simulate crash after inventory write: `add_to_inventory("A", I, 1)` (A held 0 before) and
       `add_object(run_id, effect_key="g", position="setup", kind="grant",
       ref={"character": "A", "item_id": I, "quantity": 1, "before": 0}, status="pending")`.
     - `pass_once()`: `exists` checks `1 >= 0 + 1` -> True, so the entry is NOT re-applied; row is
       promoted to `"live"` with ref `{"character": "A", "item_id": I, "quantity": 1}` (no
       `"before"` key), A holds exactly 1, run state is `"open"`.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []
SECTION = [""]


def check(label, actual, expected):
    label = f"{SECTION[0]} {label}".strip()
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def section(name, title):
    SECTION[0] = name
    print(f"{name} {title}")


def _extract_func_source(src: str, func_name: str) -> str:
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    return ""


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-items-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import config, db, hooks, item_images, quest_effects as qfx
    from app.core import quest_engine as qe, quest_objects as qo, quest_types as qt
    from app.core.config_schema import field_default
    from app.core.game_time import GameTime
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import set_game_time
    from app.core.users import create_user, update_user
    from app.imagegen.base import MediaGenerationDisabled
    from app.models import character as chars, inventory, quests, world

    db.init_schema()
    qt.register()
    # Intentionally DO NOT call qe.register() — this smoke drives evaluate/tick/pass_once directly.

    stat = config.get("inventory.discovery_stat", field_default("inventory", "discovery_stat"))

    # Fixture
    world.upsert_location(
        {"id": "L1", "name": "Forest", "entry_room": "r1",
         "rooms": [{"id": "r1", "name": "Glade"}, {"id": "r2", "name": "Hollow"}]},
        sync_world=False,
    )
    world.upsert_location(
        {"id": "L2", "name": "Camp", "entry_room": "s1",
         "rooms": [{"id": "s1", "name": "Gate"}]},
        sync_world=False,
    )
    for name in ("A", "B", "N"):
        assert chars.save_character_profile(
            name, {"current_location": "L2", "current_room": "s1", "language": "en"}, create_new=True
        ), name
    uid = create_user("demo", "smoke-password", allowed_characters=["A", "B"])
    update_user(uid, settings={"active_character": "A"})
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    def set_stat(name: str, val):
        with keyed_lock("character_profile", name):
            prof = chars.get_character_profile(name) or {}
            se = dict(prof.get("status_effects") or {})
            if val is None:
                se.pop(stat, None)
            else:
                se[stat] = val
            prof["status_effects"] = se
            assert chars.save_character_profile(name, prof), name

    def move_char(name: str, loc: str, room: str):
        if chars.get_character_current_location(name) != loc:
            chars.save_character_current_location(name, loc)
        if chars.get_character_current_room(name) != room:
            chars.save_character_current_room(name, room)

    def end_and_clean(*run_ids):
        for rid in run_ids:
            qe.cancel_run(rid)
        qfx.pass_once()

    ROLES_GLADE = [
        {"key": "glade", "kind": "room", "description": "forest glade"},
        {"key": "turnin", "kind": "room", "description": "turn-in room"},
    ]
    BIND_GLADE = {
        "glade": {"location_id": "L1", "room_id": "r1"},
        "turnin": {"location_id": "L1", "room_id": "r2"},
    }
    AT_TURNIN = {"type": "at_place", "params": {"place": "turnin"}}

    def mk_tpl(title, *, roles=None, steps=None, setup_effects=None, rewards=None):
        return quests.create_template(
            state="ready",
            title=title,
            roles=ROLES_GLADE if roles is None else roles,
            steps=steps if steps is not None else [{"id": "s1", "text": "Go to hollow.", "condition": AT_TURNIN}],
            setup_effects=setup_effects or [],
            rewards=rewards or [],
        )

    orig_gen = item_images.generate_item_image_sync
    orig_excepthook = threading.excepthook
    try:
        # (a) ----------------------------------------------------------------------------------
        section("(a)", "create_item creates item, renders placeholders, starts non-blocking image thread")
        gate = threading.Event()
        started = threading.Event()
        render_calls = []
        render_threads = []

        def _blocking_stub(item_id, overrides=None, *, raise_errors=False):
            t = threading.current_thread()
            render_calls.append((item_id, raise_errors, t.name))
            render_threads.append(t)
            started.set()
            gate.wait(timeout=5.0)
            return True

        item_images.generate_item_image_sync = _blocking_stub
        tpl_a = mk_tpl(
            "Create Box A",
            setup_effects=[{
                "key": "box",
                "type": "create_item",
                "params": {
                    "name": "Old tin box",
                    "category": "tool",
                    "stat_bonuses": json.dumps({stat: 5}),
                    "bonus_when": "carried",
                    "effects": json.dumps({f"{stat}_change": 2}),
                    "consumable": True,
                    "description": "Found in {glade}",
                },
            }],
        )
        ra = qe.start_run(tpl_a["id"], BIND_GLADE)
        res_a = qfx.pass_once()
        check("pass_once returned while renderer still blocked", gate.is_set(), False)
        check("run already open", (res_a["opened"], quests.get_run(ra["id"])["state"]), ([ra["id"]], "open"))
        objs_a = quests.list_objects(ra["id"])
        check("box object row shape",
              [(o["effect_key"], o["kind"], o["status"]) for o in objs_a],
              [("box", "item", "live")])
        box_id_a = objs_a[0]["ref"]["item_id"]
        check("minted item_id matches ^item_q_[0-9a-f]{12}$",
              bool(re.fullmatch(r"item_q_[0-9a-f]{12}", box_id_a)), True)
        item_a = inventory.get_item(box_id_a)
        check("stored item fields",
              (
                  item_a["category"],
                  item_a["consumable"],
                  item_a["properties"]["stat_bonuses"],
                  item_a["properties"]["bonus_when"],
                  item_a["effects"],
                  item_a["description"],
                  item_a["image"],
              ),
              ("tool", True, {stat: 5}, "carried", {f"{stat}_change": 2}, "Found in Glade", None))
        check("background thread reached stub", started.wait(timeout=5.0), True)
        gate.set()
        for t in render_threads:
            t.join(timeout=5.0)
        check("stub ran once with raise_errors=True on quest-item-image-* thread",
              (len(render_calls),
               render_calls[0][0] if render_calls else "",
               render_calls[0][1] if render_calls else None,
               render_calls[0][2].startswith("quest-item-image-") if render_calls else False),
              (1, box_id_a, True, True))
        end_and_clean(ra["id"])

        # (a2) ---------------------------------------------------------------------------------
        section("(a2)", "MediaGenerationDisabled is swallowed cleanly in background render thread")
        uncaught = []
        a2_done = threading.Event()
        a2_threads = []

        def _excepthook(args):
            uncaught.append(args.exc_value)

        def _disabled_stub(item_id, overrides=None, *, raise_errors=False):
            a2_threads.append(threading.current_thread())
            try:
                raise MediaGenerationDisabled("media off")
            finally:
                a2_done.set()

        threading.excepthook = _excepthook
        item_images.generate_item_image_sync = _disabled_stub
        try:
            tpl_a2 = mk_tpl(
                "Create Box A2",
                setup_effects=[{"key": "box", "type": "create_item", "params": {"name": "Quiet box"}}],
            )
            ra2 = qe.start_run(tpl_a2["id"], BIND_GLADE)
            qfx.pass_once()
            check("a2 run open", quests.get_run(ra2["id"])["state"], "open")
            check("a2 stub ran", a2_done.wait(timeout=5.0), True)
            for t in a2_threads:
                t.join(timeout=5.0)
            a2_iid = quests.list_objects(ra2["id"])[0]["ref"]["item_id"]
            check("a2 item image stays None", inventory.get_item(a2_iid)["image"], None)
            check("no uncaught thread exceptions", uncaught, [])
            end_and_clean(ra2["id"])
        finally:
            threading.excepthook = orig_excepthook

        # Install a fast no-op stub for all remaining sections (no real media)
        item_images.generate_item_image_sync = lambda item_id, overrides=None, *, raise_errors=False: True

        # (b) ----------------------------------------------------------------------------------
        section("(b)", "create_item template validation rejects bad JSON and out-of-range bonuses")
        base_b = {
            "title": "Val B",
            "roles": ROLES_GLADE,
            "steps": [{"id": "s1", "text": "Go.", "condition": AT_TURNIN}],
        }
        iss_b1 = qe.validate_template({
            **base_b,
            "setup_effects": [{"key": "box", "type": "create_item",
                               "params": {"name": "Bad", "effects": "{not json"}}],
        })
        check("bad JSON effects -> bad_json",
              [(i["path"], i["code"]) for i in iss_b1],
              [("setup_effects.0.type", "bad_json")])
        iss_b2 = qe.validate_template({
            **base_b,
            "setup_effects": [{"key": "box", "type": "create_item",
                               "params": {"name": "Bad", "stat_bonuses": "[1]"}}],
        })
        check("non-object stat_bonuses -> bad_json",
              [(i["path"], i["code"]) for i in iss_b2],
              [("setup_effects.0.type", "bad_json")])
        iss_b3 = qe.validate_template({
            **base_b,
            "setup_effects": [{"key": "box", "type": "create_item",
                               "params": {"name": "Bad", "stat_bonuses": json.dumps({stat: 200})}}],
        })
        check("out-of-range stat_bonuses -> bad_param",
              [(i["path"], i["code"]) for i in iss_b3],
              [("setup_effects.0.type", "bad_param")])
        valid_b_setup = [{
            "key": "box",
            "type": "create_item",
            "params": {
                "name": "Good",
                "effects": json.dumps({f"{stat}_change": 3}),
                "stat_bonuses": json.dumps({stat: 10}),
                "bonus_when": "carried",
            },
        }]
        iss_b4 = qe.validate_template({**base_b, "setup_effects": valid_b_setup})
        check("valid create_item -> no issues at setup_effects.0.*",
              [i for i in iss_b4 if i["path"].startswith("setup_effects.0")], [])
        tpl_b = mk_tpl("Valid B", setup_effects=valid_b_setup)
        rb = qe.start_run(tpl_b["id"], BIND_GLADE)
        qfx.pass_once()
        check("valid template run opens cleanly", quests.get_run(rb["id"])["state"], "open")
        end_and_clean(rb["id"])

        # (c) ----------------------------------------------------------------------------------
        section("(c)", "place_item difficulty scaling and item.discovered hook")
        discovered_events = []
        disc_active = [True]

        def _on_discovered(**kw):
            if disc_active[0]:
                discovered_events.append(kw)

        hooks.register("item.discovered", _on_discovered, tag="smoke_quest_items")
        try:
            tpl_c = mk_tpl(
                "Place C",
                setup_effects=[
                    {"key": "box", "type": "create_item", "params": {"name": "Hidden tin"}},
                    {"key": "spot", "type": "place_item",
                     "params": {"item": "box", "room": "glade", "hidden": True, "difficulty": 3}},
                ],
            )
            rc = qe.start_run(tpl_c["id"], BIND_GLADE)
            qfx.pass_once()
            check("run C open", quests.get_run(rc["id"])["state"], "open")
            c_iid = {o["effect_key"]: o for o in quests.list_objects(rc["id"])}["box"]["ref"]["item_id"]
            pl_c = next((p for p in inventory.get_room_items("L1", "r1") if p.get("item_id") == c_iid), None)
            check("placement fields (qty=1, hidden=True, difficulty=30)",
                  (pl_c["quantity"], pl_c["hidden"], pl_c["discovery_difficulty"]) if pl_c else None,
                  (1, True, 30))

            set_stat("A", None)
            check("A without discovery stat cannot see it",
                  inventory.placement_visible_to("A", "L1", "r1", pl_c), False)
            check("0 item.discovered events", discovered_events, [])

            set_stat("A", 35)
            check("A with stat 35 discovers it",
                  inventory.placement_visible_to("A", "L1", "r1", pl_c), True)
            check("1 item.discovered event for A",
                  discovered_events,
                  [{"character": "A", "location_id": "L1", "room_id": "r1", "item_id": c_iid}])

            check("second read for A stays True",
                  inventory.placement_visible_to("A", "L1", "r1", pl_c), True)
            check("still 1 item.discovered event", len(discovered_events), 1)

            set_stat("B", 35)
            check("B with stat 35 discovers it",
                  inventory.placement_visible_to("B", "L1", "r1", pl_c), True)
            check("2 total item.discovered events (A then B)",
                  discovered_events,
                  [
                      {"character": "A", "location_id": "L1", "room_id": "r1", "item_id": c_iid},
                      {"character": "B", "location_id": "L1", "room_id": "r1", "item_id": c_iid},
                  ])
            end_and_clean(rc["id"])
        finally:
            disc_active[0] = False

        # (d) ----------------------------------------------------------------------------------
        section("(d)", "remove_item_everywhere clears all five places and spares shared items")
        d_item = inventory.add_item("Token D", stackable=True, max_stack=10)["id"]
        with keyed_lock("character_profile", "A"):
            assert inventory.add_to_inventory("A", d_item, 2)
            assert inventory.equip_item("A", d_item).get("status") == "ok"
        with keyed_lock("character_profile", "N"):
            assert inventory.add_to_inventory("N", d_item, 1)
        assert inventory.add_item_to_room("L1", "r1", d_item, 1, hidden=True, discovery_difficulty=10)
        assert inventory.add_item_to_room("L1", "r2", d_item, 1, hidden=False)
        pl_d1 = next(p for p in inventory.get_room_items("L1", "r1") if p["item_id"] == d_item)
        assert inventory.placement_visible_to("A", "L1", "r1", pl_d1) is True

        d_inv_events = []
        d_active = [True]

        def _on_d_inv(**kw):
            if d_active[0] and kw.get("item_id") == d_item:
                d_inv_events.append(kw)

        hooks.register("inventory.changed", _on_d_inv, tag="smoke_quest_items_d")
        try:
            res_d = inventory.remove_item_everywhere(d_item)
        finally:
            d_active[0] = False

        check("remove_item_everywhere returned dict",
              res_d,
              {
                  "item_id": d_item,
                  "shared": False,
                  "found": True,
                  "deleted": True,
                  "unequipped": ["A"],
                  "inventories": ["A", "N"],
                  "placements": [["L1", "r1"], ["L1", "r2"]],
                  "discoveries": 0,
              })
        inv_sql = db.get_connection().execute(
            "SELECT COUNT(*) FROM inventory_items WHERE item_id=?", (d_item,)
        ).fetchone()[0]
        disc_sql = db.get_connection().execute(
            "SELECT COUNT(*) FROM item_discoveries WHERE item_id=?", (d_item,)
        ).fetchone()[0]
        check("nothing left in any of the five places",
              (
                  inventory.get_item(d_item),
                  inv_sql,
                  d_item in inventory.get_equipped_items("A"),
                  any(p["item_id"] == d_item for p in inventory.get_room_items("L1", "r1")),
                  any(p["item_id"] == d_item for p in inventory.get_room_items("L1", "r2")),
                  disc_sql,
              ),
              (None, 0, False, False, False, 0))
        check("inventory.changed events (-2 for A, -1 for N)",
              d_inv_events,
              [
                  {"character": "A", "item_id": d_item, "delta": -2},
                  {"character": "N", "item_id": d_item, "delta": -1},
              ])

        shared_item = inventory.add_item("Shared Relic")["id"]
        orig_is_shared = inventory.is_shared_item
        inventory.is_shared_item = lambda iid: True if iid == shared_item else orig_is_shared(iid)
        try:
            res_shared = inventory.remove_item_everywhere(shared_item)
        finally:
            inventory.is_shared_item = orig_is_shared
        check("shared item untouched",
              (res_shared["shared"], res_shared["deleted"], inventory.get_item(shared_item) is not None),
              (True, False, True))
        inventory.delete_item(shared_item)

        # (e) ----------------------------------------------------------------------------------
        section("(e)", "proof on old code (cd58910b6): delete_item unchanged and leaves placements")
        res_git = subprocess.run(
            ["git", "show", "cd58910b6:app/models/inventory.py"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if res_git.returncode != 0:
            print("  skip proof: git show cd58910b6 unavailable")
        else:
            cur_src = (ROOT / "app" / "models" / "inventory.py").read_text(encoding="utf-8")
            check("delete_item source identical to cd58910b6",
                  _extract_func_source(cur_src, "delete_item") == _extract_func_source(res_git.stdout, "delete_item"),
                  True)
            check("old code has no def remove_item_everywhere",
                  "def remove_item_everywhere" in res_git.stdout, False)

        e_item = inventory.add_item("Orphan Placement")["id"]
        assert inventory.add_item_to_room("L1", "r1", e_item, 1)
        check("delete_item returns True", inventory.delete_item(e_item), True)
        check("room placement still present after delete_item",
              any(p["item_id"] == e_item for p in inventory.get_room_items("L1", "r1")), True)
        inventory.remove_item_from_room("L1", "r1", e_item, 1)

        # (f) ----------------------------------------------------------------------------------
        section("(f)", "run end: pickup does not break run, box cleaned everywhere, permanent charm kept")
        move_char("A", "L2", "s1")
        tpl_f = mk_tpl(
            "Bring Box F",
            setup_effects=[
                {"key": "box", "type": "create_item", "params": {"name": "Quest tin box"}},
                {"key": "spot", "type": "place_item",
                 "params": {"item": "box", "room": "glade", "hidden": False}},
            ],
            steps=[{"id": "s1", "text": "Bring the box to the hollow.", "condition": AT_TURNIN}],
            rewards=[
                {"key": "charm", "type": "create_item",
                 "params": {"name": "Lucky charm", "stat_bonuses": json.dumps({stat: 4}), "bonus_when": "carried"},
                 "permanent": True},
                {"key": "charm_given", "type": "give_item",
                 "params": {"item": "charm"}, "permanent": True},
            ],
        )
        rf = qe.start_run(tpl_f["id"], BIND_GLADE)
        qfx.pass_once()
        check("run F open", quests.get_run(rf["id"])["state"], "open")
        f_box_id = {o["effect_key"]: o for o in quests.list_objects(rf["id"])}["box"]["ref"]["item_id"]

        pickup = inventory.pick_up_item("A", "L1", "r1", f_box_id, 1)
        check("A picks up box", pickup.get("success"), True)
        qe.tick()
        qe.tick()
        rf_mid = quests.get_run(rf["id"])
        check("picked-up placement keeps run open after two ticks",
              (rf_mid["state"], rf_mid.get("issues") or []), ("open", []))

        f_box_events = []
        f_active = [True]

        def _on_f_inv(**kw):
            if f_active[0] and kw.get("item_id") == f_box_id:
                f_box_events.append(kw)

        hooks.register("inventory.changed", _on_f_inv, tag="smoke_quest_items_f")
        try:
            move_char("A", "L1", "r2")
            qe.evaluate("A")
            check("run F done", quests.get_run(rf["id"])["state"], "done")
            qfx.pass_once()
            qfx.pass_once()
        finally:
            f_active[0] = False

        objs_f = {o["effect_key"]: o for o in quests.list_objects(rf["id"])}
        f_charm_id = objs_f["charm"]["ref"]["item_id"]
        check("box gone everywhere and inventory.changed -1 for A",
              (inventory.get_item(f_box_id), inventory.get_item_quantity("A", f_box_id), f_box_events),
              (None, 0, [{"character": "A", "item_id": f_box_id, "delta": -1}]))
        check("box reverted, spot gone",
              (objs_f["box"]["status"], objs_f["spot"]["status"]),
              ("reverted", "gone"))
        check("permanent charm kept and held by A",
              (
                  inventory.get_item(f_charm_id) is not None,
                  inventory.get_item_quantity("A", f_charm_id),
                  objs_f["charm"]["status"],
                  bool(objs_f["charm"]["permanent"]),
                  objs_f["charm_given"]["status"],
                  bool(objs_f["charm_given"]["permanent"]),
              ),
              (True, 1, "live", True, "live", True))
        move_char("A", "L2", "s1")

        # (g) ----------------------------------------------------------------------------------
        section("(g)", "cancel while open reverts both placement and item")
        tpl_g = mk_tpl(
            "Cancel G",
            setup_effects=[
                {"key": "box", "type": "create_item", "params": {"name": "Cancel tin box"}},
                {"key": "spot", "type": "place_item",
                 "params": {"item": "box", "room": "glade", "hidden": False}},
            ],
        )
        rg = qe.start_run(tpl_g["id"], BIND_GLADE)
        qfx.pass_once()
        g_box_id = {o["effect_key"]: o for o in quests.list_objects(rg["id"])}["box"]["ref"]["item_id"]
        check("cancel_run True", qe.cancel_run(rg["id"]), True)
        qfx.pass_once()
        objs_g = {o["effect_key"]: o for o in quests.list_objects(rg["id"])}
        check("item and placement gone, both rows reverted",
              (
                  inventory.get_item(g_box_id),
                  any(p["item_id"] == g_box_id for p in inventory.get_room_items("L1", "r1")),
                  objs_g["box"]["status"],
                  objs_g["spot"]["status"],
              ),
              (None, False, "reverted", "reverted"))

        # (h) ----------------------------------------------------------------------------------
        section("(h)", "admin deletes quest item by hand -> broken after two ticks, cleanup records gone")
        tpl_h = mk_tpl(
            "Manual Delete H",
            setup_effects=[{"key": "box", "type": "create_item", "params": {"name": "Fragile box"}}],
        )
        rh = qe.start_run(tpl_h["id"], BIND_GLADE)
        qfx.pass_once()
        h_box_id = quests.list_objects(rh["id"])[0]["ref"]["item_id"]
        check("admin delete_item True", inventory.delete_item(h_box_id), True)
        qe.tick()
        check("still open after 1st tick", quests.get_run(rh["id"])["state"], "open")
        qe.tick()
        rh_after = quests.get_run(rh["id"])
        check("broken after 2nd tick with object_gone at objects.box",
              (rh_after["state"], [(i["path"], i["code"]) for i in rh_after["issues"]]),
              ("broken", [("objects.box", "object_gone")]))
        qfx.pass_once()
        check("box row marked gone after cleanup",
              quests.list_objects(rh["id"])[0]["status"], "gone")

        # (i) ----------------------------------------------------------------------------------
        section("(i)", "give_item writes pending grant row with before BEFORE add_to_inventory")
        i_item = inventory.add_item("Grant Token", stackable=True, max_stack=10)["id"]
        tpl_i = mk_tpl(
            "Grant Pending I",
            roles=ROLES_GLADE + [{"key": "thing", "kind": "item", "description": "token"}],
            steps=[{"id": "s1", "text": "Go.", "condition": AT_TURNIN}],
            rewards=[{"key": "gift", "type": "give_item", "params": {"item": "thing"}, "permanent": True}],
        )
        ri = qe.start_run(tpl_i["id"], {**BIND_GLADE, "thing": {"item_id": i_item}})
        move_char("A", "L1", "r2")
        qe.evaluate("A")
        check("run I done", quests.get_run(ri["id"])["state"], "done")

        seen_before_write = []
        orig_add_inv = inventory.add_to_inventory

        def _spy_add_inv(character_name, item_id, *args, **kwargs):
            if character_name == "A" and item_id == i_item:
                rows_now = [o for o in quests.list_objects(ri["id"]) if o["effect_key"] == "gift"]
                seen_before_write.append(
                    [(o["kind"], o["status"], dict(o["ref"])) for o in rows_now]
                )
            return orig_add_inv(character_name, item_id, *args, **kwargs)

        inventory.add_to_inventory = _spy_add_inv
        try:
            qfx.pass_once()
        finally:
            inventory.add_to_inventory = orig_add_inv

        check("pending row with before=0 existed BEFORE add_to_inventory",
              seen_before_write,
              [[("grant", "pending", {"character": "A", "item_id": i_item, "quantity": 1, "before": 0})]])
        live_i = [o for o in quests.list_objects(ri["id"]) if o["effect_key"] == "gift"]
        check("live grant row has no before key",
              [(o["kind"], o["status"], o["ref"]) for o in live_i],
              [("grant", "live", {"character": "A", "item_id": i_item, "quantity": 1})])

        grant_kind = qo.get_kind("grant")
        pending_ref = {"character": "A", "item_id": i_item, "quantity": 1, "before": 0}
        check("pending grant exists True when A holds 1", grant_kind.exists(pending_ref), True)
        orig_qty = inventory.get_item_quantity
        inventory.get_item_quantity = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db busy"))
        try:
            check("pending grant exists None when get_item_quantity raises", grant_kind.exists(pending_ref), None)
        finally:
            inventory.get_item_quantity = orig_qty

        # Remove with before when A held 1 before and add failed (current=1, before=1)
        failed_add_ref = {"character": "A", "item_id": i_item, "quantity": 1, "before": 1}
        check("remove pending grant when current==before returns gone and keeps A's item",
              (grant_kind.remove(failed_add_ref), inventory.get_item_quantity("A", i_item)),
              ("gone", 1))
        with keyed_lock("character_profile", "A"):
            inventory.remove_from_inventory("A", i_item, quantity=1, force=True)
        check("pending grant exists False when A holds 0", grant_kind.exists(pending_ref), False)
        move_char("A", "L2", "s1")

        # (j) ----------------------------------------------------------------------------------
        section("(j)", "static checks on item_images module and callers")
        core_img_src = (ROOT / "app" / "core" / "item_images.py").read_text(encoding="utf-8")
        check("app/core/item_images.py has no app.routes", "app.routes" in core_img_src, False)
        route_inv_src = (ROOT / "app" / "routes" / "inventory.py").read_text(encoding="utf-8")
        route_gen_src = _extract_func_source(route_inv_src, "generate_item_image_sync")
        check("route generate_item_image_sync delegates to item_images", "item_images" in route_gen_src, True)
        subjects_src = (ROOT / "app" / "core" / "improvements" / "types" / "subjects.py").read_text(encoding="utf-8")
        check("subjects.py imports generate_item_image_sync from app.core.item_images",
              "from app.core.item_images import generate_item_image_sync" in subjects_src, True)
        outfit_src = (ROOT / "app" / "skills" / "outfit_creation_skill.py").read_text(encoding="utf-8")
        check("outfit_creation_skill.py imports generate_item_image_sync from app.core.item_images",
              "from app.core.item_images import generate_item_image_sync" in outfit_src, True)

        # (k) ----------------------------------------------------------------------------------
        section("(k)", "cleanup order: reverse across effects, creation order within one effect")
        from app.core import quest_catalog as qc
        removed_tags = []
        qo.register_kind(
            "t_two",
            exists=lambda ref: True,
            remove=lambda ref: removed_tags.append(ref["tag"]) or "done",
            label=lambda ref: str(ref.get("tag") or ""),
        )

        def _apply_two(params, ctx):
            return [
                qfx.CreatedObject("t_two", {"tag": f"{ctx.effect_key}.1"}, f"{ctx.effect_key}.1"),
                qfx.CreatedObject("t_two", {"tag": f"{ctx.effect_key}.2"}, f"{ctx.effect_key}.2"),
            ]

        qc.register("test", lambda: [
            qc.QuestType(
                id="t.two",
                kind="effect",
                label="Two objects",
                description="stub two-row effect",
                params=(),
                apply=_apply_two,
                object_kind="t_two",
            )
        ])
        try:
            tpl_k = mk_tpl(
                "Cleanup Order K",
                setup_effects=[
                    {"key": "first", "type": "t.two", "params": {}},
                    {"key": "second", "type": "t.two", "params": {}},
                ],
            )
            rk = qe.start_run(tpl_k["id"], BIND_GLADE)
            qfx.pass_once()
            check("run K open", quests.get_run(rk["id"])["state"], "open")
            check("cancel K True", qe.cancel_run(rk["id"]), True)
            qfx.pass_once()
            check("removal order: second.1, second.2, first.1, first.2",
                  removed_tags, ["second.1", "second.2", "first.1", "first.2"])
            check("all four rows reverted",
                  [o["status"] for o in quests.list_objects(rk["id"])],
                  ["reverted", "reverted", "reverted", "reverted"])
        finally:
            hooks.unregister_owned_providers("test")

        sample_rows = [
            {"id": 1, "run_id": "R1", "effect_key": "a"},
            {"id": 2, "run_id": "R2", "effect_key": "x"},
            {"id": 3, "run_id": "R1", "effect_key": "a"},
            {"id": 4, "run_id": "R1", "effect_key": "b"},
            {"id": 5, "run_id": "R2", "effect_key": "x"},
            {"id": 6, "run_id": "R1", "effect_key": "b"},
        ]
        check("_cleanup_order across two runs",
              [r["id"] for r in qfx._cleanup_order(sample_rows)],
              [4, 6, 2, 5, 1, 3])

        # (l) ----------------------------------------------------------------------------------
        section("(l)", "restart reconciliation strips before from promoted pending grant row")
        l_item = inventory.add_item("Reconcile Token", stackable=True, max_stack=10)["id"]
        tpl_l = mk_tpl(
            "Reconcile Grant L",
            roles=[
                {"key": "hero", "kind": "character", "description": "recipient"},
                {"key": "thing", "kind": "item", "description": "token"},
                {"key": "turnin", "kind": "room", "description": "turn-in room"},
            ],
            setup_effects=[{"key": "g", "type": "give_item", "params": {"item": "thing", "to": "hero"}}],
        )
        rl = qe.start_run(tpl_l["id"], {
            "hero": {"name": "A"},
            "thing": {"item_id": l_item},
            "turnin": {"location_id": "L1", "room_id": "r2"},
        })
        check("run L preparing", rl["state"], "preparing")
        assert inventory.add_to_inventory("A", l_item, 1)
        quests.add_object(
            rl["id"],
            effect_key="g",
            position="setup",
            kind="grant",
            ref={"character": "A", "item_id": l_item, "quantity": 1, "before": 0},
            status="pending",
        )
        qfx.pass_once()
        rows_l = [o for o in quests.list_objects(rl["id"]) if o["effect_key"] == "g"]
        check("promoted to live without before",
              [(o["status"], o["ref"]) for o in rows_l],
              [("live", {"character": "A", "item_id": l_item, "quantity": 1})])
        check("A holds exactly 1 (not paid twice)", inventory.get_item_quantity("A", l_item), 1)
        check("run L open", quests.get_run(rl["id"])["state"], "open")
        end_and_clean(rl["id"])
    finally:
        item_images.generate_item_image_sync = orig_gen
        threading.excepthook = orig_excepthook
        qfx._reset_for_tests()

    if FAILURES:
        print(f"FAIL smoke_quest_items: {len(FAILURES)} failures: {FAILURES}")
        return 1
    print("PASS smoke_quest_items: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
