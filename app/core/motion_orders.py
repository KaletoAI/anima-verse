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

Checked by scripts/smoke_order_estimate.py (vector shared/test-vectors/order_estimate.json)
and scripts/smoke_orders_route.py (publication, index, visibility).
"""
from __future__ import annotations

import copy
import math
import threading
import uuid
from collections import deque
from typing import Any, Iterable

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
        # seq and index entry in one step under the same lock (decision 6).
        published["seq"] = next_seq()
        for name in names:
            if name:
                _INDEX[name] = (published, until)
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


def boot() -> None:
    """Rebuild the index at server start: every live prop-action run that
    carries an order (``run.data.order``) stands in it again under its
    participants (no new seq, no push — the clients' first poll reads it).
    Runs in the lifespan before the AgentLoop, ``periodic_jobs`` and the
    TravelTicker (decision 7c)."""
    from app.core import prop_action_store as store
    with _INDEX_LOCK:
        _INDEX.clear()
        for run in store.live_runs():
            order = (run.get("data") or {}).get("order")
            if not isinstance(order, dict) or not order.get("order_id"):
                continue
            for name in actor_names(order):
                _INDEX[name] = (order, None)


def walking(name: str, *, profile: dict | None = None) -> bool:
    """Whether ``name`` is on a live ``walk`` order (decision 20). There is no
    ``walk`` order before plan E3 task 9: always False until then."""
    return False
