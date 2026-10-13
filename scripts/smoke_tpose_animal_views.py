#!/usr/bin/env python3
"""P1 animal reference views, using temporary storage and render doubles.

Usage: ./.venv/bin/python scripts/smoke_tpose_animal_views.py

Derived by hand from plan-tier-animationen.md §4.4, P1 and E10:
each body form has three extra views; humanoid back/left/right default off,
animal front/back/right default on. Their union has four file kinds.
An animal full pass makes four images: one main plus three views, each
referencing main and routing through tpose_view. Selecting main or front
makes exactly one image and preserves the other three. Invalid body-form
views produce zero writes/renders. Migration copies one chain once, without
sharing its list, and preserves existing chains including an empty chain.
The new occasion adds one character-scoped route without runtime inheritance.
"""
import copy
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check(label, condition):
    assert condition, label
    print(f"PASS {label}")


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix="tpose-animal-") as tmp:
        paths.init(tmp)
        from app.core import config, expression_regen, model_refs as mr
        from app.models import character
        from app.imagegen import occasions, routing
        from app.core.character_ops import apply_outfit_imagegen

        profiles = {"animal": {}, "humanoid": {}}

        def save(name, profile):
            profiles[name] = copy.deepcopy(profile)
            return True

        refs = Path(tmp) / "characters" / "animal" / "model_refs"
        refs.mkdir(parents=True)
        calls = []

        def render(name, **kw):
            calls.append(kw)
            path = Path(str(kw["output_stem"]) + ".png")
            path.write_bytes(b"new")
            return path

        with (patch.object(mr, "is_humanoid", side_effect=lambda name: name == "humanoid"),
              patch.object(character, "get_character_profile", side_effect=lambda name: copy.deepcopy(profiles[name])),
              patch.object(character, "save_character_profile", side_effect=save),
              patch.object(expression_regen, "generate_expression_image", side_effect=render)):
            check("body-form views", mr.TPOSE_VIEWS_BY_BODY == {
                "humanoid": ("back", "left", "right"),
                "animal": ("front", "back", "right")})
            check("four extra file kinds", set(mr.VIEW_KINDS) == {
                "tpose_front", "tpose_back", "tpose_left", "tpose_right"})
            check("animal default on", mr.enabled_tpose_views("animal") == ("front", "back", "right"))
            check("humanoid default off", mr.enabled_tpose_views("humanoid") == ())
            for name, view in (("humanoid", "front"), ("animal", "left")):
                before = copy.deepcopy(profiles)
                try:
                    mr.set_view_kinds(name, {view: True})
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"{name} accepted {view}")
                check(f"{name} rejects {view} without writing", profiles == before)
                try:
                    mr.generate_model_ref_images(name, kinds=("tpose",), force=True,
                        pieces={}, items=[], signature="sig", tpose_view=view)
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid render view accepted")
                check(f"{name} invalid view never renders", not calls)
            check("animal partial toggle keeps default views", mr.set_view_kinds("animal", {"back": False}) == {
                "front": True, "back": False, "right": True})
            mr.set_view_kinds("animal", {"back": True})
            mr.generate_model_ref_images("animal", kinds=("tpose",), force=True,
                pieces={}, items=[], signature="sig")
            main_image = refs / "tpose_sig.png"
            check("four animal images", len(calls) == 4 and [Path(c["output_stem"]).name for c in calls] ==
                ["tpose_sig", "tpose_front_sig", "tpose_back_sig", "tpose_right_sig"])
            check("main occasion and pose", calls[0]["occasion"] == "tpose" and
                calls[0]["prompt_prefix"] == mr.ANIMAL_POSE_PROMPT_DEFAULT and
                calls[0]["image_use_case"] == "tpose_animal")
            check("all animal views reference main and use new occasion", all(
                c["reference_image"] == main_image and c["occasion"] == "tpose_view" and
                c["image_use_case"] == "tpose_animal_view" for c in calls[1:]))
            check("animal view prompts used verbatim", [c["prompt_prefix"] for c in calls[1:]] ==
                [mr.ANIMAL_VIEW_PROMPT_DEFAULTS[v] for v in ("front", "back", "right")])
            files = {v: refs / ("tpose_sig.png" if v == "main" else f"tpose_{v}_sig.png")
                     for v in ("main", "front", "back", "right")}
            for selected in ("main", "front", "back", "right"):
                for file in files.values():
                    file.write_bytes(b"old")
                calls.clear()
                result = mr.generate_model_ref_images("animal", kinds=("tpose",), force=True,
                    pieces={}, items=[], signature="sig", tpose_view=selected)
                check(f"{selected} replaces exactly one image", len(calls) == 1 and all(
                    file.read_bytes() == (b"new" if v == selected else b"old") for v, file in files.items()))
                check(f"{selected} returns correct file kind", set(result) == {
                    "tpose" if selected == "main" else f"tpose_{selected}"})
            with patch.object(mr, "current_outfit_state", return_value=({}, [], "sig")):
                info = mr.get_model_refs_info("animal")
                check("animal info exposes three enabled views", list(info["views"]) == ["front", "back", "right"] and
                    all(v["enabled"] and v["info"] for v in info["views"].values()))
                from app.routes import characters as routes
                from fastapi import HTTPException
                with (patch.object(routes, "get_character_dir", return_value=refs.parent),
                      patch.object(mr, "trigger_now") as trigger):
                    for view in ("main", "front", "back", "right"):
                        request = SimpleNamespace(json=AsyncMock(return_value={"view": view, "kinds": ["tpose"]}))
                        asyncio.run(routes.generate_character_model_refs("animal", request))
                        check(f"API selects animal {view}", trigger.call_args.kwargs["tpose_view"] == view)
                    for name, view in (("humanoid", "front"), ("animal", "left")):
                        request = SimpleNamespace(json=AsyncMock(return_value={"view": view}))
                        try:
                            asyncio.run(routes.generate_character_model_refs(name, request))
                        except HTTPException as exc:
                            check(f"API rejects {name} {view}", exc.status_code == 422)
                        else:
                            raise AssertionError("invalid API view accepted")
                        try:
                            routes._set_character_model_refs_views_sync(name, {view: True})
                        except HTTPException as exc:
                            check(f"toggle API rejects {name} {view}", exc.status_code == 422)
                        else:
                            raise AssertionError("invalid API toggle accepted")
                    main_image.unlink()
                    request = SimpleNamespace(json=AsyncMock(return_value={"view": "front"}))
                    try:
                        asyncio.run(routes.generate_character_model_refs("animal", request))
                    except HTTPException as exc:
                        check("API requires main before animal front", exc.status_code == 409)
                    else:
                        raise AssertionError("API accepted missing main")

            occ = occasions.get_occasion("tpose_view")
            check("new character occasion", occ["character_scoped"] and
                occ["char_spec_field"] == "tpose_view_workflow" and occ["char_spec_fallback"] == "" and
                occ["style_use_cases"] == ["tpose_back", "tpose_side", "tpose_animal_view"])
            check("view styles removed from main occasion", not set(occ["style_use_cases"]) &
                set(occasions.get_occasion("tpose")["style_use_cases"]))
            profiles["animal"]["outfit_imagegen"] = {"workflow": "Normal*", "tpose_workflow": "Main*"}
            with patch.object(config, "get", return_value={"tpose": ["MainChain*"]}):
                check("views never inherit main pick or chain", routing.chain_for("tpose_view", "animal") == [])
                response = apply_outfit_imagegen("animal", {"tpose_view_workflow": "Views*"})
                check("view pick persists and resolves", response["tpose_view_workflow"] == "Views*" and
                    routing.chain_for("tpose_view", "animal") == [("Views*", "character", 0)])

        check("animal main pose exact", mr.ANIMAL_POSE_PROMPT_DEFAULT ==
            "full side view in profile facing the left edge of the frame, left flank facing the camera, standing square on all four legs, front paws side by side, hind paws side by side, legs vertical under the body, head in profile in line with the body, tail extended away from the body, mouth closed")
        check("no straight-leg prompt", all("legs straight" not in p and "straight and clearly apart" not in p
            for p in [mr.ANIMAL_POSE_PROMPT_DEFAULT, *mr.ANIMAL_VIEW_PROMPT_DEFAULTS.values()]))
        for view in ("front", "back", "right"):
            with patch.object(mr, "_cfg", side_effect=lambda key, default: "custom" if key == f"animal_{view}_prompt" else default):
                check(f"{view} admin override", mr.get_animal_view_prompt(view) == "custom")
        for family in ("natural", "keywords"):
            styles = config._DEFAULT_IMAGE_USE_CASES
            animal = styles["tpose_animal"][family]
            extra = styles["tpose_animal_view"][family]
            check(f"{family} animal styles and shadow negatives", extra["prompt_style"] == animal["prompt_style"] and
                "three-quarter" not in animal["prompt_style"] and "perpendicular to the body" in animal["prompt_style"] and
                extra["prompt_negative"] == config._NEG_TPOSE_ANIMAL + ", cast shadow, drop shadow, shadow on the floor")
        seeded = {"image_generation": {"use_cases": {"tpose_animal": {"styles": {}}}}}
        config._seed_default_use_cases(seeded)
        check("existing world backfills animal view styles", set(seeded["image_generation"]["use_cases"]["tpose_animal_view"]["styles"]) == {"natural", "keywords"})
        cfg = {"image_generation": {"routing": {"tpose": ["Qwen*", "Flux*", "Qwen*"]}}}
        check("migration copies exactly", config._migrate_tpose_view_routing(cfg) and
            cfg["image_generation"]["routing"]["tpose_view"] == ["Qwen*", "Flux*", "Qwen*"])
        cfg["image_generation"]["routing"]["tpose"].append("Changed*")
        check("migration runs once with independent list", not config._migrate_tpose_view_routing(cfg) and
            cfg["image_generation"]["routing"]["tpose_view"] == ["Qwen*", "Flux*", "Qwen*"])
        for chain in ([], ["Existing*"]):
            cfg = {"image_generation": {"routing": {"tpose": ["Main*"], "tpose_view": chain}}}
            check(f"migration preserves existing {chain}", not config._migrate_tpose_view_routing(cfg) and
                cfg["image_generation"]["routing"]["tpose_view"] == chain)
        cfg = {"image_generation": {"routing": {"tpose": ["Main*"]}}}
        config._apply_file_migrations(cfg)
        check("migration wired into load pipeline", cfg["image_generation"]["routing"]["tpose_view"] == ["Main*"])
        from app.core import config_scope
        stored = config_scope.prune(cfg)
        stored = json.loads(json.dumps(stored))
        stored["image_generation"]["routing"]["tpose"] = ["Later*"]
        check("saved migration stays independent after reload", not config._migrate_tpose_view_routing(stored) and
            stored["image_generation"]["routing"]["tpose_view"] == ["Main*"])
        root = Path(__file__).resolve().parents[1]
        translations = json.loads((root / "shared/languages/de.json").read_text())["translations"]
        check("new UI strings have German translations", all(translations.get(key) for key in (
            "Main view", "Front view", "Back view", "Right view",
            "T-pose views backend match (glob)", "Empty: T-pose views chain")))
        print("all checks passed")


if __name__ == "__main__":
    main()
