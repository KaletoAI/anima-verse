#!/usr/bin/env python3
"""Smoke run for the character RE-INIT ("Fresh start") and the admin memory
wipe — one shared implementation, two scopes (``app/core/character_reset.py``).

Why this exists
---------------
A character pack is a snapshot of that character IN ITS OLD WORLD. Before the
fix the "fresh start" import dropped a hand-written list of history tables and
then restored everything else straight out of the pack — including
``relationships`` (a rival edge) and, worse, ``files/soul/beliefs.md``, which
Retrospect writes from lived experience ("About others: …") and which the
read-side dangling filter can never see, because free prose carries no
character reference to match on. So the re-init ran and the pack promptly put
the old world back. Section [2] of this smoke asserts that the pack really does
carry that state, so the mechanism is a checked fact, not a claim.

The wipe list and the import's restore filter are now DERIVED FROM THE SAME
TABLE (``character_reset.STORES``), so this smoke walks that table and asserts
one store at a time — a new per-character table that is added to STORES is
covered here automatically, and one that is forgotten fails the count check in
section [1].

Doctrine under test (re-init = "this character starts fresh in THIS world"):
  * the character's OWN memory, relations and history go — relationship edges
    in BOTH directions, so a rival cannot survive on the partner's row;
  * WORLD facts about them held by OTHERS stay — the second character's own
    memories, and its daily summary about them (``summaries.partner``);
  * mechanical state (position/room/activity/pose) falls back to the profile.

Runs against THROWAWAY storage directories — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

Sections, each a hand-derived expectation:
  [1] The store table itself: every store is reachable, the memory scope is a
      strict subset of the re-init scope, and the import's restore-skip set is
      exactly the re-init stores that live in a real table (+ character_state).
  [2] Export: the pack CARRIES the old world — the rival relationship row and
      the rival line in soul/beliefs.md are both inside the ZIP. This is the
      evidence for the mechanism verdict.
  [3] Re-init into a FOREIGN, empty world: every store in the re-init scope is
      empty, both relationship directions are gone, the Retrospect soul files
      are back to an empty scaffold with the rival line nowhere on disk, and
      the identity stores (profile, outfits, inventory, secrets, routine) are
      still there. The intro memory is the ONE memory that exists.
  [4] Re-init over an EXISTING character in the original world (overwrite):
      same store table, but now it also has to clear what the pack never
      carried — perceptions, party invites, explored cells, notifications and
      the JSON-participant stores. The second character's own memory and its
      partner-summary about the re-initialized one are UNTOUCHED.
  [5] The MARKETPLACE path (`_dispatch_install`, the function every /install*
      endpoint funnels through) with the same flag — a character pack from a
      catalog is a character export ZIP and must offer the identical re-init.
  [6] The admin "Wipe memory" button (`wipe_character_memory`): the whole day
      timeline goes — diary entries, thoughts, state history, the action log —
      while correspondence, knowledge and relationships stay. That timeline
      surviving the button was the reported gap.

Usage:  ./.venv/bin/python scripts/smoke_character_reinit.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="char-reinit-smoke-"))
STORAGE_B = Path(tempfile.mkdtemp(prefix="char-reinit-smoke-b-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="char-reinit-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import character_reset  # noqa: E402
from app.core.character_io import (  # noqa: E402
    export_character_to_zip, import_character_from_zip)
from app.core.character_ops import wipe_character_memory  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_dir, get_character_profile, save_character_profile)

#: `demo` is the only sample character name this repo allows.
NAME = "demo"
OTHER = "demo_other"
#: The old world's rival. The whole point of the fix is that this string is
#: nowhere to be found after a re-init.
RIVAL_LINE = "I can never trust demo_other after what happened."
INTRO = "demo has just arrived in this world and knows nobody yet."

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def reset_connections():
    """Switching the storage dir inside one process must drop the per-thread
    connection cache, or the "second world" keeps writing into the first."""
    for _c in list(db._connections.values()):
        _c.close()
    db._connections.clear()


# ---------------------------------------------------------------------------
# Seeding — one row in EVERY store of the reset table, for `demo`
# ---------------------------------------------------------------------------

def count_rows(store, name):
    """Rows of `store` that still belong to `name`. For the JSON-participant
    stores that means "rows whose list still names them", which is what the
    pruner is supposed to have fixed."""
    conn = db.get_connection()
    if not store.json_column:
        return conn.execute(
            f"SELECT COUNT(*) FROM {store.table} WHERE {store.where}",
            tuple([name] * store.params)).fetchone()[0]
    lowered = name.lower()
    if store.table == "notifications":
        rows = conn.execute("SELECT title, meta FROM notifications").fetchall()
        hits = 0
        for title, meta in rows:
            if (title or "").lower() == lowered:
                hits += 1
                continue
            try:
                if str((json.loads(meta or "{}") or {}).get("character") or "").lower() == lowered:
                    hits += 1
            except Exception:
                pass
        return hits
    extra = ", owner" if store.table == "intents" else (
        ", leader" if store.table == "parties" else "")
    rows = conn.execute(
        f"SELECT {store.json_column}{extra} FROM {store.table}").fetchall()
    hits = 0
    for row in rows:
        try:
            members = json.loads(row[0] or "[]")
        except Exception:
            members = []
        names = ([str(v) for v in members.values()] if isinstance(members, dict)
                 else [str(v) for v in members])
        owner = (row[1] or "") if extra else ""
        if lowered in {n.lower() for n in names} or owner.lower() == lowered:
            hits += 1
    return hits


def seed_stores(name):
    """One row per store, plus the two rows that must SURVIVE a re-init:
    the other character's own memory, and its daily summary ABOUT `name`."""
    with db.transaction() as c:
        c.execute("INSERT INTO memories (character_name, tier, ts, content) "
                  "VALUES (?,?,?,?)", (name, "episodic", "2026-01-01T10:00:00",
                                       "The rival humiliated me at the fair."))
        c.execute("INSERT OR REPLACE INTO summaries "
                  "(character_name, kind, date_key, partner, content) VALUES (?,?,?,?,?)",
                  (name, "daily", "Y0001-D001", OTHER, "A bad day with the rival."))
        c.execute("INSERT INTO diary_entries (character_name, ts, content) "
                  "VALUES (?,?,?)", (name, "2026-01-01T20:00:00", "Dear diary…"))
        c.execute("INSERT INTO thoughts (character_name, ts, content) "
                  "VALUES (?,?,?)", (name, "2026-01-01T11:00:00", "I keep thinking about it."))
        c.execute("INSERT INTO mood_history (character_name, ts, mood) "
                  "VALUES (?,?,?)", (name, "2026-01-01T11:00:00", "angry"))
        c.execute("INSERT INTO state_history (character_name, ts, state_json) "
                  "VALUES (?,?,?)", (name, "2026-01-01T11:00:00", '{"location":"old_town"}'))
        c.execute("INSERT INTO evolution_history (character_name, ts, field, new_value) "
                  "VALUES (?,?,?,?)", (name, "2026-01-01T11:00:00", "snapshot", "{}"))
        c.execute("INSERT INTO character_action_log "
                  "(character_name, scope, user_input, created_at) VALUES (?,?,?,?)",
                  (name, "room", "look around", "2026-01-01T11:00:00"))
        c.execute("INSERT INTO chat_messages (character_name, partner, ts, role, content) "
                  "VALUES (?,?,?,?,?)", (name, OTHER, "2026-01-01T11:00:00", "user", "hi"))
        c.execute("INSERT INTO utterances (ts, speaker, volume, content) VALUES (?,?,?,?)",
                  ("2026-01-01T11:00:00", name, "normal", "Said out loud."))
        utt_id = c.execute("SELECT id FROM utterances WHERE speaker=?", (name,)).fetchone()[0]
        c.execute("INSERT INTO perceptions (perceiver, utterance_id, ts, kind, content) "
                  "VALUES (?,?,?,?,?)", (name, utt_id, "2026-01-01T11:00:00", "in_room", "heard"))
        c.execute("INSERT INTO knowledge (character_name, content, ts) VALUES (?,?,?)",
                  (name, "The old town square floods in spring.", "2026-01-01T11:00:00"))
        # BOTH directions — a rival that survives on the partner's row is
        # exactly the symptom this smoke exists for.
        c.execute("INSERT INTO relationships (from_char, to_char, content, ts) VALUES (?,?,?,?)",
                  (name, OTHER, "rival — cannot be trusted", "2026-01-01T11:00:00"))
        c.execute("INSERT INTO relationships (from_char, to_char, content, ts) VALUES (?,?,?,?)",
                  (OTHER, name, "rival — keeps score", "2026-01-01T11:00:00"))
        c.execute("INSERT OR REPLACE INTO assignments (id, character_name, task, created_at, updated_at) "
                  "VALUES (?,?,?,?,?)", ("a1", name, "settle the score", "t", "t"))
        c.execute("INSERT OR REPLACE INTO scheduler_jobs (id, character_name, action, trigger, created_at) "
                  "VALUES (?,?,?,?,?)", ("j1", name, "act", "{}", "t"))
        c.execute("INSERT OR REPLACE INTO stories (id, title, character_name, created_at, updated_at) "
                  "VALUES (?,?,?,?,?)", ("s1", "Old tale", name, "t", "t"))
        c.execute("INSERT INTO events (ts, kind, character_name) VALUES (?,?,?)",
                  ("2026-01-01T11:00:00", "danger", name))
        c.execute("INSERT OR REPLACE INTO party_invites (invite_id, inviter, invitee, created_at) "
                  "VALUES (?,?,?,?)", ("pi1", name, OTHER, "t"))
        c.execute("INSERT OR REPLACE INTO explored_cells (character_id, cx, cz) VALUES (?,?,?)",
                  (name, 3, 4))
        c.execute("INSERT OR REPLACE INTO telegram_mapping (chat_id, character_name, avatar, created_at) "
                  "VALUES (?,?,?,?)", ("c1", name, "", "t"))
        c.execute("INSERT OR REPLACE INTO intents (id, owner, participants, created_at, updated_at) "
                  "VALUES (?,?,?,?,?)", ("i1", name, json.dumps({"target": OTHER}), "t", "t"))
        c.execute("INSERT OR REPLACE INTO story_arcs (id, title, participants, created_at, updated_at) "
                  "VALUES (?,?,?,?,?)", ("sa1", "Feud", json.dumps([name, OTHER]), "t", "t"))
        c.execute("INSERT OR REPLACE INTO group_chats (id, participants, messages, created_at, updated_at) "
                  "VALUES (?,?,?,?,?)", ("g1", json.dumps([name, OTHER]), "[]", "t", "t"))
        c.execute("INSERT OR REPLACE INTO parties (party_id, leader, members, created_at) VALUES (?,?,?,?)",
                  ("p1", name, json.dumps([name, OTHER]), "t"))
        c.execute("INSERT INTO notifications (ts, kind, title, meta) VALUES (?,?,?,?)",
                  ("2026-01-01T11:00:00", "info", name, json.dumps({"character": name})))
        # Mechanical state of the OLD world.
        c.execute("INSERT OR REPLACE INTO character_state "
                  "(character_name, current_location, current_activity, pose_key) "
                  "VALUES (?,?,?,?)", (name, "old_town", "brooding", "sitting"))
        # Identity stores — these must SURVIVE the re-init.
        c.execute("INSERT INTO secrets (character_name, content) VALUES (?,?)",
                  (name, "Was born somewhere else."))
        c.execute("INSERT OR REPLACE INTO daily_schedules (character_name, enabled, slots) "
                  "VALUES (?,?,?)", (name, 1, "[]"))
        c.execute("INSERT OR REPLACE INTO inventory_items "
                  "(character_name, item_id, quantity, acquired_at) VALUES (?,?,?,?)",
                  (name, "w_thing", 1, "2026-01-01T09:00:00"))
        # The OTHER character's own record — other minds are not this
        # character's state and must come through untouched. Re-seeded
        # idempotently: the smoke seeds several times, and a growing row count
        # would make "untouched" unassertable.
        c.execute("DELETE FROM memories WHERE character_name=?", (OTHER,))
        c.execute("INSERT INTO memories (character_name, tier, ts, content) VALUES (?,?,?,?)",
                  (OTHER, "episodic", "2026-01-01T10:00:00",
                   "I remember demo losing their temper."))
        c.execute("INSERT OR REPLACE INTO summaries "
                  "(character_name, kind, date_key, partner, content) VALUES (?,?,?,?,?)",
                  (OTHER, "daily", "Y0001-D001", name, "What demo did that day."))


def seed_soul(name):
    """The Retrospect files — accumulated world history in FILE form, and the
    carrier no read-side filter can see."""
    from app.core.soul_writer import rewrite_file
    rewrite_file(name, "beliefs", [{"text": RIVAL_LINE, "category": "about_others"}],
                 language="en")
    rewrite_file(name, "lessons", [{"text": "Never turn your back on them.",
                                    "category": "from_people"}], language="en")
    rewrite_file(name, "goals", [{"text": "Outdo demo_other this season.",
                                  "category": "short_term"}], language="en")


def soul_body_lines(name, file_id):
    from app.core.soul_writer import get_soul_file_path
    p = get_soul_file_path(name, file_id)
    if not p.is_file():
        return None
    return [ln for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("- ")]


def rival_on_disk(name):
    """Any file under the character dir still holding the rival line."""
    d = get_character_dir(name)
    hits = []
    for fp in sorted(d.rglob("*")):
        if not fp.is_file():
            continue
        try:
            if RIVAL_LINE in fp.read_text(encoding="utf-8"):
                hits.append(fp.relative_to(d).as_posix())
        except Exception:
            continue
    return hits


def assert_reinit_cleared(prefix, name, seeded_intro=False):
    """Table-driven: one check per store in the re-init scope.

    ``memories`` is the one store that is not empty afterwards when an intro
    text was given — the re-init seeds exactly one memory, and asserting "1"
    here is stricter than skipping the store."""
    for store in character_reset.stores_for(character_reset.SCOPE_REINIT):
        expected = 1 if (seeded_intro and store.key == "memories") else 0
        check(f"{prefix} {store.key} empty", count_rows(store, name), expected)


# ---------------------------------------------------------------------------
# [1] The store table
# ---------------------------------------------------------------------------

print("\n[1] The store table (one list drives both the wipe and the restore filter)")

mem_stores = character_reset.stores_for(character_reset.SCOPE_MEMORY)
reinit_stores = character_reset.stores_for(character_reset.SCOPE_REINIT)
check("memory scope is a strict subset of re-init",
      {s.key for s in mem_stores} <= {s.key for s in reinit_stores}
      and len(mem_stores) < len(reinit_stores), True)
check("every store's table exists in the schema",
      sorted({s.table for s in character_reset.STORES}
             - {r[0] for r in db.get_connection().execute(
                 "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}),
      [])
# The restore filter is the re-init stores that live in a plain table, plus
# character_state (mechanical state comes from the profile, not from the pack).
check("restore_skip_tables == re-init stores (non-JSON) + character_state",
      character_reset.restore_skip_tables(),
      frozenset({s.table for s in reinit_stores if not s.json_column}
                | {"character_state"}))
check("relationships is in the restore skip set (the rival edge)",
      "relationships" in character_reset.restore_skip_tables(), True)
try:
    character_reset.reset_character(NAME, "nope")
    check("an unknown scope is refused", "no raise", "ValueError")
except ValueError:
    check("an unknown scope is refused", "ValueError", "ValueError")


# ---------------------------------------------------------------------------
# [2] Export — the pack carries the old world
# ---------------------------------------------------------------------------

print("\n[2] Export: the pack carries the old world's rival")

save_character_profile(NAME, {"name": NAME, "description": "A demo character.",
                              "height": 170}, create_new=True)
save_character_profile(OTHER, {"name": OTHER, "description": "The other one.",
                               "height": 165}, create_new=True)
seed_stores(NAME)
seed_soul(NAME)

blob = export_character_to_zip(NAME, include_chats=True, include_stories=True)

import io  # noqa: E402
import zipfile  # noqa: E402
with zipfile.ZipFile(io.BytesIO(blob)) as zf:
    names = zf.namelist()
    rels = json.loads(zf.read("db/relationships.json"))
    beliefs = zf.read("files/soul/beliefs.md").decode("utf-8")
check("the pack carries a relationships dump", "db/relationships.json" in names, True)
check("…with the outgoing rival edge",
      [r["to_char"] for r in rels], [OTHER])
check("the pack carries soul/beliefs.md", "files/soul/beliefs.md" in names, True)
check("…with the rival line verbatim (the carrier no filter can see)",
      RIVAL_LINE in beliefs, True)
check("the pack carries knowledge", "db/knowledge.json" in names, True)


# ---------------------------------------------------------------------------
# [3] Re-init into a foreign, empty world
# ---------------------------------------------------------------------------

print("\n[3] Re-init into a foreign, empty world")

paths.init(STORAGE_B)
reset_connections()
db.init_schema()

res = import_character_from_zip(blob, mode="fresh", intro_text=INTRO)
check("status", res["status"], "success")
check("mode", res["mode"], "fresh")
check("the result says what the mode meant",
      res["mode_description"].startswith("Re-initialized"), True)
check("the result lists the reset scope", res["reset"]["scope"], "reinit")
check("the result names what was kept and why",
      len(res["reset"]["mode_doc"]["kept"]) > 0, True)
check("the Retrospect soul files were not restored from the pack",
      res["reset"]["files_not_restored"],
      ["soul/beliefs.md", "soul/goals.md", "soul/lessons.md"])

assert_reinit_cleared("[foreign]", NAME, seeded_intro=True)
check("[foreign] the intro memory is the only memory",
      [r[0] for r in db.get_connection().execute(
          "SELECT content FROM memories WHERE character_name=?", (NAME,)).fetchall()],
      [INTRO])
check("[foreign] beliefs.md is an empty scaffold", soul_body_lines(NAME, "beliefs"), [])
check("[foreign] lessons.md is an empty scaffold", soul_body_lines(NAME, "lessons"), [])
check("[foreign] goals.md is an empty scaffold", soul_body_lines(NAME, "goals"), [])
check("[foreign] the rival line is nowhere on disk", rival_on_disk(NAME), [])
check("[foreign] identity survived: profile",
      (get_character_profile(NAME) or {}).get("height"), 170)
check("[foreign] identity survived: secrets",
      db.get_connection().execute("SELECT COUNT(*) FROM secrets WHERE character_name=?",
                                  (NAME,)).fetchone()[0], 1)
check("[foreign] identity survived: inventory",
      db.get_connection().execute("SELECT COUNT(*) FROM inventory_items "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 1)
check("[foreign] identity survived: daily routine",
      db.get_connection().execute("SELECT COUNT(*) FROM daily_schedules "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 1)
check("[foreign] identity survived: soul/personality.md",
      (get_character_dir(NAME) / "soul" / "personality.md").is_file(), True)

# The same pack in FULL mode restores everything — the two modes have to
# differ, or "fresh" proves nothing.
res_full = import_character_from_zip(blob, overwrite=True, mode="full")
check("[foreign] full clone restores the rival edge",
      db.get_connection().execute("SELECT COUNT(*) FROM relationships WHERE from_char=?",
                                  (NAME,)).fetchone()[0], 1)
check("[foreign] full clone restores the rival line in beliefs.md",
      rival_on_disk(NAME), ["soul/beliefs.md"])
check("[foreign] full clone says so in the result",
      res_full["mode_description"].startswith("Full clone"), True)
check("[foreign] full clone reports no reset", res_full["reset"], {})


# ---------------------------------------------------------------------------
# [4] Re-init over an existing character, in the original world
# ---------------------------------------------------------------------------

print("\n[4] Re-init over an existing character (original world, second character present)")

paths.init(STORAGE)
reset_connections()

res2 = import_character_from_zip(blob, overwrite=True, mode="fresh", intro_text=INTRO)
check("status", res2["status"], "success")
check("overwritten", res2["overwritten"], True)

assert_reinit_cleared("[home]", NAME, seeded_intro=True)
check("[home] the rival edge is gone in BOTH directions",
      db.get_connection().execute(
          "SELECT COUNT(*) FROM relationships WHERE from_char=? OR to_char=?",
          (NAME, NAME)).fetchone()[0], 0)
check("[home] the rival line is nowhere on disk", rival_on_disk(NAME), [])
check("[home] mechanical state fell back to the profile",
      db.get_connection().execute("SELECT COUNT(*) FROM character_state "
                                  "WHERE character_name=? AND current_location='old_town'",
                                  (NAME,)).fetchone()[0], 0)
# Other minds are not this character's state.
check("[home] the other character's OWN memory is untouched",
      [r[0] for r in db.get_connection().execute(
          "SELECT content FROM memories WHERE character_name=?", (OTHER,)).fetchall()],
      ["I remember demo losing their temper."])
check("[home] the other character's summary ABOUT demo is untouched",
      db.get_connection().execute(
          "SELECT COUNT(*) FROM summaries WHERE character_name=? AND partner=?",
          (OTHER, NAME)).fetchone()[0], 1)
check("[home] the room record (utterances) is untouched — others heard it",
      db.get_connection().execute("SELECT COUNT(*) FROM utterances WHERE speaker=?",
                                  (NAME,)).fetchone()[0], 1)
# JSON-participant stores: shared rows are pruned, not deleted.
check("[home] the shared story arc survived, without demo",
      json.loads(db.get_connection().execute(
          "SELECT participants FROM story_arcs WHERE id='sa1'").fetchone()[0]), [OTHER])
check("[home] the party demo led is gone entirely",
      db.get_connection().execute("SELECT COUNT(*) FROM parties").fetchone()[0], 0)


# ---------------------------------------------------------------------------
# [5] The marketplace path, same flag
# ---------------------------------------------------------------------------

print("\n[5] Marketplace path (_dispatch_install) with the same re-init flag")

from app.routes.content_packs import _dispatch_install  # noqa: E402

# Put the old world back first, so the re-init has something to clear.
_dispatch_install("character", blob, overwrite=True, mode="full")
seed_stores(NAME)
seed_soul(NAME)
check("[market] the full clone brought the rival back",
      db.get_connection().execute("SELECT COUNT(*) FROM relationships WHERE from_char=?",
                                  (NAME,)).fetchone()[0] > 0, True)

res3 = _dispatch_install("character", blob, overwrite=True, mode="fresh", intro=INTRO)
check("[market] status", res3["status"], "success")
check("[market] mode", res3["mode"], "fresh")
assert_reinit_cleared("[market]", NAME, seeded_intro=True)
check("[market] the rival line is nowhere on disk", rival_on_disk(NAME), [])


# ---------------------------------------------------------------------------
# [6] The admin "Wipe memory" button — the day timeline has to go
# ---------------------------------------------------------------------------

print("\n[6] Admin memory wipe: the whole day timeline goes, correspondence stays")

seed_stores(NAME)
seed_soul(NAME)
wipe = wipe_character_memory(NAME)
check("scope", wipe["scope"], "memory")

for store in character_reset.stores_for(character_reset.SCOPE_MEMORY):
    check(f"[button] {store.key} empty", count_rows(store, NAME), 0)

# The reported gap, spelled out: these three ARE the Tagesverlauf.
check("[button] diary entries gone (the reported gap)",
      db.get_connection().execute("SELECT COUNT(*) FROM diary_entries "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 0)
check("[button] daily summaries gone (the reported gap)",
      db.get_connection().execute("SELECT COUNT(*) FROM summaries "
                                  "WHERE character_name=? AND kind='daily'",
                                  (NAME,)).fetchone()[0], 0)
check("[button] state history gone (the timeline's own source)",
      db.get_connection().execute("SELECT COUNT(*) FROM state_history "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 0)
check("[button] day cursor reset", wipe["day_cursor"], "reset")

# Narrower than a re-init, on purpose.
check("[button] correspondence stays",
      db.get_connection().execute("SELECT COUNT(*) FROM chat_messages "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 1)
check("[button] knowledge stays",
      db.get_connection().execute("SELECT COUNT(*) FROM knowledge "
                                  "WHERE character_name=?", (NAME,)).fetchone()[0], 1)
check("[button] relationships stay",
      db.get_connection().execute("SELECT COUNT(*) FROM relationships "
                                  "WHERE from_char=?", (NAME,)).fetchone()[0], 1)
check("[button] the soul files stay (not derived memory)",
      soul_body_lines(NAME, "beliefs") is not None
      and len(soul_body_lines(NAME, "beliefs")) == 1, True)
check("[button] the other character's memory stays",
      db.get_connection().execute("SELECT COUNT(*) FROM memories "
                                  "WHERE character_name=?", (OTHER,)).fetchone()[0], 1)
check("[button] the wipe names what it kept", len(wipe["kept"]) > 0, True)


# ---------------------------------------------------------------------------

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  ✗ {f}")
import shutil  # noqa: E402
for d in (STORAGE, STORAGE_B, Path(os.environ["ANIMATION_CLIPS_DIR"])):
    shutil.rmtree(d, ignore_errors=True)
sys.exit(1 if FAILURES else 0)
