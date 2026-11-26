"""Motion orders: the wire shape of an order and the server's estimate.

An order tells every client how a figure moves from where it stands to where
the server wants it (design docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md
section 5b, plan E3 decisions 2 and 9). The client plans the real path on its
navmesh and picks the concrete clips; the server only ESTIMATES when the
figure arrives (``eta``) and when its state flips (``flip``), on the MOTION
clock (``timeutils.motion_time()``), and gives up at ``deadline``.

This module holds the pure part (constants, the estimate, the room-chain
length for a room change and the order/actor/step dict builders) and the
publication: the global ``seq``, the in-process index name -> order that the
worldmap rows and ``GET /play/orders`` read, and the visibility of an order
for an observer. It imports no world module at module level (publication,
index and visibility import inside their functions).

Usage (from code):
    from app.core import motion_orders as mo
    eta, flip = mo.estimate(now, exit_s, length_m, speed, entry_s)
    order = mo.new_order("prop_action", issued_s=now, eta_s=eta, flip_s=flip,
                         deadline_s=mo.deadline(now, eta), actors=[...], ...)

Since plan E3 Task 9 it also issues the ``walk`` orders (room changes, a
stroll inside a room, a walk in the open): ``issue_walk``, ``settle_due``,
``cancel_for`` (the choke point every other movement write passes) and the
"on the way" predicate ``walking``.

Checked by scripts/smoke_order_estimate.py (vector shared/test-vectors/order_estimate.json),
scripts/smoke_orders_route.py (publication, index, visibility),
scripts/smoke_walk_orders.py and scripts/smoke_walk_outdoor.py (walk orders).
"""
from __future__ import annotations

import copy
import logging
import math
import threading
import uuid
from collections import deque
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Fixed grace between the order and the first step (request round trip,
# path planning on the client).
START_SLACK_S = 0.5
# How long a finished or replaced order stays published (decision 6).
ORDER_TAIL_S = 10.0
# Max distance of a reported arrival from the access point.
ARRIVE_TOL_M = 0.5
# Detour factor on the horizontal legs of a room chain (decision 9).
ROOM_DETOUR = 1.3
# Lower bound of the slack between eta and deadline.
DEADLINE_MIN_S = 10.0

KINDS = ("prop_action", "walk", "cancel")
STATUSES = ("approaching", "waiting", "entering", "active", "ended")
STEPS = ("exit", "walk", "entry", "loop", "phase", "finale")

_DECIMALS = 3


def _finite(*values: float) -> None:
    """Raise ValueError unless every value is a finite number. Any numeric type
    that converts with float() counts (numpy scalars, Decimal); bools and strings
    do not."""
    for v in values:
        if isinstance(v, (bool, str, bytes)):
            raise ValueError(f"not a finite number: {v!r}")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"not a finite number: {v!r}") from None
        if not math.isfinite(f):
            raise ValueError(f"not a finite number: {v!r}")


def estimate(issued_s: float, exit_s: float, length_m: float, speed_m_s: float,
             entry_s: float) -> tuple[float, float]:
    """(eta, flip) on the motion clock.

    eta  = issued + exit_s + length_m / speed_m_s + START_SLACK_S
    flip = eta + entry_s
    A non-positive speed or a non-finite input raises ValueError."""
    _finite(issued_s, exit_s, length_m, speed_m_s, entry_s)
    issued_s, exit_s, length_m, speed_m_s, entry_s = (
        float(issued_s), float(exit_s), float(length_m), float(speed_m_s), float(entry_s))
    if speed_m_s <= 0:
        raise ValueError(f"speed_m_s must be > 0, got {speed_m_s!r}")
    eta = issued_s + exit_s + length_m / speed_m_s + START_SLACK_S
    return eta, eta + entry_s


def deadline(issued_s: float, eta_s: float) -> float:
    """Latest motion second the server waits: eta + max(DEADLINE_MIN_S, 0.5 * (eta - issued))."""
    _finite(issued_s, eta_s)
    issued_s, eta_s = float(issued_s), float(eta_s)
    return eta_s + max(DEADLINE_MIN_S, 0.5 * (eta_s - issued_s))


def _xz(p: Iterable[float]) -> tuple[float, float]:
    pts = [float(v) for v in p]
    if len(pts) == 2:
        return pts[0], pts[1]
    return pts[0], pts[2]


def _flat(a: Iterable[float], b: Iterable[float]) -> float:
    ax, az = _xz(a)
    bx, bz = _xz(b)
    return math.hypot(bx - ax, bz - az)


def room_chain_length(rooms: dict[str, int], doorways: list[dict], stairs: list[dict],
                      start: tuple[float, float, float], start_room: str,
                      goal: tuple[float, float, float], goal_room: str) -> float:
    """Estimated walking length of a room change inside ONE location (decision 9).

    ``rooms`` maps room id -> level; ``doorways`` are ``{"at": (x, z), "rooms": [a, b]}``
    (a doorway with fewer than two rooms leads outside and is no edge);
    ``stairs`` are ``{"foot": (x, y, z), "head": (x, y, z), "from_level": int,
    "to_level": int}`` with an optional ``"rooms": [foot_room, head_room]``. A
    flight without ``rooms`` links every room of ``from_level`` with every room of
    ``to_level``; with it, only those two rooms. A ``rooms`` that is set but
    unusable (not two distinct known room ids) raises ValueError instead of
    silently falling back to the level rule, which can underestimate a room
    change badly. All in world metres.

    The chain is a breadth-first search over the rooms (fewest transitions;
    among chains with the same number of transitions the one cheapest up to
    that room, so with several parallel doors it is an estimate, not always the
    shortest chain). Its length is ROOM_DETOUR times the sum
    of the horizontal legs start -> doorway(s) -> stair foot, stair head ->
    ... -> goal, plus the 3D length of each flight without the factor. Same
    room, unknown rooms or no chain: the straight line start -> goal times
    ROOM_DETOUR."""
    straight = math.dist([float(v) for v in start], [float(v) for v in goal]) * ROOM_DETOUR
    if start_room == goal_room or start_room not in rooms or goal_room not in rooms:
        return straight

    # Adjacency: room -> list of (next room, entry point, leaving point, flight length).
    adj: dict[str, list[tuple[str, tuple, tuple, float]]] = {r: [] for r in rooms}
    for door in doorways or []:
        pair = [r for r in (door.get("rooms") or []) if r in rooms]
        if len(pair) < 2 or pair[0] == pair[1]:
            continue
        at = tuple(float(v) for v in door["at"])
        adj[pair[0]].append((pair[1], at, at, 0.0))
        adj[pair[1]].append((pair[0], at, at, 0.0))
    for flight in stairs or []:
        foot = tuple(float(v) for v in flight["foot"])
        head = tuple(float(v) for v in flight["head"])
        run = math.dist(foot, head)
        named = flight.get("rooms")
        if named is not None:
            named = list(named)
            if (len(named) != 2 or named[0] == named[1]
                    or named[0] not in rooms or named[1] not in rooms):
                raise ValueError(f"stairs rooms must name two distinct known rooms, got {named!r}")
            lows, highs = [named[0]], [named[1]]
        else:
            lows = [r for r, lv in rooms.items() if lv == int(flight["from_level"])]
            highs = [r for r, lv in rooms.items() if lv == int(flight["to_level"])]
        for lo in lows:
            for hi in highs:
                if lo == hi:
                    continue
                adj[lo].append((hi, foot, head, run))
                adj[hi].append((lo, head, foot, run))

    # Layered BFS; per room keep the cheapest arrival of its first layer.
    # State: (point the figure stands at, horizontal sum so far, flight sum so far).
    best: dict[str, tuple[tuple, float, float]] = {start_room: (tuple(start), 0.0, 0.0)}
    frontier = deque([start_room])
    while frontier and goal_room not in best:
        layer: dict[str, tuple[tuple, float, float]] = {}
        for room in frontier:
            here, flat_sum, run_sum = best[room]
            for nxt, enter, leave, run in adj[room]:
                if nxt in best:
                    continue
                cand = (leave, flat_sum + _flat(here, enter), run_sum + run)
                old = layer.get(nxt)
                if old is None or cand[1] * ROOM_DETOUR + cand[2] < old[1] * ROOM_DETOUR + old[2]:
                    layer[nxt] = cand
        best.update(layer)
        frontier = deque(layer)
    if goal_room not in best:
        return straight
    here, flat_sum, run_sum = best[goal_room]
    return (flat_sum + _flat(here, goal)) * ROOM_DETOUR + run_sum


def _round(value: Any) -> Any:
    """Every float in a JSON-like value rounded to _DECIMALS places."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, _DECIMALS)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def step(step: str, pose_kind: str = "", pose_key: str = "", nominal_s: float = 0.0) -> dict:
    """One semantic phase of an actor's sequence (spec 5b)."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    _finite(nominal_s)
    return {"step": step, "pose_kind": pose_kind, "pose_key": pose_key,
            "nominal_s": round(float(nominal_s), _DECIMALS)}


def actor_row(name: str, role: str, clip_role: str, height_cm: float, start: dict, *,
              access: dict | None = None, anchor: dict | None = None, entry_mode: str = "",
              sequence: Iterable[dict] = (), reports_arrival: bool = False) -> dict:
    """One participant of an order (decision 2: access, anchor, entry_mode and
    sequence live per actor). ``start``: {x, y, z, yaw, room_id, level};
    ``access``: {x, y, z, yaw}; ``anchor``: {x, y, z, yaw, root_offset}. A
    ``cancel`` order adds ``stand`` ({x, y, z, yaw}) per actor."""
    return _round({
        "name": name, "role": role, "clip_role": clip_role, "height_cm": height_cm,
        "start": dict(start), "access": dict(access) if access is not None else None,
        "anchor": dict(anchor) if anchor is not None else None,
        "entry_mode": entry_mode, "sequence": [dict(s) for s in sequence],
        "reports_arrival": bool(reports_arrival),
    })


def new_order(kind: str, *, issued_s: float, eta_s: float, flip_s: float | None,
              deadline_s: float, actors: list[dict], target: dict, speed_m_s: float,
              gait: str, status: str, awaits: str = "", hint_route: list | None = None,
              stand: dict | None = None, snap: bool = False,
              order_id: str | None = None) -> dict:
    """The wire form of an order (decision 2), revision 1, seq 0 (``publish``
    assigns the seq). Numbers are rounded to 3 decimals. ``flip_motion_s`` is
    left out while ``awaits`` is set. ``stand`` is the stand point for every
    actor that carries none of its own (a one-actor ``cancel``); a
    multi-actor ``cancel`` sets ``actors[i]["stand"]`` itself."""
    if kind not in KINDS:
        raise ValueError(f"unknown order kind {kind!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown order status {status!r}")
    _finite(issued_s, eta_s, deadline_s, speed_m_s)
    # A moving order needs a positive speed (as estimate() does); a cancel
    # (stand-up, teleport snap) may carry 0, never a negative speed.
    if float(speed_m_s) < 0 or (kind != "cancel" and float(speed_m_s) == 0):
        raise ValueError(f"speed_m_s must be > 0 ({kind}), got {speed_m_s!r}")
    if not awaits:
        if flip_s is None:
            raise ValueError("flip_s is required unless awaits is set")
        _finite(flip_s)
    rows = []
    for actor in actors:
        row = dict(actor)
        if stand is not None and row.get("stand") is None:
            row["stand"] = dict(stand)
        rows.append(row)
    order: dict[str, Any] = {
        "order_id": order_id or f"ord-{uuid.uuid4().hex[:16]}",
        "revision": 1,
        "seq": 0,
        "kind": kind,
        "issued_motion_s": float(issued_s),
        "eta_motion_s": float(eta_s),
        "deadline_motion_s": float(deadline_s),
        "status": status,
        "awaits": awaits,
        "gait": gait,
        "speed_m_s": float(speed_m_s),
        "target": dict(target),
        "hint_route": list(hint_route or []),
        "snap": bool(snap),
        "actors": rows,
    }
    if not awaits:
        order["flip_motion_s"] = float(flip_s)
    return _round(order)


# ---------------------------------------------------------------------------
# Publication: sequence, in-process index, visibility (plan E3 decisions 3-6)
# ---------------------------------------------------------------------------

#: world_kv key of the global publication counter (decision 3).
SEQ_KEY = "motion_order_seq"

#: ONE lock for the counter AND the index: ``publish`` hands out the seq and
#: files the order under it in one step, and ``current_seq`` reads under it,
#: so a reader never sees a seq that covers an order not yet in the index
#: (decision 6). An RLock, because ``next_seq`` reads ``current_seq``.
_INDEX_LOCK = threading.RLock()
#: name -> (order, until_s): the order a figure carries right now. ``until_s``
#: is None while the order is live (its run runs), else the motion second
#: after which it is no longer published (decision 6: end + ORDER_TAIL_S).
_INDEX: dict[str, tuple[dict, float | None]] = {}

#: The top-level fields a non-participant sees (decision 4).
_PUBLIC_FIELDS = ("order_id", "revision", "seq", "kind", "issued_motion_s", "eta_motion_s",
                  "flip_motion_s", "deadline_motion_s", "status", "gait", "speed_m_s", "target",
                  "hint_route", "snap", "phase")
#: The per-actor fields a non-participant sees (decision 4).
_PUBLIC_ACTOR_FIELDS = ("name", "start", "access", "anchor", "entry_mode", "sequence", "stand")
#: Target fields that name the execution or the claimed slot: participants only.
_PRIVATE_TARGET_FIELDS = ("execution_id", "slot")


def _now_s() -> float:
    from app.core import timeutils
    return float(timeutils.motion_time())


def next_seq() -> int:
    """The next global publication number, persisted in world_kv
    (``motion_order_seq``) under the module lock (decision 3)."""
    from app.models.world import set_world_setting
    with _INDEX_LOCK:
        value = current_seq() + 1
        set_world_setting(SEQ_KEY, str(value))
    return value


def current_seq() -> int:
    """The highest publication number handed out so far (0 = none yet).
    Read under the module lock: a publication between its seq and its index
    entry is never half visible."""
    from app.models.world import get_world_setting
    with _INDEX_LOCK:
        try:
            return int(get_world_setting(SEQ_KEY, "0") or 0)
        except (TypeError, ValueError):
            return 0


def actor_names(order: dict) -> list[str]:
    """The names of an order's participants, in order."""
    return [a.get("name", "") for a in order.get("actors") or [] if a.get("name")]


def _until(order: dict) -> float | None:
    """When a published order stops being published: never on its own while
    it is a live ``prop_action`` (its run retires it, ``retire``); ``flip``
    (else ``eta``) + ORDER_TAIL_S for a ``cancel`` or an ``ended`` order."""
    if order.get("kind") == "cancel" or order.get("status") == "ended":
        end = order.get("flip_motion_s")
        if end is None:
            end = order.get("eta_motion_s", 0.0)
        return float(end) + ORDER_TAIL_S
    return None


def publish(order: dict, *, names: list[str], locations: list[str]) -> dict:
    """Publish ``order`` (a new one or a revision): give it the next ``seq``,
    make it the current order of every name in ``names`` and, after all
    locks, send the topic ``orders`` to whoever sees the change
    (``sync_topics.order_changed``: the locations, the participants). The
    push carries no data; a client fetches ``GET /play/orders``. Returns the
    published order as a deep copy with its ``seq`` — the caller (the run's
    ``data.order``) never shares nested dicts with the index."""
    published = copy.deepcopy(order)
    until = _until(published)
    with _INDEX_LOCK:
        before = _live_count()
        # seq and index entry in one step under the same lock (decision 6).
        published["seq"] = next_seq()
        for name in names:
            if name:
                _INDEX[name] = (published, until)
        first_live = before == 0 and _live_count() > 0
    if first_live:
        # 0 -> 1 live orders: stamp the liveness at once, so a restart after a
        # long idle stretch never shifts this order by that stretch. A failed
        # stamp costs only that precision, never the publication (the order
        # is already in the index; the caller must still record it).
        try:
            _write_alive(_now_s())
        except Exception:  # noqa: BLE001
            logger.exception("motion_alive_s write failed at the first live order")
    from app.core import sync_topics
    from app.core.keyed_lock import _after_locks
    who, where = list(names), list(locations)
    _after_locks(lambda: sync_topics.order_changed(who, where))
    return copy.deepcopy(published)


def retire(order_id: str, *, at_s: float | None = None) -> None:
    """The order ``order_id`` has ended without a revision (its run is over):
    it stays published ORDER_TAIL_S more seconds for every name that still
    carries it, then the row's rest placement applies (decision 6)."""
    end = (_now_s() if at_s is None else float(at_s)) + ORDER_TAIL_S
    with _INDEX_LOCK:
        for name, (order, until) in list(_INDEX.items()):
            if order.get("order_id") == order_id and until is None:
                _INDEX[name] = (order, end)


def index_get(name: str) -> dict | None:
    """The order ``name`` carries right now, or None (none, or its tail ran out)."""
    with _INDEX_LOCK:
        entry = _INDEX.get(name)
        if entry is None:
            return None
        order, until = entry
        if until is not None and _now_s() > until:
            _INDEX.pop(name, None)
            return None
        return order


def _snapshot() -> list[tuple[str, dict]]:
    """(name, order) of every order still published."""
    with _INDEX_LOCK:
        names = list(_INDEX)
    out = []
    for name in names:
        order = index_get(name)
        if order is not None:
            out.append((name, order))
    return out


def observer_place(observer: str, *, profile: dict | None = None) -> tuple[str, str]:
    """``(location_id, room_id)`` of the observer — read ONCE per request and
    handed to :func:`visible` / :func:`for_observer` as ``here``."""
    from app.core import places
    return places.where(observer, profile=profile) if observer else ("", "")


def visible(observer: str, order: dict, ctx: tuple, *,
            here: tuple[str, str] | None = None,
            seen: dict[str, bool] | None = None) -> bool:
    """Whether ``observer`` may see ``order`` (decision 4): a participant
    always; anybody else only when at least one participant stands in the
    observer's own room (outside a location: the open, ``("", "")``) AND that
    participant's worldmap row passes the row gates for the observer
    (``world_ops._visible_row``: fog, sight, veil) — out in the open a mere
    location equality would hand the order to every avatar outdoors.
    ``ctx`` comes from ``world_ops.row_visibility_ctx(observer)``, built once
    per request.

    No profile is read per call when the caller already knows: ``here`` is
    the observer's place (:func:`observer_place`, once per request), and
    ``seen`` maps a participant to "stands in ``here`` and its row passes
    the gates" — the worldmap fills it from the row it has just built (that
    row's profile, position and journey), and it doubles as a per-request
    memo: a participant not in it is looked up once and added."""
    names = actor_names(order)
    if observer and observer in names:
        return True
    if not observer:
        return False
    if here is None:
        here = observer_place(observer)
    if seen is None:
        seen = {}
    # Known participants first: they cost nothing.
    for name in sorted(names, key=lambda n: n not in seen):
        if name not in seen:
            seen[name] = _seen_by(name, here, ctx)
        if seen[name]:
            return True
    return False


def _seen_by(name: str, here: tuple[str, str], ctx: tuple) -> bool:
    """Whether ``name`` stands in the observer's place ``here`` and its
    worldmap row passes the observer's row gates (one profile load)."""
    from app.core import places
    from app.core.travel_engine import get_journey
    from app.core.world_ops import _visible_row
    from app.models.character import get_character_pos, get_character_profile
    profile = get_character_profile(name) or {}
    loc_id, room_id = places.where(name, profile=profile)
    if (loc_id, room_id) != tuple(here):
        return False
    try:
        journey = get_journey(name, profile=profile)
    except Exception:
        journey = None
    return _visible_row(name, loc_id, get_character_pos(name), journey, ctx)


def _public_view(order: dict) -> dict:
    """The movement fields of an order, for a non-participant (decision 4):
    no execution id, no slot, no ``awaits``, no roles."""
    view = {key: order[key] for key in _PUBLIC_FIELDS if key in order}
    view["target"] = {k: v for k, v in (order.get("target") or {}).items()
                      if k not in _PRIVATE_TARGET_FIELDS}
    view["actors"] = [{key: actor[key] for key in _PUBLIC_ACTOR_FIELDS if key in actor}
                      for actor in order.get("actors") or []]
    return view


def for_observer(observer: str, order: dict, ctx: tuple, *,
                 here: tuple[str, str] | None = None,
                 seen: dict[str, bool] | None = None) -> dict | None:
    """``order`` as ``observer`` may see it: whole for a participant, the
    movement fields for anybody else who sees it, None otherwise. Always a
    deep copy — nothing handed out shares a nested dict with the index.
    ``here``/``seen``: see :func:`visible`."""
    if not order or not visible(observer, order, ctx, here=here, seen=seen):
        return None
    if observer in actor_names(order):
        return copy.deepcopy(order)
    return copy.deepcopy(_public_view(order))


def orders_since(observer: str, since: int) -> dict:
    """``GET /play/orders?since=``: every order ``observer`` sees whose ``seq``
    is above ``since``, oldest publication first, with ``seq`` (the highest
    number handed out, read BEFORE the scan, so an order published meanwhile
    is never covered by it without being listed) and ``motion_now``."""
    from app.core.world_ops import row_visibility_ctx
    seq = current_seq()
    now = _now_s()
    if not observer:   # no lens (no avatar, nothing released): nothing to see
        return {"orders": [], "seq": seq, "motion_now": round(now, _DECIMALS)}
    ctx = row_visibility_ctx(observer)
    here = observer_place(observer)
    seen: dict[str, bool] = {}    # per-request memo: one profile load per participant
    newest: dict[str, dict] = {}
    for _name, order in _snapshot():
        if int(order.get("seq", 0)) <= since:
            continue
        known = newest.get(order["order_id"])
        if known is None or known["seq"] < order["seq"]:
            newest[order["order_id"]] = order
    rows = []
    for order in sorted(newest.values(), key=lambda o: o["seq"]):
        view = for_observer(observer, order, ctx, here=here, seen=seen)
        if view is not None:
            rows.append(view)
    return {"orders": rows, "seq": seq, "motion_now": round(now, _DECIMALS)}


#: world_kv key of the motion second the server last knew live orders
#: (plan E3 decision 7b): a restart shifts every order by the downtime after it.
ALIVE_KEY = "motion_alive_s"
#: At most one liveness write per this many motion seconds.
HEARTBEAT_S = 5.0
#: The motion second of this process's last liveness write (None = none yet).
_last_alive: list = [None]


def _live_count() -> int:
    """How many different orders are live (published, no tail yet)."""
    with _INDEX_LOCK:
        return len({order.get("order_id") for order, until in _INDEX.values() if until is None})


def _write_alive(now_s: float) -> None:
    from app.models.world import set_world_setting
    set_world_setting(ALIVE_KEY, f"{float(now_s):.3f}")
    _last_alive[0] = float(now_s)


def read_alive() -> float | None:
    """The stored ``motion_alive_s``, None when it is missing or unreadable."""
    from app.models.world import get_world_setting
    try:
        raw = get_world_setting(ALIVE_KEY, "")
        value = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return value if value is not None and math.isfinite(value) else None


def heartbeat() -> None:
    """Stamp ``motion_alive_s`` (world_kv) with the motion clock while live
    orders exist, at most once every HEARTBEAT_S seconds (decision 7b). The
    travel ticker calls it on every beat; without a live order it writes
    nothing."""
    if _live_count() == 0:
        return
    now = _now_s()
    last = _last_alive[0]
    if last is not None and 0 <= now - last < HEARTBEAT_S:
        return
    _write_alive(now)


def boot() -> None:
    """Server start (decision 7c, in the lifespan before the AgentLoop,
    ``periodic_jobs`` and the TravelTicker):

    (a) an approaching prop-action run without an order (older than plan E3)
        is cancelled (``e3_migration``), its slot freed;
    (b) a profile still walking a furniture approach journey (one owned by a
        prop-action run, ``execution_kind`` ``prop_action``) loses it;
    (c) every live order is shifted by the downtime ``max(0, motion_time() -
        motion_alive_s)`` (missing stamp → 0; decision 7d): its times and its
        run's times, revision + 1, republished, marked ``boot_alive_s`` with
        the stamp it was shifted against — a second boot against the same
        stamp (a crash before the heartbeat below) shifts nothing again;

    then the index is rebuilt from the live runs and the profiles' walks
    (:func:`_boot_walks`, shifted the same way) and the heartbeat written."""
    from app.core import prop_action_store as store
    from app.core import prop_action_engine as engine
    from app.core import travel_engine as travel
    from app.models.character import list_active_journeys
    for run in store.live_runs():
        if run["status"] == "approaching" and not (run.get("data") or {}).get("order"):
            engine.migrate_cancel(run["execution_id"])
    for entry in list_active_journeys():
        journey = entry.get("journey") or {}
        if isinstance(journey, dict) and journey.get("execution_kind") == "prop_action":
            travel.cancel_journey(entry["name"], journey_id=journey.get("journey_id"), reason="e3_migration")
    alive = read_alive()
    shift = max(0.0, _now_s() - alive) if alive is not None else 0.0
    with _INDEX_LOCK:
        _INDEX.clear()
        for run in store.live_runs():
            order = (run.get("data") or {}).get("order")
            if not isinstance(order, dict) or not order.get("order_id"):
                continue
            for name in actor_names(order):
                _INDEX[name] = (order, None)
    if shift > 0:
        for run in store.live_runs():
            engine.shift_run(run["execution_id"], shift, alive)
    _boot_walks(shift, alive)
    _write_alive(_now_s())


# ---------------------------------------------------------------------------
# Walk orders (plan E3 Task 9, decisions 9-11 and 20)
# ---------------------------------------------------------------------------

#: The profile field of a live walk: ``{"order": <published order>,
#: "writes_at_flip": bool}`` — the order as the index holds it, and whether
#: ``settle_due`` writes its target at the flip (a walk inside a room or out
#: in the open) or not (a room change: the setter wrote room and stand point
#: at once, decision 10).
PROFILE_KEY = "order"


def _room_level(location: dict, room_id: str) -> int:
    """The storey of a room (its layout ``level``, 0 when unset)."""
    room = next((r for r in (location or {}).get("rooms") or []
                 if isinstance(r, dict) and r.get("id") == room_id), None) or {}
    try:
        return int((room.get("layout") or {}).get("level") or 0)
    except (TypeError, ValueError):
        return 0


def _recipe(location: dict | None, location_id: str) -> dict | None:
    """The composed scene of a stored location out of the recipe cache
    (``scene_recipe.scene_for_location``, no compose when nothing moved)."""
    if not location or not location_id:
        return None
    try:
        from app.core.scene_recipe import scene_for_location
        return scene_for_location(location, location_id)
    except Exception:  # noqa: BLE001 — no recipe: the estimate falls back
        logger.debug("walk order: no scene recipe for %s", location_id, exc_info=True)
        return None


def _floor_y(recipe: dict | None, level: int) -> float:
    """The floor height of storey ``level`` in the recipe (0 without one)."""
    for entry in (recipe or {}).get("levels") or []:
        try:
            if int(entry.get("level")) == int(level):
                return float(entry.get("floor_y") or 0.0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _level_floor_y(location: dict | None, location_id: str, level: int) -> float:
    """The floor height of a storey: 0 on the ground floor (no recipe read),
    else the recipe's."""
    return _floor_y(_recipe(location, location_id), level) if level else 0.0


def start_of(name: str, *, profile: dict | None = None) -> dict | None:
    """Where ``name`` stands right now, as a walk order's actor start plus
    two private keys: ``{x, y, z, yaw, room_id, level, location_id,
    pose_key}`` (``pose_key`` = the pose it holds, for the exit of a room
    change). A decision point reads this BEFORE it calls a room setter
    (decision 10); None for a character without a point."""
    from app.core import places
    from app.models.character import (get_avatar_sync_snapshot, get_character_pos,
                                      get_character_profile, get_effective_pose_key)
    from app.models.world import get_location_by_id
    pos = get_character_pos(name)
    if pos is None:
        return None
    profile = profile if profile is not None else (get_character_profile(name) or {})
    loc_id, room_id = places.where(name, profile=profile)
    location = get_location_by_id(loc_id) if loc_id else None
    level = _room_level(location or {}, room_id)
    yaw = (get_avatar_sync_snapshot(name) or {}).get("yaw")
    try:
        pose = get_effective_pose_key(name) or ""
    except Exception:  # noqa: BLE001
        pose = ""
    return {"x": float(pos["x"]), "y": _level_floor_y(location, loc_id, level), "z": float(pos["z"]),
            "yaw": None if yaw is None else round(math.degrees(float(yaw)), 3),
            "room_id": room_id, "level": level, "location_id": loc_id, "pose_key": pose}


def _point_in(poly, x: float, z: float) -> bool:
    inside = False
    pts = [(float(p[0]), float(p[1])) for p in poly or []]
    for i in range(len(pts)):
        (ax, az), (bx, bz) = pts[i], pts[i - 1]
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            inside = not inside
    return inside


def chain_inputs(location: dict, location_id: str) -> tuple[dict, list, list] | None:
    """``(rooms, doorways, stairs)`` of :func:`room_chain_length` in WORLD
    metres, read off the location's cached scene recipe (location-local
    there). A flight names its ``rooms`` when its foot lies in exactly one
    room of its lower storey and its head in exactly one of its upper storey
    (Task 1 concern 2); otherwise the level rule applies. None without a
    recipe."""
    from app.core.world_geometry import local_to_world
    recipe = _recipe(location, location_id)
    if not recipe:
        return None
    cx, cz = float(location.get("pos_x") or 0.0), float(location.get("pos_z") or 0.0)
    yaw = float(location.get("yaw_deg") or 0.0)
    outlines, rooms = [], {}
    for room in recipe.get("rooms") or []:
        rid = str(room.get("room_id") or "")
        if not rid:
            continue
        level = int(room.get("level") or 0)
        rooms[rid] = level
        outlines.append((rid, level, room.get("outline") or []))
    doorways = []
    for door in recipe.get("doorways") or []:
        at = door.get("at_world") or door.get("at")
        if not at or len(door.get("rooms") or []) < 2:
            continue
        doorways.append({"at": local_to_world(float(at[0]), float(at[1]), cx, cz, yaw),
                         "rooms": list(door["rooms"])})

    def room_at(x, z, level):
        hits = [rid for rid, lv, poly in outlines if lv == level and _point_in(poly, x, z)]
        return hits[0] if len(hits) == 1 else None

    stairs = []
    for flight in recipe.get("stairs") or []:
        try:
            foot, head = flight["foot"], flight["head"]
            lo, hi = int(flight["from_level"]), int(flight["to_level"])
        except (KeyError, TypeError, ValueError):
            continue
        fx, fz = local_to_world(float(foot[0]), float(foot[2]), cx, cz, yaw)
        hx, hz = local_to_world(float(head[0]), float(head[2]), cx, cz, yaw)
        entry = {"foot": (fx, float(foot[1]), fz), "head": (hx, float(head[1]), hz),
                 "from_level": lo, "to_level": hi}
        named = (room_at(float(foot[0]), float(foot[2]), lo), room_at(float(head[0]), float(head[2]), hi))
        if all(named) and named[0] != named[1]:
            entry["rooms"] = list(named)
        stairs.append(entry)
    return rooms, doorways, stairs


def _index_walk(name: str) -> dict | None:
    """The live walk order ``name`` carries in the index (not ended), or None."""
    with _INDEX_LOCK:
        entry = _INDEX.get(name)
    if entry is None:
        return None
    order, until = entry
    if until is not None or order.get("kind") != "walk":
        return None
    return order


def _is_room_change(order: dict) -> bool:
    start = ((order.get("actors") or [{}])[0] or {}).get("start") or {}
    return str(start.get("room_id") or "") != str((order.get("target") or {}).get("room_id") or "")


def walking(name: str, *, profile: dict | None = None, strolls_only: bool = False) -> bool:
    """Whether ``name`` is on a live ``walk`` order whose flip lies ahead
    (decision 20): the profile's ``order`` field when the caller holds the
    profile, else the in-process index. ``strolls_only`` leaves a room-change
    walk out: its room and stand point are already written (decision 10), so
    a gate that starts something there (a pair) need not wait for the image."""
    if profile is not None:
        record = profile.get(PROFILE_KEY)
        order = record.get("order") if isinstance(record, dict) else None
    else:
        order = _index_walk(name)
    if not isinstance(order, dict) or order.get("kind") != "walk":
        return False
    if strolls_only and _is_room_change(order):
        return False
    try:
        return float(order.get("flip_motion_s")) > _now_s()
    except (TypeError, ValueError):
        return False


def walk_due_in_s() -> float | None:
    """Motion seconds until the soonest live walk flips (≤ 0: due now), None
    when no walk is live — the ticker's next beat (``_next_beat_s``)."""
    with _INDEX_LOCK:
        entries = list(_INDEX.values())
    flips = [float(order["flip_motion_s"]) for order, until in entries
             if until is None and order.get("kind") == "walk" and order.get("flip_motion_s") is not None]
    if not flips:
        return None
    return min(flips) - _now_s()


def _walk_length(name: str, start: dict, x: float, z: float, room_id: str, location: dict | None,
                 location_id: str, goal_y: float) -> tuple[float | None, list, str]:
    """``(L, hint_route, mode)`` of a walk (decisions 9 and 11), or
    ``(None, [], reason)``. mode: ``room`` (inside the walker's room: the
    visibility path on the room polygon), ``rooms`` (another room of the same
    location: the room chain of the recipe), ``open`` (the target lies outside
    every location outline: the nav-grid route of the travel engine,
    published as ``hint_route`` — the only server route search a walk makes)."""
    from app.core import places
    from app.core.prop_action_paths import visibility_path
    start_room = start.get("room_id") or ""
    if not location_id:
        from app.core import travel_engine as travel
        from app.core.terrain_query import passability_at
        from app.models.world import get_location_by_id
        if not passability_at(x, z)[0]:
            return None, [], "unpassable"
        here_id = start.get("location_id") or ""
        here = get_location_by_id(here_id) if here_id else None
        waypoints, _speed = travel._bake_route((float(start["x"]), float(start["z"])), (x, z), here,
                                               character_name=name)
        if not waypoints or len(waypoints) < 2:
            return None, [], "no_route"
        route = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in waypoints]
        return sum(math.dist(a, b) for a, b in zip(route, route[1:])), route, "open"
    if room_id == start_room:
        geometry = places._GeometryQuery().room_geometry(location_id, room_id)
        if geometry is None:
            return None, [], "no_route"
        path = visibility_path((float(start["x"]), float(start["z"])), (x, z), *geometry)
        if not path:
            return None, [], "no_route"
        return sum(math.dist(a, b) for a, b in zip(path, path[1:])), [], "room"
    inputs = chain_inputs(location or {}, location_id)
    rooms, doorways, stairs = inputs if inputs else ({}, [], [])
    begin = (float(start["x"]), float(start.get("y") or 0.0), float(start["z"]))
    try:
        length = room_chain_length(rooms, doorways, stairs, begin, start_room, (x, goal_y, z), room_id)
    except ValueError as exc:
        # No chain of doorways/stairs joins the two rooms in the recipe: the
        # estimate falls back to the empty chain (the straight distance).
        logger.warning("walk of %s: no room chain %s -> %s in %s (%s); straight estimate",
                       name, start_room, room_id, location_id, exc)
        length = room_chain_length({}, [], [], begin, start_room, (x, goal_y, z), room_id)
    return length, [], "rooms"


def issue_walk(name: str, x: float, z: float, *, room_id: str = "", level: int = 0,
               y: float | None = None, start: dict | None = None,
               reason: str = "") -> tuple[dict | None, str]:
    """Publish a ``walk`` order of ``name`` to the point ``(x, z)`` (plan E3
    Task 9): ``(order, "ok")`` or ``(None, reason)`` with reason
    ``no_route``, ``unpassable``, ``party_follower`` or the refusal of
    ``interaction_engine.stale_against_pair``.

    ``start`` is the position a decision point read BEFORE its room setter
    (:func:`start_of`); without it the current position. Three kinds of walk,
    by where the target lies (decisions 9-11; no server path search inside a
    location):

    * the walker's own room (``room_id`` = its room, or empty for a point
      inside its location): the visibility path on the room polygon; the
      position stays the start until the flip, then ONE write of the target
      (:func:`settle_due`);
    * another room of the same location: a room change the setter has already
      written (room and stand point at once, decision 10) — the estimate is
      the room chain of the recipe, the flip writes nothing;
    * outside every location outline: the nav-grid route of the travel engine
      as ``hint_route``, the passability gate on the target; the flip writes
      the target.

    A target outside the walker's own location (another location, or the
    open from inside one, or a location from the open) is a journey, not a
    walk (``no_route``).
    ``level`` and ``y`` are informative: the target room decides the storey
    and its floor (``y`` overrides the floor height). The times: ``exit_s`` of
    the pose before the walk (a room change: the pose ``start`` carries),
    ``entry_s`` 0, flip = eta. A walk inside a room or out in the open first
    ends what the figure is doing (the stale gate, the prop action, a pair, a
    journey) and frees a plain seat in the same profile write that stores
    the order; a room change leaves that to its setter."""
    from app.core import places
    from app.core import travel_engine as travel
    from app.core.height import height_cm
    from app.core.keyed_lock import keyed_lock
    from app.core.party_engine import is_party_follower
    from app.core.pose_catalog import group_of
    from app.core.world_geometry import location_at_point
    from app.models.account import is_player_controlled
    from app.models.character import get_character_profile, save_character_profile
    from app.models.world import get_location_by_id, list_locations

    if not name:
        return None, "no_route"
    try:
        gx, gz = round(float(x), 2), round(float(z), 2)
    except (TypeError, ValueError):
        return None, "no_route"
    if not (math.isfinite(gx) and math.isfinite(gz)):
        return None, "no_route"
    if is_party_follower(name):
        return None, "party_follower"
    here = dict(start) if start is not None else start_of(name)
    if here is None:
        return None, "no_route"
    held_pose = str(here.pop("pose_key", "") or "")
    walker_loc = here.pop("location_id", None)
    if walker_loc is None:
        walker_loc = places.where(name)[0]
    at = location_at_point(gx, gz, list_locations())
    location_id = (at.get("id") or "") if at else ""
    if location_id != (walker_loc or ""):
        # Entering or leaving a location (or crossing into another one) is
        # a journey, never a walk: a walk stays where it starts.
        return None, "no_route"
    location = get_location_by_id(location_id) if location_id else None
    if location_id:
        room_id = room_id or places.where(name)[1]
        if not any(isinstance(r, dict) and r.get("id") == room_id for r in (location or {}).get("rooms") or []):
            return None, "no_route"
        level = _room_level(location or {}, room_id)
        goal_y = float(y) if y is not None else _level_floor_y(location, location_id, level)
    else:
        room_id, level = "", 0
        goal_y = float(y) if y is not None else 0.0
    room_change = bool(location_id) and room_id != (here.get("room_id") or "")
    length, hint_route, mode = _walk_length(name, here, gx, gz, room_id, location, location_id, goal_y)
    if length is None:
        return None, mode

    if room_change:
        _kind, exit_s = travel.exit_bridge_for_pose(held_pose)
    else:
        from app.core.interaction_engine import end_interaction, stale_against_pair
        stale = stale_against_pair(name)
        if stale:
            return None, stale
        # The exit of the pose held BEFORE the seat is freed below.
        _kind, exit_s = travel.departure_bridge(name)
        held_pose = held_pose or ""
        from app.models.character import _interrupt_prop_action
        _interrupt_prop_action(name, "journey")
        end_interaction(name, reason="journey")
        journey = travel.get_journey(name)
        if journey:
            travel.cancel_journey(name, journey_id=journey.get("journey_id"), reason="walk")
    issued = _now_s()
    speed = float(travel.get_travel_speed_m_s())
    eta, flip = estimate(issued, exit_s, length, speed, 0.0)
    sequence = []
    if exit_s > 0:
        sequence.append(step("exit", group_of(held_pose), held_pose, exit_s))
    sequence.append(step("walk"))
    actor = actor_row(name, "actor", "", height_cm(get_character_profile(name) or {}), here,
                      sequence=sequence, reports_arrival=is_player_controlled(name))
    order = new_order("walk", issued_s=issued, eta_s=eta, flip_s=flip, deadline_s=deadline(issued, eta),
                      actors=[actor], speed_m_s=speed, gait="walk", status="approaching",
                      hint_route=hint_route,
                      target={"location_id": location_id, "room_id": room_id, "level": level,
                              "x": gx, "y": goal_y, "z": gz})
    writes = not room_change
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        old = profile.get(PROFILE_KEY)
        if writes and (profile.get("place") or exit_s > 0):
            # The seat release of _start (plan E3 Task 7, third review 3): a
            # plain seat without a run is freed nowhere else, because the flip
            # writes with preserve_movement_target=True. A held pose that needs
            # an exit (a sitting pose without a place) is let go the same way.
            profile.update(place=None, pose_key="", pose_flavor="")
        # Published under the profile lock: the profile stores the order with
        # its seq, and a settle of the same order waits for this write.
        published = publish(order, names=[name], locations=[location_id or walker_loc or ""])
        profile[PROFILE_KEY] = {"order": published, "writes_at_flip": writes}
        saved = save_character_profile(name, profile)
    if not saved:
        # The walk is already published: take it back with a cancel (stand =
        # where the figure still is) so no client plays a walk the profile does
        # not carry, then drop it from the index.
        logger.warning("walk %s of %s: profile not saved, cancelled", published["order_id"], name)
        cancel_for(name, reason="write_failed")
        with _INDEX_LOCK:
            entry = _INDEX.get(name)
            if entry is not None and entry[0].get("order_id") == published["order_id"]:
                _INDEX.pop(name, None)
        return None, "write_failed"
    if isinstance(old, dict) and isinstance(old.get("order"), dict) \
            and old["order"].get("order_id") != published["order_id"]:
        logger.debug("walk %s of %s replaced by %s", old["order"].get("order_id"), name, published["order_id"])
    try:
        travel.get_travel_ticker().wake()
    except Exception:  # noqa: BLE001 — no running ticker (scripts, tests)
        pass
    logger.info("Walk order %s: %s -> (%.2f, %.2f) %s (%s, %.2f m, flip in %.2f s)%s", published["order_id"],
                name, gx, gz, room_id or "open", mode, length, flip - issued, f" [{reason}]" if reason else "")
    return published, "ok"


def walk_room_change(name: str, start: dict | None, *, reason: str = "") -> tuple[dict | None, str]:
    """The decision points' second half of a room change (decision 10): the
    setter has written the room and the stand point; publish the walk from
    ``start`` (read before the setter, :func:`start_of`) to that point.
    ``(None, "same_room")`` when the room did not change (the setter refused)."""
    from app.core import places
    from app.models.character import get_character_pos
    if not start:
        return None, "no_route"
    loc_id, room_id = places.where(name)
    if not room_id or room_id == start.get("room_id") or loc_id != start.get("location_id"):
        return None, "same_room"
    pos = get_character_pos(name)
    if pos is None:
        return None, "no_route"
    return issue_walk(name, pos["x"], pos["z"], room_id=room_id, start=start, reason=reason)


def cancel_for(name: str, *, reason: str, snap: bool = False, quiet: bool = False,
               at: tuple[float, float] | None = None) -> None:
    """The choke point that ends a live walk (decision 20): clears the profile
    field ``order`` and publishes a ``cancel`` order (new id, ``stand`` = where
    the figure stands now, ``snap`` for a teleport) — when a walk runs, or
    always with ``snap``. ``quiet`` (only ``prop_action_engine._start``)
    clears without a cancel order: the run's order replaces the walk at once.
    ``at``: the point a position write is about to store (its caller cancels
    BEFORE the write), so ``stand`` names where the figure will be."""
    from app.core import places
    from app.core.height import height_cm
    from app.core.keyed_lock import keyed_lock
    from app.models.account import is_player_controlled
    from app.models.character import get_character_pos, get_character_profile, save_character_profile
    from app.models.world import get_location_by_id
    if not name:
        return
    if not snap and _index_walk(name) is None:
        # The index is the truth while the server runs (boot fills it from the
        # profiles): no live walk, nothing to read or write on this hot path.
        return
    walk = None
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        record = profile.get(PROFILE_KEY)
        if isinstance(record, dict):
            walk = record.get("order")
            profile.pop(PROFILE_KEY, None)
            if not save_character_profile(name, profile):
                # A DB fault: the index lets go below anyway (no settle writes
                # the old target while the server runs), but the field stays on
                # the profile — walking(profile=...) sees it until its flip and
                # a restart would file it again. Logged loudly for that reason.
                logger.error("cancel of %s's walk (%s): profile not saved, the walk field stays", name, reason)
    indexed = _index_walk(name)
    for old in (walk, indexed):
        if isinstance(old, dict):
            retire(old.get("order_id", ""))
    if quiet or (walk is None and indexed is None and not snap):
        return
    pos = get_character_pos(name) or {}
    loc_id, room_id = places.where(name)
    location = get_location_by_id(loc_id) if loc_id else None
    level = _room_level(location or {}, room_id)
    floor_y = _level_floor_y(location, loc_id, level)
    sx, sz = at if at is not None else (pos.get("x") or 0.0, pos.get("z") or 0.0)
    point = {"x": float(sx), "y": floor_y, "z": float(sz), "yaw": None}
    now = _now_s()
    actor = actor_row(name, "actor", "", height_cm(get_character_profile(name) or {}),
                      dict(point, room_id=room_id, level=level), reports_arrival=is_player_controlled(name))
    cancel = new_order("cancel", issued_s=now, eta_s=now, flip_s=now, deadline_s=deadline(now, now),
                       actors=[actor], speed_m_s=0.0, gait="walk", status="ended", snap=snap,
                       stand=point, target={"location_id": loc_id, "room_id": room_id, "level": level,
                                            "floor_y": floor_y})
    publish(cancel, names=[name], locations=[loc_id])
    logger.info("Walk cancelled: %s (%s%s)", name, reason, ", snap" if snap else "")


def settle_due(now_s: float | None = None) -> int:
    """Settle every live walk whose flip has come (``flip ≤ now``): only when
    its id is still the profile's current walk (review B4) — the field is
    cleared under the profile lock FIRST, then a walk inside a room or out in
    the open writes its target once with ``set_character_pos(...,
    preserve_movement_target=True)`` (no ``cancel_for``, no interrupt, no pair
    end; second review N3), a room change writes nothing (decision 10). The
    order is revised to ``ended`` and published; the agent loop gets its
    arrival bump. A walk another write has replaced only leaves the index.
    Returns how many settled."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile, set_character_pos
    now = _now_s() if now_s is None else float(now_s)
    with _INDEX_LOCK:
        due = [(name, order) for name, (order, until) in _INDEX.items()
               if until is None and order.get("kind") == "walk"
               and order.get("flip_motion_s") is not None and float(order["flip_motion_s"]) <= now]
    settled = 0
    for name, order in due:
        record = None
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            current = profile.get(PROFILE_KEY)
            if (isinstance(current, dict) and isinstance(current.get("order"), dict)
                    and current["order"].get("order_id") == order.get("order_id")):
                profile.pop(PROFILE_KEY, None)
                if save_character_profile(name, profile):
                    record = current
        if record is None:
            with _INDEX_LOCK:
                entry = _INDEX.get(name)
                if entry is not None and entry[0].get("order_id") == order.get("order_id"):
                    _INDEX.pop(name, None)
            continue
        target = order.get("target") or {}
        # The target write runs after the profile lock is released: the places
        # lock comes before character_profile (lock order), and
        # set_character_pos takes both. A manual position write landing in this
        # gap is overwritten by the target — the window is the time between
        # these two statements, not the walk (that case cancels, review B4).
        if record.get("writes_at_flip"):
            try:
                set_character_pos(name, float(target["x"]), float(target["z"]), preserve_movement_target=True)
            except (KeyError, TypeError, ValueError):
                logger.warning("walk %s of %s has no target point", order.get("order_id"), name)
        ended = dict(order, status="ended", revision=int(order.get("revision", 1)) + 1)
        publish(ended, names=[name], locations=[target.get("location_id") or ""])
        settled += 1
        try:
            from app.core.agent_loop import get_agent_loop
            get_agent_loop().bump(name)
        except Exception:  # noqa: BLE001 — no loop (scripts, tests)
            pass
    return settled


def _boot_walks(shift: float, alive: float | None) -> None:
    """The live walks of the profiles back into the index at boot (decision
    7c for a walk): shifted by ``shift`` unless already marked ``boot_alive_s``
    = ``alive`` (revision + 1, republished, profile rewritten), otherwise
    filed as they are — a walk whose flip has passed settles on the next beat."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, list_profile_orders, save_character_profile
    for name in list_profile_orders(out_of_world=True):
        # A walk of a body that left the world (dormant, review minor): nobody
        # settles it and no roster shows it — drop the field.
        # Same test as the live loop below: only a field that carries a walk is dropped.
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            record = profile.get(PROFILE_KEY)
            order = record.get("order") if isinstance(record, dict) else None
            if not isinstance(order, dict) or order.get("kind") != "walk":
                continue
            profile.pop(PROFILE_KEY, None)
            if not save_character_profile(name, profile):
                logger.warning("walk of out-of-world %s: field not dropped", name)
    for name in list_profile_orders():
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            record = profile.get(PROFILE_KEY)
            order = record.get("order") if isinstance(record, dict) else None
            if not isinstance(order, dict) or order.get("kind") != "walk" or order.get("status") == "ended":
                continue
            if shift > 0 and order.get("boot_alive_s") != alive:
                moved = dict(order, revision=int(order.get("revision", 1)) + 1, boot_alive_s=alive)
                for key in ("issued_motion_s", "eta_motion_s", "flip_motion_s", "deadline_motion_s"):
                    if moved.get(key) is not None:
                        moved[key] = round(float(moved[key]) + shift, _DECIMALS)
                order = publish(moved, names=[name],
                                locations=[(moved.get("target") or {}).get("location_id") or ""])
                record["order"] = order
                if not save_character_profile(name, profile):
                    # The index holds the shifted order (publish); the profile
                    # keeps the old one and the next boot shifts that again.
                    logger.warning("walk %s of %s: shifted order not saved", order.get("order_id"), name)
            else:
                with _INDEX_LOCK:
                    _INDEX[name] = (order, None)
