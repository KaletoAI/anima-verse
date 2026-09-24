#!/usr/bin/env python3
"""Smoke run for the T-pose back view (user report 2026-09-24: the back
render showed the head, then the whole upper body, facing the camera).

Three parts of the fix, each checked against values derived BY HAND:

[1] ``prompt_builder.strip_face_terms`` drops every comma/sentence segment
    of the appearance that names a facial feature. Input is the shape of a
    real appearance text; the expected output below is that text with the
    face/cheekbones/makeup/eyes segments struck out by hand.
[2] The built-in back-view pose text names no facial feature itself (the old
    "face not visible" did) and says where the head points.
[3] ``model_refs.checked_reference_override`` accepts only an existing file
    inside the character's own model_refs directory — the value arrives in a
    JSON tool input, so a path elsewhere must never reach a backend upload.

Storage is a temp dir (``paths.init`` before any world-DB import).

Usage:  ./.venv/bin/python scripts/smoke_tpose_back_view.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="smoke_tpose_back_")
from app.core import paths  # noqa: E402
paths.init(_tmp)

from app.core.prompt_builder import _FACE_TERMS_RE, strip_face_terms  # noqa: E402
from app.core import model_refs  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(("ok  " if ok else "FAIL"), label)
    if not ok:
        print("      got: ", repr(got))
        print("      want:", repr(want))
        failures.append(label)


# [1] ------------------------------------------------------------------------
appearance = ("young female, 19 years old, gorgeous, heart-shaped face, "
              "high cheekbones, perfect makeup, long red-blond hair, "
              "emeraldgreen colored eyes with golden streaks eyes, fair skin, "
              "tall, athletic build")
check("[1] facial segments dropped",
      strip_face_terms(appearance),
      "young female, 19 years old, gorgeous, long red-blond hair, fair skin, "
      "tall, athletic build")
# Prose: split on the sentence end too; "brown" must not match "brow".
check("[1] prose + word boundary",
      strip_face_terms("She has brown hair. Her lips are full; broad shoulders"),
      "She has brown hair, broad shoulders")
check("[1] nothing facial -> unchanged segments",
      strip_face_terms("short black hair, stocky build"),
      "short black hair, stocky build")

# [2] ------------------------------------------------------------------------
back = model_refs.TPOSE_BACK_PROMPT_DEFAULT
check("[2] back pose text names no facial feature",
      _FACE_TERMS_RE.findall(back), [])
check("[2] back pose text points the head away",
      "the head facing straight away from the camera" in back, True)

# [3] ------------------------------------------------------------------------
refs = Path(_tmp) / "characters" / "Demo" / "model_refs"
refs.mkdir(parents=True)
front = refs / "tpose_abc.png"
front.write_bytes(b"x")
(Path(_tmp) / "characters" / "Demo" / "images").mkdir()
portrait = Path(_tmp) / "characters" / "Demo" / "images" / "p.png"
portrait.write_bytes(b"x")

check("[3] file inside model_refs accepted",
      model_refs.checked_reference_override("Demo", str(front)),
      str(front.resolve()))
check("[3] traversal out of model_refs refused",
      model_refs.checked_reference_override(
          "Demo", str(refs / ".." / "images" / "p.png")), "")
check("[3] other directory refused",
      model_refs.checked_reference_override("Demo", str(portrait)), "")
check("[3] missing file refused",
      model_refs.checked_reference_override("Demo", str(refs / "nope.png")), "")
check("[3] another character's model_refs refused",
      model_refs.checked_reference_override("Other", str(front)), "")

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all ok")
