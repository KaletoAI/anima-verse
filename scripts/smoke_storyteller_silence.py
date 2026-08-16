#!/usr/bin/env python3
"""Smoke run for the storyteller silence rule (R1 / A9-rest).

Pure decision logic, no server, no DB, no LLM: ``should_narrate_silence``
gets the room's speech acts recorded AFTER the avatar's utterance (oldest
first) and answers whether the storyteller may step in.

The rule, derived by hand from plan-room-conversation-ergaenzungsplan § R1:

  * The storyteller narrates ONLY when nobody reacted. Any speech act by a
    third party is a reaction → no narration.
  * A line by the AVATAR itself cancels the check: that newer utterance
    brings its own silence check, and narrating for the older one would put
    the storyteller in twice.
  * Storyteller lines are not reactions. ``/play/say`` writes the spell result
    (``hint``) as a storyteller line right after the avatar's own utterance,
    and ``perform_act`` narrates under the same speaker — if those counted,
    the storyteller would silence itself in every spell round.
  * Empty/blank speakers are ignored (a broken row must not decide).

Hand-derived expectations (avatar = "Ayla", storyteller = "Storyteller"):

  [1] [Borin]                       → False  (an NPC answered)
  [2] []                            → True   (every respond turn said SKIP:
                                              no utterance was recorded at all)
  [3] [Storyteller]                 → True   (only narration, no answer)
  [4] [Ayla]                        → False  (the avatar spoke again)
  [5] [Storyteller, Ayla]           → False  (spell line, then the avatar
                                              spoke again)
  [6] [Borin, Ayla]                 → False  (answer AND a new avatar line)
  [7] [Ayla, Borin]                 → False  (the avatar comes first — the
                                              check is off from that line on)
  [8] [Storyteller, Borin]          → False  (narration is skipped, the NPC
                                              behind it still counts)
  [9] ["", "  ", Storyteller]       → True   (blank speakers are ignored)
 [10] [Borin] with avatar "Borin"   → False  (the avatar-cancel rule follows
                                              the avatar NAME, not a fixed
                                              one: here Borin is the avatar,
                                              so its own line cancels)
 [11] None                         → True   (same as [2]: nothing recorded)
 [12] [Storyteller], name defaulted → True  (the module's default name equals
                                              perception.STORYTELLER_SPEAKER)

Usage:  ./.venv/bin/python scripts/smoke_storyteller_silence.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.silence_check import should_narrate_silence  # noqa: E402

AVATAR = "Ayla"
STORYTELLER = "Storyteller"

FAILURES = []
CHECKED = 0


def rows(*speakers):
    """Utterance rows as the perception store returns them (only the speaker
    is read; content/ts are carried along to prove they are ignored)."""
    return [{"id": 100 + i, "speaker": s, "content": "…", "ts": "2026-08-17T10:00:00Z"}
            for i, s in enumerate(speakers)]


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


print("should_narrate_silence — avatar 'Ayla', storyteller 'Storyteller'")

check("[1] an NPC answered",
      should_narrate_silence(rows("Borin"), AVATAR, STORYTELLER), False)
check("[2] everybody SKIPped (no utterance at all)",
      should_narrate_silence([], AVATAR, STORYTELLER), True)
check("[3] only a storyteller line (e.g. spell result)",
      should_narrate_silence(rows(STORYTELLER), AVATAR, STORYTELLER), True)
check("[4] the avatar spoke again",
      should_narrate_silence(rows(AVATAR), AVATAR, STORYTELLER), False)
check("[5] spell line, then a new avatar line",
      should_narrate_silence(rows(STORYTELLER, AVATAR), AVATAR, STORYTELLER), False)
check("[6] NPC answer AND a new avatar line",
      should_narrate_silence(rows("Borin", AVATAR), AVATAR, STORYTELLER), False)
check("[7] avatar first, NPC after",
      should_narrate_silence(rows(AVATAR, "Borin"), AVATAR, STORYTELLER), False)
check("[8] narration first, NPC behind it",
      should_narrate_silence(rows(STORYTELLER, "Borin"), AVATAR, STORYTELLER), False)
check("[9] blank speakers are ignored",
      should_narrate_silence(rows("", "  ", STORYTELLER), AVATAR, STORYTELLER), True)
check("[10] the avatar-cancel rule holds for any avatar name",
      should_narrate_silence(rows("Borin"), "Borin", STORYTELLER), False)
check("[11] None rows behave like an empty room",
      should_narrate_silence(None, AVATAR, STORYTELLER), True)
check("[12] default storyteller name (caller passes none)",
      should_narrate_silence(rows("Storyteller"), AVATAR), True)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
