#!/usr/bin/env python3
"""Smoke run for the {fabric} clause of the mesh-input styles — that a figure
wearing nothing is not rendered against a style asking for fabric textures.

Throwaway storage, throwaway world DB — no server, no real world is touched,
and NOTHING is rendered: the image service is replaced by a stub that records
the payload `generate_from_input` is handed.

Usage:  ./.venv/bin/python scripts/smoke_fabric_clause.py

THE CHAIN, and why all three links are checked here
---------------------------------------------------------------------------
The T-pose styles name the materials the render should show — "lifelike skin
and fabric textures". On a character wearing nothing there is no fabric, and
the words alone make the model drape cloth over the figure, which then bakes
into the 3D mesh. The clause is therefore a `{fabric}` slot, filled in by
`config.get_use_case_prompts(clothed=…)`.

Three components have to agree, and the bug of 2026-09-02 sat in the middle
one, which is why the fix of the day before (commit 66afa89a) changed nothing
in the picture:

  [1] `expression_regen.generate_expression_image` KNOWS the state — it built
      the outfit text — and writes `clothed` into the payload.
  [2] `ImageService._parse_input` normalises that payload into the dict the
      generation reads. It is a WHITELIST of keys, and a key that is not in
      it is silently dropped.
  [3] `ImageService.generate` reads `input_data.get("clothed", True)` and
      hands it to `get_use_case_prompts`.

[1] and [3] were right; [2] dropped the flag, so [3] always saw its default
`True` and every undressed T-pose render carried the fabric clause. Checking
[3] alone would have passed while the picture stayed wrong — this file walks
the whole chain (feedback_pruefe_am_verbraucher).

Hand-derived expectations
---------------------------------------------------------------------------
  [1] A temporary NPC has no outfit system: it is dressed by the profile's
      free-text `outfit_description`, and `outfit_worn` is its binary dressed
      state. `render_outfit` puts the text into `full` only, never into
      `pieces`, and for `outfit_worn` false it replaces it with the STATEMENT
      `NO_CLOTHES_TEXT` = "no clothes" — which does not start with the
      "wearing: " prefix `expression_regen` strips. So:

        outfit_worn False  ->  prompt says "no clothes",   clothed False
        outfit_worn True   ->  prompt says "is wearing …", clothed True

  [2] The parsed dict carries `clothed` verbatim, False as well as True. The
      DEFAULT stays `True`: a payload without the key (every path that never
      asked) must render exactly as it did before the flag existed.

  [3] `FABRIC_CLAUSE` is " and fabric", so for the six mesh-input styles
      (tpose / tpose_back / tpose_side × natural / keywords):

        clothed=True   ->  "lifelike skin and fabric textures"
        clothed=False  ->  "lifelike skin textures"

      and no output may ever contain a raw "{fabric}". `tpose_animal` has no
      placeholder — fur is not fabric — and must come through untouched, as
      must any style an admin has typed over.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="fabric-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="fabric-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import expression_regen  # noqa: E402
from app.core.config import FABRIC_CLAUSE  # noqa: E402
from app.core.outfit_renderer import NO_CLOTHES_TEXT  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
from app.imagegen.service import ImageService  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the image-service stub ──────────────────────────────────────────────────

class FakeBackend:
    """What `expression_regen` reads off a backend: its name and the family
    that picks the style (natural = flowing prose, keywords = comma tags)."""

    name = "FakeBackend"
    image_family = "natural"


class FakeImageService:
    """Records the payload instead of rendering. The four methods below are
    everything the expression path asks of the service before it hands the
    payload over."""

    enabled = True

    def __init__(self):
        self.payloads = []

    def match_backend(self, *a, **k):
        return None

    def resolve_imagegen_target(self, *a, **k):
        return None

    def _wait_for_backend(self, *a, **k):
        return FakeBackend()

    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        # The cache-hit sentinel: a path-shaped answer would send the caller
        # looking for a file that was never written (feedback_no_new_image_sentinel).
        return "NO_NEW_IMAGE"


SERVICE = FakeImageService()
imagegen_service.get_image_service = lambda: SERVICE


def render_payload(name: str, *, worn: bool) -> dict:
    """One T-pose reference render of a free-text-wardrobe character, as
    `model_refs` asks for it. Returns the payload the service was handed."""
    save_character_profile(name, {
        "name": name,
        "character_appearance": "woman, late 20s, short hair",
        "outfit_description": "a plain linen dress",
        "outfit_worn": worn,
    }, create_new=True)
    SERVICE.payloads.clear()
    expression_regen.generate_expression_image(
        name, mood="", pose_key="", equipped_pieces={}, equipped_items=[],
        prompt_prefix="T-pose", pose_prompt_override="",
        expression_prompt_override="", image_use_case="tpose",
        output_stem=STORAGE / f"ref_{name}", apply_state_modifiers=False)
    assert SERVICE.payloads, f"the render of {name} handed the service nothing"
    return SERVICE.payloads[-1]


print("[1] the renderer states the dressed state")
undressed = render_payload("Bare", worn=False)
check("undressed: prompt says so", NO_CLOTHES_TEXT in undressed["prompt"], True)
check("undressed: no 'is wearing'", "is wearing" in undressed["prompt"], False)
check("undressed: payload clothed", undressed.get("clothed"), False)

dressed = render_payload("Dressed", worn=True)
check("dressed: prompt says what is worn",
      "is wearing a plain linen dress" in dressed["prompt"], True)
check("dressed: payload clothed", dressed.get("clothed"), True)

print("[2] the payload survives _parse_input (the hole of 2026-09-02)")
svc = ImageService.__new__(ImageService)   # no config, no backends — the
                                           # parser is pure bookkeeping
for label, payload, expected in (("undressed", undressed, False),
                                 ("dressed", dressed, True)):
    parsed = svc._parse_input(json.dumps(payload))
    check(f"{label}: clothed reaches the parsed input",
          parsed.get("clothed", "(dropped)"), expected)
    # …and what the consumer in `generate` actually computes from it:
    check(f"{label}: what generate() reads",
          bool(parsed.get("clothed", True)), expected)
check("a payload without the key defaults to dressed",
      bool(svc._parse_input(json.dumps({"prompt": "x"})).get("clothed", True)),
      True)

print("[3] the style follows the flag")
check("FABRIC_CLAUSE", FABRIC_CLAUSE, " and fabric")
for uc in ("tpose", "tpose_back", "tpose_side"):
    for family in ("natural", "keywords"):
        yes = config.get_use_case_prompts(uc, family, clothed=True)["prompt_style"]
        no = config.get_use_case_prompts(uc, family, clothed=False)["prompt_style"]
        check(f"{uc}/{family}: dressed keeps the fabric",
              "lifelike skin and fabric textures" in yes, True)
        check(f"{uc}/{family}: undressed drops it",
              "lifelike skin textures" in no and "fabric" not in no, True)
        check(f"{uc}/{family}: no raw placeholder",
              "{fabric}" in yes or "{fabric}" in no, False)

# Fur is not fabric: the animal style never carried the placeholder and must
# read the same either way.
animal_yes = config.get_use_case_prompts("tpose_animal", "natural", clothed=True)
animal_no = config.get_use_case_prompts("tpose_animal", "natural", clothed=False)
check("tpose_animal is untouched by the flag",
      animal_yes["prompt_style"] == animal_no["prompt_style"], True)

# A style an admin typed over keeps exactly what they typed — the placeholder
# is an offer, not a rewrite rule.
cfg = config.get_all()
(cfg.setdefault("image_generation", {}).setdefault("use_cases", {})
    .setdefault("tpose", {}).setdefault("styles", {})
    .setdefault("natural", {}))["prompt_style"] = "my own words, and fabric textures"
config.save(cfg, STORAGE / "config.json")
check("an admin override is left as written",
      config.get_use_case_prompts("tpose", "natural", clothed=False)["prompt_style"],
      "my own words, and fabric textures")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} ok")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
