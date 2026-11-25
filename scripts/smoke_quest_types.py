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
        return [(i["code"], i["path"]) for i in
                qc.check_expression({"type": type_id, "params": params}, roles, allowed_kinds=kinds)]

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

    if FAILURES:
        print(f"FAIL smoke_quest_types: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_types: [0], [A]-[J]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
