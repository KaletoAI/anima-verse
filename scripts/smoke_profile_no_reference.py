#!/usr/bin/env python3
"""Profile renders accept only an explicitly supplied portrait reference.

Usage: ./.venv/bin/python scripts/smoke_profile_no_reference.py

The default portrait starts without conditioning. If the service explicitly
supplies the creating character's current portrait in profile_reference, it
occupies slot 1 regardless of person detection or avatar status. The room,
other people and items NEVER condition a portrait.

Derived expectations:
  ordinary render with a room -> the room occupies slot 1
  profile render without an explicit person reference -> no slots
  profile render with agent reference, room, other person and item -> only agent
  profile render with a zero-slot backend -> no slots

No world DB, server or network is used.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.prompt_builder import Person, PromptBuilder, PromptVariables  # noqa: E402


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

        portrait_image = Path(tmp) / "portrait.png"
        portrait_image.write_bytes(b"\x89PNG\r\n\x1a\n")
        referenced = PromptVariables(
            set_profile=True,
            persons=[Person("demo", "face", "", is_user=True),
                     Person("other", "face", "")],
            ref_images={2: str(room_image)},
            ref_image_room=str(room_image),
            items=[{"name": "prop", "image": str(room_image)}],
        )
        referenced.profile_reference = str(portrait_image)
        slots = builder.resolve_reference_slots(referenced, max_slots=4)
        want = {"input_reference_image_1": str(portrait_image)}
        if slots["reference_images"] != want or not slots["has_reference_slots"]:
            failures.append(f"explicit portrait: expected only {want}, got {slots}")
        slots = builder.resolve_reference_slots(referenced, max_slots=0)
        if slots["reference_images"] or slots["has_reference_slots"]:
            failures.append(f"zero-slot portrait: expected no slots, got {slots}")
        referenced.persons = []
        slots = builder.resolve_reference_slots(referenced, max_slots=4)
        if slots["reference_images"] != want:
            failures.append(f"no detected person: expected {want}, got {slots}")

    for line in failures:
        print(f"FAIL {line}")
    if failures:
        return 1
    print("OK  portraits have no implicit refs and accept only the explicit agent ref")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
