#!/usr/bin/env python3
"""Smoke: the transformation engine as a body swap — transform, revert,
game-time expiry, refusals retried, item loss and the narration
(``plugins/transformation/engine.py``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_engine.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The embedding is stubbed to "no model" so the
transform activity resolves through the catalog's default without loading a
model; the package is loaded the way the server loads it
(``packages.enabled = "transformation"``, ``discover_packages()``).

THE SPEC (``docs/superpowers/specs/2026-11-05-linked-characters-design.md`` →
"Transformation package", "Swap rules"): ``transform(leader, def)`` checks
the item held by the leader, the cooldown (the admin ignores it) and the swap
rules -> ``swap_presence(leader, body, items=[item_id])``, applies the
condition to the BODY, records the active row and narrates. ``revert`` needs
the item on the body -> ``swap_presence(body, leader, items=[item_id])``,
cooldown on the leader. ``tick()`` reverts at the end of the maximum duration
(a refused automatic revert retries on the next tick, never forced) and when
the body no longer holds the item (wherever it stands). The package answers
``linked.expected_present`` with the body while transformed.

FIXTURE
    Location "Inn", room "taproom". Tilda (leader) stands there at point
    (1.5, 2.5) yaw 0.75 and carries the "amulet"; Glut = create_linked(Tilda,
    "Glut") (dormant). Kim (knower of Glut) and Obs (non-knower) in the
    taproom. Definition "glut": leader Tilda, body Glut, item amulet,
    condition "transformed_state" (a world prompt filter, so the condition
    catalog knows it), max 60, cooldown 30. GAME clock pinned at
    T0 = Y0002-D100T12:00:00, factor 0.

THE RULES, and what follows BY HAND
[A] Refusals before anything moves:
    transform("Obs", "glut") -> reason "unknown_definition" (not its leader);
    transform("Tilda", "nope") -> "unknown_definition";
    Tilda in a refusal state (movement_target set) -> reason "refused",
      refusal "journey", error SWAP_REFUSAL_TEXT["journey"]; Tilda still
      present, Glut dormant, no active row.
    expected_present provider for Tilda -> None (nothing active).
[B] transform("Tilda", "glut") -> {"ok": True, "reason": "", "body": "Glut",
    "error": ""}.
    Tilda: status "dormant", no location. Glut: status "", Inn/taproom, point
    (1.5, 2.5, 0.75). Amulet: carried by Glut, not by Tilda.
    Condition "transformed_state" on Glut (duration_hours 0), not on Tilda.
    Flag is_transformed True on Glut. Transform activity "transforming": no
    catalog alias, the stubbed embedding finds nothing -> key "standing",
    flavor "transforming" on Glut.
    Active row: leader Tilda, body Glut, def_id glut, started T0, until
    T0 + 60 min = "Y0002-D100T13:00:00", snapshot {"item_id": "amulet",
    "condition_id": "transformed_state", "pose_key": "standing"}.
    Narration "Tilda transforms into Glut." perceived by {Glut, Kim} (the
    present knower); Obs none. Provider linked.expected_present("Tilda") ->
    "Glut".
[C] transform again -> "already_transformed".
[D] Expiry with a refusal: clock T0 + 59 -> tick -> still active. Glut gets a
    movement_target, clock T0 + 61 = 13:01 -> tick -> still active (refused,
    never forced), Glut still present; a second tick -> still active. Target
    cleared -> tick -> reverted:
      Tilda status "", Inn/taproom, point (1.5, 2.5, 0.75); Glut dormant;
      amulet back with Tilda; condition and flag gone from Glut; Tilda's pose
      is the copied "standing" == the snapshot key -> cleared (flavor "");
      cooldown on Tilda until 13:01 + 30 = "Y0002-D100T13:31:00".
    Narration "Glut turns back into Tilda." perceived by {Tilda, Kim}.
[E] Cooldown: transform at 13:01 -> "cooldown"; ignore_cooldown=True -> ok;
    revert(reason "admin") -> ok, cooldown again "Y0002-D100T13:31:00";
    clock 13:32 -> an in-game transform is ok.
[F] Item: Glut hands the amulet to Kim -> revert(reason "verb") ->
    {"ok": False, "reason": "not_holding_item"} (the body must carry it);
    tick -> reverted with reason "item_lost" (spy on engine.revert): Tilda
    present, Glut dormant, the amulet stays with Kim.
[G] revert of nobody -> {"ok": False, "reason": "not_transformed"}.
[H] Disabled while running (review fix round 1): the amulet goes back to
    Tilda, the admin transform (ignores the cooldown) -> ok. Glut gets a
    movement_target, the definition is switched off -> tick -> revert reason
    "disabled" refused, still active; tick again -> still active (retried,
    never forced). Target cleared -> tick -> reverted with "disabled": Tilda
    present, Glut dormant, the amulet back with Tilda. Switched on again.
[I] Reset while transformed (review fix round 1, spec R3): admin transform
    -> ok. reset_character("Tilda", reinit) -> ValueError "… revert first …"
    (the core refuses re-placing a dormant leader); the active row stays. The
    package's reset handler called directly on Tilda (store.delete_character_
    rows) keeps the active row too (its body Glut stands in the world); it
    deletes only Tilda's cooldown row for glut (from [H]) -> 1. Admin revert
    -> ok; the handler now finds no active row.
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
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core import hooks  # noqa: E402
from app.core import linked_characters as lc  # noqa: E402
from app.core.db import get_connection, transaction  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models import character as ch  # noqa: E402
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


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        for k, v in values.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
        assert ch.save_character_profile(name, p), name


def where(name):
    p = ch.get_character_profile(name)
    return (ch.get_character_status(name), p.get("current_location", ""),
            p.get("current_room", ""))


def point(name):
    row = get_connection().execute(
        "SELECT pos_x, pos_z, pos_yaw FROM character_state WHERE character_name=?",
        (name,)).fetchone()
    return tuple(row) if row else None


def conditions(name):
    return [c.get("name") for c in ch.get_character_profile(name).get("active_conditions") or []
            if isinstance(c, dict)]


def line_rows(content):
    """Perceivers of every utterance with exactly this content."""
    conn = get_connection()
    ids = [r[0] for r in conn.execute("SELECT id FROM utterances WHERE content=?", (content,))]
    out = set()
    for uid in ids:
        out.update(r[0] for r in conn.execute(
            "SELECT perceiver FROM perceptions WHERE utterance_id=?", (uid,)))
    return ids, out


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

for _name in ("Tilda", "Kim", "Obs"):
    assert ch.save_character_profile(_name, {"character_name": _name,
                                             "template": "human-roleplay"},
                                     create_new=True), _name
    edit(_name, current_location=INN, current_room="taproom")
with transaction() as conn:
    conn.execute("UPDATE character_state SET pos_x=1.5, pos_z=2.5, pos_yaw=0.75 "
                 "WHERE character_name='Tilda'")
check("Glut created", lc.create_linked("Tilda", "Glut")["ok"], True)

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Tilda", "amulet")

from plugins.transformation import store as tstore  # noqa: E402
tstore.ensure_schema()
tstore.create_definition({"leader": "Tilda", "body": "Glut", "item_id": "amulet",
                          "condition_id": "transformed_state",
                          "max_duration_minutes": 60, "cooldown_minutes": 30})

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from plugins.transformation import engine, knowers, store  # noqa: E402

check("Kim made a knower of Glut", knowers.add("Kim", "Glut"), True)
expected = hooks.get_provider(lc.EXPECTED_PRESENT_PROVIDER)
check("expected_present provider registered", callable(expected), True)

# ── [A] refusals ────────────────────────────────────────────────────────────
print("[A] refusals")
check("Obs is not the leader", engine.transform("Obs", "glut", source="smoke")["reason"],
      "unknown_definition")
check("unknown definition", engine.transform("Tilda", "nope", source="smoke")["reason"],
      "unknown_definition")
edit("Tilda", movement_target="somewhere")
_r = engine.transform("Tilda", "glut", source="smoke")
check("refusal state", (_r.get("ok"), _r.get("reason"), _r.get("refusal"), _r.get("error")),
      (False, "refused", "journey", lc.SWAP_REFUSAL_TEXT["journey"]))
check("Tilda still present", where("Tilda"), ("", INN, "taproom"))
check("Glut still dormant", ch.get_character_status("Glut"), "dormant")
check("no active row", store.get_active("Tilda"), None)
check("provider: nothing active", expected("Tilda"), None)
edit("Tilda", movement_target="")

# ── [B] transform ───────────────────────────────────────────────────────────
print("[B] transform")
check("transform ok", engine.transform("Tilda", "glut", source="smoke"),
      {"ok": True, "reason": "", "body": "Glut", "error": ""})
check("Tilda dormant", where("Tilda"), ("dormant", "", ""))
check("Glut present in her place", where("Glut"), ("", INN, "taproom"))
check("Glut on her point", point("Glut"), (1.5, 2.5, 0.75))
check("amulet with Glut", "amulet" in inventory.get_carried_item_ids("Glut"), True)
check("amulet not with Tilda", "amulet" in inventory.get_carried_item_ids("Tilda"), False)
check("condition on Glut", "transformed_state" in conditions("Glut"), True)
check("no condition on Tilda", "transformed_state" in conditions("Tilda"), False)
_cond = [c for c in ch.get_character_profile("Glut").get("active_conditions") or []
         if isinstance(c, dict) and c.get("name") == "transformed_state"]
check("condition never expires on its own", _cond[0].get("duration_hours") if _cond else None, 0)
check("flag on Glut", ch.get_character_profile("Glut").get("is_transformed"), True)
_prof = ch.get_character_profile("Glut")
check("transform activity on Glut", (_prof.get("pose_key"), _prof.get("pose_flavor")),
      ("standing", "transforming"))
row = store.get_active("Tilda")
check("active row", (row.leader, row.body, row.def_id, row.started_game, row.until_game)
      if row else None, ("Tilda", "Glut", "glut", "Y0002-D100T12:00:00", "Y0002-D100T13:00:00"))
check("snapshot", row.snapshot if row else None,
      {"item_id": "amulet", "condition_id": "transformed_state", "pose_key": "standing"})
_ids, _who = line_rows("Tilda transforms into Glut.")
check("one transform line", len(_ids), 1)
check("transform line reaches Glut + Kim only", _who, {"Glut", "Kim"})
check("provider names the body", expected("Tilda"), "Glut")

# ── [C] again ───────────────────────────────────────────────────────────────
print("[C] already transformed")
check("second transform", engine.transform("Tilda", "glut", source="smoke")["reason"],
      "already_transformed")

# ── [D] expiry, refused first ───────────────────────────────────────────────
print("[D] expiry with a refusal")
at(59)
engine.tick()
check("still transformed at 12:59", store.get_active("Tilda") is not None, True)
edit("Glut", movement_target="somewhere")
at(61)
engine.tick()
check("refused at 13:01 -> still active", store.get_active("Tilda") is not None, True)
check("Glut still present", where("Glut"), ("", INN, "taproom"))
engine.tick()
check("retried, still refused", store.get_active("Tilda") is not None, True)
edit("Glut", movement_target="")
engine.tick()
check("reverted", store.get_active("Tilda"), None)
check("Tilda back", where("Tilda"), ("", INN, "taproom"))
check("Tilda on the point", point("Tilda"), (1.5, 2.5, 0.75))
check("Glut dormant", ch.get_character_status("Glut"), "dormant")
check("amulet back with Tilda", "amulet" in inventory.get_carried_item_ids("Tilda"), True)
check("condition gone from Glut", "transformed_state" in conditions("Glut"), False)
check("flag cleared on Glut", bool(ch.get_character_profile("Glut").get("is_transformed")), False)
check("transform activity cleared on Tilda", ch.get_character_profile("Tilda").get("pose_flavor"),
      "")
check("cooldown on Tilda", store.cooldown_until("Tilda", "glut"), "Y0002-D100T13:31:00")
_ids, _who = line_rows("Glut turns back into Tilda.")
check("one revert line", len(_ids), 1)
check("revert line reaches Tilda + Kim only", _who, {"Tilda", "Kim"})

# ── [E] cooldown ────────────────────────────────────────────────────────────
print("[E] cooldown")
check("immediate transform", engine.transform("Tilda", "glut", source="smoke")["reason"],
      "cooldown")
check("the admin ignores the cooldown",
      engine.transform("Tilda", "glut", source="admin", ignore_cooldown=True)["ok"], True)
check("admin revert", engine.revert("Tilda", reason="admin")["ok"], True)
check("cooldown again", store.cooldown_until("Tilda", "glut"), "Y0002-D100T13:31:00")
at(61 + 31)
check("transform after the cooldown", engine.transform("Tilda", "glut", source="smoke")["ok"],
      True)

# ── [F] item lost ───────────────────────────────────────────────────────────
print("[F] item left the body")
check("amulet handed to Kim", inventory.transfer_item("Glut", "Kim", "amulet"), True)
check("verb revert needs the item",
      {k: v for k, v in engine.revert("Tilda", reason="verb").items() if k in ("ok", "reason")},
      {"ok": False, "reason": "not_holding_item"})
_reasons = []
_real_revert = engine.revert


def _spy(leader, *, reason):
    _reasons.append((leader, reason))
    return _real_revert(leader, reason=reason)


engine.revert = _spy
try:
    engine.tick()
finally:
    engine.revert = _real_revert
check("item left -> reverted", _reasons, [("Tilda", "item_lost")])
check("not active", store.get_active("Tilda"), None)
check("Tilda present", where("Tilda"), ("", INN, "taproom"))
check("Glut dormant again", ch.get_character_status("Glut"), "dormant")
check("amulet stays with Kim", "amulet" in inventory.get_carried_item_ids("Kim"), True)

# ── [G] revert of nobody ────────────────────────────────────────────────────
print("[G] revert without a transformation")
check("revert Obs", engine.revert("Obs", reason="admin"),
      {"ok": False, "reason": "not_transformed", "error": ""})

# ── [H] disabled while running ──────────────────────────────────────────────
print("[H] definition switched off while running")
check("amulet back to Tilda", inventory.transfer_item("Kim", "Tilda", "amulet"), True)
check("admin transform", engine.transform("Tilda", "glut", source="admin",
                                          ignore_cooldown=True)["ok"], True)
edit("Glut", movement_target="somewhere")
store.update_definition("glut", {"enabled": False})
_reasons = []
engine.revert = _spy
try:
    engine.tick()
    check("disabled -> revert tried, refused", (_reasons, store.get_active("Tilda") is not None),
          ([("Tilda", "disabled")], True))
    engine.tick()
    check("retried, still refused", (len(_reasons), store.get_active("Tilda") is not None),
          (2, True))
    edit("Glut", movement_target="")
    engine.tick()
finally:
    engine.revert = _real_revert
check("reverted as disabled", (_reasons[-1:], store.get_active("Tilda")),
      ([("Tilda", "disabled")], None))
check("Tilda present, Glut dormant", (where("Tilda")[0], ch.get_character_status("Glut")),
      ("", "dormant"))
check("amulet back with Tilda", "amulet" in inventory.get_carried_item_ids("Tilda"), True)
store.update_definition("glut", {"enabled": True})

# ── [I] reset while transformed ─────────────────────────────────────────────
print("[I] reset of a transformed leader")
from app.core.character_reset import SCOPE_REINIT, reset_character  # noqa: E402
check("admin transform", engine.transform("Tilda", "glut", source="admin",
                                          ignore_cooldown=True)["ok"], True)
try:
    reset_character("Tilda", SCOPE_REINIT)
    _err = ""
except ValueError as e:
    _err = str(e)
check("reinit of the dormant leader refused", "revert first" in _err, True)
check("active row kept", store.get_active("Tilda") is not None, True)
with transaction() as conn:
    _n = store.delete_character_rows(conn, "Tilda")
store.invalidate()
check("handler keeps the active row while Glut stands",
      (_n, store.get_active("Tilda") is not None), (1, True))
check("admin revert", engine.revert("Tilda", reason="admin")["ok"], True)
with transaction() as conn:
    _n = store.delete_character_rows(conn, "Tilda")
store.invalidate()
check("handler afterwards: the new cooldown row", _n, 1)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
