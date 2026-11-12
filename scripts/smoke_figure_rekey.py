#!/usr/bin/env python3
"""Stored outfit bodies re-keyed onto their shape keys at boot (app/core/figure_migration.py
``rekey_bodies_once`` / ``rekey_body``), ``figure.stored_shape`` / ``figure.predicted_keys`` and the artefact GC by
shape and texture keys (app/core/artefact_graph.py) — plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
Task 5, builder-check ruling 4.

Usage:
    ./.venv/bin/python scripts/smoke_figure_rekey.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no Blender, no server. Files are synthetic bytes; only names and JSON sidecars matter. The shared item
library is redirected to a temp file (the mode migration would rewrite the tracked one).

``base_body.dress_text`` is replaced by a hand rule so every text below is known: the worn pieces in slot order
outer, top, bottom, feet, minus ``mesh_items``, joined "wear:" + "+".join(ids) ("" when none) — the same text for
every view. Dressed views: front, back (side views off, the default).

FIXTURE (items stored RAW without a mode; the mode migration of Task 3 runs first, for real):
  items coat {outer}, blouse {top}, shirt {top}.
  Kai: pipeline on, stored ``outfit_body_mode: "mesh"``, wears O1 {outer: coat, top: blouse}, holds all three.
  Kira: pipeline on, ``"retexture"``, wears K1 {top: shirt}, holds shirt.
  Migration (ruling 4): coat and blouse are worn only by Kai (mesh) -> in_body; shirt is worn by Kira (retexture)
  -> painted.
  Kai's stored bodies, each with the OLD record {body_id, mode "mesh", version 1, texture_signature T, base_signature,
  base_variant, built_for, views, used_views [front, back], view_guard {}, view_warnings []}:
    OLD  = ob0000aaaa built for O1, T_A = tex + "a"*12, store texts "wear:coat+blouse" (both views); files: refs
           tpose[_back]_OLD .png/.json, model3d OLD .glb/.json, unrigged/, prerig/, rollback/OLD/OLD.glb, fits
           garments/bodies/OLD/hat_abcdefabcdef .glb/.json, low/hat_abcdefabcdef.glb, failed/hat_abcdefabcdef.json
           (records name body_id OLD); the outfit model of O1 names body_id OLD (O1 front refs carry its manifest).
    OLD2 = ob0000bbbb built for O2 {top: shirt} (front refs only, no model), T_B, store texts "wear:shirt".
    OLD3 = ob0000cccc built for O3 {outer: coat, top: shirt}, T_C, store texts "wear:coat+shirt"; only O3's MODEL
           sidecar carries its pieces (the manifest fallback), and it names body_id OLD3.
    OLD4 = ob0000dddd built for O1 on base "base0123abcd" (an older base), T_A.
  Kira's painted body: the texture store + model3d/texture/<TK> of TK = what K1 paints now, her model names TK.

EXPECTED, BY HAND
  Shape key (figure.shape_key, spec ruling 1): "ob" + sha256(canonical JSON of {"version": 2, "base_signature":
  bsig, "base_variant": V1, "hair_in_body": H, "side_views": false, "dress_text": {"front": "wear:coat+blouse",
  "back": "wear:coat+blouse"}})[:8], canonical = sort_keys, separators (",", ":"), UTF-8; V1 = outfit_variant(Kai,
  O1) (the build's variant of a dressed combination), H = garment_hair.hair_in_body(Kai) — both read from the code
  as INPUTS of the fixture, not under test.
  TK (plain body, figure.texture_key = today's tsig): "tex" + sha256(canonical {"version": 1, "base_signature":
  bsigK, "base_variant": VK, "side_views": false, "dress_text": {"front": "wear:shirt", "back": "wear:shirt"}})[:12].
[1] worn_sets(Kai, O1): in_body (blouse, coat), painted (). K = the hand key; figure.shape_key agrees.
    rekey_bodies_once() = {Kai: {OLD: K, OLD2: "stale", OLD3: "stale", OLD4: "stale"}} (Kira has no body):
    OLD matches (base, in_body, variant V1, text "wear:coat+blouse" both views); OLD2: shirt is painted, nothing in
    the body; OLD3: in-body text "wear:coat" != "wear:coat+shirt" (the painted shirt is in its mesh); OLD4: older
    base. Every file of body_chain(OLD) exists under the name with OLD -> K (same bytes for non-JSON), none under
    OLD, no path below the three roots names OLD; garments/bodies/K/ holds the fit + low + failed records, each
    naming body_id K; model3d/K.json: record body_id == shape_key == K, version 2, shape_inputs = the hand inputs,
    rekeyed_from {OLD, T_A, 1}, no mode / texture_signature, ``signature`` K, ``source_image`` tpose_K.png; O1's
    model names body_id K, its body_sha256 unchanged (the bytes did not change). OLD2 / OLD3 / OLD4 untouched
    (paths + bytes). One log line per decision.
[2] = OLD2 "stale" above, its files untouched.
[3] world_kv rekeyed_figure_bodies == "1"; the second call -> None, nothing changes.
[4] stored_shape(Kai, K, view_shas=<record views>) -> the sidecar (rig mixamo); other views -> None; OLD3 (old
    record) -> None.
[5] artefact_graph.analyse(Kai): K reachable "shape of a live outfit" (O1 predicts K); its body fit goes with
    its garment only — "garment fingerprint gone" (the fixture's "hat" is held by no one), never "body gone";
    OLD2 unreachable "no live outfit on it"; OLD3 reachable "named by a live outfit model" (O3's model); OLD4
    unreachable "older base". analyse(Kira): texture TK reachable CURRENT_TEXTURE; predicted_keys(Kira, K1) =
    (bsigK, TK).
[6] All or nothing: a body OLD5 = ob0000eeee (refs, model, fit, an outfit model aaaabbbbcccc naming it) re-keyed to
    ob0000ffff by rekey_body: a rename failing at the 3rd move -> raises, the tree (every path + bytes below the
    three roots) identical to before; a sidecar write failing at the 2nd write -> same; a target name already taken
    -> RekeyConflict, nothing touched; then without a failure -> every file renamed (count = the files with OLD5 in
    their path), the outfit model names ob0000ffff.
[7] Fails on the old code (BASE 54cea23e): figure_migration.py there has no rekey_bodies_once, figure.py no
    stored_shape / predicted_keys, artefact_graph.py still reads roots.mode; app/server.py now calls
    migrate_modes_once < rekey_bodies_once < the refit sweep < the hub-job resumer.
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "54cea23e"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


SLOT_ORDER = ("outer", "top", "bottom", "feet")


def fake_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=()):
    left_out = set(mesh_items or ())
    ids = [pieces[s] for s in SLOT_ORDER if (pieces or {}).get(s) and pieces[s] not in left_out]
    return "wear:" + "+".join(ids) if ids else ""


def raw_piece(item_id: str, slots):
    from app.core import db
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, name, category, prompt_fragment, pieces, slots, meta, created_at,"
                     " updated_at) VALUES (?, ?, 'outfit_piece', '', ?, '[]', '{}', 'x', 'x')",
                     (item_id, item_id, json.dumps({"slots": list(slots)})))
    from app.core.motion_item_cache import invalidate
    invalidate()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-rekey-") as tmp:
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

        from app.core import artefact_graph as ag, base_body, figure, figure_migration as fm, garment_hair
        from app.core.model_refs import current_outfit_state, mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        from app.models.world import get_world_setting
        shared_file = root / "shared_items.json"
        shared_file.write_text(json.dumps({"items": []}))
        inventory._get_shared_items_file = lambda: shared_file
        inventory._invalidate_renders_for_item = lambda item_id: None
        base_body.dress_text = fake_dress_text
        check("fixture: dressed views", base_body.dressed_views(), ("front", "back"))

        for item_id, slots in (("coat", ["outer"]), ("blouse", ["top"]), ("shirt", ["top"])):
            raw_piece(item_id, slots)

        def make(char, mode, pieces, held):
            prof = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                    "character_appearance": "slender", "outfit_body_mode": mode, "equipped_pieces": dict(pieces),
                    "model_pipeline": "base_body"}
            assert save_character_profile(char, prof, create_new=True)
            touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + char.encode() * 8)
            prof = get_character_profile(char)
            prof["profile_image"] = f"{char}_1.png"
            assert save_character_profile(char, prof)
            for item_id in held:
                inventory.add_to_inventory(char, item_id)

        O1 = {"outer": "coat", "top": "blouse"}
        O2 = {"top": "shirt"}
        O3 = {"outer": "coat", "top": "shirt"}
        make("Kai", "mesh", O1, ["coat", "blouse", "shirt"])
        make("Kira", "retexture", O2, ["shirt"])
        migrated = fm.migrate_modes_once()
        check("fixture: modes migrated", (migrated or {}).get("items"),
              {"blouse": "in_body", "coat": "in_body", "shirt": "painted"})

        cdir = get_character_dir("Kai")
        M, R, G = cdir / "model3d", cdir / "model_refs", cdir / "garments"
        bsig = base_body.base_signature("Kai")

        def sig_of(char, pieces):
            return mesh_signature(pieces, [], char, mesh_variant(char, pieces), mesh_items_token(char, pieces))

        def front_refs(char_dir, sig, pieces, char):
            manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": mesh_variant(char, pieces),
                        "mesh_token": mesh_items_token(char, pieces)}
            for kind in ("tpose", "tpose_back"):
                touch(char_dir / "model_refs" / f"{kind}_{sig}.png", b"PNG-" + sig.encode())
                touch(char_dir / "model_refs" / f"{kind}_{sig}.json", manifest)

        def store(char_dir, tsig, text, base):
            for kind in ("tpose", "tpose_back"):
                touch(char_dir / "model_refs" / "texture" / f"{kind}_{tsig}.png", b"STORE-" + tsig.encode())
                touch(char_dir / "model_refs" / "texture" / f"{kind}_{tsig}.json",
                      {"texture_signature": tsig, "base_signature": base, "dress_text": text})

        VIEWS = {"front": "f" * 64, "back": "b" * 64}

        def body(old, *, tsig, built_for, base, variant, fits=False, rollback=False):
            rec = {"body_id": old, "mode": "mesh", "version": 1, "texture_signature": tsig, "base_signature": base,
                   "base_variant": variant, "built_for": built_for, "views": dict(VIEWS),
                   "used_views": ["front", "back"], "view_guard": {}, "view_warnings": []}
            for kind in ("tpose", "tpose_back"):
                touch(R / f"{kind}_{old}.png", b"BODYREF-" + kind.encode() + old.encode())
                touch(R / f"{kind}_{old}.json", {"texture_signature": tsig, "outfit_body": rec})
            touch(M / f"{old}.glb", b"BODY-GLB-" + old.encode())
            touch(M / f"{old}.json", {"rig": "mixamo", "signature": old, "source_image": f"tpose_{old}.png",
                                      "view_images": {"back": f"tpose_back_{old}.png"}, "outfit_body": rec})
            touch(M / "unrigged" / f"{old}.glb", b"UNRIGGED-" + old.encode())
            touch(M / "unrigged" / f"{old}.json", {"outfit_body": rec})
            touch(M / "prerig" / f"{old}.glb", b"PRERIG-" + old.encode())
            touch(M / "prerig" / f"{old}.json", {"outfit_body": rec})
            if rollback:
                touch(M / "rollback" / old / f"{old}.glb", b"ROLLBACK-" + old.encode())
            if fits:
                fit = {"accepted": True, "item_id": "hat", "fsig": "abcdefabcdef", "body_id": old,
                       "body_sha256": "9" * 64, "base_signature": base}
                touch(G / "bodies" / old / "hat_abcdefabcdef.glb", b"FIT-" + old.encode())
                touch(G / "bodies" / old / "hat_abcdefabcdef.json", fit)
                touch(G / "bodies" / old / "low" / "hat_abcdefabcdef.glb", b"FITLOW-" + old.encode())
                touch(G / "bodies" / old / "failed" / "hat_abcdefabcdef.json",
                      {"item_id": "hat", "fsig": "abcdefabcdef", "step": "fit", "error": "x", "body_id": old})
            return rec

        def outfit_model(sig, pieces, body_id, char="Kai"):
            meta = {"pieces": pieces, "items": [], "mesh_variant": mesh_variant(char, pieces),
                    "mesh_token": mesh_items_token(char, pieces), "base_signature": bsig, "body_id": body_id,
                    "body_sha256": hashlib.sha256(b"BODY-GLB-" + body_id.encode()).hexdigest(),
                    "outfit_body_mode": "mesh", "rig": "mixamo"}
            touch(M / f"{sig}.glb", b"MODEL-" + sig.encode())
            touch(M / f"{sig}.json", meta)

        OLD, OLD2, OLD3, OLD4 = "ob0000aaaa", "ob0000bbbb", "ob0000cccc", "ob0000dddd"
        TA, TB, TC = "tex" + "a" * 12, "tex" + "b" * 12, "tex" + "c" * 12
        sig1, sig2, sig3 = sig_of("Kai", O1), sig_of("Kai", O2), sig_of("Kai", O3)
        check("fixture: O1 is the worn signature", current_outfit_state("Kai")[2], sig1)
        V1, V2, V3 = (base_body.outfit_variant("Kai", p) for p in (O1, O2, O3))
        front_refs(cdir, sig1, O1, "Kai")
        front_refs(cdir, sig2, O2, "Kai")
        store(cdir, TA, "wear:coat+blouse", bsig)
        store(cdir, TB, "wear:shirt", bsig)
        store(cdir, TC, "wear:coat+shirt", bsig)
        body(OLD, tsig=TA, built_for=sig1, base=bsig, variant=V1, fits=True, rollback=True)
        body(OLD2, tsig=TB, built_for=sig2, base=bsig, variant=V2)
        body(OLD3, tsig=TC, built_for=sig3, base=bsig, variant=V3)
        body(OLD4, tsig=TA, built_for=sig1, base="base0123abcd", variant=V1)
        outfit_model(sig1, O1, OLD)
        outfit_model(sig3, O3, OLD3)

        # Kira's painted body.
        kdir = get_character_dir("Kira")
        bsigK = base_body.base_signature("Kira")
        VK = base_body.outfit_variant("Kira", O2)
        TK = "tex" + hashlib.sha256(canonical({"version": 1, "base_signature": bsigK, "base_variant": VK,
                                               "side_views": False, "dress_text": {"front": "wear:shirt",
                                                                                   "back": "wear:shirt"}})).hexdigest()[:12]
        sigK = sig_of("Kira", O2)
        front_refs(kdir, sigK, O2, "Kira")
        store(kdir, TK, "wear:shirt", bsigK)
        touch(kdir / "model3d" / "texture" / f"{TK}.glb", b"PAINTED-" + TK.encode())
        touch(kdir / "model3d" / "texture" / f"{TK}.json", {"texture_signature": TK, "base_signature": bsigK})
        touch(kdir / "model3d" / f"{sigK}.glb", b"MODEL-K")
        touch(kdir / "model3d" / f"{sigK}.json", {"pieces": O2, "items": [], "base_signature": bsigK,
                                                  "texture_signature": TK, "mesh_variant": mesh_variant("Kira", O2),
                                                  "mesh_token": mesh_items_token("Kira", O2), "rig": "mixamo"})

        def tree(char_dir):
            out = {}
            for name in ("model3d", "model_refs", "garments"):
                for p in sorted((char_dir / name).rglob("*")):
                    if p.is_file():
                        out[p.relative_to(char_dir).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            return out

        # --- [1] the re-key ------------------------------------------------------------------------------
        print("[1] OLD -> its shape key; the others stale")
        H = garment_hair.hair_in_body("Kai", get_character_profile("Kai"))
        sets = figure.worn_sets("Kai", pieces=O1)
        check("[1] worn sets of O1", (sets.in_body, sets.painted), (("blouse", "coat"), ()))
        inputs = {"version": 2, "base_signature": bsig, "base_variant": V1, "hair_in_body": H, "side_views": False,
                  "dress_text": {"front": "wear:coat+blouse", "back": "wear:coat+blouse"}}
        K = "ob" + hashlib.sha256(canonical(inputs)).hexdigest()[:8]
        check("[1] figure.shape_key == hand key", figure.shape_key("Kai", sets, bsig=bsig, variant=V1), K)
        nodes, _ = ag.scan("Kai")
        chain_keys = ag.body_chain(nodes, cdir, OLD)
        chain = sorted({p.relative_to(cdir).as_posix() for n in nodes if n.key in chain_keys
                        and n.kind in ("body", "body_fit") for p in n.files})
        check("[1] fixture: chain files", len(chain), 15)
        before = tree(cdir)
        others = {k: v for k, v in before.items() if any(o in k for o in (OLD2, OLD3, OLD4))}
        records = []
        handler = logging.Handler()
        handler.emit = lambda rec: records.append(rec.getMessage())
        fm.logger.addHandler(handler)
        result = fm.rekey_bodies_once()
        fm.logger.removeHandler(handler)
        check("[1] decisions", result, {"Kai": {OLD: K, OLD2: "stale", OLD3: "stale", OLD4: "stale"}})
        check("[1] one log line per decision",
              sorted(o for o in (OLD, OLD2, OLD3, OLD4)
                     if sum(1 for m in records if m.startswith("Re-key Kai: outfit body " + o)) == 1),
              sorted([OLD, OLD2, OLD3, OLD4]))
        after = tree(cdir)
        moved = {rel: rel.replace(OLD, K) for rel in chain}
        check("[1] every chain file under the new name", [moved[r] for r in chain if moved[r] not in after], [])
        check("[1] non-JSON bytes unchanged",
              [r for r in chain if not r.endswith(".json") and after.get(moved[r]) != before[r]], [])
        check("[1] nothing names OLD any more", [k for k in after if OLD in k], [])
        fit_dir = G / "bodies" / K
        check("[1] fits moved with the folder",
              sorted(p.relative_to(fit_dir).as_posix() for p in fit_dir.rglob("*") if p.is_file()),
              ["failed/hat_abcdefabcdef.json", "hat_abcdefabcdef.glb", "hat_abcdefabcdef.json",
               "low/hat_abcdefabcdef.glb"])
        check("[1] fit records name K",
              [json.loads((fit_dir / r).read_text()).get("body_id")
               for r in ("hat_abcdefabcdef.json", "failed/hat_abcdefabcdef.json")], [K, K])
        meta = json.loads((M / f"{K}.json").read_text())
        rec = meta.get("outfit_body") or {}
        check("[1] record keys", (rec.get("body_id"), rec.get("shape_key"), rec.get("version"),
                                  "mode" in rec, "texture_signature" in rec), (K, K, 2, False, False))
        check("[1] record shape_inputs", rec.get("shape_inputs"), inputs)
        check("[1] record rekeyed_from", rec.get("rekeyed_from"), {"body_id": OLD, "texture_signature": TA,
                                                                   "version": 1})
        check("[1] record kept the rest", (rec.get("built_for"), rec.get("views"), rec.get("base_variant")),
              (sig1, VIEWS, V1))
        check("[1] sidecar names", (meta.get("signature"), meta.get("source_image"), meta.get("view_images")),
              (K, f"tpose_{K}.png", {"back": f"tpose_back_{K}.png"}))
        check("[1] every body sidecar carries the new record",
              sorted({json.loads((cdir / moved[r]).read_text())["outfit_body"]["shape_key"]
                      for r in chain if r.endswith(".json") and "garments" not in r}), [K])
        o1 = json.loads((M / f"{sig1}.json").read_text())
        check("[1] O1's model names K, same body sha",
              (o1.get("body_id"), o1.get("body_sha256")),
              (K, hashlib.sha256(b"BODY-GLB-" + OLD.encode()).hexdigest()))
        check("[1] O1's body sha is the moved body's",
              hashlib.sha256((M / f"{K}.glb").read_bytes()).hexdigest(), o1.get("body_sha256"))
        check("[1]/[2] OLD2, OLD3, OLD4 untouched",
              {k: v for k, v in after.items() if any(o in k for o in (OLD2, OLD3, OLD4))}, others)

        # --- [3] once --------------------------------------------------------------------------------------
        print("[3] once per world")
        check("[3] flag", get_world_setting(fm.REKEY_FLAG), "1")
        check("[3] second call", fm.rekey_bodies_once(), None)
        check("[3] nothing changed", tree(cdir), after)

        # --- [4] stored_shape ------------------------------------------------------------------------------
        print("[4] stored_shape")
        got = figure.stored_shape("Kai", K, view_shas=dict(VIEWS))
        check("[4] current", (got or {}).get("rig"), "mixamo")
        check("[4] other views", figure.stored_shape("Kai", K, view_shas={"front": "0" * 64, "back": "b" * 64}),
              None)
        check("[4] old record", figure.stored_shape("Kai", OLD3, view_shas=dict(VIEWS)), None)

        # --- [5] the GC by shape and texture keys ------------------------------------------------------------
        print("[5] artefact GC")
        check("[5] predicted keys of O1", figure.predicted_keys("Kai", O1, [], bsig=bsig)[0], K)
        verdicts = {n.key: (n.reachable, n.reason) for n in ag.analyse("Kai").nodes
                    if n.kind in ("body", "body_fit")}
        check("[5] K", verdicts.get(K), (True, ag.SHAPE_OF_LIVE_OUTFIT))
        check("[5] K's fit judged by its garment, not its body",
              verdicts.get(f"bodyfit:{K}:hat_abcdefabcdef"), (False, "garment fingerprint gone"))
        check("[5] OLD2", verdicts.get(OLD2), (False, "no live outfit on it"))
        check("[5] OLD3", verdicts.get(OLD3), (True, "named by a live outfit model"))
        check("[5] OLD4", verdicts.get(OLD4), (False, "older base"))
        check("[5] Kira's keys", figure.predicted_keys("Kira", O2, [], bsig=bsigK), (bsigK, TK))
        tex = {n.key: (n.reachable, n.reason) for n in ag.analyse("Kira").nodes if n.kind == "texture"}
        check("[5] Kira's painted body", tex.get(f"texture:{TK}"), (True, ag.CURRENT_TEXTURE))

        # --- [6] all or nothing -------------------------------------------------------------------------------
        print("[6] a failure part-way leaves both names consistent")
        OLD5, NEW5 = "ob0000eeee", "ob0000ffff"
        body(OLD5, tsig=TA, built_for=sig1, base=bsig, variant=V1, fits=True, rollback=True)
        outfit_model("aaaabbbbcccc", O1, OLD5)
        snap = tree(cdir)
        n5 = len([k for k in snap if OLD5 in k])
        update = {"body_id": NEW5, "shape_key": NEW5, "version": 2, "mode": None}
        real_move, real_write = fm._move, fm._write

        def failing(real, at):
            calls = []

            def run(*args):
                calls.append(args)
                if len(calls) == at:
                    raise OSError("injected failure")
                return real(*args)
            return run
        for label, attr, at in (("rename", "_move", 3), ("sidecar write", "_write", 2)):
            setattr(fm, attr, failing(real_move if attr == "_move" else real_write, at))
            try:
                fm.rekey_body("Kai", OLD5, NEW5, record=update)
                raised = ""
            except OSError as e:
                raised = str(e)
            finally:
                fm._move, fm._write = real_move, real_write
            check(f"[6] {label} fails -> raised", raised, "injected failure")
            check(f"[6] {label} fails -> tree as before", tree(cdir), snap)
            check(f"[6] {label} fails -> no folder of the new id",
                  sorted(p.as_posix() for p in cdir.rglob("*") if NEW5 in p.name), [])
        touch(M / f"{NEW5}.glb", b"TAKEN")
        try:
            fm.rekey_body("Kai", OLD5, NEW5, record=update)
            raised = ""
        except fm.RekeyConflict as e:
            raised = type(e).__name__
        (M / f"{NEW5}.glb").unlink()
        check("[6] target taken -> RekeyConflict, nothing touched", (raised, tree(cdir)), ("RekeyConflict", snap))
        count = fm.rekey_body("Kai", OLD5, NEW5, record=update)
        done = tree(cdir)
        check("[6] then every file renamed", (count, len([k for k in done if NEW5 in k]),
                                              [k for k in done if OLD5 in k]), (n5, n5, []))
        check("[6] outfit model on it renamed in its sidecar",
              json.loads((M / "aaaabbbbcccc.json").read_text()).get("body_id"), NEW5)

        # --- [7] old code -----------------------------------------------------------------------------------
        print(f"[7] fails on the old code ({BASE})")
        old_mig = git("show", f"{BASE}:app/core/figure_migration.py").stdout
        old_fig = git("show", f"{BASE}:app/core/figure.py").stdout
        old_gc = git("show", f"{BASE}:app/core/artefact_graph.py").stdout
        check(f"[7] {BASE}: no rekey_bodies_once", ("def migrate_modes_once" in old_mig,
                                                    "def rekey_bodies_once" in old_mig), (True, False))
        check(f"[7] {BASE}: no stored_shape / predicted_keys",
              ("def shape_key" in old_fig, "def stored_shape" in old_fig, "def predicted_keys" in old_fig),
              (True, False, False))
        check(f"[7] {BASE}: GC by mode", ("roots.mode" in old_gc, "predicted_texture_signatures" in old_gc),
              (True, True))
        now_gc = (ROOT / "app/core/artefact_graph.py").read_text()
        check("[7] now: no mode in the GC", ("roots.mode" in now_gc, "predicted_texture_signatures" in now_gc),
              (False, False))
        server = (ROOT / "app/server.py").read_text()
        order = [server.find(s) for s in ("migrate_modes_once()", "rekey_bodies_once()", "start_sweep()",
                                          "start_resumer()")]
        check("[7] boot order", (all(i > 0 for i in order), order == sorted(order)), (True, True))

    print()
    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
