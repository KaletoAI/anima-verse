#!/usr/bin/env python3
"""Outfit-cache GC and base-body entries (app/core/outfit_cache_gc.py).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_gc.py

Runs against a THROWAWAY world with a copy of the repo's ``human`` package and
FAKE cache files — no renderer, no GPU, no server. Expected values by hand:

Fixtures: ``Demo`` (human-default, profile image, empty inventory) and
``DemoFox`` (animal-default). CUR = base_signature(Demo); OLD = "base0123abcd"
(a base signature of the same shape that is not the current one).

Demo's files:
  model_refs: tpose_CUR.png/.json, tpose_back_CUR.png/.json   (current base)
              tpose_OLD.png/.json, tpose_left_OLD.png          (older base)
              tpose_OUT.png/.json with manifest {} / []        (outfit entry;
                OUT = gc._sign({}, [], "Demo") re-signs -> valid)
              tpose_deadbeef1234.png/.json, no manifest        (outfit entry;
                empty inventory -> reachable set {} -> stale)
  model3d:    CUR.glb/.json + unrigged/CUR.glb                 (current base model)
              OLD.glb/.json + unrigged/OLD.glb + low/OLD.glb   (older base model)

[1] verify_cache(Demo): stale signatures exactly {OLD, deadbeef1234}
    (the outfit rule is unchanged: OUT valid, deadbeef1234 stale); refs groups
    CUR, OLD, OUT, deadbeef1234 = 4 total, 2 stale; mesh groups CUR, OLD = 2
    total, 1 stale; the report's "protected" stays the worn outfit only —
    Demo wears nothing, so that is OUT (the empty wardrobe signs to
    md5("")[:12] = "d41d8cd98f00"), never CUR.
[2] purge_stale(Demo, [OLD, CUR, OUT]): CUR and OUT are not stale -> skipped
    2; OLD's files go: 3 refs (tpose_OLD.png, tpose_OLD.json,
    tpose_left_OLD.png) + 4 mesh files (OLD.glb, OLD.json, unrigged/OLD.glb,
    low/OLD.glb) = 7 deleted. Every CUR and OUT file still exists.
[3] model3d/CUR.glb is removed (only the unrigged checkpoint and the sidecar
    remain, as during a base model run): CUR is STILL valid — the outfit rule
    "no top model = stale" does not apply to the current base.
[4] DemoFox (non-humanoid) has no base body: its tpose_OLD.png/.json is stale.
[5] base_signature unavailable (raises): no base entry is judged — Demo's
    re-created OLD entry is not stale (never delete on a guess).
"""
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
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def touch(path: Path, data: bytes = b"x" * 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-gc-") as tmp:
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

        from app.core import base_body
        from app.core import outfit_cache_gc as gc
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)
        for name, template in (("Demo", "human-default"), ("DemoFox", "animal-default")):
            check(f"create {name}", save_character_profile(name, {"template": template, "gender": "female",
                                                                  "age": 30}, create_new=True), True)
            touch(get_character_images_dir(name) / f"{name}_1.png", b"\x89PNG" + b"a" * 50)
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)

        cur = base_body.base_signature("Demo")
        old = "base0123abcd"
        out = gc._sign({}, [], "Demo")
        refs = get_character_dir("Demo") / "model_refs"
        meshes = get_character_dir("Demo") / "model3d"
        meta = json.dumps({"base_signature": cur, "equipped_pieces": {}, "equipped_items": []})
        cur_files = [touch(refs / f"tpose_{cur}.png"), touch(refs / f"tpose_{cur}.json", meta.encode()),
                     touch(refs / f"tpose_back_{cur}.png"), touch(refs / f"tpose_back_{cur}.json", meta.encode()),
                     touch(meshes / f"{cur}.glb"), touch(meshes / f"{cur}.json", b"{}"),
                     touch(meshes / "unrigged" / f"{cur}.glb")]

        def old_files():
            old_meta = json.dumps({"base_signature": old, "equipped_pieces": {}, "equipped_items": []}).encode()
            return [touch(refs / f"tpose_{old}.png"), touch(refs / f"tpose_{old}.json", old_meta),
                    touch(refs / f"tpose_left_{old}.png"),
                    touch(meshes / f"{old}.glb"), touch(meshes / f"{old}.json", b"{}"),
                    touch(meshes / "unrigged" / f"{old}.glb"), touch(meshes / "low" / f"{old}.glb")]

        olds = old_files()
        out_files = [touch(refs / f"tpose_{out}.png"),
                     touch(refs / f"tpose_{out}.json",
                           json.dumps({"equipped_pieces": {}, "equipped_items": []}).encode())]
        touch(refs / "tpose_deadbeef1234.png")
        touch(refs / "tpose_deadbeef1234.json", b'{"prompt": ""}')

        print("[1] verify")
        rep = gc.verify_cache("Demo")
        check("stale", sorted(rep["stale_signatures"]), sorted([old, "deadbeef1234"]))
        check("refs", (rep["refs"]["total"], rep["refs"]["stale"]), (4, 2))
        check("meshes", (rep["meshes"]["total"], rep["meshes"]["stale"]), (2, 1))
        check("protected unchanged", rep["protected"], [out])
        check("OUT is md5('')[:12]", out, "d41d8cd98f00")

        print("[2] purge")
        res = gc.purge_stale("Demo", [old, cur, out])
        check("deleted", res["deleted_files"], 7)
        check("skipped", res["skipped"], 2)
        check("old gone", [p.exists() for p in olds], [False] * 7)
        check("current kept", [p.exists() for p in cur_files], [True] * 7)
        check("outfit kept", [p.exists() for p in out_files], [True] * 2)

        print("[3] current base without its top model")
        (meshes / f"{cur}.glb").unlink()
        check("checkpoint-only current base valid", cur in gc.verify_cache("Demo")["stale_signatures"], False)

        print("[4] non-humanoid")
        fox_refs = get_character_dir("DemoFox") / "model_refs"
        touch(fox_refs / f"tpose_{old}.png")
        touch(fox_refs / f"tpose_{old}.json", b'{"equipped_pieces": {}}')
        check("animal base entry stale", gc.verify_cache("DemoFox")["stale_signatures"], [old])

        print("[5] base signature unavailable")
        olds = old_files()

        def broken(*_a, **_k):
            raise RuntimeError("profile unreadable")

        real = base_body.base_signature
        base_body.base_signature = broken
        try:
            check("no base judged", old in gc.verify_cache("Demo")["stale_signatures"], False)
        finally:
            base_body.base_signature = real

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
