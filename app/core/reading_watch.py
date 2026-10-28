"""Notice live reading sessions and dispatch consequences after releasing locks."""
import json

from app.core import hooks, config
from app.core.db import get_connection, transaction
from app.core.i18n import localized, t
from app.core.keyed_lock import keyed_lock
from app.core.timeutils import game_time
from app.models import character, inventory, secrets

_pending = {}
_witness_queue = {}
_witness_running = set()


def _present(session):
    from app.core.room_entry import characters_in_room
    if not session["room_id"]:
        return []  # an empty room id would mean the whole location
    return characters_in_room(session["location_id"], session["room_id"])


def _text(source, recipient, item, **values):
    lang = character.get_character_language(recipient)
    return t(source, lang).format(item=localized(item, "name", lang) or item["id"], **values)


def watching_owner(reader: str, item: dict) -> str:
    """Return the owner blocking a same-day repeat, or an empty string."""
    owner = item.get("owner", "")
    row = get_connection().execute(
        "SELECT 1 FROM item_caught_today WHERE reader=? AND item_id=? AND game_day=?",
        (reader, item["id"], game_time().day_key())).fetchone()
    if row and owner and character.get_character_current_location(owner) == character.get_character_current_location(reader) and character.get_character_current_room(owner) == character.get_character_current_room(reader):
        return owner
    return ""


def _reply(reader, owner, hint, **kwargs):
    from app.core.agent_loop import get_agent_loop
    get_agent_loop().bump_respond(reader, speaker=owner, content=hint,
        on_demand=True, obligatory=True, hint=hint, **kwargs)


def _owner_catch(session, owner, item, first):
    from app.core.perception import record_utterance, STORYTELLER_SPEAKER
    from app.models.memory import add_memory
    from app.models.relationship import record_interaction
    from app.models.account import is_player_controlled
    from app.models.notifications import create_notification
    reader = session["reader"]
    record_utterance(speaker=STORYTELLER_SPEAKER,
        content=_text("{watcher} catches {reader} reading {item}.", reader, item, watcher=owner, reader=reader),
        location_id=session["location_id"], room_id=session["room_id"], anchor=reader)
    if not first:
        return
    for name, source in [(owner, "I caught {reader} reading {item}."),
                         (reader, "{owner} caught me reading {item}.")]:
        add_memory(name, _text(source, name, item, reader=reader, owner=owner),
            memory_type="episodic", importance=4, tags=["item", "caught"])
    record_interaction(owner, reader, "caught_reading", sentiment_delta_a=-0.3,
                       sentiment_delta_b=0.0, strength_delta=0.0)
    item_name = localized(item, "name", character.get_character_language(reader)) or item["id"]
    if is_player_controlled(owner):
        create_notification(owner, _text("You catch {reader} reading {item}.", owner, item, reader=reader))
        if not is_player_controlled(reader):
            _reply(reader, owner, f"{owner} caught you reading {item_name}. Decide yourself how you react.")
    else:
        request_id = f"caught:{reader}:{item['id']}:{game_time().day_key()}"
        hint = f"You just caught {reader} secretly reading {item_name}, which belongs to you. You are upset: tell them to put it down and leave."
        with keyed_lock("reading_reply", request_id):
            _pending[request_id] = (owner, reader, item_name)
        _reply(owner, reader, hint, request_id=request_id)


def _witness(session, watcher, item):
    reader = session["reader"]
    with keyed_lock("reading_witness_queue", reader):
        _witness_queue.setdefault(reader, []).append((session, watcher, item))
        if reader in _witness_running:
            return
        _witness_running.add(reader)
    try:
        while True:
            with keyed_lock("reading_witness_queue", reader):
                queue = _witness_queue[reader]
                if not queue:
                    _witness_running.remove(reader)
                    del _witness_queue[reader]
                    return
                args = queue.pop(0)
            _apply_witness(*args)
    except BaseException:
        with keyed_lock("reading_witness_queue", reader):
            _witness_running.discard(reader)
        raise


def _apply_witness(session, watcher, item):
    from app.models.memory import add_memory
    from app.models.account import is_player_controlled
    from app.models.notifications import create_notification
    reader = session["reader"]
    add_memory(watcher, _text("I saw {reader} secretly reading {item}.", watcher, item, reader=reader),
               memory_type="episodic", importance=4, tags=["item", "caught"])
    ref = f"caught_reading:{item['id']}"
    # All witness paths for a reader are serialized by the dispatch queue above;
    # add_secret itself owns its secrets lock, never called under our lock.
    secret = next((s for s in secrets.list_secrets(reader) if s.get("source_ref") == ref), None)
    if secret is None:
        secret = secrets.add_secret(reader,
            _text("{reader} secretly read {item}.", reader, item, reader=reader),
            category="relationship", severity=3, related_characters=[item.get("owner", "")],
            source="discovered", source_ref=ref)
    secrets.add_known_by(reader, secret["id"], watcher, discovered=True)
    if is_player_controlled(watcher):
        create_notification(watcher, _text("You notice {reader} secretly reading {item}.", watcher, item, reader=reader))


def _caught_result(session, item):
    from app.core import item_reading
    with keyed_lock("reading_session", session["reader"]):
        stored = item_reading._session_row(session["reader"])
        if (stored and stored["caught"] and item_reading._session_here(stored)
                and all(stored[k] == session[k] for k in
                        ("item_id", "session_id", "location_id", "room_id"))):
            return {"caught_by": item.get("owner", "")}
    return {}


def check_session(session: dict, watchers: list[str]) -> dict:
    """Atomically claim eligible notices, then apply effects outside locks."""
    from app.core import item_reading
    from app.core.attention import is_distracted
    item = inventory.get_item(session["item_id"])
    if not item:
        return {}
    caught = _caught_result(session, item)
    if caught:
        return caught
    for watcher in watchers:
        if watcher == session["reader"] or watcher not in _present(session):
            continue
        if is_distracted(watcher) or inventory.discovery_value(watcher) < int(config.get("inventory.notice_reading_difficulty", 60)):
            continue
        owner = watcher == item.get("owner")
        with keyed_lock("reading_session", session["reader"]):
            stored = item_reading._session_row(session["reader"])
            if stored and stored["caught"] and stored["session_id"] == session["session_id"]:
                return {"caught_by": item.get("owner", "")}
            live = item_reading.active_session(session["reader"])
            if not live or any(live[k] != session[k] for k in ("item_id", "session_id", "location_id", "room_id")):
                return {}
            if watcher in live["noticed_by"]:
                continue
            live["noticed_by"].append(watcher)
            with transaction() as conn:
                conn.execute("UPDATE item_reading_sessions SET noticed_by=?, caught=? WHERE reader=?",
                    (json.dumps(live["noticed_by"]), int(owner), session["reader"]))
                first = False
                if owner:
                    first = conn.execute("INSERT OR IGNORE INTO item_caught_today VALUES (?,?,?)",
                        (session["reader"], item["id"], game_time().day_key())).rowcount == 1
        if owner:
            _owner_catch(session, watcher, item, first)
            return {"caught_by": watcher}
        _witness(session, watcher, item)
    return _caught_result(session, item)


def on_session_started(session: dict) -> dict:
    """Evaluate everyone present before the first page is learned."""
    return check_session(session, _present(session))


def _entered(character, location_id, room_id, **kwargs):
    from app.core.item_reading import sessions_in_room
    for session in sessions_in_room(location_id, room_id):
        check_session(session, [character])


def _tick(**kwargs):
    from app.core.item_reading import active_session
    rows = get_connection().execute("SELECT reader FROM item_reading_sessions WHERE caught=0").fetchall()
    for row in rows:
        with keyed_lock("reading_session", row[0]):
            from app.core.item_reading import _session_row
            stored = _session_row(row[0])
            session = active_session(row[0]) if stored and not stored["caught"] else None
        if session:
            on_session_started(session)


def _finished(character_name, request_id=None, outcome=None, **kwargs):
    from app.models.account import is_player_controlled
    with keyed_lock("reading_reply", request_id):
        pending = _pending.get(request_id)
        if not pending or pending[0] != character_name or outcome == "superseded":
            return
        owner, reader, item_name = _pending.pop(request_id)
    if not is_player_controlled(reader):
        _reply(reader, owner, f"{owner} caught you reading {item_name} and told you to put it down and leave. Decide yourself how you react.")


def register() -> None:
    """Register reading start/entry/tick and response completion handlers."""
    hooks.register("character.entered_room", _entered, tag="reading_watch")
    hooks.register("world_tick", _tick, tag="reading_watch")
    hooks.register("respond_finished", _finished, tag="reading_watch")
