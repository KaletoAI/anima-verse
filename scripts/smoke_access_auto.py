#!/usr/bin/env python3
"""Automatic access and pose transitions: the server's rules the native client ports.

Usage: ./.venv/bin/python scripts/smoke_access_auto.py

No server, no live world: `paths.init(<tmpdir>)` runs before any world-DB
import, `ANIMATION_CLIPS_DIR` points at an empty temp directory. The smoke
reads the two vector files `shared/test-vectors/access_auto.json` and
`shared/test-vectors/pose_transition.json` (class C: the derivation lives in
this docstring, the C# tests `native/tests/AccessAutoTests.cs` and
`native/tests/PoseTransitionTests.cs` replay the same cases natively) and
replays every case through the server's own functions:

  access_auto      room_stand.bridge_offset / bridge_scale (and, as a cross
                   check, room_stand.bridge_start_point with turn 0)
  pose_transition  animation_clips.resolve_pose_transition + rule_kind, with
                   the table the vector's listing names

It also checks that the vector's LISTING fixture is the shipped data — its
`transitions` are `shared/config/clip_transitions.json` rule for rule and every
`pose_groups` entry is the shipped pose catalog's `group` — and that the
listing `GET /assets/animation-clips` (`list_animation_clips`) carries
`pose_groups` with those same values, which is where the client reads them.

Hand derivation — access_auto.json
----------------------------------
The rule (docs/schnittstellen-3d.md, "Access is automatic for each chosen
marker slot"): access = body slot minus the entry clip's root travel, turned
by the facing and scaled to the figure. `room_stand.bridge_offset`, quoted:

    World XZ by which a bridge clip carries a figure that faces
    ``facing_deg`` (compass: 0 = south +z, 90 = east +x) — the clip's travel
    (+Z forward, +X the figure's left) turned by the facing and scaled to
    the figure.
        a = radians(facing); tx, tz = travel_x * scale, travel_z * scale
        offset = (tx*cos a + tz*sin a, -tx*sin a + tz*cos a)

and `bridge_scale(height_cm, ref_height_m)` = (height_cm / 100) / ref_height_m,
1.0 when either is unknown. Slot (2, 0, 3); clip travel 0.6 m forward, i.e.
travel (0, 0.6); reference height 1.70 m. Y is carried over unchanged.

  [1] yaw 90, 170 cm: scale 1.70 / 1.70 = 1; offset = (0*0 + 0.6*1,
      -0*1 + 0.6*0) = (0.6, 0); access = (2 - 0.6, 0, 3 - 0) = (1.4, 0, 3),
      yaw 90 (the heading that finishes at the marker facing, turn 0).
  [2] yaw 90, 153 cm: scale 1.53 / 1.70 = 0.9; offset (0.54, 0);
      access (1.46, 0, 3).
  [3] yaw 0, 170 cm: offset = (0*1 + 0.6*0, -0*0 + 0.6*1) = (0, 0.6);
      access (2, 0, 2.4).
  [4] height unknown: scale 1.0 -> as [1], (1.4, 0, 3).

Hand derivation — pose_transition.json
--------------------------------------
`EntryKind(pose)` = rule_kind(resolve_pose_transition("walking", pose)),
`ExitKind(pose)` = rule_kind(resolve_pose_transition(pose, "standing")), null
when no rule. resolve_pose_transition: first resolve_transition(from, to)
(exact pair, then (from, *), then (*, to); same pose = none), then — only when
that finds nothing — resolve_transition(from, @<group of to>), then
resolve_transition(@<group of from>, to). rule_kind of a per-role kind map
without a role is "".

The shipped rules (shared/config/clip_transitions.json, in file order):
  R1 sleeping -> standing get-up-bed      R7  walking -> @seat   sit-down
  R2 sleeping -> walking  get-up-bed      R8  walking -> @stand  step-in
  R3 recovering -> *      get-up-chair    R9  walking -> @ground sit-down-floor
  R4 sitting at table -> * get-up-chair   R10 walking -> @lie    lie-down
  R5 lying -> standing    get-up-bed      R11 @seat -> *         get-up-chair
  R6 standing -> walking  walk            R12 @lie -> *          get-up-bed
Shipped groups (shared/templates/pose/pose_catalog.json): sitting at table
seat, sitting seat, cooking stand, walking stand, standing stand, meditating
ground, lying lie.

  [1] sitting at table — a seat pose WITH its own rule. Entry: no rule names
      (walking, sitting at table) or (*, sitting at table) -> group @seat ->
      R7 sit-down. Exit: (sitting at table, *) is R4 -> get-up-chair.
  [2] sitting — a seat pose only over @seat. Entry R7 sit-down. Exit: no
      rule from sitting; (sitting, @stand) none; (@seat, standing) -> R11
      (@seat, *) get-up-chair.
  [3] cooking — no exit rule. Entry: group @stand -> R8 step-in. Exit:
      (cooking, standing) none, (cooking, @stand) none, (@stand, standing)
      none -> null.
  [4] meditating — entry R9 sit-down-floor; exit (@ground, standing) none ->
      null ("no ground exit").
  [5] a pose the catalog does not know: no group; entry tries (@stand of
      walking, pose) — none -> null; exit (pose, @stand) none -> null.
  [6] " Sitting At Table ": keys are trimmed and lower-cased -> as [1].
  [7] fixture OWN lists the group rules BEFORE walking -> sitting "perch" and
      sitting -> * "rise": the pose's own rule wins regardless of position ->
      entry perch, exit rise.
  [8] OWN, lying: walking -> @lie has the per-role kind {a, b}; rule_kind
      without a role -> "" (a rule, but no clip); exit: (@lie, standing) has
      no rule in OWN -> null.
  [9] walking: resolve_transition(walking, walking) is none (same pose), then
      walking's group @stand -> R8 step-in. Exit (walking, standing): no
      direct rule, then (walking, @stand) -> R8 step-in. The server's order,
      quirk included — the client must answer the same.
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke-access-auto-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
(TMP / "clips").mkdir()

from app.core import paths  # noqa: E402

paths.init(TMP / "world")
from app.core import db  # noqa: E402

db.init_schema()
from app.core import animation_clips as clips  # noqa: E402
from app.core import room_stand  # noqa: E402
from app.core.pose_catalog import get_catalog  # noqa: E402

VECTORS = ROOT / "shared" / "test-vectors"
FAILS = []


def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        FAILS.append(label)


def resolve(value, fixtures):
    """`{"$fixture": NAME}` -> a copy of that fixture (the vectors here use no `$with`)."""
    if isinstance(value, dict) and "$fixture" in value:
        return json.loads(json.dumps(fixtures[value["$fixture"]]))
    return value


def near(a, b, eps=1e-9):
    return abs(a - b) <= eps


def access_cases():
    data = json.loads((VECTORS / "access_auto.json").read_text())
    for case in data["cases"]:
        slot, dx, dz, height, ref = case["args"]
        want = case["expect"]
        scale = room_stand.bridge_scale(height, ref)
        ox, oz = room_stand.bridge_offset((dx, dz), slot["yaw"], scale)
        got = dict(x=slot["x"] - ox, y=slot["y"], z=slot["z"] - oz, yaw=slot["yaw"])
        sx, sz = room_stand.bridge_start_point((slot["x"], slot["z"]), (dx, dz), slot["yaw"], height, ref, 0.0)
        check(all(near(got[k], want[k]) for k in ("x", "y", "z", "yaw"))
              and near(sx, want["x"]) and near(sz, want["z"]), case["label"] + f" -> {got}")


def _rules(listing):
    return [dict(r, kind=clips.normalize_rule_kind(r.get("kind"))) for r in listing["transitions"]]


def pose_cases():
    data = json.loads((VECTORS / "pose_transition.json").read_text())
    fixtures = data["fixtures"]
    # The LISTING fixture is the shipped data, not a copy that may drift.
    shipped = [dict(r) for r in clips.load_shared_transitions()]
    check([(r["from"], r["to"], r["kind"], r["accel"]) for r in fixtures["LISTING"]["transitions"]]
          == [(r["from"], r["to"], r["kind"], r["accel"]) for r in shipped],
          "LISTING.transitions == shared/config/clip_transitions.json")
    catalog = get_catalog("pose")
    for key, group in fixtures["LISTING"]["pose_groups"].items():
        check((catalog.get(key) or {}).get("group") == group, f"LISTING.pose_groups[{key!r}] == catalog group {group}")
    for case in data["cases"]:
        listing = resolve(case["args"][0], fixtures)
        pose = case["args"][1]
        groups = listing["pose_groups"]
        # The table and the groups of THIS listing: rules as given, groups from
        # its pose_groups (the shipped catalog for LISTING, checked above).
        fake = {k: {"group": g} for k, g in groups.items()}
        with patch.object(clips, "effective_transitions", lambda path=None, _r=_rules(listing): _r), \
                patch("app.core.pose_catalog.get_catalog", lambda axis: fake):
            entry = clips.resolve_pose_transition("walking", pose)
            exit_ = clips.resolve_pose_transition(pose, "standing")
        got = dict(entry=clips.rule_kind(entry) if entry else None,
                   exit=clips.rule_kind(exit_) if exit_ else None)
        check(got == case["expect"], case["label"] + f" -> {got}")


def listing_groups():
    from app.routes.assets import list_animation_clips
    listing = list_animation_clips()
    groups = listing.get("pose_groups")
    check(isinstance(groups, dict), "GET /assets/animation-clips carries pose_groups")
    want = json.loads((VECTORS / "pose_transition.json").read_text())["fixtures"]["LISTING"]["pose_groups"]
    for key, group in want.items():
        check((groups or {}).get(key) == group, f"listing pose_groups[{key!r}] == {group}")
    check(all(g in ("stand", "seat", "ground", "lie") for g in (groups or {}).values()),
          "listing pose_groups names only rule groups")
    rows = [(r["from"], r["to"], r["kind"]) for r in listing.get("transitions", [])]
    check(rows == [(r["from"], r["to"], r["kind"]) for r in clips.load_transitions()],
          "listing transitions are the pose rules (from, to, kind)")


if __name__ == "__main__":
    print("[access_auto.json]")
    access_cases()
    print("[pose_transition.json]")
    pose_cases()
    print("[listing]")
    listing_groups()
    print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
