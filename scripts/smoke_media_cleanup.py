#!/usr/bin/env python3
"""Smoke run: delete paths take their media with them, and nothing a delete
removed comes back as a ghost directory.

Runs against a THROWAWAY storage directory — no server, no backend, no
Blender, no GPU. Every expected number below is derived by hand from the
rules in ``app/core/media_cleanup.py`` and the delete paths, never recorded
from a run:

  [A] location. Two places, each with ``world_gallery/<id>/{a.png,
      gallery_meta.json}`` and ``locations/<id>/model3d/building_100.glb``.
      ``delete_location(aa11bb22)`` → True; both of ITS dirs are gone, the
      other place keeps 2 + 1 files. A second delete → False (no row).
      ``remove_owned_dir`` refuses ``../x``, ``""`` and ``a/b`` (False) and
      the decoy ``STORAGE/x`` survives.
  [B] events. A danger event with its four files (``<id>.png``,
      ``<id>.json``, ``<id>_resolved.png``, ``<id>_resolved.json``) plus a
      foreign ``evt_other.png``: ``delete_event`` → 4 removed, 1 left. A
      second event (TTL 1 game hour) with its four files, clock +2 h,
      ``expire_events()`` → 1 and its 4 files gone. ``remove_event_images
      ("../evil")`` → 0.
  [C] Instagram. Post p1 with carousel p1/p2/p3 (+ one .json each, + p2.mp4
      = 7 files) and post q (q.png + q.json). ``delete_post(p1)`` → True,
      7 files gone, q's 2 remain, 1 post left. Post r whose carousel reuses
      q.png: deleting r removes r.png + r.json and KEEPS q.png (still named by
      q). A row without a payload id is deletable under its row id.
  [D] model gallery. ``model_100.glb/.json`` + ``raw/model_100.glb`` and the
      same for 200. Deleting model_100 removes ``raw/model_100.glb`` and keeps
      ``raw/model_200.glb``; deleting the rest leaves no file and no ``raw/``.
      A selection write into a directory that is gone does not recreate it.
  [E] outfit cache GC (inventory stubbed: shirt + jeans owned).
      A = model3d/A.glb + A.json (manifest names a removed piece) + low/A.glb
      + raw/A.glb; B = low/B.glb only; C = model3d/C.glb without a sidecar,
      its manifest only in model_refs/tpose_C.json (shirt → re-signs to C);
      A-s12345678 = a state variant with a sidecar (its own manifest names
      shirt, which re-signs to C, not A → stale). ``reachable_signatures``
      raises if called — every mesh entry is judged by a manifest or by its
      missing top-level model. meshes: total 4, valid 1 (C), stale 3.
      ``purge_stale([A, B, C])`` → 5 files (A: 4, B: 1), skipped 1 (C), and
      neither C nor the state variant of A is touched.
  [F] items. A fresh item has no directory, and looking up its image does not
      create one. 1.png set; ``replace_item_image(2.png)`` removes 1.png;
      ``replace_item_image(3.png)`` removes 2.png (read fresh, not from the
      caller's stale idea that 1.png is current) → only 3.png; replacing with
      the same name removes nothing. ``delete_item`` → True, the dir is gone.
  [G] no ghost dir. After ``delete_character``, every read and late writer
      below leaves ``characters/<name>`` absent, and the mesh store answers
      the "target directory is gone" error.
  [H] thumbnails. One thumbnail per location gallery image (2), one for the
      item image and one for a character image: each delete drops exactly
      its own cache file.

Usage:  ./.venv/bin/python scripts/smoke_media_cleanup.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="media-cleanup-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="media-cleanup-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import media_cleanup, thumbnails  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def png_bytes(color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def thumb_count() -> int:
    d = STORAGE / ".cache" / "thumbs"
    return len([f for f in d.iterdir() if f.is_file()]) if d.is_dir() else 0


def thumb_of(path: Path) -> None:
    thumbnails.get_thumbnail(path.resolve(), thumbnails.THUMB_WIDTHS[0])


def files_under(d: Path) -> int:
    return len([f for f in d.rglob("*") if f.is_file()]) if d.exists() else 0


def section_a_h_locations() -> None:
    print("\n[A] location delete takes gallery + models   [H] + thumbnails")
    from app.models.world import delete_location, upsert_location
    for lid, name in (("aa11bb22", "Alpha"), ("cc33dd44", "Gamma")):
        upsert_location({"id": lid, "name": name, "description": "", "rooms": []})
        g = STORAGE / "world_gallery" / lid
        g.mkdir(parents=True)
        (g / "a.png").write_bytes(png_bytes())
        (g / "gallery_meta.json").write_text(json.dumps({"a.png": {}}))
        m = STORAGE / "locations" / lid / "model3d"
        m.mkdir(parents=True)
        (m / "building_100.glb").write_bytes(b"glb")
        thumb_of(g / "a.png")
    check("H: two gallery thumbnails cached", thumb_count(), 2)
    check("A: delete_location(aa11bb22)", delete_location("aa11bb22"), True)
    check("A: its gallery dir is gone",
          (STORAGE / "world_gallery" / "aa11bb22").exists(), False)
    check("A: its model dir is gone",
          (STORAGE / "locations" / "aa11bb22").exists(), False)
    check("A: the other gallery keeps 2 files",
          files_under(STORAGE / "world_gallery" / "cc33dd44"), 2)
    check("A: the other model dir keeps 1 file",
          files_under(STORAGE / "locations" / "cc33dd44"), 1)
    check("H: one thumbnail left (the other place's)", thumb_count(), 1)
    token = thumbnails._source_token(
        (STORAGE / "world_gallery" / "cc33dd44" / "a.png").resolve())
    left = [f.name for f in (STORAGE / ".cache" / "thumbs").iterdir()]
    check("H: ...and it belongs to cc33dd44",
          all(n.startswith(token + "_") for n in left), True)
    check("A: a second delete finds nothing", delete_location("aa11bb22"), False)
    decoy = STORAGE / "x"
    decoy.mkdir()
    root = STORAGE / "world_gallery"
    check("A: '../x' refused", media_cleanup.remove_owned_dir(root, "../x"), False)
    check("A: '' refused", media_cleanup.remove_owned_dir(root, ""), False)
    check("A: 'a/b' refused", media_cleanup.remove_owned_dir(root, "a/b"), False)
    check("A: the decoy survives", decoy.is_dir(), True)


def section_b_events() -> None:
    print("\n[B] event images go with the row")
    from app.core.event_images import remove_event_images
    from app.core.game_time import GameDuration
    from app.core.timeutils import game_time, set_game_time
    from app.models.events import add_event, delete_event, expire_events
    ev_dir = STORAGE / "events"
    ev_dir.mkdir(exist_ok=True)

    def four(eid):
        for name in (f"{eid}.png", f"{eid}.json", f"{eid}_resolved.png",
                     f"{eid}_resolved.json"):
            (ev_dir / name).write_bytes(b"x")

    e1 = add_event("a fire", category="danger")["id"]
    four(e1)
    (ev_dir / "evt_other.png").write_bytes(b"x")
    check("delete_event", delete_event(e1), True)
    check("its 4 files gone, the foreign one left",
          sorted(f.name for f in ev_dir.iterdir()), ["evt_other.png"])
    e2 = add_event("a storm", category="danger", ttl_hours=1)["id"]
    four(e2)
    set_game_time(game_time() + GameDuration.of(hours=2))
    check("expire_events removes 1", expire_events(), 1)
    check("its 4 files gone too",
          sorted(f.name for f in ev_dir.iterdir()), ["evt_other.png"])
    check("an unsafe id removes nothing", remove_event_images("../evil"), 0)


def section_c_instagram() -> None:
    print("\n[C] Instagram post delete takes every carousel file")
    from app.core.db import transaction
    from app.models.instagram import (add_post_image, create_post, delete_post,
                                      get_instagram_dir, load_feed)
    ig = get_instagram_dir()
    p1 = create_post("demo", "p1.png", "one")["id"]
    add_post_image(p1, "p2.png")
    add_post_image(p1, "p3.png")
    for n in ("p1", "p2", "p3"):
        (ig / f"{n}.png").write_bytes(b"x")
        (ig / f"{n}.json").write_text("{}")
    (ig / "p2.mp4").write_bytes(b"x")
    q = create_post("demo", "q.png", "two")["id"]
    (ig / "q.png").write_bytes(b"x")
    (ig / "q.json").write_text("{}")
    before = len([f for f in ig.iterdir() if f.suffix != ".json" or f.stem != "feed"])
    check("delete_post(p1)", delete_post(p1), True)
    after = len([f for f in ig.iterdir() if f.suffix != ".json" or f.stem != "feed"])
    check("7 files removed", before - after, 7)
    check("q's 2 files remain",
          sorted(f.name for f in ig.iterdir() if f.stem == "q"),
          ["q.json", "q.png"])
    check("1 post left", len(load_feed()), 1)
    r = create_post("demo", "r.png", "three")["id"]
    add_post_image(r, "q.png")
    (ig / "r.png").write_bytes(b"x")
    (ig / "r.json").write_text("{}")
    check("delete_post(r)", delete_post(r), True)
    check("r's own files gone", (ig / "r.png").exists() or (ig / "r.json").exists(),
          False)
    check("q.png kept (post q still names it)", (ig / "q.png").exists(), True)
    with transaction() as conn:
        rowid = conn.execute(
            "INSERT INTO events (ts, kind, character_name, payload) "
            "VALUES ('2026', 'instagram_post', 'demo', ?)",
            (json.dumps({"image_filename": "nid.png"}),)).lastrowid
    check("an id-less row is deletable under its row id",
          delete_post(str(rowid)), True)
    check("a missing post → False", delete_post("post_missing"), False)


def section_d_model_gallery() -> None:
    print("\n[D] model gallery delete takes the raw/ backup")
    from app.core.model_store import ModelGallery
    d = STORAGE / "gallery_d"
    (d / "raw").mkdir(parents=True)
    for ts in (100, 200):
        (d / f"model_{ts}.glb").write_bytes(b"glb")
        (d / f"model_{ts}.json").write_text("{}")
        (d / "raw" / f"model_{ts}.glb").write_bytes(b"raw")
    g = ModelGallery(d, "model")
    check("delete(model_100.glb)", g.delete("model_100.glb"), True)
    check("raw/model_100.glb gone", (d / "raw" / "model_100.glb").exists(), False)
    check("raw/model_200.glb kept", (d / "raw" / "model_200.glb").exists(), True)
    check("delete() the rest", ModelGallery(d, "model").delete(), True)
    check("no file left", files_under(d), 0)
    check("raw/ removed once empty", (d / "raw").exists(), False)
    gone = STORAGE / "gallery_gone"
    ModelGallery(gone, "model").select("")
    check("a selection write does not recreate a deleted dir", gone.exists(), False)


def section_e_cache_gc() -> None:
    print("\n[E] outfit cache GC sees low/ and raw/, purges through the purger")
    import app.core.model_refs as mr
    import app.models.inventory as inv
    from app.core import outfit_cache_gc as gc
    from app.models.character import get_character_dir
    name = "demo_gc"
    inv.get_character_inventory = lambda n, include_equipped=True: {"inventory": [
        {"item_id": "shirt", "item_category": "outfit_piece",
         "outfit_piece": {"slots": ["top"]}},
        {"item_id": "jeans", "item_category": "outfit_piece",
         "outfit_piece": {"slots": ["bottom"]}}]}
    mr.current_outfit_state = lambda n: ({}, [], "")
    gc._worn_signature = lambda n: ""

    def boom(_n):
        raise AssertionError("reachable set enumerated")
    gc.reachable_signatures = boom

    base = get_character_dir(name)
    m3 = base / "model3d"
    refs = base / "model_refs"
    for d in (m3 / "low", m3 / "raw", refs):
        d.mkdir(parents=True)
    a, b = "aaaaaaaaaaaa", "bbbbbbbbbbbb"
    c = gc._sign({"top": "shirt"}, [], name)
    (m3 / f"{a}.glb").write_bytes(b"g")
    (m3 / f"{a}.json").write_text(json.dumps({"pieces": {"top": "gone_hat"},
                                              "items": []}))
    (m3 / "low" / f"{a}.glb").write_bytes(b"g")
    (m3 / "raw" / f"{a}.glb").write_bytes(b"g")
    (m3 / "low" / f"{b}.glb").write_bytes(b"g")
    (m3 / f"{c}.glb").write_bytes(b"g")
    (refs / f"tpose_{c}.json").write_text(json.dumps(
        {"equipped_pieces": {"top": "shirt"}, "equipped_items": []}))
    av = f"{a}-s12345678"
    (m3 / f"{av}.glb").write_bytes(b"g")
    (m3 / f"{av}.json").write_text(json.dumps({"pieces": {"top": "shirt"},
                                               "items": []}))
    try:
        rep = gc.verify_cache(name)
        meshes = {k: rep["meshes"][k] for k in ("total", "valid", "stale")}
        check("meshes counted with low/raw groups", meshes,
              {"total": 4, "valid": 1, "stale": 3})
        check("stale = A, B, A's state variant",
              sorted(rep["stale_signatures"]), sorted([a, b, av]))
        res = gc.purge_stale(name, [a, b, c])
        check("5 files deleted (A: 4, B: 1)", res["deleted_files"], 5)
        check("C skipped (valid)", res["skipped"], 1)
        check("C untouched", (m3 / f"{c}.glb").exists(), True)
        check("A's state variant untouched (glob boundary)",
              (m3 / f"{av}.glb").exists(), True)
        check("no file of A or B left",
              sorted(p.name for p in m3.rglob("*") if p.is_file()
                     and p.stem in (a, b)), [])
    except AssertionError as e:
        check("the reachable set was never needed", str(e), "")


def section_f_h_items() -> None:
    print("\n[F] item images: no dir on read, replace reads fresh   [H] thumbs")
    from app.models.inventory import (add_item, delete_item, get_item_image_path,
                                      replace_item_image, set_item_image)
    iid = add_item("Lamp", item_id="item_x")["id"]
    check("the minted id", iid, "item_x")
    d = STORAGE / "items" / iid
    check("image lookup → ''", get_item_image_path(iid), "")
    check("...and no directory appeared", d.exists(), False)
    d.mkdir(parents=True)
    (d / "1.png").write_bytes(png_bytes())
    set_item_image(iid, "1.png")
    thumb_of(d / "1.png")
    t0 = thumb_count()
    (d / "2.png").write_bytes(png_bytes((0, 0, 200)))
    check("replace with 2.png", replace_item_image(iid, "2.png"), True)
    check("1.png gone", (d / "1.png").exists(), False)
    check("H: its thumbnail dropped", thumb_count(), t0 - 1)
    (d / "3.png").write_bytes(png_bytes((0, 200, 0)))
    # A caller whose snapshot still says 1.png: the record says 2.png.
    check("replace with 3.png", replace_item_image(iid, "3.png"), True)
    check("only 3.png left", sorted(f.name for f in d.iterdir()), ["3.png"])
    check("same name again", replace_item_image(iid, "3.png"), True)
    check("3.png kept", (d / "3.png").exists(), True)
    thumb_of(d / "3.png")
    t1 = thumb_count()
    check("delete_item", delete_item(iid), True)
    check("item dir gone", d.exists(), False)
    check("H: its thumbnail dropped", thumb_count(), t1 - 1)


def section_g_h_ghost_dirs() -> None:
    print("\n[G] a deleted character stays deleted   [H] its thumbnails go")
    from app.core import model3d
    from app.core.expression_regen import (clear_expression_cache,
                                           find_nearest_expression,
                                           peek_cached_expression)
    from app.core.model_refs import get_model_refs_dir
    from app.imagegen import service as svc
    from app.models.character import (delete_character, get_character_dir,
                                      save_character_profile,
                                      save_outfit_image_meta)
    name = "demo"
    save_character_profile(name, {"character_name": name}, create_new=True)
    base = get_character_dir(name)
    (base / "images").mkdir(parents=True, exist_ok=True)
    (base / "images" / "p.png").write_bytes(png_bytes())
    thumb_of(base / "images" / "p.png")
    t0 = thumb_count()
    check("delete_character", delete_character(name), True)
    check("H: its thumbnail dropped", thumb_count(), t0 - 1)
    get_model_refs_dir(name)
    model3d.get_model3d_dir(name)
    peek_cached_expression(name, "happy", "standing")
    find_nearest_expression(name, "happy")
    check("clear_expression_cache → 0", clear_expression_cache(name), 0)
    save_outfit_image_meta(name, "x.png", {"a": 1})
    real_find = model3d.find_model3d
    model3d.find_model3d = lambda n, s=None: STORAGE / "fake.glb"
    try:
        check("build_lod → no_model",
              model3d.build_lod(name, "aaaaaaaaaaaa", ratio=0.5).get("error"),
              "no_model")
    finally:
        model3d.find_model3d = real_find
    res = svc.ImageService._store_mesh_files(
        [{"blob": b"glTF", "name": "mesh_00001_.glb", "mime": "model/gltf-binary",
          "kind": "model"}], "none", str(base / "model3d" / "sig.glb"), "test")
    check("mesh store answers 'gone'", res.get("error"), svc._TARGET_GONE)
    check("characters/<name> still absent", base.exists(), False)


def main() -> int:
    for section in (section_a_h_locations, section_b_events, section_c_instagram,
                    section_d_model_gallery, section_e_cache_gc,
                    section_f_h_items, section_g_h_ghost_dirs):
        try:
            section()
        except Exception as e:  # a crash is a failure, and the rest still runs
            import traceback
            traceback.print_exc()
            check(f"{section.__name__} ran", repr(e), "no exception")
    print(f"\n{CHECKED} checks, {len(FAILURES)} failure(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(os.environ["ANIMATION_CLIPS_DIR"], ignore_errors=True)
