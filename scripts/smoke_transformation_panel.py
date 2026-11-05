#!/usr/bin/env python3
"""Smoke: the Transformation panel (``plugins/transformation/panel.py``) — the
transformation editor on Game-Admin → Characters → <character> → Skills —
and the two generic panel additions it needs (a panel-level action with a
text input, a ``select`` field).

Usage:  ./.venv/bin/python scripts/smoke_transformation_panel.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM. The package is
loaded the way the server loads it (``packages.enabled = "transformation"``,
``discover_packages()``); the panel is driven through the core functions the
admin routes call (``app.core.character_panels``: describe / save / delete /
action — so the core's generic coercion runs first, as in production).

THE SPEC (``docs/superpowers/specs/2026-11-05-linked-characters-design.md`` →
"Transformation package"): the panel on the LEADER has one card per
definition, tab "Transformation" (body select from the leader's linked
characters, item, phrases, durations, activity, condition, enabled — short
fields side by side on the 12-column grid) and tab "Knowers"; a "Create
linked character" action asks only for a name (``create_linked``) and the new
body is selectable afterwards. On a linked character the panel shows only
status + "Revert now" and a pointer to the leader. Status "Transformed into
<body>", the knower secret "<body> is secretly <leader>.". The admin's
"Transform now" ignores the cooldown; "Revert now" shows a swap refusal.

FIXTURE
    Location "Inn", room "taproom". Tilda, Kim, Obs in the taproom; Glut =
    create_linked(Tilda) (dormant). Items amulet, ring. Tilda carries the
    amulet. GAME clock stopped at T0 = Y0002-D100T12:00:00 (factor 0).

THE RULES, and what follows BY HAND
[A] describe(Tilda): title "Transformation", intro "Tilda turns into a linked
    character through a power item."; tabs [transform "Transformation",
    knowers "Knowers"]; panel actions [create_linked "Create linked
    character", input {label "Name", placeholder "", message "A new character
    linked to Tilda, built from Tilda's template. It opens for editing right
    away."}];
    no cards; create form [body (select, required, options [Glut]),
    item_id (item, required)]. describe(Obs) (no bodies): no create form, the
    same action. German title "Verwandlung".
[B] Panel action create_linked on Tilda (card_id ""):
    value "Ember" -> ok, message "Ember was created as a linked character of
    Tilda.", open_character "Ember" (Game-Admin opens it for editing — review
    fix round 1); bodies_of(Tilda) == [Ember, Glut], Ember dormant; the create
    form's body options are now [Ember, Glut].
    value "" -> core error "Name is required."; value "Glut" -> the core's
    'A character named "Glut" already exists.'.
[C] Create, refusals first: body "Nobody" -> core "Linked character:
    invalid selection."; item "nope" -> "This item does not exist.";
    Glut/amulet -> ok, card_id "glut"; Ember/amulet -> "This item already
    turns Tilda into Glut."; Ember/ring -> ok "ember".
[D] describe(Tilda): cards [glut, ember] (glut first: Tilda holds its item).
    glut: title "Glut", badges ["holds the item"], subtitle "Held by Tilda",
    actions [transform "Transform now"], status "Ordinary self".
    Fields (key, type, tab, width):
      body select transform m, item_id item transform m, enabled bool
      transform s, activation_phrase text transform l, revert_phrase text
      transform l, max_duration_minutes int transform s, cooldown_minutes int
      transform s, transform_activity text transform s, condition_id
      condition transform s, knowers characters knowers full.
    -> row widths 4+4+3, 6+6, 3+3+3+3 (short fields side by side).
    Values: body Glut, item amulet, enabled True, phrases "", max 60, cooldown
    30, activity "transforming", condition "", knowers [].
    ember: subtitle "Nobody holds the item", actions [give "Give Ring to
    Tilda"] (no confirm: nobody loses it).
[E] Update glut: knowers [Kim, Glut, Tilda] -> ok; stored knowers [Kim] (the
    family always knows); Tilda's mind holds "Glut is secretly Tilda." (body
    Glut). max "-5" -> core "Max duration: at least 0."; the provider called
    directly with cooldown -1 -> "Minutes cannot be negative."
[F] Actions: transform glut -> ok "Tilda is now Glut."; glut status
    "Transformed into Glut since <T0 label>", actions [revert "Revert now"];
    delete glut -> "Revert first: Tilda is transformed into Glut."; transform
    again -> "Tilda is already transformed.".
    describe(Glut): intro "Glut is a linked character of Tilda — set the
    transformation up on Tilda's panel."; no tabs, no create, no panel
    actions; one card glut, title "From Tilda", no fields, status "Glut stands
    in the world for Tilda since <T0 label>", actions [revert].
    Glut gets a movement_target -> revert from Glut's panel -> error
    SWAP_REFUSAL_TEXT["journey"], still active; target cleared -> ok "Glut has
    turned back into Tilda."; Tilda's glut status "On cooldown until <T0 +
    30 min label>"; Glut's status "Dormant — Tilda stands in the world.",
    actions []. The admin's transform ignores the cooldown -> ok; revert from
    Tilda's panel -> ok. Obs: action on "glut" -> "This entry no longer
    exists." (not Obs's).
[G] give on ember -> ok "Tilda now holds Ring."; unknown action ->
    "Unknown action.".
[H] Delete ember -> ok, stored ids [glut]. German: tab labels
    ["Verwandlung", "Eingeweihte"].
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

from app.core import linked_characters as lc  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory, secrets  # noqa: E402
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


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        for k, v in values.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
        assert ch.save_character_profile(name, p), name


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
assert lc.create_linked("Tilda", "Glut")["ok"]

inventory.add_item("Amulet", item_id="amulet")
inventory.add_item("Ring", item_id="ring")
assert inventory.add_to_inventory("Tilda", "amulet")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import character_panels as cp  # noqa: E402
from plugins.transformation import knowers, panel, store  # noqa: E402

PKG = "transformation"


def describe(name="Tilda", lang="en"):
    return cp.describe_panel(PKG, name, lang)


def card(cid, name="Tilda", lang="en"):
    return next((c for c in describe(name, lang)["cards"] if c["id"] == cid), None)


def save(values, card_id=None, name="Tilda"):
    return cp.save_panel_card(PKG, name, card_id, values, "en")


def act(card_id, action_id, name="Tilda", value=None):
    return cp.run_panel_action(PKG, name, card_id, action_id, "en", value=value)


def label(stamp):
    return GameTime.parse(stamp).display_label("en")


# ── [A] empty panel ─────────────────────────────────────────────────────────
print("[A] describe, no definitions")
_p = describe()
check("title", _p["title"], "Transformation")
check("intro", _p["intro"], "Tilda turns into a linked character through a power item.")
check("tabs", _p["tabs"], [{"id": "transform", "label": "Transformation", "hint": ""},
                           {"id": "knowers", "label": "Knowers", "hint": ""}])
CREATE_ACTION = {"id": "create_linked", "label": "Create linked character", "confirm": "",
                 "primary": False,
                 "input": {"label": "Name", "placeholder": "",
                           "message": "A new character linked to Tilda, built from Tilda's "
                                      "template. It opens for editing right away."}}
check("panel actions", _p["actions"], [CREATE_ACTION])
check("no cards", _p["cards"], [])
_cf = (_p["create"] or {}).get("fields") or []
check("create fields", [(f["key"], f["type"], f["required"]) for f in _cf],
      [("body", "select", True), ("item_id", "item", True)])
check("body options", _cf[0].get("options") if _cf else None, [{"value": "Glut", "label": "Glut"}])
_po = describe("Obs")
check("Obs: no create form without bodies", _po["create"], None)
check("Obs: the create action", [a["id"] for a in _po["actions"]], ["create_linked"])
check("German title", describe(lang="de")["title"], "Verwandlung")

# ── [B] create a linked character ───────────────────────────────────────────
print("[B] create linked character")
check("create Ember", act("", "create_linked", value="Ember"),
      {"ok": True, "error": "", "message": "Ember was created as a linked character of Tilda.",
       "open_character": "Ember"})
check("bodies", lc.bodies_of("Tilda"), ["Ember", "Glut"])
check("Ember dormant", ch.get_character_status("Ember"), "dormant")
check("options now", [o["value"] for o in describe()["create"]["fields"][0]["options"]],
      ["Ember", "Glut"])
check("empty name", act("", "create_linked", value=""),
      {"ok": False, "error": "Name is required."})
check("taken name", act("", "create_linked", value="Glut")["error"],
      'A character named "Glut" already exists.')

# ── [C] create definitions ──────────────────────────────────────────────────
print("[C] create")
check("unknown body", save({"body": "Nobody", "item_id": "amulet"}),
      {"ok": False, "error": "Linked character: invalid selection."})
check("unknown item", save({"body": "Glut", "item_id": "nope"}),
      {"ok": False, "error": "This item does not exist."})
check("glut", save({"body": "Glut", "item_id": "amulet"}),
      {"ok": True, "error": "", "card_id": "glut"})
check("item taken", save({"body": "Ember", "item_id": "amulet"}),
      {"ok": False, "error": "This item already turns Tilda into Glut."})
check("ember", save({"body": "Ember", "item_id": "ring"}),
      {"ok": True, "error": "", "card_id": "ember"})

# ── [D] cards ───────────────────────────────────────────────────────────────
print("[D] cards")
_p = describe()
check("card order", [c["id"] for c in _p["cards"]], ["glut", "ember"])
_g = _p["cards"][0]
check("glut head", (_g["title"], _g["badges"], _g["subtitle"], _g["status"]),
      ("Glut", ["holds the item"], "Held by Tilda", "Ordinary self"))
check("glut actions", [(a["id"], a["label"]) for a in _g["actions"]],
      [("transform", "Transform now")])
check("glut fields", [(f["key"], f["type"], f.get("tab"), f.get("width")) for f in _g["fields"]], [
    ("body", "select", "transform", "m"), ("item_id", "item", "transform", "m"),
    ("enabled", "bool", "transform", "s"),
    ("activation_phrase", "text", "transform", "l"), ("revert_phrase", "text", "transform", "l"),
    ("max_duration_minutes", "int", "transform", "s"), ("cooldown_minutes", "int", "transform", "s"),
    ("transform_activity", "text", "transform", "s"), ("condition_id", "condition", "transform", "s"),
    ("knowers", "characters", "knowers", "full")])
check("glut values", _g["values"], {
    "body": "Glut", "item_id": "amulet", "enabled": True, "activation_phrase": "",
    "revert_phrase": "", "max_duration_minutes": 60, "cooldown_minutes": 30,
    "transform_activity": "transforming", "condition_id": "", "knowers": []})
_e = _p["cards"][1]
check("ember head", (_e["title"], _e["subtitle"]), ("Ember", "Nobody holds the item"))
check("ember actions", [(a["id"], a["label"], a["confirm"]) for a in _e["actions"]],
      [("give", "Give Ring to Tilda", "")])

# ── [E] knowers + numbers ───────────────────────────────────────────────────
print("[E] update")
check("knowers saved", save({"knowers": ["Kim", "Glut", "Tilda"]}, "glut"),
      {"ok": True, "error": "", "card_id": "glut"})
check("stored knowers", knowers.knower_names("Glut"), ["Kim"])
_sec = [s for s in secrets.list_secrets("Tilda") if s.get("source_ref") == "transformation:Glut"]
check("the knower secret", [(s.get("content"), s.get("body")) for s in _sec],
      [("Glut is secretly Tilda.", "Glut")])
check("card shows them", card("glut")["values"]["knowers"], ["Kim"])
check("negative max", save({"max_duration_minutes": "-5"}, "glut"),
      {"ok": False, "error": "Max duration: at least 0."})
_vals = dict(card("glut")["values"])
_vals["cooldown_minutes"] = -1
check("negative cooldown (provider)", panel.save("Tilda", "glut", _vals, "en"),
      {"ok": False, "error": "Minutes cannot be negative."})

# ── [F] actions ─────────────────────────────────────────────────────────────
print("[F] actions")
check("transform now", act("glut", "transform"),
      {"ok": True, "error": "", "message": "Tilda is now Glut."})
_g = card("glut")
check("status transformed", _g["status"], f"Transformed into Glut since {label(T0.canonical())}")
check("actions transformed", [(a["id"], a["label"]) for a in _g["actions"]],
      [("revert", "Revert now")])
check("delete while transformed", cp.delete_panel_card(PKG, "Tilda", "glut", "en"),
      {"ok": False, "error": "Revert first: Tilda is transformed into Glut."})
check("transform again", act("glut", "transform"),
      {"ok": False, "error": "Tilda is already transformed."})
_b = describe("Glut")
check("body intro", _b["intro"],
      "Glut is a linked character of Tilda — set the transformation up on Tilda's panel.")
check("body: no tabs/create/actions", (_b["tabs"], _b["create"], _b["actions"]), ([], None, []))
check("body cards", [(c["id"], c["title"], c["fields"]) for c in _b["cards"]],
      [("glut", "From Tilda", [])])
check("body status", _b["cards"][0]["status"],
      f"Glut stands in the world for Tilda since {label(T0.canonical())}")
check("body actions", [a["id"] for a in _b["cards"][0]["actions"]], ["revert"])
edit("Glut", movement_target="somewhere")
check("revert refused", act("glut", "revert", name="Glut"),
      {"ok": False, "error": lc.SWAP_REFUSAL_TEXT["journey"]})
check("still active", store.get_active("Tilda") is not None, True)
edit("Glut", movement_target="")
check("revert from the body's panel", act("glut", "revert", name="Glut"),
      {"ok": True, "error": "", "message": "Glut has turned back into Tilda."})
check("cooldown status", card("glut")["status"],
      "On cooldown until " + label((T0 + GameDuration.of(minutes=30)).canonical()))
_bc = describe("Glut")["cards"][0]
check("body dormant status", (_bc["status"], _bc["actions"]),
      ("Dormant — Tilda stands in the world.", []))
check("admin ignores the cooldown", act("glut", "transform")["ok"], True)
check("revert from the leader's panel", act("glut", "revert")["ok"], True)
check("not Obs's card", act("glut", "transform", name="Obs"),
      {"ok": False, "error": "This entry no longer exists."})

# ── [G] give / unknown ──────────────────────────────────────────────────────
print("[G] give")
check("give ring", act("ember", "give"), {"ok": True, "error": "", "message": "Tilda now holds Ring."})
check("unknown action", act("ember", "fly"), {"ok": False, "error": "Unknown action."})

# ── [H] delete + German ─────────────────────────────────────────────────────
print("[H] delete")
check("delete ember", cp.delete_panel_card(PKG, "Tilda", "ember", "en"), {"ok": True, "error": ""})
check("stored ids", [d["id"] for d in store.list_definitions()], ["glut"])
check("German tabs", [t["label"] for t in describe(lang="de")["tabs"]],
      ["Verwandlung", "Eingeweihte"])

# ── [J] deletion test ───────────────────────────────────────────────────────
print("[J] deletion test")
from app.core import hooks  # noqa: E402
hooks.unregister_owned_providers(PKG)
check("no panel", cp.has_panel(PKG), False)
try:
    describe()
    check("describe raises PanelNotFound", False, True)
except cp.PanelNotFound:
    check("describe raises PanelNotFound", True, True)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
