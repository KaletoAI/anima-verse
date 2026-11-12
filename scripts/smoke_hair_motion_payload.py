#!/usr/bin/env python3
"""HairDeck hair chains as a core motion source (plan docs/superpowers/plans/2026-11-12-hairdeck-spring-chains.md,
Task 5): ``app/core/hair_motion.py``, its merge into ``extension_rig.motion_payload``, the hair payload's
``hairdeck.chains`` block and ``POST /characters/{n}/hair/motion``.

Usage:
    ./.venv/bin/python scripts/smoke_hair_motion_payload.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real world,
no hub, no GPU, no server process. No skill package is loaded, so the character has no pack motion groups. The fit
record is a stub: ``garments/hair_demo_<fsig>.{glb,json}`` with ``accepted`` true, method ``hairdeck`` and a
hand-written ``report.chains``. The characters router is mounted on a bare FastAPI app with real sessions
(pattern of scripts/smoke_hair_tab_method.py).

EXPECTED VALUES, DERIVED BY HAND FROM THE TASK BRIEF AND THE LEDGER (K = HAIR_FREQ_PER_STIFFNESS = 3.7 Hz per
unit, Ruling H1a; zeta 0.5; limits 0.8..6.0 Hz)
[1] freq_zeta: 0.32 -> (0.32·3.7 = 1.184, 0.5); 0.75 × 2.0 = 1.5 -> min(1.5·3.7 = 5.55, 6.0) = 5.55;
    0.2 × 0.5 = 0.1 -> max(0.1·3.7 = 0.37, 0.8) = 0.8. And 2.0 -> min(7.4, 6.0) = 6.0.
[2] settings (Ruling H11: Swing defaults to HAIR_SWING_DEFAULT = False): {} -> {swing False, stiffness 1.0};
    hair_swing "off" -> swing False; "on" -> True; "" or "maybe" -> the default, False;
    hair_stiffness "abc" -> 1.0, 2.5 (> 2.0) -> 1.0, true -> 1.0, "1.5" -> 1.5, 0.5 -> 0.5.
    set_hair_motion(Demo, True, 0.4) -> ValueError (0.4 < 0.5), set_hair_motion(Demo, "yes", 1.0) -> ValueError
    (no bool), set_hair_motion(Demo, True, "nan") -> ValueError: the profile keeps its values (the fixture's
    hair_swing "on", no hair_stiffness).
[3] motion_groups on a summary with chain 3 (weighted [_00, _01, _02], rigid [_00], stiffness 0.4) and chain 5
    (weighted [_00], rigid [_00], stiffness 0.3), settings {swing True, stiffness 1.0}, gravity_scale 1.0:
    - exactly one group "hair_c03", bones [HairGen_c03_01, HairGen_c03_02] (no _00: rigid; no _end), hair True,
      freq_hz = freq_zeta(0.4·1.0)[0] = 1.48, zeta 0.5, gravity 0.15, max_deg 35.0, sag_max_deg 10.0,
      rigid_tail 0, rest_deg 0, gravity_scale 1.0, scale_axis "centroid";
      the other MOTION_FIELDS are RigSpec's defaults: length 1.0, girth 1.0, spill 0.0, flatten 0.0,
      stretch 0.0, spread 0.5, flatten_floor = squash[0] = 0.6, translate 0.0, gain 1.0, spill_max_deg 25.0,
      head_sag 1.0, squash [0.6, 1.4], axis_gain [1, 1, 1], rest_max_deg 90.0, straighten_deg 0.0,
      freetext_clothing_gain 1.0;
    - chain 5 is absent (its only weighted bone is rigid);
    - a chain listing its _end as weighted keeps it out (Ruling H4); a malformed chain row is skipped;
    - with ``anchor_blend`` rows (chain 3: _00 Head 1, _01 Head 0.4 / Spine2 0.6 / Neck 0, _02 Spine2 1 / Head nan,
      _end and a foreign HairGen_c09_00 too; chain 5: _00 Head 0.7 / Spine2 0.3): hair_c03 carries
      {_00: {Head 1}, _01: {Head 0.4, Spine2 0.6}, _02: {Spine2 1}} (the rigid _00 kept — it rides today's skin
      without a swing; _end, the foreign joint, the zero and the nan share dropped) and anchor_from
      "mixamorig:Head"; chain 5 becomes a rows-only group (bones [], its _00 row); without rows no anchor key;
    - swing off -> {}; chains None -> {}.
    Stiffness factor 1.5 -> chain 3 freq_zeta(0.6) = 2.22.
[4] motion_payload(Demo) — no pack declarations, the stub fit record has the summary of [3]:
    groups == {"hair_c03": …} with freq_hz 1.48 and gravity_scale = the profile's motion_gravity_scale (0.5 here).
    Fails on the old code: extension_rig.py of commit 8076597d (the task BASE in the ledger), loaded from git,
    returns groups {} for the same character (its early return ``if not declarations`` came first).
    Stiffness factor 1.5 (set_hair_motion) -> rev changes, freq_hz 2.22. Swing off -> groups {} and the rev equals
    the no-hair rev of the old code (``_revision({"declarations": []})``), so a character without hair keeps its
    rev byte for byte. The fixture profile has hair_swing "on" (the default is off since Ruling H11).
    served_chains cache: a second call with the garments/ directory unchanged does not call _newest_fit again
    (1 call for 2 polls); a new record file in garments/ (a newer fit, chain 3 stiffness 0.6) changes the
    directory mtime -> re-read, freq_hz = 0.6·3.7 = 2.22. Method "body" -> None. No worn hair -> None.
[5] panel(Demo, profile, record): {count 2, links 2 (chain 3's two bones; chain 5 has none), swing True,
    stiffness 1.0, limits [0.5, 2.0], fitted True}; record None -> {count None, links 0, fitted False}; a record
    without report.chains -> fitted False, count None. garments.hairdeck_panel(Demo, hair_demo)["chains"] is that
    block for the newest HairDeck fit.
[6] Route (``garments.start_garment`` recorded, not run): player session -> 403, nothing stored. Admin: stiffness
    2.1 -> 400, swing "yes" -> 400, the profile unchanged; {swing false, stiffness 1.5} -> 200 {swing false,
    stiffness 1.5, refit true}, profile hair_swing "off", hair_stiffness 1.5, one fit-only run of hair_demo
    (steps "fit" — Swing is a fit input, Ruling H11); {swing true, stiffness null} -> 200 {swing true, stiffness
    1.0, refit true}, stored ("on", ""), a second run; {swing true, stiffness 1.2} -> refit false, no third run
    (Stiffness is motion only).
    Unknown character -> 404. The profile write runs under the lock (scripts/smoke_profile_rmw_lock.py).
[7] Fit fingerprint (Ruling H11): with hair_swing "off", "" or "maybe" (Swing off) ``garment_fsig`` equals the one
    of ``garment_store.py`` at 47290755 (before Swing was a fit input), so the boot refit sweep refits a hair 9 fit
    under its own fingerprint; with "on" it differs (``swing: True`` joins the payload).
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

FAILS = []
FSIG_BASE = "47290755"
BASE_COMMIT = "8076597d"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def close(label, got, want, tol=1e-9):
    ok = got is not None and abs(float(got) - float(want)) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def raises(label, fn):
    try:
        fn()
    except ValueError as e:
        print(f"  OK   {label}: ValueError {e}")
        return
    print(f"  FAIL {label}: no ValueError")
    FAILS.append(label)


def summary(stiffness3=0.4):
    return {"count": 2, "dropped": 0, "cards_bound": 10, "cards_rigid": 1, "match": "ok",
            "chains": [{"index": 3, "bones": ["HairGen_c03_00", "HairGen_c03_01", "HairGen_c03_02", "HairGen_c03_end"],
                        "weighted": ["HairGen_c03_00", "HairGen_c03_01", "HairGen_c03_02"],
                        "stiffness": stiffness3, "rigid": ["HairGen_c03_00"]},
                       {"index": 5, "bones": ["HairGen_c05_00", "HairGen_c05_end"], "weighted": ["HairGen_c05_00"],
                        "stiffness": 0.3, "rigid": ["HairGen_c05_00"]}]}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-motion-") as tmp:
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

        from app.core import hair_motion as hm
        from app.core import extension_rig, garments, sessions, users
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        # --- [1] freq_zeta -------------------------------------------------------
        print("[1] freq_zeta (K = %s)" % hm.HAIR_FREQ_PER_STIFFNESS)
        check("K from the ledger (Ruling H1a)", hm.HAIR_FREQ_PER_STIFFNESS, 3.7)
        f, z = hm.freq_zeta(0.32)
        close("0.32 -> freq", f, 1.184)
        check("0.32 -> zeta", z, 0.5)
        close("0.75 x 2.0 -> 5.55", hm.freq_zeta(0.75 * 2.0)[0], 5.55)
        close("0.2 x 0.5 -> floor 0.8", hm.freq_zeta(0.2 * 0.5)[0], 0.8)
        close("2.0 -> cap 6.0", hm.freq_zeta(2.0)[0], 6.0)

        # --- fixture -------------------------------------------------------------
        check("create Demo", save_character_profile("Demo", {"template": "human-roleplay", "gender": "female"},
                                                    create_new=True), True)
        inventory.add_item(name="Hair", category="garment", owner="Demo", item_id="hair_demo",
                           garment={"kind": "hair", "slot": "hair", "body_slot": "hair"},
                           transferable=False, portable=False)
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored.update(hair_method="hairdeck", equipped_mesh_pieces={"hair": "hair_demo"},
                          motion_gravity_scale=0.5, hair_swing="on")
            check("profile fixture", save_character_profile("Demo", stored), True)

        def profile():
            return get_character_profile("Demo") or {}

        # --- [2] settings ----------------------------------------------------------
        print("[2] settings and set_hair_motion")
        check("default swing off (H11)", hm.HAIR_SWING_DEFAULT, False)
        check("{} -> defaults", hm.settings({}), {"swing": False, "stiffness": 1.0})
        check("None -> defaults", hm.settings(None), {"swing": False, "stiffness": 1.0})
        check("swing off", hm.settings({"hair_swing": "off"})["swing"], False)
        check("swing 'on' -> on", hm.settings({"hair_swing": "on"})["swing"], True)
        for raw in ("", "maybe"):
            check(f"swing {raw!r} -> the default", hm.settings({"hair_swing": raw})["swing"], False)
        for raw, want in (("abc", 1.0), (2.5, 1.0), (True, 1.0), ("1.5", 1.5), (0.5, 0.5), ("", 1.0)):
            check(f"stiffness {raw!r}", hm.settings({"hair_stiffness": raw})["stiffness"], want)
        raises("stiffness 0.4 refused", lambda: hm.set_hair_motion("Demo", True, 0.4))
        raises("swing 'yes' refused", lambda: hm.set_hair_motion("Demo", "yes", 1.0))
        raises("stiffness nan refused", lambda: hm.set_hair_motion("Demo", True, "nan"))
        check("profile untouched", (profile().get("hair_swing"), "hair_stiffness" in profile()), ("on", False))

        # --- [3] motion_groups -----------------------------------------------------
        print("[3] motion_groups")
        on = {"swing": True, "stiffness": 1.0}
        groups = hm.motion_groups(summary(), on)
        check("one group hair_c03", sorted(groups), ["hair_c03"])
        g = groups.get("hair_c03", {})
        check("bones", g.get("bones"), ["HairGen_c03_01", "HairGen_c03_02"])
        check("hair flag", g.get("hair"), True)
        close("freq_hz = freq_zeta(0.4)", g.get("freq_hz"), hm.freq_zeta(0.4)[0])
        close("freq_hz = 1.48", g.get("freq_hz"), 1.48)
        check("hair constants", (g.get("zeta"), g.get("gravity"), g.get("max_deg"), g.get("sag_max_deg"),
                                 g.get("rigid_tail"), g.get("rest_deg"), g.get("gravity_scale"),
                                 g.get("scale_axis")),
              (0.5, 0.15, 35.0, 10.0, 0, 0.0, 1.0, "centroid"))
        defaults = {"length": 1.0, "girth": 1.0, "spill": 0.0, "flatten": 0.0, "stretch": 0.0, "spread": 0.5,
                    "flatten_floor": 0.6, "translate": 0.0, "gain": 1.0, "spill_max_deg": 25.0, "head_sag": 1.0,
                    "squash": [0.6, 1.4], "axis_gain": [1.0, 1.0, 1.0], "rest_max_deg": 90.0,
                    "straighten_deg": 0.0, "freetext_clothing_gain": 1.0}
        check("RigSpec defaults", {k: g.get(k) for k in defaults}, defaults)
        check("every MOTION_FIELDS key present", sorted(set(extension_rig.MOTION_FIELDS) - set(g)), [])
        bad = summary()
        bad["chains"][0]["weighted"].append("HairGen_c03_end")
        bad["chains"].append({"index": "x", "weighted": ["HairGen_c07_00"], "stiffness": 0.4})
        bad["chains"].append({"index": 8, "weighted": ["HairGen_c08_00"]})
        check("_end never a bone, malformed rows skipped",
              {k: v["bones"] for k, v in hm.motion_groups(bad, on).items()},
              {"hair_c03": ["HairGen_c03_01", "HairGen_c03_02"]})
        # anchor_blend (Ruling H11): the rows of the chain's weighted joints, its rigid _00 included, never _end or
        # a foreign joint, non-positive / non-finite shares dropped; anchor_from = Head; a chain whose every joint
        # is rigid keeps a rows-only group (bones [])
        rows = summary()
        head, spine = "mixamorig:Head", "mixamorig:Spine2"
        rows["chains"][0]["anchor_blend"] = {
            "HairGen_c03_00": {head: 1.0}, "HairGen_c03_01": {head: 0.4, spine: 0.6, "mixamorig:Neck": 0.0},
            "HairGen_c03_02": {spine: 1.0, head: float("nan")}, "HairGen_c03_end": {spine: 1.0},
            "HairGen_c09_00": {head: 1.0}}
        rows["chains"][1]["anchor_blend"] = {"HairGen_c05_00": {head: 0.7, spine: 0.3}}
        rg = hm.motion_groups(rows, on)
        check("anchor_blend rows of the weighted joints (rigid _00 kept, _end / foreign dropped)",
              rg.get("hair_c03", {}).get("anchor_blend"),
              {"HairGen_c03_00": {head: 1.0}, "HairGen_c03_01": {head: 0.4, spine: 0.6},
               "HairGen_c03_02": {spine: 1.0}})
        check("anchor_from = Head", rg.get("hair_c03", {}).get("anchor_from"), "mixamorig:Head")
        check("all-rigid chain 5 -> rows-only group",
              (rg.get("hair_c05", {}).get("bones"), rg.get("hair_c05", {}).get("anchor_blend")),
              ([], {"HairGen_c05_00": {head: 0.7, spine: 0.3}}))
        check("no anchor_blend -> no anchor keys", sorted(k for k in g if k.startswith("anchor")), [])
        check("swing off -> {}", hm.motion_groups(summary(), {"swing": False, "stiffness": 1.0}), {})
        check("chains None -> {}", hm.motion_groups(None, on), {})
        close("factor 1.5 -> freq_zeta(0.6) = 2.22",
              hm.motion_groups(summary(), {"swing": True, "stiffness": 1.5})["hair_c03"]["freq_hz"], 2.22)

        # --- [4] motion_payload ----------------------------------------------------
        print("[4] motion_payload")
        gdir = get_character_dir("Demo") / "garments"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "hair_demo_aaaaaaaaaaaa.glb").write_bytes(b"glb-stub")
        (gdir / "hair_demo_aaaaaaaaaaaa.json").write_text(json.dumps(
            {"accepted": True, "method": "hairdeck", "report": {"chains": summary()}}))
        calls = []
        real_newest = garments._newest_fit

        def counted(*a, **k):
            calls.append(a)
            return real_newest(*a, **k)

        garments._newest_fit = counted
        p1 = extension_rig.motion_payload("Demo")
        check("hair groups without pack groups", sorted(p1["groups"]), ["hair_c03"])
        close("freq_hz 1.48", p1["groups"].get("hair_c03", {}).get("freq_hz"), 1.48)
        check("gravity_scale = the profile's", p1["groups"].get("hair_c03", {}).get("gravity_scale"), 0.5)
        extension_rig.motion_payload("Demo")
        check("served_chains cache: 1 _newest_fit for 2 polls", len(calls), 1)

        # fails on the old code: extension_rig.py of the task BASE, loaded from git
        try:
            source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/extension_rig.py"],
                                    check=True, capture_output=True, text=True).stdout
            old = types.ModuleType("extension_rig_base")
            exec(compile(source, f"{BASE_COMMIT}:app/core/extension_rig.py", "exec"), old.__dict__)
            check(f"old code ({BASE_COMMIT}) drops the hair groups", old.motion_payload("Demo")["groups"], {})
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"  FAIL old-code proof: git show {BASE_COMMIT} failed: {e}")
            FAILS.append("old-code proof")

        check("set stiffness 1.5", hm.set_hair_motion("Demo", True, 1.5), True)
        p2 = extension_rig.motion_payload("Demo")
        check("rev changes with the stiffness", p2["rev"] != p1["rev"], True)
        close("freq_hz 2.22", p2["groups"]["hair_c03"]["freq_hz"], 2.22)
        check("swing off", hm.set_hair_motion("Demo", False, 1.5), True)
        p3 = extension_rig.motion_payload("Demo")
        check("swing off -> no groups", p3["groups"], {})
        check("swing off -> the no-hair rev of the old code", p3["rev"],
              extension_rig._revision({"declarations": []}))
        check("back to defaults", hm.set_hair_motion("Demo", True, None), True)

        # a newer fit record in garments/ -> new directory mtime -> re-read
        time.sleep(0.01)
        newer = gdir / "hair_demo_bbbbbbbbbbbb.glb"
        newer.write_bytes(b"glb-stub-2")
        later = time.time() + 5
        os.utime(newer, (later, later))
        (gdir / "hair_demo_bbbbbbbbbbbb.json").write_text(json.dumps(
            {"accepted": True, "method": "hairdeck", "report": {"chains": summary(0.6)}}))
        n = len(calls)
        p4 = extension_rig.motion_payload("Demo")
        check("directory change re-reads", len(calls), n + 1)
        close("newest fit: freq_zeta(0.6) = 2.22", p4["groups"]["hair_c03"]["freq_hz"], 2.22)
        garments._newest_fit = real_newest
        check("method body -> None", hm.served_chains("Demo", {**profile(), "hair_method": "body"}), None)
        check("no worn hair -> None", hm.served_chains("Demo", {**profile(), "equipped_mesh_pieces": {}}), None)
        check("foreign item -> None",
              hm.served_chains("Demo", {**profile(), "equipped_mesh_pieces": {"hair": "nobody_hair"}}), None)

        # --- [5] panel -------------------------------------------------------------
        print("[5] panel")
        record = {"accepted": True, "method": "hairdeck", "report": {"chains": summary()}}
        check("panel with chains", hm.panel("Demo", profile(), record),
              {"count": 2, "links": 2, "swing": True, "stiffness": 1.0, "limits": [0.5, 2.0], "fitted": True})
        check("panel without a fit", hm.panel("Demo", profile(), None),
              {"count": None, "links": 0, "swing": True, "stiffness": 1.0, "limits": [0.5, 2.0], "fitted": False})
        check("panel of a pre-chain fit", hm.panel("Demo", profile(), {"accepted": True, "report": {}})["fitted"],
              False)
        try:
            block = (garments.hairdeck_panel("Demo", "hair_demo", profile=profile()) or {}).get("chains")
        except Exception as e:  # noqa: BLE001 — reported as a failure below
            block = f"{type(e).__name__}: {e}"
        newest = real_newest("Demo", "hair_demo", "hairdeck")
        check("hairdeck_panel carries the block", block, hm.panel("Demo", profile(), newest[1] if newest else None))

        # --- [6] route -------------------------------------------------------------
        print("[6] POST /characters/{n}/hair/motion")
        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role, allowed_characters=["Demo"])
            tokens[role] = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)
        url = "/characters/Demo/hair/motion"
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            check("player -> 403", client.post(url, json={"swing": False, "stiffness": 1.5}).status_code, 403)
            check("player stored nothing", profile().get("hair_swing"), "on")
            runs = []
            real_start = garments.start_garment
            garments.start_garment = lambda name, item_id, **kw: runs.append((name, item_id, kw)) or {"started": True}
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])
            before = (profile().get("hair_swing"), profile().get("hair_stiffness"))
            check("stiffness 2.1 -> 400", client.post(url, json={"swing": True, "stiffness": 2.1}).status_code, 400)
            check("swing 'yes' -> 400", client.post(url, json={"swing": "yes", "stiffness": 1.0}).status_code, 400)
            check("refused -> profile unchanged", (profile().get("hair_swing"), profile().get("hair_stiffness")),
                  before)
            r = client.post(url, json={"swing": False, "stiffness": 1.5})
            check("{false, 1.5} -> 200", (r.status_code, r.json()),
                  (200, {"swing": False, "stiffness": 1.5, "refit": True}))
            check("stored", (profile().get("hair_swing"), profile().get("hair_stiffness")), ("off", 1.5))
            check("swing change -> one fit-only run", runs, [("Demo", "hair_demo", {"steps": "fit"})])
            r = client.post(url, json={"swing": True, "stiffness": None})
            check("{true, null} -> 200 defaults", (r.status_code, r.json()),
                  (200, {"swing": True, "stiffness": 1.0, "refit": True}))
            check("stored as on / ''", (profile().get("hair_swing"), profile().get("hair_stiffness")), ("on", ""))
            r = client.post(url, json={"swing": True, "stiffness": 1.2})
            check("stiffness only -> no refit", (r.json().get("refit"), len(runs)), (False, 2))
            garments.start_garment = real_start
            check("unknown character -> 404",
                  client.post("/characters/Nobody/hair/motion", json={"swing": True}).status_code, 404)

        # --- [7] fit fingerprint -------------------------------------------------------
        print("[7] garment_fsig and Swing (Ruling H11)")
        from app.core import garment_store as gs
        try:
            src = subprocess.run(["git", "-C", str(ROOT), "show", f"{FSIG_BASE}:app/core/garment_store.py"],
                                 check=True, capture_output=True, text=True).stdout
            old_gs = types.ModuleType("garment_store_base")
            exec(compile(src, f"{FSIG_BASE}:app/core/garment_store.py", "exec"), old_gs.__dict__)
            for raw in ("off", "", "maybe"):
                prof = {**profile(), "hair_swing": raw}
                check(f"swing {raw!r}: the fsig of {FSIG_BASE}", gs.garment_fsig("Demo", "hair_demo", profile=prof),
                      old_gs.garment_fsig("Demo", "hair_demo", profile=prof))
            on_prof = {**profile(), "hair_swing": "on"}
            check("swing on: another fsig", gs.garment_fsig("Demo", "hair_demo", profile=on_prof)
                  != old_gs.garment_fsig("Demo", "hair_demo", profile=on_prof), True)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"  FAIL fsig proof: git show {FSIG_BASE} failed: {e}")
            FAILS.append("fsig proof")

    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
