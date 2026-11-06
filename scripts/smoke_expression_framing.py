#!/usr/bin/env python3
"""Expression images: what the prompt carries per framing.

Spec (2026-11-06, Game-Admin session, user directive):

* Characters — waist-up frame. The character part is the FACE prompt
  (`face_appearance`) plus the body slots declared `face` (hair, eyes, ...)
  and those declared `portrait` (chest/breast in the anatomy pack). Every
  other body attribute (build, legs, hips, ...) stays out. A portrait slot's
  `covered` fragment applies while dressed; its `exposed` fragment only while
  every covering clothing slot is empty. Clothing comes only from the
  species' clothing slots declared `portrait` (human: head, neck, outer, top,
  underwear_top). Underwear follows the usual rule: hidden when another piece
  `covers` it, shown otherwise.
  LoRAs follow the same rule: only exposed `face`/`portrait` slots.
* Templates declaring `features.expression_head_only` (temporary NPCs) —
  head and neck: face prompt, no clothing text at all (dressed or not),
  only `face` slot LoRAs, use case `expression_head`.
* The framing is part of the render contract, so switching it re-renders.

Fixture (synthetic slots added beside the real `human` package so the smoke
needs no private pack): `torso` portrait=true covered_by=[top, underwear_top]
(as the anatomy pack's breast slot), prompt
covered "{size} torso under clothing" / exposed "bare {size} torso", stored
size "broad", LoRA "torso_lora"; `hips` (not portrait) covered_by=[bottom],
exposed "bare hips", LoRA "hips_lora". Human slots: hair long/red ->
"long red hair" (face), build "curvy" -> "..., curvy build" (not face, not
portrait). Pieces: coat (top) "a linen coat", boots (feet) "leather boots".

Expected, derived by hand from the spec:
  A dressed character (coat + boots): prompt has FACE, "long red hair",
    "a linen coat", "broad torso under clothing"; NOT "leather boots", BODY,
    "curvy", "bare broad torso", "bare hips"; LoRAs contain neither
    torso_lora (covered) nor hips_lora (not portrait); size 1024x1024.
  B same character, boots only: "bare broad torso" in, torso_lora in,
    hips_lora still out, "bare hips" still out.
  C a temporary NPC wearing "a red dress": framing "head", use case
    expression_head, FACE2 in, "red dress" out.
  D the same NPC undressed: no clothing text, no torso_lora (not face).
  G bra (underwear_top) "a lace bra" alone: in the prompt, and the torso
    counts as covered ("broad torso under clothing", no torso_lora). Same bra under a
    shirt (top) that declares covers=[underwear_top]: "a lace bra" out,
    "a plain shirt" in.
  H the "Generate default expression" request (`default_expression`) keeps
    the CURRENT outfit (equipped_pieces None -> read from the profile) and
    an empty mood (the set's default), even when a current feeling is set;
    the old override body with empty pieces would have passed {} (undressed).
  I an expression render (any framing) is matted with BiRefNet portrait
    (postprocess portrait_matte=True); a full render keeps u2net
    (portrait_matte=False); the matte model is part of the render contract.
  E render_contract([], e, "upper_body", prof) != render_contract([], e, "head", prof);
    and the contract changes when a package stops declaring underwear_top
    `portrait` (the composed prompt would change, so must the hash).
  F a full render (no framing) still carries BODY.

Usage: ./.venv/bin/python scripts/smoke_expression_framing.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-framing-")
STORAGE = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
# Only the SFW `human` species package is enabled (world scope); the anatomy
# pack is private, its role is played by the synthetic slots below.
(STORAGE / "config.json").write_text(json.dumps({"packages": {"enabled": "human"}}))
config.load(STORAGE / "config.json")
db.init_schema()
from app.plugins.loader import discover_packages  # noqa: E402
discover_packages()  # the species packages (human) declare the slots

from unittest.mock import patch  # noqa: E402
from app.models.character import save_character_profile, get_character_profile  # noqa: E402
from app.models.inventory import add_item  # noqa: E402
from app.plugins.registry import BodySlotSpec  # noqa: E402
from app.core import body_slots, expression_regen as er  # noqa: E402

FACE = "oval face, freckles, green eyes"
FACE2 = "round face, dimples"
BODY = "long legs, broad hips"
_LORA = {"type": "lora_select"}
TORSO = BodySlotSpec(id="torso", package_id="smoke", covered_by=["top", "underwear_top"], portrait=True,
                     attributes={"size": {"type": "select"}, "lora": _LORA},
                     prompt={"covered": "{size} torso under clothing", "exposed": "bare {size} torso"})
HIPS = BodySlotSpec(id="hips", package_id="smoke", covered_by=["bottom"],
                    attributes={"lora": _LORA}, prompt={"exposed": "bare hips"})
_orig_slots = body_slots.slots_for_character


def _slots(name, profile=None):
    return list(_orig_slots(name, profile=profile)) + [TORSO, HIPS]


SLOT_VALUES = {"hair": {"length": "long", "color": "red"}, "build": {"type": "curvy"},
               "torso": {"size": "broad", "lora": "torso_lora"}, "hips": {"lora": "hips_lora"}}
assert save_character_profile("demo", {
    "template": "human-roleplay", "character_appearance": BODY, "face_appearance": FACE,
    "body_slots": SLOT_VALUES}, create_new=True)
assert save_character_profile("demo npc", {
    "template": "npc-temporary", "character_appearance": BODY, "face_appearance": FACE2,
    "outfit_description": "a red dress", "outfit_worn": True,
    "body_slots": SLOT_VALUES}, create_new=True)
coat = add_item("Demo coat", category="outfit_piece", prompt_fragment="a linen coat",
                outfit_piece={"slots": ["top"]})
bra = add_item("Demo bra", category="outfit_piece", prompt_fragment="a lace bra",
               outfit_piece={"slots": ["underwear_top"]})
shirt = add_item("Demo shirt", category="outfit_piece", prompt_fragment="a plain shirt",
                 outfit_piece={"slots": ["top"], "covers": ["underwear_top"]})
boots = add_item("Demo boots", category="outfit_piece", prompt_fragment="leather boots",
                 outfit_piece={"slots": ["feet"]})

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


def render(name, pieces, framing, **kw):
    cap = _Capture()
    with patch("app.imagegen.service.get_image_service", lambda: cap), \
            patch.object(body_slots, "slots_for_character", _slots):
        er.render_character_image(
            name, output_stem=STORAGE / "out" / "x", equipped_pieces=pieces, equipped_items=[],
            pose_prompt="standing naturally upright", expression_prompt="calm neutral face",
            apply_state_modifiers=False, neutral_state=True, framing=framing, **kw)
    assert cap.payloads, "render_character_image handed nothing to the image service"
    payload = cap.payloads[-1]
    print(f"  [{name} / {framing or 'full'}] {payload['prompt']}  loras={payload.get('loras')}")
    return payload, [l.get("name") for l in payload.get("loras") or []]


(STORAGE / "out").mkdir()
w, h = er.expression_image_size()

print("A dressed character, waist-up")
check(er.expression_framing(get_character_profile("demo")) == "upper_body", "character framing is upper_body")
a, a_loras = render("demo", {"top": coat["id"], "feet": boots["id"]}, "upper_body",
                    override_width=w, override_height=h)
pa = a["prompt"]
check(FACE in pa, "face prompt is the basis")
check("long red hair" in pa, "face slot (hair) is in")
check("a linen coat" in pa, "portrait clothing slot (top) is in")
check("leather boots" not in pa, "non-portrait clothing slot (feet) is out")
check(BODY not in pa, "body appearance text is out")
check("curvy" not in pa, "non-portrait body slot (build) is out")
check("broad torso under clothing" in pa, "portrait slot's covered fragment is in while dressed")
check("bare broad torso" not in pa, "portrait slot's exposed fragment is out while covered")
check("bare hips" not in pa, "non-portrait exposed fragment is out")
check("torso_lora" not in a_loras and "hips_lora" not in a_loras, "no LoRA of a covered or non-portrait slot")
check((a.get("override_width"), a.get("override_height")) == (1024, 1024), "rendered at the expression size")

print("B top empty, waist-up")
b, b_loras = render("demo", {"feet": boots["id"]}, "upper_body")
check("bare broad torso" in b["prompt"], "exposed fragment is in once the covering slots are empty")
check("torso_lora" in b_loras, "exposed portrait slot brings its LoRA")
check("hips_lora" not in b_loras and "bare hips" not in b["prompt"], "non-portrait slot stays out exposed")

print("G underwear follows the covering rule")
g, g_loras = render("demo", {"underwear_top": bra["id"]}, "upper_body")
check("a lace bra" in g["prompt"], "uncovered underwear top is shown")
check("broad torso under clothing" in g["prompt"] and "torso_lora" not in g_loras,
      "the bra covers the torso slot")
g2, _ = render("demo", {"underwear_top": bra["id"], "top": shirt["id"]}, "upper_body")
check("a lace bra" not in g2["prompt"] and "a plain shirt" in g2["prompt"],
      "underwear top covered by the shirt is hidden")

print("C/D temporary NPC, head and neck")
npc = get_character_profile("demo npc")
check(er.expression_framing(npc) == "head", "npc-temporary framing is head")
c, _ = render("demo npc", {}, "head", image_use_case="expression_head")
check(c.get("image_use_case") == "expression_head", "head framing uses the expression_head use case")
check(FACE2 in c["prompt"], "NPC face prompt is the basis")
check("red dress" not in c["prompt"], "no clothing text while dressed")
check(BODY not in c["prompt"], "NPC body text is out")
save_character_profile("demo npc", {**npc, "outfit_worn": False})
d, d_loras = render("demo npc", {}, "head", image_use_case="expression_head")
check("red dress" not in d["prompt"] and "torso" not in d["prompt"], "no clothing or body text undressed")
check("torso_lora" not in d_loras, "no body-slot LoRA in a head frame")

print("H default-expression request")
from app.routes import characters as char_routes  # noqa: E402
seen = []
with patch("app.core.expression_regen.expression_snapshot",
           lambda name, mood, **kw: seen.append((mood, kw)) or None), \
        patch.object(char_routes, "get_character_current_feeling", lambda _n: "furious"):
    char_routes._expression_request("demo", default_expression=True)
    char_routes._expression_request("demo", "", {}, [], True)
check(seen[0] == ("", {"equipped_pieces": None, "equipped_items": None}),
      f"default expression: current outfit, default mood (got {seen[0]})")
check(seen[1][1]["equipped_pieces"] == {}, "an override with empty pieces is an empty outfit")

print("I background matte")
from app.models import character as char_model  # noqa: E402
from app.models.character import get_character_images_dir  # noqa: E402


class _FileCapture(_Capture):
    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        get_character_images_dir("demo").mkdir(parents=True, exist_ok=True)
        (get_character_images_dir("demo") / "smoke.png").write_bytes(b"png")
        return "![x](/images/smoke.png)"


mattes = []
for framing in ("upper_body", ""):
    with patch("app.imagegen.service.get_image_service", lambda: _FileCapture()), \
            patch.object(char_model, "postprocess_outfit_image",
                         lambda path, **kw: mattes.append(kw) or path):
        er.render_character_image(
            "demo", output_stem=STORAGE / "out" / f"m{framing}", equipped_pieces={}, equipped_items=[],
            pose_prompt="p", expression_prompt="e", apply_state_modifiers=False,
            neutral_state=True, framing=framing)
check(len(mattes) == 2 and mattes[0].get("portrait_matte") is True,
      f"expression render uses the BiRefNet portrait matte (got {mattes[:1]})")
check(len(mattes) == 2 and not mattes[1].get("portrait_matte"), "a full render keeps the default matte")
with patch.object(er, "_matte_model", lambda: "u2net"):
    other = er.render_contract([], "e", "upper_body", get_character_profile("demo"))
check(other != er.render_contract([], "e", "upper_body", get_character_profile("demo")),
      "the matte model is part of the render contract")

print("E/F contract and full render")
prof = get_character_profile("demo")
base = er.render_contract([], "e", "upper_body", prof)
check(base != er.render_contract([], "e", "head", prof), "framing is part of the render contract")
with patch("app.core.body_slots.portrait_piece_slots", lambda _p: ("head", "neck", "outer", "top")):
    check(er.render_contract([], "e", "upper_body", prof) != base,
          "the package's portrait clothing slots are part of the render contract")
with patch.object(body_slots, "slots_for_character", _slots):
    check(er.render_contract([], "e", "upper_body", prof) != base,
          "the portrait body slots are part of the render contract")
f, _ = render("demo", {"top": coat["id"]}, "")
check(BODY in f["prompt"], "a full-body render keeps the body appearance")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("PASS expression framing: face basis + portrait slots / head only")
