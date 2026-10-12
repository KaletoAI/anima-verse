#!/usr/bin/env python3
"""Smoke the pure motion parser with hand-derived Task 6 expectations.

Caption style (plan v3 Task 3): with prefix "A person " the parser accepts
"A person waves ..." and rejects "An object waves ..." with
"caption 1 must start with 'A person '"; the default prefix stays
"An object ". prepare_motion(caption_style="person", segment_seconds=4.0)
renders the template with caption_style "person", prefix "A person " and
segment_seconds 4.0 and validates against that prefix. The REAL template
rendered for "person"/4.0 names "A person " and "4-second", for the defaults
"An object " and "2-second", and never the other prefix.

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


def parse(data, mode="entry", **kwargs):
    return parse_motion_answer(data if isinstance(data, str) else json.dumps(data),
        mode=mode, shared_groups={"stand", "seat"}, taken_aliases={"wave", "winken", "sitting"},
        **kwargs)


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

# A world override must not hide the shared group from preparation or validation.
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
with tempfile.TemporaryDirectory() as tmp:
    from app.core import paths, pose_catalog, pose_catalog_edit, llm_router, prompt_templates
    paths.init(tmp)
    os.environ.update(ANIMATION_CLIPS_DIR=str(Path(tmp) / "clips"),
                     ANIMATION_CLIPS_LICENSED_DIR=str(Path(tmp) / "licensed"),
                     ANIMATION_CLIPS_INBOX_DIR=str(Path(tmp) / "inbox"))
    from app.core.pose_animation_prompt import prepare_motion
    shared = Path(tmp) / "pose.json"
    shared.write_text(json.dumps({"groups": {"stand": {"needs_place": False}}, "entries": {}}))
    rendered = []
    def render(task, **kwargs):
        rendered.append(kwargs)
        return "system", "user"
    original = pose_catalog.catalog_path
    with patch.object(pose_catalog, "catalog_path", side_effect=lambda axis: shared if axis == "pose" else original(axis)), \
         patch.object(pose_catalog, "get_groups", return_value={"stand": {"_store": "world"}, "world-only": {"_store": "world"}}), \
         patch.object(pose_catalog, "get_catalog", return_value={}), \
         patch.object(prompt_templates, "render_task", side_effect=render), \
         patch.object(llm_router, "llm_call", return_value=SimpleNamespace(content=json.dumps(dict(BASE, entry=ENTRY)))):
        assert prepare_motion("free", text="sweep").entry["group"] == "stand"
        assert rendered[0]["groups"] == "stand"
        assert rendered[0]["caption_style"] == "object" and rendered[0]["prefix"] == "An object "
        assert rendered[0]["segment_seconds"] == 2.0
print("PASS shared group remains eligible under a world override")

PERSON = {"segments": ["A person waves its right hand back and forth."], "loop": True}
assert parse(PERSON, prefix="A person ").captions == PERSON["segments"]
try:
    parse(BASE, prefix="A person ")
except MotionPromptError as exc:
    assert "caption 1 must start with 'A person '" in str(exc), str(exc)
else:
    raise AssertionError("object caption accepted for the person style")
try:
    parse(PERSON)
except MotionPromptError as exc:
    assert "'An object '" in str(exc)
else:
    raise AssertionError("person caption accepted for the default style")
print("PASS caption prefix follows the style")

with tempfile.TemporaryDirectory() as tmp:
    from app.core import paths, pose_catalog, llm_router, prompt_templates
    paths.init(tmp)
    shared = Path(tmp) / "pose.json"
    shared.write_text(json.dumps({"groups": {"stand": {"needs_place": False}}, "entries": {}}))
    rendered = []
    real_render = prompt_templates.render_task
    def render(task, **kwargs):
        rendered.append(kwargs)
        return real_render(task, **kwargs)
    original = pose_catalog.catalog_path
    with patch.object(pose_catalog, "catalog_path", side_effect=lambda axis: shared if axis == "pose" else original(axis)), \
         patch.object(pose_catalog, "get_catalog", return_value={}), \
         patch.object(prompt_templates, "render_task", side_effect=render), \
         patch.object(llm_router, "llm_call", return_value=SimpleNamespace(content=json.dumps(dict(PERSON, entry=ENTRY)))):
        got = prepare_motion("free", text="wave", caption_style="person", segment_seconds=4.0)
        assert got.captions == PERSON["segments"]
        assert (rendered[0]["caption_style"], rendered[0]["prefix"], rendered[0]["segment_seconds"]) == \
            ("person", "A person ", 4.0)
    system, _user = real_render("pose_animation_prompt", **rendered[0])
    assert 'starts exactly with "A person "' in system and "4-second" in system, system
    assert "An object " not in system, system
    defaults = dict(rendered[0], caption_style="object", prefix="An object ", segment_seconds=2.0)
    system, _user = real_render("pose_animation_prompt", **defaults)
    assert 'starts exactly with "An object "' in system and "2-second" in system
    assert "A person " not in system
    try:
        prepare_motion("free", text="wave", caption_style="robot")
    except MotionPromptError as exc:
        assert "caption style" in str(exc)
    else:
        raise AssertionError("unknown caption style accepted")
print("PASS template and preparation follow the backend caption style")
