"""Fog-filtered sync topics for the player push channel (P4 B).

The channel carries TOPICS, never data ("invalidate, don't replicate"): a
client refetches the matching, already fog-filtered route. Timing and kind of
a signal are information too, so a topic only goes to connections whose avatar
perceives the change (spec plan-3d-naehe-push-p4.md § B3). ``Everyone`` is for
world structure and the public Instagram feed only.

Thread-safe: writers run on worker threads (skills, scheduler, agent loop,
travel ticker). Matching a recipient and queueing happen under the
connection's lock, so a rebind can never let a signal for the old avatar into
the new queue. No I/O under bus/connection locks; ``notify`` never raises.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple, Union

from app.core.log import get_logger

logger = get_logger("sync_topics")

TOPICS: Tuple[str, ...] = ("presence", "scene", "notices", "self", "world")
BATCH_S = 0.25  # At most four bundled topic frames per second.
HEARTBEAT_S = 15.0  # Keep idle proxy connections alive.
CHECK_S = 60.0  # Bound session and avatar staleness to a minute.
QUEUE_MAX = 64  # Replace larger backlogs with one resync.
SLOW_S = 30.0  # Drop consumers stalled for more than thirty seconds.
REAP_S = 5.0  # Watch lag even when no writer is active.
_clock = time.monotonic
_before_offer: Optional[Callable[[], None]] = None   # smoke hook (race test)


@dataclass(frozen=True)
class Everyone:
    pass


@dataclass(frozen=True)
class Avatar:
    name: str


@dataclass(frozen=True)
class AtLocation:
    loc_id: str


@dataclass(frozen=True)
class Avatars:
    names: Tuple[str, ...]


Recipient = Union[Everyone, Avatar, AtLocation, Avatars]
_RECIPIENT_TYPES = (Everyone, Avatar, AtLocation, Avatars)


@dataclass(eq=False)
class Connection:
    user_id: str
    token: str
    avatar: str
    location: str
    wake: Optional[Callable[[], None]] = None
    abort: Optional[Callable[[], None]] = None
    closed: bool = False
    bind_rev: int = 0                 # bumps on ANY binding change (avatar or location)
    _pending: List[str] = field(default_factory=list)
    _overflow: bool = False
    _resync: bool = True              # every connection starts with one resync
    _pending_since: Optional[float] = field(default_factory=lambda: _clock())   # oldest queued, not yet taken
    _inflight_since: Optional[float] = None  # taken frame whose send has not returned
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _matches(self, r) -> bool:          # caller holds self._lock
        if isinstance(r, Everyone):
            return True
        if isinstance(r, Avatar):
            return bool(self.avatar) and r.name == self.avatar
        if isinstance(r, AtLocation):
            return bool(r.loc_id) and r.loc_id == self.location
        if isinstance(r, Avatars):
            return bool(self.avatar) and self.avatar in r.names
        return False

    def _offer(self, topics, recips) -> bool:
        """Match and queue atomically; entry 65 overflows because 64 + 1 > 64."""
        with self._lock:
            if self.closed or not any(self._matches(r) for r in recips):
                return False
            if not (self._overflow or self._resync):
                if len(self._pending) + len(topics) > QUEUE_MAX:
                    self._overflow = True
                    self._pending.clear()
                else:
                    self._pending.extend(topics)
            if self._pending_since is None:
                self._pending_since = _clock()
            return True

    def binding(self) -> Tuple[str, str, int]:
        with self._lock:
            return self.avatar, self.location, self.bind_rev

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending) or self._overflow or self._resync

    def take(self) -> Tuple[List[str], bool]:
        with self._lock:
            full = self._overflow or self._resync
            topics = list(TOPICS) if full else sorted(set(self._pending))
            self._pending.clear()
            self._overflow = self._resync = False
            if topics:
                # the frame's age keeps running until delivered(): a blocked send is lag too
                self._inflight_since = self._pending_since if self._pending_since is not None else _clock()
            self._pending_since = None
        return topics, full

    def send_started(self) -> None:
        with self._lock:
            if self._inflight_since is None:
                self._inflight_since = _clock()

    def delivered(self) -> None:
        with self._lock:
            self._inflight_since = None        # only the delivered send; queued signals keep their age

    def _lagging(self, now: float) -> bool:
        with self._lock:
            stamps = [t for t in (self._pending_since, self._inflight_since) if t is not None]
            return not self.closed and bool(stamps) and now - min(stamps) > SLOW_S


_conns: List[Connection] = []
_lock = threading.Lock()
_move_locks: dict[str, threading.Lock] = {}
_reaper: Optional[threading.Thread] = None


def _call(fn, what: str) -> None:
    if fn is None:
        return
    try:
        fn()
    except Exception as e:  # a closed loop must not break a writer
        logger.debug("%s failed: %s", what, e)


def notify(topics, *, to) -> None:
    """Send topic(s) to the connections the recipient(s) match. Never raises."""
    try:
        tops = (topics,) if isinstance(topics, str) else tuple(topics)
        tops = tuple(t for t in tops if t in TOPICS)
        recips = (to,) if isinstance(to, _RECIPIENT_TYPES) else tuple(to)
        if not tops or not recips:
            return
        with _lock:
            conns = list(_conns)
        if _before_offer is not None:
            _before_offer()
        for c in conns:
            if c._offer(tops, recips):
                _call(c.wake, "wake")
    except Exception as e:
        logger.warning("notify(%s) failed: %s", topics, e)


def _reap_loop() -> None:
    while True:
        time.sleep(REAP_S)
        reap()


def register(user_id, token, avatar, location, wake=None, abort=None) -> Connection:
    global _reaper
    conn = Connection(user_id=user_id, token=token, avatar=avatar or "",
                      location=location or "", wake=wake, abort=abort)
    with _lock:
        _conns.append(conn)
        if _reaper is None:
            _reaper = threading.Thread(target=_reap_loop, name="sync-reaper",
                                       daemon=True)
            _reaper.start()
    return conn


def unregister(conn: Connection) -> None:
    with conn._lock:
        conn.closed = True
    with _lock:
        if conn in _conns:
            _conns.remove(conn)


def reap() -> int:
    """Close every connection whose undelivered signal is older than SLOW_S."""
    now = _clock()
    with _lock:
        conns = list(_conns)
    gone = [c for c in conns if c._lagging(now)]
    for c in gone:
        unregister(c)
        _call(c.abort, "abort")
    return len(gone)


def rebind(conn: Connection, avatar: str, location: str,
           expect_rev: Optional[int] = None) -> bool:
    """Compare-and-set of the whole binding.

    ``expect_rev``: a re-check that read the DB under an older binding passes
    the revision it started from; a binding changed meanwhile (another rebind
    or an own move) wins and nothing is written. Same avatar: only the location
    moves, no resync. New avatar: the old queue is dropped BEFORE the resync is
    queued."""
    avatar, location = avatar or "", location or ""
    with conn._lock:
        if expect_rev is not None and conn.bind_rev != expect_rev:
            return False
        if avatar == conn.avatar:
            if location != conn.location:
                conn.location = location
                conn.bind_rev += 1
            return True
        conn._pending.clear()
        conn._overflow = False
        conn.avatar = avatar
        conn.location = location
        conn.bind_rev += 1
        conn._resync = True
        if conn._pending_since is None:
            conn._pending_since = _clock()
    _call(conn.wake, "wake")
    return True


RECONCILE_TRIES = 5  # Bound DB retries under continuous binding changes.


def reconcile(conn: Connection) -> bool:
    """Bring the binding in line with the DB: read the revision, read the DB,
    compare-and-set; a binding that moved meanwhile means READ AGAIN (fresh
    revision, fresh DB), never overwrite. Runs in a thread (DB reads)."""
    from app.models.account import get_active_character_for_user
    from app.models.character import get_character_current_location
    for _ in range(RECONCILE_TRIES):
        rev = conn.binding()[2]
        avatar = get_active_character_for_user(conn.user_id)
        location = (get_character_current_location(avatar) if avatar else "") or ""
        if rebind(conn, avatar, location, expect_rev=rev):
            return True
    logger.warning("reconcile(%s): binding kept moving, next check retries", conn.user_id)
    return False


def rebind_user(user_id: str) -> None:
    """Reconcile every connection of that user (avatar switch)."""
    try:
        with _lock:
            mine = [c for c in _conns if c.user_id == user_id]
        for c in mine:
            reconcile(c)
    except Exception as e:
        logger.warning("rebind_user(%s) failed: %s", user_id, e)


def note_location(avatar: str, location: str) -> None:
    if not avatar:
        return
    with _lock:
        conns = list(_conns)
    for c in conns:
        with c._lock:
            if c.avatar == avatar and c.location != (location or ""):
                c.location = location or ""
                c.bind_rev += 1


def bound_avatars() -> set:
    with _lock:
        conns = list(_conns)
    return {c.binding()[0] for c in conns} - {""}


def connections() -> List[Connection]:
    with _lock:
        return list(_conns)


# Fields exposed for other characters by scene, others, or the world map.
# current_activity is derived on those routes, rather than shown directly.
PUBLIC_PROFILE_KEYS = frozenset({
    "current_location", "current_room", "pose_key", "pose_flavor",
    "current_feeling", "place", "equipped_pieces", "equipped_items",
    "profile_image", "interaction", "journey", "is_sleeping",
    "movement_target", "status_effects", "active_conditions", "height",
    "animation_set", "gender", "template", "motion_gravity_scale",
    "body_slots", "model3d_opts",
})


def _current_location(character: str) -> str:
    from app.models.character import get_character_current_location
    return get_character_current_location(character) or ""


def _refresh_binding(character: str) -> bool:
    """Read committed location serially; never trust a delayed writer's target.

    _lock only protects move-lock creation and is released before acquiring it.
    Hold only the character move lock during the DB read. The sole nested
    order is move lock -> bus/connection locks inside note_location; no caller
    may acquire a move lock while holding a bus or connection lock.
    """
    try:
        with _lock:
            move_lock = _move_locks.setdefault(character, threading.Lock())
        with move_lock:
            fresh = _current_location(character)
            note_location(character, fresh)
        return True
    except Exception as e:
        logger.warning("refresh_binding(%s) failed: %s", character, e)
        return False


def moved(character: str, from_id: str, to_id: str) -> None:
    """Update the binding, then invalidate both visible ends of a move."""
    try:
        if not _refresh_binding(character):
            return
        notify("presence", to=[AtLocation(from_id or ""), AtLocation(to_id or ""),
                               Avatar(character)])
    except Exception as e:
        logger.warning("moved(%s) failed: %s", character, e)


def changed_at(character: str, loc_id: Optional[str] = None,
               topics=("presence",)) -> None:
    """Invalidate a visible change at the supplied or current location."""
    try:
        loc = _current_location(character) if loc_id is None else (loc_id or "")
        notify(topics, to=[AtLocation(loc), Avatar(character)])
    except Exception as e:
        logger.warning("changed_at(%s) failed: %s", character, e)


def party_of(character: str) -> Avatars:
    """Snapshot the leader and followers without leaking lookup failures."""
    try:
        from app.core.party_engine import get_party_of
        party = get_party_of(character) or {}
        names = [party.get("leader", ""), *(party.get("members") or [])]
        return Avatars(tuple(n for n in dict.fromkeys(names) if n))
    except Exception:
        return Avatars(())


def travel_changed(character: str) -> None:
    """Journey start/cancel/blocked: notify the current side, never the goal."""
    try:
        notify("presence", to=[AtLocation(_current_location(character)),
                               Avatar(character), party_of(character)])
    except Exception as e:
        logger.warning("travel_changed(%s) failed: %s", character, e)


def avatars(names: Iterable[str], topics) -> None:
    """Invalidate unique named avatars; malformed input must not break saves."""
    try:
        notify(topics, to=Avatars(tuple(n for n in dict.fromkeys(names) if n)))
    except Exception as e:
        logger.warning("avatars failed: %s", e)


def profile_patched(character: str, before: dict, after: dict) -> None:
    """Route a bulk profile patch according to the fields actually changed."""
    try:
        changed = {k for k in before.keys() | after.keys()
                   if before.get(k) != after.get(k)}
        if "current_location" in changed:
            moved(character, before.get("current_location") or "",
                  after.get("current_location") or "")
        elif changed & PUBLIC_PROFILE_KEYS:
            changed_at(character, topics=("presence", "self"))
        else:
            avatars([character], "self")
    except Exception as e:
        logger.warning("profile_patched(%s) failed: %s", character, e)
