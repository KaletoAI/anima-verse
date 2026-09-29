#!/usr/bin/env python3
"""Smoke: a DEFERRED tool that fails is reported — never swallowed (B1).

Usage:  ./.venv/bin/python scripts/smoke_deferred_tool_feedback.py

No server, no network, no real world: a throwaway storage root (``paths.init``
BEFORE the first app import) and a fresh schema in it.

THE RULE (plan-befundrunde-2026-09-29, B1 + its binding review notes)
---------------------------------------------------------------------------
Tools and the image service do not raise, they ANSWER — and a failure answer
starts with "Error" (older: "Fehler"). ``streaming.is_error_result`` is the one
predicate for that. ``streaming.report_deferred_failure(character, tool,
result, *, speaker)`` turns such an answer into
  * a WARNING carrying the answer,
  * a narrator line through ``perception.announce_action(..., react=False)``
    with the GENERIC text "{actor} tries, but it does not work out — nothing
    came of it." (the core never names a skill — R1),
  * a notification (kind "tool_failed", sender = the character,
    metadata.to = the avatar's NAME) whose wrapper "{actor} could not
    complete {tool}: {reason}" is translated and whose reason stays raw —
    only when a REAL avatar is involved: ``speaker`` unless it is "user",
    else ``get_active_character()``, and only if player-controlled.
Language: the avatar's (``get_character_language(avatar) or "de"``), without
an avatar the character's own. A success answer produces nothing.

``announce_action`` is stubbed on ``app.core.perception`` (the helper imports
it from there at call time) — its own recording is covered by
scripts/smoke_earshot.py [14]; here the question is WHETHER and WITH WHAT it
is called. Notifications are the real table.

HAND-DERIVED EXPECTATIONS
---------------------------------------------------------------------------
Fixture: characters Mira (NPC, language "en") and Kai (avatar, language set
per case), Otto (NPC). ``is_player_controlled`` answers True for "Kai" only.
  [1] is_error_result: "Error: x" -> True, "  error: y" -> True,
      "Fehler: z" -> True, "/characters/Mira/a.png" -> False, "" -> False,
      None -> False, "Photo taken." -> False.
  [2] ("Mira", "TakePhoto", "Error: backend down", speaker="Kai"), Kai "en":
      returns True; exactly 1 WARNING containing "Error: backend down";
      announce_action called once with ("Mira",
      "Mira tries, but it does not work out — nothing came of it.",
      react=False); exactly 1 notification: character "Mira", kind
      "tool_failed", content "Mira could not complete TakePhoto: Error:
      backend down", metadata.to "Kai".
  [3] speaker "user", active character Kai, Kai "de": the narrator line is
      the de.json text "Mira versucht es, aber es klappt nicht — daraus wird
      nichts." and the notification "Mira konnte TakePhoto nicht ausführen:
      Error: backend down" (reason raw, wrapper translated), to "Kai".
  [4] speaker "user", no active character: narrator line in MIRA's language
      ("en" text), 0 new notifications.
  [5] speaker "Otto" (an NPC, not player-controlled): narrator line yes,
      0 new notifications.
  [6] success "/characters/Mira/images/x.png": returns False, no
      announce_action call, 0 new notifications, 0 warnings.
  [7] the wiring in chat_engine.execute_tool_matches (the respond lane's
      deferred runner, a daemon thread — run inline here by swapping
      threading.Thread for a synchronous stand-in): a deferred tool that
      answers "Error: x" -> 1 narrator call + 1 notification to the ctx
      speaker "Kai"; one that RAISES RuntimeError("boom") -> reported as
      "Error: boom"; one that answers a path -> nothing.
  [8] history_manager._clean_message_for_summary drops both spellings:
      "ok\\nError: no backend\\nFehler: alt\\nbye" -> "ok\\nbye".
  [9] npc_assets._delivered_image: "Error: see /tmp/x.png" -> False,
      "/characters/Mira/a.png" -> True.
 [10] TakePhoto's own failure answers start with "Error: " (source check of
      plugins/take_photo/skill.py): "Error: TakePhoto is disabled." and
      "Error: Image generation is not available." — while the in-character
      line of a temporary NPC ("lowers the camera again") is NOT an error.
 [11] notify=False (a stream no player took part in — thought/act/story):
      with an active avatar present the narrator line still comes, in the
      CHARACTER's language (no avatar is involved), and NO notification.
 [12] InstagramPost's refusals are failures too (source check of
      plugins/instagram/skill_post.py): "Error: Instagram is disabled for …"
      and "Error: … is still on post cooldown …".
"""
import logging
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]
STORAGE = Path(tempfile.mkdtemp(prefix="deferred-feedback-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

import app.core.perception as perception_mod  # noqa: E402
import app.models.account as account_mod  # noqa: E402
import app.models.character as character_mod  # noqa: E402
from app.core.streaming import is_error_result, report_deferred_failure  # noqa: E402
from app.models.notifications import get_notifications  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ------------------------------------------------------------------ fixture

LANG = {"Mira": "en", "Kai": "en", "Otto": "en"}
ACTIVE = {"name": "Kai"}
ANNOUNCED = []


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


WARN = _Warnings()
logging.getLogger("agent_loop").addHandler(WARN)   # streaming's logger

character_mod.get_character_language = lambda name: LANG.get(name, "de")
account_mod.is_player_controlled = lambda name: name == "Kai"
account_mod.get_active_character = lambda: ACTIVE["name"]
perception_mod.announce_action = (
    lambda character, text, source="direct_action", perception_meta=None,
    react=True: ANNOUNCED.append((character, text, react)))


def _notifs():
    return get_notifications(limit=100)


def _reset():
    ANNOUNCED.clear()
    WARN.records.clear()


EN_LINE = "Mira tries, but it does not work out — nothing came of it."

# ------------------------------------------------------------------ [1]
print("[1] is_error_result")
for text, want in (("Error: x", True), ("  error: y", True), ("Fehler: z", True),
                   ("/characters/Mira/a.png", False), ("", False), (None, False),
                   ("Photo taken.", False)):
    check(f"is_error_result({text!r})", is_error_result(text), want)

# ------------------------------------------------------------------ [2]
print("[2] error with the avatar as speaker")
_reset()
n0 = len(_notifs())
res = report_deferred_failure("Mira", "TakePhoto", "Error: backend down",
                              speaker="Kai")
check("returns True", res, True)
check("warnings", len([w for w in WARN.records if "Error: backend down" in w]), 1)
check("narrator calls", ANNOUNCED, [("Mira", EN_LINE, False)])
new = _notifs()[:len(_notifs()) - n0]
check("new notifications", len(new), 1)
if new:
    nt = new[0]
    check("notification sender", nt.get("character"), "Mira")
    check("notification kind", nt.get("type") or nt.get("kind"), "tool_failed")
    check("notification content", nt.get("content") or nt.get("body"),
          "Mira could not complete TakePhoto: Error: backend down")
    check("notification to", (nt.get("metadata") or {}).get("to"), "Kai")

# ------------------------------------------------------------------ [3]
print("[3] 'user' speaker -> the active avatar, in the avatar's language")
_reset()
LANG["Kai"] = "de"
n0 = len(_notifs())
report_deferred_failure("Mira", "TakePhoto", "Error: backend down", speaker="user")
check("narrator line (de)", ANNOUNCED,
      [("Mira", "Mira versucht es, aber es klappt nicht — daraus wird nichts.",
        False)])
new = _notifs()[:len(_notifs()) - n0]
check("new notifications", len(new), 1)
if new:
    check("notification content (de wrapper, raw reason)",
          new[0].get("content") or new[0].get("body"),
          "Mira konnte TakePhoto nicht ausführen: Error: backend down")
    check("notification to", (new[0].get("metadata") or {}).get("to"), "Kai")
LANG["Kai"] = "en"

# ------------------------------------------------------------------ [4]
print("[4] no avatar at all")
_reset()
ACTIVE["name"] = ""
n0 = len(_notifs())
report_deferred_failure("Mira", "TakePhoto", "Error: backend down", speaker="user")
check("narrator line in Mira's language", ANNOUNCED, [("Mira", EN_LINE, False)])
check("new notifications", len(_notifs()) - n0, 0)
ACTIVE["name"] = "Kai"

# ------------------------------------------------------------------ [5]
print("[5] an NPC speaker gets no notification")
_reset()
n0 = len(_notifs())
report_deferred_failure("Mira", "TakePhoto", "Error: backend down", speaker="Otto")
check("narrator calls", len(ANNOUNCED), 1)
check("new notifications", len(_notifs()) - n0, 0)

# ------------------------------------------------------------------ [6]
print("[6] success produces nothing")
_reset()
n0 = len(_notifs())
res = report_deferred_failure("Mira", "TakePhoto",
                              "/characters/Mira/images/x.png", speaker="Kai")
check("returns False", res, False)
check("narrator calls", ANNOUNCED, [])
check("new notifications", len(_notifs()) - n0, 0)
check("warnings", WARN.records, [])

# ------------------------------------------------------------------ [7]
print("[7] chat_engine.execute_tool_matches reads the deferred answer")
from app.core import chat_engine  # noqa: E402


class _InlineThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


def _boom(_inp):
    raise RuntimeError("boom")


_ctx = {
    "tools_dict": {"FailTool": lambda _inp: "Error: x",
                   "RaiseTool": _boom,
                   "OkTool": lambda _inp: "/characters/Mira/images/y.png"},
    "deferred_tools": {"FailTool", "RaiseTool", "OkTool"},
    "content_tools": set(),
    "speaker": "Kai",
    "medium": "in_person",
}
_real_thread = threading.Thread
threading.Thread = _InlineThread
try:
    for name, want_reason in (("FailTool", "Error: x"), ("RaiseTool", "Error: boom"),
                              ("OkTool", None)):
        _reset()
        n0 = len(_notifs())
        chat_engine.execute_tool_matches(_ctx, "Mira", [(name, "{}")],
                                         rp_text="She lifts the camera.",
                                         incoming_message="Take a photo!")
        new = _notifs()[:len(_notifs()) - n0]
        if want_reason is None:
            check(f"{name}: narrator calls", ANNOUNCED, [])
            check(f"{name}: new notifications", len(new), 0)
        else:
            check(f"{name}: narrator calls", len(ANNOUNCED), 1)
            check(f"{name}: new notifications", len(new), 1)
            if new:
                check(f"{name}: reason in the notification",
                      new[0].get("content") or new[0].get("body"),
                      f"Mira could not complete {name}: {want_reason}")
                check(f"{name}: to", (new[0].get("metadata") or {}).get("to"), "Kai")
finally:
    threading.Thread = _real_thread

# ------------------------------------------------------------------ [8]
print("[8] the summary cleaner drops both spellings")
from app.utils.history_manager import _clean_message_for_summary  # noqa: E402
check("cleaned", _clean_message_for_summary(
    "ok\nError: no backend\nFehler: alt\nbye"), "ok\nbye")

# ------------------------------------------------------------------ [9]
print("[9] npc_assets uses the same predicate")
from app.core.npc_assets import _delivered_image  # noqa: E402
check("error with a path in it", _delivered_image("Error: see /tmp/x.png"), False)
check("a delivered path", _delivered_image("/characters/Mira/a.png"), True)

# ------------------------------------------------------------------ [10]
print("[10] TakePhoto's own failure answers carry the prefix")
_src = (REPO / "plugins" / "take_photo" / "skill.py").read_text(encoding="utf-8")
check("disabled answer", 'return "Error: TakePhoto is disabled."' in _src, True)
check("no-service answer",
      'return ("Error: Image generation is not available.' in _src, True)
check("temporary-NPC line is no error",
      is_error_result("Mira lowers the camera again — there is nobody here "
                      "to show a picture to. No photo is taken."), False)

# ------------------------------------------------------------------ [11]
print("[11] notify=False: narrator line only")
_reset()
ACTIVE["name"] = "Kai"
LANG["Kai"] = "de"
n0 = len(_notifs())
res = report_deferred_failure("Mira", "TakePhoto", "Error: backend down",
                              speaker="user", notify=False)
check("returns True", res, True)
check("narrator line in Mira's language", ANNOUNCED, [("Mira", EN_LINE, False)])
check("new notifications", len(_notifs()) - n0, 0)
LANG["Kai"] = "en"

# ------------------------------------------------------------------ [12]
print("[12] InstagramPost's refusals carry the prefix")
_isrc = (REPO / "plugins" / "instagram" / "skill_post.py").read_text(encoding="utf-8")
check("disabled answer",
      'return f"Error: Instagram is disabled for {character_name}."' in _isrc, True)
check("cooldown answer",
      'return (f"Error: {character_name} is still on post cooldown "' in _isrc, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
