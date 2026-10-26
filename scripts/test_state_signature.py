"""Standalone check: neutral mesh/expression identity and stateful pose references.

Run: ./.venv/bin/python scripts/test_state_signature.py
No server — throwaway world, image modifiers supplied deterministically.

States change ordinary pose-reference signatures, not mesh or expression keys.
Existing mesh forks remain unreachable even when they are the only cached model.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

CHAR = "Demo"


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="anima_state_sig_check_")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / "instance")
    from app.core import db
    db.init_schema()
    from app.models.character import save_character_profile
    assert save_character_profile(CHAR, {"template": "human-default", "character_appearance": "neat hair"}, create_new=True)

    from app.core import prompt_filters
    from app.core import model_refs
    from app.core.model3d import find_model3d
    from app.core.outfit_cache_gc import _entry_valid
    from app.models.character import get_character_dir

    def stub_modifiers(directives):
        def fake(character_name, location_id=""):
            return directives
        prompt_filters.collect_image_modifiers = fake

    orig = prompt_filters.collect_image_modifiers
    try:
        # -- signature composition ------------------------------------------
        stub_modifiers(([], []))
        _, _, neutral = model_refs.current_outfit_state(CHAR)
        check("neutral signature has no suffix", "-s" not in neutral)
        check("neutral_signature passthrough", model_refs.neutral_signature(neutral) == neutral)

        stub_modifiers(([("neat hair", "messy tousled hair")], []))
        _, _, stated = model_refs.current_outfit_state(CHAR)
        check("mesh signature stays neutral", stated == neutral)
        stated_pose = model_refs.pose_reference_signature(CHAR, neutral)
        check("pose references retain state identity", stated_pose != neutral)
        check("neutral_signature strips pose suffix", model_refs.neutral_signature(stated_pose) == neutral)
        stub_modifiers(([("neat hair", "messy tousled hair")], ["bright colors"]))
        check("changed state keeps mesh signature", model_refs.current_outfit_state(CHAR)[2] == neutral)
        check("changed state changes pose signature", model_refs.pose_reference_signature(CHAR, neutral) != stated_pose)

        # Same directives in another trigger order → same fingerprint.
        stub_modifiers(([], ["sweaty skin", "messy tousled hair"]))
        fp_a = model_refs.state_fingerprint(CHAR)
        stub_modifiers(([], ["messy tousled hair", "sweaty skin"]))
        fp_b = model_refs.state_fingerprint(CHAR)
        check("fingerprint is order-stable", fp_a == fp_b and len(fp_a) == 8)

        # -- serving fallback ------------------------------------------------
        char_dir = get_character_dir(CHAR)
        (char_dir / "model_refs").mkdir(parents=True)
        (char_dir / "model3d").mkdir(parents=True)
        (char_dir / "model_refs" / f"pose_{neutral}.png").write_bytes(b"x")
        (char_dir / "model3d" / f"{neutral}.glb").write_bytes(b"x")

        stub_modifiers(([("neat hair", "messy tousled hair")], []))
        ref = model_refs.find_ref_image(CHAR, "pose")
        check("ref serving falls back to neutral",
              ref is not None and ref.name == f"pose_{neutral}.png")
        mesh = find_model3d(CHAR)
        check("mesh serving falls back to neutral",
              mesh is not None and mesh.name == f"{neutral}.glb")
        check("explicit state signature stays exact (ref)",
              model_refs.find_ref_image(CHAR, "pose", stated_pose) is None)
        check("explicit state signature stays exact (mesh)",
              find_model3d(CHAR, neutral + "-sdeadbeef") is None)

        (char_dir / "model_refs" / f"pose_{stated_pose}.png").write_bytes(b"x")
        (char_dir / "model3d" / f"{neutral}-sdeadbeef.glb").write_bytes(b"x")
        check("rendered state variant wins over neutral (ref)",
              model_refs.find_ref_image(CHAR, "pose").name == f"pose_{stated_pose}.png")
        check("mesh ignores rendered state fork",
              find_model3d(CHAR).name == f"{neutral}.glb")

        # Expressions are neutral, unlike the pose-reference images above.
        from app.core.expression_regen import expression_snapshot
        stub_modifiers(([], []))
        key_neutral = expression_snapshot(CHAR, "happy").stem
        stub_modifiers(([("neat hair", "messy tousled hair")], []))
        check("expression ignores replacement state", expression_snapshot(CHAR, "happy").stem == key_neutral)
        stub_modifiers(([], ["sweaty skin"]))
        check("expression ignores additive state", expression_snapshot(CHAR, "happy").stem == key_neutral)

        # -- cache GC --------------------------------------------------------
        check("GC: reachable base drops retired state variant",
              not _entry_valid(f"{neutral}-sdeadbeef", None, set(), lambda: {neutral}))
        check("GC: unreachable base drops state variant",
              not _entry_valid("f00dfeedf00d-sdeadbeef", None, set(),
                               lambda: {neutral}))
    finally:
        prompt_filters.collect_image_modifiers = orig

    print("OK")


if __name__ == "__main__":
    main()
