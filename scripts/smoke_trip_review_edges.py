#!/usr/bin/env python3
"""Shared-travel review regressions against real storage and movement.

Usage: ./.venv/bin/python scripts/smoke_trip_review_edges.py

Hand-derived expectations: answering proposal A cannot accept a later proposal
B; an expired agreement cannot enter its destination; two interleaved proposals
leave one executable agreement, not two permanently reserved characters. A
closed trip cannot report a later party join without actual membership. Invalid
JSON action scopes are HTTP 400 on both creation and conversion. Ordinary
SetLocation retains immediate avatar movement and placement from nowhere;
consent-bound trips still use their timed movement. A director result and a
third NPC's pair proposal cannot mutate actors reserved while their LLM ran.
A home-area NPC currently in a named room can propose a trip from that room.
Only LLM answers and the event scheduling interleave are scripted; profiles,
intents, invitations, parties, access gates and journeys are real. All storage,
instance, clip metadata and catalog paths are disposable.
"""
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="trip-review-edges-")
ROOT = Path(TEMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
(ROOT / "instance" / "config.json").write_text(json.dumps({
    "providers": [], "embedding": {"backend": "external"}}))
from app.core import config, db, hooks, npc_actions, npc_scenes, party_engine as P, travel_engine, pose_catalog
config.load(ROOT / "world" / "config.json")
db.init_schema()
cfg = config.get_all()
cfg.setdefault("npc", {}).update(conversation_mode="turns", action_tick_enabled=True)
cfg.setdefault("image_generation", {})["enabled"] = False
# Packages are activated per world: party + movement carry the trip code,
# interact the shared activities an undertaking ends with.
cfg["packages"] = {"enabled": "movement,party,interact"}
config.save(cfg)
from app.core.dependencies import get_skill_manager
from app.core.game_time import GameDuration, GameTime
from app.core.keyed_lock import keyed_lock
from app.core.npc_home import circle_home
from app.core.task_queue import get_task_queue
from app.core.timeutils import game_time, set_game_factor, set_game_time
from app.core.users import create_user, update_user
from app.models import character as C, intents as I, world as W
from app.plugins.context import PluginContext
from app.routes.intents import _create_route_sync, _patch_route_sync
from fastapi import HTTPException
from plugins.party import trip_intents as T
from plugins.party.skill import PartySkill
from plugins.movement.skill_set_location import SetLocationSkill
get_skill_manager()
set_game_factor(0)
set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
HOME = W.add_location("Demo inn", "Review rooms.", rooms=[
    {"id": "taproom", "name": "Taproom"}, {"id": "cellar", "name": "Cellar"},
    {"id": "loft", "name": "Loft"}])["id"]
FAR = W.add_location("Demo market", "A timed journey target.", rooms=[
    {"id": "hall", "name": "Hall"}])["id"]
UNPLACED = W.add_location("Demo unplaced", "An ordinary SetLocation target without map coordinates.", rooms=[
    {"id": "hall", "name": "Hall"}])["id"]
for lid, x, edge in [(HOME, 0, 1), (FAR, 100, 3)]:
    loc = W.get_location_by_id(lid)
    loc.update(pos_x=x, pos_z=0, map3d={"plan_width_m": 10,
        "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
        "boundary_openings": [{"edge": edge, "at": 0.5, "width_m": 4, "type": "passage"}]})
    W.upsert_location(loc, sync_world=True)
CLIPS = ROOT / "clips"
CLIPS.mkdir()
for role in ("a", "b"):
    (CLIPS / f"hug__{role}.fbx").write_bytes(b"clip metadata fixture; never parsed as a model")
(CLIPS / "hug.json").write_text(json.dumps({
    "kind": "hug", "pair": True, "fps": 30, "frames": 60, "duration_s": 2,
    "geometry": {"anchor_frame": 30, "root_distance_m": 0.6,
        "roles": {"a": {"anchor_xz_m": [-0.3, 0]}, "b": {"anchor_xz_m": [0.3, 0]}}}}))
CATALOG = ROOT / "pose_catalog.json"
CATALOG.write_text(json.dumps({
    "groups": {"stand": {"label": "Standing", "default": "standing", "needs_place": False}},
    "entries": {"standing": {"prompt": "standing", "group": "stand", "_default": True},
                "embracing": {"prompt": "two people hugging", "group": "stand", "animation": "hug",
                              "solo": False, "places": 2}}}))
original_catalog = pose_catalog.catalog_path
pose_catalog.catalog_path = lambda axis: CATALOG if axis == "pose" else original_catalog(axis)
pose_catalog.reload_catalogs()
JOIN = PartySkill({}, PluginContext("party"), "join")
MOVE = SetLocationSkill({}, PluginContext("movement"))
serial = 0


def character(template="npc-temporary"):
    global serial
    serial += 1
    name = f"demo_review_{serial}"
    assert C.save_character_profile(name, {"character_name": name, "template": template,
        "language": "en", "standing_task": "tends the inn"}, create_new=True)
    C.save_character_current_location(name, HOME)
    C.save_character_current_room(name, "taproom")
    C.set_character_pos(name, 0, 0)
    C.set_known_locations(name, [HOME, FAR, UNPLACED])
    return name


def trip(a, b, location=HOME, room="cellar"):
    return T.propose_trip(a, b, {"location_id": location, "room_id": room})


def invite_id(intent):
    return I.get_intent(intent["id"])["meta"]["travel"]["invite_id"]


def late_answer():
    a, b = character(), character()
    old = trip(a, b)
    old_id = invite_id(old)
    assert I.cancel_intent(old["id"])
    new = trip(a, b, room="loft")
    JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": old_id}))
    assert I.get_intent(new["id"])["status"] == "active", "late A answer accepted B"
    assert P.get_invite(invite_id(new))["status"] == "pending"
    assert all(C.get_character_current_room(n) == "taproom" for n in (a, b))
    JOIN.execute(json.dumps({"agent_name": b, "leader": a, "invite_id": invite_id(new)}))
    assert I.get_intent(new["id"])["status"] == "done"
    assert all(C.get_character_current_room(n) == "loft" for n in (a, b))


def closed_trip_join():
    a, b = character(), character()
    done = trip(a, b)
    iid = invite_id(done)
    assert P.resolve_pending_invite(iid, True)["status"] == "accepted"
    assert I.get_intent(done["id"])["status"] == "done"
    P.leave_party(b)
    assert P.resolve_pending_invite(iid, True)["status"] != "accepted", "old answer reports membership that does not exist"
    JOIN.execute(json.dumps({"agent_name": b, "leader": a}))
    assert (P.get_party_of(b) or {}).get("leader") == a, "historic trip poisoned an ordinary new join"
    assert I.get_intent(done["id"])["status"] == "done"


def expired_paused_journey():
    a, b = character(), character()
    intention = trip(a, b, FAR, "hall")
    I.update_intent(intention["id"], expires_at=(game_time() + GameDuration.of(seconds=1)).canonical())
    assert P.resolve_pending_invite(invite_id(intention), True)["status"] == "accepted"
    assert travel_engine.get_journey(a)
    queue = get_task_queue()
    queue.pause_queue("default")
    try:
        set_game_time(game_time() + GameDuration.of(minutes=10))
        travel_engine.advance_all_journeys()
        assert all(C.get_character_current_location(n) != FAR for n in (a, b)), "expired trip entered destination"
        assert I.get_intent(intention["id"])["status"] == "expired"
        assert not travel_engine.get_journey(a)
    finally:
        queue.resume_queue("default")


def interleaved_proposals():
    a, b = character(), character()
    barrier = threading.Barrier(2)
    emit = I.emit

    def interleave(event, **kwargs):
        if event == "intent_created" and kwargs["intent"]["title"] == "Interleaved shared trip":
            barrier.wait(timeout=5)
        return emit(event, **kwargs)

    def create(owner, target):
        participants = {owner: {"role": "leader"}, target: {"role": "follower"}}
        action = T.intent_action_validate(owner, participants, {"type": "travel_together",
            "destination": {"location_id": HOME, "room_id": "cellar"}, "scope": "pair"})
        barrier.wait(timeout=5)
        return I.create_intent(owner=owner, title="Interleaved shared trip", participants=participants, action=action)

    I.emit = interleave
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, a, b), pool.submit(create, b, a)]
            rows = [future.result(timeout=10) for future in futures]
    finally:
        I.emit = emit
    current = [I.get_intent(row["id"]) for row in rows]
    assert sorted(row["status"] for row in current) == ["active", "cancelled"], current
    winner = next(row for row in current if row["status"] == "active")
    assert P.get_invite(invite_id(winner))["status"] == "pending"
    assert P.resolve_pending_invite(invite_id(winner), True)["status"] == "accepted"
    assert I.get_intent(winner["id"])["status"] == "done"
    assert all(C.get_character_current_room(n) == "cellar" for n in (a, b))


def invalid_scope(create):
    a, b = character(), character()
    participants = {a: {"role": "leader"}, b: {"role": "follower"}}
    action = {"type": "travel_together", "destination": {"location_id": HOME, "room_id": "cellar"},
              "scope": [] if create else {}}
    try:
        if create:
            _create_route_sync({"owner": a, "title": "Invalid scope", "participants": participants, "action": action})
        else:
            ordinary = I.create_intent(owner=a, title="Ordinary plan", participants=participants)
            _patch_route_sync(ordinary["id"], {"action": action})
        raise AssertionError("malformed scope accepted")
    except HTTPException as error:
        assert error.status_code == 400
    assert not P.find_pending_invite(a, b)
    assert not I.list_intents(owner=a) if create else not I.get_intent(ordinary["id"])["action"]


def ordinary_avatar_move():
    name = character("human-roleplay")
    user = create_user("demo", "demo-review-password", allowed_characters=[name])
    assert update_user(user, settings={"active_character": name})
    try:
        MOVE.execute(json.dumps({"agent_name": name, "input": "Demo unplaced, Hall"}))
        assert C.get_character_current_location(name) == UNPLACED
        assert C.get_character_current_room(name) == "hall"
        assert not travel_engine.get_journey(name)
    finally:
        C.save_character_current_location(name, HOME)
        C.save_character_current_room(name, "taproom")


def unplaced_actor_move():
    name = character()
    C.save_character_current_location(name, "")
    MOVE.execute(json.dumps({"agent_name": name, "input": "Demo unplaced, Hall"}))
    assert C.get_character_current_location(name) == UNPLACED
    assert C.get_character_current_room(name) == "hall"
    assert not travel_engine.get_journey(name)


def stale_director():
    a, b = character(), character()
    before = {n: C.get_effective_activity(n) for n in (a, b)}

    def llm(*args, **kwargs):
        trip(a, b)
        return SimpleNamespace(content=json.dumps({"lines": [
            {"speaker": a, "line": "Let us do something else."},
            {"speaker": b, "line": "I am still considering the trip."}],
            "activities": {a: "Starts an unrelated activity", b: "Drops the proposed trip"}}))

    assert npc_scenes.run_scene_for(HOME, "taproom", [a, b], llm=llm) is None
    assert {n: C.get_effective_activity(n) for n in (a, b)} == before
    assert P.find_pending_invite(a, b)
    assert all(C.get_character_current_room(n) == "taproom" for n in (a, b))


def reserved_partner_list():
    a, b, other = character(), character(), character()
    trip(a, b)
    offered = {entry["name"] for entry in npc_actions.present_partners(other)}
    assert not {a, b} & offered, "reserved trip actors offered as unrelated action partners"


def stale_pair_target():
    a, b, other = character(), character(), character()
    C.set_character_pos(other, 4, 0)
    variables = {"talk_allowed": True, "present": [{"name": b}], "pair_keys": ["embracing"]}
    trip(a, b)
    result = npc_actions._apply_talk(other, {"pair": {"with": b, "pose": "embracing"}}, variables, moved=False)
    assert not result
    from app.core.interaction_engine import pending_invites_for, get_interaction
    assert not any(inv.get("inviter") == other for inv in pending_invites_for(b))
    assert get_interaction(b) is None and not travel_engine.get_journey(b)
    assert P.find_pending_invite(a, b)


def home_npc_proposal():
    a, b = character(), character()
    with keyed_lock("character_profile", a):
        profile = C.get_character_profile(a)
        profile["npc_home"] = circle_home(HOME, 0, 0, 5)
        assert C.save_character_profile(a, profile)
    answer = {"move": "stay", "activity": "Proposes a quiet shared trip", "action": {
        "type": "travel_together", "target": b, "scope": "pair",
        "destination": {"location_id": HOME, "room_id": "cellar"},
        "line": "Come down to the cellar with me."}}
    result = npc_actions.run_action_for(a, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps(answer)))
    assert result and result.get("intent_id"), result
    assert P.find_pending_invite(a, b)
    assert all(C.get_character_current_room(n) == "taproom" for n in (a, b))
    assert not travel_engine.get_journey(a)


def concurrent_accepts():
    a, b = character(), character()
    intent = trip(a, b, FAR, "hall")
    iid = invite_id(intent)
    original = P.get_invite
    barrier = threading.Barrier(2)
    local = threading.local()

    def synchronized_read(key):
        row = original(key)
        if key == iid and not getattr(local, "read", False):
            local.read = True
            barrier.wait(timeout=5)
        return row

    P.get_invite = synchronized_read
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: T.respond(iid, True), range(2)))
    finally:
        P.get_invite = original
    assert all(r["status"] == "accepted" for r in results), results
    assert I.get_intent(intent["id"])["meta"]["travel"]["phase"] == "travelling"
    assert travel_engine.get_journey(a)


def spoken_before_consent():
    from app.core import perception
    a, b = character(), character()
    entered, release, consent = threading.Event(), threading.Event(), threading.Event()
    original_record, original_request = perception.record_utterance, T.request_consent

    def delayed_record(**kwargs):
        if kwargs["speaker"] == a:
            entered.set()
            assert release.wait(timeout=5)
        return original_record(**kwargs)

    def answer(iid):
        consent.set()
        return T.respond(iid, True)["status"] == "accepted"

    perception.record_utterance, T.request_consent = delayed_record, answer
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            proposal = pool.submit(T.propose_trip, a, b,
                                   {"location_id": HOME, "room_id": "cellar"},
                                   announcement="Come downstairs with me.")
            assert entered.wait(timeout=5)
            active = next(row for row in I.list_intents(status="active") if row["owner"] == a)
            tick = pool.submit(T.reconcile, active["id"])
            try:
                assert not consent.wait(timeout=0.2), "Consent preceded the spoken invitation"
                assert C.get_character_current_room(a) == "taproom"
            finally:
                release.set()
            intent = proposal.result(timeout=5)
            tick.result(timeout=5)
    finally:
        release.set()
        perception.record_utterance, T.request_consent = original_record, original_request
    assert I.get_intent(intent["id"])["status"] == "done"
    assert all(C.get_character_current_room(n) == "cellar" for n in (a, b))


def ordinary_duplicate_after_departure():
    a, b = character(), character()
    iid = P.create_pending_invite(a, b)
    assert P.resolve_pending_invite(iid, True)["status"] == "accepted"
    P.leave_party(b)
    assert P.resolve_pending_invite(iid, True)["status"] == "not_found"
    assert P.get_party_of(b) is None


def arrived_follower_stays_with_leader():
    a, b = character(), character()
    intent = trip(a, b)
    assert P.resolve_pending_invite(invite_id(intent), True)["status"] == "accepted"
    answer = {"room": "taproom", "activity": "waits beside the leader", "pose": "standing"}
    npc_actions.run_action_for(b, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps(answer)))
    assert C.get_character_current_room(a) == "cellar"
    assert C.get_character_current_room(b) == "cellar", "NPC follower moved independently"
    assert P.is_party_follower(b)
    with keyed_lock("character_profile", b):
        profile = C.get_character_profile(b)
        profile["npc_home"] = circle_home(HOME, 0, 0, 5)
        assert C.save_character_profile(b, profile)
    position = C.get_character_pos(b)
    npc_actions.run_action_for(b, llm=lambda *args, **kwargs: SimpleNamespace(content=json.dumps({
        "activity": "waits with the leader", "pose": "standing"})))
    assert not travel_engine.get_journey(b)
    assert C.get_character_pos(b) == position


def chat_consent_without_saved_skill_config():
    a, b = character(), character()
    intent = trip(a, b)
    manager = get_skill_manager()
    tool = next(t for t in manager.get_agent_tools(b, check_limits=False) if t.name == "JoinParty")
    result = tool.func(json.dumps({"agent_name": b, "leader": a, "invite_id": invite_id(intent)}))
    assert I.get_intent(intent["id"])["status"] == "done", result
    assert all(C.get_character_current_room(n) == "cellar" for n in (a, b))
    C.save_character_skill_config(b, "leave_party", {"enabled": False})
    assert not any(t.name == "LeaveParty" for t in manager.get_agent_tools(b, check_limits=False))


def referenced_counterproposal():
    a, b = character(), character()
    old = trip(a, b)
    assert I.cancel_intent(old["id"])
    current = trip(a, b)
    invitation = PartySkill({}, PluginContext("party"), "invite")
    args = {"agent_name": b, "target": a, "destination": current["action"]["destination"]}
    invitation.execute(json.dumps({**args, "intent_id": old["id"]}))
    invitation.execute(json.dumps(args))
    assert P.get_invite(invite_id(current))["status"] == "pending"
    assert all(C.get_character_current_room(n) == "taproom" for n in (a, b))
    invitation.execute(json.dumps({**args, "intent_id": current["id"]}))
    assert I.get_intent(current["id"])["status"] == "done"
    assert P.get_party_of(b)["leader"] == a
    assert all(C.get_character_current_room(n) == "cellar" for n in (a, b))


def main():
    failures = []
    cases = [late_answer, closed_trip_join, expired_paused_journey, interleaved_proposals,
             lambda: invalid_scope(True), lambda: invalid_scope(False), ordinary_avatar_move,
             unplaced_actor_move, stale_director, reserved_partner_list, stale_pair_target,
             home_npc_proposal, concurrent_accepts, spoken_before_consent,
             ordinary_duplicate_after_departure, arrived_follower_stays_with_leader,
             chat_consent_without_saved_skill_config, referenced_counterproposal]
    for index, case in enumerate(cases, 1):
        try:
            case()
            print(f"PASS {index}: {case.__name__}")
        except Exception as error:
            failures.append((index, case.__name__, error))
            print(f"FAIL {index}: {case.__name__}: {type(error).__name__}: {error}")
    if failures:
        raise AssertionError(f"{len(failures)} consumer-visible review regressions failed")
    print("PASS: exact consent, expiry, concurrent creation, ordinary movement and reserved NPC isolation")


if __name__ == "__main__":
    try:
        main()
    finally:
        TEMP.cleanup()
