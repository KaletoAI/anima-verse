#!/usr/bin/env python3
"""Smoke: the Transformation panel (``plugins/transformation/panel.py``) — the
persona editor on Game-Admin → Characters → <character> → Skills.

Usage:  ./.venv/bin/python scripts/smoke_transformation_panel.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM. The package is
loaded the way the server loads it (``packages.enabled = "transformation"``,
``discover_packages()``); the panel is driven through the core functions the
admin routes call (``app.core.character_panels``: describe / save / delete /
action — so the core's generic coercion runs first, as in production), and
only the provider-specific rules are under test here.

THE SPEC (task 2 of the linked-characters plan, ruling P1): the panel edits
the reduced definition — item, alias (a plain LABEL for the knower secret and
the narration: no name rule, may repeat, may be a character's name), enabled,
phrases, durations, activity, effect — and the knowers. Three tabs; no
appearance, suit, behaviour or image settings.

FIXTURE
    Location "Inn", room "taproom". Characters Cara, Kim, Obs in the taproom.
    Items: amulet (image), ring (no image), token. Cara carries the amulet,
    Kim the ring. GAME clock stopped at Y0002-D100T12:00:00 (factor 0).

THE RULES, and what follows BY HAND
[A] Registration: provider ``character_panel:transformation`` registered by
    ``on_load``; an empty world describes title "Transformation", intro "The
    power belongs to the item: whoever holds it can transform.", no cards, a
    create form with the keys [item_id, alias], both required. German: title
    "Verwandlung".
[B] Create, refusals first (nothing stored by either):
    no alias               -> "Alias is required."          (core, required)
    item "nope"            -> "This item does not exist."
    then amulet/"Moonveil" -> ok, card_id "moonveil" (slug of the alias);
    amulet/"Starlace"      -> "This item already grants the persona Moonveil."
    A label is no name: token/"Kim" -> ok "kim" (a character's name);
    deleted again. ring/"moonveil" -> ok "moonveil_2" (a repeated alias);
    deleted again. ring/"Starlace" -> ok, "starlace".
    Stored ids: [moonveil, starlace].
[C] describe(Cara): moonveil first (she holds the amulet; badge "holds the
    item", subtitle "Held by Cara", actions [transform]), starlace second
    (subtitle "Held by Kim", no badge, action give "Give Ring to Cara" with
    confirm "Kim loses the item."). Tabs, in order: persona "Persona",
    transform "Transformation", knowers "In on the secret" (no hints).
    Fields (key, tab, width) — short fields side by side (12-column grid):
      item_id persona m, alias persona m, enabled persona s,
      activation_phrase transform l, revert_phrase transform l,
      max_duration_minutes transform s (unit "min", min 0),
      cooldown_minutes transform s, transform_activity transform m,
      condition_id transform l, knowers knowers full.
    Hints: enabled "Off: nobody can transform into it."; knowers "They know
    that Cara is Moonveil.". The alias has no hint.
    Values: exactly the ten field keys; max 60, cooldown 30, activity
    "transforming", enabled True, knowers []. Status "Ordinary self".
    describe(Obs): nobody's item -> alphabetical (Moonveil, Starlace).
[D] Update moonveil from Cara's panel: phrase "by the moon", knowers ["Kim"]
    -> ok; knower_names(Cara, moonveil) = ["Kim"] and the secret exists
    ("I am secretly Moonveil."). knowers ["Obs"] -> exactly ["Obs"] (Kim taken
    off); knowers.remove(Obs) -> True -> []; set back to ["Kim"].
    max "-5" -> core "Max duration: at least 0."; provider called directly
    with cooldown -1 -> "Minutes cannot be negative."
    Rename to "Silverveil" -> ok, card id stays "moonveil", the secret now
    reads "I am secretly Silverveil."; renamed back to Moonveil.
[E] Actions on Cara:
    transform -> ok "Cara is now Moonveil.", active row moonveil, status
      "Transformed into Moonveil since <T0 label>", actions [revert];
    a rename while worn is just a label change -> ok, status "Transformed
      into Glimmer since <T0 label>"; renamed back;
    delete while worn -> "Revert first: Cara currently wears this persona.",
      row kept;
    transform again (stale UI) -> "Cara is already transformed.";
    revert -> ok "Cara has turned back.", no active row, cooldown 30 min ->
      status "On cooldown until <T0+30min label>";
    transform (admin) -> ok "Cara is now Moonveil." despite the cooldown,
      active row moonveil; revert again -> ok; the in-game path
      (engine.transform without ignore_cooldown) -> reason "cooldown", no
      active row.
    Obs: transform moonveil -> "Obs does not hold the power item."; revert ->
    "Obs does not wear this persona."; give starlace -> ok "Obs now holds
    Ring." (Kim no longer carries it); give again -> "Obs already holds the
    item."; action "fly" -> "Unknown action.".
[F] Missing reference: power item "ring" deleted -> starlace renders without
    a give action, save with its values unchanged -> ok.
[G] Disabled: enabled False -> not in definitions.load(), badge "disabled",
    Cara (holds the amulet) gets no transform action; enabled True again.
[H] Delete starlace (Obs has a knower secret for it from set_knowers) -> ok;
    Obs's secret with ref "transformation:starlace" is gone, Obs's cooldown
    row for starlace is gone, stored ids [moonveil].
[I] German: in describe(Cara, "de") every field label and hint, the tab
    labels, the badges, status, action labels, intro, create label and the
    delete confirmation differ from the English ones — except the tab
    "Persona" (the same word in German) and the unit "min". 3 tabs.
[K] The dropped settings stay dropped: a save that also hands in
    description, suit_items, personality, pause_routine, image_backend ->
    ok (the core keeps only declared fields); the stored row keeps exactly the
    keys id + the nine columns + updated_at. No ``identity.*`` provider is
    registered (identity.active_persona, identity.costume_items -> None).
[J] Deletion test: providers of "transformation" unregistered -> has_panel
    False, describe_panel raises PanelNotFound.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-panel-smoke-"))
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

from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402
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
inventory.set_item_image("amulet", "image.png")
inventory.add_item("Ring", item_id="ring")
inventory.add_item("Token", item_id="token")
assert inventory.add_to_inventory("Cara", "amulet")
assert inventory.add_to_inventory("Kim", "ring")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import character_panels as cp  # noqa: E402
from app.models import secrets  # noqa: E402
from plugins.transformation import definitions, engine, knowers, panel, store  # noqa: E402

PKG = "transformation"


def describe(name="Cara", lang="en"):
    return cp.describe_panel(PKG, name, lang)


def card(cid, name="Cara", lang="en"):
    return next((c for c in describe(name, lang)["cards"] if c["id"] == cid), None)


def save(values, card_id=None, name="Cara", lang="en"):
    return cp.save_panel_card(PKG, name, card_id, values, lang)


def act(cid, aid, name="Cara"):
    return cp.run_panel_action(PKG, name, cid, aid, "en")


def ids():
    return [r["id"] for r in store.list_definitions()]


def own_secrets(name, pid):
    return [s for s in secrets.list_secrets(name) if s.get("source_ref") == f"transformation:{pid}"]


# ── [A] registration ────────────────────────────────────────────────────────
print("[A] registration")
check("provider registered", cp.get_panel_provider(PKG) is panel, True)
_empty = describe()
check("title", _empty["title"], "Transformation")
check("intro", _empty["intro"], "The power belongs to the item: whoever holds it can transform.")
check("no cards", _empty["cards"], [])
check("create keys", [f["key"] for f in _empty["create"]["fields"]], ["item_id", "alias"])
check("create required", [f["required"] for f in _empty["create"]["fields"]], [True, True])
check("German title", describe(lang="de")["title"], "Verwandlung")

# ── [B] create ──────────────────────────────────────────────────────────────
print("[B] create + validation")
check("no alias", save({"item_id": "amulet", "alias": ""})["error"], "Alias is required.")
check("unknown item", save({"item_id": "nope", "alias": "Moonveil"})["error"],
      "This item does not exist.")
check("nothing stored yet", ids(), [])
_r = save({"item_id": "amulet", "alias": "Moonveil"})
check("create Moonveil", _r, {"ok": True, "error": "", "card_id": "moonveil"})
check("item bound", save({"item_id": "amulet", "alias": "Starlace"})["error"],
      "This item already grants the persona Moonveil.")
check("a character's name as label", save({"item_id": "token", "alias": "Kim"})["card_id"], "kim")
check("delete it", cp.delete_panel_card(PKG, "Cara", "kim", "en")["ok"], True)
check("a repeated alias", save({"item_id": "ring", "alias": "moonveil"})["card_id"], "moonveil_2")
check("delete it", cp.delete_panel_card(PKG, "Cara", "moonveil_2", "en")["ok"], True)
check("create Starlace", save({"item_id": "ring", "alias": "Starlace"})["card_id"], "starlace")
check("stored ids", ids(), ["moonveil", "starlace"])

# ── [C] describe ────────────────────────────────────────────────────────────
print("[C] describe")
_cards = describe()["cards"]
check("order for Cara", [c["id"] for c in _cards], ["moonveil", "starlace"])
_m, _s = _cards
check("moon badge", _m["badges"], ["holds the item"])
check("moon subtitle", _m["subtitle"], "Held by Cara")
check("moon actions", [a["id"] for a in _m["actions"]], ["transform"])
check("star badge", _s["badges"], [])
check("star subtitle", _s["subtitle"], "Held by Kim")
check("star actions", [(a["id"], a["label"], a["confirm"]) for a in _s["actions"]],
      [("give", "Give Ring to Cara", "Kim loses the item.")])
check("tabs", [(tb["id"], tb["label"], tb["hint"]) for tb in describe()["tabs"]],
      [("persona", "Persona", ""), ("transform", "Transformation", ""),
       ("knowers", "In on the secret", "")])
check("layout", [(f["key"], f["tab"], f["width"]) for f in _m["fields"]],
      [("item_id", "persona", "m"), ("alias", "persona", "m"), ("enabled", "persona", "s"),
       ("activation_phrase", "transform", "l"), ("revert_phrase", "transform", "l"),
       ("max_duration_minutes", "transform", "s"), ("cooldown_minutes", "transform", "s"),
       ("transform_activity", "transform", "m"), ("condition_id", "transform", "l"),
       ("knowers", "knowers", "full")])
_f = {f["key"]: f for f in _m["fields"]}
check("hints", [_f[k]["hint"] for k in ("alias", "enabled", "knowers")],
      ["", "Off: nobody can transform into it.", "They know that Cara is Moonveil."])
check("max unit/min", (_f["max_duration_minutes"]["unit"], _f["max_duration_minutes"]["min"]), ("min", 0))
check("value keys", sorted(_m["values"]),
      sorted(["item_id", "alias", "enabled", "activation_phrase", "revert_phrase",
              "max_duration_minutes", "cooldown_minutes", "transform_activity", "condition_id",
              "knowers"]))
check("defaults", {k: _m["values"][k] for k in ("max_duration_minutes", "cooldown_minutes",
                                                  "transform_activity", "enabled", "knowers")},
      {"max_duration_minutes": 60, "cooldown_minutes": 30, "transform_activity": "transforming",
       "enabled": True, "knowers": []})
check("status", _m["status"], "Ordinary self")
check("order for Obs", [c["title"] for c in describe("Obs")["cards"]], ["Moonveil", "Starlace"])

# ── [D] update + knowers ────────────────────────────────────────────────────
print("[D] update + knowers")
_r = save({**_m["values"], "activation_phrase": "by the moon", "knowers": ["Kim"]}, "moonveil")
check("update ok", _r["ok"], True)
check("stored phrase", store.get_definition("moonveil")["activation_phrase"], "by the moon")
check("knowers Kim", knowers.knower_names("Cara", "moonveil"), ["Kim"])
check("secret created", [s.get("content") for s in own_secrets("Cara", "moonveil")],
      ["I am secretly Moonveil."])
check("panel value", card("moonveil")["values"]["knowers"], ["Kim"])
save({"knowers": ["Obs"]}, "moonveil")
check("knowers exactly Obs", knowers.knower_names("Cara", "moonveil"), ["Obs"])
check("remove Obs", knowers.remove("Obs", "Cara", "moonveil"), True)
check("knowers empty", knowers.knower_names("Cara", "moonveil"), [])
check("set back to Kim", knowers.set_knowers("Cara", "moonveil", ["Kim", " kim", "Cara"]), ["Kim"])
check("negative max (core)", save({"max_duration_minutes": "-5"}, "moonveil")["error"],
      "Max duration: at least 0.")
check("negative cooldown (provider)",
      panel.save("Cara", "moonveil", {"cooldown_minutes": -1}, "en")["error"],
      "Minutes cannot be negative.")
check("rename", save({"alias": "Silverveil"}, "moonveil"),
      {"ok": True, "error": "", "card_id": "moonveil"})
check("secret follows the alias", [s.get("content") for s in own_secrets("Cara", "moonveil")],
      ["I am secretly Silverveil."])
check("rename back", save({"alias": "Moonveil"}, "moonveil")["ok"], True)

# ── [E] actions ─────────────────────────────────────────────────────────────
print("[E] actions")
check("transform", act("moonveil", "transform"),
      {"ok": True, "error": "", "message": "Cara is now Moonveil."})
check("active row", getattr(store.get_active("Cara"), "persona_id", None), "moonveil")
_m = card("moonveil")
check("status transformed", _m["status"], f"Transformed into Moonveil since {T0.display_label('en')}")
check("actions while worn", [a["id"] for a in _m["actions"]], ["revert"])
check("rename while worn", save({"alias": "Glimmer"}, "moonveil")["ok"], True)
check("status with the new label", card("moonveil")["status"],
      f"Transformed into Glimmer since {T0.display_label('en')}")
check("rename back while worn", save({"alias": "Moonveil"}, "moonveil")["ok"], True)
check("delete while worn", cp.delete_panel_card(PKG, "Cara", "moonveil", "en")["error"],
      "Revert first: Cara currently wears this persona.")
check("row kept", ids(), ["moonveil", "starlace"])
check("transform twice", act("moonveil", "transform")["error"], "Cara is already transformed.")
check("revert", act("moonveil", "revert"), {"ok": True, "error": "", "message": "Cara has turned back."})
check("no active row", store.get_active("Cara"), None)
_cool = (T0 + GameDuration.of(minutes=30)).display_label("en")
check("status cooldown", card("moonveil")["status"], f"On cooldown until {_cool}")
check("transform on cooldown (admin overrides it)", act("moonveil", "transform"),
      {"ok": True, "error": "", "message": "Cara is now Moonveil."})
check("active row despite the cooldown", store.get_active("Cara").persona_id, "moonveil")
check("revert again", act("moonveil", "revert"), {"ok": True, "error": "", "message": "Cara has turned back."})
check("in-game transform on cooldown", engine.transform("Cara", "moonveil", source="smoke")["reason"],
      "cooldown")
check("still no active row", store.get_active("Cara"), None)
check("Obs lacks the item", act("moonveil", "transform", "Obs")["error"],
      "Obs does not hold the power item.")
check("Obs revert", act("moonveil", "revert", "Obs")["error"], "Obs does not wear this persona.")
check("give ring to Obs", act("starlace", "give", "Obs"),
      {"ok": True, "error": "", "message": "Obs now holds Ring."})
check("Kim lost the ring", "ring" in inventory.get_carried_item_ids("Kim"), False)
check("Obs carries it", "ring" in inventory.get_carried_item_ids("Obs"), True)
check("give again", act("starlace", "give", "Obs")["error"], "Obs already holds the item.")
check("unknown action", act("starlace", "fly", "Obs")["error"], "Unknown action.")

# ── [F] missing references ──────────────────────────────────────────────────
print("[F] missing references")
inventory.delete_item("ring")
_s = card("starlace")
check("no give without the item", [a["id"] for a in _s["actions"]], [])
check("save with a deleted power item", save(_s["values"], "starlace")["ok"], True)

# ── [G] disabled ────────────────────────────────────────────────────────────
print("[G] disabled")
save({"enabled": False}, "moonveil")
check("not loaded", "moonveil" in definitions.load(), False)
_m = card("moonveil")
check("badges", _m["badges"], ["holds the item", "disabled"])
check("no transform action", [a["id"] for a in _m["actions"]], [])
save({"enabled": True}, "moonveil")
check("loaded again", "moonveil" in definitions.load(), True)

# ── [H] delete ──────────────────────────────────────────────────────────────
print("[H] delete")
check("Obs knower secret", knowers.set_knowers("Obs", "starlace", ["Kim"]), ["Kim"])
store.set_cooldown("Obs", "starlace", "Y0002-D101T00:00:00")
check("delete starlace", cp.delete_panel_card(PKG, "Cara", "starlace", "en"), {"ok": True, "error": ""})
check("Obs's secret gone", own_secrets("Obs", "starlace"), [])
check("Obs's cooldown gone", store.cooldown_until("Obs", "starlace"), "")
check("stored ids", ids(), ["moonveil"])

# ── [I] German ──────────────────────────────────────────────────────────────
print("[I] German")
_en, _de = describe(), describe(lang="de")
_ce, _cd = _en["cards"][0], _de["cards"][0]
_SAME_IN_GERMAN = {"Persona"}
_untranslated = []
for _a, _b in zip(_ce["fields"], _cd["fields"]):
    for _k in ("label", "hint"):
        if _a[_k] and _a[_k] == _b[_k] and _a[_k] not in _SAME_IN_GERMAN:
            _untranslated.append(f"{_a['key']}.{_k}")
for _a, _b in zip(_en["tabs"], _de["tabs"]):
    for _k in ("label", "hint"):
        if _a[_k] and _a[_k] == _b[_k] and _a[_k] not in _SAME_IN_GERMAN:
            _untranslated.append(f"tab {_a['id']}.{_k}")
for _k in ("status", "subtitle"):
    if _ce[_k] == _cd[_k]:
        _untranslated.append(_k)
_untranslated += [b for b in _ce["badges"] if b in _cd["badges"]]
_untranslated += [a["label"] for a, b in zip(_ce["actions"], _cd["actions"]) if a["label"] == b["label"]]
for _k in ("intro",):
    if _en[_k] == _de[_k]:
        _untranslated.append(_k)
if _en["create"]["label"] == _de["create"]["label"]:
    _untranslated.append("create.label")
if _ce["delete_confirm"] == _cd["delete_confirm"]:
    _untranslated.append("delete_confirm")
check("every visible string translated", _untranslated, [])
check("German tab count", len(_de["tabs"]), 3)

# ── [K] dropped settings ───────────────────────────────────────────────────
print("[K] dropped settings stay dropped")
from app.core import hooks  # noqa: E402
check("save with old keys", save({"description": "A figure.", "suit_items": ["token"],
                                  "personality": "Bold.", "pause_routine": False,
                                  "image_backend": "flux-local"}, "moonveil")["ok"], True)
check("stored keys", sorted(store.get_definition("moonveil")),
      sorted(["id", "item_id", "alias", "activation_phrase", "revert_phrase", "condition_id",
              "max_duration_minutes", "cooldown_minutes", "transform_activity", "enabled",
              "updated_at"]))
check("no identity providers",
      [hooks.get_provider(c) for c in ("identity.active_persona", "identity.costume_items")],
      [None, None])

# ── [J] deletion test ───────────────────────────────────────────────────────
print("[J] package providers removed")
from app.core.hooks import unregister_owned_providers  # noqa: E402
unregister_owned_providers(PKG)
check("no panel", cp.has_panel(PKG), False)
try:
    describe()
    _nf = "described"
except cp.PanelNotFound:
    _nf = "PanelNotFound"
check("describe without provider", _nf, "PanelNotFound")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
