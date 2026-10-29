#!/usr/bin/env python3
"""Smoke: image overflow configuration and shared types (Task 1).

Usage: ./.venv/bin/python scripts/smoke_image_overflow_config.py

EXPECTED (derived by hand from development_instructions/plan-image-overflow.md):
C1 With SKILL_IMAGEGEN_1_ACCEPTS_OVERFLOW absent, the default is False.
C2 With that key set to "true", the backend accepts overflow: True.
C3 With config.get stubbed to return {}, the threshold defaults to 90.0.
C4 A stored threshold of 0 disables overflow: 0.0 seconds.
C5 A stored threshold of -5 is clamped to 0.0 seconds.
C6 A fresh context has no watch: OVERFLOW_WATCH.get() is None.
C7 The threshold schema default is 90; backend accepts_overflow defaults False.
C8 Exporting a backend dict with accepts_overflow=True produces a truthy
   SKILL_IMAGEGEN_1_ACCEPTS_OVERFLOW string through the real config bridge.

No server or network; storage and animation paths point only to temporary dirs.
"""
import contextvars
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    with tempfile.TemporaryDirectory(prefix="overflow-config-") as scratch:
        clips = Path(scratch) / "clips"
        clips.mkdir()
        with patch.dict(os.environ, {"ANIMATION_CLIPS_DIR": str(clips)}):
            from app.core import paths
            paths.init(Path(scratch) / "storage")

            from app.core import config
            from app.core.config_schema import SECTIONS, field_default
            from app.imagegen.base import (
                ChannelOverflow, ImageBackend, OVERFLOW_WATCH, OverflowWatch,
                image_overflow_after_seconds,
            )

            class Fake(ImageBackend):
                def check_availability(self):
                    return True

                def _generate(self, *args, **kwargs):
                    return [b"img"]

            def backend():
                return Fake("local", "http://unused", 1, "fake", "SKILL_IMAGEGEN_1_")

            def check(label, got, expected):
                assert got == expected, f"{label}: {got!r} != {expected!r}"
                print(f"OK {label}: {got!r}")

            os.environ.pop("SKILL_IMAGEGEN_1_ACCEPTS_OVERFLOW", None)
            check("C1 default backend flag", backend().accepts_overflow is False, True)
            os.environ["SKILL_IMAGEGEN_1_ACCEPTS_OVERFLOW"] = "true"
            check("C2 opted-in backend", backend().accepts_overflow is True, True)
            for label, stored, expected in (("C3", {}, 90.0), ("C4", 0, 0.0),
                                             ("C5", -5, 0.0)):
                with patch.object(config, "get", return_value=stored) as get:
                    check(label + " live threshold", image_overflow_after_seconds(), expected)
                    get.assert_called_once_with("image_generation.overflow_after_seconds", 90)
            check("C6 fresh context", contextvars.Context().run(OVERFLOW_WATCH.get), None)
            check("C7 threshold default", field_default("image_generation", "overflow_after_seconds"), 90)
            section = SECTIONS["image_generation"]
            check("C7 backend default", section["sub_arrays"]["backends"]["fields"]["accepts_overflow"]["default"], False)
            general = next(page for page in section["pages"] if page["id"] == "general")
            check("C7 general field order", general["fields"][:2], ["enabled", "overflow_after_seconds"])
            config._flatten_to_env({"image_generation": {"backends": [
                {"name": "cloud", "accepts_overflow": True},
            ]}})
            check("C8 real config export", os.environ.get("SKILL_IMAGEGEN_1_ACCEPTS_OVERFLOW", "").lower() in ("true", "1", "yes"), True)

            target = object()
            overflow = ChannelOverflow("local", 5.0, target)
            check("shared exception fields", (overflow.backend_name, overflow.waited_s, overflow.target), ("local", 5.0, target))
            watch = OverflowWatch("local", 90.0, lambda: target)
            token = OVERFLOW_WATCH.set(watch)
            try:
                check("shared watch", (OVERFLOW_WATCH.get() is watch, watch.backend_name, watch.after_s, watch.pick() is target), (True, "local", 90.0, True))
            finally:
                OVERFLOW_WATCH.reset(token)
            check("watch reset", OVERFLOW_WATCH.get(), None)
    print("all checks passed (C1-C8 and shared types)")


if __name__ == "__main__":
    main()
