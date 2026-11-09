#!/usr/bin/env python3
"""The base-body signature is the same with and without plugin discovery.

Usage:
    ./.venv/bin/python scripts/smoke_base_signature_bare_process.py

Runs against a THROWAWAY storage directory (world config
``packages.enabled = "human"``, the repo's SFW ``human`` package, which has no
``on_load``) — no real world, no private pack, no server.

Bug (E2E 2026-11-09): a script that opened a world without the server's
``discover_packages()`` saw an empty package registry — no species body
slots, no character-template fragments — so ``base_body.base_signature``
hashed a shorter character block and negative than the server did (Kira on
the S1 clone: ``basecac947a2`` in-process, ``base20d5701a`` on the server).
The fix (``app.plugins.loader.declared_packages``): before any discovery,
the pure-data readers (body slots, template fragments) read the world's
enabled packages from their manifests, without importing package code.

Fixture ``Demo`` (template human-default): gender female, age 30, height 168,
body slots skin.tone olive, eyes.color green, build.type athletic, hair long
brunette. Each case runs in its OWN Python process:

[1] bare process (paths + config loaded, NO discovery): the human package
    applies to human-default; its slots that apply to a female are, in
    manifest order, hair, eyes, skin, build (facial_hair is male only).
    base_appearance = "female, 30 years old" + the flagged ``always``
    fragments eyes "green eyes", skin "olive skin", build "{height}, {type}
    build" with 168 cm female -> "average height, athletic build" (hair is
    not flagged):
        "female, 30 years old, green eyes, olive skin, average height, athletic build"
    The registry stays empty and no discovery is recorded (no side effect).
[2] initialised process (the same + ``discover_packages()``): the same slot
    list and appearance; the registry holds exactly ["human"].
[3] base_signature of [1] == that of [2], both "base" + 8 hex.
[4] A config without ``packages.enabled`` (an unloaded config) sees no
    species package in a bare process: slots [] — the view never invents
    activation the world does not declare.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []

APPEARANCE = "female, 30 years old, green eyes, olive skin, average height, athletic build"
SLOTS = ["hair", "eyes", "skin", "build"]


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def child(mode: str, root: Path) -> None:
    """One measurement in this (fresh) process; prints a JSON line."""
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    from app.core import config
    if mode == "unloaded":
        config.load(root / "empty" / "config.json", instance_path=root / "instance" / "config.json")
    else:
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
    from app.plugins import loader, registry
    if mode == "initialised":
        loader.discover_packages()
    from app.core import base_body
    from app.core.body_slots import slots_for_character
    print(json.dumps({
        "signature": base_body.base_signature("Demo"),
        "slots": [spec.id for spec in slots_for_character("Demo")],
        "appearance": base_body.base_appearance("Demo"),
        "registry": [pkg.id for pkg in registry.packages()],
        "discovered": loader.is_discovered(),
    }))


def run_child(mode: str, root: Path) -> dict:
    out = subprocess.run([sys.executable, __file__, "--child", mode, str(root)], cwd=ROOT,
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        print(out.stderr[-3000:])
        raise SystemExit(f"child {mode} failed")
    return json.loads(out.stdout.strip().splitlines()[-1])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bsig-bare-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        from app.models.character import save_character_profile
        profile = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                   "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                  "build": {"type": "athletic"},
                                  "hair": {"length": "long", "color": "brunette"}}}
        check("create", save_character_profile("Demo", profile, create_new=True), True)

        print("[1] bare process")
        bare = run_child("bare", root)
        check("slots", bare["slots"], SLOTS)
        check("appearance", bare["appearance"], APPEARANCE)
        check("registry untouched", (bare["registry"], bare["discovered"]), ([], False))

        print("[2] initialised process")
        init = run_child("initialised", root)
        check("slots", init["slots"], SLOTS)
        check("appearance", init["appearance"], APPEARANCE)
        check("registry", (init["registry"], init["discovered"]), (["human"], True))

        print("[3] same signature")
        check("shape", bool(re.fullmatch(r"base[0-9a-f]{8}", bare["signature"] or "")), True)
        check("bare == initialised", bare["signature"], init["signature"])

        print("[4] no packages.enabled")
        unloaded = run_child("unloaded", root)
        check("no species slots", unloaded["slots"], [])

    print()
    print(f"FAILED ({len(FAILS)}): {', '.join(FAILS)}" if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], Path(sys.argv[3]))
        sys.exit(0)
    sys.exit(main())
