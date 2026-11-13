#!/usr/bin/env python3
"""Ruling A29: an image edit that only CHANGES THE VIEW never names the clothing.

The user, 2026-11-13: "Beim Ansicht Ändern immer wieder die Kleidung in den Prompt zu nehmen, haben wir schon
mehrfach als Fehler identifiziert" — and "sorg dafür, dass es überall weg ist". A back or side view made from a
reference that already shows the figure takes the clothing from the reference: no outfit text, no
``prompt_fragment``, no piece or item name, no garment description. Ylva's own-mesh blouse, worn back draft
"… completely bald, wearing only cream off-shoulder linen blouse with corset lacing exactly as on the person …"
made the model invent a skirt on one try and culottes on another; the user's own test without the piece clause
gave the blouse alone, bare legs. That sentence is the only validated wording and is pinned byte for byte.

Usage:
    ./.venv/bin/python scripts/smoke_view_prompts_no_clothing.py

Runs without a server, a hub or an LLM: a temp world and instance (``paths.init`` before any world-DB import,
STORAGE_DIR / INSTANCE_DIR set to temp dirs), a copy of the ``human`` package, the shared item library redirected
to a temp file, the image service stubbed (it records the payload and renders nothing).

Fixture (neutral wording): character "Demo" (human, female, 30). Own-mesh pieces "Zebra Waistcoat" (top, fragment
"zebra-striped waistcoat with brass toggles", back text "zebra-striped waistcoat back with a buckle strap") and
"Teal Kilt" (bottom, "teal pleated kilt with a leather sporran"); painted pieces "Saffron Blouson" (top, "saffron
corduroy blouson with patch pockets") and "Mauve Trousers" (bottom, "mauve herringbone trousers"); an equipped
non-piece item "Cobalt Lantern" ("holding a cobalt lantern"). The forbidden words are every word of four letters
or more of those names and texts that is no generic word ("with", "back", "holding"; "leather" stays forbidden).
No fixture word is one of the generic garment terms a draft's negative forbids (``base_body.DRESS_GARMENT_NEGATIVE``:
"skirt", "jacket", … — they name what the piece is NOT, never the piece).

Expected values, derived by hand:

[1] The draft sentences (``base_body.DRAFT_PROMPTS``, ``base_body.draft_prompt``) — an outfit's dressed back/side
    and an own-mesh piece's worn back. back == VALIDATED (the user's sentence, verbatim). left / right ==
    VALIDATED with the turn clause "turned around, seen directly from behind, back view" replaced by "turned to a
    strict left|right side profile view" (the existing side turn); nothing else differs. No "{outfit}" slot
    remains; ``draft_prompt`` takes no outfit text (its signature has no ``outfit_text``) and
    ``DRAFT_OUTFIT_TEXT`` / ``garment_clothing.DRAFT`` are gone.
[2] ``garment_clothing.draft_prompt(Demo, worn, <piece>)`` for both own-mesh pieces: the prompt == VALIDATED; the
    negative carries no forbidden word.
[3] The T-pose extra views (``model_refs.generate_model_ref_images``, ``tpose_view`` back / left / right, the
    painted outfit + the lantern worn, a stored main render as their reference): the payload prompt and its
    appearances carry no forbidden word; ``clothed`` stays True (the style's fabric clause follows what is worn).
    Control: the MAIN render of the same outfit (no view change) names "saffron corduroy blouson" — the fixture
    really reaches the prompt, only the views drop it.
[4] The base views (``base_body.base_prompt`` back / left / right) == ``BASE_VIEW_PROMPTS`` — no clothing.
[5] Not view changes, kept as they are and pinned so a change is seen: the ghost is an edit of the WORN image of
    the same view (``garment_clothing.EDIT_STEPS["ghost"]["source"] == "worn"``; the ghost back is made from the
    worn back, not from the ghost front); the worn front edit names its piece ("they now wear only …").
[6] Lint (AST over ``app/core``): every module-level ``*_PROMPTS`` table and every string constant that words a
    view change (turned around / seen from behind / side profile view / …) belongs to a KNOWN owner — covered by
    a builder above or listed with the reason it is no character view change; no string constant carries an
    ``{outfit}`` / ``{fragment}`` placeholder except the worn FRONT edit (``garment_clothing.WORN``); no
    ``.format(outfit=…)`` call remains; among the shipped use cases, the ones whose texts word a character view
    change are the known ones, and the reachable T-pose view use cases tell an LLM never to describe the
    clothing.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []

VALIDATED = ("The same person turned around, seen directly from behind, back view, same A-pose, same framing, "
             "completely bald, exactly as on the person in the reference image, the same length, cut and colour, "
             "and nothing else, the whole figure from head to feet in the frame.")
BACK_TURN = "turned around, seen directly from behind, back view"
SIDE_TURN = "turned to a strict {side} side profile view"

OWN = {"Zebra Waistcoat": ("top", "zebra-striped waistcoat with brass toggles",
                           "zebra-striped waistcoat back with a buckle strap"),
       "Teal Kilt": ("bottom", "teal pleated kilt with a leather sporran", "")}
PAINTED = {"Saffron Blouson": ("top", "saffron corduroy blouson with patch pockets"),
           "Mauve Trousers": ("bottom", "mauve herringbone trousers")}
LANTERN = ("Cobalt Lantern", "holding a cobalt lantern")
#: Words of four letters or more that say nothing about a particular garment.
GENERIC = {"with", "back", "holding"}


def forbidden_words() -> set:
    texts = [n for n in OWN] + [t for spec in OWN.values() for t in spec[1:]]
    texts += list(PAINTED) + [spec[1] for spec in PAINTED.values()] + list(LANTERN)
    words = {w.lower() for text in texts for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 4}
    return words - GENERIC


FORBIDDEN = forbidden_words()


def named(text: str) -> list:
    """The forbidden words ``text`` contains (whole words, any case)."""
    return sorted(w for w in FORBIDDEN if re.search(rf"\b{w}\b", text or "", re.IGNORECASE))


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


# --- [6] the lint -------------------------------------------------------------------------------------------

VIEW_WORDS = re.compile(r"turned around|turned to a strict|turned sideways|turned to face|seen directly from "
                        r"behind|seen from behind|back view|side profile|seen exactly from the side|rear view",
                        re.IGNORECASE)
#: (file, owner) -> why it is covered. ``owner``: the module-level name the constant is assigned to, else the
#: function it stands in.
KNOWN_VIEW_OWNERS = {
    ("app/core/base_body.py", "DRAFT_PROMPTS"): "[1] the draft sentences — validated wording, no clothing",
    ("app/core/base_body.py", "BASE_VIEW_PROMPTS"): "[4] the base views — the bald unclothed body",
    ("app/core/base_body.py", "DRESS_VIEW"): ("no view change: opens a dressed edit OF the base view itself "
                                              "(same view; production dresses only the front, the back and the "
                                              "sides are drafts)"),
    ("app/core/model_refs.py", "TPOSE_BACK_PROMPT_DEFAULT"): "[3] T-pose back view: pose text, outfit layer off",
    ("app/core/model_refs.py", "TPOSE_SIDE_PROMPT_TEMPLATE"): "[3] T-pose side views: pose text, outfit layer off",
    ("app/core/model_refs.py", "ANIMAL_VIEW_PROMPT_DEFAULTS"): "[3] animal views: the same render path, outfit off",
    ("app/core/garment_clothing.py", "GHOST_SIDE"): "[5] no view change: the ghost edits the worn image of its view",
    ("app/core/footwear_source.py", "EMPTY_PROMPT"): ("not a character view: the empty shoe from its item image, "
                                                      "names no piece text"),
    ("app/core/view_prompts.py", "_VIEW_PREFIX"): "props and buildings: no clothing (they re-describe the object)",
    ("app/core/config.py", "_DEFAULT_IMAGE_USE_CASES"): "checked per use case below",
    ("app/core/config.py", "_NEG_TPOSE_SIDE"): "a negative prompt (views to avoid)",
    ("app/core/config.py", "_NEG_VIEW_SIDE"): "a negative prompt (views to avoid)",
    ("app/core/config_schema.py", "SECTIONS"): "admin field labels / descriptions",
    ("app/core/garment_gates.py", "hems_reason"): "a refusal message",
    ("app/core/garment_gates.py", "worn_hems_reason"): "a refusal message",
    ("app/core/model_overview.py", "BASE_VIEW_CHANGED"): "a UI note",
    ("app/core/model_overview.py", "_dressed_view_step"): "a UI note",
}
#: Module-level ``*_PROMPTS`` tables of app/core and what covers them.
KNOWN_PROMPT_TABLES = {
    ("app/core/base_body.py", "DRAFT_PROMPTS"): "[1]",
    ("app/core/base_body.py", "BASE_VIEW_PROMPTS"): "[4]",
    ("app/core/base_body.py", "OLDER_PROMPTS"): "a freshness note, no prompt",
    ("app/core/config.py", "KEY_AREA_PROMPTS"): "key-area renders, no view change",
}
#: The only string constants with an {outfit} / {fragment} placeholder: the worn FRONT edit (no view change).
KNOWN_PLACEHOLDERS = {("app/core/garment_clothing.py", "WORN")}
#: Shipped use cases whose texts word a CHARACTER view change, and why each is covered.
KNOWN_VIEW_USE_CASES = {
    "tpose_back": "[3] reachable: its instruction must say never to describe the clothing",
    "tpose_side": "[3] reachable: its instruction must say never to describe the clothing",
    "base_back": "no reader (the base views use base_view_back); the bald unclothed body",
    "base_side": "no reader (the base views use base_view_side); the bald unclothed body",
}
REACHABLE_VIEW_USE_CASES = ("tpose_back", "tpose_side")
_PLACEHOLDER = re.compile(r"\{(?:outfit|fragment)\}")
_CHARACTER = re.compile(r"\b(?:character|person|figure)\b", re.IGNORECASE)


def _scan(path: Path):
    """``(owner, text)`` of every non-docstring str constant in ``path``; plus the module-level names and the
    ``.format`` keyword names."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    constants, names, formats = [], [], []

    def walk(node, owner):
        for child in ast.iter_child_nodes(node):
            own = owner
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own = child.name
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and owner == "<module>":
                target = child.targets[0] if isinstance(child, ast.Assign) else child.target
                if isinstance(target, ast.Name):
                    own = target.id
                    names.append(target.id)
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and id(child) not in docstrings:
                constants.append((own, child.value))
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "format"):
                formats.extend((own, kw.arg) for kw in child.keywords if kw.arg)
            walk(child, own)
    walk(tree, "<module>")
    return constants, names, formats


def lint() -> None:
    print("[6] lint: view-change wording, *_PROMPTS tables, {outfit} placeholders in app/core")
    view_owners, tables, placeholders, outfit_formats = set(), set(), set(), []
    for path in sorted((ROOT / "app" / "core").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        constants, names, formats = _scan(path)
        for owner, text in constants:
            if VIEW_WORDS.search(text):
                view_owners.add((rel, owner))
            if _PLACEHOLDER.search(text):
                placeholders.add((rel, owner))
        tables.update((rel, n) for n in names if n.endswith("_PROMPTS"))
        outfit_formats.extend((rel, owner, arg) for owner, arg in formats if arg in ("outfit", "fragment")
                              and (rel, owner) not in KNOWN_PLACEHOLDERS)
    check("every view-change wording has a known owner", sorted(view_owners - set(KNOWN_VIEW_OWNERS)), [])
    check("no known owner went missing (update the list)", sorted(set(KNOWN_VIEW_OWNERS) - view_owners), [])
    check("every *_PROMPTS table is covered", sorted(tables - set(KNOWN_PROMPT_TABLES)), [])
    check("{outfit}/{fragment} placeholders: the worn front edit only", sorted(placeholders), sorted(KNOWN_PLACEHOLDERS))
    check("no .format(outfit=…/fragment=…) outside the worn front edit", outfit_formats,
          [("app/core/garment_clothing.py", "edit_prompt", "fragment")])
    from app.core.config import _DEFAULT_IMAGE_USE_CASES
    view_use_cases = sorted(
        name for name, families in _DEFAULT_IMAGE_USE_CASES.items()
        if any(VIEW_WORDS.search(str(fields.get(key) or "")) and _CHARACTER.search(str(fields.get(key) or ""))
               for fields in families.values() if isinstance(fields, dict)
               for key in ("prompt_style", "prompt_instruction")))
    check("use cases that word a character view change", view_use_cases, sorted(KNOWN_VIEW_USE_CASES))
    for name in REACHABLE_VIEW_USE_CASES:
        for family, fields in _DEFAULT_IMAGE_USE_CASES[name].items():
            instruction = fields.get("prompt_instruction") or ""
            check(f"{name}/{family}: the LLM never describes the clothing",
                  ("Never describe the clothing" in instruction, "head-to-toe" in instruction), (True, False))


# --- the fixture --------------------------------------------------------------------------------------------

class _Service:
    """The image service: records each payload, renders nothing."""
    enabled = True

    def __init__(self):
        self.payloads: list = []

    def generate_from_input(self, raw, **_kw):
        self.payloads.append(json.loads(raw))
        return ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="a29-view-prompts-") as tmp:
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
        lint()

        from app.models import inventory
        shared_file = root / "shared_items.json"
        shared_file.write_text(json.dumps({"items": []}), encoding="utf-8")
        inventory._get_shared_items_file = lambda: shared_file

        from PIL import Image
        from app.core import base_body, garment_clothing, model_refs
        from app.core.piece_back_text import FIELD
        from app.models.character import get_character_profile, save_character_profile

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        own = {}
        for name, (slot, front, back) in OWN.items():
            item = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=front,
                                      outfit_piece={"slots": [slot], "outfit_types": ["casual"],
                                                    "mesh_mode": "own_mesh"})
            if back:
                inventory.update_item(item["id"], {FIELD: back})
            own[name] = item["id"]
        painted = {slot: inventory.add_item(name=name, category="outfit_piece", prompt_fragment=text,
                                            outfit_piece={"slots": [slot], "outfit_types": ["casual"]})["id"]
                   for name, (slot, text) in PAINTED.items()}
        lantern = inventory.add_item(name=LANTERN[0], category="tool", prompt_fragment=LANTERN[1])["id"]
        profile = get_character_profile("Demo")

        print("[1] the draft sentences")
        check("back sentence == the validated one", base_body.DRAFT_PROMPTS["back"], VALIDATED)
        for side in ("left", "right"):
            check(f"{side} sentence == the validated one with its turn",
                  base_body.DRAFT_PROMPTS[side], VALIDATED.replace(BACK_TURN, SIDE_TURN.format(side=side)))
        check("no {outfit} slot", [v for v, s in base_body.DRAFT_PROMPTS.items() if "{" in s], [])
        check("draft_prompt takes no outfit text",
              "outfit_text" in inspect.signature(base_body.draft_prompt).parameters, False)
        check("the old clothing texts are gone",
              (hasattr(base_body, "DRAFT_OUTFIT_TEXT"), hasattr(garment_clothing, "DRAFT")), (False, False))
        for view in ("back", "left", "right"):
            prompt, negative = base_body.draft_prompt("Demo", view, profile=profile)
            check(f"outfit draft {view} == its sentence", prompt, base_body.DRAFT_PROMPTS[view])
            check(f"outfit draft {view}: no garment word", named(prompt + " " + negative), [])
        check("outfit back draft == VALIDATED byte for byte", base_body.draft_prompt("Demo", "back",
                                                                                      profile=profile)[0], VALIDATED)

        print("[2] the worn back draft of an own-mesh piece")
        for name, item_id in own.items():
            prompt, negative = garment_clothing.draft_prompt("Demo", "worn", profile=profile, item_id=item_id)
            check(f"{name}: prompt == VALIDATED", prompt, VALIDATED)
            check(f"{name}: no garment word in prompt or negative", named(prompt + " " + negative), [])

        print("[3] the T-pose extra views (model_refs)")
        profile = {**get_character_profile("Demo"), "equipped_pieces": dict(painted),
                   "equipped_items": [lantern]}
        check("dress Demo", save_character_profile("Demo", profile), True)
        pieces, items, signature = model_refs.current_outfit_state("Demo")
        check("the outfit is worn", (sorted(pieces.values()), items), (sorted(painted.values()), [lantern]))
        refs = model_refs.get_model_refs_dir("Demo")
        refs.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 128), (90, 60, 40, 255)).save(refs / f"tpose_{signature}.png")
        service = _Service()
        import app.imagegen.service as image_service
        image_service.get_image_service = lambda: service
        base_body.is_base_pipeline = lambda *_a, **_k: False   # the whole-body T-pose path (temporary NPCs)
        for view in ("back", "left", "right"):
            service.payloads.clear()
            model_refs.generate_model_ref_images("Demo", kinds=("tpose",), pieces=pieces, items=items,
                                                 signature=signature, tpose_view=view)
            check(f"{view}: one render", len(service.payloads), 1)
            payload = service.payloads[0] if service.payloads else {}
            check(f"{view}: it is the view's", payload.get("image_use_case"), model_refs.TPOSE_VIEW_USE_CASES[view])
            check(f"{view}: no garment word in the prompt", named(payload.get("prompt", "")), [])
            check(f"{view}: none in the appearances", named(json.dumps(payload.get("appearances", []))), [])
            check(f"{view}: still clothed (fabric clause)", payload.get("clothed"), True)
        service.payloads.clear()
        model_refs.generate_model_ref_images("Demo", kinds=("tpose",), force=True, pieces=pieces, items=items,
                                             signature=signature, tpose_view="main")
        main_prompt = service.payloads[0].get("prompt", "") if service.payloads else ""
        check("control: the main render names the outfit",
              ("saffron corduroy blouson" in main_prompt, "cobalt lantern" in main_prompt), (True, True))

        print("[4] the base views")
        save_character_profile("Demo", {**profile, "equipped_pieces": {}, "equipped_items": []})
        for view in ("back", "left", "right"):
            prompt, negative = base_body.base_prompt("Demo", view)
            check(f"base {view}", (prompt, named(prompt + " " + negative)), (base_body.BASE_VIEW_PROMPTS[view], []))

        print("[5] not view changes, kept")
        check("the ghost edits the worn image of its own view", garment_clothing.EDIT_STEPS["ghost"]["source"],
              "worn")
        zebra = own["Zebra Waistcoat"]
        check("the worn front names its piece", garment_clothing.edit_prompt("Demo", "worn", "front", item_id=zebra)[0],
              "Keep the image exactly as it is. Only change their clothing: they now wear only "
              "zebra-striped waistcoat with brass toggles.")

    print(f"\n{len(FAILS)} failed" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
