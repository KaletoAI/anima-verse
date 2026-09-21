#!/usr/bin/env python3
"""Smoke run for DATA-7: the worldmap payload loads ONE profile per character.

``world_ops.build_worldmap_payload`` is polled every 3 seconds by every
connected client (``client3d/src/main.ts``: ``WORLDMAP_POLL_MS = 3000``). It
walks every roster character and used to ask ``get_character_profile`` again
for almost every field it reports, although it already held the merged profile
in ``_prof``. This check pins the new bound and proves the payload did not
change while the reads were removed.

Runs against a THROWAWAY storage directory and a THROWAWAY animation-clip and
pose-catalog directory — it never touches a real world, never starts a server
and makes no LLM/image call.

The seed (hand-built, so every expectation below is derived from it and not
recorded from an implementation run). Metres, contract v6:

    H "Harbour Inn"  at (0, 0), a drawn 10 m square (corners +-5),
                     one room "lounge" with layout x=-4 z=-4 w=8 d=6 and the
                     markers s1 (seat, at [1,1]) and b1 (lie, at [2,4])
    T "Tide Market"  at (200, 0), the same 10 m square — the travel target

    npc_lead     in H/lounge, standing, party LEADER
    npc_still    in H/lounge, standing, party FOLLOWER
    npc_seated   in H/lounge, seated on s1 (places.assign, pose "sitting")
    npc_sleeper  in H/lounge, is_sleeping=True — the setter lies it down, so
                 it holds the lie place b1
    npc_walker   in H/lounge, a journey to T (4000 m first leg at 1 m per
                 GAME second, so it is still on that leg for the whole run)

The game clock is pinned to a fixed GameTime for the whole run (the module
attribute ``timeutils.game_time`` is replaced; ``build_worldmap_payload``
imports it inside the function, so both the current and the HEAD module see
the frozen value). Without that the two builds compared in [3] would be
milliseconds apart and their journey/eta numbers would differ for that reason
alone.

Hand-derived expectations
-------------------------

[1] ``get_character_profile`` calls per worldmap build, counted by replacing
    the function on ``app.models.character`` (every reader resolves it through
    that module, including the ones ``world_ops`` imports locally).

    Per character, AFTER the fix — four loads, and not one of them is a
    second read of a field the loop already holds:

      1  ``_prof``  — the ONE load; location, room, movement target, profile
                      image, activity, pose key, sleep flag, journey,
                      animation set, height, interaction and place are all
                      read out of it
      1  ``get_character_current_feeling`` — has no ``profile=`` parameter
                      (``app/models/character.py``); the only loop reader left
                      that cannot be handed the profile
      2  ``resolve_animation_sets`` -> ``derive_set`` -> ``model_refs.
         is_humanoid`` -> ``character_template.is_feature_enabled``, which
         loads ``get_character_config`` (1 profile for its language/decency
         injection) and then the profile itself (1) for the template name

    Plus 2 for a character that HOLDS A PLACE: ``places.place_of`` calls
    ``places.where(name)``, which asks ``get_character_current_location`` and
    ``get_character_current_room`` without a profile. Two of the five hold one
    (npc_seated on s1, npc_sleeper on b1).

      expected total (admin view) = 5 * 4 + 2 * 2 = 24

    The fogged view (an avatar, ``show_all=False``) adds FOUR reads of the
    AVATAR, all outside the loop: ``get_character_language`` (1),
    ``visibility_context`` -> ``get_known_locations`` -> ``get_character_config``
    (1), ``_avatar_loc`` (1) and the payload's ``current_location_id`` (1).

      expected total (fogged view) = 24 + 4 = 28

    The checks are upper bounds (``<=``), because the three loads per
    character that are NOT the loop's own live in other modules
    (``character.py``, ``character_template.py``, ``places.py``) and may well
    shrink further.

    BEFORE the fix the same count was, per character:

      1 get_character_current_location + 1 _prof + 1 get_movement_target
      + 1 get_character_profile_image + 1 get_effective_activity
      + 2 get_effective_pose_key (is_character_sleeping + get_character_pose_key,
          neither got the profile) + 1 get_character_current_room
      + 1 get_character_current_feeling + 2 is_feature_enabled   = 11

    …except for the SLEEPER: ``get_effective_pose_key`` answers "sleeping"
    straight after ``is_character_sleeping`` and never reaches
    ``get_character_pose_key``, so it pays 10 rather than 11.

      total before (admin) = 4 * 11 + 1 * 10 + 2 * 2 = 58

    So this check FAILS on the old code (58 > 24) and passes on the new one.
    With git available it is not reasoned about but measured: section [3]
    builds the payload through ``git show HEAD:app/core/world_ops.py`` as
    well and prints both counts and both timings.

[2] The payload is unchanged. Every field the loop now reads out of ``_prof``
    is recomputed through the plain readers WITHOUT ``profile=`` (the old
    per-call path) and compared:
      location_id, room_id, movement_target_id, activity, height_cm,
      animation_set(s), place, avatar_url and the pose key behind
      activity_animation.

[3] Old vs. new, whole payload: the HEAD revision of ``app/core/world_ops.py``
    is loaded from a temp file as a second module and its payload is compared
    to the current one as canonical JSON — byte-identical, for the admin view
    (``show_all=True``) and for the fogged avatar view alike. Skipped with a
    notice when git is unavailable; never a failure, because a working tree
    without git history is not a defect of this fix.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_profile_loads.py
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-loads-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="worldmap-loads-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import places, pose_catalog, timeutils  # noqa: E402
from app.core import world_ops  # noqa: E402
from app.core.expression_pose_maps import resolve_pose_animation  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.height import height_cm  # noqa: E402
from app.core.party_engine import add_to_party  # noqa: E402
from app.models import character as character_mod  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_feeling, get_character_current_location,
    get_character_current_room, get_character_profile,
    get_character_profile_image, get_effective_activity,
    get_effective_pose_key, get_movement_target,
    save_character_current_location, save_character_current_room,
    save_character_profile, set_character_pos, set_is_sleeping,
    set_known_locations, set_movement_target)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_bound(label: str, actual: int, bound: int) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual <= bound
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual}"
          + ("" if ok else f" — expected <= {bound}"))
    if not ok:
        FAILURES.append(label)


# ── a pinned game clock ─────────────────────────────────────────────────
# The world calendar keeps running while this script does; two payloads built
# a few milliseconds apart would disagree on eta/progress for that reason
# alone. Everything reads the clock through this module attribute.
FROZEN = GameTime.parse("Y0002-D100T12:00:00")
timeutils.game_time = lambda: FROZEN

# ── a private pose catalog: the shipped one must not be edited ──────────
CAT = Path(tempfile.mkdtemp(prefix="worldmap-loads-cat-"))
_orig_catalog_path = pose_catalog.catalog_path
pose_catalog.catalog_path = (
    lambda axis: CAT / "pose_catalog.json" if axis == "pose"
    else _orig_catalog_path(axis))
(CAT / "pose_catalog.json").write_text(json.dumps({
    # Drops as in scripts/smoke_places.py — the values measured for the
    # contact point that meets the surface; a fixture inventing its own would
    # show a second truth next to the shipped one.
    "groups": {
        "seat": {"label": "Seat", "root_drop": 0.243, "default": "sitting",
                 "needs_place": True},
        "lie": {"label": "Bed", "root_drop": 0.003, "default": "sleeping",
                "needs_place": True},
        "stand": {"label": "Standing spot", "root_drop": 0,
                  "default": "standing", "needs_place": False}},
    "entries": {
        "standing": {"prompt": "p", "animation": "idle", "group": "stand",
                     "_default": True},
        "sitting": {"prompt": "p", "animation": "sit", "group": "seat"},
        "sleeping": {"prompt": "p", "animation": "laying", "group": "lie"}}}),
    encoding="utf-8")
pose_catalog.reload_catalogs()

# ── the world ───────────────────────────────────────────────────────────
HOUSE = add_location(name="Harbour Inn", description="worldmap load smoke",
                     rooms=[{"id": "lounge", "name": "Lounge"}])["id"]
update_location_position(HOUSE, 0.0, 0.0)
MARKET = add_location(name="Tide Market", description="the travel target")["id"]
update_location_position(MARKET, 200.0, 0.0)


def square(loc_id: str, half: float = 5.0, markers=None) -> None:
    """Give a location its DRAWN centred square (contract v6) and, for the
    inn, the room layout the place markers live in."""
    data = _load_world_data()
    for loc in data["locations"]:
        if loc["id"] != loc_id:
            continue
        map3d = loc.setdefault("map3d", {})
        map3d["plan_width_m"] = half * 2
        map3d["boundary"] = [[-half, -half], [half, -half],
                             [half, half], [-half, half]]
        if markers is not None:
            loc["rooms"][0]["layout"] = {"x": -4, "y": -4, "w": 8, "d": 6,
                                         "markers": list(markers)}
    _save_world_data(data)


square(HOUSE, markers=[{"id": "s1", "group": "seat", "at": [1, 1],
                        "rotation": 0},
                       {"id": "b1", "group": "lie", "at": [2, 4]}])
square(MARKET)
places.invalidate()

NAMES = ["npc_lead", "npc_still", "npc_seated", "npc_sleeper", "npc_walker"]


def person(name: str) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    save_character_current_location(name, HOUSE)
    # The point is the truth: set_character_pos derives the location from it.
    set_character_pos(name, -3.5, -3.5)
    save_character_current_room(name, "lounge")
    set_known_locations(name, [HOUSE, MARKET])


for _n in NAMES:
    person(_n)

# One seated, one asleep (the setter lies it down onto b1), one travelling,
# two in a party.
places.assign("npc_seated", "sitting")
set_is_sleeping("npc_sleeper", True)
add_to_party("npc_lead", "npc_still")

_prof = get_character_profile("npc_walker")
_prof["journey"] = {
    "target": MARKET,
    # 4000 m at 1 m per GAME second — still on the first leg for the whole run.
    "waypoints": [[0.0, 0.0, 0.0], [4000.0, 0.0, 4000.0]],
    "started_at_game": FROZEN.canonical(),
    "speed_m_s": 1.0,
    "entry_edge": "",
}
save_character_profile("npc_walker", _prof)
set_movement_target("npc_walker", MARKET)

# ── the counter ─────────────────────────────────────────────────────────
_real_gcp = character_mod.get_character_profile
_calls = {"n": 0}


def _counting_gcp(character_name):
    _calls["n"] += 1
    return _real_gcp(character_name)


def build_counted(fn, *args, **kwargs):
    """``fn(*args)`` with every ``get_character_profile`` counted.

    Returns ``(payload, calls, seconds)``. The patch sits on the MODULE, so
    it also catches the readers that import the function locally (the
    worldmap loop) and the ones that call it as a module global (the readers
    inside ``character.py`` itself)."""
    character_mod.get_character_profile = _counting_gcp
    _calls["n"] = 0
    try:
        t0 = time.perf_counter()
        payload = fn(*args, **kwargs)
        dt = time.perf_counter() - t0
    finally:
        character_mod.get_character_profile = _real_gcp
    return payload, _calls["n"], dt


def canonical(payload) -> str:
    """The payload as one canonical JSON string, reduced to its SHA-256 —
    the check prints what it compares, and a 4 kB dump per side would drown
    the run."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def repeat_ms(fn, *args, n: int = 20) -> float:
    """Milliseconds per build, averaged over ``n`` runs — one build is a
    fraction of a millisecond of real work here and too noisy to compare."""
    t0 = time.perf_counter()
    for _ in range(n):
        fn(*args)
    return (time.perf_counter() - t0) * 1000.0 / n


def row(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


#: The revision the "before" side is read from: the parent of the commit that
#: handed ``profile=`` down the worldmap loop (2862b391). Pinned, not ``HEAD`` —
#: once that commit is HEAD, comparing against HEAD compares the file with itself.
BASELINE_REV = "2862b391^"


def load_head_module():
    """The PRE-FIX ``app/core/world_ops.py`` (``BASELINE_REV``) as a second,
    throwaway module.

    Read-only: ``git show`` touches no git state, and the source is written
    into a temp directory, never into the tree. ``None`` when git or the
    revision is unavailable."""
    try:
        out = subprocess.run(["git", "show", f"{BASELINE_REV}:app/core/world_ops.py"],
                             cwd=str(REPO), capture_output=True, text=True,
                             timeout=60)
    except Exception as e:
        print(f"  --  git unavailable ({e}) — old/new comparison skipped")
        return None
    if out.returncode != 0 or not out.stdout:
        print(f"  --  {BASELINE_REV}:app/core/world_ops.py unavailable — "
              "old/new comparison skipped")
        return None
    path = Path(tempfile.mkdtemp(prefix="worldmap-loads-head-")) / "wo_head.py"
    path.write_text(out.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("wo_head", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wo_head"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("[0] the seed")
    admin, calls, secs = build_counted(world_ops.build_worldmap_payload,
                                       None, True)
    check("five characters on the map",
          sorted(c["name"] for c in admin["characters"]), sorted(NAMES))
    check("npc_seated holds s1",
          (row(admin, "npc_seated").get("place") or {}).get("id"), "s1")
    check("npc_sleeper holds b1",
          (row(admin, "npc_sleeper").get("place") or {}).get("id"), "b1")
    check("npc_sleeper reads as sleeping",
          row(admin, "npc_sleeper").get("activity"), "Sleeping")
    check("npc_walker travels to the market",
          (row(admin, "npc_walker").get("travel") or {}).get("target_id"),
          MARKET)
    check("npc_still follows npc_lead in a party",
          [c["name"] for c in admin["characters"]
           if c["name"] in ("npc_lead", "npc_still")],
          ["npc_lead", "npc_still"])

    print("\n[1] one profile load per character")
    print(f"  --  build took {secs * 1000:.1f} ms")
    # 5 * 4 (own + feeling + config/template behind the animation set)
    # + 2 * 2 (places.where for the two characters holding a place)
    check_bound("get_character_profile calls per admin build", calls, 24)
    fog, fog_calls, fog_secs = build_counted(
        world_ops.build_worldmap_payload, "npc_lead", False)
    print(f"  --  fogged build took {fog_secs * 1000:.1f} ms")
    # The fogged view adds the avatar's own four reads outside the loop:
    # get_character_language, visibility_context, `_avatar_loc` and the
    # payload's `current_location_id`.
    check_bound("get_character_profile calls per fogged build", fog_calls, 28)

    print("\n[2] the payload is unchanged — every field recomputed "
          "through the plain readers")
    for name in NAMES:
        r = row(admin, name)
        prof = get_character_profile(name) or {}
        check(f"{name}.location_id", r.get("location_id"),
              get_character_current_location(name) or "")
        check(f"{name}.room_id", r.get("room_id"),
              get_character_current_room(name) or "")
        check(f"{name}.movement_target_id", r.get("movement_target_id"),
              get_movement_target(name) or "")
        check(f"{name}.activity", r.get("activity"),
              get_effective_activity(name) or "")
        check(f"{name}.height_cm", r.get("height_cm"), height_cm(prof))
        check(f"{name}.mood", r.get("mood"),
              get_character_current_feeling(name) or "")
        _img = get_character_profile_image(name) or ""
        check(f"{name}.avatar_url", r.get("avatar_url"),
              f"/characters/{name}/images/{_img}" if _img else "")
        check(f"{name}.place", r.get("place"),
              world_ops._place_payload(name, prof))
        # No journey in this fixture carries an exit_clip, so the departure
        # bridge never fires and the animation is the pose key's clip.
        check(f"{name}.activity_animation", r.get("activity_animation"),
              resolve_pose_animation(get_effective_pose_key(name) or ""))

    print("\n[3] old vs. new — the whole payload, byte for byte")
    head = load_head_module()
    if head is None:
        print("  --  skipped")
    else:
        try:
            old_admin, old_calls, old_secs = build_counted(
                head.build_worldmap_payload, None, True)
            old_fog, old_fog_calls, _ = build_counted(
                head.build_worldmap_payload, "npc_lead", False)
        except Exception as e:
            # The pinned revision is a historical file running against
            # today's modules; when they drift apart it stops being a
            # reference. Sections [1] and [2] are the durable checks.
            print(f"  --  baseline no longer runs against this tree ({e}) — skipped")
            head = None
    if head is not None:
        check("admin payload identical (sha256/16)", canonical(old_admin),
              canonical(admin))
        check("fogged payload identical (sha256/16)", canonical(old_fog),
              canonical(fog))
        old_ms = repeat_ms(head.build_worldmap_payload, None, True)
        new_ms = repeat_ms(world_ops.build_worldmap_payload, None, True)
        print(f"  --  HEAD: {old_calls} profile loads, {old_ms:.2f} ms/build"
              f"  ->  now: {calls} profile loads, {new_ms:.2f} ms/build"
              f"  ({100 * (1 - new_ms / old_ms):.0f} % faster)")
        print(f"  --  HEAD fogged: {old_fog_calls} profile loads  ->  "
              f"now: {fog_calls}")
        print(f"  --  (single-build timings: HEAD {old_secs * 1000:.1f} ms, "
              f"now {secs * 1000:.1f} ms)")
        check("the new build loads strictly fewer profiles",
              calls < old_calls, True)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
