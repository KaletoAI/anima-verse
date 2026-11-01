"""Smoke: the picture text of a tool call reaches the image prompt on its own,
whatever argument name the LLM chose (ImageService._parse_input).

Usage:
    ./.venv/bin/python scripts/smoke_photo_prompt_key.py

Runs without the server and without a world DB (temp storage, the service is
built without __init__ — _parse_input reads nothing else).

Expected values, derived by hand from the user report (2026-11-01: photo
prompts showed "Action: {"image_prompt": …, "rp_context": …, "user_input": …}").
tool_calls.jsonl showed TakePhoto inputs keyed `image_prompt` (3x) and
`description` (2x); streaming._inject_rp_context adds rp_context/user_input,
and TakePhoto re-sends its parsed input with the original string under
"input". Before the fix the prompt was ctx["input"] = that whole JSON string.

A) TakePhoto shape: {"image_prompt": P, "rp_context": R, "user_input": U,
   "input": <original JSON>, "agent_name": "Kira", "user_id": "",
   "occasion": "photo"} -> prompt == P; rp_context == R, user_input == U
   (still delivered separately).
B) Same with `description` instead of `image_prompt` -> prompt == P.
C) The raw tool input alone (no TakePhoto wrapper) -> prompt == P.
D) Two free-text keys ("image_prompt" 40 chars, "style" 5 chars) -> the
   longer one, the image_prompt.
E) Unchanged paths: {"prompt": "a cat"} -> "a cat"; plain text "a dog on a
   beach" -> "a dog on a beach"; {"input": "a bird"} -> "a bird";
   {"prompt": "x", "image_prompt": "y"} -> "x" (an explicit prompt wins).
F) Only injected context, no picture text ({"rp_context": R}) -> "" (never
   the JSON).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_photo_prompt_key_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp

from app.core import paths  # noqa: E402
paths.init(_tmp)

from app.imagegen.service import ImageService  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


svc = object.__new__(ImageService)
P = "A close-up of a silvery chip held between two fingers, lake water behind"
R = "I wade further out and feel the sandy ground with my fingers."
U = "show me what you found"


def take_photo_payload(key):
    """What TakePhoto hands to generate_from_input: its parsed base input
    (the original string under "input") plus the occasion."""
    raw = json.dumps({key: P, "rp_context": R, "user_input": U}, ensure_ascii=False)
    data = ImageService._parse_base_input(raw)
    data["agent_name"] = "Kira"
    data["occasion"] = "photo"
    return json.dumps(data, ensure_ascii=False), raw


print("A) TakePhoto with image_prompt")
payload, raw = take_photo_payload("image_prompt")
d = svc._parse_input(payload)
check("prompt is the picture text", d["prompt"] == P, d["prompt"][:120])
check("rp_context still separate", d["rp_context"] == R)
check("user_input still separate", d["user_input"] == U)

print("B) TakePhoto with description")
payload, raw = take_photo_payload("description")
check("prompt is the picture text", svc._parse_input(payload)["prompt"] == P)

print("C) raw tool input")
check("prompt is the picture text", svc._parse_input(raw)["prompt"] == P)

print("D) two free-text keys")
d = svc._parse_input(json.dumps({"image_prompt": "a" * 40, "style": "photo"}))
check("longer one wins", d["prompt"] == "a" * 40, d["prompt"])

print("E) unchanged paths")
check("prompt key", svc._parse_input(json.dumps({"prompt": "a cat"}))["prompt"] == "a cat")
check("plain text", svc._parse_input("a dog on a beach")["prompt"] == "a dog on a beach")
check("input key", svc._parse_input(json.dumps({"input": "a bird"}))["prompt"] == "a bird")
check("explicit prompt wins",
      svc._parse_input(json.dumps({"prompt": "x", "image_prompt": "y"}))["prompt"] == "x")

print("F) only injected context")
d = svc._parse_input(json.dumps({"rp_context": R}))
check("empty, never the JSON", d["prompt"] == "", d["prompt"][:120])

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
