#!/usr/bin/env python3
"""The hair chains of the motion payload come from the fit the served model grafts (review unit 07 #2):
``hair_motion.served_chains`` resolves its fit like the garment assembly does (``garment_store.accepted_fit`` on
the current base model), never merely the newest accepted fit of the item — and the cached resolution
(``hair_motion._served_fit``) follows every input it is computed from.

Usage:
    ./.venv/bin/python scripts/smoke_hair_served_fit.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real world,
no hub, no GPU, no server. The base is REAL (``base_body.current_base``): Demo's base model
``model3d/<bsig>.glb`` is a stub file, BASE = its sha256. The fit files are stubs (a GLB that is no glTF:
``rigid_joints`` cannot read it, so the recorded ``rigid`` lists stay); their records carry a hand-written
``report.chains`` with ONE chain (index 3, weighted [_00, _01], rigid [], stiffness s) — the served stiffness tells
which fit was read. Every file change below sets its mtime explicitly (``os.utime``, distinct ns) and changes its
size, so no check depends on the filesystem's timestamp granularity.

Fixture: Demo wears the HairDeck hairstyle hair_demo (Swing on). Three accepted HairDeck fits of hair_demo:
  A  hair_demo_<current fsig> (``garment_store.garment_fsig`` — the name the Build gives today's fit), on BASE,
     s = 0.4, oldest GLB mtime;
  B  hair_demo_bbbbbbbbbbbb (an older fingerprint), on BASE, s = 0.6, newer;
  C  hair_demo_cccccccccccc, on another base model OTHER, s = 0.75, newest.

EXPECTED, BY HAND (``garment_store.accepted_fit``: the current-fsig fit when accepted on the base, else the newest
accepted fit of the current method ON THAT BASE by GLB mtime; ``motion_groups`` freq_hz = 3.7 × s):
[1] served_chains -> A: stiffness 0.4, hair_c03 freq_hz 1.48. The newest fit (``garments._newest_fit``, what the
    old code read) is C; the code of commit 3f2ce338 (before the fix), loaded from git, serves C's chains:
    stiffness 0.75 — the finding.
[2] Unchanged world, 3 more polls: 0 ``accepted_fit`` calls, 0 ``read_record`` calls, 0.4 each time.
[3] Fit replaced: A's record rewritten IN PLACE (no ``figure`` generation move, no directory change) with s 0.45
    -> 0.45; then through ``garment_store.write_record`` with s 0.5 -> 0.5.
[4] State switched: the profile names hair_demo open (``equipped_options.piece_state``) -> resolved again
    (1 ``accepted_fit`` call); a hairstyle is always judged closed, so still 0.5.
[5] Swing toggled off (``hair_motion.set_hair_motion``: the item's ``garment`` changes, so does its fsig): A is no
    longer the current fit -> the newest accepted fit on BASE: B (GLB mtime +10 > A's +0; C is OTHER's) -> 0.6.
    Refit under the Swing-off fsig: D on BASE, s 0.65, GLB mtime +30 -> 0.65.
[6] Base changed: the base model rewritten IN PLACE with other bytes (no generation move) -> BASE' = its new
    sha256; no fit is accepted on BASE' -> None. D's record moved onto BASE' with s 0.7 (``write_record``) -> 0.7.
[7] Base model removed (``current_base`` gives sha ""): the served model grafts no fit -> None.
"""
import hashlib
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

        from app.core import base_body, figure, garment_store, garments
        from app.core import hair_motion as hm
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

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
        folder = get_character_dir("Demo")
        now_ns = time.time_ns()
        tick = [0]

        def touch(path, offset_s=None):
            """A distinct mtime (ns) per change, or ``now + offset_s`` for a fit's GLB age."""
            tick[0] += 1
            ns = now_ns + int(offset_s * 1e9) if offset_s is not None else now_ns + 100_000_000_000 + tick[0] * 1000
            os.utime(path, ns=(ns, ns))

        bsig = base_body.base_signature("Demo", profile=profile)
        model = folder / "model3d" / f"{bsig}.glb"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"base-model-stub")
        touch(model)
        base_sha = hashlib.sha256(model.read_bytes()).hexdigest()
        check("current_base is the stub model", base_body.current_base("Demo", profile=profile), (bsig, base_sha))
        current = garment_store.garment_fsig("Demo", "hair_demo", profile=profile)
        gdir = folder / "garments"
        gdir.mkdir(parents=True, exist_ok=True)

        def record(sha, stiffness):
            return {"accepted": True, "method": "hairdeck", "base_model_sha256": sha, "report": {"chains": {
                "count": 1, "chains": [{"index": 3, "bones": ["HairGen_c03_00", "HairGen_c03_01", "HairGen_c03_end"],
                                        "weighted": ["HairGen_c03_00", "HairGen_c03_01"], "rigid": [],
                                        "stiffness": stiffness}]}}}

        def fit(fsig, sha, stiffness, age):
            glb = gdir / f"hair_demo_{fsig}.glb"
            glb.write_bytes(b"glb-stub-" + fsig.encode())
            touch(glb, age)
            glb.with_suffix(".json").write_text(json.dumps(record(sha, stiffness)))
            touch(glb.with_suffix(".json"))
            touch(gdir)
            return glb

        a = fit(current, base_sha, 0.4, 0)
        fit("bbbbbbbbbbbb", base_sha, 0.6, 10)
        fit("cccccccccccc", OTHER_SHA, 0.75, 20)

        calls = {"accepted_fit": 0, "read_record": 0}
        real_accepted, real_read = garment_store.accepted_fit, garment_store.read_record

        def counted_accepted(*args, **kwargs):
            calls["accepted_fit"] += 1
            return real_accepted(*args, **kwargs)

        def counted_read(*args, **kwargs):
            calls["read_record"] += 1
            return real_read(*args, **kwargs)

        garment_store.accepted_fit, garment_store.read_record = counted_accepted, counted_read

        def poll():
            """One worldmap poll: the stored profile, as ``extension_rig.motion_payload`` gets it."""
            calls["accepted_fit"] = calls["read_record"] = 0
            return stiffness_of(hm.served_chains("Demo", get_character_profile("Demo")))

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

        print("[2] an unchanged world costs no record read")
        for n in (1, 2, 3):
            check(f"poll {n}: A (0.4)", poll(), 0.4)
            check(f"poll {n}: accepted_fit / read_record calls", (calls["accepted_fit"], calls["read_record"]), (0, 0))

        print("[3] the fit replaced")
        generation = figure._generation[0]
        a.with_suffix(".json").write_text(json.dumps(record(base_sha, 0.45)))
        touch(a.with_suffix(".json"))
        check("in place: figure generation unchanged", figure._generation[0], generation)
        check("in place: 0.45", poll(), 0.45)
        garment_store.write_record(a.with_suffix(".json"), record(base_sha, 0.5))
        touch(a.with_suffix(".json"))
        check("write_record: 0.5", poll(), 0.5)
        check("then cached again: no accepted_fit call", (poll(), calls["accepted_fit"]), (0.5, 0))

        print("[4] the state switched")
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored["equipped_options"] = {"piece_state": {"hair_demo": "open"}}
            check("profile saved", save_character_profile("Demo", stored), True)
        check("resolved again, hair judged closed: 0.5", poll(), 0.5)
        check("one accepted_fit call", calls["accepted_fit"], 1)

        print("[5] Swing toggled, then refit")
        check("Swing off stored", hm.set_hair_motion("Demo", "hair_demo", False, None), True)
        swing_off = garment_store.garment_fsig("Demo", "hair_demo", profile=get_character_profile("Demo"))
        check("the fsig moved", swing_off != current, True)
        check("A not current: newest on BASE is B (0.6)", poll(), 0.6)
        fit(swing_off, base_sha, 0.65, 30)
        check("refit D: 0.65", poll(), 0.65)

        print("[6] the base changed")
        generation = figure._generation[0]
        model.write_bytes(b"base-model-stub-rebuilt")
        touch(model)
        new_sha = hashlib.sha256(model.read_bytes()).hexdigest()
        check("in place: figure generation unchanged", figure._generation[0], generation)
        check("no fit on the new base: None", poll(), None)
        check("current_base names the new model", base_body.current_base("Demo")[1], new_sha)
        d = gdir / f"hair_demo_{swing_off}.json"
        garment_store.write_record(d, record(new_sha, 0.7))
        touch(d)
        check("D moved onto the new base: 0.7", poll(), 0.7)

        print("[7] no base model")
        model.unlink()
        check("no base model: None", poll(), None)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
