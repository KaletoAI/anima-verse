#!/usr/bin/env python3
"""Painted bodies go by reachability, and their Delete in the Figure tab's stored list
(app/core/artefact_graph.py ``_current_textures`` / ``delete_texture``, app/core/figure.py ``delete_stored`` ->
app/core/outfit_bodies.py ``delete_texture``).

Since Task 11 of plan 2026-11-12-unified-worn-pieces the Outfit body tab is gone with its runs: its verdict line,
the repaint pre-check, the repaint publishing another tsig (was [5]) and the bounded painted-body run with its time
limit (was [6], ``body_retexture.run_timeout_seconds`` / ``run_deadline``) are removed with it; the Delete goes
through ``figure.delete_stored`` (was the tab's DELETE route).

Usage:
    ./.venv/bin/python scripts/smoke_painted_body_reachability.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server process. Files are synthetic bytes; only names and JSON sidecars matter to the GC.

THE BUG (2026-11-11): a painted body (``model_refs/texture/[drafts/]tpose[_back]_<T>`` + ``model3d/texture/<T>``)
stayed for good once a piece of its outfit changed. The old rule (commit 193321cf) kept a texture while a
live outfit's sidecars NAMED it; an outfit stays live through its recorded manifest (the outfit rule re-signs with
the recorded mesh token), so its old sidecars kept naming the old tsig. The rule: a texture lives while a live
outfit would PAINT it now (since plan 2026-11-12-unified-worn-pieces Task 5: ``figure.predicted_keys``' texture key
under the items' modes now, plus the tsig of a current dressed front — ``base_body.front_texture_signature``); one
only named is outdated (``OUTDATED_TEXTURE``, parent ``built_on``).

The fails-on-old-code proof (``git show 193321cf:app/core/artefact_graph.py`` executed beside today's core) is left
out since Task 5: that module no longer runs against today's core (it reads ``garment_store.SOURCE_DIR``, gone since
— it was red at 54cea23e already), and pinning it to a newer commit would prove nothing about the name rule.

Fixture (``make(char, mode)``, a fresh character per scenario): items top {top}, skirt {bottom}, skirt2 {bottom}
painted (mode "mesh": in the body — the outfit body mode follows the worn pieces, interim rule of plan
2026-11-12-unified-worn-pieces Task 2), dress {outer} own mesh with an accepted fit on the base model (so both modes leave it out of the paint), all
in the inventory; pipeline on; base refs + model. ``outfit(char, pieces)`` worn and stored like a build leaves it:
front/back refs + model sidecar naming T, the texture store of T (8 files: store tpose/tpose_back .png/.json,
drafts/tpose_back .png/.json, model3d/texture/<T>.glb/.json). Retexture mode: T = the texture key its pieces paint
now (``figure.predicted_keys(...)[1]``), the front carries no base view sha. Mesh mode: nothing is painted (texture
key ""), so T = the tsig of the outfit's dressed front, made current for the base (base_image_sha256 of the base
front; ``base_body.front_texture_signature``) — the views the shape is meshed from; plus the outfit body B = the
shape key of its in-body set (``figure.predicted_keys(...)[0]``; refs + model + unrigged, shape record) and the
model's ``body_id`` B.
A piece change is applied with ``inventory._invalidate_renders_for_item`` switched off — as on the clone, where the
outfits' fronts and models outlived the stilettos' own-mesh flag; with the purge the old rule already saw no name.

Expected, by hand (the rule above):
[1] text change (retexture). O1 {top, skirt} on T1: T1 kept, reason CURRENT_TEXTURE, outfits [O1]. Delete
    (figure.delete_stored) on T1 -> LookupError PAINTED_NEEDED; on tex000000000000 -> UnknownBody.
    Skirt text "a skirt" -> "a long pleated skirt": the dress text of O1 changes, so O1 paints T1' != T1; O1 stays
    live (the text is not part of its signature) -> T1 outdated: not reachable, reason OUTDATED_TEXTURE, built_on
    [O1], no outfits; figure.stored lists T1 deletable. Delete -> 8 files deleted, none of T1 left; O1's model +
    refs untouched; figure.stored no longer lists T1.
[2] own-mesh flag removed (retexture). O2 {top, dress} on T2 (dress its own mesh with an accepted fit, so left
    out: worn_sets own {dress}, painted {top}). Flag off: the dress is painted now
    -> T2' != T2; O2 stays live (recorded token) -> T2 outdated. collect(explicit)
    deletes T2's 8 files; O2's model stays.
[3] piece swapped (retexture). O1 {top, skirt} on T1, then skirt2 worn instead (O4, nothing built): O1 is still
    producible (skirt in the inventory) -> T1 stays current (worn again it paints T1). collect deletes 0 of T1. Skirt
    out of the inventory -> O1 no longer producible -> T1 named by no live outfit -> collect deletes its 8 files.
[4] served model (mesh). O1 on B1 (model body_id B1, texture T1 of its current front), then the skirt text
    change: the front now stands for T1' != T1 and the in-body set has another shape key -> T1 outdated, its 8
    files go; the served model of O1 (a self-contained copy) and B1 stay — B1 is named as body_id by the live O1
    model (the body clause's second half).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


        from app.core import artefact_graph as ag, base_body, garment_store as gs
        from app.core import figure, model3d, outfit_bodies as ob
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        # A piece change WITHOUT the render purge (module docstring).
        inventory._invalidate_renders_for_item = lambda item_id: None

        def make(char: str, mode: str):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender"}
            assert save_character_profile(char, human, create_new=True)
            touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + char.encode() * 8)
            prof = get_character_profile(char)
            prof["profile_image"] = f"{char}_1.png"
            assert save_character_profile(char, prof)
            ids = {}
            # The outfit body mode follows the worn pieces (interim rule, plan 2026-11-12-unified-worn-pieces
            # Task 2): mesh mode = the painted pieces in the body.
            painted = "in_body" if mode == "mesh" else "painted"
            for key, slots, own in (("top", ["top"], False), ("skirt", ["bottom"], False),
                                    ("skirt2", ["bottom"], False), ("dress", ["outer"], True)):
                op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "mesh_mode": "own_mesh" if own else painted}
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
            manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant, "mesh_token": token,
                        "base_signature": bsig}
            shape, tsig = figure.predicted_keys(char, pieces, [], bsig=bsig)
            if fx["mode"] == "mesh":
                # Nothing painted on the shape: T = what the current dressed front stands for (module docstring).
                manifest["base_image_sha256"] = hashlib.sha256((R / f"tpose_{bsig}.png").read_bytes()).hexdigest()
                touch(R / f"tpose_{sig}.png", b"png")
                touch(R / f"tpose_{sig}.json", manifest)
                tsig = base_body.front_texture_signature(char, sig, bsig=bsig)
            manifest["texture_signature"] = tsig
            refs = [touch(R / f"{k}_{sig}{e}", manifest if e == ".json" else b"png")
                    for k in ("tpose", "tpose_back") for e in (".png", ".json")]
            meta = {"pieces": pieces, "items": [], "mesh_variant": variant, "mesh_token": token, "base_signature": bsig,
                    "base_model_sha256": fx["base_sha"], "texture_signature": tsig,
                    "rig": "mixamo"}
            body = ""
            if fx["mode"] == "mesh":
                body = shape
                rec = {"outfit_body": {"body_id": body, "shape_key": body, "version": figure.SHAPE_VERSION,
                                       "base_signature": bsig, "built_for": sig}}
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
            # Retexture scenarios only: the texture key the pieces paint now.
            return figure.predicted_keys(char, pieces, [], bsig=fx["bsig"])[1]

        def set_text(item_id, text):
            assert inventory.update_item(item_id, {"prompt_fragment": text})

        def listed(char, tsig):
            return next((e for e in figure.stored(char) if e.get("key") == tsig), None)

        def route_delete(char, tsig):
            """The Figure tab's Delete (routes/figure.py maps UnknownBody -> 404, LookupError -> 409)."""
            try:
                return 200, figure.delete_stored(char, tsig)
            except ob.UnknownBody as e:
                return 404, str(e) or ob.NO_PAINTED_BODY
            except LookupError as e:
                return 409, str(e)

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
        set_text(ids["skirt"], "a long pleated skirt")
        t1n = predicted(char, fx, {"top": ids["top"], "bottom": ids["skirt"]})
        check("[1] O1 paints another tsig now", t1n != t1, True)
        check("[1] T1 outdated", node(ag, char, t1), (False, ag.OUTDATED_TEXTURE, [o1["sig"]], []))
        check("[1] listed deletable", (listed(char, t1) or {}).get("deletable"), True)
        status, report = route_delete(char, t1)
        check("[1] delete outdated", (status, report.get("deleted_files") if status == 200 else report),
              (200, len(o1["store"])))
        check("[1] T1's files gone", exists(o1["store"]), [False] * len(o1["store"]))
        check("[1] O1 model + refs stay", exists(o1["model"] + o1["refs"]), [True] * (len(o1["model"] + o1["refs"])))
        check("[1] no longer listed", listed(char, t1), None)

        # --- [2] own-mesh flag removed ----------------------------------------------------------------------
        print("[2] own-mesh flag removed -> outdated")
        char = "Demo2"
        fx = make(char, "retexture")
        ids = fx["ids"]
        o2 = outfit(char, fx, {"top": ids["top"], "outer": ids["dress"]})
        t2 = o2["tsig"]
        sets = figure.worn_sets(char, pieces={"top": ids["top"], "outer": ids["dress"]})
        check("[2] the dress is left out (own mesh, accepted fit)", (sorted(sets.own), sets.painted),
              ([ids["dress"]], (ids["top"],)))
        check("[2] T2 current", node(ag, char, t2)[:2], (True, ag.CURRENT_TEXTURE))
        op = dict(inventory.get_item(ids["dress"])["outfit_piece"])
        op["mesh_mode"] = "painted"
        assert inventory.update_item(ids["dress"], {"outfit_piece": op})
        check("[2] painted now -> other tsig", predicted(char, fx, {"top": ids["top"], "outer": ids["dress"]}) != t2,
              True)
        check("[2] T2 outdated", node(ag, char, t2), (False, ag.OUTDATED_TEXTURE, [o2["sig"]], []))
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
        check("[4] T1 current, B1 a shape key", (node(ag, char, o1["tsig"])[:2],
                                                  base_body.is_texture_signature(o1["tsig"]),
                                                  base_body.is_outfit_body_signature(o1["body"])),
              ((True, ag.CURRENT_TEXTURE), True, True))
        set_text(ids["skirt"], "a long pleated skirt")
        report = ag.collect(char, explicit=True, reason="smoke")
        check("[4] only T1 collected", sorted(e["key"] for e in report["orphans"]), [f"texture:{o1['tsig']}"])
        check("[4] T1's files gone", exists(o1["store"]), [False] * len(o1["store"]))
        check("[4] served model + B1 stay", exists(o1["model"] + o1["refs"]), [True] * len(o1["model"] + o1["refs"]))
        check("[4] O1 still served", model3d.find_model3d(char, o1["sig"]) is not None, True)

    print()
    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
