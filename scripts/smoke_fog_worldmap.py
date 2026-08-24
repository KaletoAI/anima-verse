#!/usr/bin/env python3
"""Smoke run for the fog-of-war worldmap payload (Etappe 5, Task 1).

Checks the contract of ``world_ops.build_worldmap_payload`` (docs/
schnittstellen-3d.md § A12): by default the payload shows only what the active
avatar knows, ``show_all=True`` (admin) shows everything, and ``world_bounds``
is computed BEFORE the fog filter so the map keeps its extent either way.

Runs against a THROWAWAY storage directory — it never touches a real world.

The seed (hand-built, so every expectation below is derived from it and not
recorded from an implementation run). Positions are world METRES since the
grid was retired (Seamless World, E1); every placed location is a 10 m square
centred on its point:

    location A "Alder Camp"   (0, 0)     <- the avatar knows this one
    location B "Birch Hollow" (20, 0)
    location C "Cedar Ridge"  (50, 30)
    location D "Dusk Template" UNPLACED  <- template placeholder

    demo_avatar  at A, known_locations = [A]
    npc_a        at A, movement_target = C
    npc_b        at B

    danger event at A, disruption event at B, danger event at C

Hand-derived expectations:

  fogged view (avatar "demo_avatar", show_all=False)
    locations           -> A (known) + D (unplaced, always passes) = 2 entries
    characters          -> demo_avatar (always itself) + npc_a (in A) = 2;
                           npc_b is at the unknown B and drops out
    npc_a.movement_target_id   -> C's id (the target itself is NOT hidden)
    npc_a.movement_target_name -> "" (C is unknown, so it stays nameless)
    events_by_location  -> only the key of A (B and C are unknown)
    world_bounds        -> over ALL placed footprints (centre ± half of
                           a drawn 10 m square = ± 5): A stretches min_x/min_z to
                           0-5 = -5, C stretches max_x to 50+5 = 55 and max_z
                           to 30+5 = 35
                           -> {"min_x": -5.0, "min_z": -5.0,
                               "max_x": 55.0, "max_z": 35.0};
                           unfiltered, so C still stretches it although the
                           avatar cannot see C
    fogged              -> True

  admin view (show_all=True)
    locations           -> A + B + C + D = 4 entries
    characters          -> 3
    npc_a.movement_target_name -> "Cedar Ridge"
    events_by_location  -> 3 keys
    world_bounds        -> unchanged {-5, -5, 55, 35}
    fogged              -> False

  off-map sleeper (§ A1.4) — npc_b goes to its off-map sleeping quarters
    npc_b stands in B, so save_character_current_location has put its point
    at B's centre (20, 0). enter_offmap_sleep clears the location AND that
    point; the payload rule is "no location + a point = wilderness", so a
    sleeper that kept its point would be emitted as a character standing in
    the open field — visible in the admin view, and visible to itself under
    fog if it were the avatar. Hence:
      pos after enter_offmap_sleep -> None
      admin view (show_all=True)   -> characters 2 (demo_avatar, npc_a),
                                      npc_b gone
      fogged view                  -> characters 2 (unchanged: npc_b was at
                                      the unknown B and already invisible)
    After wake_from_offmap the character is back at its return location AND
    at that location's centre — a location without a point has no place on
    the map:
      pos   -> {"x": 20.0, "z": 0.0}  (B's centre)
      admin view -> characters 3 again, npc_b at B

  wilderness under fog (E6) — seeded only for the sections [5]…[7] below, so
  every expectation above still counts the three characters it was written
  for:

    demo_avatar gets its own point at A's centre (0, 0) — the seed writes the
                profile directly, so it had none; the sight range measures
                from THIS point. It also gets a journey of its own, to check
                that the fog never thins the AVATAR's block.
    npc_open    location-less at (30, 0)  -> 30 m from the avatar
    npc_trav    location-less at (100, 0) -> 100 m from the avatar, WITH a
                journey (target C, a 4000 m polyline started at the current
                game time — a canonical world-calendar stamp — so it is still
                on its first leg)
    game.discovery_range_m = 50 m (the sight range, § A12; the same number
                that discovers places by coming close)

  [5] a stranger in the open is visible exactly within the sight range
        range 50 -> hypot((30,0) − (0,0)) = 30 <= 50   -> npc_open is there
        range 10 -> 30 > 10                            -> npc_open is gone
        range  0 -> sight off                          -> npc_open is gone
        show_all -> the admin sees it at every range   -> npc_open is there

  [6] a fogged traveller keeps its ROW but tells nothing about its route
        npc_trav is 100 m away, far outside every sight range used here, and
        stays on the map all the same: a journey runs through the wilderness
        for most of its length, and a figure that blinks out for the whole
        trip is what § A11 warns against. What goes is everything the route
        could be RECONSTRUCTED from — waypoints, progress_m, total_m,
        eta_game, eta_hhmm, eta_label, speed_m_s_real, pace_m_s_real are ALL
        null, while the opaque target_id and the character's own pos stay:
          fogged, npc_trav      -> the seven fields + waypoints null,
                                   target_id = C, pos = {"x": 100, "z": 0}
          fogged, demo_avatar   -> its own block is FULL (waypoints and all
                                   seven fields present)
          show_all, npc_trav    -> full block, nothing thinned

  [7] no avatar (avatar None, show_all=False) — deliberately the LAST of the
      wilderness cases, because it is only worth anything WITH that seed in
      place: a logged-in user without an active character gets this view
      (routes/play.py hands over ""), and it must know nothing at all.
        locations   -> [D] only (nothing is known, unplaced still passes)
        characters  -> [] — and that includes npc_open (no avatar point, so
                       no sight line) AND npc_trav: the traveller exception
                       of [6] needs an avatar to be an exception FROM. On a
                       map without a single visible location a traveller must
                       not be the one thing that shines through.

  [8] THE VEIL HIDES FIGURES (plan-fog-schleier-v2.md § 2) — seeded at the
      start of the section, so every count above still stands. The 3D client
      hazes over every 64 m cell the avatar has not explored
      (`app/core/exploration.py`, cell (cx,cz) = [cx·64,(cx+1)·64) on both
      axes), and a figure standing there must not reach the player payload at
      all — a crisp figure on hazed ground is the leak the haze prevents.

        E "Elder Wood" at (600, 600), an 800 m square (corners ±400, so it
          spans 200…1000 on both axes) — big enough that one can stand INSIDE
          it and outside the avatar's own cells at the same time, which is
          what [8c] needs
        G "Grey Tor" at (900, 100), the usual 10 m square
        both ADDED to the avatar's known_locations, so the location gate lets
        them through and what is measured is the veil alone.

        npc_g in G at (900, 100)  -> cell (floor(900/64), floor(100/64))
                                     = (14, 1)
        npc_e in E at (950, 950)  -> cell (14, 14), and inside E's footprint
                                     (950 < 1000) — the POINT is the truth and
                                     the location is derived from it, so this
                                     is asserted, not assumed

      The avatar's own memory is empty at this point (nothing in this smoke
      writes a position through POST /play/pos or the travel ticker), so what
      it has "seen" is its NEAR VIEW alone: the 3×3 block around its own cell
      (`seen_cells`). Standing at A's centre (0, 0) that is cell (0,0) ± 1,
      i.e. cx and cz each in {-1, 0, 1} — world [-64, 128) on both axes.

    [8a] avatar at A (0, 0), memory empty
           npc_g's cell (14, 1) is outside {-1,0,1}² -> UNDER THE VEIL
           fogged view  -> npc_g gone, demo_avatar still there
           admin view   -> npc_g there (nothing is filtered)
           locations    -> A, D, E, G all still listed: a KNOWN place stays
                           visible, it is the FIGURE on unseen ground that goes
           explored_sig -> "0" (the memory is empty, the near view is not
                           written to the table)

    [8b] the avatar remembers G's ground: mark_explored(demo_avatar, 900, 100)
         writes the 3×3 around (14, 1) = 9 rows (cx 13…15, cz 0…2)
           explored_sig -> "9"
           fogged view  -> npc_g is back, npc_e still not: its cell (14, 14)
                           is in neither the memory (cz 0…2) nor the near view

    [8c] SAME LOCATION is the exception, and the PAIR is what proves it is the
         location rather than the position — npc_e never moves, only the
         avatar does:
           avatar to E's centre (600, 600) -> cell (9, 9), near view {8,9,10}²,
             which does not contain (14, 14) either. npc_e is in the payload
             all the same, because it stands in the avatar's OWN location.
           avatar back to G's centre (900, 100) -> it has left Elder Wood, the
             exception is gone with it, and npc_e drops out again.
           demo_avatar itself -> always there, in every one of the three.

Usage:  ./.venv/bin/python scripts/smoke_fog_worldmap.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="fog-worldmap-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="fog-worldmap-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import config  # noqa: E402
from app.core.exploration import mark_explored  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models.character import (  # noqa: E402
    enter_offmap_sleep, get_character_current_location, get_character_pos,
    get_character_profile, save_character_profile, set_character_pos,
    set_known_locations, set_movement_target, wake_from_offmap)
from app.models.events import add_event  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def place(name: str, pos, half: float = 5.0) -> str:
    """Add a location, optionally placed at a world-METRE point with a square
    footprint of edge ``2·half`` (the scale anchor a placed location needs).

    ``half`` is 5 for every location of sections [1]…[7] — the 10 m square the
    docstring's world_bounds are derived from. Section [8] needs ONE location
    big enough that a character can stand inside it and outside the avatar's
    64 m cells at the same time, and that is the only reason the size is an
    argument at all."""
    loc = add_location(name=name, description=f"{name} for the fog smoke.")
    loc_id = loc["id"]
    if pos is not None:
        update_location_position(loc_id, pos[0], pos[1])
        data = _load_world_data()
        for entry in data.get("locations", []):
            if entry.get("id") == loc_id:
                # The DRAWN centred square (contract v6): since 2026-08-19 a
                # width alone is no area, so the fixture says its outline.
                entry["map3d"] = {**(entry.get("map3d") or {}),
                                  "plan_width_m": half * 2,
                                  "boundary": [[-half, -half], [half, -half],
                                               [half, half], [-half, half]]}
        _save_world_data(data)
    return loc_id


def seed_character(name: str, location_id: str) -> None:
    save_character_profile(name, {"current_location": location_id},
                           create_new=True)


A = place("Alder Camp", (0.0, 0.0))
B = place("Birch Hollow", (20.0, 0.0))
C = place("Cedar Ridge", (50.0, 30.0))
D = place("Dusk Template", None)

seed_character("demo_avatar", A)
seed_character("npc_a", A)
seed_character("npc_b", B)
set_known_locations("demo_avatar", [A])
set_movement_target("npc_a", C)

add_event("A rockslide blocks the path.", location_id=A, category="danger")
add_event("The well ran dry.", location_id=B, category="disruption")
add_event("Wolves circle the ridge.", location_id=C, category="danger")

BOUNDS = {"min_x": -5.0, "min_z": -5.0, "max_x": 55.0, "max_z": 35.0}


def ids(payload) -> list:
    return sorted(e["id"] for e in payload["locations"])


def names(payload) -> list:
    return sorted(c["name"] for c in payload["characters"])


def char(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


# The seven travel numbers the fog withholds from a foreign traveller
# (§ A11). The arrival is three of them: the canonical game stamp plus the
# two ready-made display strings the server computes beside it.
THIN_FIELDS = ("progress_m", "total_m", "eta_game", "eta_hhmm", "eta_label",
               "speed_m_s_real", "pace_m_s_real")


def sight_range(metres: float) -> None:
    """Set the world's sight range — the ONE 'how far do I see outdoors'
    number (§ A12), read fresh on every payload build."""
    config._CONFIG.setdefault("game", {})["discovery_range_m"] = metres


def put_in_the_open(name: str, x: float, z: float) -> None:
    """A character standing OUTSIDE every footprint: the point is the truth,
    the location is derived from it (and stays empty out there)."""
    save_character_profile(name, {"current_location": ""}, create_new=True)
    set_character_pos(name, x, z)


def give_journey(name: str, target: str, start_x: float) -> None:
    """A long journey starting NOW, written by hand — this is a payload check,
    not a routing check. 4000 m at 1 m per GAME second keeps the traveller on
    its first leg for the whole run."""
    prof = get_character_profile(name)
    prof["journey"] = {
        "target": target,
        "waypoints": [[start_x, 0.0, 0.0], [start_x + 4000.0, 0.0, 4000.0]],
        "started_at_game": game_time().canonical(),
        "speed_m_s": 1.0,
        "entry_edge": "",
    }
    prof["movement_target"] = target
    save_character_profile(name, prof)


def main() -> int:
    print("\n[1] fogged view — the avatar knows only A")
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("locations", ids(fog), sorted([A, D]))
    check("characters", names(fog), ["demo_avatar", "npc_a"])
    check("npc_a.movement_target_id", char(fog, "npc_a").get("movement_target_id"), C)
    check("npc_a.movement_target_name", char(fog, "npc_a").get("movement_target_name"), "")
    check("events_by_location keys", sorted(fog["events_by_location"]), [A])
    check("world_bounds (unfiltered)", fog.get("world_bounds"), BOUNDS)
    check("fogged", fog.get("fogged"), True)
    check("avatar", fog.get("avatar"), "demo_avatar")
    check("current_location_id", fog.get("current_location_id"), A)

    print("\n[2] admin view — all=1 lifts the fog")
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    check("locations", ids(allv), sorted([A, B, C, D]))
    check("characters", names(allv), ["demo_avatar", "npc_a", "npc_b"])
    check("npc_a.movement_target_name", char(allv, "npc_a").get("movement_target_name"),
          "Cedar Ridge")
    check("events_by_location keys", sorted(allv["events_by_location"]), sorted([A, B, C]))
    check("world_bounds (unchanged)", allv.get("world_bounds"), BOUNDS)
    check("fogged", allv.get("fogged"), False)

    print("\n[3] off-map sleeper is on NO map — neither fogged nor show_all")
    # Give npc_b the point every character standing in a location has (the
    # location setter syncs it; this seed wrote the profile directly).
    set_character_pos("npc_b", 20.0, 0.0)
    check("npc_b at B's centre", get_character_pos("npc_b"), {"x": 20.0, "z": 0.0})
    check("npc_b location", get_character_current_location("npc_b"), B)

    check("enter_offmap_sleep", enter_offmap_sleep("npc_b"), True)
    # The payload reads "no location + a point" as wilderness — so the point
    # has to go with the location, or the sleeper stands in the open field.
    check("pos cleared", get_character_pos("npc_b"), None)
    check("location cleared", get_character_current_location("npc_b"), "")
    check("admin view drops the sleeper",
          names(build_worldmap_payload("demo_avatar", show_all=True)),
          ["demo_avatar", "npc_a"])
    check("fogged view drops the sleeper",
          names(build_worldmap_payload("demo_avatar", show_all=False)),
          ["demo_avatar", "npc_a"])

    print("\n[4] waking puts the sleeper back — location AND centre point")
    check("wake_from_offmap", wake_from_offmap("npc_b"), True)
    check("location restored", get_character_current_location("npc_b"), B)
    check("pos = B's centre", get_character_pos("npc_b"), {"x": 20.0, "z": 0.0})
    check("admin view has it back",
          names(build_worldmap_payload("demo_avatar", show_all=True)),
          ["demo_avatar", "npc_a", "npc_b"])

    # step-walk + neighbour discovery retired with the grid (E1); free
    # movement lands in E3/E4

    # --- E6: the wilderness seed (see the docstring) ---------------------
    set_character_pos("demo_avatar", 0.0, 0.0)
    put_in_the_open("npc_open", 30.0, 0.0)
    put_in_the_open("npc_trav", 100.0, 0.0)
    give_journey("npc_trav", C, 100.0)
    give_journey("demo_avatar", C, 0.0)

    print("\n[5] out in the open a stranger is visible within the sight range")
    sight_range(50.0)
    check("30 m away, range 50 → visible",
          "npc_open" in names(build_worldmap_payload("demo_avatar")), True)
    sight_range(10.0)
    check("30 m away, range 10 → gone",
          "npc_open" in names(build_worldmap_payload("demo_avatar")), False)
    sight_range(0.0)
    check("sight switched off → gone",
          "npc_open" in names(build_worldmap_payload("demo_avatar")), False)
    check("the admin sees it at every range",
          "npc_open" in names(build_worldmap_payload("demo_avatar",
                                                     show_all=True)), True)

    print("\n[6] a fogged traveller keeps its row and tells nothing more")
    sight_range(50.0)          # npc_trav is 100 m away — outside it
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    trav = char(fog, "npc_trav")
    check("the traveller is on the map", trav.get("name"), "npc_trav")
    check("… at its own point", trav.get("pos"), {"x": 100.0, "z": 0.0})
    tr = trav.get("travel") or {}
    check("… the route is withheld", tr.get("waypoints"), None)
    for f in THIN_FIELDS:
        check(f"… {f} is null", tr.get(f), None)
    check("… the opaque target_id stays", tr.get("target_id"), C)
    own = char(fog, "demo_avatar").get("travel") or {}
    check("the avatar's OWN block is full",
          [f for f in THIN_FIELDS if own.get(f) is None]
          + ([] if own.get("waypoints") else ["waypoints"]), [])
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    atr = char(allv, "npc_trav").get("travel") or {}
    check("the admin view thins nothing",
          [f for f in THIN_FIELDS if atr.get(f) is None]
          + ([] if atr.get("waypoints") else ["waypoints"]), [])

    print("\n[7] no avatar — that view knows nothing at all, traveller or not")
    sight_range(50.0)
    none = build_worldmap_payload(None, show_all=False)
    check("locations", ids(none), [D])
    check("characters", none["characters"], [])
    check("… the stranger in the open is not among them",
          "npc_open" in names(none), False)
    check("… and neither is the TRAVELLER (no avatar, no exception)",
          "npc_trav" in names(none), False)
    check("events_by_location", none["events_by_location"], {})
    check("world_bounds (still unfiltered)", none.get("world_bounds"), BOUNDS)
    check("fogged", none.get("fogged"), True)

    print("\n[8] the veil hides FIGURES on ground the avatar has not seen")
    E = place("Elder Wood", (600.0, 600.0), half=400.0)
    G = place("Grey Tor", (900.0, 100.0))
    set_known_locations("demo_avatar", [A, E, G])
    seed_character("npc_g", G)
    set_character_pos("npc_g", 900.0, 100.0)
    seed_character("npc_e", E)
    set_character_pos("npc_e", 950.0, 950.0)
    # The POINT is the truth and the location is derived from it: this is what
    # makes the pair of [8c] a pair at all, so it is asserted rather than
    # assumed.
    check("npc_e stands inside the 800 m Elder Wood",
          get_character_current_location("npc_e"), E)

    print("  [8a] the memory is empty — only the avatar's own near view counts")
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("explored_sig", fog.get("explored_sig"), "0")
    check("locations (a KNOWN place stays visible)",
          ids(fog), sorted([A, D, E, G]))
    check("npc_g stands in cell (14,1) → under the veil",
          "npc_g" in names(fog), False)
    check("the avatar is there all the same", "demo_avatar" in names(fog), True)
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    check("the admin view filters nothing", "npc_g" in names(allv), True)

    print("  [8b] the avatar remembers that ground — the figure comes back")
    mark_explored("demo_avatar", 900.0, 100.0)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("explored_sig (the 3×3 block around (14,1))",
          fog.get("explored_sig"), "9")
    check("npc_g is on the map", "npc_g" in names(fog), True)
    check("npc_e is not — cell (14,14) is neither remembered nor near",
          "npc_e" in names(fog), False)

    print("  [8c] …and standing in the avatar's OWN location is the exception")
    set_character_pos("demo_avatar", 600.0, 600.0)   # into Elder Wood
    check("the avatar is in Elder Wood now",
          get_character_current_location("demo_avatar"), E)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("npc_e shares the avatar's location → stays, unseen ground and all",
          "npc_e" in names(fog), True)
    check("the avatar itself, always", "demo_avatar" in names(fog), True)
    set_character_pos("demo_avatar", 900.0, 100.0)   # back out, into Grey Tor
    check("the avatar has left Elder Wood",
          get_character_current_location("demo_avatar"), G)
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("nothing changed but the avatar's own place → npc_e gone again",
          "npc_e" in names(fog), False)

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
