#!/usr/bin/env python3
"""B-T2a/B-T2b writer smoke, hand-derived expectations (all cases NEU).

All cases are red on a241a8aa: sync_topics was absent there, and writers
had no fog-filtered hooks. Each case starts a fresh X/Y/Z world: a+npc in
X, b in Y, c in Z. Movement traces also record utterances, so move and
arrival reach a/b with presence+scene; own_move reaches a/c with both and removes
a from X. Its committed history adds self for a; outfit compliance creates
an owner mismatch notification, adding notices for a; wilderness reaches only a with presence; room reaches a with
presence+scene. Starting travel reaches a with presence,
never b at its destination; arrival then reaches a/b. Utterance reaches a
with scene. Outfit reaches a with presence+self. Party reaches a with
presence+notices. Private npc patches reach nobody; private a reaches only
a with self. Public npc patches reach a with presence+self. Delete,
model_checkpoint reaches a with presence; profile_image reaches a with presence+self. The twin
world_dev_patch follows the same private/public rule. Inventory is NEU:
the old writers have no sync calls. Helper failures are NEU because the
helpers did not exist; injected lookup/notification failures must escape
none of them, and party_of must return empty. No REGRESSION cases are relabelled.
NEU review cases: stale_move_hook ends bound to committed Z and rejects Y-only
notifications; failed_location/failed_wake keep queues empty and bindings unchanged
when independent history/notification writes are stubbed.
Alias mutations reject unhooked writers and accept hooked writers.
NEU partial_interaction_end signals only the saved actor at X, never the
failed partner at Y; failed_cancel emits no signal after a rejected save.
Dotted publisher imports require a sync hook too.
A repeated model checkpoint is a no-op and must produce no second signal.
"""
import ast
from contextlib import contextmanager
import os
import re
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


# B-T2b inventory includes the lowest committed writers and inherited edges.
INVENTORY.update({
    "app/models/notifications.py": ["create_notification", "_mutate_notification", "mark_all_read"],
    "app/models/unified_chat.py": ["save_message", "save_direct_message"],
    "app/routes/play.py": ["_phone_set_read"],
    "app/models/instagram.py": ["save_feed", "delete_post"],
    "app/models/rules.py": ["_rules_changed"],
    "app/models/events.py": ["_events_changed"],
    "app/core/event_images.py": ["publish_image_ready"],
    "app/models/inventory.py": ["_notify_outfit_changed", "_save_inventory", "add_item_to_room", "remove_item_from_room"],
    "app/models/world.py": ["evict_rooms_to_ground", "_after_world_write", "update_room_description", "toggle_background_image", "remove_background_image"],
    "app/models/terrain.py": ["_bump_terrain_generation"],
    "app/core/terrain_types.py": ["_bump_types_generation"],
    "app/models/world_props.py": ["_bump_world_props_generation"],
    "app/models/heightfield.py": ["save_height_area", "delete_height_area", "save_height_areas_bulk"],
    "app/core/scene_recipe.py": ["invalidate_prop_lib_token"],
    "app/core/surface_textures.py": ["_surface_changed"],
    "app/models/thought_store.py": ["add_thought"],
    "app/models/memory.py": "save_memories add_memory delete_memory clear_memories record_mood".split(),
    "app/models/diary.py": ["_save_stored"],
    "app/models/relationship.py": ["_save_relationship"],
})
INVENTORY["app/models/chat_stat_evaluations.py"] = ["commit_evaluation"]
INVENTORY["app/models/character.py"] += ["record_state_change", "adjust_status_effects", "set_state_flag"]


# Rows 10 and 15 inherit the location/publication writers rather than adding
# a second hook. Guard those edges as well as the direct-hook inventory.
DELEGATED = {
    "app/core/places.py": {"release_pair": "release"},
    "app/core/travel_engine.py": {"_settle_arrival": "save_character_current_location"},
    "app/core/model3d.py": {"_checkpoint_mesh": "_publish_signature"},
}

DELEGATED.update({
    "app/models/notifications.py": {"mark_read": "_mutate_notification", "delete_notification": "_mutate_notification"},
    "app/models/instagram.py": {"create_post": "save_feed"},
    "app/models/rules.py": {"save_rules": "_rules_changed", "_save_shared_rules": "_rules_changed"},
    "app/models/events.py": {n: "_events_changed" for n in ("_insert_event", "_update_event", "_delete_event_row", "expire_events")},
    "app/models/world.py": {"delete_location_row": "_after_world_write", "replace_all_locations": "_after_world_write", "_upsert_locations": "_after_world_write", "_save_world_data": "_upsert_locations", "upsert_location": "_upsert_locations", "upsert_locations": "_upsert_locations", "add_room": "upsert_location"},
    "app/core/surface_textures.py": {n: "_surface_changed" for n in ("_write_selection", "_write_blends", "_write_kind_meta", "save_uploaded", "delete_texture", "set_size_m")},
    "app/models/diary.py": {"add_summary": "_save_stored"},
    "app/models/relationship.py": {"record_interaction": "save_relationships", "set_address": "save_relationships", "save_relationships": "_save_relationship"},
})
DELEGATED["app/models/character.py"] = {"force_set_status": ("save_character_current_location", "save_character_current_room", "save_character_current_feeling", "set_pose_intent")}


def source_files():
    """Follow plugin pack symlinks; rglob/git grep do not descend into them."""
    for base in ("app", "plugins"):
        for directory, dirs, files in os.walk(ROOT / base, followlinks=True):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
            for filename in files:
                if filename.endswith(".py"):
                    yield Path(directory) / filename


def keyword_errors(source, file):
    errors = []
    for n in ast.walk(ast.parse(source)):
        if not isinstance(n, ast.Call):
            continue
        name = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
        if name in ("upsert_location", "upsert_locations", "add_room") and not any(k.arg == "sync_world" for k in n.keywords):
            errors.append(f"{file}:{n.lineno} {name} missing explicit sync_world")
    return errors


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
    for file in INVENTORY.keys() | DELEGATED.keys():
        names = INVENTORY.get(file, [])
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
        for caller, targets in DELEGATED.get(file, {}).items():
            for target in (targets if isinstance(targets, tuple) else (targets,)):
                if caller not in funcs or not any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == target for n in ast.walk(funcs[caller])):
                    errors.append(f"{file}:{caller} missing inherited writer {target}")
        for name in names:
            if name not in funcs or not hook(funcs[name]):
                errors.append(f"{file}:{name} missing sync hook")
    for file in source_files():
        source = file.read_text()
        errors.extend(publisher_errors(source, str(file.relative_to(ROOT))))
        errors.extend(keyword_errors(source, str(file.relative_to(ROOT))))
    tree = ast.parse((ROOT / "app/models/world.py").read_text())
    for name in ("upsert_location", "upsert_locations", "_after_world_write", "add_room"):
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        required = {arg.arg for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults) if default is None}
        if "sync_world" not in required:
            errors.append(f"{name}: sync_world must be a required keyword")
    assert not errors, "\n".join(errors)


def inventory_self_check():
    """NEU: alias mutations reject unhooked writers and accept hooked ones."""
    for name in ("upsert_location", "upsert_locations", "add_room"):
        assert keyword_errors(f"{name}({{}})", "injected.py")
        assert keyword_errors(f"world.{name}({{}})", "injected.py")
        assert not keyword_errors(f"{name}({{}}, sync_world=False)", "injected.py")
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
        with patch.object(ch, "save_character_profile", return_value=False), patch.object(ch, "record_state_change"), patch("app.models.notifications.create_notification", return_value=""):
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
        expect(conns, ["presence", "scene", "self", "notices"], c=["presence", "scene"])
        assert conns[0].location == loc["Z"]
        sync_topics.notify("scene", to=sync_topics.AtLocation(loc["X"]))
        expect(conns)
    elif case == "wilderness":
        ch.set_character_pos("npc", 1000, 1000)
        expect(conns, ["presence"])
    elif case == "room":
        room = world.add_room(loc["X"], "demo room", sync_world=True)["id"]
        drain(conns)
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
        expect(conns, ["presence", "self"])
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
            sync_topics.moved("a", loc["X"], loc["Y"])
        with patch.object(sync_topics, "notify", side_effect=RuntimeError("demo notify")):
            sync_topics.moved("npc", loc["X"], loc["Y"])
            sync_topics.changed_at("npc", loc["X"])
            sync_topics.travel_changed("npc")
            sync_topics.avatars(["npc"], "scene")
            sync_topics.profile_patched("npc", {"backstory": "old"}, {"backstory": "new"})
        sync_topics.avatars(None, "scene")
        sync_topics.profile_patched("npc", None, {})
        expect(conns)


def behaviour_part3(case):
    """NEU (a241a8aa lacked hooks). Hand oracle: owner=a; Y=b; Z=c;
    structure/global events=all; visible room items=R1 only, hidden=none.
    Embedding scheduling is stubbed: this smoke proves DB writes and routing,
    and must not start an ONNX worker during interpreter shutdown.
    A cold height cache must never turn a local item write into world push.
    """
    loc, conns = fixture("part3_" + case)
    from app.models import notifications, inventory as inv, events, rules, memory
    if case == "notification":
        nid = notifications.create_notification("npc", "demo", metadata={"to": "a"})
        assert nid
        expect(conns, ["notices"])
        assert notifications.mark_read(nid)
        expect(conns, ["notices"])
    elif case == "mark_all_global":
        with db.transaction() as conn:
            conn.execute("DELETE FROM notifications")
        for name in ("a", "b"):
            notifications.create_notification("npc", "demo", metadata={"to": name})
        drain(conns)
        assert notifications.mark_all_read(None) == 2
        expect(conns, ["notices"], ["notices"])
    elif case == "phone":
        from app.models.unified_chat import UnifiedChatManager
        from app.models.channel import Message
        assert UnifiedChatManager.save_message(Message(role="assistant", content="demo", medium="messaging"), "npc", "a")
        expect(conns, ["notices"])
    elif case == "inventory":
        item = inv.add_item(name="demo item")
        inv.add_to_inventory("a", item["id"])
        expect(conns, ["self"])
    elif case.startswith("room_item"):
        r1 = world.add_room(loc["X"], "demo R1", sync_world=True)["id"]
        r2 = world.add_room(loc["X"], "demo R2", sync_world=True)["id"]
        for name, room in (("a", r1), ("npc", r1), ("d", r2)):
            if name == "d":
                ch.save_character_profile(name, {"current_location": ""}, create_new=True)
                ch.save_character_current_location(name, loc["X"])
            ch.save_character_current_room(name, room)
        conns.append(sync_topics.register("d", "demo", "d", loc["X"]))
        item = inv.add_item(name="demo item")
        drain(conns)
        if case == "room_item_cold":
            from app.core import heightfield
            heightfield.invalidate_cache()
        assert inv.add_item_to_room(loc["X"], r1, item["id"], hidden=case == "room_item_hidden")
        assert drain(conns) == ([set()] * 4 if case == "room_item_hidden" else [{"self"}, set(), set(), set()])
    elif case == "world_admin":
        world.upsert_location(world.get_location_by_id(loc["X"]), sync_world=True)
        expect(conns, ["world"], ["world"], ["world"])
    elif case == "background_skill":
        world.toggle_background_image(loc["Y"], "demo.png")
        expect(conns, b=["scene"])
    elif case in ("terrain", "height"):
        raw = {"polygon": [[0,0],[5,0],[5,5],[0,5]], "height_m": 2, "kind": "grass"}
        if case == "terrain":
            from app.models.terrain import save_area
            save_area(raw)
        else:
            from app.models.heightfield import save_height_area
            save_height_area(raw)
        expect(conns, ["world"], ["world"], ["world"])
    elif case.startswith("event_"):
        events.add_event("demo", location_id=loc["Y"] if case == "event_local" else None)
        if case == "event_local":
            expect(conns, b=["notices", "scene", "world"])
        else:
            expect(conns, ["notices", "scene", "world"], ["notices", "scene", "world"], ["notices", "scene", "world"])
    elif case == "rule_local":
        rules.save_rules([{"id": "demo", "target": {"scope": "location", "location_id": loc["Z"]}}])
        expect(conns, c=["notices", "scene", "world"])
    elif case == "force_status":
        # NEU: clearing an admin-forced activity changes presence and self.
        profile = ch.get_character_profile("npc")
        profile.update(pose_key="standing", pose_flavor="demo activity", place=None)
        assert ch.save_character_profile("npc", profile)
        drain(conns)
        ch.force_set_status("npc", activity="")
        expect(conns, ["presence", "self"])
    elif case == "mind":
        with patch("app.core.memory_situational.schedule_embedding"):
            memory.add_memory("a", "demo memory")
        expect(conns, ["self"])


def commit_failures():
    """NEU: a rejected COMMIT rolls back the row and sends no topic.

    Hand oracle: all queues remain empty after each rejected transaction;
    the rejected notification/feed/event/inventory/world rows stay absent.
    """
    loc, conns = fixture("commit_failures")
    from app.models import notifications, inventory as inv, events, rules, instagram, memory, thought_store, diary, relationship
    from app.models.unified_chat import UnifiedChatManager
    from app.models.channel import Message
    from app.routes import play
    @contextmanager
    def rejected():
        conn = db.get_connection()
        try:
            yield conn
            raise RuntimeError("demo rejected commit")
        finally:
            conn.rollback()
    writers = [
        (notifications, lambda: notifications.create_notification("a", "demo")),
        (instagram, lambda: instagram.save_feed([{"id": "demo", "agent_name": "a"}])),
        (events, lambda: events.add_event("demo", location_id=loc["X"])),
        (rules, lambda: rules.save_rules([{"id": "demo", "character": "a"}])),
        (inv, lambda: inv._save_inventory("a", {"inventory": []})),
        (world, lambda: world.upsert_location({"id": "demo", "name": "demo"}, sync_world=True)),
        (memory, lambda: memory.add_memory("a", "demo")),
        (memory, lambda: memory.save_memories("a", [])),
        (memory, lambda: memory.record_mood("a", "happy")),
        (thought_store, lambda: thought_store.add_thought("a", "demo")),
        (diary, lambda: diary.add_summary("a", "demo", "Y0001-D001")),
        (relationship, lambda: relationship._save_relationship({"character_a": "a", "character_b": "b"})),
    ]
    for module, write in writers:
        with patch.object(module, "transaction", rejected):
            if module is rules:
                try:
                    write()
                except rules.RuleWriteError:
                    pass
                else:
                    raise AssertionError("Rejected rule commit must report a storage error")
            else:
                write()
        expect(conns)
    assert db.get_connection().execute("SELECT 1 FROM rules WHERE id='demo'").fetchone() is None
    with patch("app.models.unified_chat.transaction", rejected):
        assert not UnifiedChatManager.save_message(Message(role="assistant", content="demo", medium="messaging"), "npc", "a")
    with patch.object(db, "transaction", rejected):
        play._phone_set_read("a", "npc", "demo")
    expect(conns)
    assert world.get_location_by_id("demo") is None


def scope_changes():
    """NEU: owners/old and new scopes follow committed changes only.

    Rules and events moving X->Y reach a and b; removal reaches Y only.
    A hidden->visible or visible->hidden item reaches a in R1; hidden->hidden
    reaches nobody. Notification deletion and whitelisted reads reach owners.
    """
    loc, conns = fixture("scope_changes")
    from app.models import rules, events, notifications, inventory as inv
    rules.save_rules([{"id": "demo", "target": {"scope": "location", "location_id": loc["X"]}}])
    drain(conns)
    rules.save_rules([{"id": "demo", "target": {"scope": "location", "location_id": loc["Y"]}}])
    expect(conns, ["notices", "scene", "world"], ["notices", "scene", "world"])
    rules.save_rules([])
    expect(conns, b=["notices", "scene", "world"])
    event = events.add_event("demo", location_id=loc["X"])
    drain(conns)
    event["location_id"] = loc["Y"]
    assert events._update_event(event)
    expect(conns, ["notices", "scene", "world"], ["notices", "scene", "world"])
    assert events._delete_event_row(event["id"])
    expect(conns, b=["notices", "scene", "world"])
    nid = notifications.create_notification("npc", "demo", metadata={"to": "a"})
    drain(conns)
    assert notifications.delete_notification(nid)
    expect(conns, ["notices"])
    room = world.add_room(loc["X"], "demo R1", sync_world=True)["id"]
    ch.save_character_current_room("a", room)
    item = inv.add_item(name="demo")
    drain(conns)
    for hidden, expected in ((True, []), (False, ["self"]), (True, ["self"]), (True, [])):
        assert inv.add_item_to_room(loc["X"], room, item["id"], hidden=hidden)
        expect(conns, expected)
    assert inv.remove_item_from_room(loc["X"], room, item["id"])
    expect(conns)


def rule_editor_scope():
    """REGRESSION: RulesTab location/rooms reaches only a at X.

    b at Y and c at Z cannot see X; a room selection still routes to X.
    """
    loc, conns = fixture("rule_editor_scope")
    from app.models import rules
    room = world.add_room(loc["X"], "demo room", sync_world=True)["id"]
    drain(conns)
    for rooms in ([], [room]):
        target = {"scope": "location", "action": "enter", "location": loc["X"]}
        if rooms:
            target["rooms"] = rooms
        rules.save_rules([{"id": "demo", "name": "demo", "type": "block",
                           "condition": "", "message": "demo", "target": target}])
        expect(conns, ["notices", "scene", "world"])


def rule_character_scope():
    """REGRESSION: character a overrides location Y on add/change/delete.

    a is at X, b at Y, c at Z: all three writes must reach only a.
    """
    loc, conns = fixture("rule_character_scope")
    from app.models import rules
    rule = {"id": "demo", "character": "a",
            "target": {"scope": "location", "location_id": loc["Y"]}}
    rules.save_rules([rule])
    expect(conns, ["notices", "scene", "world"])
    rule["message"] = "changed"
    rules.save_rules([rule])
    expect(conns, ["notices", "scene", "world"])
    rules.save_rules([])
    expect(conns, ["notices", "scene", "world"])


def relationship_mixed_decay():
    """REGRESSION: decaying an NPC pair emits nothing to unchanged a/b.

    a/b has today's decay stamp: elapsed zero skips it. The NPC pair was idle
    14 days and last decayed 7 days ago: strength 20 loses exactly 1 point.
    """
    loc, conns = fixture("relationship_mixed_decay")
    from app.models import relationship
    from app.core import relationship_decay
    from app.core.game_time import GameTime, GameDuration
    now = GameTime(0) + GameDuration.of(days=100)
    relationship.record_interaction("a", "b", "demo")
    player = relationship.get_relationship("a", "b")
    player["last_decay_game"] = now.canonical()
    relationship.save_relationships([player])
    relationship._save_relationship({
        "character_a": "npc", "character_b": "npc_other", "strength": 20,
        "last_interaction_game": (now - GameDuration.of(days=14)).canonical(),
        "last_decay_game": (now - GameDuration.of(days=7)).canonical()})
    before = relationship.get_relationship("a", "b")
    drain(conns)
    with patch.object(relationship_decay, "game_time", return_value=now):
        assert relationship_decay.handle_relationship_decay({})["success"]
    expect(conns)
    assert relationship.get_relationship("a", "b") == before
    npc_pair = relationship.get_relationship("npc", "npc_other")
    assert npc_pair["last_decay_game"] == now.canonical()
    assert npc_pair["strength"] == 19


def review_endpoint_gaps():
    """NEU: hand-derived endpoint keys from actual received writer topics.

    Rule/event => scene, both maps, notices, badges; own movement => notices;
    relationship => others for the pair only; image => self for the owner.
    """
    source = (ROOT / "packages/player-ui/src/syncEndpoints.ts").read_text()
    endpoints = {key: set(re.findall(r"'([^']+)'", topics))
                 for key, topics in re.findall(r"(\w+): \{[^\n]*topics: \[([^\]]+)\]", source)}
    assert len(endpoints) == 9
    def keys(conn):
        topics = drain([conn])[0]
        return {key for key, wanted in endpoints.items() if topics & wanted}
    loc, conns = fixture("review_endpoint_gaps")
    from app.models import rules, events, relationship, account
    expected = {"scene", "worldmapPlayer", "worldmap3d", "notices", "badges"}
    rules.save_rules([{"id": "demo", "character": "a"}])
    assert keys(conns[0]) == expected
    assert keys(conns[1]) == keys(conns[2]) == set()
    event = events.add_event("demo", location_id=loc["X"])
    assert keys(conns[0]) == expected
    assert keys(conns[1]) == keys(conns[2]) == set()
    assert events._delete_event_row(event["id"])
    assert keys(conns[0]) == expected
    drain(conns)
    ch.save_character_current_location("a", loc["Y"])
    assert keys(conns[0]) == set(endpoints)
    drain(conns)
    room = world.add_room(loc["Y"], "demo room", sync_world=True)["id"]
    drain(conns)
    ch.save_character_current_room("a", room)
    assert keys(conns[0]) == set(endpoints)
    assert "notices" not in keys(conns[1])
    drain(conns)
    relationship.record_interaction("a", "b", "demo")
    pair = {"scene", "others", "self", "belongings", "mind", "worldmapPlayer", "worldmap3d"}
    assert keys(conns[0]) == keys(conns[1]) == pair
    assert keys(conns[2]) == set()
    images = ch.get_character_images_dir("a")
    images.mkdir(parents=True, exist_ok=True)
    (images / "demo.png").write_bytes(b"demo")
    assert ch.set_character_profile_image("a", "demo.png")
    assert keys(conns[0]) == pair
    drain(conns)
    with patch("app.core.users.get_user_by_id", return_value={"role": "admin", "settings": {"active_character": "a"}, "allowed_characters": []}):
        assert account.get_active_character_for_user("demo") == "a"
        admin_conn = sync_topics.register("demo", "demo", "", "")
        assert sync_topics.reconcile(admin_conn)
        assert admin_conn.binding()[:2] == ("a", loc["Y"])
        drain([admin_conn])
        sync_topics.notify("self", to=sync_topics.Avatar("a"))
        assert keys(admin_conn) == {"self", "belongings", "mind"}
        sync_topics.unregister(admin_conn)
        drain(conns)
    with patch("app.core.users.get_user_by_id", return_value={"role": "user", "settings": {"active_character": "npc"}, "allowed_characters": ["a"]}):
        assert account.get_active_character_for_user("demo") == "a"
    with patch("app.core.users.get_user_by_id", return_value={"role": "admin", "settings": {}, "allowed_characters": []}), patch.object(account, "get_user_profile", side_effect=AssertionError("shared fallback")):
        assert account.get_active_character_for_user("demo") == ""
    assert len(sync_topics._move_locks) == 64
    with patch.object(sync_topics, "_current_location", side_effect=AssertionError("unbound DB read")):
        for i in range(1000):
            assert sync_topics._refresh_binding(f"demo-unbound-{i}")
    assert len(sync_topics._move_locks) == 64


if __name__ == "__main__":
    failures = []
    cases = "move own_move wilderness room travel_start utterance outfit party private_profile public_profile delete model_checkpoint profile_image world_dev_patch helper_failures stale_move_hook failed_location failed_wake partial_interaction_end failed_cancel inventory_self_check inventory".split()
    cases += ["part3_" + c for c in "notification mark_all_global phone inventory room_item room_item_cold room_item_hidden world_admin background_skill terrain height event_local event_global rule_local mind force_status".split()]
    cases += ["commit_failures", "scope_changes", "rule_editor_scope", "rule_character_scope", "relationship_mixed_decay"]
    cases += ["review_endpoint_gaps"]
    for case in cases:
        try:
            if case in ("review_endpoint_gaps", "commit_failures", "scope_changes", "rule_editor_scope", "rule_character_scope", "relationship_mixed_decay"):
                globals()[case]()
            elif case.startswith("part3_"):
                behaviour_part3(case[6:])
            elif case == "inventory":
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
