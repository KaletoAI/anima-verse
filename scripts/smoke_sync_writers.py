#!/usr/bin/env python3
"""B-T2a writer smoke, hand-derived expectations (all cases NEU).

All cases are red on a241a8aa: sync_topics was absent there, and writers
had no fog-filtered hooks. Each case starts a fresh X/Y/Z world: a+npc in
X, b in Y, c in Z. Movement traces also record utterances, so move and
arrival reach a/b with presence+scene; own_move reaches a/c with both and removes
a from X; wilderness reaches only a with presence; room reaches a with
presence+scene. Starting travel reaches a with presence,
never b at its destination; arrival then reaches a/b. Utterance reaches a
with scene. Outfit reaches a with presence+self. Party reaches a with
presence+notices. Private npc patches reach nobody; private a reaches only
a with self. Public npc patches reach a with presence+self. Delete,
model_checkpoint and profile_image reach only a with presence. The twin
world_dev_patch follows the same private/public rule. Inventory is NEU:
the old writers have no sync calls. Helper failures are NEU because the
helpers did not exist; injected lookup/notification failures must escape
none of them, and party_of must return empty. No REGRESSION cases are relabelled.
NEU review cases: stale_move_hook ends bound to committed Z and rejects Y-only
notifications; failed_location/failed_wake keep queues empty and bindings unchanged.
Alias mutations reject unhooked writers and accept hooked writers.
NEU partial_interaction_end signals only the saved actor at X, never the
failed partner at Y; failed_cancel emits no signal after a rejected save.
Dotted publisher imports require a sync hook too.
A repeated model checkpoint is a no-op and must produce no second signal.
"""
import ast
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="sync-writers-")
os.environ["ANIMATION_CLIPS_DIR"] = str(Path(TEMP.name) / "clips")
from app.core import paths
paths.init(Path(TEMP.name) / "initial")
from app.core import db, places, state_events, sync_topics
from app.models import character as ch, world
from app.core import character_ops, party_engine, perception, travel_engine, model3d
state_events.publish = lambda *a, **kw: None

# B-T2a matrix, including the binding Step-0 amendments; row 18 is dropped.
INVENTORY = {
    "app/models/character.py": "save_character_current_location save_character_current_room _publish_activity_changed enter_offmap_sleep wake_from_offmap appear_in_world _clear_location_and_room set_is_sleeping save_character_current_feeling delete_character set_character_profile_image add_character_image delete_character_image".split(),
    "app/core/places.py": "assign release assign_pair".split(),
    "app/core/travel_engine.py": "start_journey start_journey_to_point cancel_journey _settle_arrival".split(),
    "app/core/party_engine.py": "add_to_party leave_party disband_party create_pending_invite settle_pending_invite close_intent_invites clear_invites_for".split(),
    "app/core/interaction_engine.py": "start_interaction end_interaction create_invite _set_invite_status _claim_invite cancel_invite clear_invites_for _sweep_invites".split(),
    "app/models/inventory.py": ["_notify_outfit_changed"],
    "app/core/model3d.py": ["_publish_signature", "_serial_model"],
    "app/core/perception.py": ["record_utterance"],
    "app/core/npc_pool.py": ["_unplace"],
    "app/core/character_ops.py": ["apply_profile_update"],
    "app/routes/world_dev.py": ["_apply_profile_patch_data_sync"],
    "app/models/world.py": ["evict_rooms_to_ground"],
}


# Rows 10 and 15 inherit the location/publication writers rather than adding
# a second hook. Guard those edges as well as the direct-hook inventory.
DELEGATED = {
    "app/core/places.py": {"release_pair": "release"},
    "app/core/travel_engine.py": {"_settle_arrival": "save_character_current_location"},
    "app/core/model3d.py": {"_checkpoint_mesh": "_publish_signature"},
}


def hook(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "sync_topics"
               for n in ast.walk(fn))


def dotted_name(node):
    """Resolve a name/attribute receiver to its full dotted spelling."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def publisher_errors(source, file="injected.py"):
    errors = []
    tree = ast.parse(source)
    aliases = {n.asname or n.name for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module == "app.core.state_events"
               for n in n.names if n.name == "publish"}
    modules = {alias.asname or alias.name
               for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "app.core" for alias in node.names
               if alias.name == "state_events"}
    modules.update(alias.asname or alias.name
                   for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names if alias.name == "app.core.state_events")
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        publishes = any(isinstance(n, ast.Call) and (
            isinstance(n.func, ast.Name) and n.func.id in aliases or
            isinstance(n.func, ast.Attribute) and n.func.attr == "publish"
            and dotted_name(n.func.value) in modules)
            for n in ast.walk(fn))
        if publishes and not hook(fn):
            errors.append(f"{file}:{fn.name} unhooked state publisher")
    return errors


def inventory():
    errors = []
    for file, names in INVENTORY.items():
        tree = ast.parse((ROOT / file).read_text())
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if isinstance(node, (ast.With, ast.AsyncWith)) and any(
                isinstance(part, ast.Call) and (
                    isinstance(part.func, ast.Name) and part.func.id == "transaction" or
                    isinstance(part.func, ast.Attribute) and part.func.attr == "transaction")
                for item in node.items for part in ast.walk(item.context_expr)):
                if hook(node):
                    errors.append(f"{file}:{node.lineno} sync hook inside transaction")
        for caller, target in DELEGATED.get(file, {}).items():
            if caller not in funcs or not any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == target for n in ast.walk(funcs[caller])):
                errors.append(f"{file}:{caller} missing inherited writer {target}")
        for name in names:
            if name not in funcs or not hook(funcs[name]):
                errors.append(f"{file}:{name} missing sync hook")
    for file in (ROOT / "app").rglob("*.py"):
        errors.extend(publisher_errors(file.read_text(), str(file.relative_to(ROOT))))
    assert not errors, "\n".join(errors)


def inventory_self_check():
    """NEU: alias mutations reject unhooked writers and accept hooked ones."""
    forms = [("from app.core import state_events", "state_events.publish"),
             ("from app.core import state_events as X", "X.publish"),
             ("import app.core.state_events as X", "X.publish"),
             ("import app.core.state_events", "app.core.state_events.publish"),
             ("import app.core.state_events as se", "se.publish"),
             ("from app.core.state_events import publish", "publish"),
             ("from app.core.state_events import publish as Y", "Y")]
    for imp, call in forms:
        source = f"{imp}\ndef injected_writer():\n    {call}('demo', 'a')\n"
        try:
            assert not publisher_errors(source), "\n".join(publisher_errors(source))
        except AssertionError as error:
            assert "injected.py:injected_writer unhooked state publisher" in str(error), error
        else:
            raise AssertionError(f"guard missed {imp}")
        assert not publisher_errors(source + "    from app.core import sync_topics\n    sync_topics.changed_at('a')\n")


def fixture(case):
    for conn in sync_topics.connections():
        sync_topics.unregister(conn)
    for conn in list(db._connections.values()):
        conn.close()
    db._connections.clear()
    paths.init(Path(TEMP.name) / case)
    db.init_schema()
    places.invalidate()
    locs = {}
    for i, label in enumerate(("X", "Y", "Z")):
        loc = world.add_location(label, "demo smoke")["id"]
        world.update_location_position(loc, i * 100.0, 0.0)
        locs[label] = loc
    data = world._load_world_data()
    for loc in data["locations"]:
        loc["map3d"] = {"plan_width_m": 10, "boundary": [[-5,-5],[5,-5],[5,5],[-5,5]],
                        "boundary_openings": [{"edge": 3, "at": .5, "width_m": 4, "type": "passage"},
                                              {"edge": 1, "at": .5, "width_m": 4, "type": "passage"}]}
    world._save_world_data(data)
    for name, label in (("a", "X"), ("b", "Y"), ("c", "Z"), ("npc", "X")):
        ch.save_character_profile(name, {"current_location": ""}, create_new=True)
        ch.save_character_current_location(name, locs[label])
        ch.set_known_locations(name, list(locs.values()))
    conns = [sync_topics.register(n, "demo", n, locs[l]) for n, l in (("a","X"),("b","Y"),("c","Z"))]
    drain(conns)
    return locs, conns


def drain(conns):
    result = []
    for conn in conns:
        topics, _ = conn.take()
        result.append(set(topics))
        conn.delivered()
    return result


def expect(conns, a=(), b=(), c=()):
    actual = drain(conns)
    assert actual == [set(a), set(b), set(c)], actual


def behaviour(case):
    loc, conns = fixture(case)
    if case == "stale_move_hook":
        # NEU: pause X->Y's hook after commit; finish Y->Z before resuming it.
        paused, resume = threading.Event(), threading.Event()
        original = sync_topics.moved
        errors = []
        def delayed(character, from_id, to_id):
            if character == "a" and to_id == loc["Y"]:
                paused.set()
                assert resume.wait(10), "stale hook was not released"
            original(character, from_id, to_id)
        def first_move():
            try:
                ch.save_character_current_location("a", loc["Y"])
            except Exception as error:
                errors.append(error)
        with patch.object(sync_topics, "moved", side_effect=delayed):
            thread = threading.Thread(target=first_move)
            thread.start()
            try:
                assert paused.wait(10), "first move did not reach its hook"
                ch.save_character_current_location("a", loc["Z"])
            finally:
                resume.set()
                thread.join(10)
            assert not thread.is_alive(), "stale hook deadlocked"
        assert not errors, errors
        assert conns[0].binding()[1] == loc["Z"], conns[0].binding()
        drain(conns)
        sync_topics.notify("scene", to=sync_topics.AtLocation(loc["Y"]))
        expect(conns, b=["scene"])
    elif case in ("failed_location", "failed_wake"):
        # NEU: failed persistence leaves all queues empty and binding unchanged.
        if case == "failed_wake":
            ch.enter_offmap_sleep("a")
            drain(conns)
        before = conns[0].binding()
        with patch.object(ch, "save_character_profile", return_value=False):
            if case == "failed_location":
                ch.save_character_current_location("a", loc["Y"])
            else:
                assert ch.wake_from_offmap("a")
        expect(conns)
        assert conns[0].binding() == before
    elif case == "partial_interaction_end":
        # NEU: A's committed removal changes X; B's rejected removal changes no Y.
        from app.core import interaction_engine
        for name, partner in (("a", "b"), ("b", "a")):
            profile = ch.get_character_profile(name)
            profile["interaction"] = {"id": "demo-pair", "partner": partner,
                                      "kind": "demo", "pose_key": "demo-pose",
                                      "role": "actor", "started_at_game": "demo-time"}
            assert ch.save_character_profile(name, profile)
        drain(conns)
        save = ch.save_character_profile
        def save_actor_only(name, profile, **kwargs):
            return False if name == "b" else save(name, profile, **kwargs)
        with patch.object(ch, "save_character_profile", side_effect=save_actor_only), patch("app.core.room_stand.stand_up"), patch.object(sync_topics, "changed_at", wraps=sync_topics.changed_at) as changed:
            assert interaction_engine.end_interaction("a")
        assert [call.args[0] for call in changed.call_args_list] == ["a"]
        assert not ch.get_character_profile("a").get("interaction")
        assert ch.get_character_profile("b").get("interaction")
        expect(conns, ["presence"])
    elif case == "failed_cancel":
        # NEU: failed clearing keeps the journey and emits no presence signal.
        journey, reason = travel_engine.start_journey("npc", loc["Y"])
        assert journey, reason
        drain(conns)
        with patch.object(ch, "save_character_profile", return_value=False):
            travel_engine.cancel_journey("npc")
        assert ch.get_character_profile("npc").get("journey")
        expect(conns)
    elif case == "move":
        ch.save_character_current_location("npc", loc["Y"])
        expect(conns, ["presence", "scene"], ["presence", "scene"])
    elif case == "own_move":
        ch.save_character_current_location("a", loc["Z"])
        expect(conns, ["presence", "scene"], c=["presence", "scene"])
        assert conns[0].location == loc["Z"]
        sync_topics.notify("scene", to=sync_topics.AtLocation(loc["X"]))
        expect(conns)
    elif case == "wilderness":
        ch.set_character_pos("npc", 1000, 1000)
        expect(conns, ["presence"])
    elif case == "room":
        room = world.add_room(loc["X"], "demo room")["id"]
        ch.save_character_current_room("npc", room)
        expect(conns, ["presence", "scene"])
    elif case == "travel_start":
        journey, reason = travel_engine.start_journey("npc", loc["Y"])
        assert journey, reason
        expect(conns, ["presence"])
        ch.save_character_current_location("npc", loc["Y"])
        expect(conns, ["presence", "scene"], ["presence", "scene"])
    elif case == "utterance":
        assert perception.record_utterance(speaker="npc", content="demo words", location_id=loc["X"], room_id=world.GROUND_ROOM_ID)
        expect(conns, ["scene"])
    elif case == "outfit":
        from app.models import inventory as inv
        item = inv.add_item(name="demo shirt", category="outfit_piece", outfit_piece={"slots": ["top"]})
        inv.add_to_inventory("a", item["id"])
        drain(conns)
        assert inv.equip_piece("a", item["id"])["status"] == "ok"
        expect(conns, ["presence", "self"])
    elif case == "party":
        iid = party_engine.create_pending_invite("a", "npc")
        assert party_engine.settle_pending_invite(iid, True)["status"] == "accepted"
        expect(conns, ["presence", "notices"])
    elif case in ("private_profile", "public_profile"):
        fields = {"backstory": "demo"} if case == "private_profile" else {"current_feeling": "happy"}
        character_ops.apply_profile_update("npc", {"fields": fields})
        expect(conns, ["presence", "self"] if case == "public_profile" else [])
        if case == "private_profile":
            character_ops.apply_profile_update("a", {"fields": fields})
            expect(conns, ["self"])
    elif case == "world_dev_patch":
        from app.routes.world_dev import _apply_profile_patch_data_sync
        _apply_profile_patch_data_sync({"character_name": "npc", "fields": {"backstory": "demo"}})
        expect(conns)
        _apply_profile_patch_data_sync({"character_name": "npc", "fields": {"current_feeling": "happy"}})
        expect(conns, ["presence", "self"])
    elif case == "delete":
        assert ch.delete_character("npc")
        expect(conns, ["presence"])
    elif case == "profile_image":
        (ch.get_character_images_dir("npc") / "demo.png").write_bytes(b"demo")
        assert ch.set_character_profile_image("npc", "demo.png")
        expect(conns, ["presence"])
    elif case == "model_checkpoint":
        directory = Path(TEMP.name) / case / "model"
        stage = Path(TEMP.name) / case / "stage"
        directory.mkdir(); stage.mkdir()
        sig = "demo"
        (stage / "demo.glb").write_bytes(b"glTF-demo")
        model3d._staging.directories = {"npc": stage}
        model3d._staging.source_publications = {"npc": {"directory": directory, "token": model3d._publication_token(directory, sig)}}
        try:
            model3d._checkpoint_mesh("npc", sig)
        finally:
            model3d._staging.directories = {}
            model3d._staging.source_publications = {}
        expect(conns, ["presence"])
        model3d._staging.directories = {"npc": stage}
        model3d._staging.source_publications = {"npc": {"directory": directory, "token": model3d._publication_token(directory, sig)}}
        try:
            model3d._checkpoint_mesh("npc", sig)
        finally:
            model3d._staging.directories = {}
            model3d._staging.source_publications = {}
        expect(conns)
    elif case == "helper_failures":
        with patch.object(sync_topics, "_current_location", side_effect=RuntimeError("demo lookup")):
            sync_topics.changed_at("npc")
            sync_topics.travel_changed("npc")
        with patch.object(party_engine, "get_party_of", side_effect=RuntimeError("demo party")):
            assert sync_topics.party_of("npc") == sync_topics.Avatars(())
        with patch.object(sync_topics, "note_location", side_effect=RuntimeError("demo binding")):
            sync_topics.moved("npc", loc["X"], loc["Y"])
        with patch.object(sync_topics, "notify", side_effect=RuntimeError("demo notify")):
            sync_topics.moved("npc", loc["X"], loc["Y"])
            sync_topics.changed_at("npc", loc["X"])
            sync_topics.travel_changed("npc")
            sync_topics.avatars(["npc"], "scene")
            sync_topics.profile_patched("npc", {"backstory": "old"}, {"backstory": "new"})
        sync_topics.avatars(None, "scene")
        sync_topics.profile_patched("npc", None, {})
        expect(conns)


if __name__ == "__main__":
    failures = []
    cases = "move own_move wilderness room travel_start utterance outfit party private_profile public_profile delete model_checkpoint profile_image world_dev_patch helper_failures stale_move_hook failed_location failed_wake partial_interaction_end failed_cancel inventory_self_check inventory".split()
    for case in cases:
        try:
            if case == "inventory":
                inventory()
            elif case == "inventory_self_check":
                inventory_self_check()
            else:
                behaviour(case)
            print(f"PASS {case}")
        except Exception as error:
            failures.append(case)
            print(f"FAIL {case}: {type(error).__name__}: {error}")
    print(f"sync writers: {len(cases)-len(failures)}/{len(cases)} passed")
    sys.exit(bool(failures))
