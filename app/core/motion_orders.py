"""Motion orders: the wire shape of an order and the server's estimate.

An order tells every client how a figure moves from where it stands to where
the server wants it (design docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md
section 5b, plan E3 decisions 2 and 9). The client plans the real path on its
navmesh and picks the concrete clips; the server only ESTIMATES when the
figure arrives (``eta``) and when its state flips (``flip``), on the MOTION
clock (``timeutils.motion_time()``), and gives up at ``deadline``.

This module holds the pure part: constants, the estimate, the room-chain
length for a room change and the order/actor/step dict builders. It imports
no world module at module level (publication, index and walk orders that
need the world import inside their functions).

Usage (from code):
    from app.core import motion_orders as mo
    eta, flip = mo.estimate(now, exit_s, length_m, speed, entry_s)
    order = mo.new_order("prop_action", issued_s=now, eta_s=eta, flip_s=flip,
                         deadline_s=mo.deadline(now, eta), actors=[...], ...)

Checked by scripts/smoke_order_estimate.py (vector shared/test-vectors/order_estimate.json).
"""
from __future__ import annotations

import math
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
