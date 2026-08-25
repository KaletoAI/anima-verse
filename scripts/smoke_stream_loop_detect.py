"""Smoke check: StreamLoopDetector — runaway loops trip, legitimate JSON never does.

Usage:
    ./.venv/bin/python scripts/smoke_stream_loop_detect.py

Runs without a server and without a world DB.

Expected numbers, derived by hand from the detector's spec (WINDOW=12 completed
lines, MAX_REPEAT=4 substantial duplicates, MIN_LINE_LEN=16 after strip —
EVERY completed line fills the window, short lines are spacers):

A) Layout placement JSON (the 2026-08-25 world-dev cutoff): each window
   element emits 8 lines, of which exactly 2 are substantial and constant
   ('"height_m": 1.2,' 16 chars, '"type": "window",' 17 chars); the variable
   lines ('"at": 0.2779,' 14, '"width_m": 1.2,' 15, '{', '},', '"edge": 0,')
   are shorter than 16. A 12-line window therefore spans 12/8 = 1.5 elements
   -> any constant line occurs at most 2x in the window; 2 < 4 -> NO trip,
   regardless of how many windows the layout has (checked with 8).
B) Stuck LLM, back-to-back: the same 22-char line repeated 5x. When line #5
   is checked, the window holds 4 copies; 4 >= 4 -> TRIP on the 5th.
C) Stuck LLM, 2-line cycle with a short spacer (line / '...' / line): one
   cycle = 2 window slots, so 12 slots hold 6 copies of the long line; the
   5th..7th copy sees >= 4 in the window -> TRIP.
D) Location JSON with 5 rooms (the 2026-07 regression the WINDOW was built
   for): '"decency": "public",' (20 chars) once per room, 10 lines per room
   -> a 12-line window spans 1.2 rooms -> max 2 copies -> NO trip.
E) Chunk boundaries must not matter: case B fed in 3-char chunks trips the
   same way (each line is consumed exactly once, at its completing newline).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.streaming import StreamLoopDetector  # noqa: E402

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))


def feed_all(text: str, chunk: int = 0) -> tuple:
    det = StreamLoopDetector()
    if chunk <= 0:
        return det.feed(text), det
    acc = ""
    for i in range(0, len(text), chunk):
        acc += text[i:i + chunk]
        if det.feed(acc):
            return True, det
    return False, det


def layout_json(n_windows: int) -> str:
    parts = ["{", '  "placements": [']
    for i in range(n_windows):
        parts += [
            "          {",
            '            "edge": 0,',
            f'            "at": 0.{1000 + i * 7},',
            '            "width_m": 1.2,',
            '            "height_m": 1.2,',
            '            "sill_m": 0.9,',
            '            "type": "window",',
            "          },",
        ]
    parts += ["  ]", "}", ""]
    return "\n".join(parts)


def main() -> int:
    print("A) layout JSON with 8 windows (2 substantial lines per 8-line element)")
    tripped, det = feed_all(layout_json(8))
    check("no trip on legitimate layout JSON", not tripped,
          f"offender={det.offender!r}")

    print("B) stuck LLM: same 22-char line back-to-back x5")
    stuck = ("<tool>do_thing()</tool>\n" * 5)
    tripped, det = feed_all(stuck)
    check("trip on back-to-back repetition", tripped)
    check("offender is the repeated line", det.offender == "<tool>do_thing()</tool>")

    print("C) stuck LLM: 2-line cycle with short spacer x7")
    cycle = ("I will now call the tool again.\n...\n" * 7)
    tripped, det = feed_all(cycle)
    check("trip on spaced repetition cycle", tripped)

    print("D) location JSON, 5 rooms, one constant 20-char line per 10-line room")
    rooms = []
    for i in range(5):
        rooms += [
            "    {",
            f'      "name": "Room {i} with a longer name",',
            f'      "description": "Description text number {i} for this room",',
            '      "indoor": "indoor",',
            '      "decency": "public",',
            f'      "style_hint": "style variant {i}",',
            '      "swim_allowed": false,',
            f'      "image_prompt_day": "prompt {i} day",',
            f'      "image_prompt_night": "prompt {i} night",',
            "    },",
        ]
    tripped, det = feed_all("\n".join(rooms) + "\n")
    check("no trip on 5-room location JSON", not tripped,
          f"offender={det.offender!r}")

    print("E) chunk boundaries: case B in 3-char chunks")
    tripped, _ = feed_all(stuck, chunk=3)
    check("trip independent of chunking", tripped)

    ok = all(CHECKS)
    print(f"\n{'ALL OK' if ok else 'FAILURES'} ({sum(CHECKS)}/{len(CHECKS)} checks)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
