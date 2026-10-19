#!/usr/bin/env python3
"""Undressed free-text wardrobe: package undressed text, exposed slots, defaults.

Usage:
    ./.venv/bin/python scripts/smoke_free_text_undressed_slots.py

Runs against a THROWAWAY storage directory with ONE fixture package written to a
temporary plugins directory — no real world, no repo or private package, no
server. Every expectation is derived by hand from the fixture below and the
rules in ``app/core/body_slots.py`` / ``app/core/outfit_renderer.py``:

Fixture package ``fixture_body`` (apply_to npc-temporary + human-roleplay,
``undressed_prompt: "bare"``), one slot ``marking`` with ``covered_by: [top]``:
    shade: default {apply_to: [npc-temporary], value: ""}
    shape: default {apply_to: [npc-temporary], by: {gender: {female: ring, male: star}}}
    prompt: covered "{shade} collar", exposed "visible {shade} {shape} marking"

  [1] Dressed temporary NPC (outfit_worn "true", description "grey apron"):
      free text → "wearing: grey apron". A free-text wardrobe has no pieces, so
      the dressed state decides: covered. Covered fragment needs {shade}; the
      default only stands in for the EXPOSED fragment → dropped. general = [],
      exposed = []. undressed_line = "" (dressed).
  [2] Same NPC undressed (outfit_worn "false", the UI select's string): full =
      fallback = "bare" (package text replaces "no clothes"). Exposed: shade
      default "" (word vanishes), shape by gender female → ring:
      "visible  ring marking" squashed → "visible ring marking".
      undressed_line = "bare, visible ring marking" — the description
      "grey apron" appears nowhere.
  [3] gender "Male" (case-insensitive) → "visible star marking".
  [4] Stored values beat defaults: shade dark undressed → "visible dark star
      marking"; dressed → general ["dark collar"], exposed [].
  [5] Defaults are template-scoped: a human-roleplay character (outfit system,
      no pieces → exposed by the piece rule) WITHOUT values gets no default →
      shade missing → fragment dropped → exposed []. With shade dark + shape
      ring stored → "visible dark ring marking".
  [6] Editor payload (build_body_slots) of a stored undressed NPC: exposed True,
      attribute defaults shade "" and shape "ring"; the roleplay character's
      defaults are None.
  [7] Image path (prompt_builder.person_description, include_outfit) of the
      stored undressed NPC: appearance "a sample person" + slot suffix + outfit
      → "a sample person, visible ring marking, bare".
  [8] undress/context.md undressed renders "Clothing state: bare, visible ring
      marking." and not the description.
  [9] Without the package: undressed → "no clothes", no fragments,
      undressed_line "no clothes".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


MANIFEST = {
    "name": "fixture_body",
    "apply_to": ["npc-temporary", "human-roleplay"],
    "undressed_prompt": "bare",
    "body_slots": [{
        "id": "marking",
        "covered_by": ["top"],
        "attributes": {
            "shade": {"type": "select", "options": ["pale", "dark"],
                      "default": {"apply_to": ["npc-temporary"], "value": ""}},
            "shape": {"type": "select", "options": ["star", "ring"],
                      "default": {"apply_to": ["npc-temporary"],
                                  "by": {"gender": {"female": "ring", "male": "star"}}}},
        },
        "prompt": {"covered": "{shade} collar", "exposed": "visible {shade} {shape} marking"},
    }],
}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="undressed-slots-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "fixture_body"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        (plugins / "fixture_body").mkdir(parents=True)
        (plugins / "fixture_body" / "plugin.yaml").write_text(json.dumps(MANIFEST))
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core.body_slots import prompt_fragments
        from app.core.outfit_renderer import free_text_outfit, render_outfit, undressed_line

        npc = {"template": "npc-temporary", "gender": "female",
               "outfit_description": "grey apron", "outfit_worn": "true"}
        print("[1] dressed temporary NPC")
        check("free text", free_text_outfit(npc), "wearing: grey apron")
        check("fragments", prompt_fragments("", profile=npc), {"general": [], "exposed": []})
        check("undressed line", undressed_line(profile=npc), "")

        print("[2] undressed temporary NPC")
        bare = {**npc, "outfit_worn": "false"}
        out = render_outfit(bare)
        check("full", out["full"], "bare")
        check("fallback", out["fallback"], "bare")
        check("fragments", prompt_fragments("", profile=bare),
              {"general": [], "exposed": ["visible ring marking"]})
        line = undressed_line(profile=bare)
        check("undressed line", line, "bare, visible ring marking")
        check("description left out", "grey apron" in line, False)

        print("[3] gender picks the default")
        check("male", prompt_fragments("", profile={**bare, "gender": "Male"})["exposed"],
              ["visible star marking"])

        print("[4] stored values beat defaults")
        valued = {**bare, "gender": "male", "body_slots": {"marking": {"shade": "dark"}}}
        check("undressed", prompt_fragments("", profile=valued),
              {"general": [], "exposed": ["visible dark star marking"]})
        check("dressed", prompt_fragments("", profile={**valued, "outfit_worn": True}),
              {"general": ["dark collar"], "exposed": []})

        print("[5] defaults are template-scoped")
        rp = {"template": "human-roleplay", "gender": "female"}
        check("roleplay without values", prompt_fragments("", profile=rp)["exposed"], [])
        rp_valued = {**rp, "body_slots": {"marking": {"shade": "dark", "shape": "ring"}}}
        check("roleplay with values", prompt_fragments("", profile=rp_valued)["exposed"],
              ["visible dark ring marking"])

        print("[6] editor payload")
        from app.models.character import save_character_profile
        check("NPC stored", save_character_profile(
            "sample", {**bare, "character_appearance": "a sample person"}, create_new=True), True)
        check("roleplay stored", save_character_profile("sample_rp", rp, create_new=True), True)
        from app.core.character_ops import build_body_slots
        slot = build_body_slots("sample")["slots"][0]
        check("exposed", slot["exposed"], True)
        check("defaults", {a["key"]: a["default"] for a in slot["attributes"]},
              {"shade": "", "shape": "ring"})
        rp_slot = build_body_slots("sample_rp")["slots"][0]
        check("roleplay defaults", {a["key"]: a["default"] for a in rp_slot["attributes"]},
              {"shade": None, "shape": None})

        print("[7] image path")
        from app.core.prompt_builder import person_description
        check("person description", person_description("sample", include_outfit=True),
              "a sample person, visible ring marking, bare")

        print("[8] undress context")
        import jinja2
        tpl = (ROOT / "plugins/undress/templates/llm/undress/context.md").read_text()
        text = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(tpl).render(
            mode="npc_scene", dressed=False, description="grey apron",
            undressed=undressed_line("sample"), verb="GetDressed", target_dressed=True,
            suggest_dressing=False, flags=[])
        check("clothing line", text.splitlines()[0], "Clothing state: bare, visible ring marking.")
        check("description left out", "grey apron" in text, False)

        print("[9] without the package")
        from app.plugins import registry
        registry.clear_registry()
        check("full", render_outfit(bare)["full"], "no clothes")
        check("fragments", prompt_fragments("", profile=bare), {"general": [], "exposed": []})
        check("undressed line", undressed_line(profile=bare), "no clothes")

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} — " + "; ".join(FAILS))
        return 1
    print("OK — undressed free-text wardrobe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
