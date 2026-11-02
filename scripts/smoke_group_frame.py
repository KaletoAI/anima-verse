#!/usr/bin/env python3
"""Smoke: group clips — three to five roles (plan-gruppen-animationen.md, G1).

Usage:  ./.venv/bin/python scripts/smoke_group_frame.py

No Blender, no server, a throwaway clip library. Every number below is
derived by hand from the rules in ``app/blender/scripts/_group_frame.py``;
a pair (N = 2) must come out exactly as the old pair rule.

THE CONVENTION. ``rotate_y(t, x, z) = (cos t·x + sin t·z, -sin t·x + cos t·z)``
(mathutils' rotation about +Y). The frame turns A → B onto +X
(``theta = atan2(bz - az, bx - ax) + yaw``) and puts the CENTROID of all roots
at the origin; a point lands at ``rotate_y(theta, p) - rotate_y(theta, c)``.

[1] PAIR, the old rule. A (0, 0), B (0, 2): theta = atan2(2, 0) = 90 deg,
    rotate_y(90) maps (x, z) to (z, -x); the midpoint (0, 1) maps to (1, 0).
    A -> (0, 0) - (1, 0) = (-1, 0); B -> (2, 0) - (1, 0) = (1, 0).
[2] THREE ROLES. A (0, 0), B (2, 0), C (1, 3): theta = 0, centroid (1, 1).
    A' (-1, -1), B' (1, -1), C' (0, 2).
[3] THE SAME WITH THE DIAL at 90 deg: theta = 90 deg, the centroid maps to
    (1, -1). A (0, 0) -> (0, 0) - (1, -1) = (-1, 1); B (2, 0) -> (0, -2) -
    (1, -1) = (-1, -1); C (1, 3) -> (3, -1) - (1, -1) = (2, 0). |A'B'| = 2 as
    before the turn.
[4] ANCHOR FRAME = the smallest sum of distances A -> other role.
    A stays at (0, 0); B (3, 0) (2, 0) (4, 0); C (0, 3) (0, 3) (0, 1):
    sums 6, 5, 5 -> the FIRST minimum, frame 1. A pair (C left out) with
    B (3, 0) (1, 0) (2, 0): distances 3, 1, 2 -> frame 1. ``anchor_s`` 0.1 s
    at 30 fps is frame 3, capped to the last frame 2.
[5] CONTACT, PAIR (the old half/half rule). Hands only: actor A (0, 100, 0),
    B (10, 100, 0) -> 10 cm; rig A (0, 100, 0), B (20, 100, 0) -> 20 cm;
    gap 10 along A -> B = +X: A moves (+5, 0), B (-5, 0); the record sits on
    B: to a, actor 10, rig 20, shift 10.
[6] CONTACT, GROUP (grows from A). Actor hands A (0, 100, 0), B (10, 100,
    0), C (10, 100, 30): A-B 10, A-C sqrt(1000) = 31.62, B-C 30. Round 1
    takes B (10 < 31.62) against A: rig B (16, 100, 0), rig gap 16 - 10 =
    6 toward A (direction -X) -> B (-6, 0), so B's rig hand now stands at
    (10, 100, 0). Round 2 takes C against B (30 < 31.62): rig C (10, 100,
    40) to B's moved hand (10, 100, 0) = 40, gap 40 - 30 = 10 toward B
    (direction -Z) -> C (0, -10). A never moves: (0, 0).
[7] NO PULL APART. Actor hands 20 cm apart, rig 10 cm: the gap is negative,
    nothing moves, shift 0.
[8] ONLY HAND CONTACTS. A's head (0, 100, 0) and B's hips (1, 100, 0) are
    1 cm apart but neither is a hand; the hands are 50 cm apart; A's hand
    to B's hips sqrt(1^2 + 100^2) = 100.005. The contact is the hands, 50.
[9] THE LIBRARY. Files g__a, g__b, g__c (a group of 3), p__a, p__b (a
    pair), gap__a, gap__c (B missing) and x__f (``f`` is no role letter):
    parse_clip_role("g__c.fbx") = ("g", "c"), ("x__f.fbx") = ("x__f", "");
    role_counts = {g: 3, p: 2}; pair_kinds = [p] (a group is NOT a pair);
    deleting g__b removes g__a and g__c with it.
[10] ROLE GENDER. A group sidecar roles [a, b, c] with female, female, male
    is complete; male, male, male (all the same) is {}; a missing c is {}.
    An old pair sidecar without ``roles`` reads a/b. From take names:
    Female[A]_X_Loop0, Female[B]_X_Loop0, Male[A]_X_Loop0 ->
    {a: female, b: female, c: male}; a name without "Female/Male" -> {}.
[11] GROUP TAKES. Names: 0 Female[A]_S_Loop0, 1 Male[A]_S_Loop0,
    2 Female[B]_S_Loop0, 3 Male[A]_S_Climax, 4 Female[A]_P_Loop0,
    5 Male[A]_P_Loop0. Scene "s_loop0" has three performers; role order is
    the word order female before male, then the slot: [0, 2, 1]. Scene
    "p_loop0" has two -> None (a pair keeps partner_take). Six performers
    of one scene exceed a..e -> None.
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLIPS = Path(tempfile.mkdtemp(prefix="group-frame-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="group-frame-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="group-frame-world-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.core import paths  # noqa: E402
paths.init(WORLD)
from app.core import animation_clips as ac  # noqa: E402
from app.core import fbx_import  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "_group_frame", ROOT / "app" / "blender" / "scripts" / "_group_frame.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def close(p, q, eps=1e-9):
    return all(abs(a - b) < eps for a, b in zip(p, q))


def placed(at_anchor, yaw=0.0):
    theta, m = G.frame(at_anchor, yaw)
    return {r: G.place(theta, m, *p) for r, p in at_anchor.items()}


def test_frame():
    print("\n[1]-[3] the frame of reference")
    got = placed({"a": (0, 0), "b": (0, 2)})
    check("[1] a pair: A (-1, 0), B (1, 0)", close(got["a"], (-1, 0)) and close(got["b"], (1, 0)),
          str(got))
    got = placed({"a": (0, 0), "b": (2, 0), "c": (1, 3)})
    check("[2] three roles: A (-1, -1), B (1, -1), C (0, 2)",
          close(got["a"], (-1, -1)) and close(got["b"], (1, -1)) and close(got["c"], (0, 2)),
          str(got))
    got = placed({"a": (0, 0), "b": (2, 0), "c": (1, 3)}, 90)
    check("[3] dial 90: A (-1, 1), B (-1, -1), C (2, 0)",
          close(got["a"], (-1, 1)) and close(got["b"], (-1, -1)) and close(got["c"], (2, 0)),
          str(got))


def test_anchor():
    print("\n[4] the anchor frame")
    a = [(0, 0)] * 3
    roots = {"a": a, "b": [(3, 0), (2, 0), (4, 0)], "c": [(0, 3), (0, 3), (0, 1)]}
    check("three roles: the first minimum, frame 1", G.anchor_index(roots, 30) == 1,
          str(G.anchor_index(roots, 30)))
    pair = {"a": a, "b": [(3, 0), (1, 0), (2, 0)]}
    check("a pair: the closest frame 1", G.anchor_index(pair, 30) == 1)
    check("anchor_s 0.1 s at 30 fps is capped to frame 2",
          G.anchor_index(roots, 30, anchor_s=0.1) == 2)


def test_fit():
    print("\n[5]-[8] the contact fit")
    hand = "LeftHand"
    off, rec = G.fit({"a": {hand: (0, 100, 0)}, "b": {hand: (10, 100, 0)}},
                     {"a": {hand: (0, 100, 0)}, "b": {hand: (20, 100, 0)}})
    check("[5] pair: A (+5, 0), B (-5, 0)", close(off["a"], (5, 0)) and close(off["b"], (-5, 0)),
          str(off))
    check("[5] the record: to a, 10 / 20 / 10 cm",
          rec["b"]["to"] == "a" and close((rec["b"]["actor_cm"], rec["b"]["rig_cm"],
                                           rec["b"]["shift_cm"]), (10, 20, 10)), str(rec))
    off, rec = G.fit({"a": {hand: (0, 100, 0)}, "b": {hand: (10, 100, 0)}, "c": {hand: (10, 100, 30)}},
                     {"a": {hand: (0, 100, 0)}, "b": {hand: (16, 100, 0)}, "c": {hand: (10, 100, 40)}})
    check("[6] group: A stays, B (-6, 0), C (0, -10)",
          close(off["a"], (0, 0)) and close(off["b"], (-6, 0)) and close(off["c"], (0, -10)), str(off))
    check("[6] B fitted to A, C to B",
          rec["b"]["to"] == "a" and rec["c"]["to"] == "b"
          and close((rec["c"]["actor_cm"], rec["c"]["rig_cm"], rec["c"]["shift_cm"]), (30, 40, 10)),
          str(rec))
    off, rec = G.fit({"a": {hand: (0, 100, 0)}, "b": {hand: (20, 100, 0)}},
                     {"a": {hand: (0, 100, 0)}, "b": {hand: (10, 100, 0)}})
    check("[7] a closer rig moves nothing", close(off["a"], (0, 0)) and close(off["b"], (0, 0))
          and rec["b"]["shift_cm"] == 0.0, str(off))
    off, rec = G.fit({"a": {"Head": (0, 100, 0), hand: (0, 0, 0)},
                      "b": {"Hips": (1, 100, 0), hand: (50, 0, 0)}},
                     {"a": {"Head": (0, 100, 0), hand: (0, 0, 0)},
                      "b": {"Hips": (1, 100, 0), hand: (50, 0, 0)}})
    check("[8] head-hips is no contact: the hands, 50 cm",
          rec["b"]["hands"] == [hand, hand] and abs(rec["b"]["actor_cm"] - 50) < 1e-9, str(rec))


def test_library():
    print("\n[9] the library")
    check("g__c.fbx is role c of g", ac.parse_clip_role("g__c.fbx") == ("g", "c"))
    check("x__f.fbx is a solo kind 'x__f'", ac.parse_clip_role("x__f.fbx") == ("x__f", ""))
    for stem in ("g__a", "g__b", "g__c", "p__a", "p__b", "gap__a", "gap__c", "x__f"):
        (CLIPS / f"{stem}.fbx").write_bytes(b"fbx")
    (CLIPS / "g.json").write_text(json.dumps({"kind": "g", "pair": True, "roles": ["a", "b", "c"]}))
    ac.reload_clip_caches()
    check("role_counts = {g: 3, p: 2}", ac.role_counts() == {"g": 3, "p": 2}, str(ac.role_counts()))
    check("pair_kinds = [p]", ac.pair_kinds() == ["p"], str(ac.pair_kinds()))
    res = ac.set_clip_role_gender("free", "g__b.fbx", {"a": "female", "b": "female", "c": "male"})
    check("role genders written for all three roles",
          all(v["role_gender"] == {"a": "female", "b": "female", "c": "male"} for v in res)
          and len(res) == 3, str([v["role_gender"] for v in res]))
    try:
        ac.set_clip_role_gender("free", "g__a.fbx", {"a": "male", "b": "male", "c": "male"})
        check("all the same gender is refused", False)
    except ac.ClipLibraryError:
        check("all the same gender is refused", True)
    out = ac.delete_clip("free", "g__b.fbx")
    check("deleting one role file deletes the group",
          out["deleted"] == ["g__a.fbx", "g__b.fbx", "g__c.fbx"] and out["sidecar_removed"],
          str(out))


def test_role_gender():
    print("\n[10] role gender")
    meta = {"roles": ["a", "b", "c"]}
    check("female, female, male is complete",
          ac.clip_role_gender({**meta, "role_gender": {"a": "female", "b": "female", "c": "male"}})
          == {"a": "female", "b": "female", "c": "male"})
    check("everybody male is {}",
          ac.clip_role_gender({**meta, "role_gender": {"a": "male", "b": "male", "c": "male"}}) == {})
    check("c missing is {}",
          ac.clip_role_gender({**meta, "role_gender": {"a": "female", "b": "male"}}) == {})
    check("an old pair sidecar reads a/b",
          ac.clip_role_gender({"role_gender": {"a": "female", "b": "male"}})
          == {"a": "female", "b": "male"})
    names = ["Female[A]_X_Loop0", "Female[B]_X_Loop0", "Male[A]_X_Loop0"]
    check("from take names", fbx_import.role_gender_from_names(names)
          == {"a": "female", "b": "female", "c": "male"}, str(fbx_import.role_gender_from_names(names)))
    check("a name without Female/Male gives {}",
          fbx_import.role_gender_from_names(["Female[A]_X", "Robot_X"]) == {})


def test_group_takes():
    print("\n[11] group takes")
    names = ["Female[A]_S_Loop0", "Male[A]_S_Loop0", "Female[B]_S_Loop0", "Male[A]_S_Climax",
             "Female[A]_P_Loop0", "Male[A]_P_Loop0"]
    check("scene S: [0, 2, 1] (female A, female B, male A)",
          fbx_import.group_takes(names[1], names) == [0, 2, 1], str(fbx_import.group_takes(names[1], names)))
    check("a pair scene gives None", fbx_import.group_takes(names[4], names) is None)
    six = [f"Female[{x}]_Big_Loop0" for x in "ABCD"] + ["Male[A]_Big_Loop0", "Male[B]_Big_Loop0"]
    check("six performers exceed a..e: None", fbx_import.group_takes(six[0], six) is None)


def main():
    print("Smoke: group clips (three to five roles)")
    test_frame()
    test_anchor()
    test_fit()
    test_library()
    test_role_gender()
    test_group_takes()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
