"""Standalone check: image-modifier state is part of the outfit cache key.

Run: ./.venv/bin/python scripts/test_state_signature.py
No server — throwaway world in a temp dir, image modifiers stubbed.

Contract (user decision 2026-07-29): reference renders and meshes are keyed
by outfit AND active image-modifier state (``<base>-s<fp>``), so a render
taken while e.g. "neat hair -> messy tousled hair" is triggered never claims
the neutral cache entry. Neutral state keeps the historic bare signature
(existing caches + outfit-batch pre-warm stay valid). Serving falls back to
the neutral entry while a state variant is unrendered; explicit-signature
lookups (generation skip-checks) stay exact. The cache GC judges state
variants by their outfit base.
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
    from app.core import paths, db
    paths.init(tmp)
    db.init_schema()

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
        check("neutral signature has no suffix", model_refs.STATE_SIG_SEP not in neutral)
        check("neutral_signature passthrough", model_refs.neutral_signature(neutral) == neutral)

        stub_modifiers(([("neat hair", "messy tousled hair")], []))
        _, _, stated = model_refs.current_outfit_state(CHAR)
        check("state signature = base + suffix",
              stated.startswith(neutral + model_refs.STATE_SIG_SEP) and len(stated) > len(neutral))
        check("neutral_signature strips suffix", model_refs.neutral_signature(stated) == neutral)

        stub_modifiers(([("neat hair", "messy tousled hair")], ["sweaty skin"]))
        _, _, stated2 = model_refs.current_outfit_state(CHAR)
        check("different state, different suffix", stated2 != stated and stated2.startswith(neutral))

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
              model_refs.find_ref_image(CHAR, "pose", stated) is None)
        check("explicit state signature stays exact (mesh)",
              find_model3d(CHAR, stated) is None)

        (char_dir / "model_refs" / f"pose_{stated}.png").write_bytes(b"x")
        (char_dir / "model3d" / f"{stated}.glb").write_bytes(b"x")
        check("rendered state variant wins over neutral (ref)",
              model_refs.find_ref_image(CHAR, "pose").name == f"pose_{stated}.png")
        check("rendered state variant wins over neutral (mesh)",
              find_model3d(CHAR).name == f"{stated}.glb")

        # -- expression variant cache ---------------------------------------
        from app.core.expression_regen import _cache_key

        stub_modifiers(([], []))
        key_neutral = _cache_key("happy", "reading", CHAR, {}, [])
        check("expr: neutral live key == explicit neutral key",
              key_neutral == _cache_key("happy", "reading", CHAR, {}, [], state_fp=""))

        stub_modifiers(([("neat hair", "messy tousled hair")], []))
        key_state = _cache_key("happy", "reading", CHAR, {}, [])
        check("expr: active state forks the key", key_state != key_neutral)
        check("expr: explicit neutral overrides live state",
              _cache_key("happy", "reading", CHAR, {}, [], state_fp="") == key_neutral)

        stub_modifiers(([], ["sweaty skin"]))
        key_state2 = _cache_key("happy", "reading", CHAR, {}, [])
        check("expr: different state, different key",
              key_state2 not in (key_neutral, key_state))

        # -- cache GC --------------------------------------------------------
        check("GC: reachable base keeps state variant",
              _entry_valid(f"{neutral}-sdeadbeef", None, set(), {neutral}))
        check("GC: unreachable base drops state variant",
              not _entry_valid("f00dfeedf00d-sdeadbeef", None, set(), {neutral}))
    finally:
        prompt_filters.collect_image_modifiers = orig

    print("OK")


if __name__ == "__main__":
    main()
