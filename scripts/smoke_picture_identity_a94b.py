#!/usr/bin/env python3
"""Ruling A94b: (1) ``stored_base_haired`` reads the bald head where it stands since the prompt review of
2026-11-11 — the front's ``final_prompt`` (the character block) — with ``prompt`` for older sidecars; (2) was
the outfit front made from its own reference picture — removed by Ruling A125.

Usage:
    ./.venv/bin/python scripts/smoke_picture_identity_a94b.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process, no render. ``socket.socket.connect`` and ``requests.Session.request`` are replaced by
counters that refuse: the run must end with 0 outbound attempts.

Fixtures (as smoke_picture_identity_a94; template human-roleplay, profile image <name>_1.png):
  ``Beard``      male, hair slot {short, auburn}, appearance "…, a full auburn beard", hairstyle from the Appearance
                 in mode "body" (hair text "short auburn hair").
  ``Deck``       female, hair slot {long, black}, hairstyle mode "hairdeck" (bald plain body), no facial hair.
  ``Rewritten``  male, no facial hair, hairstyle "a shaved undercut" in mode "body" (not the Appearance's hair).

Hand-derived (BALD = "completely bald with a smooth bare scalp"):

[1] stored_base_haired(Deck, bsig) with a front file tpose_<bsig>.png and the sidecar
      {final_prompt: "change … to " + BALD + ", the same face …", prompt: <A-pose text, no bald words>}  -> False
        (the old code read ``prompt`` alone: True — every stored bald front read as haired);
      {final_prompt: "change … to short auburn hair, …", prompt: <A-pose + hair clause>}               -> True;
      {final_prompt: "change … to the same face, hair and facial hair as the person …", prompt: …}      -> True;
      an older sidecar without final_prompt, prompt "…, completely bald, smooth clean-shaven head, …"   -> False;
      the same without the bald words                                                                  -> True;
      no front file                                                                                     -> None.
[2] (Removed by Ruling A125: an outfit's dressed front is no longer made from its reference picture —
    ``outfit_edit_prompt`` is gone; the edit of the base view is ``smoke_dressed_edit_a125.py``.)
[3] Fails on the old code (commit OLD = 7df28407f, Ruling A94, before A94b — never HEAD): its
    stored_base_haired reads the first [1] sidecar as True.
[4] Outbound attempts: 0.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The commit before Ruling A94b — never HEAD.
OLD = "7df28407f"
FAILS = []
OUTBOUND = []

BALD = "completely bald with a smooth bare scalp"
ORB = "wearing exactly the clothing of the person in the picture and nothing else"
PREFIX = "change the view and position of the character in the picture to "


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def block_network():
    import socket
    import requests

    def refuse_connect(self, *a, **kw):
        OUTBOUND.append(("socket", a))
        raise OSError("network blocked in smoke")

    def refuse_request(self, method, url, *a, **kw):
        OUTBOUND.append(("requests", method, url))
        raise OSError("network blocked in smoke")
    socket.socket.connect = refuse_connect
    requests.Session.request = refuse_request


def png(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (180, 120, 90)).save(path)


def old_module():
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/base_body.py"],
                         capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType(f"base_body_{OLD}")
    mod.__file__ = f"base_body_{OLD}.py"
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="picture-identity-b-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                       "base_body": {"skin_detail_step": False}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, garment_hair
        from app.core.model_refs import get_model_refs_dir
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        slots = {"skin": {"tone": "olive"}, "eyes": {"color": "green"}, "build": {"type": "athletic"}}
        fixtures = (
            ("Beard", {"gender": "male", "age": 40, "height": 180,
                       "character_appearance": "{gender}, {age} years old, a full auburn beard",
                       "body_slots": {**slots, "hair": {"length": "short", "color": "auburn"}}}, "", "body"),
            ("Deck", {"gender": "female", "age": 30, "height": 168, "character_appearance": "{gender}, {age} years old",
                      "body_slots": {**slots, "hair": {"length": "long", "color": "black"}}}, "", "hairdeck"),
            ("Rewritten", {"gender": "male", "age": 40, "height": 180,
                           "character_appearance": "{gender}, {age} years old",
                           "body_slots": {**slots, "hair": {"length": "short", "color": "black"}}},
             "a shaved undercut", "body"),
        )
        for name, data, hair, mode in fixtures:
            check(f"create {name}", save_character_profile(name, {"template": "human-roleplay", **data},
                                                           create_new=True), True)
            png(get_character_images_dir(name) / f"{name}_1.png")
            stored = get_character_profile(name)
            stored["profile_image"] = f"{name}_1.png"
            check(f"profile image {name}", save_character_profile(name, stored), True)
            garment_hair.create_hairstyle(name, hair, mode)
        old = old_module()

        print("[1] stored_base_haired reads the final prompt")
        bsig = base_body.base_signature("Deck")
        refs = get_model_refs_dir("Deck")
        sidecar = refs / f"tpose_{bsig}.json"
        check("no front: None", base_body.stored_base_haired("Deck", bsig), None)
        png(refs / f"tpose_{bsig}.png")
        pose = base_body.base_prompt("Deck", "front")[0]
        haired_pose = base_body.base_prompt("Beard", "front")[0]
        cases = [
            ("bald front, bald head in the block", {"final_prompt": PREFIX + BALD + ", the same face as the person in "
                                                    "the picture, an unclothed body", "prompt": pose}, False),
            ("haired text front", {"final_prompt": PREFIX + "short auburn hair, an unclothed body",
                                   "prompt": haired_pose}, True),
            ("haired picture front", {"final_prompt": PREFIX + "the same face, hair and facial hair as the person "
                                      "in the picture, an unclothed body", "prompt": haired_pose}, True),
            ("older sidecar, bald in prompt", {"prompt": "standing upright, completely bald, smooth clean-shaven "
                                               "head, A-pose"}, False),
            ("older sidecar, haired prompt", {"prompt": "standing upright, short auburn hair, A-pose"}, True),
        ]
        old_first = None
        for label, meta, want in cases:
            sidecar.write_text(json.dumps({"base_signature": bsig, **meta}))
            check(label, base_body.stored_base_haired("Deck", bsig), want)
            if old_first is None:
                old_first = old.stored_base_haired("Deck", bsig)

        print("[3] fails on the old code")
        check("old stored_base_haired reads a bald front as haired", old_first, True)

    print("[4] outbound")
    check("outbound attempts", len(OUTBOUND), 0)
    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
