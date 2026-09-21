#!/usr/bin/env python3
"""Smoke: character writes fail loudly, and no reader falls back to a JSON file.

Usage:
    ./.venv/bin/python scripts/smoke_profile_write_failures.py

Throwaway storage (tempfile + ``paths.init``), no server, no real world DB, no
LLM. ``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.
The write failure is produced by replacing ``transaction`` in
``app.models.character`` with one that raises
``sqlite3.OperationalError("database is locked")`` — the error DATA-1's long
world writes produce under load, and the one the busy_timeout of 5 s gives up
with.

WHY (DATA-13 and DATA-17 of the 2026-09-20 review)
--------------------------------------------------
``save_character_profile`` caught every exception, logged it at ERROR without
a traceback and then carried straight on: it updated the CALLER's dict with
the runtime keys and fired the outfit hook, and it returned nothing at all, so
``POST /characters/{name}/profile`` answered ``{"status": "success"}``. The UI
showed the new value (it is in the returned dict) and it was gone after the
next reload. ``save_character_config`` did the same; ``_record_state_change``
logged its loss at DEBUG.
Three readers then covered the tracks: ``get_character_profile``,
``get_character_config`` and ``list_available_characters`` caught the DB error
and fell back to ``character_profile.json`` / ``character_config.json`` —
files nothing has written since world data became DB-only. A failing DB read
therefore looked like "this character has no personality" instead of an error.

EXPECTED, derived by hand from the contracts (not from current output):

  [1] HAPPY PATH UNCHANGED.
        save_character_profile(name, {...}, create_new=True) -> True, and the
        row is in ``characters``.
        save_character_config(name, {...}) -> True, row updated.
        _record_state_change(name, "location", "market") -> True, one row in
        ``state_history``.
      None of the three takes an argument that changes on success.

  [2] FAILING WRITE -> False, AND NOTHING IS HALF-WRITTEN.
        With ``transaction`` raising, all three return False and the stored
        row keeps its OLD value: profile field ``mood`` stays "calm" although
        the save was handed "furious", the config keeps ``importance`` 1, and
        ``state_history`` has no new row.
      On the old code all three returned ``None`` — falsy, but they returned
      ``None`` on success too, so the value carried no information ([4]).

  [3] THE FAILURE IS LOGGED AT ERROR WITH A TRACEBACK.
        One ERROR record per failed call on the ``character`` logger, and
        ``record.exc_info`` is set — without it the line names the exception
        but not the statement that raised it. ``_record_state_change`` used
        DEBUG, so it logged nothing at all at this level.

  [4] THE RETURN VALUE CARRIES INFORMATION.
        Success is ``True`` (not ``None``), and the two refusals that store
        nothing by design are ``False`` as well: a reserved name ("system")
        and an unknown character without ``create_new``.

  [5] THE CALLER'S DICT IS NOT LEFT LOOKING SAVED.
        The dict handed to a FAILED ``save_character_profile`` still carries
        the runtime keys it came in with (they are popped out of it during the
        save and must be put back — otherwise the caller loses its own keys),
        but the write is reported as failed, and the outfit hook that
        re-renders a temporary NPC's pictures MUST NOT have run: a picture for
        an outfit that never reached the DB contradicts the stored profile.
        The hook is observed by monkey-patching
        ``app.core.npc_assets.on_outfit_description_changed``.

  [6] NO JSON FALLBACK ANY MORE (DATA-17). A ``character_profile.json`` and a
      ``character_config.json`` are written into the character directory by
      hand, each with a value that is NOT in the DB ("ghost"). Then:
        (a) with a WORKING DB the stored values win — they did before, too;
        (b) with the DB read raising, ``get_character_profile`` returns the
            empty default profile (``character_personality`` == "") and
            ``get_character_config`` returns the defaults — NOT "ghost";
        (c) ``list_available_characters`` returns [] when its query raises,
            instead of listing the directory;
        (d) a second character whose directory holds ONLY ``profile.json``
            is not served from it, and the file is NOT renamed to
            ``character_profile.json`` — the old fallback renamed it, a write
            on a read path.
      On the old code (a) held, (b) returned "ghost", (c) listed the
      character and (d) renamed the file.

  [7] ``app.models.chat.save_message`` PASSES THE RESULT THROUGH (DATA-13).
      True for a stored row, False when the underlying write fails, False for
      an empty character name. It returned ``None`` in every case before.

  [8] ``app.models.chat.get_chat_history`` PASSES ``limit`` THROUGH (DATA-12)
      and the bounded read is the same tail as the unbounded one: 7 messages
      stored, ``limit=3`` yields the last 3 dicts of the full history, and no
      argument still yields all 7.
"""
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="writefail-char-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="writefail-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models import character as ch  # noqa: E402
from app.models import chat as chatmod  # noqa: E402

NAME = "Racer"
FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'[ok]' if ok else '[FAIL]'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


class Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class Exploding:
    """A ``transaction()`` context manager that raises on enter — what a
    ``database is locked`` looks like to these functions."""

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        raise sqlite3.OperationalError("database is locked")

    def __exit__(self, *a):
        return False


def stored_profile(name=NAME):
    row = db.get_connection().execute(
        "SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
    import json
    return json.loads(row[0]) if row and row[0] else {}


def stored_config(name=NAME):
    row = db.get_connection().execute(
        "SELECT config_json FROM characters WHERE name=?", (name,)).fetchone()
    import json
    return json.loads(row[0]) if row and row[0] else {}


def state_rows(name=NAME):
    return db.get_connection().execute(
        "SELECT COUNT(*) FROM state_history WHERE character_name=?",
        (name,)).fetchone()[0]


print("[1] happy path unchanged")
ok = ch.save_character_profile(NAME, {
    "character_name": NAME,
    "template": "human-default",
    "character_personality": "calm",
    "mood": "calm",
}, create_new=True)
check("save_character_profile -> True", ok is True, repr(ok))
check("the row carries the value", stored_profile().get("mood") == "calm",
      repr(stored_profile().get("mood")))

ok = ch.save_character_config(NAME, {"importance": 1, "tool_format": "auto"})
check("save_character_config -> True", ok is True, repr(ok))
check("the row carries the value", stored_config().get("importance") == 1,
      repr(stored_config().get("importance")))

before_state = state_rows()
ok = ch._record_state_change(NAME, "location", "market")
check("_record_state_change -> True", ok is True, repr(ok))
check("the row is there", state_rows() == before_state + 1)

print("[2]/[3] a failing write is False, silent on disk and loud in the log")
log = Collector()
ch.logger.addHandler(log)
_real_tx = ch.transaction
ch.transaction = Exploding()
try:
    res_p = ch.save_character_profile(NAME, {"character_name": NAME,
                                             "mood": "furious"})
    res_c = ch.save_character_config(NAME, {"importance": 3})
    before_state = state_rows()
    res_s = ch._record_state_change(NAME, "location", "harbour")
finally:
    ch.transaction = _real_tx
    ch.logger.removeHandler(log)

check("save_character_profile -> False", res_p is False, repr(res_p))
check("the stored profile still says calm", stored_profile().get("mood") == "calm",
      repr(stored_profile().get("mood")))
check("save_character_config -> False", res_c is False, repr(res_c))
check("the stored config still says 1", stored_config().get("importance") == 1,
      repr(stored_config().get("importance")))
check("_record_state_change -> False", res_s is False, repr(res_s))
check("no state_history row was added", state_rows() == before_state)

errors = [r for r in log.records if r.levelno >= logging.ERROR]
check("exactly three ERROR records", len(errors) == 3,
      str([r.getMessage()[:60] for r in errors]))
check("every one carries a traceback",
      bool(errors) and all(r.exc_info for r in errors))

print("[4] the return value carries information")
check("success is True, not None",
      ch.save_character_profile(NAME, {"character_name": NAME}) is True)
check("reserved name -> False",
      ch.save_character_profile("system", {"character_name": "system"}) is False)
check("unknown character without create_new -> False",
      ch.save_character_profile("Nobody Here", {"character_name": "Nobody Here"})
      is False)
check("save_character_config for an unknown character -> False",
      ch.save_character_config("Nobody Here", {"importance": 2}) is False)

print("[5] a failed save leaves no trace of success")
import app.core.npc_assets as npc_assets  # noqa: E402

hook_calls = []
_real_hook = npc_assets.on_outfit_description_changed
npc_assets.on_outfit_description_changed = (
    lambda *a, **kw: hook_calls.append(a))
# A temporary NPC is the only character the hook fires for, so the failing
# save has to be one: same template feature the real NPCs carry.
TNPC = "Passer By"
ch.save_character_profile(TNPC, {
    "character_name": TNPC,
    "template": "npc-temporary",
    "outfit_description": "grey coat",
}, create_new=True)
hook_calls.clear()
handed = {"character_name": TNPC, "outfit_description": "red dress",
          "current_location": "market", "current_activity": "walking"}
_real_tx = ch.transaction
ch.transaction = Exploding()
try:
    res = ch.save_character_profile(TNPC, handed)
finally:
    ch.transaction = _real_tx
check("the failed save reports False", res is False, repr(res))
check("the outfit hook did NOT run", hook_calls == [], repr(hook_calls))
check("the caller keeps its own runtime keys",
      handed.get("current_location") == "market"
      and handed.get("current_activity") == "walking", repr(handed))
check("the DB still holds the old outfit",
      stored_profile(TNPC).get("outfit_description") == "grey coat",
      repr(stored_profile(TNPC).get("outfit_description")))
npc_assets.on_outfit_description_changed = _real_hook

print("[6] no JSON fallback reader is left")
import json  # noqa: E402

# Re-seed: [4] deliberately saved a bare dict, and a profile save writes the
# WHOLE blob — so the personality this section compares against has to be put
# back first.
ch.save_character_profile(NAME, {"character_name": NAME,
                                 "template": "human-default",
                                 "mood": "calm"})
char_dir = ch.get_character_dir(NAME, create=True)
(char_dir / "character_profile.json").write_text(json.dumps({
    "character_name": NAME, "mood": "ghost",
    "character_personality": "ghost"}), encoding="utf-8")
(char_dir / "character_config.json").write_text(json.dumps({
    "importance": 99, "ghost": True}), encoding="utf-8")
# The rename check needs a character whose directory has ONLY the pre-rename
# file: the old fallback renamed ``profile.json`` to ``character_profile.json``
# — a write on a read path — and only when the target did not exist yet.
RENAMER = "Old Timer"
renamer_dir = ch.get_character_dir(RENAMER, create=True)
(renamer_dir / "profile.json").write_text(json.dumps({
    "character_name": RENAMER, "mood": "ghost"}), encoding="utf-8")

check("(a) with a working DB the stored profile wins",
      ch.get_character_profile(NAME).get("mood") == "calm",
      repr(ch.get_character_profile(NAME).get("mood")))
check("(a) with a working DB the stored config wins",
      ch.get_character_config(NAME).get("importance") == 1
      and "ghost" not in ch.get_character_config(NAME),
      repr(ch.get_character_config(NAME).get("importance")))


class ExplodingConn:
    """A ``get_connection()`` whose every query raises."""

    def execute(self, *a, **kw):
        raise sqlite3.OperationalError("database is locked")

    def __call__(self, *a, **kw):
        return self


log = Collector()
ch.logger.addHandler(log)
_real_conn = ch.get_connection
ch.get_connection = ExplodingConn()
try:
    prof = ch.get_character_profile(NAME)
    cfg = ch.get_character_config(NAME)
    roster = ch.list_available_characters()
    renamer_prof = ch.get_character_profile(RENAMER)
finally:
    ch.get_connection = _real_conn
    ch.logger.removeHandler(log)

check("(b) get_character_profile does not read the JSON file",
      prof.get("mood") is None and prof.get("character_personality") == "",
      repr({k: prof.get(k) for k in ("mood", "character_personality")}))
check("(b) get_character_config does not read the JSON file",
      "ghost" not in cfg and cfg.get("importance") == 1,
      repr({k: cfg.get(k) for k in ("importance", "ghost")}))
check("(c) list_available_characters does not list the directory",
      roster == [], repr(roster))
check("(d) profile.json was NOT renamed and NOT read",
      (renamer_dir / "profile.json").exists()
      and not (renamer_dir / "character_profile.json").exists()
      and renamer_prof.get("mood") is None,
      repr(sorted(p.name for p in renamer_dir.iterdir())))
read_errors = [r for r in log.records if r.levelno >= logging.ERROR]
check("every failed read logged ERROR with a traceback",
      len(read_errors) >= 4 and all(r.exc_info for r in read_errors),
      str([r.getMessage()[:50] for r in read_errors]))

print("[7]/[8] the chat wrapper passes result and limit through")
check("save_message -> True",
      chatmod.save_message({"role": "user", "content": "one",
                            "timestamp": "T01"}, NAME, partner_name="Bob")
      is True)
check("no character name -> False",
      chatmod.save_message({"role": "user", "content": "x"}, "") is False)

import app.models.unified_chat as uc  # noqa: E402

_real_uc_tx = uc.transaction
uc.transaction = Exploding()
try:
    res = chatmod.save_message({"role": "user", "content": "lost",
                                "timestamp": "T02"}, NAME, partner_name="Bob")
finally:
    uc.transaction = _real_uc_tx
check("a failing write -> False", res is False, repr(res))

for i in range(2, 8):
    chatmod.save_message({"role": "user", "content": f"msg{i}",
                          "timestamp": f"T{i:02d}"}, NAME, partner_name="Bob")
full = chatmod.get_chat_history(NAME, partner_name="Bob")
tail = chatmod.get_chat_history(NAME, partner_name="Bob", limit=3)
check("the unbounded read still returns everything", len(full) == 7,
      f"{len(full)} messages")
check("limit=3 returns the last three of them",
      [m.get("content") for m in tail] == [m.get("content") for m in full[-3:]],
      f"{[m.get('content') for m in tail]} vs {[m.get('content') for m in full[-3:]]}")

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
