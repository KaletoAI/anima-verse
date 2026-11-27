#!/usr/bin/env python3
"""Smoke: quest authoring pipeline core (quest stage 3, Task 3).

Throwaway storage (``paths.init(<tmpdir>)`` BEFORE importing any world-DB
module), no server, no real LLM. ``llm_router.llm_call`` is monkeypatched with
a scripted stub recording ``(task, label, user_prompt)``.

Usage:
    ./.venv/bin/python scripts/smoke_quest_authoring.py

FIXTURE
    Locations:
      - "inn" ("Inn"), room "hall" ("Hall"), pos (0, 0).
      - "market" ("Market"), room "square" ("Square"), pos (30, 40) ->
        hypot(30, 40) == 50 m from "inn".
    Characters:
      - Ava: player avatar (user "demo", active_character "Ava") at inn/hall.
      - Bram: NPC giver at inn/hall.

WHAT FOLLOWS BY HAND
  (a) Admin happy path: draft prose, then valid json:quest (roles giver=character,
      place=location; step 0 condition at_place{place: "place"}; bindings
      giver->Bram, place->market) -> ok True, phase "done", calls ==
      ["quest_draft", "quest_structure"], bindings kept, quests.list_templates()
      == [], progress phases == ["draft", "structure", "validate", "done"].
  (b) Unknown type -> repaired: first structure answer uses condition type
      "no_such_type" (validate_template reports path "steps.0.condition.type",
      code "unknown_type", message "Unknown condition type 'no_such_type'"),
      repair answer is valid -> ok True, 3 calls ["quest_draft",
      "quest_structure", "quest_structure"], repair user prompt contains the gap
      line "- steps.0.condition.type: Unknown condition type 'no_such_type'".
  (c) Still broken after repair (auto mode, both structure answers use
      "no_such_type") -> ok False, issues contain code "unknown_type", phase
      "repair".
  (d) Prose answer without ```json:quest fence twice -> ok False, issues contain
      code "no_block".
  (e) Auto mode restrictions (repair repeats the same object):
      - non-empty start_condition -> ok False, issue code "not_allowed_auto" at
        "start_condition".
      - create_prop in setup_effects -> ok False, issue code "not_allowed_auto"
        at "setup_effects.0.type".
  (f) dry_check:
      - auto mode with step-0 at_place bound to "inn" (where Ava already stands)
        -> ok False, issue code "already_true" at "steps.0.condition".
      - direct quest_engine.dry_check on the inn-bound template returns the same
        "already_true" issue; on the market-bound template returns [].
  (g) llm_call raising RuntimeError on draft -> ok False, code "llm_failed",
      phase "draft".
  (h) Admin mode drops an invalid proposed binding (place -> {"location_id":
      "nowhere"}) silently -> ok True, "place" not in bindings.
  (i) quest_context.build("Bram"): giver name "Bram" & location_id "inn",
      locations[0] starts with "inn", market line contains "50 m away",
      characters contain Ava with " (avatar)" and Bram with " (giver)",
      rendered catalog length <= MAX_CATALOG_CHARS, a line starting with
      "llm_judgement (condition, step only)" exists.
  (j) world_dev_tools no longer defines _quest_issue_blocks or
      MAX_QUEST_TEMPLATE_BYTES; quest_engine.blocking_issue({"path":
      "rewards.0.type", "code": "x"}) is True and
      quest_engine.blocking_issue({"path": "steps.0.text", "code": "required"})
      is False.
  (k) Admin mode with non-blocking issue + unparseable repair: structure answer
      is _valid_obj("market") with steps[0].text == "" (validate_template gives
      non-blocking issue path "steps.0.text", code "required"), repair answer is
      plain prose without a fence -> ok True, phase "done", template equals the
      first object's template, issues contain code "required" at "steps.0.text"
      and code "repair_unparsed" (message prefixed "The repair answer was
      unusable: ").
  (l) Admin mode with non-blocking issue + repair RuntimeError("down"): same
      first answer as (k), repair llm_call raises RuntimeError("down") -> ok
      False, phase "repair", issues contain both code "required" at
      "steps.0.text" and code "llm_failed".
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def _fence(obj: dict) -> str:
    return "```json:quest\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```"


def _valid_obj(place_loc: str = "market") -> dict:
    return {
        "template": {
            "title": "Walk to {place}",
            "summary": "{giver} wants you to visit {place}.",
            "gm_notes": "Smoke fixture quest.",
            "giver_role": "giver",
            "roles": [
                {"key": "giver", "kind": "character", "description": "Quest giver"},
                {"key": "place", "kind": "location", "description": "Destination"},
            ],
            "steps": [
                {
                    "id": "s1",
                    "text": "Go to {place}.",
                    "condition": {"type": "at_place", "params": {"place": "place"}},
                }
            ],
            "start_condition": {},
            "prerequisites": {},
            "setup_effects": [],
            "rewards": [],
            "time_limit_s": 0,
        },
        "bindings": {
            "giver": {"name": "Bram"},
            "place": {"location_id": place_loc},
        },
    }


def _scripted_llm(answers: list):
    queue = list(answers)
    calls: list[tuple[str, str, str]] = []

    def fake(task, system_prompt, user_prompt, **kwargs):
        calls.append((task, str(kwargs.get("label") or ""), str(user_prompt or "")))
        if not queue:
            raise AssertionError(f"unexpected extra llm_call #{len(calls)} for task={task}")
        nxt = queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return SimpleNamespace(content=nxt)

    return fake, calls


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-authoring-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)

    from app.core import (
        db,
        llm_router,
        quest_authoring,
        quest_context,
        quest_engine,
        quest_types,
        world_dev_tools,
    )
    from app.core.users import create_user, update_user
    from app.models import character as chars, quests, world

    db.init_schema()
    quest_types.register()

    world.upsert_location(
        {
            "id": "inn",
            "name": "Inn",
            "entry_room": "hall",
            "pos_x": 0.0,
            "pos_z": 0.0,
            "rooms": [{"id": "hall", "name": "Hall"}],
        },
        sync_world=False,
    )
    world.upsert_location(
        {
            "id": "market",
            "name": "Market",
            "entry_room": "square",
            "pos_x": 30.0,
            "pos_z": 40.0,
            "rooms": [{"id": "square", "name": "Square"}],
        },
        sync_world=False,
    )
    for name in ("Ava", "Bram"):
        assert chars.save_character_profile(
            name,
            {"current_location": "inn", "current_room": "hall"},
            create_new=True,
        ), name
    uid = create_user("demo", "smoke-password", allowed_characters=["Ava"])
    update_user(uid, settings={"active_character": "Ava"})

    # (a) Admin happy path
    print("(a) admin happy path")
    fake, calls = _scripted_llm(["Bram asks the hero to walk to the market.", _fence(_valid_obj("market"))])
    seen_phases: list[str] = []
    with patch.object(llm_router, "llm_call", fake):
        res_a = quest_authoring.generate(
            "Visit the market for Bram",
            giver="Bram",
            mode="admin",
            progress=seen_phases.append,
        )
    check("a. ok True", res_a["ok"] is True, str(res_a))
    check("a. phase done", res_a["phase"] == "done", str(res_a["phase"]))
    check("a. calls [quest_draft, quest_structure]", [c[0] for c in calls] == ["quest_draft", "quest_structure"], str(calls))
    check("a. bindings kept", res_a["bindings"] == {"giver": {"name": "Bram"}, "place": {"location_id": "market"}}, str(res_a["bindings"]))
    check("a. nothing written", quests.list_templates() == [], str(quests.list_templates()))
    check("a. progress phases", seen_phases == ["draft", "structure", "validate", "done"], str(seen_phases))

    # (b) Unknown type -> repaired
    print("(b) unknown type -> repaired")
    broken_unknown = _valid_obj("market")
    broken_unknown["template"]["steps"][0]["condition"] = {"type": "no_such_type", "params": {}}
    fake, calls = _scripted_llm([
        "Draft prose.",
        _fence(broken_unknown),
        _fence(_valid_obj("market")),
    ])
    with patch.object(llm_router, "llm_call", fake):
        res_b = quest_authoring.generate("Visit the market", giver="Bram", mode="admin")
    check("b. ok True after repair", res_b["ok"] is True, str(res_b))
    check("b. 3 calls", [c[0] for c in calls] == ["quest_draft", "quest_structure", "quest_structure"], str([c[0] for c in calls]))
    repair_prompt = calls[2][2] if len(calls) >= 3 else ""
    check(
        "b. repair prompt has gap line for unknown_type",
        "steps.0.condition.type: Unknown condition type 'no_such_type'" in repair_prompt,
        repair_prompt[:300],
    )

    # (c) Still broken after repair
    print("(c) still broken after repair")
    fake, calls = _scripted_llm([
        "Draft prose.",
        _fence(broken_unknown),
        _fence(broken_unknown),
    ])
    with patch.object(llm_router, "llm_call", fake):
        res_c = quest_authoring.generate("Visit the market", giver="Bram", avatar="Ava", mode="auto")
    check("c. ok False", res_c["ok"] is False, str(res_c))
    check("c. issues contain unknown_type", any(i.get("code") == "unknown_type" for i in res_c["issues"]), str(res_c["issues"]))
    check("c. phase repair", res_c["phase"] == "repair", str(res_c["phase"]))

    # (d) Prose answer without fence twice
    print("(d) prose answer without fence twice")
    fake, _calls = _scripted_llm(["Draft prose.", "Just prose, no fence.", "Still no fence."])
    with patch.object(llm_router, "llm_call", fake):
        res_d = quest_authoring.generate("Visit the market", giver="Bram", mode="admin")
    check("d. ok False", res_d["ok"] is False, str(res_d))
    check("d. issue code no_block", any(i.get("code") == "no_block" for i in res_d["issues"]), str(res_d["issues"]))

    # (e) Auto mode restrictions
    print("(e) auto mode restrictions")
    with_start = _valid_obj("market")
    with_start["template"]["start_condition"] = {"type": "at_place", "params": {"place": "place"}}
    fake, _calls = _scripted_llm(["Draft.", _fence(with_start), _fence(with_start)])
    with patch.object(llm_router, "llm_call", fake):
        res_e1 = quest_authoring.generate("Start cond test", giver="Bram", avatar="Ava", mode="auto")
    check("e1. ok False", res_e1["ok"] is False, str(res_e1))
    check(
        "e1. not_allowed_auto at start_condition",
        any(i.get("code") == "not_allowed_auto" and i.get("path") == "start_condition" for i in res_e1["issues"]),
        str(res_e1["issues"]),
    )

    with_prop = _valid_obj("market")
    with_prop["template"]["setup_effects"] = [
        {
            "key": "statue",
            "type": "create_prop",
            "params": {"name": "Stone Statue", "prompt": "a stone statue", "near": "place"},
        }
    ]
    fake, _calls = _scripted_llm(["Draft.", _fence(with_prop), _fence(with_prop)])
    with patch.object(llm_router, "llm_call", fake):
        res_e2 = quest_authoring.generate("Create prop test", giver="Bram", avatar="Ava", mode="auto")
    check("e2. ok False", res_e2["ok"] is False, str(res_e2))
    check(
        "e2. not_allowed_auto at setup_effects.0.type",
        any(i.get("code") == "not_allowed_auto" and i.get("path") == "setup_effects.0.type" for i in res_e2["issues"]),
        str(res_e2["issues"]),
    )

    # (f) dry_check
    print("(f) dry_check")
    already_true_obj = _valid_obj("inn")
    fake, _calls = _scripted_llm(["Draft.", _fence(already_true_obj), _fence(already_true_obj)])
    with patch.object(llm_router, "llm_call", fake):
        res_f = quest_authoring.generate("Stay at inn", giver="Bram", avatar="Ava", mode="auto")
    check("f. auto mode ok False", res_f["ok"] is False, str(res_f))
    check("f. issue code already_true", any(i.get("code") == "already_true" for i in res_f["issues"]), str(res_f["issues"]))
    direct_inn = quest_engine.dry_check(already_true_obj["template"], already_true_obj["bindings"], "Ava")
    check(
        "f. direct dry_check inn gives already_true",
        len(direct_inn) == 1 and direct_inn[0]["code"] == "already_true" and direct_inn[0]["path"] == "steps.0.condition",
        str(direct_inn),
    )
    market_obj = _valid_obj("market")
    direct_market = quest_engine.dry_check(market_obj["template"], market_obj["bindings"], "Ava")
    check("f. direct dry_check market gives []", direct_market == [], str(direct_market))

    # (g) llm_call raising RuntimeError on draft
    print("(g) llm_call RuntimeError on draft")
    fake, _calls = _scripted_llm([RuntimeError("provider offline")])
    with patch.object(llm_router, "llm_call", fake):
        res_g = quest_authoring.generate("Offline test", giver="Bram", mode="admin")
    check("g. ok False", res_g["ok"] is False, str(res_g))
    check("g. code llm_failed", any(i.get("code") == "llm_failed" for i in res_g["issues"]), str(res_g["issues"]))
    check("g. phase draft", res_g["phase"] == "draft", str(res_g["phase"]))

    # (h) Admin mode drops invalid binding silently
    print("(h) admin mode drops invalid proposed binding silently")
    bad_binding_obj = _valid_obj("nowhere")
    fake, _calls = _scripted_llm(["Draft.", _fence(bad_binding_obj)])
    with patch.object(llm_router, "llm_call", fake):
        res_h = quest_authoring.generate("Bad binding test", giver="Bram", mode="admin")
    check("h. ok True", res_h["ok"] is True, str(res_h))
    check("h. invalid binding dropped", "place" not in res_h["bindings"], str(res_h["bindings"]))

    # (i) quest_context.build("Bram")
    print("(i) quest_context.build('Bram')")
    ctx = quest_context.build("Bram")
    check("i. giver name Bram", (ctx["giver"] or {}).get("name") == "Bram", str(ctx["giver"]))
    check("i. giver location inn", (ctx["giver"] or {}).get("location_id") == "inn", str(ctx["giver"]))
    check("i. locations[0] starts with inn", bool(ctx["locations"]) and ctx["locations"][0].startswith("inn"), str(ctx["locations"]))
    market_line = next((ln for ln in ctx["locations"] if ln.startswith("market")), "")
    check("i. market line has 50 m away", "50 m away" in market_line, market_line)
    check("i. characters has Ava (avatar)", any("Ava" in ln and " (avatar)" in ln for ln in ctx["characters"]), str(ctx["characters"]))
    check("i. characters has Bram (giver)", any("Bram" in ln and " (giver)" in ln for ln in ctx["characters"]), str(ctx["characters"]))
    cat_text = "\n".join(ctx["catalog"])
    check("i. catalog length <= MAX_CATALOG_CHARS", len(cat_text) <= quest_context.MAX_CATALOG_CHARS, f"{len(cat_text)} > {quest_context.MAX_CATALOG_CHARS}")
    check(
        "i. catalog has llm_judgement (condition, step only)",
        any(ln.startswith("llm_judgement (condition, step only)") for ln in ctx["catalog"]),
        str([ln for ln in ctx["catalog"] if ln.startswith("llm_judgement")]),
    )

    # (j) Promoted helpers moved out of world_dev_tools into quest_engine
    print("(j) promoted helpers in quest_engine")
    check("j. world_dev_tools lacks _quest_issue_blocks", not hasattr(world_dev_tools, "_quest_issue_blocks"))
    check("j. world_dev_tools lacks MAX_QUEST_TEMPLATE_BYTES", not hasattr(world_dev_tools, "MAX_QUEST_TEMPLATE_BYTES"))
    check("j. blocking_issue rewards.0.type True", quest_engine.blocking_issue({"path": "rewards.0.type", "code": "x"}) is True)
    check("j. blocking_issue steps.0.text False", quest_engine.blocking_issue({"path": "steps.0.text", "code": "required"}) is False)

    # (k) Admin mode: non-blocking issue + unparseable repair keeps draft ok
    print("(k) admin mode: non-blocking issue + unparseable repair")
    missing_step_text = _valid_obj("market")
    missing_step_text["template"]["steps"][0]["text"] = ""
    fake, _calls = _scripted_llm(["Draft.", _fence(missing_step_text), "Plain prose without fence."])
    with patch.object(llm_router, "llm_call", fake):
        res_k = quest_authoring.generate("Missing step text test", giver="Bram", mode="admin")
    check("k. ok True", res_k["ok"] is True, str(res_k))
    check("k. phase done", res_k["phase"] == "done", str(res_k["phase"]))
    check("k. template preserved", res_k["template"] == missing_step_text["template"], str(res_k["template"]))
    check(
        "k. issues contain required at steps.0.text",
        any(i.get("code") == "required" and i.get("path") == "steps.0.text" for i in res_k["issues"]),
        str(res_k["issues"]),
    )
    check(
        "k. issues contain repair_unparsed",
        any(
            i.get("code") == "repair_unparsed"
            and str(i.get("message") or "").startswith("The repair answer was unusable: ")
            for i in res_k["issues"]
        ),
        str(res_k["issues"]),
    )

    # (l) Admin mode: repair RuntimeError preserves prior issues + llm_failed
    print("(l) admin mode: repair RuntimeError preserves prior issues")
    fake, _calls = _scripted_llm(["Draft.", _fence(missing_step_text), RuntimeError("down")])
    with patch.object(llm_router, "llm_call", fake):
        res_l = quest_authoring.generate("Repair error test", giver="Bram", mode="admin")
    check("l. ok False", res_l["ok"] is False, str(res_l))
    check("l. phase repair", res_l["phase"] == "repair", str(res_l["phase"]))
    check(
        "l. issues contain required at steps.0.text",
        any(i.get("code") == "required" and i.get("path") == "steps.0.text" for i in res_l["issues"]),
        str(res_l["issues"]),
    )
    check(
        "l. issues contain llm_failed",
        any(i.get("code") == "llm_failed" and "down" in str(i.get("message") or "") for i in res_l["issues"]),
        str(res_l["issues"]),
    )

    print()
    if FAILURES:
        print(f"FAIL smoke_quest_authoring: {len(FAILURES)}/{CHECKS} failed: {FAILURES}")
        return 1
    print(f"PASS smoke_quest_authoring: {CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
