#!/usr/bin/env python3
"""Ruling A111: the base front's body text and the full-body reference's framing are reworded WITHOUT aging anything
(user decision 2026-11-16: every existing image stays current — no "Built with older prompts", no Build or
improvement re-render, 0 jobs). app/core/base_body.py ``BODY_TEXT`` / ``BODY_TEXT_FINGERPRINT`` /
``_fingerprint_form``; app/core/config.py ``_REFERENCE_STYLE`` / ``_NEG_REFERENCE``.

Usage:
    ./.venv/bin/python scripts/smoke_body_text_a111.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Renders go to a recorder writing an 8x8 PNG; network connects are refused and counted
(must end at 0). The skin detail step is off.

Fixtures (template human-roleplay, skin olive, eyes green, build athletic, female 30, hair long black,
hairstyle mode "hairdeck" so the plain body is bald):
  ``Pic``   profile image Pic_1.png — its front is an edit of the profile picture.
  ``Full``  profile image + a full-body reference (gallery Full_ref.png, recorded with the OLD reference prompt).
  ``Text``  no profile image — its front is made from text.

Hand-derived from the ruling:
[1] BODY_TEXT = "an unclothed body with the same skin and body surface as the person in the picture, realistic
    detailed texture, natural matte look" (the user-tested text); OLD = "an unclothed body with realistic natural
    skin, visible pores, subtle skin tone variation, matte skin" = BODY_TEXT_FINGERPRINT. edit_character(Pic) =
    BALD + ", the same face as the person in the picture, " + BODY_TEXT (the text really sent).
[2] The rule: every fingerprint hashes the A111 literal as OLD, so for each fixture today's prompt_fingerprint ==
    the pinned old module's (commit OLD_COMMIT = 6c4824a7e6e7ed93fcfdcd1d7978b81f4a0f5dd6, before the ruling — never
    HEAD), today's front_reference()["prompt"] == old._edit_fingerprint, base_identity == old.base_identity.
[3] Stored base front/back/left/right made with the OLD texts (sidecars carry the old module's fingerprint and
    front record): prompts_current True, base_prompts_freshness state "current" (no OLDER_PROMPTS),
    front_reference_state current, base_refresh_plan reason "" (the improvement spends nothing).
[4] Only the A111 literal is mapped: BODY_TEXT + ", light freckles" changes the fingerprint (a real change ages).
[5] Reference framing: _REFERENCE_STYLE starts "Full body shot from head to feet inside the frame, both feet fully
    visible with empty floor below them, {character}"; _NEG_REFERENCE ends "cropped feet, feet cut off, feet out of
    frame, cropped legs, legs cut off". Full's stored reference (old prompt in its record) stays its base image and
    the front source stays "full_body" (a reference is kept by its sha256, never by its prompt).
[6] Outbound attempts: 0.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD_COMMIT = "6c4824a7e6e7ed93fcfdcd1d7978b81f4a0f5dd6"

FAILS = []
OUTBOUND = []

BALD = "completely bald with a smooth bare scalp"
BODY = ("an unclothed body with the same skin and body surface as the person in the picture, realistic detailed "
        "texture, natural matte look")
OLD_BODY = "an unclothed body with realistic natural skin, visible pores, subtle skin tone variation, matte skin"
OLD_REFERENCE_PROMPT = ("Full body shot from head to feet inside the frame, female, 30 years old, neutral studio "
                        "lighting, plain clean background, photorealistic, high detail")


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


def png(path: Path, colour=(180, 120, 90)) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), colour).save(path)


def recorder(character_name, *, output_stem, **kw):
    from PIL import Image
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 200, 200)).save(buf, format="PNG")
    out.write_bytes(buf.getvalue())
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00",
                                                    "prompt": kw.get("bare_prompt", ""), **extra}))
    return out


def old_module():
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/base_body.py"],
                         capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType(f"base_body_{OLD_COMMIT[:9]}")
    mod.__file__ = f"base_body_{OLD_COMMIT[:9]}.py"
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="body-text-a111-") as tmp:
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

        from app.core import base_body, expression_regen, full_body_reference, garment_hair
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        data = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                "character_appearance": "{gender}, {age} years old",
                "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"}, "build": {"type": "athletic"},
                               "hair": {"length": "long", "color": "black"}}}
        names = ("Pic", "Full", "Text")
        for name in names:
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(data)), create_new=True), True)
            if name != "Text":
                png(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                check(f"profile image {name}", save_character_profile(name, stored), True)
            garment_hair.create_hairstyle(name, "", "hairdeck")
        png(get_character_images_dir("Full") / "Full_ref.png", (90, 120, 180))
        full_body_reference.set_base("Full", "Full_ref.png", origin=full_body_reference.ORIGIN_GENERATED,
                                     prompt=OLD_REFERENCE_PROMPT)
        old = old_module()

        print("[1] the texts")
        check("BODY_TEXT", base_body.BODY_TEXT, BODY)
        check("fingerprint key = the old wording", base_body.BODY_TEXT_FINGERPRINT, OLD_BODY)
        check("old module's body text", old.BODY_TEXT, OLD_BODY)
        check("edit block Pic (sent)", base_body.edit_character("Pic"),
              BALD + ", the same face as the person in the picture, " + BODY)

        print("[2] the fingerprints are the old ones")
        for name in names:
            profile = get_character_profile(name)
            check(f"{name} prompt_fingerprint", base_body.prompt_fingerprint(name), old.prompt_fingerprint(name))
            check(f"{name} base_identity", base_body.base_identity(name), old.base_identity(name))
            check(f"{name} edit fingerprint", base_body._edit_fingerprint(name, profile),
                  old._edit_fingerprint(name, profile))
        check("Full front made from the reference", base_body.front_reference("Full").get("source"),
              base_body.SOURCE_FULL_BODY)

        print("[3] stored bases made with the old texts stay current")
        from app.core.model_refs import get_model_refs_dir
        expression_regen.render_character_image = recorder
        for name in names:
            base_body.generate_base_images(name, force=True)
            bsig = base_body.base_signature(name)
            profile = get_character_profile(name)
            old_record = old.front_reference(name, profile=profile)
            fp = old.prompt_fingerprint(name)
            views = 0
            for path in get_model_refs_dir(name).glob(f"tpose*_{bsig}.json"):
                meta = json.loads(path.read_text())
                meta["prompt_fingerprint"] = fp
                if path.name == f"tpose_{bsig}.json":
                    meta["front_reference"] = old_record
                path.write_text(json.dumps(meta))
                views += 1
            check(f"{name}: four stored views", views, 4)
            check(f"{name}: prompts current", base_body.prompts_current(name, bsig), True)
            check(f"{name}: no OLDER_PROMPTS", base_body.base_prompts_freshness(name)["state"], "current")
            check(f"{name}: front reference current", base_body.front_reference_state(name)["current"], True)
            check(f"{name}: refresh plan empty", base_body.base_refresh_plan(name)["reason"], "")

        print("[4] only the A111 literal is mapped")
        before = base_body.prompt_fingerprint("Pic")
        with patch.object(base_body, "BODY_TEXT", base_body.BODY_TEXT + ", light freckles"):
            check("a clause added ages", base_body.prompt_fingerprint("Pic") != before, True)

        print("[5] the reference framing")
        check("style framing", config._REFERENCE_STYLE.startswith(
            "Full body shot from head to feet inside the frame, both feet fully visible with empty floor below them, "
            "{character}, "), True)
        check("negative feet terms", config._NEG_REFERENCE.endswith(
            "cropped feet, feet cut off, feet out of frame, cropped legs, legs cut off"), True)
        image = full_body_reference.base_image("Full")
        check("Full keeps its reference", image.name if image else None, "Full_ref.png")
        check("Full reference record keeps its old prompt",
              get_character_profile("Full")[full_body_reference.PROFILE_KEY]["prompt"], OLD_REFERENCE_PROMPT)

    print("[6] outbound")
    check("outbound attempts", len(OUTBOUND), 0)
    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
