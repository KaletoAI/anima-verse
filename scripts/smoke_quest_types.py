#!/usr/bin/env python3
"""Smoke: the built-in quest types (`app/core/quest_types.py`).

Quest system stage 1, Task 4. Throwaway storage (`paths.init(<tmpdir>)` BEFORE any world-DB
module), no server, no LLM. Every expected value below is derived by hand from the plan's Task 4 table
(types, params, "passed when"), D4-D7 and Review Focus 4 — not recorded from a run.

Usage:
    ./.venv/bin/python scripts/smoke_quest_types.py

FIXTURE
    Locations: "inn" (rooms hall, cellar), "mill" (room loft).
    Characters: Ada (in inn/hall, status_effects {"focus": 40}), Nim (NPC, in inn/hall),
    Kai (in inn/hall) with a linked body Lio (create_linked -> dormant, stands nowhere).
    Items: "Coin" (stackable), "Lantern".
    Roles of the test template: giver (character), place (room), town (location),
    thing (item), lamp (item), nowhere (room, left UNBOUND).
    Bindings: giver {"name": "Nim"}, place {"location_id": "inn", "room_id": "hall"},
    town {"location_id": "inn"}, thing {"item_id": <coin>}, lamp {"item_id": <lantern>}.
    The run: {"bindings": <the bindings>, "started_game_ts": T.canonical()} with T = the game
    clock at fixture time.

WHAT FOLLOWS BY HAND (each result written as (available, passed))
[0] register(): the catalog holds the seven ids with their kinds — at_place, holds_item,
    stat_compare, spoke_with, time_elapsed, expression: condition; relationship_at_least:
    prerequisite. Signals: at_place (character.entered_room,), holds_item (inventory.changed,),
    stat_compare/time_elapsed (world_tick,), spoke_with (utterance.heard,), expression
    (world_tick, character.entered_room, inventory.changed), relationship_at_least ().
[A] build_context("Ada", run): avatar Ada, mind Ada (not linked), location inn, room hall,
    bindings == run bindings, the run dict itself, now >= T (the game clock runs, so only the
    order is fixed). build_context("Nobody", run) -> None (a strict profile read of a missing
    row raises; the one WARNING "quest context for Nobody unavailable" in the output is expected).
[B] at_place. place = inn/hall (room role): Ada in inn/hall -> (T, T). Ada in inn/cellar (right
    location, wrong room) -> (T, F). town = inn (location role) with Ada in inn/cellar -> (T, T)
    (a location role ignores the room). Ada in mill/loft with town -> (T, F). The unbound role
    "nowhere" -> (F, F).
[C] holds_item thing count=2: Ada holds 1 coin -> 1 >= 2 false -> (T, F); a second coin
    -> 2 >= 2 -> (T, T); count omitted (default 1) with 2 coins -> (T, T); the unbound role
    -> (F, F). check: count=0 -> bad_param at ".params.count" (min 1).
[D] stat_compare on focus = 40: ">=" 40 -> (T, T); ">" 40 -> (T, F); "<" 50 -> (T, T);
    "=" 40 -> (T, T); "<=" 39 -> (T, F); an unknown stat "luck" -> effective_stat None ->
    (F, F). check: op "!=" -> bad_param at ".params.op" (not a choice).
[E] spoke_with giver (Nim): no fact -> (T, F); add_fact("Ada", "spoke_with", "Nim") -> (T, T);
    unbound role -> (F, F).
[F] time_elapsed hours=2, run opened at T: now = T + 1h59m -> (T, F); now = T + 2h -> (T, T);
    a run without started_game_ts (never opened) -> (F, F). check: hours=0 -> bad_param.
[G] expression: "focus>30" -> 40 > 30 -> (T, T); "focus<30" -> (T, F); "NOT NOT night"
    (a double NOT is a syntax error of the grammar) -> check_expression gives an issue at
    ".type" with code "syntax", and evaluate -> (F, F).
[H] relationship_at_least giver (Nim): no relationship row -> strength 0: strength=30 ->
    (T, F), strength=0 -> 0 >= 0 -> (T, T). update_relationship_manual(Ada, Nim, strength=40):
    strength=30 -> (T, T), strength=50 -> (T, F). check: strength=101 -> bad_param (max 100);
    in a condition-only position -> wrong_kind at ".type"; in ("condition", "prerequisite") ->
    no issue.
[I] check_binding: room inn/hall -> []; room inn/attic -> 1 issue; room {} -> 1 issue;
    location inn -> []; location "nowhere" -> 1 issue; item coin -> []; item "item_gone" ->
    1 issue; character Nim -> []; character "Ghost" -> 1 issue; character Lio (dormant body,
    still exists) -> []; an unknown kind "secret" -> 1 issue.
[J] LINKED (Review Focus 4). Kai holds the lantern and stands in inn/hall; Lio (dormant) does
    not. add_fact(mind_of("Kai") = "Kai", "spoke_with", "Nim").
    ctx(Lio): mind "Kai"; spoke_with giver -> (T, T) (the fact is the mind's); holds_item lamp
    -> Lio holds no lantern -> (T, F); at_place place -> Lio stands nowhere -> (T, F).
    swap_presence(Kai -> Lio) without items: Lio now stands where Kai stood (inn/hall), Kai is
    dormant. ctx(Lio): at_place -> (T, T), holds_item lamp -> (T, F) (the lantern stayed with
    Kai's body), spoke_with -> (T, T) (still the mind's fact). ctx(Kai): at_place -> (T, F).
    A bound body resolves to its mind: add_fact("Ada", "spoke_with", "Kai") and a binding
    {"name": "Lio"} -> spoke_with for Ada -> mind_of("Lio") = "Kai" -> (T, T).
[K] Stage 2 registration & static checks: knows_secret (condition, ("secret.learned",)),
    found_item (condition, ("item.discovered",)), near_object (condition,
    ("character.entered_room", "world_tick")); holds_item "item" param has type "target",
    role_kinds ["item"], object_kinds ["item"]. Source of app/core/quest_types.py contains
    "journey_state" and "get_character_pos", does not contain "location_at_point", and does not
    import scene_recipe.
[L] objects in QuestContext: real run with add_object: "box" (item, live, coin), second "box"
    (item, live, lantern), "hint" (secret, pending), "m" (marker, live).
    build_context("Ada", run).objects == {"box": {"item_id": coin}} (first live row wins;
    pending and marker excluded). quests.live_object_refs("") == {}.
[M] holds_item with targets: ctx with objects {"box": {"item_id": coin}}: Ada holds 2 coins ->
    holds_item item="box" count=2 -> (T, T); item="ghost" -> (F, F); role key "thing" -> (T, T).
    check_expression with Scope(roles, {"box": "item"}): item="box" -> []; with
    Scope(roles, {"box": "secret"}): 1 issue code "wrong_kind"; item="thing" -> [].
[N] knows_secret: Nim owns secret sid ("Under the roots.", source="quest",
    source_ref="quest_run:qr_smoke"); objects {"hint": {"owner": "Nim", "secret_id": sid}}.
    Ada -> (T, F); add_known_by("Nim", sid, "Ada") -> (T, T); secret="nohint" -> (F, F);
    nonexistent secret id -> (F, F); Nim (owner) -> (T, T). Linked: add_known_by("Nim", sid, "Lio")
    -> ctx(Kai) -> (T, T); new secret sid2 known only via Lio -> ctx(Lio) -> (T, T).
[O] found_item: objects {"spot": {"location_id": "inn", "room_id": "cellar", "item_id": lantern,
    "quantity": 1}}. No fact -> (T, F); add_fact("Ada", "found", found_subject("inn", "cellar",
    lantern)) -> (T, T); found_subject("inn", "cellar", "x") == "inn/cellar/x"; target "nospot"
    -> (F, F). Linked: add_fact("Kai", "found", ...) -> ctx(Lio) -> (T, T).
[P] near_object: world_props row id="wp_rock" at (100.0, 0.0); objects {"rock": world_prop wp_rock,
    "chair": room_prop inn/hall, "spot": room_item inn/cellar}. Ada at (108, 6): hypot(8, 6)=10.0
    <= 10 -> (T, T) with default radius 10; (111, 0): 11.0 > 10 -> (T, F); radius_m=11 at (111, 0)
    -> (T, T); no point (None, None) -> (T, F); placement "wp_gone" -> (F, F). Journey-aware:
    stored point (0, 0) + point journey (0, 0, 0) -> (200, 0, 200) started at motion_time()-108.0
    -> journey_state puts Ada near (108, 0), distance ~8 <= 10 -> (T, T). Room objects: Ada in
    inn/hall -> "chair" (T, T); Ada in inn/cellar -> "chair" (T, F), "spot" (T, T).
"""
import dataclasses
import os
import sys
import tempfile
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


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-types-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__
    from app.core import db
    db.init_schema()
    from app.core import quest_catalog as qc
    from app.core.game_time import GameDuration
    from app.core.linked_characters import create_linked, mind_of, swap_presence
    from app.core.timeutils import game_time
    from app.models import character as chars, inventory, relationship, world
    from app.models.quests import add_fact
    try:
        from app.core import quest_types as qt
    except ImportError as e:
        print(f"  FAIL app.core.quest_types is missing: {e}")
        print("FAIL smoke_quest_types: 1 failed")
        return 1

    world.upsert_location({"id": "inn", "name": "Inn", "entry_room": "hall",
                           "rooms": [{"id": "hall", "name": "Hall"},
                                     {"id": "cellar", "name": "Cellar"}]}, sync_world=False)
    world.upsert_location({"id": "mill", "name": "Mill", "entry_room": "loft",
                           "rooms": [{"id": "loft", "name": "Loft"}]}, sync_world=False)
    for name, extra in (("Ada", {"status_effects": {"focus": 40}}), ("Nim", {}), ("Kai", {})):
        assert chars.save_character_profile(
            name, {"current_location": "inn", "current_room": "hall", **extra}, create_new=True), name
    made = create_linked("Kai", "Lio")
    assert made.get("ok"), made
    coin = inventory.add_item("Coin", stackable=True, max_stack=99)["id"]
    lantern = inventory.add_item("Lantern")["id"]

    qt.register()
    T = game_time()
    bindings = {"giver": {"name": "Nim"},
                "place": {"location_id": "inn", "room_id": "hall"},
                "town": {"location_id": "inn"},
                "thing": {"item_id": coin},
                "lamp": {"item_id": lantern}}
    run = {"id": "qr_smoke", "bindings": bindings, "started_game_ts": T.canonical()}
    roles = [{"key": "giver", "kind": "character"}, {"key": "place", "kind": "room"},
             {"key": "town", "kind": "location"}, {"key": "thing", "kind": "item"},
             {"key": "lamp", "kind": "item"}, {"key": "nowhere", "kind": "room"}]

    def ev(type_id, ctx, **params):
        r = qc.evaluate_expression({"type": type_id, "params": params}, ctx)
        return (r.available, r.passed)

    def issues(type_id, kinds=("condition",), **params):
        scope = qc.Scope({r["key"]: r["kind"] for r in roles}, {})
        return [(i["code"], i["path"]) for i in
                qc.check_expression({"type": type_id, "params": params}, scope, allowed_kinds=kinds)]

    SECTION[0] = "[0]"
    print("[0] registration")
    known = qc.types()
    want_kinds = {"at_place": "condition", "holds_item": "condition", "stat_compare": "condition",
                  "spoke_with": "condition", "time_elapsed": "condition", "expression": "condition",
                  "relationship_at_least": "prerequisite"}
    check("kinds", {k: known[k].kind for k in want_kinds if k in known}, want_kinds)
    check("signals", {k: known[k].signals for k in want_kinds if k in known}, {
        "at_place": ("character.entered_room",), "holds_item": ("inventory.changed",),
        "stat_compare": ("world_tick",), "spoke_with": ("utterance.heard",),
        "time_elapsed": ("world_tick",),
        "expression": ("world_tick", "character.entered_room", "inventory.changed"),
        "relationship_at_least": ()})

    SECTION[0] = "[A]"
    print("[A] build_context")
    ctx = qt.build_context("Ada", run)
    check("built", ctx is not None, True)
    if ctx is None:
        print("FAIL smoke_quest_types: no context")
        return 1
    check("fields", (ctx.avatar, ctx.mind, ctx.location_id, ctx.room_id, ctx.bindings),
          ("Ada", "Ada", "inn", "hall", bindings))
    check("profile is Ada's", ctx.profile.get("status_effects"), {"focus": 40})
    check("now >= T", ctx.now >= T, True)
    check("run kept", ctx.run is run, True)
    check("unknown avatar -> None", qt.build_context("Nobody", run), None)

    SECTION[0] = "[B]"
    print("[B] at_place")
    cellar = dataclasses.replace(ctx, room_id="cellar")
    loft = dataclasses.replace(ctx, location_id="mill", room_id="loft")
    check("room role, in the room", ev("at_place", ctx, place="place"), (True, True))
    check("room role, right location wrong room", ev("at_place", cellar, place="place"), (True, False))
    check("location role, other room", ev("at_place", cellar, place="town"), (True, True))
    check("location role, other location", ev("at_place", loft, place="town"), (True, False))
    check("unbound role", ev("at_place", ctx, place="nowhere"), (False, False))

    SECTION[0] = "[C]"
    print("[C] holds_item")
    inventory.add_to_inventory("Ada", coin, 1)
    check("1 of 2", ev("holds_item", ctx, item="thing", count=2), (True, False))
    inventory.add_to_inventory("Ada", coin, 1)
    check("2 of 2", ev("holds_item", ctx, item="thing", count=2), (True, True))
    check("count default 1", ev("holds_item", ctx, item="thing"), (True, True))
    check("unbound role", ev("holds_item", ctx, item="nowhere", count=1), (False, False))
    check("count=0 refused", issues("holds_item", item="thing", count=0), [("bad_param", ".params.count")])

    SECTION[0] = "[D]"
    print("[D] stat_compare")
    for op, value, want in ((">=", 40, (True, True)), (">", 40, (True, False)), ("<", 50, (True, True)),
                            ("=", 40, (True, True)), ("<=", 39, (True, False))):
        check(f"focus {op} {value}", ev("stat_compare", ctx, stat="focus", op=op, value=value), want)
    check("unknown stat", ev("stat_compare", ctx, stat="luck", op=">=", value=1), (False, False))
    check("op != refused", issues("stat_compare", stat="focus", op="!=", value=1), [("bad_param", ".params.op")])

    SECTION[0] = "[E]"
    print("[E] spoke_with")
    check("no fact", ev("spoke_with", ctx, character="giver"), (True, False))
    add_fact("Ada", "spoke_with", "Nim")
    check("fact", ev("spoke_with", ctx, character="giver"), (True, True))
    check("unbound role", ev("spoke_with", ctx, character="nowhere"), (False, False))

    SECTION[0] = "[F]"
    print("[F] time_elapsed")
    early = dataclasses.replace(ctx, now=T + GameDuration.of(hours=1, minutes=59))
    due = dataclasses.replace(ctx, now=T + GameDuration.of(hours=2))
    check("T + 1h59m", ev("time_elapsed", early, hours=2), (True, False))
    check("T + 2h", ev("time_elapsed", due, hours=2), (True, True))
    never = dataclasses.replace(due, run={"bindings": bindings, "started_game_ts": ""})
    check("run never opened", ev("time_elapsed", never, hours=2), (False, False))
    check("hours=0 refused", issues("time_elapsed", hours=0), [("bad_param", ".params.hours")])

    SECTION[0] = "[G]"
    print("[G] expression")
    check("focus>30", ev("expression", ctx, expression="focus>30"), (True, True))
    check("focus<30", ev("expression", ctx, expression="focus<30"), (True, False))
    check("syntax error: validate", issues("expression", expression="NOT NOT night"), [("syntax", ".type")])
    check("syntax error: evaluate", ev("expression", ctx, expression="NOT NOT night"), (False, False))

    SECTION[0] = "[H]"
    print("[H] relationship_at_least")
    check("no row, 30", ev("relationship_at_least", ctx, character="giver", strength=30), (True, False))
    check("no row, 0", ev("relationship_at_least", ctx, character="giver", strength=0), (True, True))
    relationship.update_relationship_manual("Ada", "Nim", strength=40)
    check("40 >= 30", ev("relationship_at_least", ctx, character="giver", strength=30), (True, True))
    check("40 >= 50", ev("relationship_at_least", ctx, character="giver", strength=50), (True, False))
    check("unbound role", ev("relationship_at_least", ctx, character="nowhere", strength=1), (False, False))
    pre = ("condition", "prerequisite")
    check("strength=101 refused", issues("relationship_at_least", pre, character="giver", strength=101),
          [("bad_param", ".params.strength")])
    check("not a step condition", issues("relationship_at_least", character="giver", strength=1),
          [("wrong_kind", ".type")])
    check("fine as a prerequisite", issues("relationship_at_least", pre, character="giver", strength=1), [])

    SECTION[0] = "[I]"
    print("[I] check_binding")
    for kind, binding, n in (("room", {"location_id": "inn", "room_id": "hall"}, 0),
                             ("room", {"location_id": "inn", "room_id": "attic"}, 1),
                             ("room", {}, 1),
                             ("location", {"location_id": "inn"}, 0),
                             ("location", {"location_id": "nowhere"}, 1),
                             ("item", {"item_id": coin}, 0),
                             ("item", {"item_id": "item_gone"}, 1),
                             ("character", {"name": "Nim"}, 0),
                             ("character", {"name": "Ghost"}, 1),
                             ("character", {"name": "Lio"}, 0),
                             ("secret", {"secret_id": "x"}, 1)):
        got = qt.check_binding(kind, binding)
        check(f"{kind} {binding}", len(got), n)
        if got:
            check(f"{kind} {binding} issue has code+message", bool(got[0].code and got[0].message), True)

    SECTION[0] = "[J]"
    print("[J] linked bodies")
    inventory.add_to_inventory("Kai", lantern, 1)
    add_fact(mind_of("Kai"), "spoke_with", "Nim")
    lio = qt.build_context("Lio", run)
    check("Lio's mind", lio and lio.mind, "Kai")
    check("Lio spoke_with (mind fact)", ev("spoke_with", lio, character="giver"), (True, True))
    check("Lio holds_item (body)", ev("holds_item", lio, item="lamp"), (True, False))
    check("Lio at_place (dormant)", ev("at_place", lio, place="place"), (True, False))
    swapped = swap_presence("Kai", "Lio")
    check("swap ok", swapped.get("ok"), True)
    lio = qt.build_context("Lio", run)
    kai = qt.build_context("Kai", run)
    check("after swap: Lio at_place", ev("at_place", lio, place="place"), (True, True))
    check("after swap: Lio holds_item", ev("holds_item", lio, item="lamp"), (True, False))
    check("after swap: Lio spoke_with", ev("spoke_with", lio, character="giver"), (True, True))
    check("after swap: Kai at_place", ev("at_place", kai, place="place"), (True, False))
    add_fact("Ada", "spoke_with", "Kai")
    body_bound = dataclasses.replace(ctx, bindings={**bindings, "giver": {"name": "Lio"}})
    check("bound body resolves to its mind", ev("spoke_with", body_bound, character="giver"), (True, True))

    SECTION[0] = "[K]"
    print("[K] stage 2 condition registration and static checks")
    known = qc.types()
    s2_kinds = {"knows_secret": "condition", "found_item": "condition", "near_object": "condition"}
    check("stage 2 kinds", {k: known[k].kind for k in s2_kinds if k in known}, s2_kinds)
    check("stage 2 signals", {k: known[k].signals for k in s2_kinds if k in known}, {
        "knows_secret": ("secret.learned",),
        "found_item": ("item.discovered",),
        "near_object": ("character.entered_room", "world_tick"),
    })
    holds_item_param = next((p for p in known["holds_item"].params if p.get("key") == "item"), {})
    check("holds_item item param is target",
          (holds_item_param.get("type"), holds_item_param.get("role_kinds"), holds_item_param.get("object_kinds")),
          ("target", ["item"], ["item"]))
    qt_src = (ROOT / "app" / "core" / "quest_types.py").read_text(encoding="utf-8")
    check("uses journey_state", "journey_state" in qt_src, True)
    check("uses get_character_pos", "get_character_pos" in qt_src, True)
    check("no location_at_point", "location_at_point" in qt_src, False)
    check("no scene_recipe import", "scene_recipe" in qt_src, False)

    SECTION[0] = "[L]"
    print("[L] objects in QuestContext")
    from app.models import quests, secrets
    real_run = quests.create_run(template={"id": "qt_smoke"}, bindings=bindings, state="open")
    quests.add_object(real_run["id"], effect_key="box", position="setup", kind="item",
                      ref={"item_id": coin}, status="live")
    quests.add_object(real_run["id"], effect_key="box", position="setup", kind="item",
                      ref={"item_id": lantern}, status="live")
    quests.add_object(real_run["id"], effect_key="hint", position="setup", kind="secret",
                      ref={"owner": "Nim", "secret_id": "sec_pending"}, status="pending")
    quests.add_object(real_run["id"], effect_key="m", position="setup", kind="marker",
                      ref={"effect_key": "m"}, status="live")
    ctx_l = qt.build_context("Ada", real_run)
    check("first live non-marker wins", ctx_l.objects if ctx_l else None, {"box": {"item_id": coin}})
    check("empty run_id -> {}", quests.live_object_refs(""), {})

    SECTION[0] = "[M]"
    print("[M] holds_item with targets")
    ctx_m = dataclasses.replace(ctx, objects={"box": {"item_id": coin}})
    check("object target 2 of 2", ev("holds_item", ctx_m, item="box", count=2), (True, True))
    check("unknown target -> unavailable", ev("holds_item", ctx_m, item="ghost", count=1), (False, False))
    check("role target still works", ev("holds_item", ctx_m, item="thing", count=2), (True, True))
    role_map = {r["key"]: r["kind"] for r in roles}
    check("check_expression object item -> []",
          qc.check_expression({"type": "holds_item", "params": {"item": "box"}},
                              qc.Scope(role_map, {"box": "item"}), allowed_kinds=("condition",)),
          [])
    bad_obj = qc.check_expression({"type": "holds_item", "params": {"item": "box"}},
                                  qc.Scope(role_map, {"box": "secret"}), allowed_kinds=("condition",))
    check("check_expression object secret -> wrong_kind", [i["code"] for i in bad_obj], ["wrong_kind"])
    check("check_expression role thing -> []",
          qc.check_expression({"type": "holds_item", "params": {"item": "thing"}},
                              qc.Scope(role_map, {}), allowed_kinds=("condition",)),
          [])

    SECTION[0] = "[N]"
    print("[N] knows_secret")
    sid = secrets.add_secret("Nim", "Under the roots.", source="quest",
                             source_ref="quest_run:qr_smoke")["id"]
    hint_objs = {"hint": {"owner": "Nim", "secret_id": sid},
                 "gone": {"owner": "Nim", "secret_id": "sec_does_not_exist"}}
    ctx_n = dataclasses.replace(ctx, objects=hint_objs)
    check("Ada does not know", ev("knows_secret", ctx_n, secret="hint"), (True, False))
    secrets.add_known_by("Nim", sid, "Ada")
    check("Ada knows after add_known_by", ev("knows_secret", ctx_n, secret="hint"), (True, True))
    check("missing object -> unavailable", ev("knows_secret", ctx_n, secret="nohint"), (False, False))
    check("gone secret -> unavailable", ev("knows_secret", ctx_n, secret="gone"), (False, False))
    nim_ctx = dataclasses.replace(qt.build_context("Nim", run), objects=hint_objs)
    check("owner Nim knows own secret", ev("knows_secret", nim_ctx, secret="hint"), (True, True))
    secrets.add_known_by("Nim", sid, "Lio")
    kai_n = dataclasses.replace(qt.build_context("Kai", run), objects=hint_objs)
    check("linked: Kai knows what Lio learned", ev("knows_secret", kai_n, secret="hint"), (True, True))
    sid2 = secrets.add_secret("Nim", "Behind the waterfall.", source="quest",
                              source_ref="quest_run:qr_smoke")["id"]
    secrets.add_known_by("Nim", sid2, "Lio")
    lio_n = dataclasses.replace(qt.build_context("Lio", run),
                                objects={"hint2": {"owner": "Nim", "secret_id": sid2}})
    check("linked: Lio knows secret learned through Lio", ev("knows_secret", lio_n, secret="hint2"), (True, True))

    SECTION[0] = "[O]"
    print("[O] found_item")
    spot_ref = {"location_id": "inn", "room_id": "cellar", "item_id": lantern, "quantity": 1}
    ctx_o = dataclasses.replace(ctx, objects={"spot": spot_ref})
    check("no found fact", ev("found_item", ctx_o, placement="spot"), (True, False))
    add_fact("Ada", "found", qt.found_subject("inn", "cellar", lantern))
    check("found fact passes", ev("found_item", ctx_o, placement="spot"), (True, True))
    check("found_subject format", qt.found_subject("inn", "cellar", "x"), "inn/cellar/x")
    check("missing target -> unavailable", ev("found_item", ctx_o, placement="nospot"), (False, False))
    add_fact("Kai", "found", qt.found_subject("inn", "cellar", lantern))
    lio_o = dataclasses.replace(qt.build_context("Lio", run), objects={"spot": spot_ref})
    check("linked: Lio sees Kai's found fact", ev("found_item", lio_o, placement="spot"), (True, True))

    SECTION[0] = "[P]"
    print("[P] near_object")
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import motion_time, utc_now_iso
    now_iso = utc_now_iso()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO world_props (id, prop_id, x, z, yaw_deg, offset_y, variant, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("wp_rock", "rock", 100.0, 0.0, 0.0, 0.0, None, now_iso, now_iso),
        )
    near_objs = {
        "rock": {"placement_id": "wp_rock", "written": True},
        "gone_rock": {"placement_id": "wp_gone", "written": True},
        "chair": {"location_id": "inn", "room_id": "hall", "place_id": "pl_1", "prop_id": "p1"},
        "spot": spot_ref,
    }
    ctx_p = dataclasses.replace(ctx, objects=near_objs)
    chars._write_character_pos("Ada", 108.0, 6.0)
    check("(108, 6) distance 10.0 <= default 10", ev("near_object", ctx_p, object="rock"), (True, True))
    chars._write_character_pos("Ada", 111.0, 0.0)
    check("(111, 0) distance 11.0 > default 10", ev("near_object", ctx_p, object="rock"), (True, False))
    check("(111, 0) with radius_m=11", ev("near_object", ctx_p, object="rock", radius_m=11), (True, True))
    chars._write_character_pos("Ada", None, None)
    check("no point -> (T, F)", ev("near_object", ctx_p, object="rock"), (True, False))
    check("gone placement -> (F, F)", ev("near_object", ctx_p, object="gone_rock"), (False, False))

    chars._write_character_pos("Ada", 0.0, 0.0)
    with keyed_lock("character_profile", "Ada"):
        prof = chars.get_character_profile("Ada")
        prof["journey"] = {
            "target": "",
            "target_point": {"x": 200.0, "z": 0.0},
            "waypoints": [[0.0, 0.0, 0.0], [200.0, 0.0, 200.0]],
            "started_at_s": motion_time() - 108.0,
            "speed_m_s": 1.0,
        }
        prof["movement_target"] = ""
        chars.save_character_profile("Ada", prof)
    try:
        ctx_j = dataclasses.replace(qt.build_context("Ada", run), objects=near_objs)
        check("journey-aware position near (108, 0)", ev("near_object", ctx_j, object="rock"), (True, True))
    finally:
        with keyed_lock("character_profile", "Ada"):
            prof = chars.get_character_profile("Ada")
            prof.pop("journey", None)
            chars.save_character_profile("Ada", prof)

    ctx_hall = dataclasses.replace(ctx, location_id="inn", room_id="hall", objects=near_objs)
    ctx_cellar = dataclasses.replace(ctx, location_id="inn", room_id="cellar", objects=near_objs)
    check("room_prop chair in inn/hall", ev("near_object", ctx_hall, object="chair"), (True, True))
    check("room_prop chair from inn/cellar", ev("near_object", ctx_cellar, object="chair"), (True, False))
    check("room_item spot in inn/cellar", ev("near_object", ctx_cellar, object="spot"), (True, True))

    if FAILURES:
        print(f"FAIL smoke_quest_types: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_types: [0], [A]-[P]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
