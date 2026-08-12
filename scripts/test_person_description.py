"""Standalone check: ONE person-description composition for renders + previews.

Run: ./.venv/bin/python scripts/test_person_description.py
No server — throwaway world, data sources stubbed.

Contract (user directive 2026-07-29): every path that describes a person for
an image prompt — PromptBuilder (expression variants, chat images), the scene
render / scene photo person text, and every prompt preview — runs through
prompt_builder.person_description. A preview therefore always shows what the
render would send; the composers cannot drift apart again.
"""
import sys
import tempfile

sys.path.insert(0, ".")

CHAR = "Demo"


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="anima_person_desc_check_")
    from app.core import paths, db
    paths.init(tmp)
    db.init_schema()

    import app.models.character as character
    import app.core.body_slots as body_slots
    import app.core.outfit_renderer as outfit_renderer
    import app.core.prompt_filters as prompt_filters
    from app.core.prompt_builder import PromptBuilder, person_description
    from app.core.scene_render import _appearance_text

    orig = (character.get_character_appearance, body_slots.appearance_suffix,
            outfit_renderer.render_outfit, prompt_filters.collect_image_modifiers)
    character.get_character_appearance = lambda n: "43 year old man,\n  neat hair"
    body_slots.appearance_suffix = lambda n, **kw: "hazel eyes"
    outfit_renderer.render_outfit = lambda **kw: {"full": "wearing: blue t-shirt"}
    prompt_filters.collect_image_modifiers = lambda n, loc="": ([("neat hair", "messy tousled hair")], ["tired eyes"])
    try:
        base = person_description(CHAR)
        check("composition: appearance + slots + modifiers",
              base == "43 year old man, messy tousled hair, hazel eyes, tired eyes")
        check("whitespace collapsed", "\n" not in base)

        pb = PromptBuilder(CHAR).detect_persons("", character_names=[CHAR])
        check("PromptBuilder appearance == person_description",
              bool(pb) and pb[0].appearance == base)
        check("neutral render skips modifiers",
              PromptBuilder(CHAR, apply_state_modifiers=False)
              .detect_persons("", character_names=[CHAR])[0].appearance
              == "43 year old man, neat hair, hazel eyes")

        scene = _appearance_text(CHAR)
        check("scene text == person_description(include_outfit=True)",
              scene == person_description(CHAR, include_outfit=True))
        check("scene text carries the outfit", "blue t-shirt" in scene)
        check("modifiers apply over outfit-inclusive text", "tired eyes" in scene)

        # A replacement may rewrite outfit text in the scene composition ...
        prompt_filters.collect_image_modifiers = lambda n, loc="": ([("blue t-shirt", "torn t-shirt")], [])
        check("scene: replacement reaches outfit text",
              "torn t-shirt" in _appearance_text(CHAR))
        # ... but not in the outfit-less variant composition (outfit is a
        # separate prompt segment there).
        check("no-outfit composition untouched by outfit replacement",
              person_description(CHAR) == "43 year old man, neat hair, hazel eyes")
    finally:
        (character.get_character_appearance, body_slots.appearance_suffix,
         outfit_renderer.render_outfit, prompt_filters.collect_image_modifiers) = orig

    print("OK")


if __name__ == "__main__":
    main()
