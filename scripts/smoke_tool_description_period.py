#!/usr/bin/env python3
"""Smoke: no tool description the LLM sees carries a doubled period (B4).

Usage:  ./.venv/bin/python scripts/smoke_tool_description_period.py

No server, no network, no real world: a throwaway storage root (``paths.init``
BEFORE the first app import) whose config switches EVERY discovered package
on, so gated verbs (search, n8n, markdown writer, photo, …) load as well.

THE RULE (plan-befundrunde-2026-09-29, B4.4 + the binding review note)
---------------------------------------------------------------------------
A description ends WITHOUT a period — once, at load time
(``app/plugins/loader._apply_skill_meta``: ``.rstrip(".")`` on the final
value) — and every verb that extends it in ``as_tool`` appends
"<description without its period>. <more>" (the eight legacy join points:
take_photo, searx, markdown_writer, instagram post, movement/set_location,
n8n, video_generation, describe_room). A template sentence ending in "." used
to come out as "Generates images based on text descriptions.. Input …".

HAND-DERIVED EXPECTATIONS
---------------------------------------------------------------------------
  [1] Every loaded skill's ``as_tool().description`` has no ".." that is not
      part of an ellipsis — i.e. no match of (?<!\\.)\\.\\.(?!\\.) — and the
      assembled AVAILABLE TOOLS block (``build_tool_instruction``) has none
      either.
  [2] Every PLUGIN verb's ``skill.description`` (the loader's final value)
      does not end with ".".
  [3] The eight join points are really covered: TakePhoto, SetLocation and
      the tools of searx / markdown_writer / instagram (post) / n8n /
      video_generation / describe_room each appear among the loaded tools —
      a check that loaded none of them would prove nothing. (Counted by the
      skill's SKILL_ID, the stable key; the tool names are template data.)
  [4] TakePhoto's description asks for NAMES ("by their NAME") and its usage
      example names two people ("Luna and Pixel").
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="tool-desc-period-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="tool-desc-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from app.plugins.loader import discover_packages  # noqa: E402
_pkgs = discover_packages(force=True)
(STORAGE / "config.json").write_text(json.dumps(
    {"skills": {p.id: {"enabled": True} for p in _pkgs}}), encoding="utf-8")

from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

# The legacy registry verbs that are not ALWAYS_LOAD read an env switch.
from app.skills.skill_manager import SkillManager  # noqa: E402
for _sid in SkillManager.SKILL_REGISTRY:
    os.environ[f"SKILL_{_sid.upper()}_ENABLED"] = "true"

from app.core.tool_formats import build_tool_instruction  # noqa: E402

# No network: a verb may probe its service on construction (the search verb
# does) — plugins reach HTTP through PluginContext.http, i.e. ``requests``.
import requests  # noqa: E402


def _no_network(*a, **k):
    raise requests.ConnectionError("smoke: network disabled")


requests.get = requests.post = _no_network

FAILURES = []
CHECKED = 0
DOUBLE = re.compile(r"(?<!\.)\.\.(?!\.)")


def check(label, ok, detail=""):
    global CHECKED
    CHECKED += 1
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


sm = SkillManager()
sm.load_skills()
print(f"loaded {len(sm.skills)} skills")

print("[1] no doubled period in any tool description")
specs = []
for sk in sm.skills:
    try:
        spec = sk.as_tool()
    except Exception as e:  # noqa: BLE001 — a verb that cannot render here
        print(f"  skip {getattr(sk, 'name', '?')}: as_tool failed ({e})")
        continue
    specs.append(spec)
    m = DOUBLE.search(spec.description or "")
    check(f"{spec.name}: no '..'", m is None,
          (spec.description or "")[max(0, m.start() - 40):m.end() + 20] if m else "")
_block = build_tool_instruction("tag", specs)
check("assembled AVAILABLE TOOLS block: no '..'", DOUBLE.search(_block) is None)

print("[2] plugin descriptions carry no closing period")
from app.plugins.base import PluginSkill  # noqa: E402
for sk in sm.skills:
    if isinstance(sk, PluginSkill):
        check(f"{sk.name}: description without closing '.'",
              not (sk.description or "").endswith("."), sk.description or "")

print("[3] the eight join points were really rendered")
_ids = {getattr(sk, "SKILL_ID", "") for sk in sm.skills}
_names = {sk.name for sk in sm.skills}
for want in ("image_generation", "setlocation", "searx", "markdown_writer",
             "n8n", "video_generation", "describe_room"):
    check(f"skill id '{want}' loaded", want in _ids, ", ".join(sorted(_ids)))
check("an instagram posting verb loaded",
      any("instagram" in (getattr(sk, "SKILL_ID", "") or "") for sk in sm.skills),
      ", ".join(sorted(_ids)))

print("[4] TakePhoto asks for names")
_photo = next((sk for sk in sm.skills
               if getattr(sk, "SKILL_ID", "") == "image_generation"), None)
if _photo is not None:
    check("description asks for NAMES", "by their NAME" in _photo.as_tool().description)
    check("usage example names two people",
          "Luna and Pixel" in _photo.get_usage_instructions("tag"))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
