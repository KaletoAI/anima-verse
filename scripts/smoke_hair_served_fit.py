#!/usr/bin/env python3
"""The hair chains of the motion payload come from the fit the served model grafts (review unit 07 #2):
``hair_motion.served_chains`` resolves its fit like the garment assembly does (``garment_store.accepted_fit`` on
the current base model), never merely the newest accepted fit of the item.

Usage:
    ./.venv/bin/python scripts/smoke_hair_served_fit.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real world,
no hub, no GPU, no server. ``base_body.current_base`` is a stand-in naming the base model BASE (no base model is
built here). The fit files are stubs (a GLB that is no glTF: ``rigid_joints`` cannot read it, so the recorded
``rigid`` lists stay); their records carry a hand-written ``report.chains`` with ONE chain (index 3, weighted
[_00, _01], rigid [], stiffness s) — the served stiffness tells which fit was read.

Fixture: Demo wears the HairDeck hairstyle hair_demo (Swing on). Three accepted HairDeck fits of hair_demo:
  A  hair_demo_<current fsig> (``garment_store.garment_fsig`` — the name the Build gives today's fit), on BASE,
     s = 0.4, oldest GLB mtime;
  B  hair_demo_bbbbbbbbbbbb (an older fingerprint, e.g. made with Swing off), on BASE, s = 0.6, newer;
  C  hair_demo_cccccccccccc, on another base model OTHER, s = 0.75, newest.

EXPECTED, BY HAND (``garment_store.accepted_fit``: the current-fsig fit when accepted on the base, else the newest
accepted fit of the current method ON THAT BASE; ``motion_groups`` freq_hz = 3.7 × s):
[1] served_chains -> A: stiffness 0.4, hair_c03 freq_hz 1.48. The newest fit (``garments._newest_fit``, what the
    old code read) is C; the code of commit 3f2ce338 (before the fix), loaded from git, serves C's chains:
    stiffness 0.75 — the finding.
[2] A removed: B (the newest on BASE; C is another base's) -> 0.6, freq_hz 2.22.
[3] Off the pipeline (``current_base`` None): the served model grafts no fit -> None.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "3f2ce338"
BASE_SHA = "5" * 64
OTHER_SHA = "6" * 64
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def stiffness_of(chains):
    rows = (chains or {}).get("chains") or []
    return rows[0].get("stiffness") if rows else None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-served-fit-") as tmp:
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

        from app.core import base_body, garment_store, garments
        from app.core import hair_motion as hm
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile
        base = {"value": ("b" * 12, BASE_SHA)}
        base_body.current_base = lambda name, profile=None: base["value"]

        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female"},
                                                    create_new=True), True)
        inventory.add_item(name="Hair", category="garment", owner="Demo", item_id="hair_demo",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair", "mesh_mode": "hairdeck",
                                    "description": "long hair", "hair_swing": "on"},
                           transferable=False, portable=False)
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored["equipped_mesh_pieces"] = {"hair": "hair_demo"}
            check("Demo wears hair_demo", save_character_profile("Demo", stored), True)
        profile = get_character_profile("Demo")
        current = garment_store.garment_fsig("Demo", "hair_demo", profile=profile)
        gdir = get_character_dir("Demo") / "garments"
        gdir.mkdir(parents=True, exist_ok=True)
        now = time.time()

        def fit(fsig, sha, stiffness, age):
            glb = gdir / f"hair_demo_{fsig}.glb"
            glb.write_bytes(b"glb-stub-" + fsig.encode())
            os.utime(glb, (now + age, now + age))
            glb.with_suffix(".json").write_text(json.dumps({
                "accepted": True, "method": "hairdeck", "base_model_sha256": sha, "report": {"chains": {
                    "count": 1, "chains": [{"index": 3, "bones": ["HairGen_c03_00", "HairGen_c03_01",
                                                                  "HairGen_c03_end"],
                                            "weighted": ["HairGen_c03_00", "HairGen_c03_01"], "rigid": [],
                                            "stiffness": stiffness}]}}}))
            return glb

        a = fit(current, BASE_SHA, 0.4, 0)
        fit("bbbbbbbbbbbb", BASE_SHA, 0.6, 10)
        fit("cccccccccccc", OTHER_SHA, 0.75, 20)

        print("[1] the served fit, not the newest")
        served = hm.served_chains("Demo", profile)
        check("A's chains (stiffness 0.4)", stiffness_of(served), 0.4)
        check("freq_hz 1.48", hm.motion_groups(served, {"swing": True, "stiffness": 1.0})["hair_c03"]["freq_hz"],
              1.48)
        newest = garments._newest_fit("Demo", "hair_demo", garment_store.HAIRDECK)
        check("the newest fit is C", newest[0].name if newest else None, "hair_demo_cccccccccccc.glb")
        try:
            source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/hair_motion.py"], check=True,
                                    capture_output=True, text=True).stdout
            old = types.ModuleType("hair_motion_old")
            exec(compile(source, f"{OLD}:app/core/hair_motion.py", "exec"), old.__dict__)
            check(f"old code ({OLD}) serves C's chains (the finding)", stiffness_of(old.served_chains("Demo", profile)),
                  0.75)
        except (subprocess.CalledProcessError, OSError) as e:
            check(f"old-code proof (git show {OLD})", str(e), "loaded")

        print("[2] the current fit missing: the newest on the CURRENT base")
        a.unlink()
        a.with_suffix(".json").unlink()
        check("B's chains (stiffness 0.6)", stiffness_of(hm.served_chains("Demo", profile)), 0.6)

        print("[3] off the pipeline")
        base["value"] = None
        check("no base: None", hm.served_chains("Demo", profile), None)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
