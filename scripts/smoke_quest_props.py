#!/usr/bin/env python3
"""Smoke: quest prop effects (create_prop, place_prop), object kinds, room_prop removal, and D17 tagging.

Quest system stage 2, Task 8 (D5, D6, D8, D9, D12, D17). Throwaway storage
(``paths.init(<tmpdir>)`` BEFORE any world-DB module), no server, no LLM, no media
(``props.trigger_generation``, ``props.is_pending``, ``quest_effects._prop_has_model``,
and ``quest_effects._prop_media_problem`` are monkeypatched).

Usage:
    ./.venv/bin/python scripts/smoke_quest_props.py

FIXTURE
    Location L1 ("Wood", pos_x=100.0, pos_z=-50.0, map3d.boundary square) with
    rooms "glade" (layout {x: 0, y: 0, w: 6, d: 4}) and "hollow" (layout {x: 6, y: 0, w: 4, d: 4}).
    Character N (NPC) for the giver role.
    Game clock: Y0001-D010T12:00:00.

WHAT FOLLOWS BY HAND
 (a) create_prop near a location:
     - Params: name "Big rock", prompt "a large mossy boulder", height_m 2.0 (width_m/depth_m omitted),
       near "wood", offset_x 12, offset_z -4, yaw 45.
     - Missing dims fill to largest given (2.0) -> dims 2/2/2 -> max_dim = 2.0 ->
       face_num = clamp(6000 * 2.0, 2000..20000) = 12000; texture_size = 2048 (2.0 >= 1.5).
     - After first pass_once(): run stays "preparing", exactly 1 trigger call with
       face_num=12000 and texture_size=2048; sidecar exists with source == "generated"
       and quest_run == run_id; object rows for key "rock" in id order are
       ("world_prop", "pending") then ("prop", "pending"); list_world_props() has 0 rows.
 (b) model lands + scope_at:
     - Mark pid modeled and not pending -> pass_once() opens the run.
     - World prop row: x = 100.0 + 12.0 = 112.0, z = -50.0 + (-4.0) = -54.0, yaw_deg = 45.0.
     - Both object rows are "live"; live_object_refs(run_id)["rock"] has "placement_id"
       (the placement row, not the library row) and its "written" equals the stored row.
     - The prop row ref is exactly {"prop_id": pid}.
     - scope_at(template, "step:0").objects["rock"] == "world_prop"; with room instead of near
       it is "room_prop".
 (c) media off:
     - _prop_media_problem returns "Media generation is off: test".
     - pass_once() keeps run "preparing" with 1 issue at "setup_effects.0" with that message;
       0 trigger calls; no new prop sidecar created.
 (d) mesh failed + retry:
     - Start + pass_once() -> 1 trigger. Remove pid from PENDING without adding to MODELED.
     - pass_once() -> run stays "preparing" with issue code "mesh_failed".
     - quest_effects.retry(run_id) + pass_once() -> issues cleared, 2nd trigger call for the
       SAME pid, still 1 prop directory for this run; then model lands -> open.
 (e) mesh timeout:
     - Keep pid in PENDING. Patch timeutils.utc_now to prop_row.created_at + 31 min (1860 s > 1800 s)
       -> pass_once() fails with issue code "mesh_timeout".
     - Fresh run with utc_now patched to created_at + 29 min (1740 s <= 1800 s) -> no issue,
       still preparing.
 (f) restart while preparing with running mesh:
     - quest_effects._reset_for_tests() while pid is still in PENDING -> pass_once() makes
       0 new trigger calls, creates no second prop directory and no extra object row
       (rows for key == 2, new prop dirs == 1).
 (g) world cap:
     - Set world_props.MAX_WORLD_PROPS = count_world_props() -> pass_once() fails non-retryably
       before creating anything (0 triggers, 0 new prop dirs).
 (h) room placement + full room read-back:
     - create_prop with room "glade" (w=6, d=4) -> at = [6/2, 4/2] = [3.0, 2.0].
     - After model lands -> glade's layout.props has entry with minted place_id, prop_id == pid,
       at == [3.0, 2.0]; room_prop ref has exact keys {"location_id", "room_id", "place_id", "prop_id"}.
     - Monkeypatch world.append_room_props to return True without writing -> pass_once() records
       an issue (read-back caught the silent drop).
 (i) place_prop:
     - Unknown prop_id -> start_run raises QuestRefused with issue code "unknown_prop".
     - Real untagged library prop -> start_run + 1 pass_once() writes placement and opens run
       immediately (0 trigger calls).
 (j) cancel while mesh is running:
     - cancel_run + pass_once() -> placement row "gone" (never written), prop row "revert_pending",
       sidecar still exists.
     - Remove pid from PENDING + pass_once() -> prop row "reverted", sidecar gone,
       invalidate_prop_lib_token called >= 1 time.
 (k) cancel after open:
     - Open run with world prop; add an extra hand-made layout.props entry for the quest prop
       in room "hollow".
     - cancel_run + pass_once() -> world placement deleted (row "reverted"), prop deleted
       (row "reverted"), and the extra placement in "hollow" is removed too.
 (l) admin edit respected:
     - place_prop of library prop near wood -> open -> edit placement by hand (x -> 125.0).
     - cancel_run + pass_once() -> row status "gone" and the edited placement (x == 125.0) remains.
 (m) exclusion (D17):
     - room_furnish._library() excludes a tagged quest prop and includes an untagged library prop.
     - content_io.export_prop_to_zip(<tagged>) raises ValueError.
 (n) permanent prop (D17):
     - create_prop with permanent=True -> open -> cancel_run -> pass_once() -> prop and placement
       still exist, object rows stay "live", sidecar has no "quest_run" key.
 (o) remove_room_props unit:
     - Room with two entries -> remove one id -> returns 1 and only the other remains;
       removing an unknown id -> returns 0.
 (p) EffectFailed default code:
     - quest_effects.EffectFailed("x").code == "effect_failed".
 (q) boot order (static):
     - In app/server.py, "quest_effects.start()" appears exactly once and at a character index
       strictly greater than "start_resumer()".
 (r) Retry after mesh_timeout:
     - Start create_prop run + pass_once() -> 1 trigger, pid stays in PENDING.
     - Patch timeutils.utc_now to created_at + 31 min (1860 s > 1800 s) -> pass_once() ->
       issue code "mesh_timeout" and prop row ref has mesh_failed == True.
     - quest_effects.retry(run_id) -> True; pass_once() at the same patched time (+31 min) ->
       issues == [], still "preparing", still 1 trigger call (mesh still running, no re-trigger),
       prop row ref has no "mesh_failed" key and mesh_started_at == (created_at + 31 min) ISO.
     - pass_once() at created_at + 31 + 29 = +60 min (29 min <= 30 min from new anchor) ->
       issues == [], still "preparing".
     - pass_once() at created_at + 31 + 31 = +62 min (31 min > 30 min from new anchor) ->
       issue code "mesh_timeout" again.
 (s) Restart reconcile after placement was written:
     - Start create_prop (near) + pass_once() -> rows ("world_prop", "pending"), ("prop", "pending").
     - Simulate crash after model landed and placement was written: add pid to MODELED, remove
       from PENDING, write world prop by hand with the pending row's placement_id.
     - quest_effects._reset_for_tests() + pass_once() -> run opens, both rows "live", exactly 1
       world prop row with that id, 0 new trigger calls, prop row ref == {"prop_id": pid}
       (pending-only keys stripped), world_prop ref has no mesh_failed / mesh_started_at / before.
     - cancel_run + pass_once() -> placement and prop both removed, both rows "reverted"
       (empty written dict skips edit comparison).
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
from datetime import timedelta
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


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-props-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__

    from app.core import content_io, db, props, quest_effects as qfx
    from app.core import quest_engine as qe, quest_types as qt
    from app.core import room_furnish, scene_recipe, timeutils
    from app.core.game_time import GameTime
    from app.core.timeutils import set_game_time
    from app.models import character as chars, quests, world, world_props

    db.init_schema()
    qt.register()
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))

    # Fixture: one location with map coordinates + boundary and two rooms; one NPC.
    world.upsert_location(
        {
            "id": "L1",
            "name": "Wood",
            "pos_x": 100.0,
            "pos_z": -50.0,
            "entry_room": "glade",
            "map3d": {"boundary": [[-20.0, -20.0], [20.0, -20.0], [20.0, 20.0], [-20.0, 20.0]]},
            "rooms": [
                {"id": "glade", "name": "Glade", "layout": {"x": 0, "y": 0, "w": 6, "d": 4}},
                {"id": "hollow", "name": "Hollow", "layout": {"x": 6, "y": 0, "w": 4, "d": 4}},
            ],
        },
        sync_world=False,
    )
    assert chars.save_character_profile(
        "N",
        {
            "name": "N",
            "current_location": "L1",
            "current_room": "glade",
            "status_effects": {},
        },
        create_new=True,
    )

    # Stubs: no GPU, no media call anywhere.
    triggers = []
    pending_pids = set()
    modeled_pids = set()
    media_problem = [""]
    invalidate_calls = [0]

    def fake_trigger(prop_id, **kwargs):
        triggers.append((prop_id, dict(kwargs)))
        pending_pids.add(prop_id)
        return True

    def fake_is_pending(prop_id=""):
        if prop_id:
            return [prop_id] if prop_id in pending_pids else []
        return sorted(pending_pids)

    orig_invalidate = scene_recipe.invalidate_prop_lib_token

    def counting_invalidate():
        invalidate_calls[0] += 1
        return orig_invalidate()

    props.trigger_generation = fake_trigger
    props.is_pending = fake_is_pending
    qfx._prop_has_model = lambda pid: pid in modeled_pids
    qfx._prop_media_problem = lambda: media_problem[0]
    scene_recipe.invalidate_prop_lib_token = counting_invalidate

    BASE_ROLES = [
        {"key": "giver", "kind": "character", "description": "who asks"},
        {"key": "wood", "kind": "location", "description": "the wood"},
        {"key": "glade", "kind": "room", "description": "the glade"},
    ]
    BASE_BINDINGS = {
        "giver": {"name": "N"},
        "wood": {"location_id": "L1"},
        "glade": {"location_id": "L1", "room_id": "glade"},
    }

    def make_tpl(title, setup_effects, *, key="rock"):
        return quests.create_template(
            title=title,
            summary="{giver} lost something near {wood}.",
            giver_role="giver",
            roles=copy.deepcopy(BASE_ROLES),
            setup_effects=copy.deepcopy(setup_effects),
            steps=[{
                "id": "s1",
                "text": "Find the object.",
                "hint": "",
                "condition": {"type": "near_object", "params": {"object": key, "radius_m": 15}},
            }],
            state="ready",
        )

    def prop_dirs():
        d = paths.get_storage_dir() / "props"
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []

    # ------------------------------------------------------------------ (a)
    section("(a)", "create_prop near a location")
    tpl_a = make_tpl(
        "The big rock",
        [{
            "key": "rock",
            "type": "create_prop",
            "params": {
                "name": "Big rock",
                "prompt": "a large mossy boulder",
                "height_m": 2.0,
                "near": "wood",
                "offset_x": 12,
                "offset_z": -4,
                "yaw": 45,
            },
        }],
    )
    run_a = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    run_a_now = quests.get_run(run_a["id"])
    check("run stays preparing", run_a_now["state"], "preparing")
    check("1 trigger call", len(triggers), 1)
    pid_a, kw_a = triggers[0]
    check("trigger face_num", kw_a.get("face_num"), 12000)
    check("trigger texture_size", kw_a.get("texture_size"), 2048)
    sc_a = props.read_sidecar(pid_a, read_only=True)
    check("sidecar source", sc_a.get("source"), "generated")
    check("sidecar quest_run", sc_a.get("quest_run"), run_a["id"])
    rows_a = [o for o in quests.list_objects(run_a["id"]) if o["effect_key"] == "rock"]
    check("object rows in id order", [(r["kind"], r["status"]) for r in rows_a],
          [("world_prop", "pending"), ("prop", "pending")])
    check("no world prop row yet", world_props.list_world_props(), [])

    # ------------------------------------------------------------------ (b)
    section("(b)", "model lands + scope_at")
    pending_pids.discard(pid_a)
    modeled_pids.add(pid_a)
    qfx.pass_once()
    run_a_open = quests.get_run(run_a["id"])
    check("run opened", run_a_open["state"], "open")
    wp_rows = world_props.list_world_props()
    check("1 world prop written", len(wp_rows), 1)
    wp_a = wp_rows[0]
    check("world prop x/z/yaw", (wp_a["x"], wp_a["z"], wp_a["yaw_deg"]), (112.0, -54.0, 45.0))
    rows_a_live = [o for o in quests.list_objects(run_a["id"]) if o["effect_key"] == "rock"]
    check("both rows live", [(r["kind"], r["status"]) for r in rows_a_live],
          [("world_prop", "live"), ("prop", "live")])
    live_ref_a = quests.live_object_refs(run_a["id"])["rock"]
    check("live_object_refs resolves to placement", "placement_id" in live_ref_a, True)
    check("live_object_refs written equals stored row", live_ref_a.get("written"), wp_a)
    check("prop row ref exact", rows_a_live[1]["ref"], {"prop_id": pid_a})
    check("scope_at near -> world_prop", qe.scope_at(tpl_a, "step:0").objects["rock"], "world_prop")
    tpl_room_scope = copy.deepcopy(tpl_a)
    tpl_room_scope["setup_effects"][0]["params"] = {"name": "Big rock", "prompt": "a rock", "room": "glade"}
    check("scope_at room -> room_prop", qe.scope_at(tpl_room_scope, "step:0").objects["rock"], "room_prop")

    # ------------------------------------------------------------------ (c)
    section("(c)", "media off")
    triggers.clear()
    dirs_before_c = set(prop_dirs())
    media_problem[0] = "Media generation is off: test"
    try:
        run_c = qe.start_run(tpl_a["id"], BASE_BINDINGS)
        qfx.pass_once()
        got_c = quests.get_run(run_c["id"])
        check("stays preparing", got_c["state"], "preparing")
        check("1 issue at setup_effects.0", [(i["path"], i["message"]) for i in got_c["issues"]],
              [("setup_effects.0", "Media generation is off: test")])
        check("0 trigger calls", len(triggers), 0)
        check("no prop sidecar created", set(prop_dirs()) - dirs_before_c, set())
        qe.cancel_run(run_c["id"])
        qfx.pass_once()
    finally:
        media_problem[0] = ""

    # ------------------------------------------------------------------ (d)
    section("(d)", "mesh failed + retry")
    triggers.clear()
    dirs_before_d = set(prop_dirs())
    run_d = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    check("1st trigger call", len(triggers), 1)
    pid_d = triggers[0][0]
    pending_pids.discard(pid_d)  # fails: not pending, not modeled
    qfx.pass_once()
    got_d = quests.get_run(run_d["id"])
    check("preparing with mesh_failed", (got_d["state"], [i["code"] for i in got_d["issues"]]),
          ("preparing", ["mesh_failed"]))
    check("retry returns True", qfx.retry(run_d["id"]), True)
    qfx.pass_once()
    got_d2 = quests.get_run(run_d["id"])
    check("issues cleared after retry", got_d2["issues"], [])
    check("2nd trigger for same pid", (len(triggers), triggers[1][0]), (2, pid_d))
    check("still 1 prop dir for run d", len(set(prop_dirs()) - dirs_before_d), 1)
    pending_pids.discard(pid_d)
    modeled_pids.add(pid_d)
    qfx.pass_once()
    check("opens after retry model lands", quests.get_run(run_d["id"])["state"], "open")
    qe.cancel_run(run_d["id"])
    qfx.pass_once()

    # ------------------------------------------------------------------ (e)
    section("(e)", "mesh timeout")
    triggers.clear()
    run_e1 = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_e1 = triggers[0][0]
    prop_row_e1 = [o for o in quests.list_objects(run_e1["id"]) if o["kind"] == "prop"][0]
    created_e1 = timeutils.parse_iso(prop_row_e1["created_at"])
    orig_utc_now = timeutils.utc_now
    try:
        timeutils.utc_now = lambda: created_e1 + timedelta(minutes=31)
        qfx.pass_once()
        got_e1 = quests.get_run(run_e1["id"])
        check("+31 min -> mesh_timeout", (got_e1["state"], [i["code"] for i in got_e1["issues"]]),
              ("preparing", ["mesh_timeout"]))

        timeutils.utc_now = orig_utc_now
        run_e2 = qe.start_run(tpl_a["id"], BASE_BINDINGS)
        qfx.pass_once()
        pid_e2 = triggers[-1][0]
        prop_row_e2 = [o for o in quests.list_objects(run_e2["id"]) if o["kind"] == "prop"][0]
        created_e2 = timeutils.parse_iso(prop_row_e2["created_at"])
        timeutils.utc_now = lambda: created_e2 + timedelta(minutes=29)
        qfx.pass_once()
        got_e2 = quests.get_run(run_e2["id"])
        check("+29 min -> no issue", (got_e2["state"], got_e2["issues"]), ("preparing", []))
    finally:
        timeutils.utc_now = orig_utc_now
    qe.cancel_run(run_e1["id"])
    qe.cancel_run(run_e2["id"])
    pending_pids.discard(pid_e1)
    pending_pids.discard(pid_e2)
    qfx.pass_once()

    # ------------------------------------------------------------------ (f)
    section("(f)", "restart while preparing with running mesh")
    triggers.clear()
    dirs_before_f = set(prop_dirs())
    run_f = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_f = triggers[0][0]
    qfx._reset_for_tests()
    qfx.pass_once()
    check("no new trigger after restart", len(triggers), 1)
    check("rows of key == 2", len([o for o in quests.list_objects(run_f["id"]) if o["effect_key"] == "rock"]), 2)
    check("new prop dirs == 1", len(set(prop_dirs()) - dirs_before_f), 1)
    qe.cancel_run(run_f["id"])
    pending_pids.discard(pid_f)
    qfx.pass_once()

    # ------------------------------------------------------------------ (g)
    section("(g)", "world cap")
    triggers.clear()
    dirs_before_g = set(prop_dirs())
    orig_max_wp = world_props.MAX_WORLD_PROPS
    try:
        world_props.MAX_WORLD_PROPS = world_props.count_world_props()
        run_g = qe.start_run(tpl_a["id"], BASE_BINDINGS)
        qfx.pass_once()
        got_g = quests.get_run(run_g["id"])
        check("cap fails non-retryably", (got_g["state"], len(got_g["issues"])), ("preparing", 1))
        check("0 triggers under cap", len(triggers), 0)
        check("0 new prop dirs under cap", set(prop_dirs()) - dirs_before_g, set())
        qe.cancel_run(run_g["id"])
        qfx.pass_once()
    finally:
        world_props.MAX_WORLD_PROPS = orig_max_wp

    # ------------------------------------------------------------------ (h)
    section("(h)", "room placement + full room read-back")
    triggers.clear()
    tpl_h = make_tpl(
        "Room statue",
        [{
            "key": "statue",
            "type": "create_prop",
            "params": {"name": "Stone owl", "prompt": "a carved stone owl", "room": "glade"},
        }],
        key="statue",
    )
    run_h = qe.start_run(tpl_h["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_h = triggers[0][0]
    pending_pids.discard(pid_h)
    modeled_pids.add(pid_h)
    qfx.pass_once()
    check("room prop run opened", quests.get_run(run_h["id"])["state"], "open")
    rp_row_h = [o for o in quests.list_objects(run_h["id"]) if o["kind"] == "room_prop"][0]
    check("room_prop ref exact keys", set(rp_row_h["ref"].keys()),
          {"location_id", "room_id", "place_id", "prop_id"})
    loc_h = world.get_location_by_id("L1")
    glade_props = (world.get_room_by_id(loc_h, "glade").get("layout") or {}).get("props") or []
    placed_h = next((p for p in glade_props if p.get("id") == rp_row_h["ref"]["place_id"]), None)
    check("room entry prop_id and at", (placed_h is not None and placed_h.get("prop_id"), placed_h.get("at") if placed_h else None),
          (pid_h, [3.0, 2.0]))
    qe.cancel_run(run_h["id"])
    qfx.pass_once()

    # Full room: append_room_props returns True without writing -> read-back catches it
    triggers.clear()
    orig_append = world.append_room_props
    try:
        run_h2 = qe.start_run(tpl_h["id"], BASE_BINDINGS)
        qfx.pass_once()
        pid_h2 = triggers[0][0]
        pending_pids.discard(pid_h2)
        modeled_pids.add(pid_h2)
        world.append_room_props = lambda loc_id, r_id, placements: True
        qfx.pass_once()
        got_h2 = quests.get_run(run_h2["id"])
        check("full room caught by read-back", (got_h2["state"], len(got_h2["issues"])), ("preparing", 1))
    finally:
        world.append_room_props = orig_append
    qe.cancel_run(run_h2["id"])
    qfx.pass_once()

    # ------------------------------------------------------------------ (i)
    section("(i)", "place_prop unknown vs existing library prop")
    tpl_i_bad = make_tpl(
        "Place missing",
        [{
            "key": "rock",
            "type": "place_prop",
            "params": {"prop_id": "no-such-prop-123456", "near": "wood", "offset_x": 5, "offset_z": 5},
        }],
    )
    refused_codes = []
    try:
        qe.start_run(tpl_i_bad["id"], BASE_BINDINGS)
    except qe.QuestRefused as exc:
        refused_codes = [i["code"] for i in exc.issues]
    check("unknown prop refused at start", "unknown_prop" in refused_codes, True)

    lib_prop = props.create_prop(name="Old Barrel", description="a wooden barrel", source="manual")
    lib_pid = lib_prop["id"]
    triggers.clear()
    tpl_i_ok = make_tpl(
        "Place barrel",
        [{
            "key": "rock",
            "type": "place_prop",
            "params": {"prop_id": lib_pid, "near": "wood", "offset_x": 5, "offset_z": 5, "yaw": 90},
        }],
    )
    run_i = qe.start_run(tpl_i_ok["id"], BASE_BINDINGS)
    qfx.pass_once()
    check("place_prop opens in 1st pass", quests.get_run(run_i["id"])["state"], "open")
    check("0 trigger calls for place_prop", len(triggers), 0)
    rows_i = [o for o in quests.list_objects(run_i["id"]) if o["effect_key"] == "rock"]
    check("1 live world_prop row", [(r["kind"], r["status"]) for r in rows_i], [("world_prop", "live")])
    qe.cancel_run(run_i["id"])
    qfx.pass_once()
    check("library prop still exists after cancel", bool(props.read_sidecar(lib_pid, read_only=True)), True)

    # ------------------------------------------------------------------ (j)
    section("(j)", "cancel while mesh is running")
    triggers.clear()
    run_j = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_j = triggers[0][0]
    qe.cancel_run(run_j["id"])
    qfx.pass_once()
    rows_j1 = [o for o in quests.list_objects(run_j["id"]) if o["effect_key"] == "rock"]
    check("while pending: placement gone, prop revert_pending",
          [(r["kind"], r["status"]) for r in rows_j1],
          [("world_prop", "gone"), ("prop", "revert_pending")])
    check("sidecar still exists while pending", bool(props.read_sidecar(pid_j, read_only=True)), True)

    inv_before_j = invalidate_calls[0]
    pending_pids.discard(pid_j)
    qfx.pass_once()
    rows_j2 = [o for o in quests.list_objects(run_j["id"]) if o["effect_key"] == "rock"]
    check("after pending clears: prop reverted", rows_j2[1]["status"], "reverted")
    check("sidecar gone", bool(props.read_sidecar(pid_j, read_only=True)), False)
    check("invalidate_prop_lib_token called >= 1", invalidate_calls[0] - inv_before_j >= 1, True)

    # ------------------------------------------------------------------ (k)
    section("(k)", "cancel after open removes world placement, extra room placement, and prop")
    # Use run_a (still open from (b)) and add a hand-made layout.props entry in room "hollow".
    extra_added = world.append_room_props("L1", "hollow", [{"id": "extrah01", "prop_id": pid_a, "at": [1.0, 1.0]}])
    check("extra room placement added", extra_added, True)
    qe.cancel_run(run_a["id"])
    qfx.pass_once()
    rows_k = [o for o in quests.list_objects(run_a["id"]) if o["effect_key"] == "rock"]
    check("world_prop and prop both reverted",
          [(r["kind"], r["status"]) for r in rows_k],
          [("world_prop", "reverted"), ("prop", "reverted")])
    check("world placement deleted", any(r["id"] == wp_a["id"] for r in world_props.list_world_props()), False)
    check("prop sidecar deleted", bool(props.read_sidecar(pid_a, read_only=True)), False)
    hollow_props = (world.get_room_by_id(world.get_location_by_id("L1"), "hollow").get("layout") or {}).get("props") or []
    check("extra room placement removed", any(p.get("prop_id") == pid_a for p in hollow_props), False)

    # ------------------------------------------------------------------ (l)
    section("(l)", "admin edit respected on cancel")
    run_l = qe.start_run(tpl_i_ok["id"], BASE_BINDINGS)
    qfx.pass_once()
    row_l = [o for o in quests.list_objects(run_l["id"]) if o["kind"] == "world_prop"][0]
    wid_l = row_l["ref"]["placement_id"]
    edited = dict(row_l["ref"]["written"])
    edited["x"] = 125.0
    world_props.save_world_prop(edited)
    qe.cancel_run(run_l["id"])
    qfx.pass_once()
    row_l_after = [o for o in quests.list_objects(run_l["id"]) if o["kind"] == "world_prop"][0]
    check("edited placement marked gone", row_l_after["status"], "gone")
    stored_l = next((r for r in world_props.list_world_props() if r["id"] == wid_l), None)
    check("edited placement preserved", stored_l is not None and stored_l["x"], 125.0)
    world_props.delete_world_prop(wid_l)

    # ------------------------------------------------------------------ (m)
    section("(m)", "exclusion from room_furnish and export (D17)")
    triggers.clear()
    run_m = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_m = triggers[0][0]
    lib_map = room_furnish._library()
    check("tagged quest prop excluded from room_furnish._library", pid_m in lib_map, False)
    check("untagged library prop included in room_furnish._library", lib_pid in lib_map, True)
    export_refused = False
    try:
        content_io.export_prop_to_zip(pid_m)
    except ValueError:
        export_refused = True
    check("export_prop_to_zip refuses tagged prop", export_refused, True)
    qe.cancel_run(run_m["id"])
    pending_pids.discard(pid_m)
    qfx.pass_once()

    # ------------------------------------------------------------------ (n)
    section("(n)", "permanent prop untagged at run end (D17)")
    triggers.clear()
    tpl_n = make_tpl(
        "Permanent rock",
        [{
            "key": "rock",
            "type": "create_prop",
            "permanent": True,
            "params": {
                "name": "Monument",
                "prompt": "a stone monument",
                "near": "wood",
                "offset_x": 3,
                "offset_z": 3,
            },
        }],
    )
    run_n = qe.start_run(tpl_n["id"], BASE_BINDINGS)
    qfx.pass_once()
    pid_n = triggers[0][0]
    check("tagged while running", props.read_sidecar(pid_n, read_only=True).get("quest_run"), run_n["id"])
    pending_pids.discard(pid_n)
    modeled_pids.add(pid_n)
    qfx.pass_once()
    check("permanent run opened", quests.get_run(run_n["id"])["state"], "open")
    row_n_wp = [o for o in quests.list_objects(run_n["id"]) if o["kind"] == "world_prop"][0]
    wid_n = row_n_wp["ref"]["placement_id"]
    qe.cancel_run(run_n["id"])
    qfx.pass_once()
    rows_n_after = [o for o in quests.list_objects(run_n["id"]) if o["effect_key"] == "rock"]
    check("permanent rows stay live", [r["status"] for r in rows_n_after], ["live", "live"])
    check("permanent placement still exists", any(r["id"] == wid_n for r in world_props.list_world_props()), True)
    sc_n_after = props.read_sidecar(pid_n, read_only=True)
    check("permanent prop still exists", bool(sc_n_after), True)
    check("quest_run key removed from sidecar", "quest_run" in sc_n_after, False)

    # ------------------------------------------------------------------ (o)
    section("(o)", "remove_room_props unit")
    world.append_room_props(
        "L1",
        "hollow",
        [
            {"id": "rmtest01", "prop_id": lib_pid, "at": [1.0, 1.0]},
            {"id": "rmtest02", "prop_id": lib_pid, "at": [2.0, 2.0]},
        ],
    )
    check("remove one id returns 1", world.remove_room_props("L1", "hollow", ["rmtest01"]), 1)
    hollow_after = (world.get_room_by_id(world.get_location_by_id("L1"), "hollow").get("layout") or {}).get("props") or []
    check("only second id remains", [p.get("id") for p in hollow_after], ["rmtest02"])
    check("remove unknown id returns 0", world.remove_room_props("L1", "hollow", ["no_such_id"]), 0)

    # ------------------------------------------------------------------ (p)
    section("(p)", "EffectFailed default code")
    check("default code is effect_failed", qfx.EffectFailed("x").code, "effect_failed")

    # ------------------------------------------------------------------ (q)
    section("(q)", "boot order: quest_effects.start after start_resumer")
    server_src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    check("quest_effects.start() appears once", server_src.count("quest_effects.start()"), 1)
    idx_resumer = server_src.find("start_resumer()")
    idx_qfx_start = server_src.find("quest_effects.start()")
    check("quest_effects.start() comes after start_resumer()", idx_resumer >= 0 and idx_qfx_start > idx_resumer, True)

    # ------------------------------------------------------------------ (r)
    section("(r)", "retry after mesh_timeout gets fresh 30 minutes without re-triggering")
    triggers.clear()
    run_r = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    check("1 initial trigger", len(triggers), 1)
    pid_r = triggers[0][0]
    prop_row_r = [o for o in quests.list_objects(run_r["id"]) if o["kind"] == "prop"][0]
    created_r = timeutils.parse_iso(prop_row_r["created_at"])
    t_plus_31 = created_r + timedelta(minutes=31)
    t_plus_60 = created_r + timedelta(minutes=60)
    t_plus_62 = created_r + timedelta(minutes=62)
    orig_utc_now = timeutils.utc_now
    try:
        timeutils.utc_now = lambda: t_plus_31
        qfx.pass_once()
        got_r1 = quests.get_run(run_r["id"])
        prop_r1 = [o for o in quests.list_objects(run_r["id"]) if o["kind"] == "prop"][0]
        check("+31 min -> mesh_timeout", [i["code"] for i in got_r1["issues"]], ["mesh_timeout"])
        check("prop ref has mesh_failed True", prop_r1["ref"].get("mesh_failed"), True)

        check("retry returns True", qfx.retry(run_r["id"]), True)
        qfx.pass_once()
        got_r2 = quests.get_run(run_r["id"])
        prop_r2 = [o for o in quests.list_objects(run_r["id"]) if o["kind"] == "prop"][0]
        check("after retry at +31 min: preparing, no issues", (got_r2["state"], got_r2["issues"]), ("preparing", []))
        check("still 1 trigger call (no re-trigger while pending)", len(triggers), 1)
        check("mesh_failed cleared from prop ref", "mesh_failed" in prop_r2["ref"], False)
        check("mesh_started_at reset to +31 min", prop_r2["ref"].get("mesh_started_at"),
              t_plus_31.isoformat(timespec="seconds"))

        timeutils.utc_now = lambda: t_plus_60
        qfx.pass_once()
        got_r3 = quests.get_run(run_r["id"])
        check("+60 min (29 min after retry) -> no issue", (got_r3["state"], got_r3["issues"]), ("preparing", []))

        timeutils.utc_now = lambda: t_plus_62
        qfx.pass_once()
        got_r4 = quests.get_run(run_r["id"])
        check("+62 min (31 min after retry) -> mesh_timeout again",
              (got_r4["state"], [i["code"] for i in got_r4["issues"]]),
              ("preparing", ["mesh_timeout"]))
    finally:
        timeutils.utc_now = orig_utc_now
    qe.cancel_run(run_r["id"])
    pending_pids.discard(pid_r)
    qfx.pass_once()

    # ------------------------------------------------------------------ (s)
    section("(s)", "restart reconcile after placement was written")
    triggers.clear()
    run_s = qe.start_run(tpl_a["id"], BASE_BINDINGS)
    qfx.pass_once()
    check("1 initial trigger for s", len(triggers), 1)
    pid_s = triggers[0][0]
    rows_s0 = [o for o in quests.list_objects(run_s["id"]) if o["effect_key"] == "rock"]
    check("initial pending rows", [(r["kind"], r["status"]) for r in rows_s0],
          [("world_prop", "pending"), ("prop", "pending")])
    wid_s = rows_s0[0]["ref"]["placement_id"]

    # Simulate crash after model landed and placement was written, before rows were promoted live.
    pending_pids.discard(pid_s)
    modeled_pids.add(pid_s)
    world_props.save_world_prop({
        "id": wid_s,
        "prop_id": pid_s,
        "x": 112.0,
        "z": -54.0,
        "yaw_deg": 0.0,
        "offset_y": 0.0,
    })
    qfx._reset_for_tests()
    qfx.pass_once()
    check("reconciled run opened", quests.get_run(run_s["id"])["state"], "open")
    rows_s1 = [o for o in quests.list_objects(run_s["id"]) if o["effect_key"] == "rock"]
    check("both rows promoted to live", [(r["kind"], r["status"]) for r in rows_s1],
          [("world_prop", "live"), ("prop", "live")])
    matching_wp_s = [r for r in world_props.list_world_props() if r["id"] == wid_s]
    check("exactly 1 world prop row with that id", len(matching_wp_s), 1)
    check("no new trigger call", len(triggers), 1)
    check("prop row ref exact (pending-only keys stripped)", rows_s1[1]["ref"], {"prop_id": pid_s})
    check("world_prop ref has no pending-only keys",
          any(k in rows_s1[0]["ref"] for k in ("mesh_failed", "mesh_started_at", "before")),
          False)

    qe.cancel_run(run_s["id"])
    qfx.pass_once()
    rows_s2 = [o for o in quests.list_objects(run_s["id"]) if o["effect_key"] == "rock"]
    check("cancel removes placement and prop (both reverted)",
          [(r["kind"], r["status"]) for r in rows_s2],
          [("world_prop", "reverted"), ("prop", "reverted")])
    check("world prop deleted on cancel", any(r["id"] == wid_s for r in world_props.list_world_props()), False)
    check("prop sidecar deleted on cancel", bool(props.read_sidecar(pid_s, read_only=True)), False)

    if FAILURES:
        print(f"FAIL smoke_quest_props: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_props")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
