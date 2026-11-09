#!/usr/bin/env python3
"""Artefact registry + reachability GC (app/core/artefact_graph.py; plan
docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 3; spec "Deletion = reachability").

Usage:
    ./.venv/bin/python scripts/smoke_artefact_gc.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server process. Every file is synthetic bytes; only names and JSON sidecars matter to the GC.

Fixture (``make(char, s)``, one fresh character per scenario; items ``top<s>`` {top}, ``skirt<s>`` {bottom} painted,
``dress<s>`` {outer} own mesh, all in the inventory; hair item worn, hair_method hairdeck; pipeline on, mode mesh;
profile picture). bsig = base_signature; T1 = "tex111111111111", T2 = "tex222222222222"; B1/B2 =
outfit_body_id(T1/T2). Outfits (sig = model_refs.mesh_signature of the pieces with their recorded variant + token):
  O1 {top, skirt} WORN, on B1 (texture T1);  O3 {top, skirt, dress} on B1 (T1 — Review Focus 4: same painted
  pieces, other own-mesh piece -> one body, two assemblies);  O2 {top, dress} on B2 (T2).
Labels (file groups the oracle knows):
  base      refs tpose/tpose_back_<bsig> (.png+.json), model3d <bsig>.glb/.json, unrigged/, prerig/, covered/, facefix/
  O1m/O2m/O3m  model3d <sig>.glb/.json, low/, assembled/, assembled/low/ (+ O1: rollback/<sig>/manifest.json)
  O1r/O2r/O3r  refs tpose_, tpose_back_, drafts/tpose_back_, pose_ (.png+.json); the sidecars name texture + manifest
  T1/T2     model_refs/texture/tpose[_back]_<T>, texture/drafts/tpose_back_<T>, model3d/texture/<T>.glb/.json
  B1/B2     refs tpose[_back]_<B>, model3d <B>.glb/.json, unrigged/, prerig/, raw/, facefix/, rollback/<B>/<B>.glb
            (record outfit_body {body_id, texture_signature, base_signature})
  Gd        dress, current fsig Fd: images worn/ghost front, raw/, prepared/ (+.json), fit + .json (accepted on
            sha(base glb)), low/
  Gh        hair, current fsig Fh: fit + .json (accepted, method hairdeck, inputs.hsig = H), low/
  Bd1/Bd2   dress fit on B1/B2: bodies/<B>/dress_Fd.glb/.json, low/; Bd1 also layers/dress_Fd_<12>.glb/.json + layers/low/
  Bh1/Bh2   hair fit on B1/B2 (bodies/<B>/hair_Fh.glb/.json); Bh2 also failed/hair_Fh.json
  HD        garments/raw/<hair>_<H>/ (record.json, hair_seed42.glb, hair_seed42_nohead.glb), H = garment_hsig
  FACE      model_refs/face_view.png/.json;   UNK  model3d/notes.txt (unknown: never deleted)
  LIVE      model3d/.process-live/x.glb, mtime -2 d, registered in model3d._active_stages;  YOUNG model_refs/.fitgate_young/a/x.png
Pre-planted orphans (``orphans=True``, scenario [0] only):
  OLDB  base0123abcd refs + model (older base);  GOLD dress fsig "0123456789ab" images + fit (record NOT accepted)
  BdOLD its fit on B1;  HDOLD raw/<hair>_aaaaaaaaaaaa/;  DEAD model3d/.process-dead/x.glb (-2 d);
  TMP garments/raw/.<hair>_<H>.1.2.tmp/x (-2 d)

Expected, by hand from the spec + plan rulings (module docstring of artefact_graph):
[0] collect(explicit): exactly OLDB, GOLD, BdOLD, HDOLD, DEAD, TMP go; the walk of model3d/ model_refs/ garments/ is
    EVERYTHING else (incl. UNK, LIVE, YOUNG). A second collect deletes 0 files. verify_cache: stale_signatures [].
[1] outfit delete: route DELETE model3d (current outfit O1) -> O1m gone; collect: nothing else (O1r live = worn ->
    T1 live -> B1 reachable in mesh mode). Outfit set deleted (route) -> nothing.
[2] item delete: route DELETE /items/dress<s> -> gone: O2m O2r O3m O3r (invalidation + not producible), T2 (no live
    outfit), B2 + Bd2 + Bh2 (body of a dead texture, Review Focus 2: fits on ALL bodies), Gd, Bd1. Kept: base O1m O1r
    T1 B1 Bh1 Gh HD FACE UNK LIVE YOUNG.
[3] base regenerated (new profile picture -> new bsig; new base views written): gone at once: base (older
    base), T1 T2 (sidecars name the old base), B1 B2 Bd1 Bd2 Bh1 Bh2 (record names the old base — ruling
    "immediately"). Kept: O1..O3 (producible; rebuilt later), Gd Gh (R11: newest accepted fit at all), HD (the
    hsig changed with the picture, but the kept hair fit names it), NEWBASE refs, FACE UNK LIVE YOUNG.
[4] mode switch (apply_profile_update outfit_body_mode retexture): 0 deletions (every body still named by a live
    outfit model). O1m + O3m rebuilt in retexture (sidecar without body_id) -> collect: B1 Bd1 Bh1 gone; O2m
    rebuilt -> B2 Bd2 Bh2 gone. Mode back to mesh -> 0 deletions (T1 T2 stay in both modes: mode back = no render).
[5] character delete: delete_character -> the directory is gone; collect afterwards mints nothing.
[6] running: B2 made unreachable (retexture, O2m rebuilt) but a live stage on B2 -> B2, Bd2, Bh2 skipped "running";
    another thread holds keyed_lock("outfit_body", B2) -> skipped; open hub op model3d:<char>:<B2> -> skipped;
    nothing of them deleted. All released -> they go. Garment run of dress (status running) + dress out of the
    inventory -> Gd, Bd1, Bd2 kept; run ended -> they go.
[7] grace: orphans planted fresh -> sweep (explicit False) deletes 0 and skips them "grace"; mtimes set 1 h back ->
    sweep deletes them. LIVE (registered) and YOUNG (< 24 h) survive every sweep.
[8] admin routes: GET .../artefacts/orphans is a dry run (files unchanged, orphans listed with parents);
    POST .../artefacts/collect deletes; both need admin (Depends(require_admin)).
[9] wiring: base_body.generate_base_model / generate_base_images and expression_regen's item invalidation call
    artefact_graph.collect_quietly; periodic_jobs lists artefact_gc daily.
"""
import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OLD_S = 2 * 24 * 3600


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def age(paths, seconds):
    import time
    when = time.time() - seconds
    for p in paths:
        for q in ([p] + list(p.rglob("*")) if p.is_dir() else [p]):
            os.utime(q, (when, when))


def main() -> int:
    try:
        from app.core import artefact_graph  # noqa: F401
    except ImportError as e:
        check("artefact_graph imports", str(e), "")
        print(f"\n{len(FAILS)} failure(s)")
        return 1
    with tempfile.TemporaryDirectory(prefix="artefact-gc-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import (artefact_graph as ag, base_body, character_ops, garment_hair, garment_store as gs,
                              hub_ops, model3d, outfit_cache_gc)
        from app.core.keyed_lock import keyed_lock
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import (delete_character, get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        T1, T2 = "tex111111111111", "tex222222222222"
        B1, B2 = base_body.outfit_body_id(T1), base_body.outfit_body_id(T2)

        def make(char: str, s: str, *, orphans: bool = False):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender, wavy hair with a side parting", "hair_method": "hairdeck",
                     "outfit_body_mode": "mesh",
                     "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}
            assert save_character_profile(char, human, create_new=True)
            touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + char.encode() * 8)
            prof = get_character_profile(char)
            prof["profile_image"] = f"{char}_1.png"
            assert save_character_profile(char, prof)
            assert base_body.set_pipeline(char, True)
            hid = garment_hair.ensure_hair_item(char)
            ids = {}
            for key, slots, own in (("top", ["top"], False), ("skirt", ["bottom"], False), ("dress", ["outer"], True)):
                op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "own_mesh": own}
                ids[key] = inventory.add_item(name=f"{key}{s}", category="outfit_piece", item_id=f"{key}{s}",
                                              prompt_fragment=f"a {key}", outfit_piece=op)["id"]
                inventory.add_to_inventory(char, ids[key])
            outfits = {"O1": {"top": ids["top"], "bottom": ids["skirt"]},
                       "O2": {"top": ids["top"], "outer": ids["dress"]},
                       "O3": {"top": ids["top"], "bottom": ids["skirt"], "outer": ids["dress"]}}
            prof = get_character_profile(char)
            prof["equipped_pieces"] = dict(outfits["O1"])
            assert save_character_profile(char, prof)
            cdir = get_character_dir(char)
            M, R, G = cdir / "model3d", cdir / "model_refs", cdir / "garments"
            bsig = base_body.base_signature(char)
            L = {}
            base_glb = b"BASE-GLB-" + char.encode()
            L["base"] = [touch(R / f"tpose_{bsig}.png"), touch(R / f"tpose_{bsig}.json", {"base_signature": bsig}),
                         touch(R / f"tpose_back_{bsig}.png"), touch(R / f"tpose_back_{bsig}.json", {"base_signature": bsig}),
                         touch(M / f"{bsig}.glb", base_glb), touch(M / f"{bsig}.json", {"base": True, "rig": "mixamo"}),
                         touch(M / "unrigged" / f"{bsig}.glb"), touch(M / "prerig" / f"{bsig}.glb"),
                         touch(M / "prerig" / f"{bsig}.json", {}), touch(M / "covered" / f"{bsig}.glb"),
                         touch(M / "covered" / f"{bsig}.json", {}), touch(M / "facefix" / f"{bsig}.glb"),
                         touch(M / "facefix" / f"{bsig}.png"), touch(M / "facefix" / f"{bsig}.json", {})]
            base_sha = hashlib.sha256(base_glb).hexdigest()
            sigs, tex_of, body_of = {}, {"O1": T1, "O2": T2, "O3": T1}, {"O1": B1, "O2": B2, "O3": B1}
            for name, pieces in outfits.items():
                variant, token = mesh_variant(char, pieces), mesh_items_token(char, pieces)
                sig = mesh_signature(pieces, [], char, variant, token)
                sigs[name] = sig
                manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant,
                            "mesh_token": token, "texture_signature": tex_of[name], "base_signature": bsig}
                L[name + "r"] = [touch(R / f"{k}_{sig}{e}", manifest if e == ".json" else b"png")
                                 for k in ("tpose", "tpose_back", "pose") for e in (".png", ".json")]
                L[name + "r"] += [touch(R / "drafts" / f"tpose_back_{sig}.png"),
                                  touch(R / "drafts" / f"tpose_back_{sig}.json", manifest)]
                mmeta = {"pieces": pieces, "items": [], "mesh_variant": variant, "mesh_token": token,
                         "base_signature": bsig, "base_model_sha256": base_sha, "texture_signature": tex_of[name],
                         "outfit_body_mode": "mesh", "body_id": body_of[name], "body_sha256": "x", "rig": "mixamo"}
                L[name + "m"] = [touch(M / f"{sig}.glb"), touch(M / f"{sig}.json", mmeta),
                                 touch(M / "low" / f"{sig}.glb"), touch(M / "low" / f"{sig}.json", {}),
                                 touch(M / "assembled" / f"{sig}.glb"), touch(M / "assembled" / f"{sig}.json", {}),
                                 touch(M / "assembled" / "low" / f"{sig}.glb"),
                                 touch(M / "assembled" / "low" / f"{sig}.json", {})]
            L["O1m"].append(touch(M / "rollback" / sigs["O1"] / "manifest.json", {}))
            for label, t in (("T1", T1), ("T2", T2)):
                tm = {"base_signature": bsig, "texture_signature": t}
                L[label] = [touch(R / "texture" / f"tpose_{t}.png"), touch(R / "texture" / f"tpose_{t}.json", tm),
                            touch(R / "texture" / f"tpose_back_{t}.png"),
                            touch(R / "texture" / f"tpose_back_{t}.json", tm),
                            touch(R / "texture" / "drafts" / f"tpose_back_{t}.png"),
                            touch(R / "texture" / "drafts" / f"tpose_back_{t}.json", tm),
                            touch(M / "texture" / f"{t}.glb"), touch(M / "texture" / f"{t}.json", tm)]
            for label, b, t in (("B1", B1, T1), ("B2", B2, T2)):
                rec = {"outfit_body": {"body_id": b, "mode": "mesh", "texture_signature": t, "base_signature": bsig}}
                L[label] = [touch(R / f"tpose_{b}.png"), touch(R / f"tpose_{b}.json", rec),
                            touch(R / f"tpose_back_{b}.png"), touch(R / f"tpose_back_{b}.json", rec),
                            touch(M / f"{b}.glb"), touch(M / f"{b}.json", {**rec, "rig": "mixamo"}),
                            touch(M / "unrigged" / f"{b}.glb"), touch(M / "unrigged" / f"{b}.json", rec),
                            touch(M / "prerig" / f"{b}.glb"), touch(M / "prerig" / f"{b}.json", rec),
                            touch(M / "raw" / f"{b}.glb"), touch(M / "facefix" / f"{b}.glb"),
                            touch(M / "facefix" / f"{b}.json", {}), touch(M / "rollback" / b / f"{b}.glb")]
            dress, fd = ids["dress"], gs.garment_fsig(char, ids["dress"])
            hsig = gs.garment_hsig(char, hid)
            fh = gs.garment_fsig(char, hid)
            fitrec = {"accepted": True, "base_model_sha256": base_sha, "body_id": bsig, "base_signature": bsig}
            L["Gd"] = [touch(gs.garment_path(char, dress, fd, "image", step=st, view="front").with_suffix(e),
                             {"accepted": True} if e == ".json" else b"png")
                       for st in ("worn", "ghost") for e in (".png", ".json")]
            L["Gd"] += [touch(gs.garment_path(char, dress, fd, "raw")),
                        touch(gs.garment_path(char, dress, fd, "prepared")),
                        touch(gs.garment_path(char, dress, fd, "prepared").with_suffix(".json"), {"accepted": True}),
                        touch(gs.garment_path(char, dress, fd, "fit")),
                        touch(gs.garment_path(char, dress, fd, "fit").with_suffix(".json"),
                              {**fitrec, "item_id": dress, "fsig": fd}),
                        touch(gs.garment_path(char, dress, fd, "low"))]
            L["Gh"] = [touch(gs.garment_path(char, hid, fh, "fit")),
                       touch(gs.garment_path(char, hid, fh, "fit").with_suffix(".json"),
                             {**fitrec, "item_id": hid, "fsig": fh, "method": "hairdeck",
                              "inputs": {"hsig": hsig, "seed": 42}}),
                       touch(gs.garment_path(char, hid, fh, "low"))]
            for label, item, f, b in (("Bd1", dress, fd, B1), ("Bd2", dress, fd, B2), ("Bh1", hid, fh, B1),
                                      ("Bh2", hid, fh, B2)):
                rec = {"accepted": True, "item_id": item, "fsig": f, "body_id": b, "base_signature": bsig}
                L[label] = [touch(gs.garment_path(char, item, f, "fit", body=b)),
                            touch(gs.garment_path(char, item, f, "fit", body=b).with_suffix(".json"), rec)]
                if item == dress:
                    L[label].append(touch(gs.garment_path(char, item, f, "low", body=b)))
            L["Bd1"] += [touch(gs.garment_path(char, dress, fd, "layer", lsig="abcdefabcdef", body=B1)),
                         touch(gs.garment_path(char, dress, fd, "layer", lsig="abcdefabcdef", body=B1)
                               .with_suffix(".json"), {"body_id": B1}),
                         touch(gs.garment_path(char, dress, fd, "layer_low", lsig="abcdefabcdef", body=B1))]
            L["Bh2"].append(touch(gs.garment_path(char, hid, fh, "failed", body=B2), {"error": "too tight"}))
            hd = gs.hairdeck_dir(char, hid, hsig)
            L["HD"] = [touch(hd / "record.json", {"accepted": True, "seed": 42}), touch(hd / "hair_seed42.glb"),
                       touch(hd / "hair_seed42_nohead.glb")]
            L["FACE"] = [touch(R / "face_view.png"), touch(R / "face_view.json", {})]
            L["UNK"] = [touch(M / "notes.txt")]
            live = M / ".process-live"
            L["LIVE"] = [touch(live / "x.glb")]
            age([live], OLD_S)
            model3d._active_stages[str(live.resolve())] = (char, sigs["O1"])
            L["YOUNG"] = [touch(R / ".fitgate_young" / "a" / "x.png")]
            if orphans:
                old = "base0123abcd"
                L["OLDB"] = [touch(R / f"tpose_{old}.png"), touch(R / f"tpose_{old}.json", {"base_signature": old}),
                             touch(M / f"{old}.glb"), touch(M / f"{old}.json", {})]
                fo = "0123456789ab"
                L["GOLD"] = [touch(gs.garment_path(char, dress, fo, "image", step="worn", view="front")),
                             touch(gs.garment_path(char, dress, fo, "fit")),
                             touch(gs.garment_path(char, dress, fo, "fit").with_suffix(".json"), {"accepted": False})]
                L["BdOLD"] = [touch(gs.garment_path(char, dress, fo, "fit", body=B1))]
                L["HDOLD"] = [touch(gs.hairdeck_dir(char, hid, "aaaaaaaaaaaa") / "record.json", {})]
                dead = M / ".process-dead"
                L["DEAD"] = [touch(dead / "x.glb")]
                tmpw = G / "raw" / f".{hid}_{hsig}.1.2.tmp"
                L["TMP"] = [touch(tmpw / "x")]
                age([dead, tmpw], OLD_S)
            return {"L": L, "sigs": sigs, "ids": ids, "hid": hid, "bsig": bsig, "dir": cdir, "outfits": outfits}

        def walk(char):
            cdir = get_character_dir(char)
            return {p.relative_to(cdir).as_posix() for d in ag.ROOT_DIRS if (cdir / d).is_dir()
                    for p in (cdir / d).rglob("*") if p.is_file()}

        def expect(fx, labels):
            return {p.relative_to(fx["dir"]).as_posix() for lab in labels for p in fx["L"][lab]}

        ALL = ["base", "O1m", "O1r", "O2m", "O2r", "O3m", "O3r", "T1", "T2", "B1", "B2", "Gd", "Gh", "Bd1", "Bd2",
               "Bh1", "Bh2", "HD", "FACE", "UNK", "LIVE", "YOUNG"]

        def same(label, char, fx, labels):
            got, want = walk(char), expect(fx, labels)
            check(f"{label}: orphans left", sorted(got - want), [])
            check(f"{label}: reachable removed", sorted(want - got), [])

        def without(*drop):
            return [x for x in ALL if x not in drop]

        def rebuild_retexture(fx, name):
            sidecar = fx["dir"] / "model3d" / f"{fx['sigs'][name]}.json"
            meta = json.loads(sidecar.read_text())
            for k in ("body_id", "body_sha256"):
                meta.pop(k, None)
            meta["outfit_body_mode"] = "retexture"
            sidecar.write_text(json.dumps(meta))

        def set_mode(char, mode):
            return character_ops.apply_profile_update(char, {"fields": {"outfit_body_mode": mode}})

        # --- [0] initial tree with planted orphans -------------------------------------------------------
        print("[0] initial collect removes exactly the planted orphans")
        fx = make("Demo0", "0", orphans=True)
        report = ag.collect("Demo0", explicit=True, reason="smoke")
        same("[0]", "Demo0", fx, ALL)
        check("[0] orphan kinds", sorted({e["kind"] for e in report["orphans"]}),
              ["base", "body_fit", "garment", "hairdeck", "temp"])
        check("[0] unknown reported, kept", report["unknown"], ["model3d/notes.txt"])
        check("[0] second collect deletes 0", ag.collect("Demo0", explicit=True)["deleted_files"], 0)
        check("[0] verify_cache: nothing stale", outfit_cache_gc.verify_cache("Demo0")["stale_signatures"], [])
        bd1 = next((n for n in ag.analyse("Demo0").nodes if n.key.startswith(f"bodyfit:{B1}:dress0")), None)
        check("[0] body fit parents", bd1 and {k: bd1.parents[k] for k in ("body_id", "item_id")},
              {"body_id": B1, "item_id": "dress0"})

        # --- [1] outfit delete ---------------------------------------------------------------------------
        print("[1] outfit delete")
        from app.routes.characters import delete_character_model3d
        from app.routes.inventory import delete_item_route, delete_outfit_set_route
        fx = make("Demo1", "1")
        check("[1] DELETE model3d", delete_character_model3d("Demo1"), {"status": "success"})
        same("[1] model deleted", "Demo1", fx, without("O1m"))
        from app.models.character import add_character_outfit
        oid = add_character_outfit("Demo1", {"name": "Set", "pieces": list(fx["outfits"]["O2"].values())})
        check("[1] DELETE outfit set", delete_outfit_set_route("Demo1", oid, _admin={})["status"], "ok")
        same("[1] set deleted", "Demo1", fx, without("O1m"))

        # --- [2] item delete -----------------------------------------------------------------------------
        print("[2] own-mesh item delete -> its fits on ALL bodies, its outfits, their texture + body")
        fx = make("Demo2", "2")
        check("[2] DELETE item", delete_item_route("dress2"), {"ok": True})
        same("[2]", "Demo2", fx, without("O2m", "O2r", "O3m", "O3r", "T2", "B2", "Bd2", "Bh2", "Gd", "Bd1"))

        # --- [3] base regenerated ------------------------------------------------------------------------
        print("[3] base regenerated -> old base's bodies + fits go at once")
        fx = make("Demo3", "3")
        prof = get_character_profile("Demo3")
        touch(get_character_images_dir("Demo3") / "Demo3_2.png", b"\x89PNG" + b"new picture" * 9)
        prof["profile_image"] = "Demo3_2.png"
        save_character_profile("Demo3", prof)
        nb = base_body.base_signature("Demo3")
        check("[3] new base signature", nb != fx["bsig"], True)
        refs = fx["dir"] / "model_refs"
        fx["L"]["NEWBASE"] = [touch(refs / f"tpose_{nb}.png"), touch(refs / f"tpose_{nb}.json", {"base_signature": nb})]
        ag.collect_quietly("Demo3", "base images rendered")
        same("[3]", "Demo3", fx, without("base", "T1", "T2", "B1", "B2", "Bd1", "Bd2", "Bh1", "Bh2") + ["NEWBASE"])

        # --- [4] mode switch -----------------------------------------------------------------------------
        print("[4] mode switch mesh -> retexture -> mesh")
        fx = make("Demo4", "4")
        check("[4] switch to retexture", set_mode("Demo4", "retexture")["status"], "success")
        same("[4] after switch", "Demo4", fx, ALL)
        rebuild_retexture(fx, "O1")
        rebuild_retexture(fx, "O3")
        ag.collect("Demo4", explicit=True)
        same("[4] O1+O3 rebuilt", "Demo4", fx, without("B1", "Bd1", "Bh1"))
        rebuild_retexture(fx, "O2")
        ag.collect("Demo4", explicit=True)
        same("[4] O2 rebuilt", "Demo4", fx, without("B1", "Bd1", "Bh1", "B2", "Bd2", "Bh2"))
        set_mode("Demo4", "mesh")
        same("[4] back to mesh", "Demo4", fx, without("B1", "Bd1", "Bh1", "B2", "Bd2", "Bh2"))

        # --- [5] character delete ------------------------------------------------------------------------
        print("[5] character delete")
        fx = make("Demo5", "5")
        check("[5] delete_character", delete_character("Demo5"), True)
        check("[5] directory gone", fx["dir"].exists(), False)
        ag.collect("Demo5", explicit=True)
        check("[5] collect mints nothing", fx["dir"].exists(), False)

        # --- [6] running protection ----------------------------------------------------------------------
        print("[6] running work is never deleted")
        fx = make("Demo6", "6")
        set_mode("Demo6", "retexture")
        rebuild_retexture(fx, "O2")
        stage = fx["dir"] / "model3d" / ".process-b2"
        stage.mkdir()
        model3d._active_stages[str(stage.resolve())] = ("Demo6", B2)
        rep = ag.collect("Demo6", explicit=True)
        check("[6] live stage: B2 + fits skipped running",
              sorted({s["why"] for s in rep["skipped"] if B2 in s["key"]}), ["running"])
        same("[6] live stage", "Demo6", fx, ALL)
        model3d._active_stages.pop(str(stage.resolve()))
        stage.rmdir()
        held, release = threading.Event(), threading.Event()

        def holder():
            with keyed_lock("outfit_body", f"Demo6:{B2}"):
                held.set()
                release.wait(10)
        t = threading.Thread(target=holder)
        t.start()
        held.wait(5)
        rep = ag.collect("Demo6", explicit=True)
        release.set()
        t.join()
        check("[6] body lock held: B2 skipped", any(s["key"] == B2 and s["why"] == "running" for s in rep["skipped"]),
              True)
        check("[6] body lock held: B2 refs + model kept",
              sorted(set(expect(fx, ["B2"])) - walk("Demo6")), [])
        op = hub_ops.create("character_mesh", f"model3d:Demo6:{B2}", {"character": "Demo6", "signature": B2})
        rep = ag.collect("Demo6", explicit=True)
        check("[6] open hub op: B2 skipped", any(s["key"] == B2 and s["why"] == "running" for s in rep["skipped"]),
              True)
        hub_ops.delete(op)
        ag.collect("Demo6", explicit=True)
        same("[6] released", "Demo6", fx, without("B2", "Bd2", "Bh2"))
        gs.start("Demo6", "dress6", "fit")
        inventory.remove_from_inventory("Demo6", "dress6", force=True)
        prof = get_character_profile("Demo6")
        prof["equipped_pieces"] = {k: v for k, v in prof.get("equipped_pieces", {}).items() if v != "dress6"}
        save_character_profile("Demo6", prof)
        ag.collect("Demo6", explicit=True)
        dead_outfits = ["O2m", "O2r", "O3m", "O3r", "T2"]
        same("[6] garment run: dress kept", "Demo6", fx, without("B2", "Bd2", "Bh2", *dead_outfits))
        gs.end("Demo6", "dress6", "fit")
        ag.collect("Demo6", explicit=True)
        # B1 is no longer named by a live outfit (O1 is the only live one and it names B1 -> stays).
        same("[6] run ended", "Demo6", fx, without("B2", "Bd2", "Bh2", *dead_outfits, "Gd", "Bd1"))

        # --- [7] grace -----------------------------------------------------------------------------------
        print("[7] grace window of the sweep")
        fx = make("Demo7", "7", orphans=True)
        aged = ["DEAD", "TMP"]
        fresh = ["OLDB", "GOLD", "BdOLD", "HDOLD"]
        rep = ag.collect("Demo7", explicit=False, reason="daily sweep")
        check("[7] sweep: fresh orphans skipped grace",
              sorted({s["why"] for s in rep["skipped"]}), ["grace"])
        same("[7] fresh kept", "Demo7", fx, ALL + fresh)
        age([p for lab in fresh for p in fx["L"][lab]], 3600)
        ag.collect("Demo7", explicit=False, reason="daily sweep")
        same("[7] aged gone", "Demo7", fx, ALL)
        check("[7] temp aged were gone in the first sweep", [p.exists() for lab in aged for p in fx["L"][lab]],
              [False, False])

        # --- [8] admin routes ----------------------------------------------------------------------------
        print("[8] admin routes")
        from app.routes import characters as routes_characters
        fx = make("Demo8", "8", orphans=True)
        before = walk("Demo8")
        dry = routes_characters.get_character_artefact_orphans("Demo8", _={})
        check("[8] dry run deletes nothing", walk("Demo8") == before, True)
        check("[8] dry run lists the orphans", sorted({e["key"] for e in dry["orphans"] if e["kind"] == "base"}),
              ["base0123abcd"])
        done = routes_characters.collect_character_artefacts("Demo8", _={})
        check("[8] collect deletes", done["deleted_files"] > 0, True)
        same("[8]", "Demo8", fx, ALL)
        for fn in (routes_characters.get_character_artefact_orphans, routes_characters.collect_character_artefacts):
            dep = inspect.signature(fn).parameters["_"].default
            check(f"[8] {fn.__name__} admin-only", getattr(getattr(dep, "dependency", None), "__name__", ""),
                  "require_admin")

        # --- [9] wiring ----------------------------------------------------------------------------------
        print("[9] wiring")
        from app.core import expression_regen, periodic_jobs
        check("[9] base model -> collect", "collect_quietly" in inspect.getsource(base_body.generate_base_model), True)
        check("[9] base images -> collect", "collect_quietly" in inspect.getsource(base_body.generate_base_images), True)
        check("[9] item change -> collect",
              "collect_quietly" in inspect.getsource(expression_regen._invalidate_outfit_caches_for_item), True)
        check("[9] daily sweep", [(iv, lab) for f, iv, lab in periodic_jobs._SUB_TASKS if lab == "artefact_gc"],
              [(86400, "artefact_gc")])

    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
