#!/usr/bin/env python3
"""Hair as its own mesh, task 3: the garment store (app/core/garment_store.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_store.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no renderer, no GPU, no server. Synthetic bytes only.
Every expectation is derived by hand below from plan
2026-11-09-base-body-phase4-hair (R10, R11, R13 and Task 3).

Fixture: ``Demo`` (template human-roleplay, female, on the base-body pipeline,
hair slot {length: medium, color: blonde}, appearance "slender, wavy hair with
a side parting"). ensure_hair_item(Demo) gives the item H (id "hair_demo").
BSIG = base_signature(Demo). The base views are fake PNG bytes at
model_refs/tpose_BSIG.png (front) and model_refs/tpose_back_BSIG.png (back);
the base model is model3d/BSIG.glb with bytes b"model-1".

[1] fsig = md5[:12] over {kind, description, behind_shoulders, pronouns,
    version, bsig, sha256 of base front + back image}:
    - 12 lowercase hex characters, and two calls give the same value;
    - another description (appearance "slender, curly hair", so the description
      becomes "medium blonde hair, curly hair") -> different;
    - GARMENT_VERSION["hair"] 1 -> 2 -> different (restored afterwards);
    - another bsig: the same image bytes copied to "base0123abcd" and
      base_signature patched to answer it -> different (only bsig changed);
    - the back image rewritten under the SAME name (other bytes, mtime moved
      by +2 s so the stat-keyed hash cache sees it) -> different;
    - a new base model file (model3d/BSIG.glb -> b"model-2") -> SAME fsig
      (the model is not an fsig input; the fit record decides, R10);
    - the pronouns: female -> ("her", "she"), male -> ("his", "he"), anything
      else -> ("their", "they").
[2] garment_path (F = current fsig):
      image, step haired, view front        -> garments/images/H_F_haired_front.png
      image, haired, back, attempt 2         -> garments/images/H_F_haired_back.try2.png
      raw / prepared / low                   -> garments/{raw,prepared,low}/H_F.glb
      fit                                    -> garments/H_F.glb
    "../x" as item id -> ValueError; "a/b" -> ValueError; fsig "xyz" ->
    ValueError; part "bogus" -> ValueError; image with step "mesh" (no image
    step) or view "left" -> ValueError.
[3] read_record/write_record: round trip of {"accepted": True, "n": 1}; no
    "*.tmp" left behind; read of a missing / broken file -> {}.
[4] accepted_fit with SHA = sha256(b"model-2"), current fsig F, older fsigs
    OLD_A = "0000000000aa" and OLD_B = "0000000000bb":
    (a) F, OLD_A both accepted on SHA, OLD_A's GLB 100 s NEWER than F's ->
        F (current wins over newer older ones);
    (b) F's record accepted False -> OLD_A (newest accepted on SHA; OLD_B
        is accepted on SHA too but 50 s older);
    (c) base_model_sha "other" -> None; "" -> None.
[5] checked_reference_override: garments/images/H_F_haired_front.png ->
    its resolved path; garments/raw/H_F.glb -> "" (not an image of the chain).
[6] Status: start(Demo, H, "haired") -> running_step "haired", failed None;
    end(..., error="gate", gates={"xor": 0.2}) -> running_step None, failed
    {step haired, error gate, gates {xor: 0.2}, failed_at <iso>}; end of the
    same step without error clears it. char_lock(Demo) is the same Lock
    object on every call and differs from char_lock("Other").
[7] GC (outfit_cache_gc). Groups under garments/ (key "garment:<item>_<fsig>"):
      CUR  = H_F       : images haired front .png/.json + .try1.png,
                         raw .glb, prepared .glb (no fit yet: a run in flight)
      FALL = H_OLD_A   : fit .glb/.json accepted on SHA        -> fallback, kept
      OLDB = H_OLD_B   : images ghost back .png/.json, fit .glb/.json
                         (record without "accepted")            -> stale
      ORPH = hair_gone_0000000000cc : raw .glb, low .glb        -> stale (no such
                         item equipped)
    plus one unparseable file garments/notes.txt (never judged, never deleted).
    verify_cache: garments {total 4, valid 2, stale 2}; stale_signatures
    contains exactly the two garment keys garment:H_OLD_B and
    garment:hair_gone_0000000000cc beside whatever the outfit rule reports;
    stale_bytes = sum of their file sizes (4 files of 10 bytes + 2 of 10 = 60).
    purge_stale(Demo, [garment:H_OLD_B, garment:hair_gone_..., garment:H_F]):
    H_F is not stale -> skipped 1; deleted 6 files (OLDB: 4, ORPH: 2); every
    CUR and FALL file and notes.txt still exist.
    Unequipped (equipped_mesh_pieces {}): every garment group is stale (no
    equipped item) -> 2 more stale keys (CUR, FALL).
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc=ValueError):
    try:
        fn()
    except exc:
        check(label, "raised", "raised")
        return
    except Exception as e:  # noqa: BLE001
        check(label, f"{type(e).__name__}: {e}", "raised")
        return
    check(label, "no error", "raised")


def touch(path: Path, data: bytes = b"x" * 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def age(path: Path, seconds: float) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-store-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, garment_assembly, garment_hair, model_refs
        from app.core import outfit_cache_gc as gc
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_profile,
                                          save_character_profile)
        garment_assembly.schedule = lambda *a, **k: False
        try:
            from app.core import garment_store as gs
        except ImportError as e:
            check("garment_store importable", str(e), "importable")
            print("FAILED: " + ", ".join(FAILS))
            return 1

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender, wavy hair with a side parting",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = garment_hair.ensure_hair_item("Demo")
        check("hair item id", hid, "hair_demo")

        cdir = get_character_dir("Demo")
        bsig = base_body.base_signature("Demo")
        refs = cdir / "model_refs"
        front = touch(refs / f"tpose_{bsig}.png", b"\x89PNG-front-" + b"a" * 40)
        back = touch(refs / f"tpose_back_{bsig}.png", b"\x89PNG-back-" + b"b" * 40)
        model = touch(cdir / "model3d" / f"{bsig}.glb", b"model-1")

        print("[1] fsig")
        fsig = gs.garment_fsig("Demo", hid)
        check("12 hex", bool(re.fullmatch(r"[0-9a-f]{12}", fsig)), True)
        check("stable", gs.garment_fsig("Demo", hid), fsig)
        profile = get_character_profile("Demo")
        curly = dict(profile, character_appearance="slender, curly hair")
        check("description input", garment_hair.fsig_inputs("Demo", profile=curly)["description"],
              "medium blonde hair, curly hair")
        check("other description", gs.garment_fsig("Demo", hid, profile=curly) != fsig, True)
        gs.GARMENT_VERSION["hair"] = 2
        try:
            check("version bump", gs.garment_fsig("Demo", hid) != fsig, True)
        finally:
            gs.GARMENT_VERSION["hair"] = 1
        check("version restored", gs.garment_fsig("Demo", hid), fsig)
        other = "base0123abcd"
        shutil.copyfile(front, refs / f"tpose_{other}.png")
        shutil.copyfile(back, refs / f"tpose_back_{other}.png")
        real_bsig = base_body.base_signature
        base_body.base_signature = lambda *a, **k: other
        try:
            check("other bsig", gs.garment_fsig("Demo", hid) != fsig, True)
        finally:
            base_body.base_signature = real_bsig
        for p in (refs / f"tpose_{other}.png", refs / f"tpose_back_{other}.png"):
            p.unlink()
        back.write_bytes(b"\x89PNG-back-" + b"c" * 40)
        age(back, 2)
        fsig2 = gs.garment_fsig("Demo", hid)
        check("rewritten back image", fsig2 != fsig, True)
        fsig = fsig2
        model.write_bytes(b"model-2")
        age(model, 2)
        check("new base model keeps fsig", gs.garment_fsig("Demo", hid), fsig)
        check("pronouns female", garment_hair.pronouns({"gender": "female"}), ("her", "she"))
        check("pronouns male", garment_hair.pronouns({"gender": "Male"}), ("his", "he"))
        check("pronouns other", garment_hair.pronouns({"gender": ""}), ("their", "they"))

        print("[2] garment_path")
        gdir = gs.garments_dir("Demo")
        check("garments dir", gdir, cdir / "garments")
        check("image", gs.garment_path("Demo", hid, fsig, "image", step="haired", view="front"),
              gdir / "images" / f"{hid}_{fsig}_haired_front.png")
        check("attempt", gs.garment_path("Demo", hid, fsig, "image", step="haired", view="back", attempt=2),
              gdir / "images" / f"{hid}_{fsig}_haired_back.try2.png")
        for part in ("raw", "prepared", "low"):
            check(part, gs.garment_path("Demo", hid, fsig, part), gdir / part / f"{hid}_{fsig}.glb")
        check("fit", gs.garment_path("Demo", hid, fsig, "fit"), gdir / f"{hid}_{fsig}.glb")
        raises("../x", lambda: gs.garment_path("Demo", "../x", fsig, "fit"))
        raises("a/b", lambda: gs.garment_path("Demo", "a/b", fsig, "fit"))
        raises("bad fsig", lambda: gs.garment_path("Demo", hid, "xyz", "fit"))
        raises("bad part", lambda: gs.garment_path("Demo", hid, fsig, "bogus"))
        raises("non-image step", lambda: gs.garment_path("Demo", hid, fsig, "image", step="mesh", view="front"))
        raises("bad view", lambda: gs.garment_path("Demo", hid, fsig, "image", step="haired", view="left"))

        print("[3] records")
        rec = gdir / "probe.json"
        gs.write_record(rec, {"accepted": True, "n": 1})
        check("round trip", gs.read_record(rec), {"accepted": True, "n": 1})
        check("no tmp left", sorted(p.name for p in gdir.iterdir() if ".tmp" in p.name), [])
        check("missing", gs.read_record(gdir / "missing.json"), {})
        touch(rec, b"{broken")
        check("broken", gs.read_record(rec), {})
        rec.unlink()

        print("[4] accepted_fit")
        sha = hashlib.sha256(b"model-2").hexdigest()
        check("base sha", base_body.base_model_sha256("Demo", bsig), sha)
        old_a, old_b = "0000000000aa", "0000000000bb"

        def fit(f, accepted, base_sha, offset):
            glb = touch(gs.garment_path("Demo", hid, f, "fit"))
            gs.write_record(glb.with_suffix(".json"), {"accepted": accepted, "base_model_sha256": base_sha})
            age(glb, offset)
            return glb

        cur_fit = fit(fsig, True, sha, 0)
        a_fit = fit(old_a, True, sha, 100)
        fit(old_b, True, sha, 50)
        got = gs.accepted_fit("Demo", hid, base_model_sha=sha)
        check("(a) current wins", got and got[0], cur_fit)
        check("(a) record", got and got[1].get("accepted"), True)
        gs.write_record(cur_fit.with_suffix(".json"), {"accepted": False, "base_model_sha256": sha})
        got = gs.accepted_fit("Demo", hid, base_model_sha=sha)
        check("(b) newest older", got and got[0], a_fit)
        check("(c) other sha", gs.accepted_fit("Demo", hid, base_model_sha="other"), None)
        check("(c) empty sha", gs.accepted_fit("Demo", hid, base_model_sha=""), None)
        for f in (fsig, old_a, old_b):
            p = gs.garment_path("Demo", hid, f, "fit")
            p.unlink()
            p.with_suffix(".json").unlink()

        print("[5] checked_reference_override")
        img = touch(gs.garment_path("Demo", hid, fsig, "image", step="haired", view="front"))
        raw = touch(gs.garment_path("Demo", hid, fsig, "raw"))
        check("images accepted", model_refs.checked_reference_override("Demo", str(img)), str(img.resolve()))
        check("raw refused", model_refs.checked_reference_override("Demo", str(raw)), "")
        img.unlink()
        raw.unlink()

        print("[6] status")
        gs.start("Demo", hid, "haired")
        st = gs.status("Demo", hid)
        check("running", (st["running_step"], st["failed"]), ("haired", None))
        gs.end("Demo", hid, "haired", error="gate", gates={"xor": 0.2})
        st = gs.status("Demo", hid)
        check("ended", st["running_step"], None)
        failed = st["failed"] or {}
        check("failed", (failed.get("step"), failed.get("error"), failed.get("gates")),
              ("haired", "gate", {"xor": 0.2}))
        check("failed_at iso", isinstance(failed.get("failed_at"), str) and "T" in failed["failed_at"], True)
        gs.start("Demo", hid, "haired")
        gs.end("Demo", hid, "haired")
        check("cleared", gs.status("Demo", hid)["failed"], None)
        lock = gs.char_lock("Demo")
        check("lock type", isinstance(lock, type(threading.Lock())), True)
        check("same lock", gs.char_lock("Demo") is lock, True)
        check("other lock", gs.char_lock("Other") is lock, False)

        print("[7] GC")

        def gp(item, f, part, **kw):
            return gs.garment_path("Demo", item, f, part, **kw)

        im = gp(hid, fsig, "image", step="haired", view="front")
        cur_files = [touch(im), touch(im.with_suffix(".json")),
                     touch(gp(hid, fsig, "image", step="haired", view="front", attempt=1)),
                     touch(gp(hid, fsig, "raw")), touch(gp(hid, fsig, "prepared"))]
        fall_glb = touch(gp(hid, old_a, "fit"))
        fall_rec = fall_glb.with_suffix(".json")
        gs.write_record(fall_rec, {"accepted": True, "base_model_sha256": sha})
        fall_files = [fall_glb, fall_rec]
        imb = gp(hid, old_b, "image", step="ghost", view="back")
        oldb_glb = gp(hid, old_b, "fit")
        # 10 bytes of JSON without "accepted" -> never accepted.
        oldb_files = [touch(imb), touch(imb.with_suffix(".json")), touch(oldb_glb),
                      touch(oldb_glb.with_suffix(".json"), b'{"n": 0}  ')]
        orph_files = [touch(gp("hair_gone", "0000000000cc", "raw")),
                      touch(gp("hair_gone", "0000000000cc", "low"))]
        notes = touch(gdir / "notes.txt")
        k_cur, k_fall = f"garment:{hid}_{fsig}", f"garment:{hid}_{old_a}"
        k_oldb, k_orph = f"garment:{hid}_{old_b}", "garment:hair_gone_0000000000cc"

        rep = gc.verify_cache("Demo")
        garment_keys = sorted(s for s in rep["stale_signatures"] if s.startswith("garment:"))
        check("stale garment keys", garment_keys, sorted([k_oldb, k_orph]))
        g = rep.get("garments") or {}
        check("garments side", (g.get("total"), g.get("valid"), g.get("stale"), g.get("stale_bytes")),
              (4, 2, 2, 60))

        res = gc.purge_stale("Demo", [k_oldb, k_orph, k_cur])
        check("skipped", res["skipped"], 1)
        check("deleted", res["deleted_files"], 6)
        check("freed", res["freed_bytes"], 60)
        check("stale gone", [p.exists() for p in oldb_files + orph_files], [False] * 6)
        check("current kept", [p.exists() for p in cur_files], [True] * 5)
        check("fallback kept", [p.exists() for p in fall_files], [True] * 2)
        check("unknown file kept", notes.exists(), True)

        check("unequip", inventory.unequip_mesh_piece("Demo", "hair"), True)
        rep = gc.verify_cache("Demo")
        check("unequipped: all stale",
              sorted(s for s in rep["stale_signatures"] if s.startswith("garment:")),
              sorted([k_cur, k_fall]))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
