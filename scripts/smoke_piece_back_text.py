#!/usr/bin/env python3
"""Smoke: the optional back description of an outfit piece (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 11e,
Ruling V1 as amended: "hinten ist optional", "du setzt die Rückseite für
alle").

Usage:
    ./.venv/bin/python scripts/smoke_piece_back_text.py

Runs without a server, a hub or an LLM: a temp world (``paths.init`` first),
the shared item library redirected to a temp file
(``inventory._get_shared_items_file``) so the tracked
``shared/items/items.json`` is never read or written, and
``llm_router.llm_call`` stubbed (it records every call).

Fixture (neutral wording): "Grey Blazer", outfit piece, slots [top], mode
own_mesh, front text F = "grey tailored blazer, deep neckline, three front
buttons, office setting" (69 characters, below ``FIT_FRAGMENT_MAX`` 120, so
``fit_text`` keeps it whole); back text B = "grey tailored blazer".

Expected values, derived by hand from the code's constants:

[1] ``update_item`` keeps the field cleaned: " grey tailored blazer. " is
    stored "grey tailored blazer" (whitespace collapsed, no trailing full
    stop); "" drops the key; a non-outfit item ("tool") never keeps it.
[2] Empty field — the front text everywhere, as before:
    ``back_text`` = ``view_text(back|left|right|side)`` = F; the fit =
    "edit the first image with the clothes from the second image: the
    person wears only F, add no other clothing beyond that, the rest of the
    body stays exactly as in the first image; a back view seen from behind,
    the back view stays a back view"; keywords "back view, seen from
    behind, F, only these clothes, no other clothing, body unchanged from
    the first image"; the draft says "wearing only F exactly as on the
    person in the reference image"; ``fsig_inputs`` has no
    ``prompt_fragment_back`` key.
[3] Field B — the back wins, the front stays byte for byte: the fit says
    "wears only grey tailored blazer, add no other clothing" and not "deep
    neckline"; the draft "wearing only grey tailored blazer exactly as on
    the person"; ``view_text(left)`` = ``view_text(side)`` = B,
    ``view_text(front)`` = F; ``fsig_inputs[prompt_fragment_back]`` = B
    and the fsig differs from [2]'s. The worn FRONT edit = "Keep the image
    exactly as it is. Only change their clothing: they now wear only F."
    and the ghost FRONT = ``GHOST`` with noun "grey blazer" — identical with
    and without the field. The ghost BACK = ``GHOST_KEEP`` with side "seen
    from behind, the back view stays a back view" (sleeves, neck opening:
    no waistband piece). A field EQUAL to the front (F) keeps [2]'s fsig and
    inputs (the old keys).
[4] ``base_body.fit_prompt``: back = FIT_PROMPT + "; a back view seen from
    behind, the back view stays a back view", left = FIT_PROMPT + "; a left
    side profile view, the side view stays a side view", right likewise,
    front = FIT_PROMPT.
[5] Suggest (``routes.inventory.suggest_back_text_route``): the stub
    answers "CHANGE: yes\\nBACK: grey tailored blazer" -> {text: B, changed:
    True}, one call of task ``piece_back_text`` whose user prompt contains
    "Description: F"; "CHANGE: no" -> {text: "", changed: False}; the item
    is unchanged after both (nothing saved); an empty front -> 400 without
    a call; a raising LLM -> 502.
[6] ``parse_answer``: no CHANGE line -> None; "yes" without BACK -> None;
    a BACK of len(F words)=10 + 4 = 14 words -> None (cap +3); a BACK equal
    to the front in other case -> (False, "").
[7] Migration: world W1 (front "blue cotton shirt, open collar at the
    front, beach setting"; stub yes -> "blue cotton shirt"), W2 ("plain
    black trousers"; stub raises on run 1, answers no on run 2), W3 (field
    filled "red scarf" -> never asked), W4 (category tool -> never asked);
    shared S1 ("green wool coat, front pockets"; stub yes -> "green wool
    coat"), the shared file carrying ``note: "keep me"``.
    Run 1: W1 and S1 written, W2 empty, ``failed`` [W2], world
    "incomplete" (flag unset), shared "done" (marker set, note kept), every
    call at ``Priority.LOW``, three calls (W1, W2, S1). Run 2: one call (W2),
    W2 stays empty, world "done", flag set, shared "already". Run 3: None,
    no call; ``start_migration`` returns None.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []

F = "grey tailored blazer, deep neckline, three front buttons, office setting"
B = "grey tailored blazer"
VIEW = "a back view seen from behind, the back view stays a back view"
FIT_PROMPT = "edit the first image with what the person in the second image wears, and nothing else"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def fit(text: str) -> tuple:
    return (f"edit the first image with the clothes from the second image: the person wears only {text}, add no "
            f"other clothing beyond that, the rest of the body stays exactly as in the first image; {VIEW}",
            f"back view, seen from behind, {text}, only these clothes, no other clothing, body unchanged from the "
            f"first image")


class Reply:
    def __init__(self, content: str):
        self.content = content


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="piece-back-text-") as tmp:
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

        from app.models import inventory
        shared_file = root / "shared_items.json"
        shared_file.write_text(json.dumps({"items": [], "note": "keep me"}), encoding="utf-8")
        inventory._get_shared_items_file = lambda: shared_file

        from fastapi import HTTPException
        from app.core import base_body, garment_clothing, llm_router, piece_back_text as pbt
        from app.core import garment_store as gs
        from app.core.llm_queue import Priority
        from app.models.character import save_character_profile
        from app.routes import inventory as inv_route

        calls: list = []
        answers: dict = {}

        def fake_llm_call(task, system_prompt, user_prompt, **kw):
            calls.append({"task": task, "user": user_prompt, "priority": kw.get("priority")})
            front = user_prompt.split("Description: ", 1)[-1].strip()
            answer = answers.get(front)
            if isinstance(answer, Exception):
                raise answer
            if answer is None:
                raise RuntimeError(f"no stub answer for {front!r}")
            return Reply(answer)
        llm_router.llm_call = fake_llm_call

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        jid = inventory.add_item(name="Grey Blazer", category="outfit_piece", prompt_fragment=F,
                                 outfit_piece={"slots": ["top"], "outfit_types": ["casual"],
                                               "mesh_mode": "own_mesh"})["id"]

        def set_back(value):
            return inventory.update_item(jid, {pbt.FIELD: value})

        print("[1] the item field")
        check("cleaned", (set_back(" grey tailored blazer. ") or {}).get(pbt.FIELD), B)
        check("empty drops the key", pbt.FIELD in (set_back("") or {}), False)
        tool = inventory.add_item(name="Hammer", category="tool", prompt_fragment="holding a hammer")["id"]
        check("non-outfit never keeps it",
              pbt.FIELD in (inventory.update_item(tool, {pbt.FIELD: "a hammer"}) or {}), False)

        print("[2] empty field: the front text")
        item = inventory.get_item(jid)
        check("back_text", pbt.back_text(item), F)
        check("view texts", [pbt.view_text(item, v) for v in ("back", "left", "right", "side")], [F] * 4)
        check("fit", garment_clothing.fit_prompt("worn", item_id=jid), fit(F))
        draft = garment_clothing.draft_prompt("Demo", "worn", item_id=jid)[0]
        check("draft names the front text", f"wearing only {F} exactly as on the person in the reference image"
              in draft, True)
        inputs_empty = garment_clothing.fsig_inputs("Demo", jid)
        check("no back key", pbt.FIELD in inputs_empty, False)
        fsig_empty = gs.garment_fsig("Demo", jid)
        worn_front = garment_clothing.edit_prompt("Demo", "worn", "front", item_id=jid)
        ghost_front = garment_clothing.edit_prompt("Demo", "ghost", "front", item_id=jid)
        check("worn front", worn_front[0],
              f"Keep the image exactly as it is. Only change their clothing: they now wear only {F}.")
        check("ghost front", ghost_front[0], garment_clothing.GHOST.format(noun="grey blazer"))

        print("[3] field B: the back wins")
        set_back(B)
        item = inventory.get_item(jid)
        got_fit = garment_clothing.fit_prompt("worn", item_id=jid)
        check("fit", got_fit, fit(B))
        check("fit without the front-only words", "deep neckline" in got_fit[0] + got_fit[1], False)
        draft = garment_clothing.draft_prompt("Demo", "worn", item_id=jid)[0]
        check("draft names the back text", (f"wearing only {B} exactly as on the person" in draft,
                                            "neckline" in draft), (True, False))
        check("view texts", [pbt.view_text(item, v) for v in ("front", "back", "left", "side")], [F, B, B, B])
        inputs_b = garment_clothing.fsig_inputs("Demo", jid)
        check("inputs", (inputs_b.get("prompt_fragment"), inputs_b.get(pbt.FIELD)), (F, B))
        check("fsig differs", gs.garment_fsig("Demo", jid) != fsig_empty, True)
        check("worn front byte-identical", garment_clothing.edit_prompt("Demo", "worn", "front", item_id=jid),
              worn_front)
        check("ghost front byte-identical", garment_clothing.edit_prompt("Demo", "ghost", "front", item_id=jid),
              ghost_front)
        check("ghost back", garment_clothing.edit_prompt("Demo", "ghost", "back", item_id=jid)[0],
              garment_clothing.GHOST_KEEP.format(noun="grey blazer",
                                                 side="seen from behind, the back view stays a back view",
                                                 stance="the sleeves at exactly the same angle as in the image",
                                                 openings="the neck opening, sleeves and hem"))
        set_back(F)
        check("field equal to the front keeps the inputs", garment_clothing.fsig_inputs("Demo", jid), inputs_empty)
        check("... and the fsig", gs.garment_fsig("Demo", jid), fsig_empty)
        set_back("")

        print("[4] dressed fits name their view")
        check("fit prompts", [base_body.fit_prompt(v) for v in ("front", "back", "left", "right")],
              [FIT_PROMPT, f"{FIT_PROMPT}; {VIEW}",
               f"{FIT_PROMPT}; a left side profile view, the side view stays a side view",
               f"{FIT_PROMPT}; a right side profile view, the side view stays a side view"])

        print("[5] Suggest saves nothing")
        before = inventory.get_item(jid)
        answers[F] = "CHANGE: yes\nBACK: grey tailored blazer"
        del calls[:]
        check("suggest yes", inv_route.suggest_back_text_route({"prompt_fragment": F, "name": "Grey Blazer"}),
              {"text": B, "changed": True})
        check("one call", [(c["task"], f"Description: {F}" in c["user"]) for c in calls],
              [("piece_back_text", True)])
        answers[F] = "CHANGE: no"
        check("suggest no", inv_route.suggest_back_text_route({"prompt_fragment": F}), {"text": "", "changed": False})
        check("item unchanged", inventory.get_item(jid), before)
        del calls[:]
        for label, body, want in (("empty front", {"prompt_fragment": "  "}, 400),
                                  ("LLM fails", {"prompt_fragment": "unknown piece"}, 502)):
            try:
                inv_route.suggest_back_text_route(body)
                check(label, "no error", want)
            except HTTPException as e:
                check(label, e.status_code, want)
        check("no call for the empty front", len(calls), 1)

        print("[6] parse_answer")
        check("no CHANGE", pbt.parse_answer("grey blazer", F), None)
        check("yes without BACK", pbt.parse_answer("CHANGE: yes", F), None)
        check("overlong", pbt.parse_answer("CHANGE: yes\nBACK: " + " ".join(["word"] * 14), F), None)
        check("BACK equal to the front", pbt.parse_answer("CHANGE: yes\nBACK: " + F.upper(), F), (False, ""))

        print("[7] the one-time migration")
        w1_front, w2_front, s1_front = ("blue cotton shirt, open collar at the front, beach setting",
                                        "plain black trousers", "green wool coat, front pockets")
        w1 = inventory.add_item(name="Blue Shirt", category="outfit_piece", prompt_fragment=w1_front,
                                outfit_piece={"slots": ["top"]})["id"]
        w2 = inventory.add_item(name="Black Trousers", category="outfit_piece", prompt_fragment=w2_front,
                                outfit_piece={"slots": ["bottom"]})["id"]
        w3 = inventory.add_item(name="Red Scarf", category="outfit_piece", prompt_fragment="red scarf, knotted at "
                                "the front", outfit_piece={"slots": ["neck"]})["id"]
        inventory.update_item(w3, {pbt.FIELD: "red scarf"})
        shared_file.write_text(json.dumps({"items": [{"id": "s1", "name": "Green Coat", "category": "outfit_piece",
                                                      "prompt_fragment": s1_front,
                                                      "outfit_piece": {"slots": ["outer"]}}],
                                           "note": "keep me"}), encoding="utf-8")
        # The Grey Blazer of [1]-[5] answers "no" (it stays empty), the hammer is no outfit piece.
        answers.update({F: "CHANGE: no", w1_front: "CHANGE: yes\nBACK: blue cotton shirt",
                        w2_front: RuntimeError("provider down"), s1_front: "CHANGE: yes\nBACK: green wool coat"})
        del calls[:]
        out = pbt.migrate_once()
        asked = sorted(c["user"].split("Description: ", 1)[-1].strip() for c in calls)
        check("run 1 asked", asked, sorted([F, w1_front, w2_front, s1_front]))
        check("run 1 background priority", {c["priority"] for c in calls}, {Priority.LOW})
        check("run 1 written", (out or {}).get("written"), {w1: "blue cotton shirt", "s1": "green wool coat"})
        check("run 1 failed / scopes", ((out or {}).get("failed"), out.get("world"), out.get("shared")),
              ([w2], "incomplete", "done"))
        check("W1 field", inventory.get_item(w1).get(pbt.FIELD), "blue cotton shirt")
        check("W2 empty", pbt.FIELD in inventory.get_item(w2), False)
        check("blazer stays empty (same)", pbt.FIELD in inventory.get_item(jid), False)
        check("W3 kept", inventory.get_item(w3).get(pbt.FIELD), "red scarf")
        from app.models.world import get_world_setting
        check("world flag unset", get_world_setting(pbt.WORLD_FLAG), "")
        meta = inventory.get_shared_items_meta()
        check("shared marker + note", (bool(meta.get(pbt.SHARED_KEY)), meta.get("note")), (True, "keep me"))
        check("S1 field", (inventory.get_item("s1") or {}).get(pbt.FIELD), "green wool coat")

        answers[w2_front] = "CHANGE: no"
        del calls[:]
        out = pbt.migrate_once()
        check("run 2 asked", sorted(c["user"].split("Description: ", 1)[-1].strip() for c in calls),
              sorted([F, w2_front]))
        check("run 2 scopes", ((out or {}).get("world"), out.get("shared"), out.get("written")),
              ("done", "already", {}))
        check("W2 still empty", pbt.FIELD in inventory.get_item(w2), False)
        check("world flag set", bool(get_world_setting(pbt.WORLD_FLAG)), True)
        del calls[:]
        check("run 3 is a no-op", (pbt.migrate_once(), len(calls)), (None, 0))
        check("start_migration skips", pbt.start_migration(delay=0), None)

    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
