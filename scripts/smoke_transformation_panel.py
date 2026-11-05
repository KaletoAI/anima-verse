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

FIXTURE
    Location "Inn", room "taproom". Characters Cara, Kim, Obs in the taproom.
    Items: amulet (image), ring (no image), outfit pieces suit_top (top) and
    cape (outer). Cara carries the amulet, Kim the ring. GAME clock stopped at
    Y0002-D100T12:00:00 (factor 0).

THE RULES (task brief), and what follows BY HAND
[A] Registration: provider ``character_panel:transformation`` registered by
    ``on_load``; an empty world describes title "Transformation", intro "The
    power belongs to the item: whoever holds it can transform.", no cards, a
    create form with the keys [item_id, alias, description] (item + alias
    required; description labelled "Persona appearance"). German: title
    "Verwandlung".
[B] Create, refusals first (nothing stored by any of them):
    no alias               -> "Alias is required."          (core, required)
    alias "Kim"            -> "Kim is the name of a character."
    alias "admin"          -> '"admin" is a reserved name and cannot be used for a character.'
    alias "Moon/veil"      -> 'Character name must not contain "/".'
    item "nope"            -> "This item does not exist."
    then amulet/"Moonveil" -> ok, card_id "moonveil" (slug of the alias);
    ring/"moonveil"        -> "Another persona already uses the alias moonveil."
    amulet/"Starlace"      -> "This item already grants the persona Moonveil."
    ring/"Starlace"        -> ok, "starlace". Stored ids: [moonveil, starlace].
    German duplicate alias: "Der Deckname moonveil wird schon von einer anderen
    Gestalt verwendet."
[C] describe(Cara): moonveil first (she holds the amulet; badge "holds the
    item", subtitle "Held by Cara", actions [transform]), starlace second
    (subtitle "Held by Kim", no badge, action give "Give Ring to Cara" with
    confirm "Kim loses the item."). Tabs (editor v2 brief), in order:
    persona "Persona", transform "Transformation", suit "Suit & images",
    behaviour "Behaviour" (hint "Empty = unchanged. Filled = replaces it while
    transformed."), knowers "In on the secret". Field keys tab by tab, with
    (tab, width[, rows]):
      persona:   item_id m, alias m, enabled s, description full rows 3
                 (label "Persona appearance", hint "Body, face and hair as
                 everyone — and every picture — sees them while transformed.
                 The suit comes from the suit pieces.")
      transform: activation_phrase l, revert_phrase l, max_duration_minutes s
                 (unit "min", min 0), cooldown_minutes s, transform_activity m,
                 condition_id l
      suit:      suit_items full (filter "outfit"), image_backend l (backend),
                 tpose_backend l (backend), image_loras l (loras,
                 backend_field image_backend, target render), tpose_loras l
                 (loras, backend_field tpose_backend, fallback_field
                 image_backend, target tpose)
      behaviour: personality l rows 4, dialogue_style l rows 4, presence l
                 rows 3, task l rows 3, goals l rows 3, pause_routine l (bool)
      knowers:   knowers full
    Values: max 60, cooldown 30, activity "transforming", enabled True,
    knowers [], the five behaviour texts "", pause_routine True, both backends
    "", both LoRA lists []. Status "Ordinary self".
    describe(Obs): nobody's item -> alphabetical (Moonveil, Starlace).
[D] Update moonveil from Cara's panel: suit [suit_top, cape], phrase "by the
    moon", knowers ["Kim"] -> ok; knower_names(Cara, moonveil) = ["Kim"] and
    the secret exists ("I am secretly Moonveil."). Saving the UNCHANGED alias
    passes (its own alias is a reserved name — the own-alias exception).
    knowers ["Obs"] -> exactly ["Obs"] (Kim taken off); knowers.remove(Obs) ->
    True -> []; set back to ["Kim"].
    max "-5" -> core "Max duration: at least 0."; provider called directly
    with cooldown -1 -> "Minutes cannot be negative."
    Rename to "Silverveil" (not worn) -> ok, card id stays "moonveil", the
    secret now reads "I am secretly Silverveil."; renamed back to Moonveil.
[E] Actions on Cara:
    transform -> ok "Cara is now Moonveil.", active row moonveil, status
      "Transformed into Moonveil since <T0 label>", actions [revert];
    alias change while worn -> "Revert first: Cara currently wears this
      persona.", alias unchanged; delete while worn -> same refusal, row kept;
    transform again (stale UI) -> "Cara is already transformed.";
    revert -> ok "Cara has turned back.", no active row, cooldown 30 min ->
      status "On cooldown until <T0+30min label>";
    transform -> "Cara is on cooldown until <T0+30min label>.", no active row.
    Obs: transform moonveil -> "Obs does not hold the power item."; revert ->
    "Obs does not wear this persona."; give starlace -> ok "Obs now holds
    Ring." (Kim no longer carries it); give again -> "Obs already holds the
    item."; action "fly" -> "Unknown action.".
[F] Missing references: item "cape" deleted -> describe(Cara) still renders,
    moonveil's suit value still lists "cape"; saving the card with its values
    unchanged -> ok. Power item "ring" deleted -> starlace renders without a
    give action, save -> ok.
[G] Disabled: enabled False -> not in definitions.load(), badge "disabled",
    Cara (holds the amulet) gets no transform action; enabled True again.
[H] Delete starlace (Obs has a knower secret for it from set_knowers) -> ok;
    Obs's secret with ref "transformation:starlace" is gone, Obs's cooldown
    row for starlace is gone, stored ids [moonveil].
[I] German: in describe(Cara, "de") every field label and hint, the tab
    labels and hints, the badges, status, action labels, intro, create label
    differ from the English ones — except the words that are the same in
    German: the unit "min", the label "LoRAs" and the tab "Persona".
[K] Persona settings (editor v2 brief). The clock moves to T0+31 min (Cara's
    cooldown from [E] has run out). Save through the core
    (``save_panel_card``) on moonveil: personality "Bold and loud.",
    dialogue_style "Short, clipped sentences.", presence "   ", task
    "Guard the harbour.", goals "", pause_routine False, image_backend
    "flux-local", tpose_backend "", image_loras [moon_face "0.8", moon_face 1
    (duplicate), "" (no name)] -> ok. By hand:
      core coercion: image_loras -> [{"name": "moon_face", "strength": 0.8}];
      stored prompt_overrides = {character_personality: "Bold and loud.",
        dialogue_style: "Short, clipped sentences.", character_task:
        "Guard the harbour."} — the raw column has exactly these three keys
        (empty strings are not stored);
      stored pause_routine False; imagegen {workflow "flux-local",
        tpose_workflow "", loras [moon_face 0.8], tpose_loras []}, the raw
        column only the non-empty keys {workflow, loras};
      describe values: the same texts under the panel keys, presence "" and
        goals "", image_backend "flux-local", tpose_backend "", the lists;
      definitions.load()["moonveil"] carries the same three values.
    Partial saves: {tpose_backend: "sdxl"} keeps workflow + loras;
    {personality: ""} drops only character_personality.
    Transform Cara -> the ``identity.active_persona`` answer carries
      field_overrides = the stored overrides, pause_routine False, imagegen =
      the stored dict, suit_items ["suit_top", "cape"] (cape's item was
      deleted in [F]; the definition still lists it). Appending to the
      answer's LoRA list leaves definitions.load() untouched. Revert.
    ``identity.costume_items``: {"suit_top": "moonveil", "cape": "moonveil"};
      a new persona Sunward (item sun_ring, suit [sun_mask]) adds
      "sun_mask": "sunward"; Sunward disabled -> back to the moonveil map.
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
inventory.add_item("Suit top", category="outfit_piece", item_id="suit_top",
                   outfit_piece={"slots": ["top"]})
inventory.add_item("Cape", category="outfit_piece", item_id="cape",
                   outfit_piece={"slots": ["outer"]})
assert inventory.add_to_inventory("Cara", "amulet")
assert inventory.add_to_inventory("Kim", "ring")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import character_panels as cp  # noqa: E402
from app.models import secrets  # noqa: E402
from plugins.transformation import definitions, knowers, panel, store  # noqa: E402

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
check("create keys", [f["key"] for f in _empty["create"]["fields"]], ["item_id", "alias", "description"])
check("create required", [f["required"] for f in _empty["create"]["fields"]], [True, True, False])
check("create appearance label", _empty["create"]["fields"][2]["label"], "Persona appearance")
check("German title", describe(lang="de")["title"], "Verwandlung")

# ── [B] create ──────────────────────────────────────────────────────────────
print("[B] create + validation")
check("no alias", save({"item_id": "amulet", "alias": ""})["error"], "Alias is required.")
check("character name", save({"item_id": "amulet", "alias": "Kim"})["error"],
      "Kim is the name of a character.")
check("reserved name", save({"item_id": "amulet", "alias": "admin"})["error"],
      '"admin" is a reserved name and cannot be used for a character.')
check("invalid name", save({"item_id": "amulet", "alias": "Moon/veil"})["error"],
      'Character name must not contain "/".')
check("unknown item", save({"item_id": "nope", "alias": "Moonveil"})["error"],
      "This item does not exist.")
check("nothing stored yet", ids(), [])
_r = save({"item_id": "amulet", "alias": "Moonveil", "description": "A figure in moonlit silver."})
check("create Moonveil", _r, {"ok": True, "error": "", "card_id": "moonveil"})
check("duplicate alias", save({"item_id": "ring", "alias": "moonveil"})["error"],
      "Another persona already uses the alias moonveil.")
check("duplicate alias (de)", save({"item_id": "ring", "alias": "moonveil"}, lang="de")["error"],
      "Der Deckname moonveil wird schon von einer anderen Gestalt verwendet.")
check("item bound", save({"item_id": "amulet", "alias": "Starlace"})["error"],
      "This item already grants the persona Moonveil.")
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
       ("suit", "Suit & images", ""),
       ("behaviour", "Behaviour", "Empty = unchanged. Filled = replaces it while transformed."),
       ("knowers", "In on the secret", "")])
check("field order", [f["key"] for f in _m["fields"]],
      ["item_id", "alias", "enabled", "description",
       "activation_phrase", "revert_phrase", "max_duration_minutes", "cooldown_minutes",
       "transform_activity", "condition_id",
       "suit_items", "image_backend", "tpose_backend", "image_loras", "tpose_loras",
       "personality", "dialogue_style", "presence", "task", "goals", "pause_routine",
       "knowers"])
check("layout", [(f["key"], f["tab"], f["width"], f.get("rows")) for f in _m["fields"]],
      [("item_id", "persona", "m", None), ("alias", "persona", "m", None),
       ("enabled", "persona", "s", None), ("description", "persona", "full", 3),
       ("activation_phrase", "transform", "l", None), ("revert_phrase", "transform", "l", None),
       ("max_duration_minutes", "transform", "s", None),
       ("cooldown_minutes", "transform", "s", None),
       ("transform_activity", "transform", "m", None), ("condition_id", "transform", "l", None),
       ("suit_items", "suit", "full", None), ("image_backend", "suit", "l", None),
       ("tpose_backend", "suit", "l", None), ("image_loras", "suit", "l", None),
       ("tpose_loras", "suit", "l", None),
       ("personality", "behaviour", "l", 4), ("dialogue_style", "behaviour", "l", 4),
       ("presence", "behaviour", "l", 3), ("task", "behaviour", "l", 3),
       ("goals", "behaviour", "l", 3), ("pause_routine", "behaviour", "l", None),
       ("knowers", "knowers", "full", None)])
_f = {f["key"]: f for f in _m["fields"]}
check("appearance label/hint", (_f["description"]["label"], _f["description"]["hint"]),
      ("Persona appearance", "Body, face and hair as everyone — and every picture — sees them "
       "while transformed. The suit comes from the suit pieces."))
check("new labels", [(k, _f[k]["type"], _f[k]["label"]) for k in (
          "image_backend", "tpose_backend", "image_loras", "tpose_loras", "personality",
          "dialogue_style", "presence", "task", "goals", "pause_routine")],
      [("image_backend", "backend", "Image backend"), ("tpose_backend", "backend", "T-pose backend"),
       ("image_loras", "loras", "LoRAs"), ("tpose_loras", "loras", "T-pose LoRAs"),
       ("personality", "textarea", "Personality"), ("dialogue_style", "textarea", "Speech"),
       ("presence", "textarea", "Presence"), ("task", "textarea", "Tasks"),
       ("goals", "textarea", "Goals"), ("pause_routine", "bool", "Daily routine rests")])
check("new hints", [_f[k]["hint"] for k in ("image_backend", "tpose_backend", "image_loras",
                                             "tpose_loras", "presence")],
      ["Empty = the character's own.", "Empty = image backend.",
       "Replace the character's LoRAs while transformed.", "Empty = the LoRAs above.",
       "Also what others sense of the persona."])
check("lora wiring", [(_f[k]["backend_field"], _f[k]["fallback_field"], _f[k]["target"])
                      for k in ("image_loras", "tpose_loras")],
      [("image_backend", "", "render"), ("tpose_backend", "image_backend", "tpose")])
check("new defaults", {k: _m["values"][k] for k in (
          "personality", "dialogue_style", "presence", "task", "goals", "pause_routine",
          "image_backend", "tpose_backend", "image_loras", "tpose_loras")},
      {"personality": "", "dialogue_style": "", "presence": "", "task": "", "goals": "",
       "pause_routine": True, "image_backend": "", "tpose_backend": "", "image_loras": [],
       "tpose_loras": []})
check("suit filter", _f["suit_items"]["filter"], "outfit")
check("max unit/min", (_f["max_duration_minutes"]["unit"], _f["max_duration_minutes"]["min"]), ("min", 0))
check("defaults", {k: _m["values"][k] for k in ("max_duration_minutes", "cooldown_minutes",
                                                  "transform_activity", "enabled", "knowers")},
      {"max_duration_minutes": 60, "cooldown_minutes": 30, "transform_activity": "transforming",
       "enabled": True, "knowers": []})
check("status", _m["status"], "Ordinary self")
check("order for Obs", [c["title"] for c in describe("Obs")["cards"]], ["Moonveil", "Starlace"])

# ── [D] update + knowers ────────────────────────────────────────────────────
print("[D] update + knowers")
_r = save({**_m["values"], "suit_items": ["suit_top", "cape"], "activation_phrase": "by the moon",
           "knowers": ["Kim"]}, "moonveil")
check("update ok (own alias kept)", _r["ok"], True)
check("stored suit", store.get_definition("moonveil")["suit_items"], ["suit_top", "cape"])
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
check("rename while worn", save({"alias": "Other"}, "moonveil")["error"],
      "Revert first: Cara currently wears this persona.")
check("alias unchanged", store.get_definition("moonveil")["alias"], "Moonveil")
check("delete while worn", cp.delete_panel_card(PKG, "Cara", "moonveil", "en")["error"],
      "Revert first: Cara currently wears this persona.")
check("row kept", ids(), ["moonveil", "starlace"])
check("transform twice", act("moonveil", "transform")["error"], "Cara is already transformed.")
check("revert", act("moonveil", "revert"), {"ok": True, "error": "", "message": "Cara has turned back."})
check("no active row", store.get_active("Cara"), None)
_cool = (T0 + GameDuration.of(minutes=30)).display_label("en")
check("status cooldown", card("moonveil")["status"], f"On cooldown until {_cool}")
check("transform on cooldown", act("moonveil", "transform")["error"],
      f"Cara is on cooldown until {_cool}.")
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
inventory.delete_item("cape")
_m = card("moonveil")
check("renders with a deleted suit piece", _m["values"]["suit_items"], ["suit_top", "cape"])
check("save unchanged", save(_m["values"], "moonveil")["ok"], True)
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
_SAME_IN_GERMAN = {"LoRAs", "Persona"}
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
check("German tab count", len(_de["tabs"]), 5)

# ── [K] persona settings ────────────────────────────────────────────────────
print("[K] persona settings")
from app.core import hooks  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.identity_view import PROVIDER_ACTIVE  # noqa: E402

set_game_time(T0 + GameDuration.of(minutes=31))
_r = save({"personality": "Bold and loud.", "dialogue_style": "Short, clipped sentences.",
           "presence": "   ", "task": "Guard the harbour.", "goals": "", "pause_routine": False,
           "image_backend": "flux-local", "tpose_backend": "",
           "image_loras": [{"name": "moon_face", "strength": "0.8"},
                           {"name": "moon_face", "strength": 1}, {"name": ""}],
           "tpose_loras": []}, "moonveil")
check("save persona settings", _r, {"ok": True, "error": "", "card_id": "moonveil"})
_OVERRIDES = {"character_personality": "Bold and loud.",
              "dialogue_style": "Short, clipped sentences.",
              "character_task": "Guard the harbour."}
_IMAGE = {"workflow": "flux-local", "tpose_workflow": "",
          "loras": [{"name": "moon_face", "strength": 0.8}], "tpose_loras": []}
_row = store.get_definition("moonveil")
check("stored overrides", _row["prompt_overrides"], _OVERRIDES)
check("stored pause_routine", _row["pause_routine"], False)
check("stored imagegen", _row["imagegen"], _IMAGE)
_raw = get_connection().execute("SELECT prompt_overrides, pause_routine, imagegen FROM "
                                "transformation_definitions WHERE id='moonveil'").fetchone()
check("raw overrides: no empty strings", json.loads(_raw[0]), _OVERRIDES)
check("raw pause_routine", _raw[1], 0)
check("raw imagegen: only set keys", json.loads(_raw[2]),
      {"workflow": "flux-local", "loras": [{"name": "moon_face", "strength": 0.8}]})
_v = card("moonveil")["values"]
check("describe values", {k: _v[k] for k in (
          "personality", "dialogue_style", "presence", "task", "goals", "pause_routine",
          "image_backend", "tpose_backend", "image_loras", "tpose_loras")},
      {"personality": "Bold and loud.", "dialogue_style": "Short, clipped sentences.",
       "presence": "", "task": "Guard the harbour.", "goals": "", "pause_routine": False,
       "image_backend": "flux-local", "tpose_backend": "",
       "image_loras": [{"name": "moon_face", "strength": 0.8}], "tpose_loras": []})
_d = definitions.load()["moonveil"]
check("definition values", (_d.prompt_overrides, _d.pause_routine, _d.imagegen),
      (_OVERRIDES, False, _IMAGE))
check("partial save: T-pose backend", save({"tpose_backend": "sdxl"}, "moonveil")["ok"], True)
_IMAGE = {**_IMAGE, "tpose_workflow": "sdxl"}
check("image kept beside it", store.get_definition("moonveil")["imagegen"], _IMAGE)
check("clear personality", save({"personality": ""}, "moonveil")["ok"], True)
_OVERRIDES = {k: v for k, v in _OVERRIDES.items() if k != "character_personality"}
check("only personality dropped", store.get_definition("moonveil")["prompt_overrides"], _OVERRIDES)

check("transform for the provider", act("moonveil", "transform")["ok"], True)
_ans = hooks.get_provider(PROVIDER_ACTIVE)("Cara")
check("answer: new keys", {k: _ans.get(k) for k in ("field_overrides", "pause_routine",
                                                    "imagegen", "suit_items")},
      {"field_overrides": _OVERRIDES, "pause_routine": False, "imagegen": _IMAGE,
       "suit_items": ["suit_top", "cape"]})
_ans["imagegen"]["loras"].append({"name": "x", "strength": 1.0})
_ans["field_overrides"]["character_goals"] = "x"
check("answer is a copy", (definitions.load()["moonveil"].imagegen,
                           definitions.load()["moonveil"].prompt_overrides),
      (_IMAGE, _OVERRIDES))
check("revert", act("moonveil", "revert")["ok"], True)

_costume = hooks.get_provider("identity.costume_items")
check("costume_items registered", _costume is not None, True)
check("costume map", _costume(), {"suit_top": "moonveil", "cape": "moonveil"})
inventory.add_item("Sun ring", item_id="sun_ring")
inventory.add_item("Sun mask", category="outfit_piece", item_id="sun_mask",
                   outfit_piece={"slots": ["head"]})
check("create Sunward", save({"item_id": "sun_ring", "alias": "Sunward"})["card_id"], "sunward")
check("Sunward suit", save({"suit_items": ["sun_mask"]}, "sunward")["ok"], True)
check("costume map with Sunward", _costume(),
      {"suit_top": "moonveil", "cape": "moonveil", "sun_mask": "sunward"})
check("disable Sunward", save({"enabled": False}, "sunward")["ok"], True)
check("disabled persona skipped", _costume(), {"suit_top": "moonveil", "cape": "moonveil"})

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
