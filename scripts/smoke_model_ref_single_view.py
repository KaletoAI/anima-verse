#!/usr/bin/env python3
"""Check that regenerating one T-pose view preserves every other image.

Derived by hand: with four cached views, selecting back/left/right/main
must replace exactly that file, even with force=True and all views enabled.
A side view without a main must fail without producing any image. Rendering
is replaced at the external image boundary; file lookup and selection are real.
Storage is temporary and initialized before importing world modules.

Usage: ./.venv/bin/python scripts/smoke_model_ref_single_view.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix="model-ref-single-view-") as tmp:
        paths.init(tmp)
        from app.core import expression_regen, model_refs as mr

        refs = Path(tmp) / "characters" / "demo" / "model_refs"
        refs.mkdir(parents=True)
        files = {
            "main": refs / "tpose_sig.png",
            "back": refs / "tpose_back_sig.png",
            "left": refs / "tpose_left_sig.png",
            "right": refs / "tpose_right_sig.png",
        }

        def render(name, **kwargs):
            target = Path(str(kwargs["output_stem"]) + ".png")
            if target != files["main"]:
                assert kwargs["reference_image"] == files["main"]
                assert files["main"].read_bytes() == b"old-main"
            target.write_bytes(b"new")
            return target

        with (patch.object(mr, "is_humanoid", return_value=True),
              patch.object(mr, "enabled_tpose_views", return_value=("back", "left", "right")),
              patch.object(expression_regen, "generate_expression_image", side_effect=render)):
            for selected in ("back", "left", "right", "main"):
                for view, file in files.items():
                    file.write_bytes(f"old-{view}".encode())
                mr.generate_model_ref_images(
                    "demo", kinds=("tpose",), force=True, tpose_view=selected,
                    pieces={}, items=[], signature="sig")
                for view, file in files.items():
                    expected = b"new" if view == selected else f"old-{view}".encode()
                    assert file.read_bytes() == expected, (selected, view)
                print(f"ok: {selected} replaced alone")

            files["main"].unlink()
            before = {view: file.read_bytes() for view, file in files.items() if view != "main"}
            try:
                mr.generate_model_ref_images(
                    "demo", kinds=("tpose",), force=True, tpose_view="back",
                    pieces={}, items=[], signature="sig")
            except ValueError:
                pass
            else:
                raise AssertionError("A side view requires an existing main render")
            assert not files["main"].exists()
            assert {view: files[view].read_bytes() for view in before} == before
            print("ok: missing main refuses side regeneration without changing files")


if __name__ == "__main__":
    main()
