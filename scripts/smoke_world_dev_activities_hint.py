#!/usr/bin/env python3
"""Smoke: World Dev location/room validation rejects 'activities' with an activity_hint pointer.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_activities_hint.py

Calls ``world_dev_tools._check_location_fields`` directly in a temp storage dir
(``paths.init`` and ``ANIMATION_CLIPS_DIR`` set before any world-DB import).

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
Activities are free text in Anima Verse (``activity_hint`` on a location or
room); ``activities`` is not a valid field.

1. ``{"activities": ["x"]}`` -> raises ``ToolRefusal`` whose message names
   ``'activity_hint'``.
2. ``{"rooms": [{"name": "A", "activities": ["x"]}]}`` -> raises ``ToolRefusal``
   whose message starts with ``"rooms[0]: "`` and names ``'activity_hint'``.
3. ``{"activity_hint": "baden"}`` -> accepted (no ``ToolRefusal``).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS_DIR = Path(tempfile.mkdtemp(prefix="smoke_wd_act_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_act_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS_DIR)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import world_dev_tools as wt  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def main():
    try:
        # 1. Location-level 'activities'
        msg1 = None
        try:
            wt._check_location_fields({"activities": ["x"]}, "patch")
        except wt.ToolRefusal as exc:
            msg1 = str(exc)
        check("location 'activities' refused with activity_hint",
              msg1 is not None and "'activity_hint'" in msg1, msg1)

        # 2. Room-level 'activities'
        msg2 = None
        try:
            wt._check_location_fields({"rooms": [{"name": "A", "activities": ["x"]}]}, "patch")
        except wt.ToolRefusal as exc:
            msg2 = str(exc)
        check("room 'activities' refused with rooms[0]: prefix and activity_hint",
              msg2 is not None and msg2.startswith("rooms[0]: ") and "'activity_hint'" in msg2,
              msg2)

        # 3. Valid 'activity_hint'
        err3 = None
        try:
            wt._check_location_fields({"activity_hint": "baden"}, "patch")
        except wt.ToolRefusal as exc:
            err3 = str(exc)
        check("location 'activity_hint' accepted", err3 is None, err3)
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS_DIR, ignore_errors=True)

    if failures:
        print(f"FAIL ({len(failures)} failed): {', '.join(failures)}")
        sys.exit(1)
    print("PASS (3/3 checks)")


if __name__ == "__main__":
    main()
