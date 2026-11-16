"""Smoke: Ruling A143 — a figure render that slots a picture of the person does not re-describe the person.

Usage:
    ./.venv/bin/python scripts/smoke_picture_reference_appearance.py

Runs without the server, without a world DB of its own (a temp storage + instance), without any image/LLM request
(``socket.connect`` / ``requests`` refuse; the image service is a stub that records the payload).

Fixture ``Pic`` (template human-roleplay, female, 21, 168 cm) with distinctive tokens in the free-text appearance
"{gender}, {age} years old, ink-stained fingers, round glasses, slightly hunched posture" and the human slots
hair {length long, color auburn}, eyes {color green}, skin {tone olive}, build {type slender}; a profile image.

Expected, derived by hand from plugins/human/plugin.yaml (hair "{length} {color} hair" face, eyes "{color} eyes"
face, skin "{tone} skin" face, build "{height}, {type} build" — not face; 168 cm female → "average height", the
phrase smoke_full_body_reference.py measures for the same height) and the rule:

[1] person_description without a picture (today's text, unchanged):
      "female, 21 years old, ink-stained fingers, round glasses, slightly hunched posture, long auburn hair,
       green eyes, olive skin, average height, slender build"  (appearance text, then the slots in manifest order)
    with picture_reference=True: "average height, slender build" — no free text, no face slot.
[2] full_body_reference.base_block / outfit_block (an edit of the profile picture or the plain body's reference —
    always a picture): "average height, slender build" (the height phrase is already in the build fragment).
[3] The T-pose extra view (render_character_image, occasion tpose_view, reference_image = the main render):
    the payload prompt contains none of the tokens "ink-stained", "glasses", "hunched", "auburn", "green eyes",
    "olive skin", "21 years old"; it contains "average height, slender build" and the hair slot's mesh-input line
    for long hair ("hair tucked back behind the shoulders …") — a placement rule (A-series), not a description. The same render WITHOUT a reference
    image (and the T-pose main, which slots the profile picture only where the backend can) keeps every token.
[4] Outbound attempts: 0.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FULL = ("female, 21 years old, ink-stained fingers, round glasses, slightly hunched posture, long auburn hair, "
        "green eyes, olive skin, average height, slender build")
PICTURE = "average height, slender build"
#: plugins/human/plugin.yaml, hair slot mesh_input_prompt for long hair (a placement rule, not a description).
HAIR_LINE = "hair tucked back behind the shoulders and falling down the back, the chest and collarbones free of hair"
TOKENS = ("ink-stained", "glasses", "hunched", "auburn", "green eyes", "olive skin", "21 years old")

FAILS: list = []
OUTBOUND: list = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f"\n       want {want!r}"))
    if not ok:
        FAILS.append(label)


def block_network():
    import socket
    import requests

    def refuse_connect(self, *a, **kw):
        OUTBOUND.append(("socket", a))
        raise OSError("network refused in smoke")

    def refuse_request(self, method, url, *a, **kw):
        OUTBOUND.append((method, url))
        raise OSError("network refused in smoke")
    socket.socket.connect = refuse_connect
    requests.Session.request = refuse_request


def png(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (200, 100, 50, 255)).save(path)


class StubService:
    enabled = True

    def __init__(self):
        self.payloads = []

    def generate_from_input(self, raw, **kw):
        self.payloads.append(json.loads(raw) if isinstance(raw, str) else dict(raw))
        return None

    def __getattr__(self, name):
        raise AttributeError(name)


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="a143-") as tmp:
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
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import expression_regen, full_body_reference as fbr
        from app.core.prompt_builder import person_description
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        profile = {"template": "human-roleplay", "gender": "female", "age": 21, "height": 168,
                   "character_appearance": "{gender}, {age} years old, ink-stained fingers, round glasses, "
                                           "slightly hunched posture",
                   "body_slots": {"hair": {"length": "long", "color": "auburn"}, "eyes": {"color": "green"},
                                  "skin": {"tone": "olive"}, "build": {"type": "slender"}}}
        check("create Pic", save_character_profile("Pic", profile, create_new=True), True)
        png(get_character_images_dir("Pic") / "Pic_1.png")
        stored = get_character_profile("Pic")
        stored["profile_image"] = "Pic_1.png"
        check("profile image", save_character_profile("Pic", stored), True)
        stored = get_character_profile("Pic")

        print("[1] person_description")
        kw = dict(apply_state_modifiers=False, body_profile=stored, neutral_state=True)
        check("no picture: today's text", person_description("Pic", **kw), FULL)
        check("picture slotted: only what the render enforces",
              person_description("Pic", picture_reference=True, **kw), PICTURE)

        print("[2] full-body references")
        check("base_block", fbr.base_block("Pic"), PICTURE)
        check("outfit_block (nothing worn)", fbr.outfit_block("Pic"), PICTURE)

        print("[3] render_character_image, T-pose extra view")
        stub = StubService()
        ref = root / "main.png"
        png(ref)
        with patch("app.imagegen.service.get_image_service", lambda: stub), \
                patch("app.core.model_refs.checked_reference_override", lambda name, raw: raw):
            for label, reference in (("with the main render", ref), ("without a reference", None)):
                stub.payloads.clear()
                try:
                    expression_regen.render_character_image(
                        "Pic", output_stem=root / "out" / "view", equipped_pieces={}, equipped_items=[],
                        pose_prompt="", expression_prompt="", prompt_prefix="the same figure turned around",
                        image_use_case="tpose_back", occasion="tpose_view", apply_state_modifiers=False,
                        mesh_input_profile=stored, back_view=False, reference_image=reference, name_outfit=False)
                except Exception as err:   # the stub delivers nothing; the payload is what counts
                    print(f"       (render ended: {type(err).__name__})")
                prompt = stub.payloads[0].get("prompt", "") if stub.payloads else ""
                print(f"       prompt {label}: {prompt!r}")
                present = [t for t in TOKENS if t in prompt]
                if reference is not None:
                    check(f"{label}: no appearance token", present, [])
                    check(f"{label}: build kept", PICTURE in prompt, True)
                    check(f"{label}: the mesh-input hair line stays (it places the hair)", HAIR_LINE in prompt, True)
                else:
                    check(f"{label}: every appearance token", present, list(TOKENS))

        print("[4] outbound")
        check("outbound attempts", OUTBOUND, [])
    print("\nFAILED: %d — %s" % (len(FAILS), FAILS) if FAILS else "\nAll checks passed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
