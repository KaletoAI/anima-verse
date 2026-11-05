#!/usr/bin/env python3
"""Smoke: the transformation package's store — definitions, active state,
cooldowns, knowers, the reset store (``plugins/transformation/``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_store.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any world-DB module is
imported), no server, no real world DB, no LLM. The package is loaded the way
the server loads it: ``packages.enabled = "transformation"`` in the world
config, then ``discover_packages()`` runs its ``on_load`` (``register.py``).

THE SPEC (task 2 of the linked-characters plan, ruling P1): the package is
reduced to its trigger. A definition is ``{id, item_id, alias,
activation_phrase, revert_phrase, condition_id, max_duration_minutes,
cooldown_minutes, transform_activity, enabled}``; the ``alias`` is a plain
LABEL (knower secret text, narration) — nothing masks a name with it, so it
is no reserved name and a repeated alias is no defect. The tables stay; the
columns an earlier version wrote (definitions: description, suit_items,
prompt_overrides, pause_routine, imagegen; active: granted_items,
lock_before) are neither read nor written. No ``identity.*`` provider.

FIXTURE
    The three tables are created FIRST in the shape a live world has them
    (the CREATEs of commit 2db33db3, all old columns), so every check below
    runs against the old shape. Then ``store.create_definition``, in order:
    #1 id "moon"    item "moon_brooch" alias "Moonveil"  max 0, cooldown 15, activity "glowing"
    #2 id "noalias" item "x"           alias ""          -> skipped: lacks alias
    #3 id "noitem"  item ""            alias "Nobody"    -> skipped: lacks item
    #4 id "off"     item "w"           alias "Dormant"   enabled false -> skipped
    #5 id "moon"    item "v"           alias "Other"     -> refused by the table (PRIMARY KEY)
    #6 id "sun"     item "sun_ring"    alias "Sunward"   (only the required fields)
    #7 id "echo"    item "y"           alias "moonveil"  -> KEPT (a label may repeat)
    #8 id "kim"     item "z"           alias "KIM"       -> KEPT (a label may be a name)
    Characters Cara (bearer), Kim (knower), Obs (non-knower).

THE RULES, and what follows BY HAND
[A] Storage: #5 raises ``sqlite3.IntegrityError`` (id taken), so does a
    second row for item "moon_brooch" (``item_id`` UNIQUE); 7 rows stored,
    ``list_definitions`` in creation order: moon, noalias, noitem, off, sun,
    echo, kim. A stored row's keys are exactly id + the nine written columns +
    updated_at (no description/suit/override/image key). A row created
    without id gets a slug of its alias: "Ünder Moon!" -> "under_moon", the
    next one with the same alias "under_moon_2", an alias without one ASCII
    letter -> "persona". Every write bumps ``definitions_generation()``. The
    old columns keep their defaults on a new row: description '', suit_items
    '[]', prompt_overrides '{}', pause_routine 1, imagegen '{}'.
[B] definitions.load(): kept = {echo, kim, moon, sun}.
    moon: max 0, cooldown 15, activity "glowing".
    sun:  table defaults = the constants in ``definitions`` — enabled True,
          max 60, cooldown 30, activity "transforming".
    The Definition has exactly the fields id, enabled, item_id, alias,
    activation_phrase, revert_phrase, condition_id, max_duration_minutes,
    cooldown_minutes, transform_activity.
    for_item("moon_brooch").id = "moon"; for_item("nothing") = None.
    An ``update_definition`` is seen by the next ``load()`` at once (the
    write generation is the cache key): sun's cooldown 45 -> 45, back to 30.
[C] Active state: a row written straight into ``transformation_active`` with
    the old columns set (as a restart finds it) is visible after
    ``store.invalidate()`` -> get_active("Cara").persona_id "moon",
    snapshot {"alias": "Moonveil", "condition_id": "", "pose_key": ""}; the
    ActiveRow has exactly bearer, persona_id, started_game, until_game,
    snapshot. Obs: None. set_active/clear_active are visible at once (they
    invalidate); a set_active on the old table leaves granted_items '[]' and
    lock_before 0 (defaults, not written).
[D] knowers: ensure_secret twice -> the same id, exactly one secret with
    source_ref "transformation:moon", source "record", content
    "I am secretly Moonveil.". known_by = ["  kim"] (as the Secrets editor
    may store it) -> knowers.knows("Kim", "Cara", "moon") True (casefold,
    stripped); Obs False; the bearer herself True. knowers.add("Obs", "Cara",
    "moon") -> True, then Obs knows.
[E] Names: an alias reserves nothing — character_name_problem("Moonveil"),
    ("Sunward") and ("Dormant") are all None. The package registers no
    ``identity.*`` provider: get_providers of identity.active_persona,
    identity.knows, identity.persona_names, identity.costume_items are [].
[F] cooldown: cooldown_until before any write = ""; after
    set_cooldown("Cara", "moon", "Y0001-D002T10:00:00") that string.
[G] reset store: reset_character("Cara", reinit) reports
    result["transformation"] = 2 (1 active row + 1 cooldown row), both tables
    hold 0 rows of Cara afterwards and get_active("Cara") is None. A
    memory-scope reset keeps the state (mechanical state, not memory): after
    re-arming, reset_character("Cara", memory) has no "transformation" key and
    the active row stays. Neither reset touches the definitions: still 7 rows.
[H] deletion: delete_character("Obs") sweeps Obs's active row (the tables key
    the character in a ``character_name`` column, which the delete sweep
    covers).
[I] reload: a second discover_packages(force=True) runs on_load again without
    error; get_active("Cara").persona_id is still "moon".
[J] A FRESH table (all three dropped, ensure_schema again) has exactly the
    kept columns: definitions id, item_id, alias, activation_phrase,
    revert_phrase, condition_id, max_duration_minutes, cooldown_minutes,
    transform_activity, enabled, updated_at; active character_name,
    persona_id, started_game, until_game, outfit_snapshot.
"""
import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="transformation-store-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="transformation-clips-")

RECORDS = [
    {"id": "moon", "item_id": "moon_brooch", "alias": "Moonveil", "max_duration_minutes": 0,
     "cooldown_minutes": 15, "transform_activity": "glowing"},
    {"id": "noalias", "item_id": "x", "alias": ""},
    {"id": "noitem", "item_id": "", "alias": "Nobody"},
    {"id": "off", "item_id": "w", "alias": "Dormant", "enabled": False},
    {"id": "moon", "item_id": "v", "alias": "Other"},
    {"id": "sun", "item_id": "sun_ring", "alias": "Sunward"},
    {"id": "echo", "item_id": "y", "alias": "moonveil"},
    {"id": "kim", "item_id": "z", "alias": "KIM"},
]
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.db import get_connection, transaction  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

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


# The old table shape (commit 2db33db3), before the package's on_load runs.
with transaction() as _conn:
    _conn.execute("""CREATE TABLE transformation_definitions (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL UNIQUE,
        alias TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        activation_phrase TEXT NOT NULL DEFAULT '',
        revert_phrase TEXT NOT NULL DEFAULT '',
        suit_items TEXT NOT NULL DEFAULT '[]',
        condition_id TEXT NOT NULL DEFAULT '',
        max_duration_minutes INTEGER NOT NULL DEFAULT 60,
        cooldown_minutes INTEGER NOT NULL DEFAULT 30,
        transform_activity TEXT NOT NULL DEFAULT 'transforming',
        enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT '',
        prompt_overrides TEXT NOT NULL DEFAULT '{}',
        pause_routine INTEGER NOT NULL DEFAULT 1,
        imagegen TEXT NOT NULL DEFAULT '{}')""")
    _conn.execute("""CREATE TABLE transformation_active (
        character_name TEXT PRIMARY KEY,
        persona_id TEXT NOT NULL,
        started_game TEXT NOT NULL,
        until_game TEXT NOT NULL DEFAULT '',
        outfit_snapshot TEXT NOT NULL DEFAULT '{}',
        granted_items TEXT NOT NULL DEFAULT '[]',
        lock_before INTEGER NOT NULL DEFAULT 0)""")
    _conn.execute("""CREATE TABLE transformation_cooldown (
        character_name TEXT,
        persona_id TEXT,
        until_game TEXT NOT NULL,
        PRIMARY KEY(character_name, persona_id))""")

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name}, create_new=True)

from app.models import inventory  # noqa: E402
inventory.add_item("Moon brooch", item_id="moon_brooch")
inventory.add_item("Sun ring", item_id="sun_ring")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

# ── [A] storage ────────────────────────────────────────────────────────────
print("[A] definitions table")
import sqlite3  # noqa: E402
from plugins.transformation import definitions, knowers, store  # noqa: E402
_gen0 = store.definitions_generation()
_refused = []
for _r in RECORDS:
    try:
        store.create_definition({k: v for k, v in _r.items() if k != "id"}, persona_id=_r["id"])
    except sqlite3.IntegrityError:
        _refused.append(_r["id"] + "/" + _r["item_id"])
check("duplicate id refused by the table", _refused, ["moon/v"])
try:
    store.create_definition({"item_id": "moon_brooch", "alias": "Second"}, persona_id="second")
    _item_twice = "stored"
except sqlite3.IntegrityError:
    _item_twice = "refused"
check("one persona per item", _item_twice, "refused")
check("rows stored, creation order", [r["id"] for r in store.list_definitions()],
      ["moon", "noalias", "noitem", "off", "sun", "echo", "kim"])
check("row keys", sorted(store.get_definition("moon")),
      sorted(["id", "item_id", "alias", "activation_phrase", "revert_phrase", "condition_id",
              "max_duration_minutes", "cooldown_minutes", "transform_activity", "enabled",
              "updated_at"]))
check("writes bump the generation", store.definitions_generation() > _gen0, True)
check("old columns keep their defaults", tuple(get_connection().execute(
    "SELECT description, suit_items, prompt_overrides, pause_routine, imagegen "
    "FROM transformation_definitions WHERE id='moon'").fetchone()), ("", "[]", "{}", 1, "{}"))
_s1 = store.create_definition({"item_id": "q1", "alias": "Ünder Moon!"})
_s2 = store.create_definition({"item_id": "q2", "alias": "Ünder Moon!"})
_s3 = store.create_definition({"item_id": "q3", "alias": "月"})
check("slug ids", [_s1, _s2, _s3], ["under_moon", "under_moon_2", "persona"])
for _sid in (_s1, _s2, _s3):
    check(f"delete {_sid}", store.delete_definition(_sid), True)
check("delete unknown", store.delete_definition("nope"), False)

# ── [B] definitions ─────────────────────────────────────────────────────────
print("[B] definitions")
defs = definitions.load()
check("kept ids", sorted(defs), ["echo", "kim", "moon", "sun"])
moon, sun = defs["moon"], defs["sun"]
check("Definition fields", [f.name for f in dataclasses.fields(definitions.Definition)],
      ["id", "enabled", "item_id", "alias", "activation_phrase", "revert_phrase",
       "condition_id", "max_duration_minutes", "cooldown_minutes", "transform_activity"])
check("moon alias", moon.alias, "Moonveil")
check("moon item", moon.item_id, "moon_brooch")
check("moon max", moon.max_duration_minutes, 0)
check("moon cooldown", moon.cooldown_minutes, 15)
check("moon activity", moon.transform_activity, "glowing")
check("echo keeps its repeated alias", defs["echo"].alias, "moonveil")
check("sun enabled", sun.enabled, True)
check("sun max default", sun.max_duration_minutes, 60)
check("sun cooldown default", sun.cooldown_minutes, 30)
check("sun activity default", sun.transform_activity, "transforming")
check("for_item moon_brooch", getattr(definitions.for_item("moon_brooch"), "id", None), "moon")
check("for_item unknown", definitions.for_item("nothing"), None)
store.update_definition("sun", {"cooldown_minutes": 45})
check("update seen at once", definitions.load()["sun"].cooldown_minutes, 45)
store.update_definition("sun", {"cooldown_minutes": 30})

# ── [C] active state + cache ────────────────────────────────────────────────
print("[C] active state")
from app.core.timeutils import game_time  # noqa: E402
NOW = game_time().canonical()
SNAP = {"alias": "Moonveil", "condition_id": "", "pose_key": ""}
check("Cara not transformed yet", store.get_active("Cara"), None)
with transaction() as conn:   # what a restart finds in the (old-shape) table
    conn.execute("INSERT INTO transformation_active (character_name, persona_id, started_game, "
                 "until_game, outfit_snapshot, granted_items, lock_before) VALUES (?,?,?,?,?,?,?)",
                 ("Cara", "moon", NOW, "", json.dumps(SNAP), json.dumps(["silver_mask"]), 1))
store.invalidate()
row = store.get_active("Cara")
check("cache rebuilt from table", getattr(row, "persona_id", None), "moon")
check("row snapshot", getattr(row, "snapshot", None), SNAP)
check("ActiveRow fields", [f.name for f in dataclasses.fields(store.ActiveRow)],
      ["bearer", "persona_id", "started_game", "until_game", "snapshot"])
check("Obs wears nothing", store.get_active("Obs"), None)
store.set_active(store.ActiveRow(bearer="Obs", persona_id="sun", started_game=NOW))
check("set_active visible at once", getattr(store.get_active("Obs"), "persona_id", None), "sun")
check("old active columns not written", tuple(get_connection().execute(
    "SELECT granted_items, lock_before FROM transformation_active "
    "WHERE character_name='Obs'").fetchone()), ("[]", 0))
check("all_active", sorted(r.bearer for r in store.all_active()), ["Cara", "Obs"])
store.clear_active("Obs")
check("clear_active visible at once", store.get_active("Obs"), None)

# ── [D] knowers ─────────────────────────────────────────────────────────────
print("[D] knowers")
from app.models import secrets  # noqa: E402
sid = knowers.ensure_secret("Cara", moon)
check("ensure_secret idempotent", knowers.ensure_secret("Cara", moon), sid)
own = [s for s in secrets.list_secrets("Cara") if s.get("source_ref") == "transformation:moon"]
check("one secret with the ref", len(own), 1)
check("secret source", own[0].get("source"), "record")
check("secret content", own[0].get("content"), "I am secretly Moonveil.")
secrets.update_secret("Cara", sid, {"known_by": ["  kim"]})
check("knower casefold", knowers.knows("Kim", "Cara", "moon"), True)
check("non-knower", knowers.knows("Obs", "Cara", "moon"), False)
check("the bearer herself", knowers.knows("Cara", "Cara", "moon"), True)
check("knowers.add", knowers.add("Obs", "Cara", "moon"), True)
check("Obs knows after add", knowers.knows("Obs", "Cara", "moon"), True)
secrets.update_secret("Cara", sid, {"known_by": ["  kim"]})

# ── [E] names + providers ──────────────────────────────────────────────────
print("[E] an alias reserves nothing; no identity providers")
from app.core.character_name import character_name_problem  # noqa: E402
from app.core.hooks import get_providers  # noqa: E402
check("Moonveil free", character_name_problem("Moonveil"), None)
check("Sunward free", character_name_problem("Sunward"), None)
check("Dormant free", character_name_problem("Dormant"), None)
check("no identity providers",
      [cap for cap in ("identity.active_persona", "identity.knows", "identity.persona_names",
                       "identity.costume_items") if get_providers(cap)], [])

# ── [F] cooldown ────────────────────────────────────────────────────────────
print("[F] cooldown")
check("no cooldown yet", store.cooldown_until("Cara", "moon"), "")
store.set_cooldown("Cara", "moon", "Y0001-D002T10:00:00")
check("cooldown stored", store.cooldown_until("Cara", "moon"), "Y0001-D002T10:00:00")

# ── [G] reset store ─────────────────────────────────────────────────────────
print("[G] reset store")
from app.core.character_reset import SCOPE_MEMORY, SCOPE_REINIT, reset_character  # noqa: E402


def _rows(table, name):
    return get_connection().execute(
        f"SELECT COUNT(*) FROM {table} WHERE character_name=?", (name,)).fetchone()[0]


result = reset_character("Cara", scope=SCOPE_REINIT)
check("reset count", result.get("transformation"), 2)
check("reset errors", [e for e in result.get("errors", []) if e.get("store") == "transformation"], [])
check("active rows gone", _rows("transformation_active", "Cara"), 0)
check("cooldown rows gone", _rows("transformation_cooldown", "Cara"), 0)
check("reset invalidates the cache", store.get_active("Cara"), None)
store.set_active(store.ActiveRow(bearer="Cara", persona_id="moon", started_game=NOW))
result = reset_character("Cara", scope=SCOPE_MEMORY)
check("memory reset leaves the state", "transformation" in result, False)
check("active row kept", _rows("transformation_active", "Cara"), 1)
check("definitions survive both resets", len(store.list_definitions()), 7)

# ── [H] deletion sweep ─────────────────────────────────────────────────────
print("[H] character deletion")
from app.models.character import delete_character  # noqa: E402
store.set_active(store.ActiveRow(bearer="Obs", persona_id="sun", started_game=NOW))
check("delete Obs", delete_character("Obs"), True)
check("Obs active row swept", _rows("transformation_active", "Obs"), 0)

# ── [I] reload ─────────────────────────────────────────────────────────────
print("[I] reload")
loader.discover_packages(force=True)
check("state after reload", getattr(store.get_active("Cara"), "persona_id", None), "moon")

# ── [J] fresh table shape ──────────────────────────────────────────────────
print("[J] fresh tables")
with transaction() as conn:
    for _t in ("transformation_definitions", "transformation_active", "transformation_cooldown"):
        conn.execute(f"DROP TABLE {_t}")
store.ensure_schema()


def _cols(table):
    return [r[1] for r in get_connection().execute(f"PRAGMA table_info({table})")]


check("fresh definitions columns", _cols("transformation_definitions"),
      ["id", "item_id", "alias", "activation_phrase", "revert_phrase", "condition_id",
       "max_duration_minutes", "cooldown_minutes", "transform_activity", "enabled", "updated_at"])
check("fresh active columns", _cols("transformation_active"),
      ["character_name", "persona_id", "started_game", "until_game", "outfit_snapshot"])
store.invalidate()

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
