"""Provider-backed room reading and bounded memories, with no narration.

Provider calls and add_memory always run after every local lock/transaction
has been released. Callers must likewise hold no locks when entering here.
"""
import json

from app.core import config, hooks
from app.core.game_time import GameDuration, GameTime
from app.core.db import get_connection, transaction
from app.core.i18n import localized, t
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import game_time
from app.models import character, inventory, secrets
from app.models.memory import add_memory

logger = get_logger("item_reading")
MEMORIES_PER_DAY = 2
NPC_PAGES = 2
NPC_PAGE_CHARS = 600


def _session_row(reader):
    row = get_connection().execute(
        "SELECT * FROM item_reading_sessions WHERE reader=?", (reader,)).fetchone()
    if row is None:
        return None
    session = dict(row)
    session["noticed_by"] = json.loads(session["noticed_by"])
    return session


def _session_here(session):
    return (GameTime.parse(session["until_game_ts"]) >= game_time()
            and character.get_character_current_location(session["reader"]) == session["location_id"]
            and (character.get_character_current_room(session["reader"]) or "") == session["room_id"])


def _until(now):
    return str(now + GameDuration.of(minutes=int(config.get("inventory.reading_minutes", 10))))


def start_session(reader: str, item_id: str, location_id: str, room_id: str) -> dict:
    """Replace this reader's session; callers invoke the watcher after return."""
    now = game_time()
    with keyed_lock("reading_session", reader), transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO item_reading_sessions "
                     "(reader,item_id,location_id,room_id,started_game_ts,until_game_ts) "
                     "VALUES (?,?,?,?,?,?)", (reader, item_id, location_id, room_id, str(now), _until(now)))
        return _session_row(reader)


def active_session(reader: str) -> dict | None:
    """Return a live session, deleting caught, expired or departed rows."""
    with keyed_lock("reading_session", reader):
        session = _session_row(reader)
        if session and (session["caught"] or not _session_here(session)):
            end_session(reader, "inactive")
            return None
        return session


def extend_session(reader: str, item_id: str) -> dict | None:
    """Extend a matching live session to now plus the configured duration."""
    with keyed_lock("reading_session", reader):
        session = active_session(reader)
        if not session or session["item_id"] != item_id:
            return None
        session["until_game_ts"] = _until(game_time())
        with transaction() as conn:
            conn.execute("UPDATE item_reading_sessions SET until_game_ts=? WHERE reader=?",
                         (session["until_game_ts"], reader))
        return session


def sessions_in_room(location_id: str, room_id: str) -> list[dict]:
    """List live sessions, pruning dead rows through active_session."""
    readers = get_connection().execute(
        "SELECT reader FROM item_reading_sessions WHERE location_id=? AND room_id=? AND caught=0",
        (location_id, room_id)).fetchall()
    sessions = []
    for row in readers:
        with keyed_lock("reading_session", row[0]):
            stored = _session_row(row[0])
            session = active_session(row[0]) if stored and not stored["caught"] else None
        if session and session["location_id"] == location_id and session["room_id"] == room_id:
            sessions.append(session)
    return sessions


def end_session(reader: str, reason: str) -> None:
    """Delete a session; reason describes the caller's lifecycle event."""
    with keyed_lock("reading_session", reader), transaction() as conn:
        conn.execute("DELETE FROM item_reading_sessions WHERE reader=?", (reader,))


def heartbeat(reader: str, item_id: str) -> dict:
    """Report a pending owner catch or extend a live matching session."""
    with keyed_lock("reading_session", reader):
        session = _session_row(reader)
        if session and session["item_id"] == item_id and session["caught"] and _session_here(session):
            item = inventory.get_item(item_id) or {}
            return {"caught_by": item.get("owner", "")}
        extend_session(reader, item_id)
    return {"caught_by": ""}


def _start_reading(reader, item_id):
    from app.core import reading_watch
    session = start_session(reader, item_id,
                            character.get_character_current_location(reader) or "",
                            character.get_character_current_room(reader) or "")
    return reading_watch.on_session_started(session)


def has_pages(item: dict) -> bool:
    """Whether a page provider is registered for the item, without calling it
    (cheap enough for a polled listing)."""
    source = item.get("pages_source")
    return bool(source) and hooks.get_provider(f"item_pages.{source}") is not None


def pages_of(item: dict, reader: str) -> list[dict] | None:
    """Return chronological pages, or None for an unavailable/broken source."""
    source = item.get("pages_source")
    provider = hooks.get_provider(f"item_pages.{source}") if source else None
    if provider is None:
        return None
    try:
        pages = provider(item, reader)
        if not isinstance(pages, list) or any(not isinstance(p, dict) for p in pages):
            raise ValueError("item pages must be a list of dictionaries")
        return pages
    except Exception:
        logger.exception("Item pages provider failed: %s (item %s)", source, item.get("id"))
        return None


def _here(reader, item_id):
    item = inventory.get_item(item_id)
    loc = character.get_character_current_location(reader) or ""
    room = character.get_character_current_room(reader) or ""
    if not item or not loc:
        return None
    placement = next((p for p in inventory.get_room_items(loc, room)
                      if p.get("item_id") == item_id), None)
    if placement is None or not inventory.placement_visible_to(reader, loc, room, placement):
        return None
    pages = pages_of(item, reader)
    return (item, pages) if pages is not None else None


def readable_here(reader: str, item_id: str) -> bool:
    """Whether a visible placement in this reader's room supplies pages."""
    return _here(reader, item_id) is not None


def _learn(reader, item, pages, day):
    owner = item.get("owner", "")
    if not owner or reader == owner:
        return
    lang = character.get_character_language(reader)
    item_name = localized(item, "name", lang) or item["id"]
    for page in pages:
        sid = page.get("secret_id")
        if not sid:
            continue
        # Serialize the check and first learning across all items of this owner.
        # Reserve the daily slot atomically, then release ALL locks before memory.
        remember = False
        with keyed_lock("secrets", owner):
            secret = secrets.get_secret(owner, sid)
            if not secret or reader in secret.get("known_by", []):
                continue
            if not secrets.add_known_by(owner, sid, reader, discovered=True):
                continue
            with transaction() as conn:
                conn.execute("INSERT OR IGNORE INTO item_reads(reader,item_id,game_day) VALUES (?,?,?)",
                             (reader, item["id"], day))
                remember = conn.execute(
                    "UPDATE item_reads SET memories=memories+1 "
                    "WHERE reader=? AND item_id=? AND game_day=? AND memories<?",
                    (reader, item["id"], day, MEMORIES_PER_DAY)).rowcount == 1
        if remember:
            add_memory(reader, t("Read in {item}: {secret}", lang).format(
                item=item_name, secret=secret.get("content", "")),
                memory_type="episodic", importance=3, tags=["item", "read"],
                related_character=owner, extra_meta={"item_id": item["id"],
                    "owner": owner, "secret_id": sid, "ref": page.get("ref", "")})


def _public_page(page, *, npc=False):
    text = page.get("text", "")
    return {"heading": page.get("heading", ""),
            "text": text[:NPC_PAGE_CHARS] if npc else text}


def read_page(reader: str, item_id: str, index: int, *, opening: bool = False) -> dict:
    """Read and learn one page, starting or extending the reading session."""
    found = _here(reader, item_id)
    if found is None:
        return {"error": "There is nothing like that to read here."}
    item, pages = found
    from app.core.reading_watch import watching_owner
    owner = watching_owner(reader, item)
    if opening and owner:
        return {"error": t("{owner} is watching.", character.get_character_language(reader)).format(owner=owner)}
    result = _start_reading(reader, item_id) if opening else heartbeat(reader, item_id)
    if not opening and not result.get("caught_by") and active_session(reader) is None:
        # The session ran out while the book stayed open (no heartbeat, e.g. a
        # sleeping tab): turning a page reads again, so it starts a new one.
        result = _start_reading(reader, item_id)
    if result.get("caught_by") or result.get("error"):
        return result
    index = max(0, min(index, len(pages)-1))
    page = pages[index] if pages else None
    _learn(reader, item, [page] if page else [], game_time().day_key())
    return {"item_name": localized(item, "name", character.get_character_language(reader)) or item_id,
            "index": index, "total": len(pages),
            "page": _public_page(page) if page is not None else None}


def npc_read_today(reader: str, item_id: str) -> bool:
    """Whether this reader already used the NPC path on this game day."""
    row = get_connection().execute(
        "SELECT npc_read FROM item_reads WHERE reader=? AND item_id=? AND game_day=?",
        (reader, item_id, game_time().day_key())).fetchone()
    return bool(row and row[0])


def npc_read(reader: str, item_id: str) -> dict:
    """Read up to two newest unknown secrets, once daily; otherwise newest page."""
    found = _here(reader, item_id)
    if found is None:
        return {"error": "There is nothing like that to read here."}
    item, pages = found
    from app.core.reading_watch import watching_owner
    owner = watching_owner(reader, item)
    if owner:
        return {"error": t("{owner} is watching.", character.get_character_language(reader)).format(owner=owner)}
    day = game_time().day_key()
    with transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO item_reads(reader,item_id,game_day) VALUES (?,?,?)",
                     (reader, item_id, day))
        claimed = conn.execute("UPDATE item_reads SET npc_read=1 "
            "WHERE reader=? AND item_id=? AND game_day=? AND npc_read=0",
            (reader, item_id, day)).rowcount
    if not claimed:
        return {"error": "You already read that today."}
    result = _start_reading(reader, item_id)
    if result.get("caught_by") or result.get("error"):
        return result
    unknown = []
    owner = item.get("owner", "")
    seen = set()
    if owner and owner != reader:
        for page in reversed(pages):
            sid = page.get("secret_id")
            secret = secrets.get_secret(owner, sid) if sid else None
            if secret and sid not in seen and reader not in secret.get("known_by", []):
                unknown.append(page)
                seen.add(sid)
                if len(unknown) == NPC_PAGES:
                    break
    selected = unknown or pages[-1:]
    _learn(reader, item, selected, day)
    return {"item_name": localized(item, "name", character.get_character_language(reader)) or item_id,
            "pages": [_public_page(p, npc=True) for p in selected]}
