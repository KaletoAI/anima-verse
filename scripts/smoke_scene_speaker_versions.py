#!/usr/bin/env python3
"""Checks the expression versions GET /play/scene reports for the SPEAKERS of
the history it returns (``speaker_expr_versions``).

Usage:
    ./.venv/bin/python scripts/smoke_scene_speaker_versions.py

Throwaway storage, throwaway world DB — no server, no real world is touched,
nothing is generated. The route function is called DIRECTLY (it is a plain
``def``, FastAPI only wires it up), so what is measured is the payload the
player/HUD would receive. Three collaborators are replaced by stubs so the run
is hermetic and its numbers are hand-derivable:

  * ``perception_store.get_character_room_stream`` -> a CONSTRUCTED history
    (the point of the check is the selection rule, not SQL),
  * ``perception.addressable_for``                -> exactly one person present,
  * ``play._expr_version``                        -> a COUNTING stub, so the
    number of computations is observable at all.

All three are looked up at call time inside the route, so patching the module
attribute is what the route sees.

WHY these expectations (derived by hand from the payload rule, not recorded
from current output):

  THE CASE. The HUD chat window (plan-hud-chat-portraits.md, Task 1a) shows a
  portrait next to every line. It needs a cache-buster version for EVERY
  speaker of the history — not just for the people currently in the room:
  somebody who spoke and then walked out is still in the history, its image
  would be served unversioned, and the expression route caches a hit for an
  hour (``Cache-Control: public, max-age=3600``,
  ``app/routes/characters.py``). ``present_detail[].expr_version`` and
  ``avatar_expr_version`` cover the two old cases and stay untouched.

  WHO IS RENDERABLE. ``meta.speaker`` is always set (the only write path is
  ``perception.record_utterance``). Three kinds of line have no face:
  narrator prose, display-only meta lines (relationship notes) and event
  verdicts — and all three are written with ``speaker=STORYTELLER_SPEAKER``
  (``app/core/chat_engine.py``, ``app/core/act_engine.py``). So ONE canonical
  comparison drops all three.

  [1] THE SELECTION, by hand. The constructed history has eight lines:

        #1  Torvin       spoke                  -> renderable, 1st seen
        #2  Storyteller  narration              -> no face
        #3  Mira         spoke, with an image   -> renderable, 2nd seen
        #4  Torvin       spoke again            -> already seen, no repeat
        #5  Storyteller  display_only (💞 …)    -> no face
        #6  Storyteller  event_verdict          -> no face
        #7  Aveline      spoken_self (the avatar itself)  -> renderable, 3rd
        #8  a line without any meta at all      -> no speaker, dropped

      Expected order = order of FIRST appearance, deduplicated:
        ["Torvin", "Mira", "Aveline"]

  [2] THE PRECONDITION FOR [3]. The avatar's language is "de" and
      ``t("Storyteller", "de")`` really is "Erzähler"
      (``shared/languages/de.json``), so the route DOES rewrite the label of
      the three storyteller lines for display. Without that this run could not
      tell a canonical check from a localised one.

  [3] CANONICAL, NEVER LOCALISED. The payload therefore carries the German
      label on the lines — and the version map must contain NEITHER
      "Storyteller" NOR "Erzähler". A check written against the display string
      would let every narrator line through the moment the player switches
      language; a check performed after the localisation pass would let it
      through in German.

  [4] EVERY VERSION IS THERE AND IS THE ONE OF ITS NAME. The stub answers
      "v-<name>", so the map must be exactly
        {"Torvin": "v-Torvin", "Mira": "v-Mira", "Aveline": "v-Aveline"}.

  [5] EACH NAME IS COMPUTED EXACTLY ONCE — the point of the memo.
      ``_expr_version`` reads the profile state, the pose, the equipped items
      AND the mtime of the cached variant; per request it must run once per
      NAME, not once per use. The request needs three distinct names:
        * Torvin  — present (present_detail) AND a speaker,
        * Mira    — a speaker only,
        * Aveline — the avatar (avatar_expr_version) AND a speaker.
      Hand count with the memo: 3 calls. Without it: Torvin twice, Aveline
      twice, Mira once = 5. Asserted as the exact call log per name.

  [6] THE OLD FIELDS ARE UNCHANGED. ``present_detail[].expr_version`` and
      ``avatar_expr_version`` still carry their values — this is an addition,
      not a rebuild.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="scenespeakers-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="scenespeakers-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import perception  # noqa: E402
from app.core.i18n import t as _t  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER  # noqa: E402
from app.models import perception_store  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.routes import play  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'}  {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


AVATAR = "Aveline"
PRESENT = "Torvin"
GONE = "Mira"

# --- the constructed history (oldest first, as the store returns it) ---------
SCENE = [
    {"id": 1, "ts": "2026-08-30T10:00:00+00:00", "kind": "in_room",
     "content": "Guten Morgen.", "meta": {"speaker": PRESENT}},
    {"id": 2, "ts": "2026-08-30T10:00:05+00:00", "kind": "in_room",
     "content": "Die Tür fällt ins Schloss.",
     "meta": {"speaker": STORYTELLER_SPEAKER}},
    {"id": 3, "ts": "2026-08-30T10:00:10+00:00", "kind": "in_room",
     "content": "Sieh mal.",
     "meta": {"speaker": GONE, "image_url": "/x.png"}},
    {"id": 4, "ts": "2026-08-30T10:00:15+00:00", "kind": "in_room",
     "content": "Schon wieder ich.", "meta": {"speaker": PRESENT}},
    {"id": 5, "ts": "2026-08-30T10:00:20+00:00", "kind": "in_room",
     "content": "💞 Aveline ⇄ Torvin: neutral → acquaintance",
     "meta": {"speaker": STORYTELLER_SPEAKER, "display_only": True,
              "relationship": True}},
    {"id": 6, "ts": "2026-08-30T10:00:25+00:00", "kind": "in_room",
     "content": "Das Ereignis wurde gelöst.",
     "meta": {"speaker": STORYTELLER_SPEAKER, "event_verdict": "resolved"}},
    {"id": 7, "ts": "2026-08-30T10:00:30+00:00", "kind": "spoken_self",
     "content": "Dann los.", "meta": {"speaker": AVATAR}},
    {"id": 8, "ts": "2026-08-30T10:00:35+00:00", "kind": "in_room",
     "content": "(kein meta)"},
]
EXPECTED_SPEAKERS = [PRESENT, GONE, AVATAR]

for who in (AVATAR, PRESENT, GONE):
    save_character_profile(who, {"name": who, "language": "de"},
                           create_new=True)
set_active_character(AVATAR)

# --- [1] the pure selection rule --------------------------------------------
check("renderable speakers of the constructed history, first appearance first",
      play._renderable_speakers(SCENE), EXPECTED_SPEAKERS)
check("an empty history has no speakers", play._renderable_speakers([]), [])

# --- [2] the precondition: the storyteller label really is localised here ----
check("t('Storyteller', 'de') is the German label", _t("Storyteller", "de"),
      "Erzähler")

# --- the route, with the three collaborators stubbed out ---------------------
calls = []


def _counting_expr_version(name: str) -> str:
    calls.append(name)
    return f"v-{name}"


play._expr_version = _counting_expr_version
perception.addressable_for = lambda name: [PRESENT]
perception_store.get_character_room_stream = (
    lambda *a, **kw: [dict(ln) for ln in SCENE])

payload = play.play_scene(user=None)

# --- [3] canonical, never localised -----------------------------------------
check("the payload's storyteller lines ARE localised for display",
      sorted({(ln.get("meta") or {}).get("speaker") for ln in payload["scene"]
              if (ln.get("meta") or {}).get("speaker")}),
      sorted({AVATAR, PRESENT, GONE, "Erzähler"}))
check("no storyteller in the version map (canonical nor localised)",
      [k for k in payload["speaker_expr_versions"]
       if k in (STORYTELLER_SPEAKER, "Erzähler")], [])

# --- [4] the versions themselves --------------------------------------------
check("one version per renderable speaker", payload["speaker_expr_versions"],
      {PRESENT: f"v-{PRESENT}", GONE: f"v-{GONE}", AVATAR: f"v-{AVATAR}"})

# --- [5] each name computed exactly once ------------------------------------
check("every name's version was computed exactly once",
      sorted(calls), sorted([PRESENT, GONE, AVATAR]))

# --- [6] the existing fields are untouched ----------------------------------
check("present_detail keeps its expr_version",
      [(d["name"], d["expr_version"]) for d in payload["present_detail"]],
      [(PRESENT, f"v-{PRESENT}")])
check("avatar_expr_version keeps its value", payload["avatar_expr_version"],
      f"v-{AVATAR}")

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
