#!/usr/bin/env python3
"""Ruling A94: a base front made as an EDIT of a picture keeps the face, the hair and the facial hair OF THE
PICTURE instead of re-describing them, and the edit views of such a front take hair and facial hair from the front
(app/core/base_body.py: ``edit_character``, ``base_prompt(picture=…)``, ``prompt_fingerprint``).

Usage:
    ./.venv/bin/python scripts/smoke_picture_identity_a94.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Every render goes to a recorder (``expression_regen.render_character_image``) that
writes an 8x8 PNG. ``socket.socket.connect`` and ``requests.Session.request`` are replaced by counters that refuse:
the run must end with 0 outbound attempts. The skin detail step is switched off (it is not what this checks).

Fixtures (template human-roleplay, profile image <name>_1.png, skin olive, eyes green, build athletic):
  ``Beard``      male 40, hair slot {length short, color auburn}, appearance "{gender}, {age} years old, a full
                 auburn beard"; first hairstyle made from the Appearance in mode "body".
  ``BeardDeck``  the same, hairstyle mode "hairdeck" (the plain body is bald).
  ``Deck``       female 30, hair slot {length long, color black}, appearance "{gender}, {age} years old";
                 hairstyle mode "hairdeck".
  ``Rewritten``  male 40, hair slot {length short, color black}, appearance "{gender}, {age} years old"; first
                 hairstyle "a shaved undercut" (a text that is NOT the Appearance's hair) in mode "body".
  ``Bare``       = Beard without a profile image: its front is made from text.

Hand-derived from the ruling (the user: the reference image is the truth; precedent Ruling A29: a view change
never re-describes what the picture shows) with BALD = "completely bald with a smooth bare scalp", BODY = "an
unclothed body with the same skin and body surface as the person in the picture, realistic detailed texture,
natural matte look" (Ruling A111; the human package adds no base-body text):

[1] The Appearance's hair text of Beard is the hair slot's "{length} {color} hair" = "short auburn hair" (the beard
    clause names no \\bhair\\b) — the plain hair text, so hair_from_picture(Beard) True; Rewritten's plain text
    "a shaved undercut" is not "short black hair": False. Facial hair: Beard / BeardDeck True ("beard"), Deck /
    Rewritten False. edit_character:
      Beard      "the same face, hair and facial hair as the person in the picture, " + BODY   (no "auburn")
      BeardDeck  BALD + ", the same face and facial hair as the person in the picture, " + BODY
      Deck       BALD + ", the same face as the person in the picture, " + BODY
      Rewritten  "a shaved undercut, the same face as the person in the picture, " + BODY
[2] base_prompt(picture=True). VIEW_HAIR = "the same hairstyle, hair length, hair volume and hair colour as the
    reference", BEARD = "the same facial hair as the reference":
      Beard back  = "The same person turned around, seen directly from behind, back view, same A-pose, same
                    framing, " + VIEW_HAIR + ", " + BEARD + ", the whole figure from head to feet in the frame."
      BeardDeck left = "The same person turned to a strict left side profile view, same A-pose, same framing,
                    completely bald, " + BEARD + ", the whole figure from head to feet in the frame."
      Deck back/left/right = BASE_VIEW_PROMPTS (unchanged: bald, no facial hair);
      Rewritten back = the old haired text (hair text + "the same hairstyle, hair length and hair volume as the
                    reference"), byte for byte as base_prompt(picture=False).
    Negatives: Beard's starts "hat, hood, headscarf, wig" (haired, as before); BeardDeck's = "long hair, short hair,
    ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, stubble on the scalp, hair on the shoulders,
    hair on the back, clothing, underwear, jewellery, " + POSE_NEG — no bare "hair" clause (it would forbid the
    beard); Deck's = BASE_NEGATIVE (with the bare "hair").
    picture=False for every fixture == the old module's base_prompt, byte for byte (a text front keeps its texts).
[3] generate_base_images(Beard): the front's use case "base_front_edit", style_character = [1]'s Beard block,
    bare_prompt = the A-pose with the hair clause (unchanged), extra_negative = [2]'s Beard negative; the back
    render's bare_prompt = [2]'s Beard back. generate_base_images(Bare): use case "base_front", style_character
    = base_character(front) (the hair text named — no picture), the back = the old module's text.
[4] What becomes due (old records written as the old module makes them, then judged by today's code):
      Deck: prompt_fingerprint == the old module's (nothing in its views changed); its front record's edit text
        differs (the face clause) -> front_reference_state reason FRONT_OTHER_EDIT_TEXT, prompts_current True,
        base_refresh_plan() reason "" (the improvement never spends on it), base_refresh_plan(missing=True)
        reason "reference" (a click: every view, then the model);
      Beard: prompt_fingerprint != the old module's -> OLDER_PROMPTS (base_prompts_freshness "stale");
      Bare (text front): prompt_fingerprint == the old module's and front_reference {"method": "text"} on both:
        current.
[5] Fails on the old code (commit OLD = 83855a099, before the ruling — never HEAD): its edit_character(Beard) is
    "short auburn hair, " + OLD_BODY (its pre-A111 body text; the hair re-described, no face, no beard) and its base_prompt takes no
    ``picture`` — each of [1]/[2] would fail there.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The commit before Ruling A94 — never HEAD.
OLD = "83855a099"
FAILS = []
OUTBOUND = []
CALLS = []

BALD = "completely bald with a smooth bare scalp"
BODY = "an unclothed body with the same skin and body surface as the person in the picture, realistic detailed texture, natural matte look"
#: The body text of the pinned old code (before Ruling A111).
OLD_BODY = "an unclothed body with realistic natural skin, visible pores, subtle skin tone variation, matte skin"
VIEW_HAIR = "the same hairstyle, hair length, hair volume and hair colour as the reference"
BEARD = "the same facial hair as the reference"
POSE_NEG = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, feet cut off, "
            "cropped legs, close-up, portrait crop")
BEARD_DECK_NEG = ("long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, stubble on "
                  "the scalp, hair on the shoulders, hair on the back, clothing, underwear, jewellery, " + POSE_NEG)


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


def png_grey() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


def recorder(character_name, *, output_stem, **kw):
    CALLS.append({"name": character_name, **kw})
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png_grey())
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00",
                                                    "prompt": kw.get("bare_prompt", ""), **extra}))
    return out


def old_module():
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/base_body.py"],
                         capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType(f"base_body_{OLD}")
    mod.__file__ = f"base_body_{OLD}.py"
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="picture-identity-") as tmp:
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

        from app.core import base_body, expression_regen, garment_hair
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        slots = {"skin": {"tone": "olive"}, "eyes": {"color": "green"}, "build": {"type": "athletic"}}
        bearded = {"template": "human-roleplay", "gender": "male", "age": 40, "height": 180,
                   "character_appearance": "{gender}, {age} years old, a full auburn beard",
                   "body_slots": {**slots, "hair": {"length": "short", "color": "auburn"}}}
        plain_m = {"template": "human-roleplay", "gender": "male", "age": 40, "height": 180,
                   "character_appearance": "{gender}, {age} years old",
                   "body_slots": {**slots, "hair": {"length": "short", "color": "black"}}}
        female = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                  "character_appearance": "{gender}, {age} years old",
                  "body_slots": {**slots, "hair": {"length": "long", "color": "black"}}}
        fixtures = (("Beard", bearded, True, "", "body"), ("BeardDeck", bearded, True, "", "hairdeck"),
                    ("Deck", female, True, "", "hairdeck"), ("Rewritten", plain_m, True, "a shaved undercut", "body"),
                    ("Bare", bearded, False, "", "body"))
        for name, data, image, hair, mode in fixtures:
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(data)), create_new=True), True)
            if image:
                png(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                check(f"profile image {name}", save_character_profile(name, stored), True)
            garment_hair.create_hairstyle(name, hair, mode)
        old = old_module()

        print("[1] the edit block keeps the person of the picture")
        check("appearance hair Beard", garment_hair.appearance_hair_text("Beard"), "short auburn hair")
        check("plain hair Beard / BeardDeck", (base_body.hair_text("Beard"), base_body.hair_text("BeardDeck")),
              ("short auburn hair", ""))
        check("hair from the picture", [base_body.hair_from_picture(n) for n in ("Beard", "Rewritten", "Deck")],
              [True, False, False])
        check("facial hair", [base_body.has_facial_hair(n) for n in ("Beard", "BeardDeck", "Deck", "Rewritten")],
              [True, True, False, False])
        blocks = {
            "Beard": "the same face, hair and facial hair as the person in the picture, " + BODY,
            "BeardDeck": BALD + ", the same face and facial hair as the person in the picture, " + BODY,
            "Deck": BALD + ", the same face as the person in the picture, " + BODY,
            "Rewritten": "a shaved undercut, the same face as the person in the picture, " + BODY,
        }
        for name, want in blocks.items():
            check(f"edit block {name}", base_body.edit_character(name), want)
        check("no hair colour in Beard's block", "auburn" in base_body.edit_character("Beard"), False)

        print("[2] the edit views of a front made from a picture")
        views = {v: base_body.BASE_VIEW_PROMPTS[v] for v in ("back", "left", "right")}
        check("Beard back", base_body.base_prompt("Beard", "back", picture=True)[0],
              "The same person turned around, seen directly from behind, back view, same A-pose, same framing, "
              + VIEW_HAIR + ", " + BEARD + ", the whole figure from head to feet in the frame.")
        check("BeardDeck left", base_body.base_prompt("BeardDeck", "left", picture=True)[0],
              "The same person turned to a strict left side profile view, same A-pose, same framing, completely "
              "bald, " + BEARD + ", the whole figure from head to feet in the frame.")
        check("Deck views unchanged", {v: base_body.base_prompt("Deck", v, picture=True)[0] for v in views}, views)
        check("Rewritten back = the text-front text", base_body.base_prompt("Rewritten", "back", picture=True)[0],
              base_body.base_prompt("Rewritten", "back", picture=False)[0])
        check("Rewritten back names its hair", "a shaved undercut, the same hairstyle, hair length and hair volume "
              "as the reference" in base_body.base_prompt("Rewritten", "back", picture=True)[0], True)
        check("Beard negative (haired)", base_body.base_prompt("Beard", "front", picture=True)[1]
              .startswith("hat, hood, headscarf, wig, "), True)
        neg = base_body.base_prompt("BeardDeck", "front", picture=True)[1]
        check("BeardDeck negative", neg, BEARD_DECK_NEG)
        check("BeardDeck negative: no bare 'hair'", "hair" in [c.strip() for c in neg.split(",")], False)
        check("Deck negative", base_body.base_prompt("Deck", "front", picture=True)[1], base_body.BASE_NEGATIVE)
        for name, *_rest in fixtures:
            check(f"{name}: text front = old texts", [base_body.base_prompt(name, v) for v in base_body.BASE_VIEWS],
                  [old.base_prompt(name, v) for v in base_body.BASE_VIEWS])

        print("[3] the render")
        expression_regen.render_character_image = recorder
        base_body.generate_base_images("Beard")
        front, back = CALLS[0], next(c for c in CALLS if c.get("back_view"))
        check("Beard front use case", front["image_use_case"], "base_front_edit")
        check("Beard front block", front["style_character"], blocks["Beard"])
        check("Beard front pose", front["bare_prompt"], base_body.base_prompt("Beard", "front", picture=False)[0])
        check("Beard front negative", front["extra_negative"], base_body.base_prompt("Beard", "front",
                                                                                     picture=True)[1])
        check("Beard back prompt", back["bare_prompt"], base_body.base_prompt("Beard", "back", picture=True)[0])
        CALLS.clear()
        base_body.generate_base_images("Bare")
        front, back = CALLS[0], next(c for c in CALLS if c.get("back_view"))
        check("Bare front: the text render", (front["image_use_case"], front["style_character"]),
              ("base_front", base_body.base_character("Bare", "front")))
        check("Bare back: the old text", back["bare_prompt"], old.base_prompt("Bare", "back")[0])

        print("[4] what becomes due")
        from app.core.model_refs import get_model_refs_dir
        expression_regen.render_character_image = recorder
        for name in ("Deck", "Beard"):
            base_body.generate_base_images(name, force=True)
            bsig = base_body.base_signature(name)
            refs = get_model_refs_dir(name)
            record = dict(base_body.front_reference(name), prompt=old._edit_fingerprint(name,
                                                                                         get_character_profile(name)))
            fp = old.prompt_fingerprint(name)
            for path in refs.glob(f"tpose*_{bsig}.json"):
                meta = json.loads(path.read_text())
                meta["prompt_fingerprint"] = fp
                if path.name == f"tpose_{bsig}.json":
                    meta["front_reference"] = record
                path.write_text(json.dumps(meta))
        check("Deck fingerprint = the old one", base_body.prompt_fingerprint("Deck"), old.prompt_fingerprint("Deck"))
        state = base_body.front_reference_state("Deck")
        check("Deck front: older edit text", (state["current"], state["reason"]),
              (False, base_body.FRONT_OTHER_EDIT_TEXT))
        check("Deck prompts current", base_body.prompts_current("Deck", base_body.base_signature("Deck")), True)
        check("Deck: the improvement spends nothing", base_body.base_refresh_plan("Deck")["reason"], "")
        run_all = base_body.base_refresh_plan("Deck", missing=True)
        check("Deck: a click re-makes it", (run_all["reason"], run_all["views"], run_all["model"]),
              ("reference", list(base_body.BASE_VIEWS), True))
        check("Beard fingerprint differs", base_body.prompt_fingerprint("Beard") != old.prompt_fingerprint("Beard"),
              True)
        check("Beard: older prompts", base_body.base_prompts_freshness("Beard")["reason"], base_body.OLDER_PROMPTS)
        check("Bare fingerprint = the old one", base_body.prompt_fingerprint("Bare"), old.prompt_fingerprint("Bare"))
        check("Bare front reference: text", (base_body.front_reference("Bare"), old.front_reference("Bare")),
              ({"method": "text"}, {"method": "text"}))
        check("Bare prompts current", base_body.base_prompts_freshness("Bare")["state"], "current")

        print("[5] fails on the old code")
        check("old edit block re-describes the hair", old.edit_character("Beard"), "short auburn hair, " + OLD_BODY)
        check("old edit block != today's", old.edit_character("Beard") != blocks["Beard"], True)
        try:
            old.base_prompt("Beard", "back", picture=True)
            got = "accepted"
        except TypeError:
            got = "no picture"
        check("old base_prompt has no picture", got, "no picture")

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
