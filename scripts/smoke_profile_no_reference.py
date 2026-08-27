#!/usr/bin/env python3
"""A profile render slots NO reference image.

Usage: ./.venv/bin/python scripts/smoke_profile_no_reference.py

The profile picture is where a character's identity COMES FROM, so nothing may
condition it: no self-reference (that would loop), and above all not the room
the character happens to stand in. ``render_has_reference_image`` already tells
the backend selection exactly that ("a set_profile render slots no reference,
so it belongs on the cheaper txt2img backend") — this check pins the other end
of that promise, the slot planner that actually fills the slots.

Two runs over the SAME variables, only the ``set_profile`` flag differs:

  set_profile=False -> the room image lands in slot 1 (ordinary priority:
                       agent, room, others, items — no person ref here, so the
                       room is first)
  set_profile=True  -> no slot at all

Works without a world DB and without the server: ``_plan_qwen_slots`` reads
nothing but the PromptVariables it is handed.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.prompt_builder import PromptBuilder, PromptVariables  # noqa: E402


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        room_image = Path(tmp) / "gasthaus.png"
        room_image.write_bytes(b"\x89PNG\r\n\x1a\n")

        builder = PromptBuilder("Demo NPC")

        base = dict(ref_image_room=str(room_image))

        ordinary = PromptVariables(set_profile=False, **base)
        slots = builder.resolve_reference_slots(ordinary, max_slots=4)
        got = slots["reference_images"]
        want = {"input_reference_image_1": str(room_image)}
        if got != want:
            failures.append(f"ordinary render: expected {want}, got {got}")

        portrait = PromptVariables(set_profile=True, **base)
        slots = builder.resolve_reference_slots(portrait, max_slots=4)
        got = slots["reference_images"]
        if got:
            failures.append(f"profile render: expected no reference, got {got}")
        if slots["has_reference_slots"]:
            failures.append("profile render: has_reference_slots must be False")

    for line in failures:
        print(f"FAIL {line}")
    if failures:
        return 1
    print("OK  a profile render slots no reference, an ordinary one slots the room")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
