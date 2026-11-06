#!/usr/bin/env python3
"""Expression images are built on the FACE prompt, not the body appearance.

Spec (2026-11-06, Game-Admin session): an expression image is framed from the
waist up. The full body description (build, legs, every body slot) pulled the
model into a full-length picture, so the character part of an expression render
is the face prompt — the profile image's basis (`face_appearance`, tokens
resolved). Outfit, pose and expression follow unchanged, and the render uses the
expression size (`image_generation.expression_image_width/height`, schema
default 1024x1024), not the outfit size (schema default 832x1216).

Expected values, derived by hand from that spec:
  * the character's face prompt "oval face, freckles, green eyes" is in the
    prompt handed to the image service;
  * the body text "long legs, broad hips" is NOT in it;
  * the outfit fragment "a linen coat" is still in it;
  * override_width == 1024 and override_height == 1024;
  * a full-body render of the same character (the default-pose reference path,
    no face basis) still carries "long legs, broad hips".
  * the render contract changes when the basis changes: it is not the digest
    computed without the "appearance" key.

Usage: ./.venv/bin/python scripts/smoke_expression_face_basis.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-face-")
STORAGE = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from unittest.mock import patch  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.inventory import add_item  # noqa: E402
from app.core import expression_regen as er  # noqa: E402

FACE = "oval face, freckles, green eyes"
BODY = "long legs, broad hips"
assert save_character_profile("demo", {
    "template": "human-roleplay",  # has the outfit system
    "character_appearance": BODY,
    "face_appearance": FACE,
}, create_new=True)
coat = add_item("Demo coat", category="outfit_piece", prompt_fragment="a linen coat",
                outfit_piece={"slots": ["top"]})

failures = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


class _Capture:
    enabled = True

    def __init__(self):
        self.payloads = []

    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        return "no image (smoke)"


def render(face_basis, **size):
    cap = _Capture()
    with patch("app.imagegen.service.get_image_service", lambda: cap):
        er.render_character_image(
            "demo", output_stem=STORAGE / "out" / "demo_x",
            equipped_pieces={"top": coat["id"]}, equipped_items=[],
            pose_prompt="standing naturally upright", expression_prompt="calm neutral face",
            apply_state_modifiers=False, neutral_state=True, face_basis=face_basis, **size)
    assert cap.payloads, "render_character_image handed nothing to the image service"
    return cap.payloads[-1]


(STORAGE / "out").mkdir()
w, h = er.expression_image_size()
check((w, h) == (1024, 1024), f"expression size is the schema default 1024x1024 (got {w}x{h})")

face = render(True, override_width=w, override_height=h)
prompt = face["prompt"]
print("  expression prompt:", prompt)
check(FACE in prompt, "the face prompt is the character part")
check(BODY not in prompt, "the body appearance is left out")
check("a linen coat" in prompt, "the outfit is still described")
check(face.get("override_width") == 1024 and face.get("override_height") == 1024,
      "rendered at the expression size")

full = render(False)
check(BODY in full["prompt"], "a full-body render keeps the body appearance")

old = er._digest({"version": 2, "pose_prompt": "p", "expression_prompt": "e",
                  "style": er._style_fingerprint(), "size": [w, h]})
check(er.render_contract("p", "e") != old, "the face basis is part of the render contract")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("PASS expression images are built on the face prompt at their own size")
