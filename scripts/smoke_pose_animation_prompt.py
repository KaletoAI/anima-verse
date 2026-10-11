#!/usr/bin/env python3
"""Smoke the pure motion parser with hand-derived Task 6 expectations.

Usage: ./.venv/bin/python scripts/smoke_pose_animation_prompt.py
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.pose_animation_prompt import MotionPromptError, parse_motion_answer

BASE = {"segments": ["An object waves its right hand back and forth."], "loop": True}
ENTRY = {"key": "sweep", "prompt": "sweeping the floor", "synonyms":
         ["winken", "hand heben", "Hand Heben"], "group": "stand"}
checks = 0


def parse(data, mode="entry"):
    return parse_motion_answer(data if isinstance(data, str) else json.dumps(data),
        mode=mode, shared_groups={"stand", "seat"}, taken_aliases={"wave", "winken", "sitting"})


def reject(data, reason, mode="entry"):
    global checks
    try:
        parse(data, mode)
    except MotionPromptError as exc:
        assert reason in str(exc), (reason, str(exc))
    else:
        raise AssertionError(f"Expected rejection: {reason}")
    checks += 1


result = parse(BASE)
assert result.captions == BASE["segments"] and result.loop is True and result.entry is None
checks += 1
assert parse("```json\n" + json.dumps(BASE) + "\n```").captions == BASE["segments"]
checks += 1
reject({"error": "unsupported_motion", "reason": "no tail"}, "unsupported motion: no tail")
reject(dict(BASE, segments=["A man waves."]), "caption 1 must start with 'An object '")
reject(dict(BASE, segments=["An object waves.\nThen stops."]), "line break")
for segments in ([], ["An object moves."] * 4):
    reject(dict(BASE, segments=segments), "1..3 segments")
reject(dict(BASE, seed=1), "unknown field(s): seed")
reject(dict(BASE, entry={"seed": 1}), "unknown field(s): seed")
reject(dict(BASE, entry="x"), "entry missing or not an object")
result = parse(dict(BASE, entry=dict(ENTRY, key="wave", group="lie")))
assert result.captions == BASE["segments"] and result.loop is True and result.entry is None
checks += 1
reject(dict(BASE, loop="yes"), "loop must be a bool")
reject(BASE, "entry missing", "candidate")
for field, value, reason in (
    ("key", "wave", "key 'wave' already exists"),
    ("group", "lie", "unknown place type 'lie'"),
    ("prompt", "", "prompt must not be empty"),
    ("key", "Fegen Boden/x", "key must not contain '/'"),
):
    reject(dict(BASE, entry=dict(ENTRY, **{field: value})), reason, "candidate")
for mode in ("candidate", "free"):
    result = parse(dict(BASE, entry=ENTRY), mode)
    assert result.entry == dict(ENTRY, synonyms=["hand heben"])
    checks += 1
reject("not JSON", "invalid JSON")
reject(BASE, "unknown mode", "other")
reject(dict(BASE, segments=[42]), "caption 1 must be a string")
reject(dict(BASE, entry=dict(ENTRY, extra=1)), "unknown field(s): extra", "free")
reject(dict(BASE, entry=dict(ENTRY, synonyms="sweep")), "synonyms must be a list", "free")
print(f"{checks}/{checks} checks passed")
