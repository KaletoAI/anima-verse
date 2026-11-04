#!/usr/bin/env python3
"""Smoke: the transformation engine — transform, revert, game-time expiry,
item loss and the narrator lines (``plugins/transformation/engine.py``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_engine.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The embedding is stubbed to "no model" so the
transform activity resolves through the catalog's default without loading a
model; the package is loaded the way the server loads it
(``packages.enabled = "transformation"``, ``discover_packages()``).

FIXTURE
    Items: "amulet" (tool, the power item), "suit_top" (outfit piece, slot
    top), "suit_bottom" (slot bottom), "shirt" (top), "boots" (feet).
    Characters Cara (bearer), Kim (knower), Obs (non-knower), all three in
    location "Inn", room "taproom". Cara carries amulet, shirt, boots and
    WEARS equipped_pieces = {"top": "shirt", "feet": "boots"}.
    Persona "p1": item amulet, alias "Moonveil", suit "suit_top,suit_bottom",
    condition "transformed_state" (a world prompt filter, so the condition
    catalog knows it), max_duration_minutes 60, cooldown_minutes 30.
    Game clock pinned at T0 = Y0002-D100T12:00:00 with factor 0 (it only moves
    when the smoke sets it).

THE RULES (task brief) and what follows BY HAND
[A] tick() before any transform: Cara holds the amulet -> her secret for p1
    exists (source_ref "transformation:p1"). Kim is then added as a knower.
[B] transform("Cara", "p1"):
    -> {"ok": True, "reason": "", "alias": "Moonveil"}.
    Suit covers top + bottom; the snapshot top (shirt) is replaced, the feet
    (boots) are not covered and stay:
      equipped_pieces == {"top": "suit_top", "bottom": "suit_bottom", "feet": "boots"}
    suit_top/suit_bottom were not carried -> granted, now carried; active row
    granted_items == ("suit_top", "suit_bottom").
    flag is_transformed True; active_conditions names contain
    "transformed_state" with duration_hours 0 (never expires on its own);
    outfit locked; shown_name("Obs","Cara") == "Moonveil",
    shown_name("Kim","Cara") == "Moonveil (Cara)".
    Transform activity "transforming" (persona default): no catalog alias,
    the stubbed embedding finds nothing -> the default key "standing" with
    flavor "transforming"; the active row remembers pose_key "standing".
    until_game == (T0 + 60 min).canonical() == "Y0002-D100T13:00:00".
    Narration "Cara transforms into Moonveil." reaches Cara and Kim (present
    knower), Obs has no perception row for that utterance.
[C] a second transform -> {"ok": False, "reason": "already_transformed"}.
    Unknown persona "nope" -> "unknown_persona"; Obs (no amulet) ->
    "not_holding_item".
[D] clock to T0 + 59 min, tick() -> nothing happens (13:00 not reached).
    clock to T0 + 61 min = Y0002-D100T13:01:00, tick() -> reverted "expired":
      equipped_pieces == {"top": "shirt", "feet": "boots"}
      suit_top, suit_bottom no longer carried; condition gone; flag False;
      outfit lock back to False; shown_name("Obs","Cara") == "Cara";
      the pose is still the remembered "standing" -> cleared (flavor "");
      cooldown_until == (13:01 + 30 min) == "Y0002-D100T13:31:00".
    Narration "Moonveil turns back into Cara." reaches Cara + Kim, not Obs.
[E] transform at 13:01 -> "cooldown" (13:01 < 13:31). Clock to 13:32
    (revert + 31 min, past 13:31) -> ok. Before it the outfit lock is set
    True, so the active row remembers lock_before True.
[F] item left: transfer_item("Cara", "Kim", "amulet"), tick() -> revert with
    reason "item_lost" (spy on engine.revert); outfit back to
    {"top": "shirt", "feet": "boots"}; outfit lock restored to True (it was
    True before this transform); shown_name("Obs","Cara") == "Cara".
    The same tick sees Kim holding the amulet -> Kim's own secret for p1
    exists now.
[G] revert of someone not transformed -> False.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-engine-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")

PERSONA = {"id": "p1", "item_id": "amulet", "alias": "Moonveil",
           "description": "A figure in moonlit silver.",
           "suit_items": "suit_top,suit_bottom", "condition_id": "transformed_state",
           "max_duration_minutes": 60, "cooldown_minutes": 30}
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
    "skills": {"transformation_personas": [PERSONA]},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core.db import get_connection, transaction  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import game_time, set_game_factor, set_game_time  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import (get_character_profile, is_outfit_locked,  # noqa: E402
                                  save_character_profile, set_outfit_locked)
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

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


T0 = GameTime.parse("Y0002-D100T12:00:00")
set_game_factor(0.0)
set_game_time(T0)


def at(minutes):
    set_game_time(T0 + GameDuration.of(minutes=minutes))


# ── world ───────────────────────────────────────────────────────────────────
with transaction() as conn:
    conn.execute("INSERT OR REPLACE INTO prompt_filters (id, label, condition, prompt_modifier, "
                 "enabled, meta) VALUES (?,?,?,?,?,?)",
                 ("transformed_state", "Transformed", "", "You are transformed.", 1, "{}"))
from app.core.prompt_filters import invalidate_filter_snapshot  # noqa: E402
invalidate_filter_snapshot()

INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = "taproom"
        assert save_character_profile(_name, _p)

inventory.add_item("Amulet", item_id="amulet")
inventory.add_item("Suit top", category="outfit_piece", item_id="suit_top",
                   outfit_piece={"slots": ["top"]})
inventory.add_item("Suit bottom", category="outfit_piece", item_id="suit_bottom",
                   outfit_piece={"slots": ["bottom"]})
inventory.add_item("Shirt", category="outfit_piece", item_id="shirt",
                   outfit_piece={"slots": ["top"]})
inventory.add_item("Boots", category="outfit_piece", item_id="boots",
                   outfit_piece={"slots": ["feet"]})
for _iid in ("amulet", "shirt", "boots"):
    assert inventory.add_to_inventory("Cara", _iid)
with keyed_lock("character_profile", "Cara"):
    inventory.apply_equipped_pieces("Cara", pieces={"top": "shirt", "feet": "boots"},
                                    source="smoke")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import identity_view, perception  # noqa: E402
from app.models import secrets  # noqa: E402
from plugins.transformation import engine, knowers, store  # noqa: E402

check("Cara in the room", perception.addressable_for("Cara"), ["Kim", "Obs"])
check("Cara wears shirt + boots", get_character_profile("Cara").get("equipped_pieces"),
      {"top": "shirt", "feet": "boots"})


def pieces():
    return get_character_profile("Cara").get("equipped_pieces") or {}


def conditions():
    return [c.get("name") for c in get_character_profile("Cara").get("active_conditions") or []
            if isinstance(c, dict)]


def secret_of(holder):
    return [s for s in secrets.list_secrets(holder)
            if s.get("source_ref") == "transformation:p1"]


def line_rows(content):
    """Perceivers of every utterance with exactly this content."""
    conn = get_connection()
    ids = [r[0] for r in conn.execute("SELECT id FROM utterances WHERE content=?", (content,))]
    out = set()
    for uid in ids:
        out.update(r[0] for r in conn.execute(
            "SELECT perceiver FROM perceptions WHERE utterance_id=?", (uid,)))
    return ids, out


# ── [A] secret before the first transform ───────────────────────────────────
print("[A] tick ensures the holder's secret")
check("no secret yet", len(secret_of("Cara")), 0)
engine.tick()
check("Cara's secret exists after tick", len(secret_of("Cara")), 1)
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)

# ── [B] transform ───────────────────────────────────────────────────────────
print("[B] transform")
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})
check("suit on, boots kept", pieces(), {"top": "suit_top", "bottom": "suit_bottom", "feet": "boots"})
carried = inventory.get_carried_item_ids("Cara")
check("suit_top granted", "suit_top" in carried, True)
check("suit_bottom granted", "suit_bottom" in carried, True)
row = store.get_active("Cara")
check("granted_items", getattr(row, "granted_items", None), ("suit_top", "suit_bottom"))
check("until_game", getattr(row, "until_game", None), "Y0002-D100T13:00:00")
check("flag set", get_character_profile("Cara").get("is_transformed"), True)
check("condition applied", "transformed_state" in conditions(), True)
_cond = [c for c in get_character_profile("Cara").get("active_conditions") or []
         if isinstance(c, dict) and c.get("name") == "transformed_state"]
check("condition never expires on its own", _cond[0].get("duration_hours") if _cond else None, 0)
check("outfit locked", is_outfit_locked("Cara"), True)
check("Obs sees the alias", identity_view.shown_name("Obs", "Cara"), "Moonveil")
_prof = get_character_profile("Cara")
check("transform activity shown", _prof.get("pose_flavor"), "transforming")
check("its catalog key remembered", row.outfit_snapshot.get("pose_key"), _prof.get("pose_key"))
check("Kim sees through it", identity_view.shown_name("Kim", "Cara"), "Moonveil (Cara)")
_ids, _who = line_rows("Cara transforms into Moonveil.")
check("one transform line", len(_ids), 1)
check("transform line reaches Cara + Kim only", _who, {"Cara", "Kim"})

# ── [C] refusals ────────────────────────────────────────────────────────────
print("[C] refusals")
check("second transform", engine.transform("Cara", "p1", source="smoke")["reason"],
      "already_transformed")
check("unknown persona", engine.transform("Cara", "nope", source="smoke")["reason"],
      "unknown_persona")
check("Obs holds no amulet", engine.transform("Obs", "p1", source="smoke")["reason"],
      "not_holding_item")

# ── [D] expiry ──────────────────────────────────────────────────────────────
print("[D] expiry")
at(59)
engine.tick()
check("still transformed at 12:59", store.get_active("Cara") is not None, True)
at(61)
engine.tick()
check("reverted at 13:01", store.get_active("Cara"), None)
check("outfit restored", pieces(), {"top": "shirt", "feet": "boots"})
carried = inventory.get_carried_item_ids("Cara")
check("suit_top taken back", "suit_top" in carried, False)
check("suit_bottom taken back", "suit_bottom" in carried, False)
check("shirt still carried", "shirt" in carried, True)
check("condition removed", "transformed_state" in conditions(), False)
check("flag cleared", get_character_profile("Cara").get("is_transformed"), False)
check("outfit lock back to False", is_outfit_locked("Cara"), False)
check("Obs sees Cara again", identity_view.shown_name("Obs", "Cara"), "Cara")
check("transform activity cleared", get_character_profile("Cara").get("pose_flavor"), "")
check("cooldown until", store.cooldown_until("Cara", "p1"), "Y0002-D100T13:31:00")
_ids, _who = line_rows("Moonveil turns back into Cara.")
check("one revert line", len(_ids), 1)
check("revert line reaches Cara + Kim only", _who, {"Cara", "Kim"})

# ── [E] cooldown ────────────────────────────────────────────────────────────
print("[E] cooldown")
check("immediate transform", engine.transform("Cara", "p1", source="smoke")["reason"], "cooldown")
at(61 + 31)
set_outfit_locked("Cara", True)
check("transform after the cooldown", engine.transform("Cara", "p1", source="smoke")["ok"], True)
check("lock_before remembered", getattr(store.get_active("Cara"), "lock_before", None), True)

# ── [F] item lost ───────────────────────────────────────────────────────────
print("[F] item left -> reverted")
_reasons = []
_real_revert = engine.revert


def _spy(bearer, *, reason):
    _reasons.append((bearer, reason))
    return _real_revert(bearer, reason=reason)


engine.revert = _spy
try:
    check("amulet handed to Kim", inventory.transfer_item("Cara", "Kim", "amulet"), True)
    engine.tick()
finally:
    engine.revert = _real_revert
check("item left -> reverted", _reasons, [("Cara", "item_lost")])
check("not active", store.get_active("Cara"), None)
check("outfit restored again", pieces(), {"top": "shirt", "feet": "boots"})
check("outfit lock restored to True", is_outfit_locked("Cara"), True)
check("Obs sees Cara", identity_view.shown_name("Obs", "Cara"), "Cara")
check("Kim, the new holder, has a secret now", len(secret_of("Kim")), 1)

# ── [G] revert of nobody ────────────────────────────────────────────────────
print("[G] revert without a transformation")
check("revert Obs", engine.revert("Obs", reason="admin"), False)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
