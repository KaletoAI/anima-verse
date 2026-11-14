#!/usr/bin/env python3
"""Deleting a hairstyle with its files (Ruling A59, ``app/core/hairstyle_delete.py``, routes
``GET /characters/{c}/hairstyles/{item}/delete-preview`` and ``DELETE /characters/{c}/hairstyles/{item}``).

Usage:
    ./.venv/bin/python scripts/smoke_hairstyle_delete.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server. Stubs: ``figure_build.request`` and ``garment_assembly.schedule`` are recorders (nothing
is built or assembled); ``figure.stored`` answers a fixed list and ``figure.delete_stored`` is a recorder (the
artefact analysis of a body shape is the Figure tab's own, checked by its smokes); the image service is an empty
namespace; the session lookup of the auth gate reads the role from a header (as in ``smoke_auth_gate.py``).

FIXTURE
  Kai (human, slot hair {length short, color black}). H1 = create_hairstyle(Kai, "short black hair", "hairdeck")
  -> id ``hair_kai`` (``_new_item_id``: "hair_" + slug), his first: worn and the plain body's.
  H2 = create_hairstyle(Kai, "long braided hair", "haar") -> ``hair_kai_2`` (the numeric suffix) — an id that
  STARTS with H1's id plus "_", so a name sweep by prefix alone would take H2's files too. Then H2 is worn and made
  the plain body's (profile ``base_hairstyle`` = H2): H1 is neither worn nor the plain body's.
  An outfit set "Day" {hairstyle H1}, a set "Night" {hairstyle H2}, a set "Gym" {hairstyle ""}.
  Files under characters/Kai/garments/ (S = 12-hex signatures; H1 HairDeck, H2 HAAR, a shirt):
    H1: raw/hair_kai_a00000000001/{record.json, input.png, beard_free.png}          3 files  HairDeck jobs
        hair_kai_b00000000001.{glb,json,strands.json,strands.npz}, low/…glb         5 files  Fits and strand records
        failed/hair_kai_c00000000001.json                                           1 file   Failure records
        attempts/hair_kai_b00000000001.{glb,json,npz}, attempts/prev/…glb           4 files  Refused attempts
        bodies/ob00000001/hair_kai_b00000000001.{glb,json}, bodies/ob00000001/low/…glb  3   Fits on body shapes
    H2: raw/hair_kai_2_d00000000002/{record.json, s1/strands.npy, s1/tile.png}      3 files  HAAR strand jobs
        hair_kai_2_e00000000002.{glb,json,strands.json,strands.npz}, low/…glb       5 files
        bodies/ob00000001/hair_kai_2_e00000000002.glb                               1 file
    shirt: shirt_kai_f00000000003.{glb,json}, layers/shirt_kai_f00000000003_a00000000004.glb   (another garment)
    garments/notes.txt                                                              (no item's name)
  model3d/assembled/sigA.{glb,json} grafting {hair_kai, shirt_kai}; sigB.{glb,json} grafting {hair_kai_2};
  sigC.{glb,json} grafting {shirt_kai}. Body shape sidecars model3d/ob00000001.json (shape_inputs.hair "short black
  hair") and model3d/ob00000002.json (hair "long braided hair"). items/hair_kai/pic.png (the item's media folder).

EXPECTED, BY HAND
[1] Preview of H1: worn False, plain False, last False; files by group in LABELS order — HairDeck jobs 3, Fits and
    strand records 5, Fits on body shapes 3, Refused attempts 4, Failure records 1 (total 16); item_files 1;
    assembled 1 (sigA's sidecar — the low tier has none); shapes [ob00000001] (hair = H1's text; H2's text differs),
    outfit_sets ["Day"]; estimate None (neither worn nor the plain body's: the figure does not change).
[2] Delete H1 (the unworn one): 200; deleted_files 16, assembled 2 (sigA.glb + sigA.json), outfit_sets ["Day"],
    worn False, plain False, shapes_deleted [ob00000001] (``figure.stored`` says deletable), build_requested False
    — no ``figure_build.request``. After: every H1 path gone, the item ``hair_kai`` gone and its media folder
    ``items/hair_kai`` gone; every H2 file, the shirt files, notes.txt, sigB and sigC byte-identical (sha256);
    H2 still worn and the plain body's; set "Day" now hairstyle "", "Night" still H2. A second DELETE of H1 -> 404.
    ``figure.delete_stored`` called once, with ob00000001 (never ob00000002).
[3] Delete H2 (the worn one, the last one): its preview says worn True, plain True, last True, HAAR strand jobs 3,
    Fits and strand records 5, Fits on body shapes 1; 200; deleted_files 9, assembled 2 (sigB); worn True,
    plain True; ``figure_build.request`` called once with (Kai, "outfit_change") — the figure is due — and
    ``garment_assembly.schedule`` with Kai; the profile has no hair slot in ``equipped_mesh_pieces`` and no
    ``base_hairstyle``: ``worn_hair_id`` "", ``hair_mode`` "" (no hair at all); ``hairstyles(Kai)`` []; set "Night"
    hairstyle ""; ob00000002 kept (``figure.stored`` says the figure stands on it: not deletable), named in ``kept``.
    The shirt files, notes.txt and sigC unchanged.
[4] Path traversal: DELETE …/hairstyles/{x} for x in "%2e%2e", "hair..kai", "..%2Fgarments", "%2E%2E%2Fgarments"
    (a bare ".." is folded by the client before it is sent), and the core calls delete_hairstyle(Kai, x) for x in
    "..", "../garments", "hair_kai/../../x" -> 400 or 404 (400 for an id that is no safe item id, 404 when the
    router never reaches the route) and the whole character directory is byte-identical before and after.
[5] Auth: a player session (role user, Kai allowed) -> 403 on DELETE and on the preview GET; anonymous -> 401;
    nothing deleted (the H3 item made for it stays).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def tree_hashes(*dirs: Path) -> dict:
    out = {}
    for d in dirs:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def write(path: Path, data: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data or path.name)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairstyle-delete-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(world_cfg, instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from app.core import figure, figure_build, garment_assembly, garment_hair, hairstyle_delete
        from app.core.keyed_lock import keyed_lock
        from app.core.paths import get_storage_dir
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_dir, get_character_outfits,
                                          get_character_profile, save_character_profile)
        requests, schedules, deleted_shapes = [], [], []
        figure_build.request = lambda name, trigger: requests.append((name, trigger)) or True
        garment_assembly.schedule = lambda name, signature=None: schedules.append(name) or True
        stored = {"ob00000001": True, "ob00000002": False}
        figure.stored = lambda name: [{"kind": "shape", "key": k, "deletable": d, "running": False}
                                      for k, d in stored.items()]
        figure.delete_stored = lambda name, key: deleted_shapes.append(key) or {}
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()

        check("create Kai", save_character_profile("Kai", {
            "template": "human-roleplay", "age": 30, "gender": "male", "height": 180,
            "character_appearance": "athletic", "body_slots": {"hair": {"length": "short", "color": "black"}}},
            create_new=True), True)
        h1 = garment_hair.create_hairstyle("Kai", "short black hair", "hairdeck")
        h2 = garment_hair.create_hairstyle("Kai", "long braided hair", "haar")
        check("ids", (h1, h2), ("hair_kai", "hair_kai_2"))
        check("wear H2", garment_hair.wear_hairstyle("Kai", h2, request=False), True)
        with keyed_lock("character_profile", "Kai"):
            profile = get_character_profile("Kai")
            profile[garment_hair.BASE_HAIRSTYLE_KEY] = h2
            check("H2 the plain body's", save_character_profile("Kai", profile), True)
        for name, hair in (("Day", h1), ("Night", h2), ("Gym", "")):
            add_character_outfit("Kai", {"name": name, "hairstyle": hair})
        inventory.add_item(name="Shirt", category="clothing", item_id="shirt_kai", prompt_fragment="a shirt")
        char = get_character_dir("Kai")
        g = char / "garments"
        h1_paths = [
            write(g / "raw/hair_kai_a00000000001/record.json"), write(g / "raw/hair_kai_a00000000001/input.png"),
            write(g / "raw/hair_kai_a00000000001/beard_free.png"),
            *[write(g / f"hair_kai_b00000000001.{s}") for s in ("glb", "json", "strands.json", "strands.npz")],
            write(g / "low/hair_kai_b00000000001.glb"),
            write(g / "failed/hair_kai_c00000000001.json"),
            *[write(g / f"attempts/hair_kai_b00000000001.{s}") for s in ("glb", "json", "npz")],
            write(g / "attempts/prev/hair_kai_b00000000001.glb"),
            write(g / "bodies/ob00000001/hair_kai_b00000000001.glb"),
            write(g / "bodies/ob00000001/hair_kai_b00000000001.json"),
            write(g / "bodies/ob00000001/low/hair_kai_b00000000001.glb")]
        check("H1 fixture files", len(h1_paths), 16)
        h2_paths = [
            write(g / "raw/hair_kai_2_d00000000002/record.json"),
            write(g / "raw/hair_kai_2_d00000000002/s1/strands.npy"),
            write(g / "raw/hair_kai_2_d00000000002/s1/tile.png"),
            *[write(g / f"hair_kai_2_e00000000002.{s}") for s in ("glb", "json", "strands.json", "strands.npz")],
            write(g / "low/hair_kai_2_e00000000002.glb"),
            write(g / "bodies/ob00000001/hair_kai_2_e00000000002.glb")]
        other_paths = [write(g / "shirt_kai_f00000000003.glb"), write(g / "shirt_kai_f00000000003.json"),
                       write(g / "layers/shirt_kai_f00000000003_a00000000004.glb"), write(g / "notes.txt")]
        asm = char / "model3d" / "assembled"
        for sig, grafted in (("sigA", ["hair_kai", "shirt_kai"]), ("sigB", ["hair_kai_2"]), ("sigC", ["shirt_kai"])):
            write(asm / f"{sig}.glb")
            write(asm / f"{sig}.json", json.dumps({"garments": {i: {"fsig": "x"} for i in grafted}}))
        write(char / "model3d/ob00000001.json", json.dumps({"outfit_body": {
            "body_id": "ob00000001", "shape_inputs": {"hair": "short black hair"}}}))
        write(char / "model3d/ob00000002.json", json.dumps({"outfit_body": {
            "body_id": "ob00000002", "shape_inputs": {"hair": "long braided hair"}}}))
        media = write(get_storage_dir() / "items" / "hair_kai" / "pic.png")

        # The routes through the real router, behind the real gate (session lookup stubbed as in smoke_auth_gate).
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import characters as characters_route
        users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Kai"]},
                 "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}

        def session_user(request: Request):
            return users.get(request.headers.get("x-test-user", ""))
        auth_dependency._get_session_user = session_user
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(characters_route.router)
        client = TestClient(app)
        admin = {"x-test-user": "admin"}

        print("[1] preview of the unworn H1")
        r = client.get(f"/characters/Kai/hairstyles/{h1}/delete-preview", headers=admin)
        check("preview status", r.status_code, 200)
        p = r.json() if r.status_code == 200 else {}
        check("preview flags", (p.get("worn"), p.get("plain"), p.get("last")), (False, False, False))
        check("preview groups", [(f["label"], f["files"]) for f in p.get("files", [])],
              [("HairDeck jobs", 3), ("Fits and strand records", 5), ("Fits on body shapes", 3),
               ("Refused attempts", 4), ("Failure records", 1)])
        check("preview totals", (p.get("total_files"), p.get("item_files"), p.get("assembled")), (16, 1, 1))
        check("preview shapes", [(s["key"], s["deletable"]) for s in p.get("shapes", [])], [("ob00000001", True)])
        check("preview sets / estimate", (p.get("outfit_sets"), p.get("estimate")), (["Day"], None))

        print("[2] delete the unworn H1")
        kept_files = h2_paths + other_paths + [asm / "sigB.glb", asm / "sigB.json", asm / "sigC.glb",
                                               asm / "sigC.json"]
        keep_before = {str(q): hashlib.sha256(q.read_bytes()).hexdigest() for q in kept_files}
        r = client.delete(f"/characters/Kai/hairstyles/{h1}", headers=admin)
        check("delete H1 status", r.status_code, 200)
        d = r.json() if r.status_code == 200 else {}
        check("delete H1 report", (d.get("deleted_files"), d.get("assembled"), d.get("outfit_sets"), d.get("worn"),
                                   d.get("plain"), d.get("shapes_deleted"), d.get("build_requested")),
              (16, 2, ["Day"], False, False, ["ob00000001"], False))
        check("H1 files gone", [str(q.relative_to(g)) for q in h1_paths if q.exists()], [])
        check("H1 folders gone", (g / "raw/hair_kai_a00000000001").exists(), False)
        check("H1 item + media gone", (inventory.get_item(h1), media.parent.exists()), (None, False))
        check("sigA gone, sigB/sigC kept", [(asm / f"{s}.glb").exists() for s in ("sigA", "sigB", "sigC")],
              [False, True, True])
        keep_after = {str(q): hashlib.sha256(q.read_bytes()).hexdigest() for q in kept_files if q.exists()}
        check("H2 + shirt + notes + sigB/sigC byte-identical", keep_after == keep_before, True)
        check("H2 still worn + plain", (garment_hair.worn_hair_id("Kai"),
                                        get_character_profile("Kai").get(garment_hair.BASE_HAIRSTYLE_KEY)), (h2, h2))
        check("sets", {o["name"]: o.get("hairstyle") for o in get_character_outfits("Kai")},
              {"Day": "", "Night": h2, "Gym": ""})
        check("no Build request", requests, [])
        check("shape delete via the Figure tab's Delete", deleted_shapes, ["ob00000001"])
        check("second delete 404", client.delete(f"/characters/Kai/hairstyles/{h1}", headers=admin).status_code, 404)

        print("[3] delete the worn (and last) H2")
        r = client.get(f"/characters/Kai/hairstyles/{h2}/delete-preview", headers=admin)
        p = r.json() if r.status_code == 200 else {}
        check("preview H2", ((p.get("worn"), p.get("plain"), p.get("last")),
                             [(f["label"], f["files"]) for f in p.get("files", [])]),
              ((True, True, True), [("HAAR strand jobs", 3), ("Fits and strand records", 5),
                                     ("Fits on body shapes", 1)]))
        schedules.clear()
        r = client.delete(f"/characters/Kai/hairstyles/{h2}", headers=admin)
        check("delete H2 status", r.status_code, 200)
        d = r.json() if r.status_code == 200 else {}
        check("delete H2 report", (d.get("deleted_files"), d.get("assembled"), d.get("worn"), d.get("plain"),
                                   d.get("shapes_deleted")), (9, 2, True, True, []))
        check("ob00000002 kept and named", any(k.startswith("ob00000002") for k in d.get("kept", [])), True)
        check("H2 files gone", [str(q.relative_to(g)) for q in h2_paths if q.exists()], [])
        check("figure due: Build requested", requests, [("Kai", "outfit_change")])
        check("assembly scheduled", schedules, ["Kai"])
        prof = get_character_profile("Kai")
        check("no hair worn, no plain hairstyle",
              ("hair" in (prof.get("equipped_mesh_pieces") or {}), garment_hair.BASE_HAIRSTYLE_KEY in prof,
               garment_hair.worn_hair_id("Kai"), garment_hair.hair_mode("Kai"), garment_hair.hairstyles("Kai")),
              (False, False, "", "", []))
        check("set Night cleared", {o["name"]: o.get("hairstyle") for o in get_character_outfits("Kai")},
              {"Day": "", "Night": "", "Gym": ""})
        check("shirt + notes + sigC still there", [q.exists() for q in other_paths + [asm / "sigC.glb"]],
              [True] * 5)
        check("shapes deleted overall", deleted_shapes, ["ob00000001"])

        print("[4] path traversal")
        h3 = garment_hair.create_hairstyle("Kai", "a bun", "hairdeck")
        write(g / f"raw/{h3}_a00000000005/record.json")
        before = tree_hashes(char, get_storage_dir() / "items")
        # A bare ".." is not sent: the HTTP client (like a browser) folds the dot segment before sending, so the
        # request would be DELETE /characters/Kai — another route. The encoded forms reach the router as they are.
        for bad in ("%2e%2e", "hair..kai", "..%2Fgarments", "%2E%2E%2Fgarments"):
            code = client.delete(f"/characters/Kai/hairstyles/{bad}", headers=admin).status_code
            check(f"DELETE {bad!r}", code in (400, 404), True)
        for bad in ("..", "../garments", "hair_kai/../../x"):
            try:
                hairstyle_delete.delete_hairstyle("Kai", bad)
                check(f"core {bad!r}", "no error", "ValueError")
            except ValueError:
                check(f"core {bad!r}", "ValueError", "ValueError")
        check("nothing deleted by the bad ids", tree_hashes(char, get_storage_dir() / "items") == before, True)

        print("[5] auth")
        for method, path in (("DELETE", f"/characters/Kai/hairstyles/{h3}"),
                             ("GET", f"/characters/Kai/hairstyles/{h3}/delete-preview")):
            check(f"player {method}", client.request(method, path, headers={"x-test-user": "user"}).status_code, 403)
            check(f"anon {method}", client.request(method, path).status_code, 401)
        check("H3 still there", (garment_hair.is_hairstyle(inventory.get_item(h3), "Kai"),
                                 (g / f"raw/{h3}_a00000000005/record.json").exists()), (True, True))
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
