#!/usr/bin/env python3
"""Smoke run for FREE WALKING over ``POST /play/pos``
(Seamless World, E4 task 5).

Runs against a THROWAWAY storage directory — never touches a real world.
Route level: the handler function of ``app/routes/play.py`` is called
directly (a minimal request stand-in supplies the JSON body), so the whole
gate chain runs exactly as it does behind uvicorn — without a server.

WHAT THE ROUTE IS. The metre world has no cells, so it has no compass step
either: the client walks freely and REPORTS where it stands. The server is
not asked for permission per boundary any more, it JUDGES a reported point —
which is why the gates that used to sit on the step have to sit here, all of
them (the E3-C1 lesson: a derived location change that skips the entry gates
is a hole in every rule the world has).

The validation chain, in the order the route applies it:

  1. auth — the logged-in user's active avatar; a party FOLLOWER owns no
     movement at all (403 ``party_follower``, the same sentence
     ``/play/travel`` refuses with),
  2. the numbers are finite (400 — a NaN sails through every later
     comparison and poisons the JSON encoder),
  3. STALE: a report whose ``seq`` is not newer than the last ACCEPTED one is
     dropped SILENTLY (200 ``{ok: false, stale: true}``) — case [21],
  4. THROTTLE: at most ~4 accepted reports a second per avatar. Excess is
     dropped SILENTLY (200 ``{ok: false, throttled: true}``) — a client that
     reports every frame must not collect error toasts,
  5. plausible step against the time elapsed since the LAST ACCEPTED report:
     allowance = max(5 m, 3 × travel_speed × game_factor × elapsed,
     3 × 3.4 m/s × elapsed). THREE terms: the floor, the GAME-clock term and
     the REAL-clock term — the last one exists because free walking is not
     coupled to the game clock, so a frozen or slow world (factor 0) must not
     collect 409s from an honest walker. Generous on purpose — this is an
     anti-teleport bound, not a precision anticheat (409 ``too_far`` + the
     last valid point). ``elapsed`` is the CLIENT's own ``t_ms`` difference
     when the report is stamped, the server's processing-time difference when
     it is not (case [21]),
  6. the LOCATION of the point (``location_at_point``) — derived FIRST,
     because it decides whether the terrain check applies at all,
  7. terrain ``passability_at`` at the reported point, ONLY OUT IN THE
     WILDERNESS (409 ``impassable`` + the last valid point) — inside a placed
     footprint the FOOTPRINT WINS (decision 2026-08-13, case [20]),
  8. the LOCATION TRANSITION derived from the point, through the FULL gate
     (see below).

A running journey is CANCELLED by the first accepted report — free walking
overrides travel deliberately (``set_character_pos`` does it: a position
write that is not a travel step ends the journey).

THE TRANSITION GATE. ``location_at_point`` derives the location of the
reported point; compared with the avatar's current one that is one of four
cases:

  * same location, or wilderness → wilderness: accepted, nothing but the
    point is written;
  * ENTRY (derived, different, non-empty): across an authored boundary
    opening — the point must lie within 1.5 m of one of the target's opening
    world points (§ A1.1) — and only when ``accessible_when`` and
    ``check_access`` pass. A target with NO authored opening at all has a
    FREE boundary (case [15]): it never said where its way in is, so the
    geometric half of the gate has nothing to check and only the rule gates
    remain. The arrival semantics are the ones every other arrival path uses:
    the location is set through ``save_character_current_location`` (which
    discovers the place), and the room is the opening's linked room;
  * EXIT (current non-empty → empty or another): ``boundary_entry.may_leave``
    with the room the avatar stands in — across a near opening from the room
    it links to, from the entry room over any edge, or freely when the
    location declares no entry room at all — AND ``rules.check_leave``, the
    rule half every other movement path asks before it moves anybody;
  * location → location (adjacent footprints): EXIT check, then ENTRY check.

THE WORLD used below (all grass unless painted):

    HALL    (50, 50)   w 10, yaw 0, opening N at 0.5 → (50, 45),
                       rooms foyer + hall, entry_room "hall",
                       the opening links to "foyer"
    LOCKED  (150, 50)  w 10, opening N at 0.5 → (150, 45),
                       accessible_when ["has_item:silver_key"]
    GATE    (250, 50)  w 10, opening N at 0.5 → (250, 45),
                       behind a block rule (action "enter")
    OPEN    (350, 50)  w 10, opening N at 0.5 → (350, 45), NO entry_room
    SQUARE  (0, 200)   w 40, NO openings at all, no entry_room
    HUT     (0, 200)   w 8, INSIDE the square, opening edge 2 (south) at
                       0.5 → (0, 204),
                       rooms foyer + hall, entry_room "hall", link "foyer"
    BLUFF   (600, 50)  w 10, opening edge 0 (north) at 0.5 → (600, 45), ON
                       PAINTED ROCK
                       (rock x ∈ [596, 604], z ∈ [46, 54] — strictly inside
                       the footprint, so the approach outside stays grass)
    a deep-water rectangle x ∈ [-10, 10], z ∈ [6, 26]
    a rock rectangle  x ∈ [640, 650], z ∈ [40, 50] (wilderness, case [20])

HAND-DERIVED EXPECTATIONS (the opening points first, since every entry case
rests on them — ``opening_world_points`` puts the point on the boundary EDGE
the opening names (v6 Nr. 5) and maps local → world through the pin; without a
drawn boundary the effective one is the square, whose edge 0 is the north side
(z = −w/2) and edge 2 the south. At yaw 0 the map is the identity, so HALL's
edge-0 opening at 0.5 sits at (50, 50 − 5) = (50, 45)):

  [1] wilderness → wilderness is free: (0, 0) → (0, 3) is accepted with
      ``location_id: ""`` and ``room_id: ""``.

  [2] The deep-water rectangle is a wall: from (0, 3) the point (0, 7) lies
      inside it and is 4 m away — INSIDE the step allowance of case [3], so
      the terrain is really what refuses it → 409 ``impassable``, and the
      answer hands back the LAST VALID point (0, 3) so the client can snap
      the figure onto it. The MESSAGE names the ground it refused on — the
      catalog's display name for `deep_water` is "Deep water", so it reads
      "You cannot walk there — that is Deep water." (finding B1). Plain
      `water` is SWIMMABLE since round 2 of the acceptance — a wall of water
      is its own kind now.

  [3] Anti-teleport. The clock is pinned at factor 0 for this run, so the
      game term is 0; the reports follow each other within milliseconds, so
      the real term (3 × 3.4 × elapsed, well under 0.1 m here) stays far
      below the floor as well: max(5, 0, ~0.01) = 5 m.
      (0, 3) → (3, 5) is √(3² + 2²) = 3.606 m ≤ 5 → accepted;
      (3, 5) → (500, 0) is ≈ 497 m > 5 → 409 ``too_far`` + (3, 5) back.

  [4] ENTRY through the opening. Standing at (50, 43.5) (wilderness, north of
      HALL), the reported point (50, 46.4) is inside the footprint
      (x ∈ [45, 55], z ∈ [45, 55]) and |46.4 − 45| = 1.4 m from the opening
      (50, 45) → accepted. The room is the OPENING's link "foyer", NOT the
      entry room "hall" (an opening that names a room answers the question by
      itself), and HALL joins ``known_locations`` — arrival discovers.

  [5] The same step 20 cm further in is refused: (50, 46.6) is 1.6 m > 1.5 m
      from the opening → 403 ``no_opening`` + the last valid point.

  [6] ``accessible_when`` is a WALL, not a hint (backend-status-3d.md,
      bdd8598): the entry at (150, 46.4) — 1.4 m from LOCKED's opening — is
      refused with 403 ``not_accessible`` without the silver key and accepted
      with it in the inventory.

  [7] A block rule (action "enter") on GATE refuses the entry at
      (250, 46.4) with 403 ``block_enter`` and the RULE's own sentence.

  [8] LEAVING is ``may_leave``. Standing in HALL's room "foyer" at (50, 52),
      the reported point (50, 56) leaves over the south edge — 11 m from the
      only opening, so no opening backs it, and "foyer" is not the entry room
      "hall" → 403 ``leave_blocked``.

  [9] From the same room ACROSS THE OPENING it works: standing at (50, 46),
      the point (50, 44) is 1 m from the opening (50, 45), whose link
      ("foyer") is the room the avatar is in → accepted, and the avatar
      stands in the wilderness afterwards (location and room both empty).

  [10] From the ENTRY ROOM every edge is a way out: standing in "hall" at
      (50, 52), the same southern point (50, 56) is accepted.

  [11] A location without an entry room lets go anywhere: standing on OPEN's
      ground at (350, 52), (350, 56) is accepted.

  [12] A running journey dies with the first accepted report: after
      ``POST /play/travel`` the profile holds a journey and a movement
      target; one accepted point later both are gone.

  [13] The throttle, pinned from BOTH sides and without a wall clock (E7
      finding B5). The interval is a module attribute, so the case sets it
      instead of racing it: with an hour of interval the second report of the
      pair is dropped no matter how slow the machine is
      (``{ok: false, throttled: true}``, and the avatar keeps the point of the
      accepted one); with the interval back at 0 the very same report is
      accepted. Inside → dropped, outside → accepted, and no timing left to
      lose. The first report of the pair is free because ``park()`` forgets
      the report clock.

  [14] A party follower is refused with 403 ``party_follower``; a non-finite
      coordinate is a 400.

  [15] A location with NO authored opening has a FREE boundary (decision of
      the E4 task 5 review): it never said where its way in is, which is the
      mirror of ``may_leave``'s "no entry room = leave anywhere". SQUARE
      spans x, z ∈ [−20, 20] around (0, 200), so (0, 185) is inside it and
      15 m from every corner — accepted, and the room is the ordinary
      arrival rule's answer (no entry room → the ground). The rule gates are
      untouched by the exemption: the place is still discovered on arrival.

  [16] Nested footprints. HUT (8 m) sits inside SQUARE (40 m) on the same
      centre, so HUT covers z ∈ [196, 204] and ``location_at_point`` gives
      the SMALLEST match: (0, 200) is the hut, (0, 205.2) is the square.
      Walking out of the hut is therefore an EXIT and an ENTRY in ONE report
      — |205.2 − 204| = 1.2 m ≤ 1.5 from the hut's S opening whose link
      "foyer" is the room the avatar stands in, and the square is openingless
      → free. The way BACK is not free: the hut HAS an opening, so (0, 203)
      (1 m from it) is let in and (0, 197) (7 m from it) is refused.

  [17] ``rules.check_leave`` is a gate here too. The geometry of case [9]
      verbatim, but with a block rule ``action="leave"`` on HALL: 403
      ``block_leave`` with the rule's own sentence. Every other movement path
      asks that rule (travel route, ticker, SetLocation skill, scheduler);
      walking out must not be the one hole in it.

  [18] Walking WAKES a sleeping avatar — the same rule ``/play/enter-room``
      and ``/play/travel`` apply. A REFUSED report wakes nobody: it moved
      nobody.

  [19] The allowance is not only game-time coupled. With the clock frozen
      (factor 0) the travel-speed term is 0, so what is left is the 5 m floor
      and the REAL-speed term 3 × 3.4 m/s × elapsed. After 0.55 s that is
      5.61 m, so a 5.05 m step — outside the bare floor — is allowed; the
      next report has elapsed ≈ 0, the allowance is the floor again, and
      20 m is far outside it.

  [20] FOOTPRINT WINS (decision 2026-08-13, acceptance finding B1 — and the
      prerequisite for E8's plateau, where the ground under a footprint is
      levelled). Painted terrain judges the WILDERNESS; inside a placed
      footprint it is not asked at all. BLUFF sits at (600, 50) with 10 m
      width, so it covers x, z ∈ [595, 605] × [45, 55], and the rock is
      painted x ∈ [596, 604], z ∈ [46, 54] — strictly inside it, so the
      approach from the north stays grass. Three probes, and the middle one
      is the counter-probe that would have failed under the old order:
        a) the ROCK IS REALLY THERE: ``passability_at(600, 46.4)`` is False
           and ``kind_at`` says "rock" — without this line the case could
           pass on a world where nothing was painted at all;
        b) entering at (600, 46.4) — 1.4 m ≤ 1.5 from the opening (600, 45),
           and on that very rock — is ACCEPTED, room "foyer"; walking on
           within the place to (600, 48) (1.6 m, deeper into the rock) is
           accepted too: the ground inside is nobody's gate;
        c) DELETE the location and report the identical point from the
           identical parking spot: now it is wilderness rock and comes back
           409 ``impassable`` with the catalog's name ("Rock").
      Plus the wilderness half, untouched: a rock patch x ∈ [640, 650],
      z ∈ [40, 50] with no location anywhere near it refuses (645, 42).

  [21] THE ORDERING PAIR ``seq`` + ``t_ms`` (2026-08-23) — the answer to the
      snap-back loop a BLOCKED EVENT LOOP produces. The client gives a report
      8 s and then aborts it, but the request keeps running on the server and
      is processed late; taken as the newest point it drags the server's
      baseline seconds behind the figure, and every honest report after it
      looks like a 12 m stride in 0.4 s. Four probes, all with the game clock
      frozen (factor 0, so the game term of the allowance is 0):
        a) two stamped reports, ``seq`` 1 then 5, land the avatar on
           (800, 803) — plain wilderness grass, nothing near it;
        b) THE LEFTOVER: ``seq`` 2 at (800, 802). One metre away, grass, in
           the wilderness — it would sail through every single gate, which is
           the point: only the ORDER refuses it. Answer 200
           ``{ok: false, stale: true}``, and the stored point stays
           (800, 803). No correction is sent, so nothing snaps back;
        c) THE STALLED SERVER: the client walked 20 m while the loop was
           blocked for 3 s and its clock says so (``t_ms`` 2000 → 5000), while
           the gap between the two handler runs is ≈ 0. Client-measured
           elapsed 3.0 s → allowance max(5, 0, 3 × 3.4 × 3.0) = 30.6 m, and
           20 m is inside it → accepted;
        d) THE COUNTER-PROBE, the same 20 m from the same point with NO stamp:
           elapsed is the server's ≈ 0, the allowance falls back to the 5 m
           floor and it is refused ``too_far`` — which is both halves at once,
           the proof that (c) was really the client's clock and the proof that
           an unstamped client is judged exactly as before (a 2 m step right
           after it is accepted, so what refuses is the distance and not a
           block).
      Plus the RELOAD: a fresh session restarts its counter at 1, and a
      baseline of ``seq`` 40 would make every one of its reports "stale"
      forever. The client clock gives it away — 90 s of the old session
      against 30 ms of the new one is far outside the 15 s leftover window —
      so the baseline is dropped and the new session's first report is taken.

  [22] ONE REPORT AT A TIME PER AVATAR, AND THE SECOND IS DROPPED
      (2026-08-24). The route hands everything after the body parse to the
      threadpool, so the event loop stops being the thing that serialized two
      reports of the same avatar. What serializes them now is a per-avatar
      lock — taken WITHOUT WAITING: a walker sends up to four reports a
      second, and parking each contended one on the lock would tie a
      threadpool worker to it (the shared executor is what the move off the
      event loop was meant to protect), while the point it carries is stale by
      the time the lock is free anyway. So with the avatar's lock taken by the
      test, a report started in another thread comes back AT ONCE with 200
      ``{ok: false, superseded: true}`` and writes nothing — the client reads
      every ``ok: false`` the same way (still dirty, report again next tick,
      ≤ 250 ms later), and the report after the release is an ordinary
      acceptance. Two DIFFERENT avatars get two different locks, which is what
      keeps two players out of each other's way.

  [23] THE BAKED SURFACES ARE PART OF THE STEP (spec-surface-height § 7).
      The height gate does not measure the world ground alone any more: ``dh``
      runs between ``stand_height_at(was, here)`` and
      ``stand_height_at(derived, x, z)``, and ``stand_height_at`` is
      ``max(ground_at, the highest answering lattice of the location)`` — the
      server's copy of the client's ``standY``.
      The lattices are STUBBED here (``model_surface._placed_specs``), so the
      case owns its numbers instead of a Blender bake's. YARD — 40 m wide at
      (1000, 1000), no openings, flat ground, nothing else near it — carries
      two walkable props, each a 1 m x 1 m box of ONE height with a 5 x 5
      lattice (1 m / 0.25 m + 1 nodes per side, ``origin`` on the box's lower
      corner), ``max_m`` 1 and ``measure`` "xyz". So the placement scale is
      ``s = max_m / max(1, h, 1) = 1`` and a node reads
      ``bottom_y + lift + s * value/100`` = the box height itself, over the
      local square x, z in [-0.5, 0.5] around the anchor:
        CRATE at the pin, local (0, 0)  -> 0.30 m,
        BLOCK 10 m east, local (10, 0)  -> 0.80 m.
      With ``max_step`` = 0.4 m (the default of ``get_max_step_height_m()``),
      ``max_slope_deg`` = 40 and a 0.7 m report — inside ``STEP_DISTANCE_M``
      = 1 m, so the step limit applies on top of the slope one:
        a) THE CACHE. YARD has no layout, no outline and no building model, so
           it is the 404 case: nothing composes, the empty answer is cached
           under the location id and ``forget_surfaces`` drops it again.
        b) THE READINGS: beside the crate 0.00, on it 0.30, on the block 0.80,
           and without a location the bare ground.
        c) THE LIFT (§ 6.2). With the ground stubbed to a ramp
           ``g(x) = (x - 1000) * 0.1`` the datum is the ground under the pin,
           ``g(1000) = 0``, and a storey-0 placement stands on the ground under
           ITS OWN anchor: the block's lift is ``g(1010) - 0 = 1.0``, so it
           reads 0 + 1.0 + 0.8 = 1.80. Put the same spec on storey 1 and it is
           FILTERED OUT OF THE GROUND LADDER entirely (``tileWalkY`` takes
           ``level === 0`` only) — what is left at that point is the terrain,
           1.00 (Entscheid 5: the terrain stays the lower bound).
           And the filter is what does it, not the arithmetic: back on flat
           ground a storey-1 lattice standing at ``bottom_y`` 3.0 would answer
           3.80 and out-rank every terrain there is — the gate still says 0.00.
        d) CLIMBING THE CRATE: park at (999.3, 1000) — 0.7 m west of the pin,
           outside the lattice, so 0.00 — and report (1000, 1000):
           dh = 0.30 <= 0.4 -> accepted.
        e) THE BLOCK IS A WALL: park at (1009.3, 1000) (0.00) and report
           (1010, 1000): dh = 0.80 > 0.4 over 0.7 m -> 409 ``too_steep`` with
           the STEP sentence, and the last valid point comes back.
        f) AND DOWN AGAIN: from the crate (1000, 1000) to (999.3, 1000) is
           dh = -0.30 -> accepted; the gate is symmetric.
        g) A BROKEN LATTICE IS NOT A WALL (ruling task 2): with the lookup
           raising, the gate logs ONCE per location and answers on the world
           ground instead of refusing the report — or, worse, 500-ing it. The
           flag that silences the second traceback is dropped by
           ``forget_surfaces`` together with the cached lattices.

NOTE ON THE PARKING HELPER. ``park()`` writes the avatar's point directly
(``set_character_pos``) and forgets the report clock — it is WORLD SETUP, not
a call of the route: walking the 45 m up to HALL through the route would be a
hundred accepted reports and would say nothing the cases above do not. The
first report after a park therefore has no baseline to measure against, which
is exactly the rule the route applies to a fresh session (a takeover, an
admin move): the step check needs a previous ACCEPTED report and skips
without one. Cases [3] and [13] are the ones that supply that baseline.

Usage:  ./.venv/bin/python scripts/smoke_play_pos.py
"""
import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]

STORAGE = Path(tempfile.mkdtemp(prefix="play-pos-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="play-pos-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import terrain_query, travel_engine  # noqa: E402
from app.core.party_engine import add_to_party, leave_party  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_pos, get_known_locations, get_movement_target,
    is_character_sleeping, save_character_current_room, save_character_profile,
    set_character_pos, set_is_sleeping, set_known_locations)
from app.models.inventory import add_item, add_to_inventory  # noqa: E402
from app.models.rules import add_rule, delete_rule  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    delete_location, update_location_position)
from app.routes import play as play_route  # noqa: E402
from app.routes.play import play_pos, play_travel  # noqa: E402

FAILURES = []
CHECKED = 0

# Game time is the world calendar — a canonical stamp, never a date.
START_GT = GameTime.parse("Y0001-D001T12:00:00")
USER = {"username": "demo", "role": "user"}
AVATAR = "demo_avatar"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _FakeRequest:
    """Minimal stand-in: the route only ever awaits ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def patch_location(location_id: str, **fields) -> None:
    """Merge top-level fields into a stored location (rooms, entry_room, …)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc.update(fields)
    _save_world_data(data)


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (boundary, openings).

    A ``plan_width_m`` handed in is DRAWN as the centred square of that edge
    (clockwise in map view) and the width is kept alongside — exactly what
    ``_sanitize_map3d`` stores for such an outline. Since 2026-08-19 the width
    alone is no shape at all: a location without a drawn boundary has no area
    anywhere, so every fixture that wants ground has to say so.
    """
    width = fields.get("plan_width_m")
    if width:
        _h = round(float(width) / 2.0, 2)
        fields.setdefault("boundary", [[-_h, -_h], [_h, -_h],
                                       [_h, _h], [-_h, _h]])
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def place(name: str, x: float, z: float, *, room: str = "",
          entry_room: str = "", width: float = 10.0, edge: int = 0,
          openings: bool = True) -> str:
    """A location at (x, z) with ONE authored opening (default: edge 0, the
    NORTH side of the square boundary — contract v6 Nr. 5 numbers the edges
    clockwise from the north-west corner).

    ``openings=False`` draws none at all — the FREE-BOUNDARY case: a place
    that never said where its way in is (a painted square, a meadow).
    """
    loc_id = add_location(name=name, description="play/pos smoke")["id"]
    update_location_position(loc_id, x, z)
    set_map3d(loc_id, plan_width_m=width,
              boundary_openings=[{"edge": edge, "at": 0.5, "width_m": 4.0,
                                  "type": "passage", "room": room}]
              if openings else [])
    patch_location(loc_id,
                   rooms=[{"id": "foyer", "name": "Foyer"},
                          {"id": "hall", "name": "Hall"}],
                   entry_room=entry_room)
    return loc_id


def report(x: float, z: float, seq: int = None, t_ms: float = None):
    """POST /play/pos → ("ok", payload) or ("refused", (status, detail)).

    ``seq``/``t_ms`` are the client's ORDERING PAIR (case [21]) and are only
    put into the body when given — every other case here reports UNSTAMPED,
    which is the behaviour the pair must leave untouched.
    """
    payload = {"x": x, "z": z}
    if seq is not None:
        payload["seq"], payload["t_ms"] = seq, t_ms
    try:
        return "ok", asyncio.run(play_pos(_FakeRequest(payload), user=USER))
    except HTTPException as exc:
        return "refused", (exc.status_code, exc.detail)


def park(x: float, z: float, room: str = "") -> None:
    """World setup, not a move: put the avatar at a point and forget BOTH
    report baselines (the server's clock and the client's ordering pair), so
    the next report is judged like a session's first one."""
    set_character_pos(AVATAR, x, z)
    if room:
        save_character_current_room(AVATAR, room)
    play_route._pos_report_at.pop(AVATAR, None)
    play_route._pos_client_at.pop(AVATAR, None)


def refusal_of(res):
    status, detail = res[1]
    detail = detail if isinstance(detail, dict) else {"message": detail}
    return status, detail.get("reason"), detail.get("pos"), \
        detail.get("location_id"), detail.get("message")


# ── the world ───────────────────────────────────────────────────────────
set_game_factor(0.0)
set_game_time(START_GT)

HALL = place("Smoke Hall", 50.0, 50.0, room="foyer", entry_room="hall")
LOCKED = place("Smoke Vault", 150.0, 50.0, room="foyer", entry_room="hall")
GATE = place("Smoke Gate", 250.0, 50.0, room="foyer", entry_room="hall")
OPEN = place("Smoke Clearing", 350.0, 50.0)
# The nested pair: a 40 m square WITHOUT openings (x, z ∈ [-20, 20] + 200) and
# an 8 m hut in its middle (z ∈ [196, 204]) whose S opening sits at (0, 204).
SQUARE = place("Smoke Square", 0.0, 200.0, width=40.0, openings=False)
HUT = place("Smoke Hut", 0.0, 200.0, width=8.0, edge=2, room="foyer",
            entry_room="hall")
BLUFF = place("Smoke Bluff", 600.0, 50.0, room="foyer", entry_room="hall")
# Case [23]: the baked-surface yard — 40 m without openings (x, z ∈ [980,
# 1020] around (1000, 1000)), far from every other fixture, on flat ground.
YARD = place("Smoke Yard", 1000.0, 1000.0, width=40.0, openings=False)
patch_location(LOCKED, accessible_when=["has_item:silver_key"])
add_item(name="Silver Key", description="opens the vault", item_id="silver_key")
terrain.save_area({"kind": "deep_water",
                   "polygon": [[-10, 6], [10, 6], [10, 26], [-10, 26]],
                   "z_order": 0})
# Case [20]: rock STRICTLY INSIDE the bluff's footprint (x, z ∈ [595, 605]),
# so the approach from the north is grass and only the inside is rock…
terrain.save_area({"kind": "rock",
                   "polygon": [[596, 46], [604, 46], [604, 54], [596, 54]],
                   "z_order": 0})
# …and a second patch far out in the wilderness, where the rule is unchanged.
terrain.save_area({"kind": "rock",
                   "polygon": [[640, 40], [650, 40], [650, 50], [640, 50]],
                   "z_order": 0})

save_character_profile(AVATAR, {"current_location": "", "language": "en"},
                       create_new=True)
set_character_pos(AVATAR, 0.0, 0.0)
set_known_locations(AVATAR, [])
set_active_character(AVATAR)

# The throttle is the ONE rule that is about wall time — the route reads the
# interval from this module attribute, so the smoke SETS the interval instead
# of racing the clock. Everywhere but case [13] it is 0: no report is ever
# dropped, so no case has to sleep FOR THE THROTTLE. (Case [19] does sleep,
# and deliberately: what it measures IS real elapsed time — the real-speed
# term of the step allowance. That sleep is open and stable, it only ever
# grants MORE allowance.)
#
# Case [13] uses the two extremes, never the production 0.25 s (E7 finding B5:
# with the real interval the outcome depended on how fast this machine ran two
# calls in a row — on a loaded box the second report could legitimately arrive
# LATE and be accepted, and the case failed for no defect at all).
#   * BLOCK_INTERVAL — an hour. Whatever the machine does between two calls,
#     the elapsed time is far below it, so the drop is certain.
#   * 0.0 — nothing is ever dropped, so the acceptance after it is certain too.
# Between them they pin the rule from both sides ("inside the interval →
# dropped, outside → accepted") with no wall-clock assumption left.
BLOCK_INTERVAL = 3600.0
play_route._POS_REPORT_INTERVAL_S = 0.0


def main() -> int:
    print("\n[1] wilderness → wilderness is free")
    status, payload = report(0.0, 3.0)
    check("the call succeeded", status, "ok")
    check("accepted", (payload or {}).get("ok"), True)
    check("the answered point", (payload or {}).get("pos"), {"x": 0.0, "z": 3.0})
    check("no location out there", (payload or {}).get("location_id"), "")
    check("no room out there", (payload or {}).get("room_id"), "")
    check("the stored point followed", get_character_pos(AVATAR),
          {"x": 0.0, "z": 3.0})

    print("\n[2] impassable terrain is a wall (409 + the last valid point)")
    res = report(0.0, 7.0)
    status, reason, pos, loc_id, _msg = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 409)
    check("the reason", reason, "impassable")
    # The message NAMES THE GROUND (E4 acceptance finding B1). The display
    # name is the terrain catalog's — shared/terrain/types.json has
    # `deep_water` as "Deep water" — and the avatar's language is "en", so the
    # English source string comes back with the name interpolated.
    check("the message names the terrain", _msg,
          "You cannot walk there — that is Deep water.")
    check("the last valid point comes back", pos, {"x": 0.0, "z": 3.0})
    check("with the location it belongs to", loc_id, "")
    check("the avatar did not move", get_character_pos(AVATAR),
          {"x": 0.0, "z": 3.0})

    print("\n[3] the anti-teleport bound (allowance floor 5 m at factor 0)")
    status, payload = report(3.0, 5.0)          # 3.606 m — inside the floor
    check("a 3.606 m step is accepted", (payload or {}).get("ok")
          if status == "ok" else status, True)
    res = report(500.0, 0.0)                    # ≈ 497 m — far outside it
    status, reason, pos, _loc, _msg = refusal_of(res)
    check("the jump is refused", res[0], "refused")
    check("the status", status, 409)
    check("the reason", reason, "too_far")
    check("the last valid point comes back", pos, {"x": 3.0, "z": 5.0})
    check("the avatar did not move", get_character_pos(AVATAR),
          {"x": 3.0, "z": 5.0})

    print("\n[4] ENTRY across the authored opening (1.4 m from (50, 45))")
    park(50.0, 43.5)
    status, payload = report(50.0, 46.4)
    check("the call succeeded", status, "ok")
    check("accepted", (payload or {}).get("ok"), True)
    check("the derived location", (payload or {}).get("location_id"), HALL)
    check("the room is the OPENING's link, not the entry room",
          (payload or {}).get("room_id"), "foyer")
    check("the profile agrees on the location",
          get_character_current_location(AVATAR), HALL)
    check("the profile agrees on the room",
          get_character_current_room(AVATAR), "foyer")
    check("arriving discovered the place",
          HALL in get_known_locations(AVATAR), True)

    print("\n[5] 20 cm further in there is no opening any more (1.6 m)")
    park(50.0, 43.5)
    res = report(50.0, 46.6)
    status, reason, pos, loc_id, _msg = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "no_opening")
    check("the last valid point comes back", pos, {"x": 50.0, "z": 43.5})
    check("the avatar stayed outside",
          get_character_current_location(AVATAR), "")

    print("\n[6] accessible_when is a wall, not a hint")
    park(150.0, 43.5)
    res = report(150.0, 46.4)
    status, reason, _pos, _loc, _msg = refusal_of(res)
    check("refused without the key", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "not_accessible")
    check("the avatar stayed outside",
          get_character_current_location(AVATAR), "")
    add_to_inventory(AVATAR, "silver_key")
    park(150.0, 43.5)
    status, payload = report(150.0, 46.4)
    check("with the key the very same step is accepted", status, "ok")
    check("the derived location", (payload or {}).get("location_id"), LOCKED)

    print("\n[7] a block rule refuses the entry with its own sentence")
    rule = add_rule({"type": "block", "action": "enter", "name": "Sealed",
                     "condition": "always",
                     "message": "The gate is sealed.",
                     "target": {"scope": "location", "location_id": GATE}})
    park(250.0, 43.5)
    res = report(250.0, 46.4)
    status, reason, _pos, _loc, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "block_enter")
    check("the rule's own message", message, "The gate is sealed.")
    check("the avatar stayed outside",
          get_character_current_location(AVATAR), "")
    delete_rule(rule.get("id") if isinstance(rule, dict) else rule)

    print("\n[8] leaving over a plain edge from the wrong room is barred")
    park(50.0, 52.0, room="foyer")
    check("the setup put the avatar in HALL",
          get_character_current_location(AVATAR), HALL)
    res = report(50.0, 56.0)
    status, reason, pos, loc_id, _msg = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "leave_blocked")
    check("the last valid point comes back", pos, {"x": 50.0, "z": 52.0})
    check("with the location it belongs to", loc_id, HALL)
    check("the avatar is still inside",
          get_character_current_location(AVATAR), HALL)

    print("\n[9] …but across the opening, from the room it links to, it works")
    park(50.0, 46.0, room="foyer")
    status, payload = report(50.0, 44.0)
    check("the call succeeded", status, "ok")
    check("accepted", (payload or {}).get("ok"), True)
    check("out in the wilderness", (payload or {}).get("location_id"), "")
    check("and roomless with it", (payload or {}).get("room_id"), "")
    check("the profile agrees", get_character_current_location(AVATAR), "")

    print("\n[10] from the entry room every edge is a way out")
    park(50.0, 52.0, room="hall")
    status, payload = report(50.0, 56.0)
    check("the call succeeded", status, "ok")
    check("out in the wilderness", (payload or {}).get("location_id"), "")

    print("\n[11] a location without an entry room lets go anywhere")
    park(350.0, 52.0)
    check("the setup put the avatar in OPEN",
          get_character_current_location(AVATAR), OPEN)
    status, payload = report(350.0, 56.0)
    check("the call succeeded", status, "ok")
    check("out in the wilderness", (payload or {}).get("location_id"), "")

    print("\n[12] the first accepted report cancels a running journey")
    park(50.0, 43.5)
    set_known_locations(AVATAR, [HALL, LOCKED, GATE, OPEN])
    asyncio.run(play_travel(_FakeRequest({"target_id": OPEN}), user=USER))
    check_true("a journey is running",
               travel_engine.get_journey(AVATAR) is not None)
    check("with a movement target", get_movement_target(AVATAR), OPEN)
    park(50.0, 43.5)
    status, _payload = report(50.0, 42.0)
    check("the report was accepted", status, "ok")
    check("the journey is gone", travel_engine.get_journey(AVATAR), None)
    check("and its target with it", get_movement_target(AVATAR), "")

    print("\n[13] the throttle drops the excess silently")
    # An hour of interval instead of the real 0.25 s: no machine can outrun it,
    # so this case measures the RULE and not the runtime (see BLOCK_INTERVAL).
    play_route._POS_REPORT_INTERVAL_S = BLOCK_INTERVAL
    park(0.0, 0.0)      # forgets the report clock: no baseline, first is free
    status, first = report(0.0, 1.0)
    check("the first report is accepted", (first or {}).get("ok")
          if status == "ok" else status, True)
    status, second = report(0.0, 2.0)
    check("the second one inside the interval is dropped", status, "ok")
    check("…not as an error", (second or {}).get("ok"), False)
    check("…and it says why", (second or {}).get("throttled"), True)
    check("the avatar stands where the accepted report put it",
          get_character_pos(AVATAR), {"x": 0.0, "z": 1.0})
    # The other extreme, and the proof that the drop was the INTERVAL and not
    # a permanent block: with the interval at 0 the very same third report
    # (the baseline is a fraction of a second old) is accepted.
    play_route._POS_REPORT_INTERVAL_S = 0.0
    status, third = report(0.0, 2.0)
    check("outside the interval the same report is accepted", status, "ok")
    check("…and it is a real acceptance", (third or {}).get("ok"), True)
    check("the avatar followed it", get_character_pos(AVATAR),
          {"x": 0.0, "z": 2.0})

    print("\n[14] the two refusals that come before everything else")
    park(0.0, 0.0)
    res = report(float("nan"), 0.0)
    check("a non-finite coordinate is a 400", res[1][0]
          if res[0] == "refused" else res[0], 400)
    # A party needs both of them in the SAME location (``same_location`` is
    # the central brake), so the two stand in HALL for this one.
    save_character_profile("demo_leader", {"current_location": "",
                                           "language": "en"}, create_new=True)
    set_character_pos("demo_leader", 50.0, 50.0)
    park(50.0, 50.0)
    check_true("the party was formed",
               add_to_party("demo_leader", AVATAR) is not None)
    res = report(50.0, 51.0)
    status, reason, _pos, _loc, _msg = refusal_of(res)
    check("a party follower is refused", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "party_follower")
    leave_party(AVATAR)

    print("\n[15] a location WITHOUT authored openings has a free boundary")
    # SQUARE spans x, z in [-20, 20] around (0, 200) and draws no opening at
    # all. It never said where its way in is — the mirror of may_leave's "no
    # entry room = leave anywhere" — so walking in is free. (0, 178) is
    # outside it, (0, 185) is inside and 15 m from every corner.
    park(0.0, 178.0)
    check("the setup left the avatar outside",
          get_character_current_location(AVATAR), "")
    status, payload = report(0.0, 185.0)
    check("the call succeeded", status, "ok")
    check("the derived location", (payload or {}).get("location_id"), SQUARE)
    # No opening means no room link either, so the ordinary arrival rule
    # decides: SQUARE declares no entry room, which is the ground.
    check("the room is the arrival rule's answer, the ground",
          (payload or {}).get("room_id"), GROUND_ROOM_ID)
    check("but the rule gates still ran: it was discovered",
          SQUARE in get_known_locations(AVATAR), True)

    print("\n[16] the nested case: out of the hut IS into the square")
    # HUT (8 m) sits inside SQUARE (40 m) on the same centre, so its z runs
    # [196, 204] and its S opening is at (0, 204). location_at_point gives the
    # SMALLEST footprint, so (0, 200) is the hut and (0, 205.2) is the square.
    # Leaving the hut is therefore an EXIT plus an ENTRY in one report:
    #   exit  — |205.2 - 204| = 1.2 m <= 1.5 from the S opening, whose link
    #           "foyer" is the room the avatar stands in -> may_leave
    #   enter — SQUARE has no openings -> free boundary
    park(0.0, 200.0, room="foyer")
    check("the setup put the avatar in the hut",
          get_character_current_location(AVATAR), HUT)
    status, payload = report(0.0, 205.2)
    check("the call succeeded", status, "ok")
    check("one report, two gates: it lands in the square",
          (payload or {}).get("location_id"), SQUARE)
    check("...on its ground", (payload or {}).get("room_id"), GROUND_ROOM_ID)
    # And the way back in: the hut HAS an opening, so only that one lets in.
    status, payload = report(0.0, 203.0)     # 1 m inside, 1 m from (0, 204)
    check("back in through the hut's own opening", status, "ok")
    check("the derived location", (payload or {}).get("location_id"), HUT)
    check("the room is the opening's link", (payload or {}).get("room_id"),
          "foyer")
    park(0.0, 200.0, room="foyer")
    status, _payload = report(3.0, 197.0)    # still inside the hut
    check("moving WITHIN the hut needs no opening at all", status, "ok")
    park(0.0, 210.0)                         # in the square, north of the hut
    res = report(0.0, 197.0)                 # into the hut, 7 m from (0, 204)
    status, reason, _pos, _loc, _msg = refusal_of(res)
    check("into the hut anywhere else: refused", res[0], "refused")
    check("the reason", reason, "no_opening")

    print("\n[17] a leave RULE bars the way out, not just the geometry")
    # The geometry of case [9] verbatim — out of HALL across its own opening,
    # from the room it links to — but with a block rule on leaving. Every
    # other movement path asks check_leave (travel, ticker, skill, scheduler);
    # walking out must not be the one hole in it.
    rule = add_rule({"type": "block", "action": "leave", "name": "Pinned",
                     "condition": "always",
                     "message": "You promised to wait here.",
                     "target": {"scope": "location", "location_id": HALL}})
    park(50.0, 46.0, room="foyer")
    res = report(50.0, 44.0)
    status, reason, pos, loc_id, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 403)
    check("the reason", reason, "block_leave")
    check("the rule's own message", message, "You promised to wait here.")
    check("the avatar is still inside",
          get_character_current_location(AVATAR), HALL)
    delete_rule(rule.get("id") if isinstance(rule, dict) else rule)
    park(50.0, 46.0, room="foyer")
    status, _payload = report(50.0, 44.0)
    check("without the rule the very same step works again", status, "ok")

    print("\n[18] walking wakes a sleeping avatar — a refused report does not")
    park(0.0, 0.0)
    set_is_sleeping(AVATAR, True)
    res = report(0.0, 7.0)                   # into the water: refused
    check("the report was refused", res[0], "refused")
    check("...so nobody woke up", is_character_sleeping(AVATAR), True)
    status, _payload = report(0.0, 2.0)
    check("an accepted report", status, "ok")
    check("...wakes the avatar", is_character_sleeping(AVATAR), False)

    print("\n[19] the allowance follows REAL time, not only the game clock")
    # The game clock is frozen (factor 0) for this whole run, so the
    # travel-speed term is 0 and only two terms are left:
    #   floor            = 5 m
    #   real-speed term  = 3 x 3.4 m/s x elapsed
    # After 0.55 s of real time that is 3 x 3.4 x 0.55 = 5.61 m, so a 5.05 m
    # step — refused by the bare floor — is allowed. The very next report has
    # elapsed ~= 0, the allowance falls back to the 5 m floor, and 20 m is
    # far outside it.
    park(200.0, 200.0)
    status, _payload = report(200.0, 201.0)  # sets the baseline clock
    check("the baseline report", status, "ok")
    time.sleep(0.55)
    status, _payload = report(205.05, 201.0)
    check("5.05 m after 0.55 s of walking is allowed", status, "ok")
    res = report(225.05, 201.0)
    status, reason, _pos, _loc, _msg = refusal_of(res)
    check("20 m in the same instant is not", res[0], "refused")
    check("the reason", reason, "too_far")

    print("\n[20] FOOTPRINT WINS: painted ground judges the wilderness only")
    # (a) the counter-probe FIRST: the rock really is under the footprint, so
    # the acceptance below is the new gate order and not an unpainted world.
    check("the point inside the bluff is impassable ground",
          terrain_query.passability_at(600.0, 46.4)[0], False)
    check("...and it is rock", terrain_query.kind_at(600.0, 46.4), "rock")
    # (b) entering ON that rock, 1.4 m from the opening (600, 45).
    park(600.0, 43.5)
    check("the setup left the avatar outside",
          get_character_current_location(AVATAR), "")
    status, payload = report(600.0, 46.4)
    check("the call succeeded", status, "ok")
    check("the derived location", (payload or {}).get("location_id"), BLUFF)
    check("the room is the opening's link", (payload or {}).get("room_id"),
          "foyer")
    status, payload = report(600.0, 48.0)      # 1.6 m deeper into the rock
    check("walking on inside the place is free too", status, "ok")
    check("...and it stays the same location",
          (payload or {}).get("location_id"), BLUFF)
    # (c) the same point WITHOUT the location: now it is wilderness rock.
    park(600.0, 43.5)
    check_true("the location is gone", delete_location(BLUFF))
    res = report(600.0, 46.4)
    status, reason, pos, _loc, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 409)
    check("the reason", reason, "impassable")
    check("the message names the ground", message,
          "You cannot walk there — that is Rock.")
    check("the last valid point comes back", pos, {"x": 600.0, "z": 43.5})
    # And the wilderness rule itself is untouched.
    park(645.0, 38.0)
    res = report(645.0, 42.0)
    status, reason, _pos, _loc, _msg = refusal_of(res)
    check("wilderness rock is still a wall", res[0], "refused")
    check("the reason", reason, "impassable")

    print("\n[21] the ordering pair: a leftover cannot pull the walk back")
    # (a) the baseline — two STAMPED reports out in empty wilderness
    # (x ≈ 800, z ≈ 800: no location, no painted area, flat ground).
    park(800.0, 800.0)
    status, _payload = report(800.0, 801.0, seq=1, t_ms=1000.0)
    check("the first stamped report is accepted", status, "ok")
    status, _payload = report(800.0, 803.0, seq=5, t_ms=2000.0)
    check("the second stamped report is accepted", status, "ok")
    check("the avatar stands where it put it", get_character_pos(AVATAR),
          {"x": 800.0, "z": 803.0})
    # (b) THE LEFTOVER. A point that would pass every gate — 1 m away, grass,
    # wilderness — refused by its ORDER alone (seq 2 <= 5). This is the report
    # that used to become the server's "last valid point" and snap the figure
    # back onto a spot seconds behind it.
    status, late = report(800.0, 802.0, seq=2, t_ms=1200.0)
    check("the call succeeded — 200, not an error", status, "ok")
    check("...but nothing was taken", (late or {}).get("ok"), False)
    check("...and it says why", (late or {}).get("stale"), True)
    check("no correction was sent with it", (late or {}).get("pos"), None)
    check("the baseline point did not move backwards",
          get_character_pos(AVATAR), {"x": 800.0, "z": 803.0})
    # (c) THE STALLED SERVER. The loop was blocked for 3 s: the client walked
    # 20 m and its clock says so (t_ms 2000 → 5000), while the gap between the
    # two handler runs is ≈ 0 — pinned here by setting the server baseline to
    # NOW, so the case measures the rule and not the machine.
    # allowance = max(5, 0 [factor 0], 3 × 3.4 × 3.0) = 30.6 m > 20 m.
    play_route._pos_report_at[AVATAR] = time.monotonic()
    status, _payload = report(820.0, 803.0, seq=6, t_ms=5000.0)
    check("20 m over 3 s of CLIENT time is allowed", status, "ok")
    check("the avatar followed it", get_character_pos(AVATAR),
          {"x": 820.0, "z": 803.0})
    # (d) THE COUNTER-PROBE: identical geometry, identical server clock, but
    # UNSTAMPED. Now elapsed is the server's ≈ 0 and the allowance is the bare
    # 5 m floor — refused. Both halves in one probe: (c) really was the
    # client's clock, and a client without the pair is judged as before.
    park(800.0, 803.0)
    play_route._pos_report_at[AVATAR] = time.monotonic()
    res = report(820.0, 803.0)
    status, reason, pos, _loc, _msg = refusal_of(res)
    check("the same step on the SERVER's clock is refused", res[0], "refused")
    check("the status", status, 409)
    check("the reason", reason, "too_far")
    check("the last valid point comes back", pos, {"x": 800.0, "z": 803.0})
    status, _payload = report(802.0, 803.0)   # 2 m — inside the bare floor
    check("...and an unstamped step inside the floor still passes", status,
          "ok")
    # (e) THE RELOAD. A fresh session restarts its counter at 1; against a
    # baseline of seq 40 every report of it would be "stale" forever. The
    # client clock gives the restart away (90 s → 30 ms is far outside the
    # 15 s leftover window), so the baseline is dropped instead.
    park(800.0, 803.0)
    status, _payload = report(800.0, 804.0, seq=40, t_ms=90000.0)
    check("the old session's last report is accepted", status, "ok")
    status, fresh = report(800.0, 805.0, seq=1, t_ms=30.0)
    check("the reloaded session's first report is not stale", status, "ok")
    check("...it is a real acceptance", (fresh or {}).get("ok"), True)
    check("the avatar followed it", get_character_pos(AVATAR),
          {"x": 800.0, "z": 805.0})

    print("\n[22] one report at a time per avatar — the second is SUPERSEDED")
    import threading
    check("the same avatar always gets the SAME lock",
          play_route._pos_lock(AVATAR) is play_route._pos_lock(AVATAR), True)
    check("another avatar gets its own",
          play_route._pos_lock(AVATAR) is play_route._pos_lock("someone-else"),
          False)
    park(800.0, 805.0)
    held: list = []

    def _report_in_thread():
        held.append(report(800.0, 806.0))

    lock = play_route._pos_lock(AVATAR)
    lock.acquire()
    worker = threading.Thread(target=_report_in_thread, daemon=True)
    worker.start()
    # It must NOT wait: the report finds the lock taken and answers at once.
    worker.join(5.0)
    check("a second report does not wait for the lock", worker.is_alive(), False)
    check("...it answers 200, not an error", held[0][0] if held else None, "ok")
    check("...as a non-acceptance", (held[0][1] if held else {}).get("ok"), False)
    check("...flagged superseded",
          (held[0][1] if held else {}).get("superseded"), True)
    check("nothing was written while the lock was held",
          get_character_pos(AVATAR), {"x": 800.0, "z": 805.0})
    lock.release()
    # The lock is free again: the very next report is an ordinary acceptance,
    # which is what makes the drop harmless — the client retries ≤ 250 ms later.
    status, again = report(800.0, 806.0)
    check("the next report goes through once the lock is free", status, "ok")
    check("...and is a real acceptance", (again or {}).get("ok"), True)
    check("the avatar followed it", get_character_pos(AVATAR),
          {"x": 800.0, "z": 806.0})

    print("\n[23] the baked surfaces are part of the step")
    from app.core import model_surface, relief
    from app.models.world import get_location_by_id
    yard = get_location_by_id(YARD)
    # (a) THE CACHE, on the real reader: YARD has nothing to compose, so the
    # 404 case answers with no lattices at all — and remembers that.
    model_surface.forget_surfaces()
    check("a location without a scene stands on the ground alone",
          round(model_surface.stand_height_at(yard, 1000.0, 1000.0), 3), 0.0)
    check_true("...and the empty answer was cached",
               YARD in model_surface._placed_cache)
    model_surface.forget_surfaces(YARD)
    check_true("...forget_surfaces drops it",
               YARD not in model_surface._placed_cache)

    def lattice(value_cm: int, height_m: float) -> dict:
        """A 5 x 5 lattice of ONE height over a 1 m x 1 m box, in the model's
        own frame: 1 m / 0.25 m + 1 nodes per side, origin on the lower
        corner, values in centimetres above the box floor."""
        return {"step": 0.25, "origin": [-0.5, -0.5], "cols": 5, "rows": 5,
                "values": [value_cm] * 25,
                "box_min": [-0.5, 0.0, -0.5], "box_max": [0.5, height_m, 0.5],
                "extent_snapped": [1.0, height_m, 1.0]}

    def walkable_prop(pid: str, anchor, value_cm: int, height_m: float,
                      level: int = 0) -> dict:
        """One placement spec of the shape ``compose_scene`` ships for a prop
        tagged ``walkable`` — tile-local metres, ``max_m`` 1 so the scale is 1."""
        return {"role": "prop", "id": pid, "room_id": "", "level": level,
                "anchor": list(anchor), "yaw_deg": 0.0, "bottom_y": 0.0,
                "max_m": 1.0, "measure": "xyz", "walkable": True,
                "surface": lattice(value_cm, height_m)}

    yard_specs = [walkable_prop("crate", (0.0, 0.0), 30, 0.3),
                  walkable_prop("block", (10.0, 0.0), 80, 0.8)]
    real_placed = model_surface._placed_specs
    model_surface._placed_specs = lambda loc: (
        yard_specs if str((loc or {}).get("id") or "") == YARD else [])
    try:
        # (b) THE READINGS.
        check("beside the crate: the bare ground",
              round(model_surface.stand_height_at(yard, 999.3, 1000.0), 3), 0.0)
        check("on the crate", round(
            model_surface.stand_height_at(yard, 1000.0, 1000.0), 3), 0.3)
        check("on the block", round(
            model_surface.stand_height_at(yard, 1010.0, 1000.0), 3), 0.8)
        check("no location, no lattice", round(
            model_surface.stand_height_at(None, 1000.0, 1000.0), 3), 0.0)

        # (c) THE LIFT: a ramp of 0.1 m per metre east, datum g(1000) = 0.
        real_ground = relief.ground_at
        relief.ground_at = lambda x, z: (float(x) - 1000.0) * 0.1
        try:
            check("a storey-0 placement rides the ground under its own anchor",
                  round(model_surface.stand_height_at(yard, 1010.0, 1000.0), 3),
                  1.8)
            yard_specs[1]["level"] = 1
            check("...a storey-1 one drops out of the ground ladder, and the "
                  "terrain is the floor",
                  round(model_surface.stand_height_at(yard, 1010.0, 1000.0), 3),
                  1.0)
        finally:
            yard_specs[1]["level"] = 0
            relief.ground_at = real_ground
        # …and the FILTER is what does that, not the arithmetic: on flat ground
        # a storey-1 lattice at bottom_y 3.0 would answer 3.80 and out-rank
        # every terrain there is. The ground ladder never sees it.
        upstairs = walkable_prop("balcony", (5.0, 0.0), 80, 0.8, level=1)
        upstairs["bottom_y"] = 3.0
        yard_specs.append(upstairs)
        try:
            check("a storey-1 lattice does not raise the ground ladder",
                  round(model_surface.stand_height_at(yard, 1005.0, 1000.0), 3),
                  0.0)
        finally:
            yard_specs.pop()

        # (d) CLIMBING THE CRATE — and the report that enters the yard.
        park(999.3, 1000.0)
        status, _payload = report(1000.0, 1000.0)
        check("stepping onto the crate (0.30 m) is allowed", status, "ok")
        check("the avatar stands on it", get_character_pos(AVATAR),
              {"x": 1000.0, "z": 1000.0})

        # (e) THE BLOCK IS A WALL.
        park(1009.3, 1000.0)
        res = report(1010.0, 1000.0)
        status, reason, pos, _loc, message = refusal_of(res)
        check("the block (0.80 m) refuses the step", res[0], "refused")
        check("the status", status, 409)
        check("the reason", reason, "too_steep")
        check("...named as a STEP, not a slope", message,
              "That step is too high to climb.")
        check("the last valid point comes back", pos,
              {"x": 1009.3, "z": 1000.0})

        # (f) AND DOWN AGAIN.
        park(1000.0, 1000.0)
        status, _payload = report(999.3, 1000.0)
        check("climbing back down off the crate is allowed", status, "ok")

        # (g) A BROKEN LATTICE IS NOT A WALL (ruling task 2). The traceback it
        # writes is the point of the ruling but not of this report, so the
        # module's logger is muted and the ONCE-guard is asserted instead.
        def _broken(_loc):
            raise RuntimeError("a malformed surface sidecar")

        model_surface._placed_specs = _broken
        model_surface._read_warned.clear()
        model_surface.logger.setLevel(logging.CRITICAL)
        park(1000.0, 1000.0)
        status, _payload = report(1000.7, 1000.0)
        check("a broken lattice falls back to the ground instead of 500",
              status, "ok")
        check_true("...and it was logged, once per location",
                   model_surface._read_warned == {YARD: True})
        # …and the flag goes when the cache does, or a repaired sidecar would
        # never be worth a traceback again.
        model_surface.forget_surfaces(YARD)
        check_true("forget_surfaces clears the failure flag too",
                   model_surface._read_warned == {})
    finally:
        model_surface.logger.setLevel(logging.NOTSET)
        model_surface._placed_specs = real_placed
        model_surface.forget_surfaces()

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
