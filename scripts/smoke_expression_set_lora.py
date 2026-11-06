#!/usr/bin/env python3
"""Expression sets carry ONE LoRA; the fixed image pose is gone.

Spec (2026-11-06, Game-Admin session, user directive): the shipped sets stay
(no LoRA). A new set is created in the Poses tab with its own expressions
and one LoRA (+ strength). A character picks the set in its Expressions tab;
the LoRA is shown after the pick together with whether the character's
expression backend has it. Generation renders the set member's prompt with
the set's LoRA. Switching the set drops the expression cache. Sets no longer
have a fixed image pose.

Expected values, derived by hand from that spec:
  A the shipped catalog file has no "pose_prompt" in any group; the shipped
    sets humanoid/animal have lora "" (strength 1.0).
  B replace_set('emote', lora "emote_v2.safetensors", strength 0.8, one
    member "emote_neutral" prompt "make the woman neutral") -> the set reads
    back lora "emote_v2.safetensors", lora_strength 0.8.
  C a character on set "emote": its snapshot carries loras
    [{"name": "emote_v2.safetensors", "strength": 0.8}] and the prompt
    "make the woman neutral"; its render contract differs from the same
    contract with loras [] (a LoRA change re-renders).
  D the render payload's LoRAs contain emote_v2.safetensors at 0.8, and the
    prompt carries no former set pose ("standing naturally upright").
  E switching humanoid -> emote deletes the cached expression files (2 -> 0);
    switching "" (Automatic, resolves to humanoid) -> "humanoid" keeps them.
  G import into "emote" from pasted lines: "0 | Frustrated | make the woman
    frustrated", "38 | Lip Bite | make the woman bite her lip", "74 | LipBite |
    make the woman lip-bite", "Neutral | make the woman neutral" -> created 3
    (emote_frustrated, emote_lip_bite, emote_lipbite); "Neutral" skipped
    (emote_neutral exists); synonyms "frustrated", "lip bite", "lipbite";
    a second identical import creates 0 and skips all 4; a malformed line
    ("just text") rejects the whole import and changes nothing.
  F the character options report, per set, whether the expression backend
    has the LoRA: emote True when the library associates it with backend
    "Qwen", False when not; humanoid (no LoRA) None.

Usage: ./.venv/bin/python scripts/smoke_expression_set_lora.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-set-lora-")
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
from app.core.expression_sets_migration import migrate_catalog_metadata  # noqa: E402
migrate_catalog_metadata()

from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402
from app.core import expression_sets as es, expression_regen as er  # noqa: E402
from app.core.character_ops import apply_profile_update  # noqa: E402
from app.models.character import save_character_profile, get_character_profile  # noqa: E402

failures = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


print("A shipped sets")
shipped = json.loads(Path("shared/templates/expression/expression_catalog.json").read_text())
check(all("pose_prompt" not in g for g in shipped["groups"].values()), "no fixed pose in the shipped catalog")
cat = es.catalog_snapshot()
check(all(cat.sets[s].lora == "" and cat.sets[s].lora_strength == 1.0 for s in ("humanoid", "animal")),
      "shipped sets have no LoRA")

print("B a set with a LoRA")
es.replace_set("emote", {"label": "Emote", "default": "emote_neutral", "members": ["emote_neutral"],
                         "lora": "emote_v2.safetensors", "lora_strength": 0.8,
                         "entries": {"emote_neutral": {"prompt": "make the woman neutral",
                                                       "synonyms": ["neutral"]}}}, store="world")
spec = es.catalog_snapshot().sets["emote"]
check((spec.lora, spec.lora_strength) == ("emote_v2.safetensors", 0.8), f"set reads back its LoRA ({spec.lora}, {spec.lora_strength})")

print("C snapshot and contract")
assert save_character_profile("demo", {"template": "human-roleplay", "face_appearance": "oval face",
                                       "expression_set": "emote"}, create_new=True)
snap = er.expression_snapshot("demo", "")
check(er._thaw(snap.loras) == [{"name": "emote_v2.safetensors", "strength": 0.8}], f"snapshot carries the set LoRA ({er._thaw(snap.loras)})")
check(snap.expression_prompt == "make the woman neutral", "snapshot carries the member prompt")
profile = get_character_profile("demo")
check(snap.contract != er.render_contract([], snap.expression_prompt, snap.framing, profile),
      "the set LoRA is part of the render contract")

print("D render payload")


class _Capture:
    enabled = True

    def __init__(self):
        self.payloads = []

    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        return "no image (smoke)"


cap = _Capture()
with patch("app.imagegen.service.get_image_service", lambda: cap):
    er.render_character_image("demo", output_stem=STORAGE / "x", equipped_pieces={}, equipped_items=[],
                              pose_prompt="", expression_prompt=snap.expression_prompt, framing=snap.framing,
                              expression_set_loras=er._thaw(snap.loras),
                              apply_state_modifiers=False, neutral_state=True)
payload = cap.payloads[-1]
print("  prompt:", payload["prompt"], " loras:", payload.get("loras"))
check({"name": "emote_v2.safetensors", "strength": 0.8} in (payload.get("loras") or []), "the set LoRA reaches the render")
check("standing naturally upright" not in payload["prompt"], "no fixed set pose in the prompt")

print("E a set switch drops the cache")


def fill_cache():
    folder = er._get_expressions_dir("demo")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "demo_a.png").write_bytes(b"png")
    (folder / "demo_a.json").write_text("{}")
    return folder


apply_profile_update("demo", {"fields": {"expression_set": ""}})
folder = fill_cache()
apply_profile_update("demo", {"fields": {"expression_set": "humanoid"}})
check(len(list(folder.iterdir())) == 2, "Automatic -> its own set keeps the images")
apply_profile_update("demo", {"fields": {"expression_set": "emote"}})
check(len([p for p in folder.iterdir() if p.is_file()]) == 0, "humanoid -> emote drops the images")

print("G import")
LINES = ("0 | Frustrated | make the woman frustrated\n38 | Lip Bite | make the woman bite her lip\n"
         "74 | LipBite | make the woman lip-bite\nNeutral | make the woman neutral\n")
r = es.import_entries("emote", LINES)
cat = es.catalog_snapshot()
check(r["created"] == 3 and r["skipped"] == ["Neutral"], f"3 created, Neutral skipped ({r})")
check({"emote_frustrated", "emote_lip_bite", "emote_lipbite"} <= set(cat.sets["emote"].members), "keys are set_label-slug")
check(cat.entries["emote_lip_bite"]["prompt"] == "make the woman bite her lip", "prompt taken verbatim")
check([cat.entries[k]["synonyms"] for k in ("emote_frustrated", "emote_lip_bite", "emote_lipbite")]
      == [("frustrated",), ("lip bite",), ("lipbite",)], "label is the synonym")
again = es.import_entries("emote", LINES)
check(again["created"] == 0 and len(again["skipped"]) == 4, "a repeated import creates nothing")
before = es.catalog_snapshot().revision
try:
    es.import_entries("emote", "1 | Happy | make the woman happy\njust text")
    check(False, "a malformed line must reject the import")
except es.ExpressionSetError:
    check(es.catalog_snapshot().revision == before and "emote_happy" not in es.catalog_snapshot().entries,
          "a malformed line rejects the whole import")

print("F LoRA fit on the character's expression backend")
from app.routes import characters as char_routes  # noqa: E402
route = SimpleNamespace(backend=SimpleNamespace(name="Qwen", lora_filter=""))
for associated, expected in ((["emote_v2.safetensors"], True), ([], False)):
    with patch("app.imagegen.routing.resolve_image_route", lambda *a, **k: route), \
            patch("app.core.config.get_lora_options",
                  lambda name, lora_filter="", _a=associated: [{"name": n} for n in _a]):
        backend, fit = char_routes._expression_lora_fit("demo", es.catalog_snapshot().sets.values())
    check(backend == "Qwen" and fit.get("emote") is expected, f"emote fit is {expected} (got {fit.get('emote')})")
    check(fit.get("humanoid") is None, "a set without LoRA reports no fit")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("PASS expression sets carry one LoRA, no fixed pose")
