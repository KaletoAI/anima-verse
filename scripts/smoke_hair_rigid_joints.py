#!/usr/bin/env python3
"""Hair-chain joints inside the head collision capsule ride the head (Ruling H10 of plan
docs/superpowers/plans/2026-11-12-hairdeck-spring-chains.md, Task 6): ``hair_motion.rigid_joints`` / ``with_rigid`` /
``served_chains`` / ``panel``, the payload's 3-decimal ``freq_hz`` / ``zeta`` and the served-chains cache key.

Usage:
    ./.venv/bin/python scripts/smoke_hair_rigid_joints.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real world,
no hub, no server process.

FIXTURE GLB (built here, no mesh): nodes Hips (origin) → Head (local (0, 1.5, 0)) → the chain joints, every rotation
identity, inverse bind matrices = T(−world). World positions:
  HairGen_c00_00 (0, 1.62, −0.05), _01 (0, 1.55, −0.09), _02 (0, 1.45, −0.07), _end (0, 1.55, −0.01);
  HairGen_c01_00 (0.079, 1.55, 0), _01 (0.1, 1.45, 0), _end (0.1, 1.35, 0).
``collision.fit_capsules`` is replaced by a stand-in returning ONE head capsule a = b = Head with
b_pos (0, 1.6, 0), r = 0.08 × the head scale it is called with (the real fit scales the radius the same way) — the
GLB has no body to fit one on. Segment (0, 1.5, 0)–(0, 1.6, 0); distances by hand:
  c00_00: closest (0, 1.6, 0), √(0.02² + 0.05²) = 0.053852 → inside (< 0.08);
  c00_01: closest (0, 1.55, 0), 0.09 → outside;   c00_02: closest (0, 1.5, 0), √(0.05² + 0.07²) = 0.086023 → outside;
  c00_end: 0.01 → inside, but a leaf never counts;
  c01_00: closest (0, 1.55, 0), 0.079 → inside at scale 1 (r 0.08), outside at head scale 0.9 (r 0.072);
  c01_01: closest (0, 1.5, 0), √(0.1² + 0.05²) = 0.111803 → outside.
[1] rigid_joints: scale 1 → {c00_00, c01_00}; scale 0.9 → {c00_00}; the stand-in saw the head scale. A file whose
    capsule fit fails (the REAL fit_capsules on this mesh-less GLB → ValueError) is not readable for
    ``_rigid_of_fit`` → None (the recorded list stays).
[2] with_rigid: recorded rigid ["x"] + computed → ["x", c00_00]; ``_end`` and names of other chains are never added;
    the input summary is not mutated; rigid None → the same object.
[3] served_chains on a stored fit (garments/hair_demo_<fsig>.{glb,json}, chains c00 weighted [_00, _01, _02],
    stiffness 0.4 and c01 weighted [_00, _01], stiffness 0.32, both ``rigid: []`` as fit_hairdeck records them):
    c00 rigid [c00_00], c01 rigid [c01_00]; motion_groups → hair_c00 bones [_01, _02], freq_hz 0.4 × 3.7 = 1.48,
    hair_c01 bones [_01], freq_hz 0.32 × 3.7 = 1.184 — EXACTLY (rounded to 3 decimals; the float product is
    1.1840000000000002), zeta 0.5. Cache: a second poll does not read the fit again; a change of the profile's
    hair (hair_forward_m) is a miss; head scale 0.9 (model3d_opts.collision_scales) is a miss and gives c01
    rigid [] → hair_c01 bones [_00, _01].
[4] panel(Demo, profile, record, path): links = 2 + 1 = 3 at scale 1 (5 without the path — the recorded lists).
[5] FAILS ON THE OLD CODE (pinned c061f759): that commit's hair_motion.py, loaded from git, serves the same fit with
    rigid [] → hair_c00 bones [_00, _01, _02], and its freq_zeta(0.32)[0] is 1.1840000000000002, not 1.184.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "c061f759"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


JOINTS = [("mixamorig:Hips", None, (0.0, 0.0, 0.0)), ("mixamorig:Head", 0, (0.0, 1.5, 0.0)),
          ("HairGen_c00_00", 1, (0.0, 1.62, -0.05)), ("HairGen_c00_01", 2, (0.0, 1.55, -0.09)),
          ("HairGen_c00_02", 3, (0.0, 1.45, -0.07)), ("HairGen_c00_end", 4, (0.0, 1.55, -0.01)),
          ("HairGen_c01_00", 1, (0.079, 1.55, 0.0)), ("HairGen_c01_01", 6, (0.1, 1.45, 0.0)),
          ("HairGen_c01_end", 7, (0.1, 1.35, 0.0))]


def fixture_glb() -> bytes:
    """Nodes in skin order with LOCAL translations (world − parent world); IBMs = T(−world), column-major."""
    nodes = []
    for i, (name, parent, world) in enumerate(JOINTS):
        pw = JOINTS[parent][2] if parent is not None else (0.0, 0.0, 0.0)
        nodes.append({"name": name, "translation": [w - p for w, p in zip(world, pw)]})
    for i, (_, parent, _) in enumerate(JOINTS):
        if parent is not None:
            nodes[parent].setdefault("children", []).append(i)
    blob = b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -w[0], -w[1], -w[2], 1)
                    for _, _, w in JOINTS)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "skins": [{"joints": list(range(len(JOINTS))), "inverseBindMatrices": 0}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(JOINTS), "type": "MAT4"}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}],
           "buffers": [{"byteLength": len(blob)}]}
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def record():
    return {"accepted": True, "method": "hairdeck", "report": {"chains": {
        "count": 2, "dropped": 0, "cards_bound": 4, "cards_rigid": 0, "match": "ok",
        "chains": [{"index": 0, "bones": ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_02", "HairGen_c00_end"],
                    "weighted": ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_02"], "stiffness": 0.4,
                    "rigid": []},
                   {"index": 1, "bones": ["HairGen_c01_00", "HairGen_c01_01", "HairGen_c01_end"],
                    "weighted": ["HairGen_c01_00", "HairGen_c01_01"], "stiffness": 0.32, "rigid": []}]}}}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-rigid-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        from app.core import collision, garments
        from app.core import hair_motion as hm
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        glb = fixture_glb()
        real_fit = collision.fit_capsules
        seen = []

        def stand_in(blob, *, scales=None, extension=None):
            scale = float((scales or {}).get("head", 1.0))
            seen.append(scale)
            return {"version": collision.VERSION, "skipped": [], "scales": scales,
                    "capsules": [{"id": "head", "a": "mixamorig:Head", "b": "mixamorig:Head",
                                  "b_pos": [0.0, 1.6, 0.0], "r": 0.08 * scale, "region": "head"}]}

        # --- [1] rigid_joints --------------------------------------------------------
        print("[1] rigid_joints")
        collision.fit_capsules = stand_in
        check("scale 1", sorted(hm.rigid_joints(glb, scales={"head": 1.0})), ["HairGen_c00_00", "HairGen_c01_00"])
        check("scale 0.9", sorted(hm.rigid_joints(glb, scales={"head": 0.9})), ["HairGen_c00_00"])
        check("the capsule fit saw the head scale", seen[-2:], [1.0, 0.9])
        collision.fit_capsules = real_fit
        bad = root / "bad.glb"
        bad.write_bytes(glb)
        check("real fit on a mesh-less GLB → unreadable → None", hm._rigid_of_fit(bad, 1.0), None)
        collision.fit_capsules = stand_in

        # --- [2] with_rigid ------------------------------------------------------------
        print("[2] with_rigid")
        chains = record()["report"]["chains"]
        chains["chains"][0]["rigid"] = ["x"]
        before = json.dumps(chains)
        out = hm.with_rigid(chains, frozenset({"HairGen_c00_00", "HairGen_c00_end", "HairGen_c09_00"}))
        check("recorded + computed, leaf and foreign names never", [c["rigid"] for c in out["chains"]],
              [["x", "HairGen_c00_00"], []])
        check("input not mutated", json.dumps(chains), before)
        check("rigid None → same object", hm.with_rigid(chains, None) is chains, True)

        # --- [3] served_chains ---------------------------------------------------------
        print("[3] served_chains / motion_groups")
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female"},
                                                    create_new=True), True)
        inventory.add_item(name="Hair", category="garment", owner="Demo", item_id="hair_demo",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair"},
                           transferable=False, portable=False)
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored.update(hair_method="hairdeck", equipped_mesh_pieces={"hair": "hair_demo"})
            check("profile fixture", save_character_profile("Demo", stored), True)
        gdir = get_character_dir("Demo") / "garments"
        gdir.mkdir(parents=True, exist_ok=True)
        fit_path = gdir / "hair_demo_aaaaaaaaaaaa.glb"
        fit_path.write_bytes(glb)
        (gdir / "hair_demo_aaaaaaaaaaaa.json").write_text(json.dumps(record()))
        calls = []
        real_newest = garments._newest_fit

        def counted(*a, **k):
            calls.append(a)
            return real_newest(*a, **k)

        garments._newest_fit = counted
        profile = get_character_profile("Demo")
        served = hm.served_chains("Demo", profile)
        check("rigid filled", [c["rigid"] for c in served["chains"]], [["HairGen_c00_00"], ["HairGen_c01_00"]])
        groups = hm.motion_groups(served, {"swing": True, "stiffness": 1.0})
        check("bones", {k: v["bones"] for k, v in groups.items()},
              {"hair_c00": ["HairGen_c00_01", "HairGen_c00_02"], "hair_c01": ["HairGen_c01_01"]})
        check("freq_hz exactly 1.48 / 1.184, zeta 0.5",
              [(v["freq_hz"], v["zeta"]) for v in groups.values()], [(1.48, 0.5), (1.184, 0.5)])
        hm.served_chains("Demo", profile)
        check("second poll: no re-read", len(calls), 1)
        hm.served_chains("Demo", {**profile, "hair_forward_m": 0.002})
        check("profile hair change: miss", len(calls), 2)
        scaled = {**profile, "model3d_opts": {"collision_scales": {"head": 0.9}}}
        served9 = hm.served_chains("Demo", scaled)
        check("head scale change: miss", len(calls), 3)
        check("head scale 0.9: c01 rigid []", [c["rigid"] for c in served9["chains"]], [["HairGen_c00_00"], []])
        check("head scale 0.9: hair_c01 bones",
              hm.motion_groups(served9, {"swing": True, "stiffness": 1.0})["hair_c01"]["bones"],
              ["HairGen_c01_00", "HairGen_c01_01"])
        garments._newest_fit = real_newest
        check("stored record unchanged",
              [c["rigid"] for c in json.loads((gdir / "hair_demo_aaaaaaaaaaaa.json").read_text())
               ["report"]["chains"]["chains"]], [[], []])

        # --- [4] panel -------------------------------------------------------------------
        print("[4] panel")
        check("links with the fit path", hm.panel("Demo", profile, record(), fit_path)["links"], 3)
        check("links without the path (recorded lists)", hm.panel("Demo", profile, record())["links"], 5)

        # --- [5] fails on the old code ----------------------------------------------------
        print(f"[5] old code ({OLD_COMMIT})")
        try:
            source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/hair_motion.py"],
                                    check=True, capture_output=True, text=True).stdout
            old = types.ModuleType("hair_motion_old")
            exec(compile(source, f"{OLD_COMMIT}:app/core/hair_motion.py", "exec"), old.__dict__)
            old_groups = old.motion_groups(old.served_chains("Demo", profile), {"swing": True, "stiffness": 1.0})
            check("old: hair_c00 swings its head-capsule joint", old_groups["hair_c00"]["bones"],
                  ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_02"])
            check("old: freq_zeta(0.32) unrounded", old.freq_zeta(0.32)[0] != 1.184, True)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"  FAIL old-code proof: git show {OLD_COMMIT} failed: {e}")
            FAILS.append("old-code proof")
        collision.fit_capsules = real_fit

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
