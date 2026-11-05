#!/usr/bin/env python3
"""Smoke: the transformation package skeleton — definitions, active state,
knowers and the three identity providers (``plugins/transformation/``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_store.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any world-DB module is
imported), no server, no real world DB, no LLM. The package is loaded the way
the server loads it: ``packages.enabled = "transformation"`` in the world
config, then ``discover_packages()`` runs its ``on_load`` (``register.py``).

FIXTURE (``store.create_definition``, in this order — the store writes rows as
given, the usability rules are ``definitions.load()``'s)
    #1 id "moon"     item "moon_brooch" alias "Moonveil"  suit "silver_mask, , silver_cape"
                     max 0, cooldown 15, activity "glowing", description "A masked figure in silver."
    #2 id "noalias"  item "x"           alias ""          -> skipped: lacks alias
    #3 id "dup"      item "y"           alias "moonveil"  -> skipped: duplicate alias (casefold of #1)
    #4 id "kimclash" item "z"           alias "KIM"       -> skipped: collides with character Kim
    #5 id "off"      item "w"           alias "Dormant"   enabled false -> skipped: disabled
    #6 id "moon"     item "v"           alias "Other"     -> refused by the table (PRIMARY KEY)
    #7 id "sun"      item "sun_ring"    alias "Sunward"   (only the required fields)
    Characters Cara (bearer), Kim (knower), Obs (non-knower). Item "moon_brooch"
    has an image, "sun_ring" has none.

THE RULES (task brief), and what follows BY HAND
[A] Storage (task 2): the world config list ``skills.transformation_personas``
    is gone — no package subsection in the registry, none in
    ``config_schema.get_schema()["skills"]`` or the world-scope schema
    (``config_scope.schema_for("world")``, what Setup → Skills renders). The
    personas are rows of ``transformation_definitions``: #6 raises
    ``sqlite3.IntegrityError`` (id taken), so does a second row for item
    "moon_brooch" (``item_id`` UNIQUE); 6 rows stored. ``list_definitions``
    keeps creation order; #1's suit is stored as
    ["silver_mask", "silver_cape"] (blank member dropped). A row created
    without id gets a slug of its alias: "Ünder Moon!" -> "under_moon", the
    next one with the same alias "under_moon_2", an alias without one ASCII
    letter -> "persona". Every write bumps ``definitions_generation()``.
[B] definitions.load(): kept = {"moon", "sun"} (#2..#5 skipped as listed).
    moon: suit_items = ("silver_mask", "silver_cape") (blank member dropped),
          max 0, cooldown 15, activity "glowing".
    sun:  table defaults = the constants in ``definitions`` — enabled True,
          max 60, cooldown 30, activity "transforming", suit_items = (),
          description "".
    for_item("moon_brooch").id = "moon"; for_item("nothing") = None.
    An ``update_definition`` is seen by the next ``load()`` at once (the
    write generation is the cache key): sun's cooldown 45 -> 45, back to 30.
[C] cache rebuilt from table: a row written straight into
    ``transformation_active`` (as a restart would find it) is visible after
    ``store.invalidate()`` -> active_persona("Cara").alias = "Moonveil",
    description "A masked figure in silver.", portrait_url
    "/inventory/items/moon_brooch/image" (the item has an image). Obs wears
    nothing -> None. A "sun" bearer -> portrait_url "" (no item image).
    set_active/clear_active are visible at once (they invalidate).
    get_active returns the stored JSON columns parsed: outfit_snapshot dict,
    granted_items tuple, lock_before bool.
[D] knowers: ensure_secret twice -> the same id, exactly one secret with
    source_ref "transformation:moon", source "record", content
    "I am secretly Moonveil.". knower casefold: known_by = ["  kim"] (as the
    Secrets editor may store it) -> identity_view.knows("Kim", "Cara") True,
    shown_name("Kim", "Cara") = "Moonveil (Cara)"; Obs -> False, "Moonveil".
    knowers.add("Obs", "Cara", "moon") -> True, then Obs knows.
[E] reserved names: character_name_problem("Moonveil") and ("moonveil") are
    not None (configured alias); "Sunward" not None (configured, not worn);
    "Dormant" None (disabled record reserves nothing).
    persona_names() = {"Moonveil", "Sunward"}.
[F] cooldown: cooldown_until before any write = ""; after
    set_cooldown("Cara", "moon", "Y0001-D002T10:00:00") that string.
[G] reset store: reset_character("Cara", reinit) reports
    result["transformation"] = 2 (1 active row + 1 cooldown row), both tables
    hold 0 rows of Cara afterwards and active_persona("Cara") is None.
    A memory-scope reset keeps the state (it is mechanical state, not memory):
    after re-arming, reset_character("Cara", memory) has no "transformation"
    key and the active row stays. Neither reset touches the definitions (world
    content): still 6 rows.
[H] deletion: delete_character("Obs") sweeps Obs's active row (the tables key
    the character in a ``character_name`` column, which the delete sweep
    covers).
[I] reload: a second discover_packages(force=True) runs on_load again without
    error and the providers still answer ("Moonveil").
[J] deletion test: with the package's providers unregistered,
    shown_name("Obs", "Cara") = "Cara".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="transformation-store-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="transformation-clips-")

RECORDS = [
    {"id": "moon", "item_id": "moon_brooch", "alias": "Moonveil",
     "description": "A masked figure in silver.",
     "suit_items": "silver_mask, , silver_cape", "max_duration_minutes": 0,
     "cooldown_minutes": 15, "transform_activity": "glowing"},
    {"id": "noalias", "item_id": "x", "alias": ""},
    {"id": "dup", "item_id": "y", "alias": "moonveil"},
    {"id": "kimclash", "item_id": "z", "alias": "KIM"},
    {"id": "off", "item_id": "w", "alias": "Dormant", "enabled": False},
    {"id": "moon", "item_id": "v", "alias": "Other"},
    {"id": "sun", "item_id": "sun_ring", "alias": "Sunward"},
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


for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name}, create_new=True)

from app.models import inventory  # noqa: E402
inventory.add_item("Moon brooch", item_id="moon_brooch")
inventory.set_item_image("moon_brooch", "image.png")
inventory.add_item("Sun ring", item_id="sun_ring")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

# ── [A] storage ────────────────────────────────────────────────────────────
print("[A] definitions table, no config list")
import sqlite3  # noqa: E402
from app.core import config_schema, config_scope  # noqa: E402
from plugins.transformation import definitions, knowers, store  # noqa: E402
check("no registry subsection", "transformation_personas" in registry.config_subsections(), False)
check("no schema subsection",
      "transformation_personas" in (config_schema.get_schema()["skills"].get("subsections") or {}),
      False)
check("not in Setup → Skills (world schema)",
      "transformation_personas" in ((config_scope.schema_for(config_scope.WORLD).get("skills") or {})
                                    .get("subsections") or {}),
      False)
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
      ["moon", "noalias", "dup", "kimclash", "off", "sun"])
check("suit stored as a clean list", store.get_definition("moon")["suit_items"],
      ["silver_mask", "silver_cape"])
check("writes bump the generation", store.definitions_generation() > _gen0, True)
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
check("kept ids", sorted(defs), ["moon", "sun"])
moon, sun = defs["moon"], defs["sun"]
check("moon alias", moon.alias, "Moonveil")
check("moon item", moon.item_id, "moon_brooch")
check("moon suit_items", moon.suit_items, ("silver_mask", "silver_cape"))
check("moon max", moon.max_duration_minutes, 0)
check("moon cooldown", moon.cooldown_minutes, 15)
check("moon activity", moon.transform_activity, "glowing")
check("sun enabled", sun.enabled, True)
check("sun max default", sun.max_duration_minutes, 60)
check("sun cooldown default", sun.cooldown_minutes, 30)
check("sun activity default", sun.transform_activity, "transforming")
check("sun suit default", sun.suit_items, ())
check("sun description default", sun.description, "")
check("for_item moon_brooch", getattr(definitions.for_item("moon_brooch"), "id", None), "moon")
check("for_item unknown", definitions.for_item("nothing"), None)
store.update_definition("sun", {"cooldown_minutes": 45})
check("update seen at once", definitions.load()["sun"].cooldown_minutes, 45)
store.update_definition("sun", {"cooldown_minutes": 30})

# ── [C] active state + cache ────────────────────────────────────────────────
print("[C] active state")
from app.core import identity_view  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402
NOW = game_time().canonical()
check("Cara not transformed yet", identity_view.active_persona("Cara"), None)
with transaction() as conn:   # what a restart finds in the table
    conn.execute("INSERT INTO transformation_active (character_name, persona_id, started_game, "
                 "until_game, outfit_snapshot, granted_items, lock_before) VALUES (?,?,?,?,?,?,?)",
                 ("Cara", "moon", NOW, "", json.dumps({"outfit": ["dress"]}),
                  json.dumps(["silver_mask"]), 1))
store.invalidate()
persona = identity_view.active_persona("Cara")
check("cache rebuilt from table", getattr(persona, "alias", None), "Moonveil")
check("persona description", getattr(persona, "description", None), "A masked figure in silver.")
check("persona portrait", getattr(persona, "portrait_url", None), "/inventory/items/moon_brooch/image")
check("persona id", getattr(persona, "persona_id", None), "moon")
row = store.get_active("Cara")
check("row outfit_snapshot", row.outfit_snapshot, {"outfit": ["dress"]})
check("row granted_items", row.granted_items, ("silver_mask",))
check("row lock_before", row.lock_before, True)
check("Obs wears nothing", identity_view.active_persona("Obs"), None)
store.set_active(store.ActiveRow(bearer="Obs", persona_id="sun", started_game=NOW))
check("set_active visible at once", getattr(identity_view.active_persona("Obs"), "alias", None), "Sunward")
check("no item image -> empty portrait", identity_view.active_persona("Obs").portrait_url, "")
check("all_active", sorted(r.bearer for r in store.all_active()), ["Cara", "Obs"])
store.clear_active("Obs")
check("clear_active visible at once", identity_view.active_persona("Obs"), None)

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
check("knower casefold", identity_view.knows("Kim", "Cara"), True)
check("knower label", identity_view.shown_name("Kim", "Cara"), "Moonveil (Cara)")
check("non-knower", identity_view.knows("Obs", "Cara"), False)
check("non-knower label", identity_view.shown_name("Obs", "Cara"), "Moonveil")
check("knowers.add", knowers.add("Obs", "Cara", "moon"), True)
check("Obs knows after add", knowers.knows("Obs", "Cara", "moon"), True)
secrets.update_secret("Cara", sid, {"known_by": ["  kim"]})

# ── [E] reserved names ─────────────────────────────────────────────────────
print("[E] reserved names")
from app.core.character_name import character_name_problem  # noqa: E402
check("Moonveil reserved", character_name_problem("Moonveil") is not None, True)
check("moonveil reserved", character_name_problem("moonveil") is not None, True)
check("Sunward reserved", character_name_problem("Sunward") is not None, True)
check("Dormant free", character_name_problem("Dormant"), None)
from app.core.hooks import get_provider  # noqa: E402
check("persona_names", set(get_provider(identity_view.PROVIDER_NAMES)()), {"Moonveil", "Sunward"})

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
check("reset invalidates the cache", identity_view.active_persona("Cara"), None)
store.set_active(store.ActiveRow(bearer="Cara", persona_id="moon", started_game=NOW))
result = reset_character("Cara", scope=SCOPE_MEMORY)
check("memory reset leaves the state", "transformation" in result, False)
check("active row kept", _rows("transformation_active", "Cara"), 1)
check("definitions survive both resets", len(store.list_definitions()), 6)

# ── [H] deletion sweep ─────────────────────────────────────────────────────
print("[H] character deletion")
from app.models.character import delete_character  # noqa: E402
store.set_active(store.ActiveRow(bearer="Obs", persona_id="sun", started_game=NOW))
check("delete Obs", delete_character("Obs"), True)
check("Obs active row swept", _rows("transformation_active", "Obs"), 0)

# ── [I] reload ─────────────────────────────────────────────────────────────
print("[I] reload")
loader.discover_packages(force=True)
check("providers answer after reload",
      getattr(identity_view.active_persona("Cara"), "alias", None), "Moonveil")

# ── [J] deletion test ──────────────────────────────────────────────────────
print("[J] package providers removed")
from app.core.hooks import unregister_owned_providers  # noqa: E402
unregister_owned_providers("transformation")
check("real name without the package", identity_view.shown_name("Obs", "Cara"), "Cara")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
