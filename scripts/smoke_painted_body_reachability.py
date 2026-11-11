#!/usr/bin/env python3
"""Painted bodies go by reachability, Delete in the Outfit body tab, and the bounded painted-body run
(app/core/artefact_graph.py ``_current_textures`` / ``delete_texture``, app/core/outfit_bodies.py
``texture_gc`` / ``delete_texture`` / ``_run_bounded`` / ``repaint_texture``, app/core/body_retexture.py
``run_deadline``).

Usage:
    ./.venv/bin/python scripts/smoke_painted_body_reachability.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server process. Files are synthetic bytes; only names and JSON sidecars matter to the GC.

THE BUG (2026-11-11): a painted body (``model_refs/texture/[drafts/]tpose[_back]_<T>`` + ``model3d/texture/<T>``)
stayed for good once a piece of its outfit changed. The old rule (pinned: commit 193321cf) kept a texture while a
live outfit's sidecars NAMED it; an outfit stays live through its recorded manifest (the outfit rule re-signs with
the recorded mesh token), so its old sidecars kept naming the old tsig. The new rule: a texture lives while a live
outfit would PAINT it now (``base_body.predicted_texture_signatures`` in both outfit body modes, plus the tsig of a
current dressed front); one only named is outdated (``OUTDATED_TEXTURE``, parent ``built_on``).

Fixture (``make(char, mode)``, a fresh character per scenario): items top {top}, skirt {bottom}, skirt2 {bottom}
painted, dress {outer} own mesh with an accepted fit on the base model (so both modes leave it out of the paint), all
in the inventory; pipeline on; base refs + model. ``outfit(char, pieces)`` worn and stored like a build leaves it:
front/back refs + model sidecar naming T = the tsig its pieces paint now in the character's mode, the texture store
of T (8 files: store tpose/tpose_back .png/.json, drafts/tpose_back .png/.json, model3d/texture/<T>.glb/.json); in
mesh mode also the outfit body B = outfit_body_id(T) (refs + model + unrigged) and the model's ``body_id`` B.
A piece change is applied with ``inventory._invalidate_renders_for_item`` switched off — as on the clone, where the
outfits' fronts and models outlived the stilettos' own-mesh flag; with the purge the old rule already saw no name.

Expected, by hand (the rule above):
[1] text change (retexture). O1 {top, skirt} on T1: T1 kept, reason CURRENT_TEXTURE, outfits [O1]. Delete route on
    T1 -> 409 PAINTED_NEEDED; on tex000000000000 -> 404 NO_PAINTED_BODY. Repaint pre-check on T1 -> 409 NO_SOURCE
    (the stored front carries no base view sha, so no outfit is a source — still current, not "cannot repaint").
    Skirt text "a skirt" -> "a long pleated skirt": the dress text of O1 changes, so O1 paints T1' != T1; O1 stays
    live (the text is not part of its signature) -> T1 outdated: not reachable, reason OUTDATED_TEXTURE, built_on
    [O1], no outfits. OLD rule (193321cf): T1 reachable (the proof). Tab: T1's gc {kept False, reason
    PAINTED_OUTDATED, 1 outfit}, blocked.delete "", blocked.regenerate PAINTED_CANNOT_REPAINT; repaint pre-check
    409 PAINTED_CANNOT_REPAINT. Delete route -> 8 files deleted, none of T1 left; O1's model + refs untouched; the
    tab no longer lists T1.
[2] own-mesh flag removed (retexture). O2 {top, dress} on T2 (dress left out). Flag off: the dress is painted now
    -> T2' != T2; O2 stays live (recorded token) -> T2 outdated; OLD rule: reachable (the proof). collect(explicit)
    deletes T2's 8 files; O2's model stays.
[3] piece swapped (retexture). O1 {top, skirt} on T1, then skirt2 worn instead (O4, nothing built): O1 is still
    producible (skirt in the inventory) -> T1 stays current (worn again it paints T1). collect deletes 0 of T1. Skirt
    out of the inventory -> O1 no longer producible -> T1 named by no live outfit -> collect deletes its 8 files.
[4] served model (mesh). O1 on B1 (model body_id B1, texture T1), then the skirt text change: T1 outdated -> its 8
    files go; the served model of O1 (a self-contained copy) and B1 stay — B1 is named as body_id by the live O1
    model (the body clause's second half).
[5] repaint publishing another tsig (retexture). A repaint of T1 whose build stands on tex999999999999 (the pieces
    changed meanwhile) -> {ok False, error PAINTED_AS_OTHER} (the log names both tsigs): never published under T1.
[6] time limit. body_retexture.run_timeout_seconds = 2:
    a) the run's work ignores the limit (pure-Python 4 s): at 3 s the run is failed for the tab — last result
       PAINT_TIMED_OUT, no current run (the tab's ``active`` ends, the poll stops) — while ``_run_bounded`` still
       holds the slot; it returns PAINT_TIMED_OUT after the work ended (~4 s).
    b) the work starts the retexture worker (a fake that sleeps 60 s with a child): the worker is killed at the
       deadline (RetextureFailed RUN_DEADLINE, both pids gone), ``_run_bounded`` returns PAINT_TIMED_OUT in < 10 s.
    c) the tab's poll (useOutfitBodies.ts) stops when the server reports no run and after POLL_MAX polls; the tab
       shows a Retry for a failed painted-body run.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD_COMMIT = "193321cf"  # the last artefact_graph with the name rule
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def load_old_graph():
    """artefact_graph.py as of ``OLD_COMMIT``, as its own module (the fails-on-old-code proof)."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/artefact_graph.py"],
                         capture_output=True, check=True).stdout
    spec = importlib.util.spec_from_loader("app.core._artefact_graph_old", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.core"
    sys.modules[spec.name] = mod  # dataclasses look their module up there
    exec(compile(src, f"artefact_graph.py@{OLD_COMMIT}", "exec"), mod.__dict__)
    return mod


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="painted-body-gc-") as tmp:
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

        from fastapi import HTTPException

        from app.core import artefact_graph as ag, base_body, body_retexture as br, garment_store as gs
        from app.core import model3d, outfit_bodies as ob
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.routes.outfit_bodies import delete_outfit_body
        old_ag = load_old_graph()
        # A piece change WITHOUT the render purge (module docstring).
        inventory._invalidate_renders_for_item = lambda item_id: None
        ob._base_ready = lambda c, b: ""  # the fixture's base is synthetic bytes; readiness is not under test

        def make(char: str, mode: str):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender", "outfit_body_mode": mode}
            assert save_character_profile(char, human, create_new=True)
            touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + char.encode() * 8)
            prof = get_character_profile(char)
            prof["profile_image"] = f"{char}_1.png"
            assert save_character_profile(char, prof)
            assert base_body.set_pipeline(char, True)
            ids = {}
            for key, slots, own in (("top", ["top"], False), ("skirt", ["bottom"], False),
                                    ("skirt2", ["bottom"], False), ("dress", ["outer"], True)):
                op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "own_mesh": own}
                ids[key] = inventory.add_item(name=f"{key} {char}", category="outfit_piece", item_id=f"{key}_{char.lower()}",
                                              prompt_fragment=f"a {key}", outfit_piece=op)["id"]
                inventory.add_to_inventory(char, ids[key])
            cdir = get_character_dir(char)
            M, R = cdir / "model3d", cdir / "model_refs"
            bsig = base_body.base_signature(char)
            base_glb = b"BASE-GLB-" + char.encode()
            for kind in ("tpose", "tpose_back"):
                touch(R / f"{kind}_{bsig}.png")
                touch(R / f"{kind}_{bsig}.json", {"base_signature": bsig})
            touch(M / f"{bsig}.glb", base_glb)
            touch(M / f"{bsig}.json", {"base": True, "rig": "mixamo"})
            touch(M / "unrigged" / f"{bsig}.glb")
            base_sha = hashlib.sha256(base_glb).hexdigest()
            fd = gs.garment_fsig(char, ids["dress"])
            fit = gs.garment_path(char, ids["dress"], fd, "fit")
            touch(fit)
            touch(fit.with_suffix(".json"), {"accepted": True, "base_model_sha256": base_sha, "item_id": ids["dress"],
                                             "fsig": fd, "base_signature": bsig, "body_id": bsig})
            return {"ids": ids, "bsig": bsig, "M": M, "R": R, "mode": mode, "base_sha": base_sha}

        def wear(char, pieces):
            prof = get_character_profile(char)
            prof["equipped_pieces"] = dict(pieces)
            assert save_character_profile(char, prof)

        def outfit(char, fx, pieces):
            """Worn + built in the character's mode: refs, model, texture store (+ body in mesh mode)."""
            wear(char, pieces)
            M, R, bsig = fx["M"], fx["R"], fx["bsig"]
            variant, token = mesh_variant(char, pieces), mesh_items_token(char, pieces)
            sig = mesh_signature(pieces, [], char, variant, token)
            tsig = base_body.predicted_texture_signatures(char, pieces, [], bsig=bsig)[fx["mode"]]
            manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant, "mesh_token": token,
                        "texture_signature": tsig, "base_signature": bsig}
            refs = [touch(R / f"{k}_{sig}{e}", manifest if e == ".json" else b"png")
                    for k in ("tpose", "tpose_back") for e in (".png", ".json")]
            meta = {"pieces": pieces, "items": [], "mesh_variant": variant, "mesh_token": token, "base_signature": bsig,
                    "base_model_sha256": fx["base_sha"], "texture_signature": tsig, "outfit_body_mode": fx["mode"],
                    "rig": "mixamo"}
            body = ""
            if fx["mode"] == "mesh":
                body = base_body.outfit_body_id(tsig)
                rec = {"outfit_body": {"body_id": body, "mode": "mesh", "texture_signature": tsig,
                                       "base_signature": bsig}}
                refs += [touch(R / f"tpose_{body}.png"), touch(R / f"tpose_{body}.json", rec),
                         touch(M / f"{body}.glb"), touch(M / f"{body}.json", {**rec, "rig": "mixamo"}),
                         touch(M / "unrigged" / f"{body}.glb"), touch(M / "unrigged" / f"{body}.json", rec)]
                meta.update(body_id=body, body_sha256="x")
            model = [touch(M / f"{sig}.glb", b"MODEL-" + sig.encode()), touch(M / f"{sig}.json", meta)]
            tm = {"base_signature": bsig, "texture_signature": tsig}
            store = [touch(R / "texture" / f"{k}_{tsig}{e}", tm if e == ".json" else b"png")
                     for k in ("tpose", "tpose_back") for e in (".png", ".json")]
            store += [touch(R / "texture" / "drafts" / f"tpose_back_{tsig}.png"),
                      touch(R / "texture" / "drafts" / f"tpose_back_{tsig}.json", tm),
                      touch(M / "texture" / f"{tsig}.glb"), touch(M / "texture" / f"{tsig}.json", tm)]
            return {"sig": sig, "tsig": tsig, "body": body, "refs": refs, "model": model, "store": store}

        def node(graph, char, tsig):
            n = next((n for n in graph.analyse(char, explicit=True).nodes if n.key == f"texture:{tsig}"), None)
            return n and (n.reachable, n.reason, n.parents.get("built_on", []), n.parents.get("outfits", []))

        def predicted(char, fx, pieces):
            return base_body.predicted_texture_signatures(char, pieces, [], bsig=fx["bsig"])[fx["mode"]]

        def set_text(item_id, text):
            assert inventory.update_item(item_id, {"prompt_fragment": text})

        def tab_entry(char, tsig):
            ob._verdicts.clear()  # a DB edit moves no file mtime; the display cache would hold it ≤ 20 s
            return next((t for t in ob.info(char)["textures"] if t.get("key") == tsig), None)

        def route_delete(char, tsig):
            try:
                return 200, delete_outfit_body(char, tsig, {})
            except HTTPException as e:
                return e.status_code, e.detail

        def precheck(char, tsig):
            ob._verdicts.clear()
            try:
                ob.check_run(char, "repaint", tsig)
                return ""
            except LookupError as e:
                return str(e)

        exists = lambda files: [p.exists() for p in files]  # noqa: E731

        # --- [1] text change --------------------------------------------------------------------------------
        print("[1] piece text changed -> the painted body is outdated; Delete")
        char = "Demo1"
        fx = make(char, "retexture")
        ids = fx["ids"]
        o1 = outfit(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        t1 = o1["tsig"]
        check("[1] T1 current", node(ag, char, t1), (True, ag.CURRENT_TEXTURE, [], [o1["sig"]]))
        check("[1] delete current -> 409", route_delete(char, t1), (409, ob.PAINTED_NEEDED))
        check("[1] delete unknown -> 404", route_delete(char, "tex000000000000"), (404, ob.NO_PAINTED_BODY))
        check("[1] repaint pre-check while current", precheck(char, t1), ob.NO_SOURCE)
        set_text(ids["skirt"], "a long pleated skirt")
        t1n = predicted(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        check("[1] O1 paints another tsig now", t1n != t1, True)
        check("[1] T1 outdated", node(ag, char, t1), (False, ag.OUTDATED_TEXTURE, [o1["sig"]], []))
        check(f"[1] OLD rule ({OLD_COMMIT}) keeps T1", (node(old_ag, char, t1) or (None,))[0], True)
        entry = tab_entry(char, t1) or {}
        gc = entry.get("gc") or {}
        check("[1] tab verdict", (gc.get("kept"), gc.get("reason"), len(gc.get("outfits") or []), bool(gc.get("free"))),
              (False, ob.PAINTED_OUTDATED, 1, True))
        check("[1] tab blocked", {k: (entry.get("blocked") or {}).get(k) for k in ("delete", "regenerate")},
              {"delete": "", "regenerate": ob.PAINTED_CANNOT_REPAINT})
        check("[1] repaint pre-check outdated", precheck(char, t1), ob.PAINTED_CANNOT_REPAINT)
        status, report = route_delete(char, t1)
        check("[1] delete outdated", (status, report.get("deleted_files") if status == 200 else report),
              (200, len(o1["store"])))
        check("[1] T1's files gone", exists(o1["store"]), [False] * len(o1["store"]))
        check("[1] O1 model + refs stay", exists(o1["model"] + o1["refs"]), [True] * (len(o1["model"] + o1["refs"])))
        check("[1] tab no longer lists T1", tab_entry(char, t1), None)

        # --- [2] own-mesh flag removed ----------------------------------------------------------------------
        print("[2] own-mesh flag removed -> outdated")
        char = "Demo2"
        fx = make(char, "retexture")
        ids = fx["ids"]
        o2 = outfit(char, fx, {"top": ids["top"], "outer": ids["dress"]})
        t2 = o2["tsig"]
        mi = base_body.predicted_mesh_items(char, {"top": ids["top"], "outer": ids["dress"]}, mode="retexture",
                                            bsig=fx["bsig"])
        check("[2] the dress is left out (accepted fit)", (mi.get("effective"), mi.get("unpainted")),
              ([ids["dress"]], [ids["dress"]]))
        check("[2] T2 current", node(ag, char, t2)[:2], (True, ag.CURRENT_TEXTURE))
        op = dict(inventory.get_item(ids["dress"])["outfit_piece"])
        op["own_mesh"] = False
        assert inventory.update_item(ids["dress"], {"outfit_piece": op})
        check("[2] painted now -> other tsig", predicted(char, fx, {"top": ids["top"], "outer": ids["dress"]}) != t2,
              True)
        check("[2] T2 outdated", node(ag, char, t2), (False, ag.OUTDATED_TEXTURE, [o2["sig"]], []))
        check(f"[2] OLD rule ({OLD_COMMIT}) keeps T2", (node(old_ag, char, t2) or (None,))[0], True)
        report = ag.collect(char, explicit=True, reason="smoke")
        check("[2] collect deletes T2", ([e["key"] for e in report["orphans"] if e["kind"] == "texture"],
                                         exists(o2["store"])), ([f"texture:{t2}"], [False] * len(o2["store"])))
        check("[2] O2 model stays", exists(o2["model"]), [True, True])

        # --- [3] piece swapped ------------------------------------------------------------------------------
        print("[3] piece swapped -> kept while the old outfit can be worn, gone once it cannot")
        char = "Demo3"
        fx = make(char, "retexture")
        ids = fx["ids"]
        o1 = outfit(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        wear(char, {"top": ids["top"], "bottom": ids["skirt2"]})
        check("[3] T1 still current", node(ag, char, o1["tsig"])[:2], (True, ag.CURRENT_TEXTURE))
        ag.collect(char, explicit=True, reason="smoke")
        check("[3] collect keeps T1", exists(o1["store"]), [True] * len(o1["store"]))
        inventory.remove_from_inventory(char, ids["skirt"], force=True)
        check("[3] skirt gone: T1 named by no live outfit", node(ag, char, o1["tsig"])[:2],
              (False, "no live outfit names it"))
        ag.collect(char, explicit=True, reason="smoke")
        check("[3] T1's files gone", exists(o1["store"]), [False] * len(o1["store"]))

        # --- [4] served model (mesh) ------------------------------------------------------------------------
        print("[4] the served model keeps working: texture goes, model + body stay")
        char = "Demo4"
        fx = make(char, "mesh")
        ids = fx["ids"]
        o1 = outfit(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        check("[4] T1 current, B1 named", (node(ag, char, o1["tsig"])[:2], bool(o1["body"])),
              ((True, ag.CURRENT_TEXTURE), True))
        set_text(ids["skirt"], "a long pleated skirt")
        report = ag.collect(char, explicit=True, reason="smoke")
        check("[4] only T1 collected", sorted(e["key"] for e in report["orphans"]), [f"texture:{o1['tsig']}"])
        check("[4] T1's files gone", exists(o1["store"]), [False] * len(o1["store"]))
        check("[4] served model + B1 stay", exists(o1["model"] + o1["refs"]), [True] * len(o1["model"] + o1["refs"]))
        check("[4] O1 still served", model3d.find_model3d(char, o1["sig"]) is not None, True)

        # --- [5] repaint publishing another tsig -------------------------------------------------------------
        print("[5] a repaint that paints another tsig fails, nothing under the old key")
        char = "Demo5"
        fx = make(char, "retexture")
        ids = fx["ids"]
        o1 = outfit(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        saved = (ob.texture_source, base_body.generate_dressed_images, base_body.dressed_image,
                 model3d.generate_for_current_outfit)
        other = "tex999999999999"

        def fake_build(character_name, *, signature, force):
            sidecar = fx["M"] / f"{signature}.json"
            meta = json.loads(sidecar.read_text())
            meta["texture_signature"] = other
            sidecar.write_text(json.dumps(meta))
            return {"ok": True}
        ob.texture_source = lambda c, t, users, **k: o1["sig"]
        base_body.generate_dressed_images = lambda *a, **k: None
        base_body.dressed_image = lambda c, view, sig, bsig: fx["R"] / f"tpose_{o1['sig']}.png"
        model3d.generate_for_current_outfit = fake_build
        try:
            result = ob.repaint_texture(char, o1["tsig"])
        finally:
            (ob.texture_source, base_body.generate_dressed_images, base_body.dressed_image,
             model3d.generate_for_current_outfit) = saved
        check("[5] PAINTED_AS_OTHER", result, {"ok": False, "error": ob.PAINTED_AS_OTHER})

        # --- [6] time limit ---------------------------------------------------------------------------------
        print("[6] the painted-body run has a hard time limit")
        config._CONFIG.setdefault("body_retexture", {})["run_timeout_seconds"] = 2
        check("[6] limit read", ob.paint_timeout_s(), 2)
        real_paint = ob.paint_worn
        char = "Demo5"
        key = o1["tsig"]
        # a) work that ignores the limit
        ob.paint_worn = lambda c, k, deadline=None: (time.sleep(4), {"ok": True, "error": ""})[1]
        job = ob._Job("paint", key)
        with ob._lock:
            ob._current[char] = job
        out, t0 = {}, time.monotonic()
        runner = threading.Thread(target=lambda: out.update(r=ob._run_bounded(char, job), t=time.monotonic() - t0))
        runner.start()
        time.sleep(3)
        with ob._lock:
            last = dict(ob._results.get((char, key)) or {})
        check("[6a] at 3 s: failed for the tab, no current run, slot still held",
              (last.get("error"), ob._run_state(char, key)[0], runner.is_alive()), (ob.PAINT_TIMED_OUT, "", True))
        runner.join(10)
        check("[6a] returns PAINT_TIMED_OUT after the work ended", (out.get("r"), out.get("t", 0) >= 3.9),
              ({"ok": False, "error": ob.PAINT_TIMED_OUT}, True))
        # b) the retexture worker is killed at the limit
        fake = root / "sleep"
        (fake / ".venv" / "bin").mkdir(parents=True)
        (fake / ".venv" / "bin" / "python").symlink_to(Path(sys.executable).resolve())
        (fake / "body_core").mkdir()
        (fake / "body_core" / "__init__.py").write_text("")
        pidfile = root / "pids.json"
        (fake / "body_core" / "__main__.py").write_text(
            "import json, os, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"json.dump({{'worker': os.getpid(), 'child': child.pid}}, open({str(pidfile)!r}, 'w'))\n"
            "time.sleep(60)\n")
        config._CONFIG["body_retexture"].update(worker_dir=str(fake), timeout_seconds=1800)
        raised = []

        def paint_with_worker(c, k, deadline=None):
            v = {"front": (touch(root / "d.png"), touch(root / "r.png"))}
            try:
                br.retexture(touch(root / "in.glb"), v, root / "out.glb", proof=root / "proof.json",
                             atlas=root / "atlas.png")
            except br.RetextureFailed as e:
                raised.append(str(e))
                return {"ok": False, "error": str(e)}
            return {"ok": True, "error": ""}
        ob.paint_worn = paint_with_worker
        job = ob._Job("paint", key)
        t0 = time.monotonic()
        result = ob._run_bounded(char, job)
        took = time.monotonic() - t0
        ob.paint_worn = real_paint
        check("[6b] PAINT_TIMED_OUT within 10 s", (result, took < 10), ({"ok": False, "error": ob.PAINT_TIMED_OUT}, True))
        check("[6b] worker killed at the run's limit", raised, [br.RUN_DEADLINE])
        pids = json.loads(pidfile.read_text()) if pidfile.is_file() else {}
        until = time.monotonic() + 3
        while time.monotonic() < until and any(alive(p) for p in pids.values()):
            time.sleep(0.05)
        check("[6b] worker + child gone", (sorted(pids), [alive(p) for p in pids.values()]),
              (["child", "worker"], [False, False]))
        # c) the client side
        hook = (ROOT / "frontend/src/tabs/characters/useOutfitBodies.ts").read_text()
        field = (ROOT / "frontend/src/tabs/characters/FieldOutfitBody.tsx").read_text()
        check("[6c] poll stops on no run and after POLL_MAX",
              ("if (!d?.active) return" in hook, "if (n >= POLL_MAX) return" in hook), (True, True))
        check("[6c] a failed painted-body run offers Retry", "t('Retry')" in field, True)

    print()
    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
