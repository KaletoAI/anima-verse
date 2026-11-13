#!/usr/bin/env python3
"""Ruling A37 — the right stored attempt: of several stored attempts that
pass, the one NEAREST the worn piece is published; every stored attempt can
be used by hand ("Use this"), a refused one as an acceptance by the user.

Usage:
    ./.venv/bin/python scripts/smoke_attempt_pick_and_use.py

A throwaway storage + instance directory with a copy of the repo's ``human``
package; no world, no hub, no server. Every outbound socket connect is
refused and counted (must stay 0).

[1] ``garment_gates.attempt_distance`` by hand. Frame 1000 x 600, worn region
    R = rows [300, 500) x cols [200, 400) = 40000 px, the worn piece W = (200,
    180, 160) on R (brightness 180). An attempt covers R exactly (mask = R).
    colour = mean over R of mean_c |a - (mean(a) / mean(w)) x w|; structure =
    mean over R of |mean(a) x median(mean w) / median(mean a) - mean(w)|.
    A0 = W everywhere: colour 0, structure 0, score 0.
    A1 = W with its bottom quarter (rows [450, 500), 10000 px) in shadow
         D = (100, 90, 80) = W / 2: per pixel the hue is W's -> colour 0. The
         attempt's brightness: 30000 px at 180, 10000 at 90 -> median 180 ->
         exposure 180 / 180 = 1; |90 - 180| = 90 on a quarter -> structure
         90 x 10000 / 40000 = 22.5; score 22.5.
    A2 = (220, 180, 140) everywhere (mean 180, another hue): scale 1 ->
         (|220 - 200| + 0 + |140 - 160|) / 3 = 13.333; structure 0; score
         13.333.
    The overlap is the attempt's mask AND R: an attempt whose mask is R's left
    half (cols [200, 300)) is measured on 20000 px.
[2] ``garment_images._regate_stored`` with two stored attempts whose records
    are of an older gate version and that BOTH pass when judged again
    (attempt 1 = A1, attempt 2 = A2): with ``closeness`` (the ghost's: the
    attempt against the worn piece in R) attempt 2 is published (13.333 <
    22.5), the final records ``picked`` with both scores; without it (a step
    with no worn piece to compare) attempt 1 — the first that passes, as
    before. Both attempts carry their new records either way.
[3] "Use this" (``garments.use_attempt``, ``use_plans``, the route) on a
    throwaway world: Demo with an own-mesh Blouse. Fixture finals: worn front
    + back, ghost front (hem 0.65 / worn hem 0.65), cut-out front, the
    prepared mesh; the ghost back has two stored attempts, no final:
    attempt 1 refused ("skin left"), attempt 2 passing (hem 0.65 / 0.65), and
    a recorded chain failure of step ghost. The clothing cost table:
    worn 2, ghost 2, cutout 2, mesh 1, fit 0.
    Before: ``run_estimate`` = ghost (2 - 1 view kept) 1 + cutout 2 + mesh 1
    = 4 hub jobs, steps [ghost, cutout, mesh, fit].
    ``use_plans`` ghost back: attempt 1 passing False, attempt 2 True, both
    block "", in_use False, follow_up = the chain after the click: ghost done
    (both views; the pair agrees — a view taken by the user is never redone
    for the pair, a passing back at hem 0.65 agrees with the front), the
    cut-out back missing -> cutout (2 - 1) 1 + mesh 1 = 2 hub jobs, note
    "cutout 1 + mesh 1", steps [cutout, mesh, fit]; the worn views have no
    stored attempts.
    [3a] Use attempt 1 (refused): changed, user_accepted; the final record's
         ``user_accepted.inputs`` = {the worn back's file: its sha256}; the
         view counts accepted; the prepared mesh is gone; the chain failure is
         cleared; ``follow_up`` = 2 hub jobs "cutout 1 + mesh 1" = the plan's;
         the panel shows ``user_accepted.holds`` True; use_plans: attempt 1
         in_use, attempt 2 still usable with the same 2 jobs.
    [3b] Voided by an input change: the worn back rewritten -> the ghost back
         no longer counts accepted (holds False) and the estimate is the 4 of
         "Before" again; the worn back restored -> it holds again; the final
         file itself rewritten -> voided too.
    [3c] Use attempt 2 (passing): the record has no ``user_accepted``,
         ``used_by_hand.attempt`` 2, accepted; using it again: changed False.
    [3d] An attempt older than the worn back it edits (created_at before the
         worn back's): block "Made from an earlier image of the step
         before"; the use raises, the route answers 409, nothing changes.
    [3e] A garment run holds the piece's run lock: ``UseBusy``, route 409.
    [3f] The pair: a ghost back at hem 0.70 / worn 0.65 against the front at
         0.65 disagrees (|0.05| > HEM_AGREE 0.02); taken by the user, the pair
         counts as agreeing.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OUTBOUND = []


def check(label, got, want):
    ok = got == want
    tail = "" if ok else f" — expected {want!r}"[:400]
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + tail)
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol=1e-3):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def _refuse_connect(self, address, *a, **k):
    OUTBOUND.append(address)
    raise OSError("smoke: no outbound connections")


def arrays():
    import numpy as np
    region = np.zeros((1000, 600), dtype=bool)
    region[300:500, 200:400] = True
    W = (200, 180, 160)
    worn = np.full((1000, 600, 3), 128, dtype=np.uint8)
    worn[region] = W
    a0 = worn.copy()
    a1 = worn.copy()
    a1[450:500, 200:400] = (100, 90, 80)
    a2 = worn.copy()
    a2[region] = (220, 180, 140)
    return region, worn, a0, a1, a2


def part_distance():
    from app.core import garment_gates as gg
    print("[1] attempt_distance by hand")
    region, worn, a0, a1, a2 = arrays()
    d0 = gg.attempt_distance(worn, region, a0, region)
    check("A0: colour, structure, score, overlap", (d0["colour"], d0["structure"], d0["score"], d0["overlap"]),
          (0.0, 0.0, 0.0, 40000))
    d1 = gg.attempt_distance(worn, region, a1, region)
    near("A1 colour", d1["colour"], 0.0)
    near("A1 structure", d1["structure"], 22.5)
    near("A1 score", d1["score"], 22.5)
    d2 = gg.attempt_distance(worn, region, a2, region)
    near("A2 colour", d2["colour"], 13.333)
    near("A2 structure", d2["structure"], 0.0)
    near("A2 score", d2["score"], 13.333)
    half = region.copy()
    half[:, 300:] = False
    check("overlap = mask AND region", gg.attempt_distance(worn, region, a1, half)["overlap"], 20000)
    check("no overlap -> None", gg.attempt_distance(worn, region, a1, ~region), None)


def part_pick(tmp: Path):
    from PIL import Image
    from app.core import garment_clothing, garment_gates as gg, garment_images as gi
    from app.core.garment_store import garment_path, read_record, write_record
    print("[2] several stored attempts pass: the nearest wins")
    region, worn, _a0, a1, a2 = arrays()
    version = garment_clothing.GATE_VERSIONS["ghost"]

    def setup(who):
        item, fsig = "item_demo_blouse", "a1b2c3d4e5f6"
        for n, img in ((1, a1), (2, a2)):
            target = garment_path(who, item, fsig, "image", step="ghost", view="back", attempt=n)
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(img).save(target, format="PNG")
            write_record(target.with_suffix(".json"), {
                "garment": {"item_id": item, "fsig": fsig, "step": "ghost", "view": "back", "attempt": n},
                "gate": {"view": "back", "ok": False, "reasons": ["older gate"], "gate_version": version - 1,
                         "attempt": n}})
        return item, fsig, garment_path(who, item, fsig, "image", step="ghost", view="back")

    def regate(_path, old):
        return {"view": "back", "ok": True, "reasons": [], "gate_version": version}

    def closeness(path):
        with Image.open(path) as im:
            import numpy as np
            rgb = np.asarray(im.convert("RGB"))
        return gg.attempt_distance(worn, region, rgb, region)

    drop_later, gi._drop_later = gi._drop_later, lambda *a, **k: None
    try:
        item, fsig, final = setup("Pick")
        hit = gi._regate_stored("Pick", item, fsig, "ghost", "back", garment_clothing, final=final, regate=regate,
                                closeness=closeness)
        rec = read_record(final.with_suffix(".json"))
        check("with closeness: attempt 2 published", (hit == final, rec.get("accepted"), rec.get("attempt")),
              (True, True, 2))
        scores = {k: v["score"] for k, v in (rec.get("picked") or {}).get("scores", {}).items()}
        near("picked score attempt 1", scores.get("1"), 22.5)
        near("picked score attempt 2", scores.get("2"), 13.333)
        both = [read_record(garment_path("Pick", item, fsig, "image", step="ghost", view="back", attempt=n)
                            .with_suffix(".json")).get("gate", {}) for n in (1, 2)]
        check("both judged again", [(g.get("ok"), g.get("regated_from")) for g in both],
              [(True, version - 1), (True, version - 1)])
        item, fsig, final = setup("First")
        gi._regate_stored("First", item, fsig, "ghost", "back", garment_clothing, final=final, regate=regate)
        rec = read_record(final.with_suffix(".json"))
        check("without closeness: attempt 1 (the first)", (rec.get("attempt"), "picked" in rec), (1, False))
    finally:
        gi._drop_later = drop_later


def part_use(root: Path):
    from fastapi import HTTPException
    from app.core import base_body, garment_images as gi, garment_source, garments
    from app.core import garment_store as gs
    from app.models import inventory
    from app.models.character import save_character_profile
    from app.routes import characters as routes
    print("[3] Use this")
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
             "character_appearance": "slender",
             "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"}, "build": {"type": "athletic"},
                            "hair": {"length": "medium", "color": "blonde"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)
    bid = inventory.add_item(name="Blouse", category="outfit_piece", prompt_fragment="a white blouse",
                             outfit_piece={"slots": ["top"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
    check("inventory", inventory.add_to_inventory("Demo", bid), True)
    check("equip", inventory.equip_piece("Demo", bid, source="smoke")["status"], "ok")
    fsig = gs.garment_fsig("Demo", bid)
    check("on the pipeline", base_body.current_base("Demo") is not None, True)
    ghost_v = gi._kind_module(bid).GATE_VERSIONS["ghost"]
    OK_GHOST = {"ok": True, "hem_c": 0.65, "worn_hem_c": 0.65, "gate_version": ghost_v}

    def path(step, view, attempt=0):
        return gs.garment_path("Demo", bid, fsig, "image", step=step, view=view, attempt=attempt)

    def put(step, view, record=None, extra=None):
        p = path(step, view)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"fixture-{step}-{view}".encode())
        rec = dict(record or (OK_GHOST if step == "ghost" else {"ok": True, "gate_version": 4}), attempt=1)
        gs.write_record(p.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": rec},
                                                 "created_at": "2026-11-13T22:00:00+00:00", **(extra or {})})

    def attempt(n, gate, created="2026-11-13T23:00:00+00:00"):
        p = path("ghost", "back", n)
        p.write_bytes(f"ghost-back-try{n}".encode())
        gs.write_record(p.with_suffix(".json"), {"garment": {"step": "ghost", "view": "back", "attempt": n},
                                                 "created_at": created, "gate": {**gate, "attempt": n}})

    put("worn", "front")
    put("worn", "back", extra={"fit": "composite", "front_sha256": base_body.file_sha256(path("worn", "front"))})
    put("ghost", "front")
    put("cutout", "front", record={"ok": True})
    prepared = gs.garment_path("Demo", bid, fsig, "prepared")
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_bytes(b"glb")
    gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
    attempt(1, {"view": "back", "ok": False, "reasons": ["skin left in the image: 0.0151 > 0.005"],
                "gate_version": ghost_v})
    attempt(2, {"view": "back", **OK_GHOST})
    gs.record_failure("Demo", bid, fsig, step="ghost", error="ghost back refused — skin left")

    def est():
        e = garments.run_estimate("Demo", bid)
        return e["hub_jobs"], e["note"], e["steps"]

    def brief(plan):
        f = plan["follow_up"]
        return (plan["passing"], plan["in_use"], plan["block"], f and (f["hub_jobs"], f["note"], f["steps"]))

    two = (2, "cutout 1 + mesh 1", ["cutout", "mesh", "fit"])
    four = (4, "ghost 1 + cutout 2 + mesh 1", ["ghost", "cutout", "mesh", "fit"])
    with patch.object(garment_source, "find_source", lambda *a, **k: None):
        check("before: run_estimate", est(), four)
        plans = garments.use_plans("Demo", bid)
        back = plans["ghost"]["back"]
        check("plan attempt 1 (refused)", brief(back["1"]), (False, False, "", two))
        check("plan attempt 2 (passing)", brief(back["2"]), (True, False, "", two))
        check("no worn attempts", plans.get("worn"), None)

        print("[3a] use the refused attempt")
        res = garments.use_attempt("Demo", bid, "ghost", "back", 1)
        check("result", (res["changed"], res["passing"], res["user_accepted"]), (True, False, True))
        check("follow_up = the plan's", (res["follow_up"]["hub_jobs"], res["follow_up"]["note"],
                                         res["follow_up"]["steps"]), two)
        rec = gs.read_record(path("ghost", "back").with_suffix(".json"))
        check("user_accepted.inputs", rec["user_accepted"]["inputs"],
              {path("worn", "back").name: base_body.file_sha256(path("worn", "back"))})
        check("user_accepted attempt + sha", (rec["user_accepted"]["attempt"], rec["user_accepted"]["attempt_sha256"]),
              (1, base_body.file_sha256(path("ghost", "back", 1))))
        check("view accepted", gi._accepted(path("ghost", "back")), True)
        check("mesh dropped", prepared.is_file(), False)
        check("failure cleared", gs.chain_failure("Demo", bid, fsig), None)
        check("estimate after", est(), two)
        info = garments._image_info("Demo", bid, fsig, "ghost", "back")
        check("panel: accepted, holds", (info["accepted"], info["user_accepted"]["holds"]), (True, True))
        back = garments.use_plans("Demo", bid)["ghost"]["back"]
        check("plans after: attempt 1 in use", brief(back["1"]), (False, True, "", None))
        check("plans after: attempt 2 usable", brief(back["2"]), (True, False, "", two))

        print("[3b] voided by an input change")
        worn_back = path("worn", "back")
        kept = worn_back.read_bytes()
        worn_back.write_bytes(b"another worn back")
        check("worn back changed: not accepted", gi._accepted(path("ghost", "back")), False)
        info = garments._image_info("Demo", bid, fsig, "ghost", "back")
        check("panel: accepted, holds", (info["accepted"], info["user_accepted"]["holds"]), (False, False))
        check("estimate: the ghost is due again", est(), four)
        worn_back.write_bytes(kept)
        check("worn back restored: holds again", gi._accepted(path("ghost", "back")), True)
        final = path("ghost", "back")
        taken = final.read_bytes()
        final.write_bytes(b"edited")
        check("the image itself changed: voided", gi._accepted(final), False)
        final.write_bytes(taken)

        print("[3c] use the passing attempt")
        res = garments.use_attempt("Demo", bid, "ghost", "back", 2)
        rec = gs.read_record(path("ghost", "back").with_suffix(".json"))
        check("passing: no user_accepted", (res["changed"], res["passing"], "user_accepted" in rec,
                                            rec["used_by_hand"]["attempt"], rec["attempt"]), (True, True, False, 2, 2))
        check("accepted", gi._accepted(path("ghost", "back")), True)
        check("again: changed False", garments.use_attempt("Demo", bid, "ghost", "back", 2)["changed"], False)

        print("[3d] an attempt older than the image it edits")
        attempt(1, {"view": "back", "ok": False, "reasons": ["hem"], "gate_version": ghost_v},
                created="2026-11-13T21:00:00+00:00")
        check("block", garments.use_plans("Demo", bid)["ghost"]["back"]["1"]["block"], gi.EARLIER_SOURCE)
        try:
            garments.use_attempt("Demo", bid, "ghost", "back", 1)
            check("use raises", "used", "AttemptUnusable")
        except gi.AttemptUnusable as e:
            check("use raises", str(e), gi.EARLIER_SOURCE)
        try:
            routes.use_character_garment_attempt("Demo", bid, "ghost", "back", 1, {})
            check("route 409", "ok", 409)
        except HTTPException as e:
            check("route 409", (e.status_code, e.detail), (409, gi.EARLIER_SOURCE))
        check("nothing changed", gs.read_record(path("ghost", "back").with_suffix(".json"))["attempt"], 2)

        print("[3e] a run holds the lock")
        attempt(1, {"view": "back", "ok": False, "reasons": ["hem"], "gate_version": ghost_v})
        lock = gs.run_item_lock("Demo", bid)
        lock.acquire()
        try:
            try:
                garments.use_attempt("Demo", bid, "ghost", "back", 1)
                check("UseBusy", "used", "UseBusy")
            except garments.UseBusy:
                check("UseBusy", True, True)
            try:
                routes.use_character_garment_attempt("Demo", bid, "ghost", "back", 1, {})
                check("route 409 busy", "ok", 409)
            except HTTPException as e:
                check("route 409 busy", e.status_code, 409)
        finally:
            lock.release()

        print("[3f] the pair")
        put("ghost", "back", record={"ok": True, "hem_c": 0.70, "worn_hem_c": 0.65, "gate_version": ghost_v})
        check("disagreeing pair", garments._pair("Demo", bid, "clothing", fsig)[0], False)
        # The same back as a refused attempt, taken by the user.
        attempt(1, {"view": "back", "ok": False, "reasons": ["hem"], "hem_c": 0.70, "worn_hem_c": 0.65,
                    "gate_version": ghost_v})
        garments.use_attempt("Demo", bid, "ghost", "back", 1)
        check("taken by the user: the pair agrees", garments._pair("Demo", bid, "clothing", fsig)[0], True)


def main() -> int:
    socket.socket.connect = _refuse_connect
    with tempfile.TemporaryDirectory(prefix="attempt-pick-use-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)
        from app.core import garment_assembly
        garment_assembly.schedule = lambda *a, **k: False
        part_distance()
        part_pick(root)
        part_use(root)
    check("outbound connects", len(OUTBOUND), 0)
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
