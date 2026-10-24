#!/usr/bin/env python3
"""Smoke: the animation studio's PAIR clips — frame, partner goals, pair
checks, publish with a synonym take-over. No Blender.

Usage: ./.venv/bin/python scripts/smoke_animstudio_pair.py

Expectations are derived by hand from the convention in animstudio.compile
(``role_transform``): A's own clip space is turned by Ry(+90), which maps a
local (x, y, z) to (z, y, -x), and moved to (-d/2, 0, +s/2); B by Ry(-90),
(x, y, z) -> (-z, y, x), moved to (+d/2, 0, -s/2) (cm). Rest numbers come
from animation-studio/rig_rest.json.

[1] frame: d = 0.5 m, s = 0.2 m, nothing keyed. A's Hips head (rest
    (0, 113.03, 0)) sits at (-25, 113.03, +10), B's at (+25, 113.03, -10);
    A's front (0, 0, 1) points along D_a = Ry(90): (1, 0, 0), B's along
    (-1, 0, 0). Tolerance 1e-6 cm. A negative stagger s = -0.2 m moves
    each to its own LEFT: A's hips at (-25, 113.03, -10), B's at
    (+25, 113.03, +10).
[2] partner goal: d = 0.4, s = 0. A's right hand aims at B's Spine2 with
    offset (0, 0, 0.10) m (10 cm in front of B's chest). B's Spine2 head
    h = rest head -> (-h.z, h.y, h.x) + (20, 0, 0); the offset turns with B
    (rest, so D = Ry(-90)): (0, 0, 10) -> (-10, 0, 0). Target =
    (20 - h.z - 10, h.y, h.x) = about (9.6, 136.3, 0). A's right shoulder
    (RightArm head r -> (r.z - 20, r.y, -r.x), about (-24.1, 153.1, 12.2))
    is 39.6 cm away, inside the 54.8 cm reach: the hand head lands on the
    target within 0.01 cm and ik_error_cm["r_hand"] < 0.01.
[3] pair checks on two rest-armed figures face to face (arms hanging, the
    RELAXED base):
    d = 0.50: the Spine1 heads (rest z = 0.8) lie 50 - 1.6 = 48.4 cm apart,
      more than the grown depth 2 * 9 = 18 -> pair_chests ok; head centres
      (z (-1.4 + 2.4) / 2 = 0.5) 49 cm apart >= 18 -> pair_heads ok; the
      hanging arms stay by their own sides -> pair_arms ok.
    d = 0.15: Spine1 heads 15 - 1.6 = 13.4 cm apart < 18 -> pair_chests
      FAILS; head centres 15 - 1.0 = 14 cm < 18 -> pair_heads FAILS.
[4] validation: a PartnerTarget on "LeftHand" (not a torso bone) raises
    StudioError; a PartnerTarget in a SOLO Animation raises StudioError at
    compile; validate_pair accepts stagger -0.5 and 0.5 and refuses 0.6
    and -0.6 (bounds -0.5..0.5); a take_over synonym that is not among the synonyms raises
    StudioError on publish.
[5] publish of a fake pair build (kind "demo-hug", key "hug-demo",
    synonyms ("hug demo", "umarmen-demo"), take_over ("umarmen-demo",))
    into a temp git repo with a copy of the shipped catalog plus a
    smoke-owned entry "demo-owner" (synonyms "trösten-demo",
    "umarmen-demo"), where the working tree adds a LOCAL synonym
    "local-extra" to "demo-owner" (never committed):
    - the library holds demo-hug__a.fbx, demo-hug__b.fbx, demo-hug.json;
    - HEAD's entry "hug-demo" = solo false, places 2, yaw_offset 0,
      animation "demo-hug";
    - HEAD's "demo-owner" = ["trösten-demo"] (no "local-extra"); the
      working tree's "demo-owner" keeps "local-extra" and lost
      "umarmen-demo";
    - the commit touches exactly: catalog, the two halves, the sidecar,
      the source.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(tempfile.mkdtemp(prefix="animstudio-pair-repo-"))
# smoke_scripts_storage_lint accepts only a literal paths.init(...) or
# STORAGE_DIR before a world-DB import - bootstrap() is a wrapper it cannot see.
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="animstudio-world-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(REPO / "shared/models/clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(REPO / "shared/models/clips-licensed")
sys.path.insert(0, str(ROOT / "animation-studio"))

import animstudio                                                     # noqa: E402
animstudio.bootstrap()
animstudio.OUT = REPO / "animation-studio/out"
animstudio.ANIMS = REPO / "animation-studio/anims"

import numpy as np                                                    # noqa: E402
from animstudio import StudioError, rig                               # noqa: E402
from animstudio.checks import pair_checks                             # noqa: E402
from animstudio.compile import compile_anim, compile_pair             # noqa: E402
from animstudio.dsl import (Animation, Catalog, PairAnimation, PartnerTarget, Pose,  # noqa: E402
                            Role, validate_pair)

FAIL = []
CAT_REL = "shared/templates/pose/pose_catalog.json"
REST = rig.load_rest()
CAT = Catalog(key="x", group="stand", prompt="p")


def near(label, got, want, tol):
    if np.linalg.norm(np.asarray(got, float) - np.asarray(want, float)) > tol:
        FAIL.append(f"{label}: got {np.round(got, 4)} want {np.round(want, 4)}")


def pair(d, s=0.0, a=None, b=None):
    return PairAnimation(kind="t", duration_s=0.1, loop=False, catalog=CAT,
                         a=a or Role(), b=b or Role(), distance_m=d, stagger_m=s)


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True,
                          text=True).stdout


try:
    # [1]
    cp = compile_pair(pair(0.5, 0.2), REST)
    hy = REST.head["Hips"][1]
    fa, fb = cp.pair_frames("a")[0], cp.pair_frames("b")[0]
    near("[1] A hips", fa.pos["Hips"], (-25.0, hy, 10.0), 1e-6)
    near("[1] B hips", fb.pos["Hips"], (25.0, hy, -10.0), 1e-6)
    near("[1] A front", fa.D["Hips"] @ np.array([0.0, 0.0, 1.0]), (1, 0, 0), 1e-9)
    near("[1] B front", fb.D["Hips"] @ np.array([0.0, 0.0, 1.0]), (-1, 0, 0), 1e-9)
    cp = compile_pair(pair(0.5, -0.2), REST)
    near("[1] A hips s<0", cp.pair_frames("a")[0].pos["Hips"], (-25.0, hy, -10.0), 1e-6)
    near("[1] B hips s<0", cp.pair_frames("b")[0].pos["Hips"], (25.0, hy, 10.0), 1e-6)

    # [2]
    h = REST.head["Spine2"]
    want = (20.0 - h[2] - 10.0, h[1], h[0])
    cp = compile_pair(pair(0.4, a=Role(ik=[PartnerTarget("r", "Spine2", (0.0, 0.0, 0.10))])),
                      REST)
    near("[2] hand on target", cp.pair_frames("a")[0].pos["RightHand"], want, 0.01)
    if cp.a.ik_error_cm.get("r_hand", 99.0) >= 0.01:
        FAIL.append(f"[2] ik error {cp.a.ik_error_cm}")
    print(f"[2] target {np.round(want, 2)}")

    # [3]
    relaxed = Role(base=Pose(**rig.RELAXED))
    for d, ok in ((0.50, {"pair_chests": True, "pair_heads": True, "pair_arms": True}),
                  (0.15, {"pair_chests": False, "pair_heads": False})):
        cp = compile_pair(pair(d, a=relaxed, b=relaxed), REST)
        got = {c.name: c for c in pair_checks({r: cp.pair_frames(r) for r in "ab"})}
        for name, want_ok in ok.items():
            if got[name].ok != want_ok:
                FAIL.append(f"[3] d={d} {name}: {got[name]}")
        print(f"[3] d={d}: " + ", ".join(f"{n} {c.value}" for n, c in got.items()))

    # [4]
    try:
        compile_pair(pair(0.4, a=Role(ik=[PartnerTarget("r", "LeftHand", (0, 0, 0))])), REST)
        FAIL.append("[4] LeftHand accepted")
    except StudioError:
        pass
    try:
        compile_anim(Animation(kind="t", duration_s=0.1, loop=False, catalog=CAT,
                               ik=[PartnerTarget("r", "Spine2", (0, 0, 0))]), REST)
        FAIL.append("[4] solo PartnerTarget accepted")
    except StudioError:
        pass
    for s_m, ok in ((-0.5, True), (0.5, True), (0.6, False), (-0.6, False)):
        try:
            validate_pair(pair(0.4, s_m))
            if not ok:
                FAIL.append(f"[4] stagger {s_m} accepted")
        except StudioError as e:
            if ok:
                FAIL.append(f"[4] stagger {s_m} refused: {e}")

    # [5]
    from app.core import pose_catalog as pc
    from animstudio import publish as P
    from animstudio.build import spec_sha
    (REPO / "shared/templates/pose").mkdir(parents=True)
    (REPO / "shared/models/clips").mkdir(parents=True)
    (REPO / "shared/models/clips-licensed").mkdir(parents=True)
    # The shipped catalog plus a smoke-owned owner entry, so the take-over
    # does not depend on which synonyms the real catalog holds today.
    doc = json.loads((ROOT / CAT_REL).read_text())
    doc["entries"]["demo-owner"] = {"prompt": "a person demo-owner someone",
                                    "synonyms": ["trösten-demo", "umarmen-demo"],
                                    "animation": "idle", "group": "stand"}
    (REPO / CAT_REL).write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    git("init", "-q")
    git("config", "user.email", "smoke@example.invalid")
    git("config", "user.name", "smoke")
    git("add", CAT_REL)
    git("commit", "-qm", "seed")
    shipped = json.loads((REPO / CAT_REL).read_text())["entries"]["demo-owner"]["synonyms"]
    doc = json.loads((REPO / CAT_REL).read_text())
    doc["entries"]["demo-owner"]["synonyms"].append("local-extra")
    (REPO / CAT_REL).write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    pc.catalog_path = lambda a, _o=pc.catalog_path: (REPO / CAT_REL) if a == "pose" else _o(a)
    pc.reload_catalogs()

    def fake_pair(kind, take_over):
        src = animstudio.ANIMS / f"{kind}.py"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            "from animstudio.dsl import Catalog, PairAnimation, Role\n"
            f"ANIM = PairAnimation(kind={kind!r}, duration_s=1.0, loop=False, distance_m=0.4,\n"
            "    catalog=Catalog(key='hug-demo', group='stand', prompt='two people hugging',\n"
            f"        synonyms=('hug demo', 'umarmen-demo'), take_over={tuple(take_over)!r}),\n"
            "    a=Role(), b=Role())\n")
        out = animstudio.OUT / kind
        out.mkdir(parents=True, exist_ok=True)
        for role in ("a", "b"):
            (out / f"{kind}__{role}.fbx").write_bytes(f"FBX-{kind}-{role}".encode())
        (out / f"{kind}.json").write_text(json.dumps({"kind": kind, "pair": True, "fps": 30}))
        (out / "build.json").write_text(json.dumps(
            {"kind": kind, "spec_sha": spec_sha(kind), "ok": True, "pair": True,
             "checks": [{"name": "pair_arms", "ok": True, "value": -0.1, "limit": "<= 0",
                         "detail": ""}]}))

    fake_pair("demo-hug", ("hug demo-x",))
    try:
        P.publish("demo-hug", repo=REPO)
        FAIL.append("[4] stray take_over accepted")
    except StudioError:
        pass
    fake_pair("demo-hug", ("umarmen-demo",))
    r = P.publish("demo-hug", repo=REPO)
    if r["moved"] != {"demo-owner": ["umarmen-demo"]}:
        FAIL.append(f"[5] moved {r['moved']}")
    lib = REPO / "shared/models/clips"
    for name in ("demo-hug__a.fbx", "demo-hug__b.fbx", "demo-hug.json"):
        if not (lib / name).is_file():
            FAIL.append(f"[5] {name} missing in the library")
    head = json.loads(git("show", f"HEAD:{CAT_REL}"))["entries"]
    e = head.get("hug-demo") or {}
    if (e.get("solo"), e.get("places"), e.get("yaw_offset"), e.get("animation")) != \
            (False, 2, 0, "demo-hug"):
        FAIL.append(f"[5] HEAD entry {e}")
    if head["demo-owner"]["synonyms"] != [x for x in shipped if x != "umarmen-demo"]:
        FAIL.append(f"[5] HEAD demo-owner {head['demo-owner']['synonyms']}")
    wt = json.loads((REPO / CAT_REL).read_text())["entries"]["demo-owner"]["synonyms"]
    if "local-extra" not in wt or "umarmen-demo" in wt:
        FAIL.append(f"[5] working-tree demo-owner {wt}")
    changed = sorted(git("show", "--name-only", "--format=", "HEAD").split())
    want_files = sorted([CAT_REL, "shared/models/clips/demo-hug__a.fbx",
                         "shared/models/clips/demo-hug__b.fbx",
                         "shared/models/clips/demo-hug.json",
                         "animation-studio/anims/demo-hug.py"])
    if changed != want_files:
        FAIL.append(f"[5] commit touches {changed}")
finally:
    shutil.rmtree(REPO, ignore_errors=True)

if FAIL:
    print("FAIL smoke_animstudio_pair")
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("OK smoke_animstudio_pair")
