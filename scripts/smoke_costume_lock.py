#!/usr/bin/env python3
"""Smoke: the costume lock — a persona's suit pieces are wearable only by the
character who wears exactly that persona right now, and while she wears them
they stay on until she turns back (``app.core.identity_view`` costume
functions, the guards in ``app/models/inventory.py``, the compliance finder,
the ChangeOutfit index, the wardrobe payload/routes and the transformation
engine's bypass).

Usage:  ./.venv/bin/python scripts/smoke_costume_lock.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. Part 1 uses fake providers (``owner="smoke"``), part 2
the real ``plugins/transformation`` package.

FIXTURE
    Items (outfit pieces): suit_top (top), suit_mask (head), tee (top),
    hat (head), shirt (top), boots (feet), suit_bottom (bottom).
    Characters: Ann (language "en") owns suit_top, suit_mask, tee, hat.
    Bea (language "de") owns suit_top, suit_mask, tee, hat. Cid owns nothing.
    Cara (part 2, language "en") owns amulet, shirt, boots, suit_top (owned
    BEFORE any persona — the "pre-owned piece") and wears
    {"top": "shirt", "feet": "boots"}.

PART 1 — fake providers. ``identity.costume_items`` answers
    {"suit_top": "p1", "suit_mask": "p1"}; ``identity.active_persona`` answers
    for names in ACTIVE only: {"persona_id": "p1", "alias": "Moonveil",
    "suit_items": ["suit_top", "suit_mask"]}.
[A] No provider at all: costume_owner("suit_top") None, wear_refusal "",
    costume_pinned False; Ann equips suit_top -> ok (then takes it off).
[B] costume_items registered, nobody transformed:
    costume_owner("suit_top") == "p1", costume_owner("tee") is None.
    Ann (never a bearer, but OWNS it) equip suit_top -> error "costume";
    Bea (the bearer, not transformed) -> "costume" too. equip tee -> ok.
    equip_piece(..., allow_costume=True) passes -> ok (taken off again with
    allow_costume=True, it is not pinned anyway).
    apply_equipped_pieces(Ann, pieces={"top": "suit_top"}) -> skipped
    [{"item_id": "suit_top", "slot": "top", "reason": "costume"}]; the tee
    she wears sits in slot "top", which the target NAMES — step 1 leaves a
    named slot's occupant to its replacement, the replacement is skipped, so
    the tee stays (the existing skip semantics): pieces_after == {"top": "tee"}.
    Legacy worn piece: Ann's profile is written directly with
    {"head": "suit_mask"} (worn before the lock); apply with pieces
    {"head": "suit_mask", "top": "tee"} -> suit_mask skipped "costume" AND
    taken off; pieces_after == {"top": "tee"}.
[C] Compliance finder (outfit_compliance._find_inventory_piece_for_slot):
    Ann's inventory order is suit_top, suit_mask, tee, hat. Slot "top": the
    first single-slot top piece is suit_top, refused -> tee. Slot "head":
    suit_mask refused -> hat. exclude {"tee"} on "top" -> None (never the
    costume).
[D] ChangeOutfit: decision_menu("Ann") lists hat, tee (no suit piece; tee is
    worn -> "tee (top, worn)"); equip=["Suit top"] -> no match (the index
    has no suit piece) -> "nicht im Inventar", nothing equipped.
[E] Wardrobe payload: build_belongings("Ann") -> wear_lock of suit_top and
    suit_mask == "Costume — only while transformed", tee/hat "".
    Route _equip_route_sync(Ann, suit_top) -> HTTP 409, detail
    {"reason": "costume", "message": "Suit top is a costume piece: it can
    only be worn while transformed."} (Ann speaks "en").
[F] Bea transformed into p1 (ACTIVE = {"Bea"}): wear_refusal(Bea, suit_top)
    "" -> equip ok; costume_pinned(Bea, suit_top) True.
    unequip_piece(Bea, slot="top") -> {"status": "error", "reason":
    "costume_pinned", "item_id": "suit_top"}; equip tee (top) -> displaces
    suit_top -> "costume_pinned"; apply pieces={"top": "tee"} -> step 1
    meets the worn suit_top (not in the target, pinned) and keeps it
    (skipped {"item_id": "suit_top", "reason": "costume_pinned", "slot":
    "top"}), step 2 refuses tee because it would displace it (skipped
    {"item_id": "tee", "slot": "top", "reason": "costume_pinned"}; the suit
    is reported once), unchanged;
    remove_slots ["top"] -> unchanged, skipped suit_top "costume_pinned".
    remove_from_inventory -> False, still carried; drop_item -> success
    False, reason "costume_pinned"; transfer_item(Bea -> Cid) -> False and Cid
    has no suit_top; gift_item -> reason "costume_pinned".
    Route _unequip_route_sync(Bea, slot top) -> 409, German message
    "Das Kostüm bleibt an, bis Bea sich zurückverwandelt." (Bea speaks "de").
    Route DELETE (remove_inventory_item_route) -> 409 "costume_pinned".
    Ann is NOT the bearer: wear_refusal(Ann, suit_top) still "costume".
    unequip_piece(Bea, slot="top", allow_costume=True) -> ok (bypass).
[G] A raising costume provider -> costume_owner None, Ann may wear suit_top.
[H] Deletion: unregister_owned_providers("smoke") -> Ann equips suit_top ok,
    nobody pinned.

PART 2 — the real package. Persona p1: item amulet, alias "Moonveil", suit
    "suit_top,suit_bottom", max_duration_minutes 60, cooldown_minutes 0 (the
    table default would block the re-transforms of [L]/[M]). Game clock pinned at
    T0 = Y0002-D100T12:00:00, factor 0.
[I] Before: Cara equip suit_top (pre-owned) -> "costume".
[J] transform -> ok; worn {"top": "suit_top", "bottom": "suit_bottom",
    "feet": "boots"} (the suit wins top + bottom, boots stay); granted only
    suit_bottom (suit_top was carried) -> granted_items ("suit_bottom",).
    unequip top -> "costume_pinned"; equip shirt -> "costume_pinned".
[K] revert(reason="admin") (the admin "Revert now" path) -> True; worn
    {"top": "shirt", "feet": "boots"}; suit_bottom no longer carried;
    suit_top still carried but equip -> "costume".
[L] Half-way failure: the engine's set_state_flag raises once during the
    next transform -> the transform raises, worn again {"top": "shirt",
    "feet": "boots"}, suit_bottom not carried, no active row.
[M] Expiry: transform at T0, clock to T0 + 61 min, tick() -> reverted
    ("expired"): worn {"top": "shirt", "feet": "boots"}, suit_bottom gone.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="costume-lock-smoke-"))
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

from app.core import hooks, identity_view  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402

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


def http_error(fn, *args):
    """(status, detail) of the HTTPException ``fn`` raises, else (None, result)."""
    from fastapi import HTTPException
    try:
        return None, fn(*args)
    except HTTPException as e:
        return e.status_code, e.detail


def worn(name):
    return dict(get_character_profile(name).get("equipped_pieces") or {})


def set_worn(name, pieces):
    with keyed_lock("character_profile", name):
        p = get_character_profile(name)
        p["equipped_pieces"] = dict(pieces)
        assert save_character_profile(name, p)


# ── world ───────────────────────────────────────────────────────────────────
for _name, _lang in (("Ann", "en"), ("Bea", "de"), ("Cid", "en"), ("Cara", "en")):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay",
                                          "language": _lang}, create_new=True), _name

for _iid, _name, _slot in (("suit_top", "Suit top", "top"), ("suit_mask", "Suit mask", "head"),
                           ("tee", "Tee", "top"), ("hat", "Hat", "head"),
                           ("shirt", "Shirt", "top"), ("boots", "Boots", "feet"),
                           ("suit_bottom", "Suit bottom", "bottom")):
    inventory.add_item(_name, category="outfit_piece", item_id=_iid,
                       outfit_piece={"slots": [_slot]})
inventory.add_item("Amulet", item_id="amulet")
for _owner in ("Ann", "Bea"):
    for _iid in ("suit_top", "suit_mask", "tee", "hat"):
        assert inventory.add_to_inventory(_owner, _iid)

# ── PART 1: fake providers ──────────────────────────────────────────────────
ACTIVE = set()


def fake_active(subject):
    if subject not in ACTIVE:
        return None
    return {"persona_id": "p1", "alias": "Moonveil", "description": "",
            "portrait_url": "", "suit_items": ["suit_top", "suit_mask"]}


def fake_costumes():
    return {"suit_top": "p1", "suit_mask": "p1"}


print("[A] no provider: every item wearable")
check("costume_owner none", identity_view.costume_owner("suit_top"), None)
check("wear_refusal none", identity_view.wear_refusal("Ann", "suit_top"), "")
check("pinned none", identity_view.costume_pinned("Ann", "suit_top"), False)
check("Ann equips suit_top", inventory.equip_piece("Ann", "suit_top")["status"], "ok")
check("Ann takes it off", inventory.unequip_piece("Ann", slot="top")["status"], "ok")

print("[B] costume items known, nobody transformed")
hooks.register_provider(identity_view.PROVIDER_COSTUME, fake_costumes, owner="smoke")
hooks.register_provider(identity_view.PROVIDER_ACTIVE, fake_active, owner="smoke")
check("owner of suit_top", identity_view.costume_owner("suit_top"), "p1")
check("owner of tee", identity_view.costume_owner("tee"), None)
check("Ann equip suit_top refused", inventory.equip_piece("Ann", "suit_top"),
      {"status": "error", "reason": "costume"})
check("Bea (bearer, not transformed) refused", inventory.equip_piece("Bea", "suit_top"),
      {"status": "error", "reason": "costume"})
check("Ann equips tee", inventory.equip_piece("Ann", "tee")["status"], "ok")
check("allow_costume passes", inventory.equip_piece("Ann", "suit_mask", allow_costume=True)["status"],
      "ok")
check("allow_costume off again",
      inventory.unequip_piece("Ann", slot="head", allow_costume=True)["status"], "ok")
r = inventory.apply_equipped_pieces("Ann", pieces={"top": "suit_top"}, source="smoke")
check("apply skips the costume", r["skipped"],
      [{"item_id": "suit_top", "slot": "top", "reason": "costume"}])
check("apply: the tee stays", r["pieces_after"], {"top": "tee"})
set_worn("Ann", {"head": "suit_mask"})
r = inventory.apply_equipped_pieces("Ann", pieces={"head": "suit_mask", "top": "tee"},
                                    source="smoke")
check("legacy worn costume skipped", [s["reason"] for s in r["skipped"]], ["costume"])
check("legacy worn costume taken off", r["pieces_after"], {"top": "tee"})

print("[C] compliance never picks a costume piece")
from app.core.outfit_compliance import _find_inventory_piece_for_slot  # noqa: E402
check("top -> tee", _find_inventory_piece_for_slot("Ann", "top"), "tee")
check("head -> hat", _find_inventory_piece_for_slot("Ann", "head"), "hat")
check("top without tee -> None",
      _find_inventory_piece_for_slot("Ann", "top", exclude_ids={"tee"}), None)

print("[D] ChangeOutfit omits costume pieces")
from app.skills.outfit_change_skill import OutfitChangeSkill  # noqa: E402
skill = OutfitChangeSkill({})
check("menu", skill.decision_menu("Ann"), ["Hat (head)", "Tee (top, worn)"])
out = skill.execute(json.dumps({"agent_name": "Ann", "user_id": "", "equip": ["Suit top"]}))
check("equip by name finds nothing", "'Suit top' nicht im Inventar" in out, True)
check("still the tee", worn("Ann"), {"top": "tee"})

print("[E] wardrobe payload + route")
from app.routes.play import build_belongings  # noqa: E402
locks = {it["item_id"]: it.get("wear_lock") for it in build_belongings("Ann")["items"]}
check("wear_lock", locks, {"suit_top": "Costume — only while transformed",
                           "suit_mask": "Costume — only while transformed",
                           "tee": "", "hat": ""})
from app.routes import inventory as inv_routes  # noqa: E402
check("equip route 409", http_error(inv_routes._equip_route_sync, "Ann", {"item_id": "suit_top"}),
      (409, {"reason": "costume",
             "message": "Suit top is a costume piece: it can only be worn while transformed."}))

print("[F] Bea transformed into p1")
ACTIVE.add("Bea")
check("Bea may wear suit_top", identity_view.wear_refusal("Bea", "suit_top"), "")
check("Bea equips suit_top", inventory.equip_piece("Bea", "suit_top")["status"], "ok")
check("pinned", identity_view.costume_pinned("Bea", "suit_top"), True)
check("unequip refused", inventory.unequip_piece("Bea", slot="top"),
      {"status": "error", "reason": "costume_pinned", "item_id": "suit_top"})
check("displacing refused", inventory.equip_piece("Bea", "tee"),
      {"status": "error", "reason": "costume_pinned", "item_id": "suit_top"})
r = inventory.apply_equipped_pieces("Bea", pieces={"top": "tee"}, source="smoke")
check("apply over the suit", (r["changed"], r["skipped"]),
      (False, [{"item_id": "suit_top", "reason": "costume_pinned", "slot": "top"},
               {"item_id": "tee", "slot": "top", "reason": "costume_pinned"}]))
r = inventory.apply_equipped_pieces("Bea", remove_slots=["top"], source="smoke")
check("remove_slots keeps the suit", (r["changed"], r["skipped"]),
      (False, [{"item_id": "suit_top", "slot": "top", "reason": "costume_pinned"}]))
check("still worn", worn("Bea"), {"top": "suit_top"})
check("remove_from_inventory refused", inventory.remove_from_inventory("Bea", "suit_top"), False)
check("still carried", "suit_top" in inventory.get_carried_item_ids("Bea"), True)
r = inventory.drop_item("Bea", "nowhere", "", "suit_top")
check("drop refused", (r["success"], r.get("reason")), (False, "costume_pinned"))
check("transfer refused", inventory.transfer_item("Bea", "Cid", "suit_top"), False)
check("Cid got nothing", "suit_top" in inventory.get_carried_item_ids("Cid"), False)
check("gift refused", inventory.gift_item("Bea", "Cid", "suit_top").get("reason"),
      "costume_pinned")
check("unequip route 409 (German)",
      http_error(inv_routes._unequip_route_sync, "Bea", {"slot": "top"}),
      (409, {"reason": "costume_pinned",
             "message": "Das Kostüm bleibt an, bis Bea sich zurückverwandelt."}))
check("delete route 409", http_error(inv_routes.remove_inventory_item_route, "Bea", "suit_top")[0],
      409)
check("Ann still refused", identity_view.wear_refusal("Ann", "suit_top"), "costume")
check("bypass takes it off",
      inventory.unequip_piece("Bea", slot="top", allow_costume=True)["status"], "ok")
ACTIVE.clear()

print("[G] a raising costume provider -> wearable")


def broken():
    raise RuntimeError("boom")


hooks.register_provider(identity_view.PROVIDER_COSTUME, broken, owner="smoke")
check("owner None", identity_view.costume_owner("suit_top"), None)
check("Ann may wear", identity_view.wear_refusal("Ann", "suit_top"), "")

print("[H] deletion test")
hooks.unregister_owned_providers("smoke")
check("Ann equips suit_top", inventory.equip_piece("Ann", "suit_top")["status"], "ok")
check("nobody pinned", identity_view.costume_pinned("Ann", "suit_top"), False)

# ── PART 2: the real package ────────────────────────────────────────────────
print("[I] real package: pre-owned suit piece refused")
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
T0 = GameTime.parse("Y0002-D100T12:00:00")
set_game_factor(0.0)
set_game_time(T0)

from plugins.transformation import store as tstore  # noqa: E402
tstore.ensure_schema()
tstore.create_definition({"item_id": "amulet", "alias": "Moonveil",
                          "description": "A figure in moonlit silver.",
                          "suit_items": "suit_top,suit_bottom",
                          "max_duration_minutes": 60, "cooldown_minutes": 0}, persona_id="p1")
for _iid in ("amulet", "shirt", "boots", "suit_top"):
    assert inventory.add_to_inventory("Cara", _iid)
with keyed_lock("character_profile", "Cara"):
    inventory.apply_equipped_pieces("Cara", pieces={"top": "shirt", "feet": "boots"},
                                    source="smoke")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)
from plugins.transformation import engine, store  # noqa: E402

BEFORE = {"top": "shirt", "feet": "boots"}
check("Cara wears shirt + boots", worn("Cara"), BEFORE)
check("pre-owned suit_top refused", inventory.equip_piece("Cara", "suit_top"),
      {"status": "error", "reason": "costume"})

print("[J] transform")
check("transform ok", engine.transform("Cara", "p1", source="smoke")["ok"], True)
check("suit worn", worn("Cara"), {"top": "suit_top", "bottom": "suit_bottom", "feet": "boots"})
check("granted only suit_bottom", store.get_active("Cara").granted_items, ("suit_bottom",))
check("unequip refused", inventory.unequip_piece("Cara", slot="top")["reason"], "costume_pinned")
check("shirt over the suit refused", inventory.equip_piece("Cara", "shirt")["reason"],
      "costume_pinned")

print("[K] admin revert")
check("revert", engine.revert("Cara", reason="admin"), True)
check("old outfit back", worn("Cara"), BEFORE)
carried = inventory.get_carried_item_ids("Cara")
check("granted piece gone", "suit_bottom" in carried, False)
check("pre-owned piece kept", "suit_top" in carried, True)
check("pre-owned piece refused again", inventory.equip_piece("Cara", "suit_top")["reason"],
      "costume")

print("[L] a transform that fails half-way restores the outfit")
_real_flag = engine.set_state_flag
_calls = {"n": 0}


def _flaky_flag(*args, **kwargs):
    _calls["n"] += 1
    if _calls["n"] == 1:
        raise RuntimeError("flag store down")
    return _real_flag(*args, **kwargs)


engine.set_state_flag = _flaky_flag
try:
    engine.transform("Cara", "p1", source="smoke")
    raised = False
except RuntimeError:
    raised = True
engine.set_state_flag = _real_flag
check("transform raised", raised, True)
check("outfit restored", worn("Cara"), BEFORE)
check("granted piece gone", "suit_bottom" in inventory.get_carried_item_ids("Cara"), False)
check("no active row", store.get_active("Cara"), None)

print("[M] expiry tick reverts past the lock")
check("transform ok", engine.transform("Cara", "p1", source="smoke")["ok"], True)
check("suit worn", worn("Cara").get("bottom"), "suit_bottom")
set_game_time(T0 + GameDuration.of(minutes=61))
engine.tick()
check("reverted", store.get_active("Cara"), None)
check("old outfit back", worn("Cara"), BEFORE)
check("granted piece gone", "suit_bottom" in inventory.get_carried_item_ids("Cara"), False)

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks: {', '.join(FAILURES)}")
    sys.exit(1)
print(f"OK — {CHECKED} checks")
