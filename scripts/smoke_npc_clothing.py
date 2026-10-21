#!/usr/bin/env python3
"""Autonomous free-text clothing decisions, real tick/storage, injected LLM.

Usage: ./.venv/bin/python scripts/smoke_npc_clothing.py

Hand-derived contract: an explicit clothing action changes only outfit_worn
and preserves the described outfit; works alone in room and home-area modes
without a talk partner. A clothing turn never starts a walk. Narrating dressing
without an action is not dressing. A room move, unknown direction, disabled
skill, or stale action must not change clothing. Bathing may explicitly choose
undressing, but ordinary bathing prose does not toggle clothing or wetness.
No model, server, real world, animation clips or media generation is used.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="npc-clothing-") as tmp:
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    from app.core import config, db, embedding, npc_actions
    # Packages load only when the world enables them explicitly (ba172904).
    (Path(tmp) / "config.json").write_text(
        json.dumps({"packages": {"enabled": "undress"}}), encoding="utf-8")
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    # Rendering is external to the clothing transition under test.
    media = patch("app.core.npc_assets.submit_assets_job", return_value="")
    media.start()
    embedding.embed = lambda text: None
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(require_assets=False, conversation_mode="off")
    config.save(cfg, Path(tmp) / "config.json")
    from app.core.dependencies import get_skill_manager
    from app.core.npc_ops import apply_npc
    from app.core.keyed_lock import keyed_lock
    from app.core.outfit_renderer import render_outfit, is_outfit_worn
    from app.models.character import (get_character_profile, save_character_profile,
                                      save_character_skill_config)
    from app.models.world import add_location
    get_skill_manager()
    loc = add_location("Bathhouse", "A bathhouse.", rooms=[
        {"id": "hall", "name": "Hall", "description": "Reception.", "activity_hint": "working"},
        {"id": "bath", "name": "Bath", "description": "A bath.", "activity_hint": "bathing"}])
    name, description = "demo_npc", "a patched oilskin"
    apply_npc({"character_name": name, "character_appearance": "an innkeeper",
               "standing_task": "tends reception", "outfit_description": description},
              loc["id"], "hall", template="npc-temporary")

    def update(**fields):
        with keyed_lock("character_profile", name):
            p = get_character_profile(name)
            p.update(fields)
            assert save_character_profile(name, p)

    def turn(action=None, activity="Puts the oilskin back on.", room="hall", during=None):
        answer = {"room": room, "activity": activity, "pose": "standing"}
        if action is not None:
            answer["action"] = action
        def llm(**kwargs):
            if during:
                during()
            return SimpleNamespace(content=json.dumps(answer))
        return npc_actions.run_action_for(name, llm=llm)

    dress = {"type": "clothing", "dressed": True}
    undress = {"type": "clothing", "dressed": False}
    update(outfit_worn="false")
    result = turn(dress)
    assert result is not None, result
    assert is_outfit_worn(get_character_profile(name)), "Solo action tick must execute GetDressed"
    assert render_outfit(character_name=name)["full"] == f"wearing: {description}"
    assert get_character_profile(name)["outfit_description"] == description
    assert not get_character_profile(name).get("journey")

    update(outfit_worn=False)
    turn(activity="Puts the oilskin back on.")
    assert not is_outfit_worn(get_character_profile(name)), "Prose alone must not dress"
    turn(dress, room="bath")
    assert not is_outfit_worn(get_character_profile(name)), "Cannot dress and leave in one turn"
    turn({"type": "clothing", "dressed": "true"})
    assert not is_outfit_worn(get_character_profile(name)), "Only a JSON bool is a direction"
    save_character_skill_config(name, "get_dressed", {"enabled": False})
    turn(dress)
    assert not is_outfit_worn(get_character_profile(name)), "Disabled dressing is not executable"
    save_character_skill_config(name, "get_dressed", {"enabled": True})

    update(npc_home={"kind": "circle", "location_id": loc["id"],
                     "cx": 0, "cz": 0, "radius_m": 40}, outfit_worn=False)
    result = turn(dress)
    assert result is not None and is_outfit_worn(get_character_profile(name))
    assert not get_character_profile(name).get("journey"), "Dressing must not start the home walk"
    update(npc_home=None)
    turn(undress, activity="Bathes in the tub.")
    assert not is_outfit_worn(get_character_profile(name)), "Explicit bathing undress must apply"
    assert not get_character_profile(name).get("is_wet"), "Undressing is not EnterWater"
    update(outfit_worn=True)
    turn(activity="Bathes in the tub.")
    assert is_outfit_worn(get_character_profile(name)), "Bathing prose must not flip clothing"

    update(current_room="bath", outfit_worn=True)
    result = turn(undress, room="bath", during=lambda: update(current_room="hall"))
    assert result is None
    assert is_outfit_worn(get_character_profile(name)), "A stale bath action must not undress in the hall"
    update(npc_home={"kind": "circle", "location_id": loc["id"],
                     "cx": 0, "cz": 0, "radius_m": 40})
    from app.core.npc_pool import pool_npc
    result = turn(undress, during=lambda: pool_npc(name))
    assert result is None
    assert is_outfit_worn(get_character_profile(name)), "A pooled NPC must not execute a pending action"
    from app.models.character import set_character_status
    assert set_character_status(name, "")
    update(current_location=loc["id"], current_room="hall", npc_home=None)

    update(outfit_worn=False)
    result = turn(dress, during=lambda: update(outfit_worn=True))
    assert is_outfit_worn(get_character_profile(name))
    assert result is None, "An already reached direction must not report a new dressing action"
    # Removing the package and reloading while an answer is pending removes
    # the capability, including callbacks outside the skill manager's list.
    from app.plugins import loader
    empty_plugins = Path(tmp) / "empty-plugins"
    empty_plugins.mkdir()
    update(outfit_worn=True)
    def remove_package():
        with patch.object(loader, "PLUGIN_DIR", empty_plugins):
            get_skill_manager().reload_skills()
    turn(undress, during=remove_package)
    assert is_outfit_worn(get_character_profile(name)), "Removed package must not execute old callbacks"
    from app.core.hooks import emit
    blocks = []
    emit("character.prompt_context", character_name=name, mode="npc_action", blocks=blocks)
    assert blocks == [], "Removed package must contribute no prompt context"
    media.stop()
    print("PASS: room/home clothing actions, prose separation, disabled/malformed/stale guards")
