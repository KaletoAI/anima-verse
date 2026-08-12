#!/usr/bin/env python3
"""Smoke run for the v2 travel block in the worldmap payload (E3, Task 6).

Checks the ``travel`` block of ``world_ops.build_worldmap_payload`` against
docs/schnittstellen-3d.md § A11 (metre polyline): the block carries
``{target_id, waypoints, progress_m, total_m, eta_game, speed_m_s_real,
pace_m_s_real}`` and NOTHING else — every cell field of v1 (``path``/``seg``/
``frac``/``progress_cells``/``cell_seconds_real``) is gone without
replacement.

Runs against a THROWAWAY storage directory — it never touches a real world.
The journey is written onto the profile BY HAND, so no expectation below
depends on the pathfinder: this is a payload check, not a routing check
(routing is scripts/smoke_journey_v2.py).

The seed:

    location A "Alder Camp"   (0, 0)     10 m footprint  <- known to the avatar
    location B "Birch Hollow" (30, 40)   10 m footprint  <- UNKNOWN, the target

    demo_avatar  in A, known_locations = [A], journey -> B
    npc_walker   in B, journey -> B (same polyline; it is the FOG probe)
    npc_near     in A, journey -> B (VISIBLE under fog — it stands in the
                 known A, so it probes what a fogged payload tells about
                 SOMEONE ELSE's journey)
    npc_idle     in A, movement_target = B but NO journey dict
    npc_slow     in A, journey -> B on the SLOW polyline (see below) — the
                 probe that tells `speed_m_s_real` (nominal) and
                 `pace_m_s_real` (this segment) apart

    server.timezone = Europe/Berlin  (+02:00 in August — so a world-tz stamp
                                      is provably not the UTC one)

The hand-built journey (identical for both travellers):

    waypoints = [[0, 0, 0.0], [30, 0, 30.0], [30, 40, 70.0]]
    speed_m_s = 1.0        started_at_game = 2026-08-09T12:00:00+00:00

    leg 1: (0,0) -> (30,0)   = 30 m, baked at t_cum 30 s
    leg 2: (30,0) -> (30,40) = 40 m, baked at t_cum 70 s
    total                    = 70 m over 70 GAME seconds

The SLOW polyline (npc_slow) — same points, same nominal ``speed_m_s`` 1.0,
but leg 2 runs over soft ground and was baked at HALF the pace (that is what
the terrain ``speed_factor`` does to ``t_cum``, § A1.5):

    waypoints = [[0, 0, 0.0], [30, 0, 30.0], [30, 40, 110.0]]

    leg 1: 30 m in 30 game s  -> 1.0 m per GAME second
    leg 2: 40 m in 80 game s  -> 0.5 m per GAME second

Hand-derived expectations:

  [1] frozen world, game clock standing at start + 35 s
      elapsed 35 s falls into leg 2 (t0 30, t1 70, span 40):
        frac       = (35 − 30) / 40           = 0.125
        progress_m = 30 + 40 × 0.125          = 35.0
        total_m    = 30 + 40                  = 70.0
        eta_game   = 12:00:00 UTC + 70 s      = 12:01:10 UTC
                   = 2026-08-09T14:01:10+02:00 in the world timezone
                     (the HH:MM slice [11:16] a client cuts out = "14:01",
                      i.e. game WALL-CLOCK time, § A11)
        waypoints  = [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]]  — x/z ONLY,
                     the baked t_cum stays server-internal
        speed_m_s_real = null — the clock stands (factor 0), so nothing may
                     be extrapolated
        pace_m_s_real  = null — same reason, same clock

  [2] running world
        factor 2.0 -> speed_m_s_real = 1.0 m/GAME-s × 2 GAME-s/REAL-s
                                     = 2.0 m/REAL-s
        factor 0.5 -> 0.5
      A SPEED multiplies by the factor where v1's DURATION
      (``cell_seconds_real``) divided by it — same clock, inverse quantity.
      ``progress_m`` then only gets a tolerance check: real time passes
      between the anchor and the payload build.

  [2b] the SEGMENT pace (E4) — ``pace_m_s_real`` is the pace of the segment
      the figure is walking RIGHT NOW, straight out of the baked stamps:
        |w[seg+1] − w[seg]| / (t[seg+1] − t[seg]) × factor
      On the fast polyline every segment runs at the nominal 1.0 m/GAME-s,
      so both fields agree — that proves nothing. npc_slow does:
        clock at start + 35 s -> elapsed 35 falls into leg 2
                                 (t0 30, t1 110, span 80)
        frac       = (35 − 30) / 80          = 0.0625
        progress_m = 30 + 40 × 0.0625        = 32.5
        pace       = 40 m / 80 game s        = 0.5 m/GAME-s
        factor 2.0 -> pace_m_s_real  = 1.0   (0.5 × 2)
                      speed_m_s_real = 2.0   (nominal 1.0 × 2, unchanged)
      Its FIRST leg is the nominal one: at start + 10 s the two agree again
      (pace 30 m / 30 s = 1.0 m/GAME-s -> 2.0 at factor 2).

  [2c] ``pace_m_s_real`` is null wherever an extrapolation would be a lie:
      frozen clock (see [1]) and after the arrival — a journey walked past
      its end has no current segment. ``speed_m_s_real`` stays filled there
      (it is the journey's nominal pace, not a statement about a segment).

  [3] a movement target alone is NOT a journey
        npc_idle carries movement_target = B but no journey dict
          -> travel is null, movement_target_id is still B

  [4] a journey walked past its end (clock at start + 200 s, still frozen)
        progress_m = total_m = 70.0, and the block stays until the ticker
        settles the arrival ("field gone" is the arrival signal, § A11)

  [5] fog (§ A12) holds for travellers too
        fogged view : npc_walker stands in the unknown B -> gone entirely,
                      travelling or not; the avatar sees its OWN block
        the avatar's movement_target_name stays "" (B is unknown) while
        travel.target_id names the id — exactly like movement_target_id,
        which fog never hid either
        admin view  : npc_walker is back, with the same travel block

  [6] fog does not hand out the ROUTE of SOMEONE ELSE — nor the numbers it
      could be reconstructed from (E6)
        The polyline ends at the target's opening — metre-exact map markers
        for a place the avatar may not know (a far worse leak than the
        opaque target_id, which fog never hid either). The walked distance,
        the total length, the arrival time and the two paces say the same
        thing indirectly: position + remaining distance + heading is a
        target. So in a FOGGED payload a foreign traveller keeps its ROW and
        its ``target_id``, and everything else in the block is null:
          fogged, npc_near (visible, travelling) -> waypoints, progress_m,
                    total_m, eta_game, speed_m_s_real, pace_m_s_real ALL
                    null; target_id still B; the keys all stay (so "not
                    told" stays distinguishable from "empty")
          fogged, demo_avatar (itself)           -> the full block
          show_all, npc_near                     -> the full block

Usage:  ./.venv/bin/python scripts/smoke_worldmap_travel.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-travel-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="worldmap-travel-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import config  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_profile, save_character_profile, set_known_locations,
    set_movement_target)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, set_world_frozen,
    update_location_position)

FAILURES = []
CHECKED = 0

START_ISO = "2026-08-09T12:00:00+00:00"
START_DT = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
WAYPOINTS = [[0.0, 0.0, 0.0], [30.0, 0.0, 30.0], [30.0, 40.0, 70.0]]
# Same points, same nominal speed — leg 2 baked at half the pace (soft ground).
SLOW_WAYPOINTS = [[0.0, 0.0, 0.0], [30.0, 0.0, 30.0], [30.0, 40.0, 110.0]]
SPEED = 1.0
# Exactly the fields § A11 lists — no more, no less.
FIELDS = {"target_id", "waypoints", "progress_m", "total_m", "eta_game",
          "speed_m_s_real", "pace_m_s_real"}
# The v1 cell vocabulary, dropped without replacement.
V1_FIELDS = ("path", "seg", "frac", "progress_cells", "cell_seconds_real")


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def approx(label: str, actual, expected, tol: float) -> None:
    global CHECKED
    CHECKED += 1
    ok = isinstance(actual, (int, float)) and abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected ≈{expected!r} (tol {tol})"))
    if not ok:
        FAILURES.append(label)


def place(name: str, x: float, z: float) -> str:
    """A location placed at a world-METRE point with a 10 m footprint edge."""
    loc = add_location(name=name, description=f"{name} for the travel smoke.")
    loc_id = loc["id"]
    update_location_position(loc_id, x, z)
    data = _load_world_data()
    for entry in data.get("locations", []):
        if entry.get("id") == loc_id:
            entry["map3d"] = {**(entry.get("map3d") or {}),
                              "plan_width_m": 10.0}
    _save_world_data(data)
    return loc_id


def seed_character(name: str, location_id: str) -> None:
    save_character_profile(name, {"current_location": location_id},
                           create_new=True)


def give_journey(name: str, target: str, waypoints=None) -> None:
    """Write journey + movement target in ONE profile save — the two live and
    die together, and a mismatch would make ``get_journey`` call it stale."""
    prof = get_character_profile(name)
    prof["journey"] = {"target": target,
                       "waypoints": [list(w) for w in (waypoints or WAYPOINTS)],
                       "started_at_game": START_ISO, "speed_m_s": SPEED,
                       "entry_edge": ""}
    prof["movement_target"] = target
    save_character_profile(name, prof)


def freeze_at(seconds: float) -> None:
    """Stand the game clock still at START + ``seconds``. Freeze FIRST: the
    freeze hook re-anchors, so a time set afterwards is the one that stays."""
    set_world_frozen(True)
    set_game_time(START_DT + timedelta(seconds=seconds))


def char(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


def names(payload) -> list:
    return sorted(c["name"] for c in payload["characters"])


# The world clock has an offset of its own — a UTC stamp would pass a
# same-instant check while breaking every client that slices HH:MM out.
config._CONFIG.setdefault("server", {})["timezone"] = "Europe/Berlin"

A = place("Alder Camp", 0.0, 0.0)
B = place("Birch Hollow", 30.0, 40.0)

seed_character("demo_avatar", A)
seed_character("npc_walker", B)
seed_character("npc_near", A)
seed_character("npc_idle", A)
seed_character("npc_slow", A)
set_known_locations("demo_avatar", [A])
give_journey("demo_avatar", B)
give_journey("npc_walker", B)
give_journey("npc_near", B)
give_journey("npc_slow", B, waypoints=SLOW_WAYPOINTS)
set_movement_target("npc_idle", B)


def main() -> int:
    print("\n[1] a running journey on a FROZEN clock — field for field")
    freeze_at(35.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    tr = char(allv, "demo_avatar").get("travel")
    check("the block exists", isinstance(tr, dict), True)
    tr = tr or {}
    check("exactly the § A11 fields", sorted(tr), sorted(FIELDS))
    for f in V1_FIELDS:
        check(f"no v1 cell field {f!r}", f in tr, False)
    check("target_id", tr.get("target_id"), B)
    check("waypoints (x/z only, no t_cum)", tr.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("progress_m = 30 + 40 × 0.125", tr.get("progress_m"), 35.0)
    check("total_m = 30 + 40", tr.get("total_m"), 70.0)
    check("eta_game in world time", tr.get("eta_game"),
          "2026-08-09T14:01:10+02:00")
    check("… the HH:MM a client slices out", (tr.get("eta_game") or "")[11:16],
          "14:01")
    check("speed_m_s_real is null while frozen", tr.get("speed_m_s_real"), None)
    check("pace_m_s_real is null while frozen", tr.get("pace_m_s_real"), None)

    print("\n[2] a running clock — the real-seconds pace")
    for factor, expected in ((2.0, 2.0), (0.5, 0.5)):
        set_world_frozen(False)
        set_game_factor(factor)
        run = build_worldmap_payload("demo_avatar", show_all=True)
        rtr = char(run, "demo_avatar").get("travel") or {}
        check(f"factor {factor} → speed_m_s_real", rtr.get("speed_m_s_real"),
              expected)
        approx(f"factor {factor} → progress_m still ≈35 m",
               rtr.get("progress_m"), 35.0, 2.0)
        check(f"factor {factor} → pace_m_s_real (this leg IS the nominal one)",
              rtr.get("pace_m_s_real"), expected)

    print("\n[2b] the segment pace tells a slow leg from the nominal speed")
    freeze_at(35.0)
    set_world_frozen(False)
    set_game_factor(2.0)
    slow = char(build_worldmap_payload("demo_avatar", show_all=True),
                "npc_slow").get("travel") or {}
    approx("progress_m = 30 + 40 × 0.0625", slow.get("progress_m"), 32.5, 2.0)
    check("speed_m_s_real stays the NOMINAL 1.0 × 2", slow.get("speed_m_s_real"),
          2.0)
    check("pace_m_s_real = 40 m / 80 game s × 2", slow.get("pace_m_s_real"), 1.0)
    freeze_at(10.0)
    set_world_frozen(False)
    set_game_factor(2.0)
    fast_leg = char(build_worldmap_payload("demo_avatar", show_all=True),
                    "npc_slow").get("travel") or {}
    check("on ITS first leg the two agree again (30 m / 30 s × 2)",
          fast_leg.get("pace_m_s_real"), 2.0)

    print("\n[2c] past the end there is no current segment any more")
    freeze_at(200.0)
    set_world_frozen(False)
    set_game_factor(1.0)
    done = char(build_worldmap_payload("demo_avatar", show_all=True),
                "demo_avatar").get("travel") or {}
    check("pace_m_s_real is null after the arrival", done.get("pace_m_s_real"),
          None)
    check("… while speed_m_s_real (nominal) still stands",
          done.get("speed_m_s_real"), 1.0)

    print("\n[3] a movement target alone is no journey")
    freeze_at(35.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    idle = char(allv, "npc_idle")
    check("npc_idle.travel", idle.get("travel"), None)
    check("… but the target is still reported",
          idle.get("movement_target_id"), B)

    print("\n[4] past the end the block stands until the ticker settles it")
    freeze_at(200.0)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    tr = char(allv, "demo_avatar").get("travel") or {}
    check("progress_m = total_m", (tr.get("progress_m"), tr.get("total_m")),
          (70.0, 70.0))
    check("eta_game unchanged", tr.get("eta_game"),
          "2026-08-09T14:01:10+02:00")

    print("\n[5] fog holds for travellers too")
    freeze_at(35.0)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("a traveller in an unknown place is gone", names(fog),
          ["demo_avatar", "npc_idle", "npc_near", "npc_slow"])
    ftr = char(fog, "demo_avatar").get("travel") or {}
    check("the avatar sees its own journey", ftr.get("target_id"), B)
    check("… the destination stays nameless",
          char(fog, "demo_avatar").get("movement_target_name"), "")
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    check("admin view has the traveller back", names(allv),
          ["demo_avatar", "npc_idle", "npc_near", "npc_slow", "npc_walker"])
    check("… with the same block",
          (char(allv, "npc_walker").get("travel") or {}).get("progress_m"),
          35.0)

    print("\n[6] fog withholds the ROUTE of everyone but the avatar — and "
          "every number it could be rebuilt from")
    freeze_at(35.0)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    near = char(fog, "npc_near").get("travel") or {}
    check("someone else's waypoints are withheld", near.get("waypoints"), None)
    check("… and the five numbers with them",
          [f for f in ("progress_m", "total_m", "eta_game", "speed_m_s_real",
                       "pace_m_s_real") if near.get(f) is not None], [])
    check("… the opaque target_id stays", near.get("target_id"), B)
    check("… and every key is there, only null", sorted(near), sorted(FIELDS))
    own = char(fog, "demo_avatar").get("travel") or {}
    check("the avatar keeps its own route", own.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("… and its own numbers",
          (own.get("progress_m"), own.get("total_m")), (35.0, 70.0))
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    other = char(allv, "npc_near").get("travel") or {}
    check("the admin view hides no route", other.get("waypoints"),
          [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0]])
    check("… and thins no number",
          (other.get("progress_m"), other.get("total_m")), (35.0, 70.0))

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
