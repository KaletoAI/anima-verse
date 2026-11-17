#!/usr/bin/env python3
"""Two concurrent callers of ``garment_hair.ensure_hairstyle`` mint ONE first hairstyle (review unit 07 #3): the
check (worn? owned?) and the create run under ``keyed_lock("garment_item", name)``, the lock every hairstyle mint
holds.

Usage:
    ./.venv/bin/python scripts/smoke_hairstyle_ensure_race.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) with a copy of
the repo's ``human`` package — no real world, no hub, no server. ``garment_assembly.schedule`` is a recorder.

The race window is widened on purpose: ``garment_hair.appearance_hair_text`` (read after the owned check and
before the create) sleeps 0.3 s per call, and two threads start together.

EXPECTED, BY HAND
Kai (human-roleplay, hair short/black — hair text "short black hair") owns no hairstyle.
[1] Two threads ensure_hairstyle("Kai") at once: the second waits for the lock, then finds the first one's
    hairstyle worn -> Kai owns exactly ONE hairstyle and both threads return its id.
[2] The OLD body of ``ensure_hairstyle`` (commit 3f2ce338, before the fix — copied below as ``old_ensure``: the same
    statements without the lock) on Lea (hair long/red, no hairstyle), same timing: both threads pass the owned
    check before either creates -> Lea owns TWO hairstyles — the finding.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def race(fn, name):
    results, errors = [], []
    start = threading.Barrier(2)

    def run():
        start.wait()
        try:
            results.append(fn(name))
        except Exception as e:  # noqa: BLE001 — reported below
            errors.append(f"{type(e).__name__}: {e}")
    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results, errors


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairstyle-ensure-race-") as tmp:
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
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)
        from app.core import garment_assembly, garment_hair
        from app.models.character import get_character_profile, save_character_profile
        garment_assembly.schedule = lambda *a, **k: True

        for name, colour, length in (("Kai", "black", "short"), ("Lea", "red", "long")):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "age": 30, "gender": "female", "height": 168,
                "character_appearance": "slender", "body_slots": {"hair": {"length": length, "color": colour}}},
                create_new=True), True)

        real_text = garment_hair.appearance_hair_text

        def slow_text(*a, **kw):
            time.sleep(0.3)
            return real_text(*a, **kw)
        garment_hair.appearance_hair_text = slow_text

        print("[1] ensure_hairstyle under the lock")
        results, errors = race(garment_hair.ensure_hairstyle, "Kai")
        owned = [i["id"] for i in garment_hair.hairstyles("Kai")]
        check("no error", errors, [])
        check("Kai owns ONE hairstyle", len(owned), 1)
        check("both callers got it", sorted(results), sorted(owned * 2))

        print("[2] the old body (3f2ce338), no lock")

        def old_ensure(character_name):
            # ensure_hairstyle of commit 3f2ce338, verbatim apart from the module prefix.
            profile = get_character_profile(character_name) or {}
            worn = garment_hair.worn_hair_id(character_name, profile)
            if worn:
                return worn
            if garment_hair.hairstyles(character_name):
                return ""
            if not garment_hair.appearance_hair_text(character_name, profile=profile):
                return ""
            return garment_hair.create_hairstyle(character_name, "", "")

        results, errors = race(old_ensure, "Lea")
        check("old: no error", errors, [])
        check("old: Lea owns TWO hairstyles (the finding)", len(garment_hair.hairstyles("Lea")), 2)
        garment_hair.appearance_hair_text = real_text

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
