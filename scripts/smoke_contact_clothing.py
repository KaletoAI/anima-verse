#!/usr/bin/env python3
"""Smoke: contact clips and the clothes in the way (owner decisions 2026-11-25, ``app/core/contact_clothing.py``).

Usage:
    ./.venv/bin/python scripts/smoke_contact_clothing.py

Runs without a server and without the owner's world: ``paths.init`` on a temp dir before any world-DB import, a
fresh ``world.db`` there (``db.init_schema``), ``ANIMATION_CLIPS_DIR`` on an empty temp dir. Exit 0 = all green,
exit 1 = at least one check failed. The fixture items are created through ``inventory.add_item`` (and the item API)
in that temp world; profiles, clip sidecars, the pose → clip mapping and the loaded packages are stubs:

* packages: ONE fixture body slot ``lower`` (covered_by [bottom, underwear_bottom]) with a rig group ``chain``
  (applies_to gender male, ``contact_free: [bottom, underwear_bottom]``) and a channel region ``chan`` (applies_to
  gender female, ``contact_free: [bottom, underwear_bottom]``) — the shape the anatomy pack declares;
* clips (``clip_meta``; no package defaults): ``fx_channel`` roles [a, b], relations [{part a, at b, channel}];
  ``fx_mouth`` [{part a, at b, mouth}]; ``fx_hand`` [{part a, at b, hand_left}]; ``fx_three`` roles [a, b, c],
  [{part a, at b, channel}, {part c, at b, mouth}]; ``fx_none`` roles [a, b] without relations;
* poses: ``p_channel`` → fx_channel, ``p_mouth`` → fx_mouth, ``p_intimate`` → fx_plain (pair, no relations),
  ``p_intimate3`` → fx_plain3 (three roles, no relations), ``p_hug`` → fx_hug (pair, no relations, NOT intimate)
  (``interaction_engine.pair_kind_for_pose``);
* the contact default: a fixture provider ``contact.default_requirement`` answers True for p_intimate / p_intimate3
  and p_mouth (the package's intimate poses), like the intimacy package; [11] removes it (deletion test).

Fixture items (outfit_piece):
  jeans    slots [bottom]                                  closed trousers
  jeans_o  slots [bottom]  closable                        trousers that can be worn open
  boxers   slots [underwear_bottom]
  panties  slots [underwear_bottom]
  kilt     slots [bottom]  open_below
  skirt    slots [bottom]  open_below
  dress    slots [top, bottom] covers [underwear_bottom] open_below
  body     slots [top] covers [underwear_bottom]           closed (reaches the slot only through covers)
  shirt    slots [top]

Rule (by hand from the decisions): a role that is the ``part`` of a relation needs its part's contact_free slots
free (R1); the ``at`` role of a channel target its channel's slots (R2); mouth / hand targets ask nothing of the
receiving role. A worn piece blocks when it sits on, or covers, such a slot — unless it is open_below (R3) or worn
open; a free-text wardrobe never blocks. Kai = male (has the part, no channel), Mia = female (channel, no part).

Expected (clip fx_channel, Kai plays a = part, Mia plays b = channel):
 [1] part role Kai:  nothing → []; boxers → [boxers]; jeans → [jeans]; kilt → []; kilt+boxers → [boxers];
     shirt only → [] (top is not declared)
 [2] channel role Mia: nothing → []; panties → [panties]; jeans (no underwear) → [jeans];
     skirt (no underwear) → []; skirt+panties → [panties]; dress (open_below, covers underwear_bottom) → [];
     body (closed, covers underwear_bottom) → [body]; jeans_o worn open → []; jeans_o closed → [jeans_o]
 [3] mouth / hand targets (fx_mouth, fx_hand): Mia in panties → []; Kai in jeans → [jeans] (part role)
 [4] reversed: Mia plays a (part role) — no part declared for her → [] even in jeans; Kai as b of a channel target
     has no channel → [] even in boxers
 [5] three roles fx_three [Kai a, Mia b, Ben c]: Kai nothing, Mia panties, Ben jeans → 2 blockers (Mia panties,
     Ben jeans); the mouth relation asks nothing more of Mia
 [6] free-text wardrobe (template npc-temporary): Kai with jeans in equipped_pieces → []
 [7] a clip without relations (fx_none) → [] even with everything on
 [8] the reason: refusal() → reason "clothing", message names "Kai still wears Jeans (jeans)" and ChangeOutfit
     unequip_items; player_text in German: "Kai trägt noch Jeans"; free → {}
 [9] gated entry points refuse WITH the reason and pass when free:
     check_can_pair (pose p_channel; Kai jeans → message; nothing → ""), create_invite (blocked → None and no row;
     free → an invite id), pose_scene._start_finale (roles given; blocked → reason clothing + message; free → the
     next check, no_finale), interaction_engine.set_alt (blocked → clothing; free → unknown_alt), the furniture
     run's refusal details (prop_action_engine._refused with a pair run → message + blockers), the offer wording
     (prop_actions._worded → reason_text), the play routes' wording (_pair_refusal_text / _pair_clothing),
     start_interaction_at and _validate call the gate (AST: refusal before the anchors / before _requirements)
[10] prefill: judge() on fixture words — "Pleated skirt" / "Sommerkleid" / "Tartan kilt" / "Evening gown" open;
     "Jeans" / "Hosenrock" / "Skirt with shorts" / "Lace panties" / "Dress pants" closed; a piece on top only not
     judged; prefill_once flags the world items once (flag set, second run None) and needs declared slots
[11] the per-anatomy DEFAULT for an intimate clip without relations (fx_plain, Kai a, Mia b; by hand: each body
     by its own anatomy — Kai has the part → bottom + underwear_bottom free; Mia has no part but the channel → the
     same slots free):
     Kai in jeans → [Kai jeans] (refusal names "Kai still wears Jeans"); Mia in closed jeans_o → [Mia jeans_o];
     Mia in a skirt without underwear and Kai bare → []; skirt + panties → [Mia panties];
     three roles fx_plain3 [Kai, Mia, Ben]: Ben in jeans, Mia in panties → both (Ben is checked though he may only
     watch: strict by design);
     the mouth kind WITH its declared relation (p_mouth) still exempts the receiver: Mia in panties → [];
     the non-intimate pair p_hug: everyone fully dressed → {} (also via check_can_pair);
     deletion test — the provider unregistered: p_intimate with Kai in jeans → {}, nothing raises; a raising
     provider counts as "no" → {}
[12] item API round trip: POST open_below true → stored true; PUT without the key keeps it; PUT false clears it;
     a non-bool "yes" is stored false; GET /inventory/body-under-piece lists contact_free_slots [bottom,
     underwear_bottom]
"""
import ast
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="contact-clothing-clips-")
_TMP = tempfile.mkdtemp(prefix="contact-clothing-storage-")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp(prefix="contact-clothing-instance-")

from app.core import paths  # noqa: E402
paths.init(_TMP)
from app.core import config, db  # noqa: E402
config.load(Path(_TMP) / "config.json")
db.init_schema()

from app.core import animation_clips, body_slots, contact_clothing as cc  # noqa: E402
from app.core import interaction_engine as IE  # noqa: E402
from app.models import character as character_model  # noqa: E402
from app.models import inventory  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, RegionSpec, RigSpec  # noqa: E402

FAILURES = []
CHECKS = 0


def check(name, condition, detail=""):
    global CHECKS
    CHECKS += 1
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + ("" if condition else f": {detail}"))
    if not condition:
        FAILURES.append(name)


FREE = ["bottom", "underwear_bottom"]
LOWER = BodySlotSpec(id="lower", package_id="fixture", covered_by=list(FREE))
LOWER.rigs = [RigSpec(id="chain", op="appendage_chain", chains=[], applies_to={"gender": ["male"]},
                      contact_free=list(FREE))]
LOWER.regions = [RegionSpec(id="chan", kind="channel", bone="Hips", offset=[0, 0, 0], axis=[0, 1, 0], depth=0.2,
                            radius=0.03, cone_deg=30, funnel=0.05, accepts_ops=["appendage_chain"],
                            applies_to={"gender": ["female"]}, contact_free=list(FREE))]
PACKAGES = [SimpleNamespace(id="fixture", body_slots=[LOWER])]


def _rel(part, at, target):
    return {"part": part, "at": at, "target": target}


CLIPS = {
    "fx_channel": {"roles": ["a", "b"], "contact_relations": [_rel("a", "b", "channel")]},
    "fx_mouth": {"roles": ["a", "b"], "contact_relations": [_rel("a", "b", "mouth")]},
    "fx_hand": {"roles": ["a", "b"], "contact_relations": [_rel("a", "b", "hand_left")]},
    "fx_three": {"roles": ["a", "b", "c"], "contact_relations": [_rel("a", "b", "channel"), _rel("c", "b", "mouth")]},
    "fx_none": {"roles": ["a", "b"]},
}
CLIPS.update({"fx_plain": {"roles": ["a", "b"]}, "fx_plain3": {"roles": ["a", "b", "c"]},
              "fx_hug": {"roles": ["a", "b"]}})
POSES = {"p_channel": "fx_channel", "p_mouth": "fx_mouth", "p_intimate": "fx_plain", "p_intimate3": "fx_plain3",
         "p_hug": "fx_hug"}
INTIMATE = {"p_intimate", "p_intimate3", "p_mouth"}


def fixture_default(pose_key="", kind="", **_k):
    """The fixture package's contact default: its intimate poses (by key, else by the kind they name)."""
    if pose_key:
        return pose_key in INTIMATE
    return kind in {POSES[k] for k in INTIMATE}

ITEM_DEFS = [
    ("jeans", "Jeans", {"slots": ["bottom"], "closable": False}),
    ("jeans_o", "Open jeans", {"slots": ["bottom"], "closable": True}),
    ("boxers", "Boxers", {"slots": ["underwear_bottom"]}),
    ("panties", "Briefs", {"slots": ["underwear_bottom"]}),
    ("kilt", "Kilt", {"slots": ["bottom"], "open_below": True}),
    ("skirt", "Skirt", {"slots": ["bottom"], "open_below": True}),
    ("dress", "Dress", {"slots": ["top", "bottom"], "covers": ["underwear_bottom"], "open_below": True}),
    ("body", "Body", {"slots": ["top"], "covers": ["underwear_bottom"], "closable": False}),
    ("shirt", "Shirt", {"slots": ["top"]}),
]
for iid, name, piece in ITEM_DEFS:
    inventory.add_item(name, category="outfit_piece", outfit_piece=piece, item_id=iid, prompt_fragment=name.lower())
SLOT_OF = {"jeans": "bottom", "jeans_o": "bottom", "boxers": "underwear_bottom", "panties": "underwear_bottom",
           "kilt": "bottom", "skirt": "bottom", "dress": "bottom", "body": "top", "shirt": "top"}


def person(name, gender, *ids, open_ids=(), template=""):
    p = {"name": name, "gender": gender, "equipped_pieces": {SLOT_OF[i]: i for i in ids},
         "equipped_options": {"piece_state": {i: "open" for i in open_ids}}}
    if template:
        p["template"] = template
    return p


PROFILES = {}


def ids(found):
    return sorted((b["character"], b["item_id"]) for b in found)


def run_blockers(kind, roles, profiles):
    return ids(cc.blockers(kind, roles, profiles=profiles))


def main() -> int:
    patches = [
        patch.object(registry, "packages", return_value=PACKAGES),
        patch.object(body_slots, "slots_for_character", return_value=[LOWER]),
        patch.object(animation_clips, "clip_meta", side_effect=lambda kind, *a, **k: CLIPS.get(kind)),
        patch.object(animation_clips, "package_contact_targets", return_value={}),
        patch.object(IE, "pair_kind_for_pose", side_effect=lambda pose, *a, **k: POSES.get(pose, "")),
        patch.object(character_model, "get_character_profile", side_effect=lambda n, *a, **k: PROFILES.get(n)),
    ]
    for p in patches:
        p.start()
    from app.core import hooks
    hooks.register_provider(cc.DEFAULT_CAPABILITY, fixture_default, owner="fixture_intimacy", multiple=True)
    try:
        _truth_table()
        _reason()
        _entry_points()
        _prefill()
        _default()
        _item_api()
    finally:
        for p in patches:
            p.stop()
    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks green")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
        return 1
    return 0


def _truth_table():
    mia0 = person("Mia", "female")
    print("[1] part role (Kai plays a of fx_channel)")
    for label, worn, expect in (("nothing", (), []), ("boxers", ("boxers",), [("Kai", "boxers")]),
                                ("jeans", ("jeans",), [("Kai", "jeans")]), ("kilt", ("kilt",), []),
                                ("kilt+boxers", ("kilt", "boxers"), [("Kai", "boxers")]), ("shirt", ("shirt",), [])):
        got = run_blockers("fx_channel", {"a": "Kai", "b": "Mia"},
                           {"Kai": person("Kai", "male", *worn), "Mia": mia0})
        check(f"part role, {label}", got == expect, got)

    print("[2] channel role (Mia plays b of fx_channel)")
    kai0 = person("Kai", "male")
    for label, worn, opened, expect in (
            ("nothing", (), (), []), ("panties", ("panties",), (), [("Mia", "panties")]),
            ("closed trousers, no underwear", ("jeans",), (), [("Mia", "jeans")]),
            ("skirt, no underwear", ("skirt",), (), []),
            ("skirt+panties", ("skirt", "panties"), (), [("Mia", "panties")]),
            ("open-below dress that covers underwear_bottom", ("dress",), (), []),
            ("closed body that covers underwear_bottom", ("body",), (), [("Mia", "body")]),
            ("trousers worn open", ("jeans_o",), ("jeans_o",), []),
            ("the same trousers closed", ("jeans_o",), (), [("Mia", "jeans_o")])):
        got = run_blockers("fx_channel", {"a": "Kai", "b": "Mia"},
                           {"Kai": kai0, "Mia": person("Mia", "female", *worn, open_ids=opened)})
        check(f"channel role, {label}", got == expect, got)

    print("[3] mouth and hand targets")
    for kind in ("fx_mouth", "fx_hand"):
        got = run_blockers(kind, {"a": "Kai", "b": "Mia"},
                           {"Kai": kai0, "Mia": person("Mia", "female", "panties")})
        check(f"{kind}: receiving role in underwear passes", got == [], got)
        got = run_blockers(kind, {"a": "Kai", "b": "Mia"},
                           {"Kai": person("Kai", "male", "jeans"), "Mia": mia0})
        check(f"{kind}: part role in jeans blocks", got == [("Kai", "jeans")], got)

    print("[4] roles reversed")
    got = run_blockers("fx_channel", {"a": "Mia", "b": "Kai"},
                       {"Mia": person("Mia", "female", "jeans"), "Kai": person("Kai", "male", "boxers")})
    check("no part declared for Mia, no channel for Kai: nothing required", got == [], got)

    print("[5] three roles")
    got = run_blockers("fx_three", {"a": "Kai", "b": "Mia", "c": "Ben"},
                       {"Kai": kai0, "Mia": person("Mia", "female", "panties"), "Ben": person("Ben", "male", "jeans")})
    check("Mia's underwear and Ben's jeans block", got == [("Ben", "jeans"), ("Mia", "panties")], got)

    print("[6] free-text wardrobe")
    got = run_blockers("fx_channel", {"a": "Kai", "b": "Mia"},
                       {"Kai": person("Kai", "male", "jeans", template="npc-temporary"), "Mia": mia0})
    check("a free-text character never blocks", got == [], got)

    print("[7] a clip without contact relations")
    got = run_blockers("fx_none", {"a": "Kai", "b": "Mia"},
                       {"Kai": person("Kai", "male", "jeans", "boxers"), "Mia": person("Mia", "female", "panties")})
    check("no relations, no requirement", got == [], got)


def _reason():
    print("[8] the reason")
    profiles = {"Kai": person("Kai", "male", "jeans"), "Mia": person("Mia", "female")}
    refused = cc.refusal("p_channel", ["Kai", "Mia"], profiles=profiles)
    check("reason code", refused.get("reason") == "clothing", refused)
    msg = refused.get("message", "")
    check("message names the person, the piece and its id", "Kai still wears Jeans (jeans)" in msg, msg)
    check("message says how to take it off", "ChangeOutfit" in msg and "unequip_items" in msg, msg)
    check("blockers are public (no item dict)", all("item" not in b for b in refused.get("blockers", [])), refused)
    text = cc.player_text(refused["blockers"], "de")
    check("player text in German", text == "Kai trägt noch Jeans", text)
    check("player text in English", cc.player_text(refused["blockers"], "en") == "Kai still wears Jeans")
    free = cc.refusal("p_channel", ["Kai", "Mia"], profiles={"Kai": person("Kai", "male"), "Mia": person("Mia", "female")})
    check("free → {}", free == {}, free)


def _set_world(kai_worn=(), mia_worn=()):
    PROFILES.clear()
    PROFILES["Kai"] = person("Kai", "male", *kai_worn)
    PROFILES["Mia"] = person("Mia", "female", *mia_worn)


def _entry_points():
    print("[9] gated entry points")
    from app.core import pose_scene, prop_action_engine as engine, prop_actions
    with patch("app.core.travel_engine.get_journey", return_value=None), \
            patch.object(IE, "get_interaction", return_value=None), \
            patch.object(IE, "together_in", return_value=None), \
            patch.object(IE, "_pose_participation", return_value=""), \
            patch.object(character_model, "is_character_sleeping", return_value=False), \
            patch.object(character_model, "get_character_current_location", return_value="loc"), \
            patch.object(character_model, "get_character_current_room", return_value="room"):
        _set_world(kai_worn=("jeans",))
        got = IE.check_can_pair("Kai", "Mia", "p_channel")
        check("check_can_pair refuses with the reason", "Kai still wears Jeans" in got, got)
        got = IE.check_can_pair("Kai", "Mia", "p_mouth")
        check("check_can_pair: mouth pose, part role in jeans refuses too", "Kai still wears Jeans" in got, got)
        _set_world()
        check("check_can_pair passes when free", IE.check_can_pair("Kai", "Mia", "p_channel") == "")
        _set_world(mia_worn=("panties",))
        check("check_can_pair: mouth pose with the receiver in underwear passes",
              IE.check_can_pair("Kai", "Mia", "p_mouth") == "")

        _set_world(kai_worn=("jeans",))
        check("create_invite refuses (None)", IE.create_invite("Kai", "Mia", "p_channel") is None)
        rows = db.get_connection().execute("SELECT COUNT(*) FROM interaction_invites").fetchone()[0]
        check("no invitation row written", rows == 0, rows)
        _set_world()
        with patch("app.core.hooks.emit", return_value=None):
            got = IE.create_invite("Kai", "Mia", "p_channel")
        check("create_invite records when free", bool(got), got)

    _set_world(kai_worn=("jeans",))
    roles = {"a": "Kai", "b": "Mia"}
    with patch.object(pose_scene, "finale_kind", return_value="fx_channel"):
        result, _ = pose_scene._start_finale("scene1", "Kai", "p_channel", "a", 1.0, roles=roles)
        check("finale refused with the reason", result.get("reason") == "clothing"
              and "Kai still wears Jeans" in result.get("message", ""), result)
        _set_world()
        result, _ = pose_scene._start_finale("scene1", "Kai", "p_channel", "a", 1.0, roles=roles)
        check("finale passes the gate when free (next check: no clip file)", result.get("reason") == "no_finale",
              result)

    current = {"kind": "fx_channel", "role": "a", "members": {"a": "Kai", "b": "Mia"}}
    with patch.object(IE, "get_interaction", return_value=current):
        _set_world(mia_worn=("panties",))
        got = IE.set_alt("Kai", "alt1")
        check("alt half refused with the reason", got.get("reason") == "clothing"
              and "Mia still wears Briefs" in got.get("message", ""), got)
        _set_world()
        got = IE.set_alt("Kai", "alt1")
        check("alt half passes the gate when free (next check: unknown_alt)", got.get("reason") == "unknown_alt",
              got)

    _set_world(kai_worn=("jeans",))
    run = {"actor": "Kai", "members": ["Mia"], "definition": {"ability": "pair", "pose_key": "p_channel"},
           "data": {"clip_roles": {"a": "Kai", "b": "Mia"}}}
    with patch.object(engine.store, "people", side_effect=lambda r: [r["actor"], *r["members"]]):
        got = engine._refused("clothing", run)
        check("furniture refusal carries message + blockers", "Kai still wears Jeans" in got.get("message", "")
              and got.get("blockers"), got)
        check("another refusal code carries nothing more", set(engine._refused("no_free_slot", run)) ==
              {"execution_id", "status", "reason"})
        worded = prop_actions._worded(dict(enabled=False, reason="clothing", blockers=got["blockers"]), "de")
        check("offer wording in the player's language", worded.get("reason_text") == "Kai trägt noch Jeans", worded)

    from app.routes import play as play_routes, prop_actions as prop_routes
    with patch.object(character_model, "get_character_language", return_value="en"):
        text = play_routes._pair_refusal_text("Kai", "Mia", "p_channel",
                                              cc.refusal("p_channel", ["Kai", "Mia"])["message"], "Kai")
        check("play route words the clothing refusal for the player", text == "Kai still wears Jeans", text)
        check("play route keeps any other refusal as it is",
              play_routes._pair_refusal_text("Kai", "Mia", "p_channel", "Mia is asleep", "Kai") == "Mia is asleep")
        worded = prop_routes._worded({"status": "refused", "reason": "clothing", "blockers": got["blockers"]}, "Kai")
        check("furniture route adds reason_text", worded.get("reason_text") == "Kai still wears Jeans", worded)
        with patch.object(character_model, "list_available_characters", return_value=["Kai", "Mia"]), \
                patch.object(character_model, "get_character_current_location", return_value="loc"), \
                patch.object(character_model, "get_character_current_room", return_value="room"):
            # The avatar initiates and plays a (no role gender): Kai's jeans block both poses with Mia; Mia as the
            # avatar plays a herself — no part declared for her, no channel for Kai: nothing listed.
            poses = [("p_channel", "fx_channel"), ("p_mouth", "fx_mouth")]
            got = play_routes._pair_clothing("Kai", poses, "en")
            check("options list the blocked free poses per partner",
                  got == {"Mia": {"p_channel": "Kai still wears Jeans", "p_mouth": "Kai still wears Jeans"}}, got)
            got = play_routes._pair_clothing("Mia", poses, "en")
            check("options: the reversed roles block nothing", got == {}, got)

    # The two starts that need a whole furniture run: the gate sits where it must (AST order).
    src = (ROOT / "app/core/interaction_engine.py").read_text(encoding="utf-8")
    body = _function_source(src, "start_interaction_at")
    check("start_interaction_at gates after the role check and before the anchors",
          0 < body.find("pair_roles_changed") < body.find("contact_clothing.refusal") < body.find("anchors = "),
          "order")
    src = (ROOT / "app/core/prop_action_engine.py").read_text(encoding="utf-8")
    body = _function_source(src, "_validate")
    check("_validate gates before the requirements",
          0 < body.find("contact_clothing.refusal") < body.find("_requirements(run"), "order")


def _function_source(src, name):
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


def _prefill():
    print("[10] open-below prefill")
    from app.core import open_below_migration as obm

    def item(name, slots, **extra):
        return {"id": name, "name": name, "category": "outfit_piece",
                "outfit_piece": {"slots": slots, **extra.pop("piece", {})}, **extra}
    for name, expect in (("Pleated skirt", "open"), ("Sommerkleid", "open"), ("Tartan kilt", "open"),
                         ("Evening gown", "open"), ("Jeans", "closed"), ("Hosenrock", "closed"),
                         ("Skirt with shorts", "closed"), ("Lace panties", "closed"), ("Dress pants", "closed")):
        verdict, why = obm.judge(item(name, ["bottom"]), FREE)
        check(f"judge '{name}' → {expect}", verdict == expect, why)
    check("a piece on an undeclared slot is not judged", obm.judge(item("Summer dress", ["top"]), FREE) == ("", ""))
    check("a description word alone never opens", obm.judge(item("Item 7", ["bottom"], description="a long wool skirt"),
                                                            FREE)[0] == "closed")
    check("a one-piece over top and bottom opens", obm.judge(item("Velvet Night", ["top", "bottom"]), FREE)[0] == "open")
    check("a closed one-piece stays closed",
          obm.judge(item("Black Leather Bodysuit", ["top", "bottom"]), FREE)[0] == "closed")
    check("an outer piece is skipped whatever its name",
          obm.judge(item("Silk Robe", ["outer"], piece={"covers": ["underwear_bottom"]}), FREE)[0] == "skip")
    check("an underwear piece is skipped", obm.judge(item("Slip dress", ["underwear_bottom"]), FREE)[0] == "skip")

    inventory.add_item("Midi skirt", category="outfit_piece", outfit_piece={"slots": ["bottom"]}, item_id="midi")
    inventory.add_item("Cargo shorts", category="outfit_piece", outfit_piece={"slots": ["bottom"]}, item_id="cargo")
    shared_file = Path(_TMP) / "shared-items.json"
    shared_file.write_text('{"items": [{"id": "s_robe", "name": "Bathrobe", "category": "outfit_piece", '
                           '"outfit_piece": {"slots": ["outer"], "covers": ["underwear_bottom"]}}, {"id": "s_kilt", "name": "Kilt", '
                           '"category": "outfit_piece", "outfit_piece": {"slots": ["bottom"]}}]}', encoding="utf-8")
    with patch.object(inventory, "_get_shared_items_file", return_value=shared_file):
        with patch.object(cc, "declared_slots", return_value=[]):
            check("no declared slot: waits (None, no flag)", obm.prefill_once() is None)
        got = obm.prefill_once()
        check("world piece flagged", "midi" in (got or {}).get("world", []), got)
        check("closed world piece left", "cargo" not in (got or {}).get("world", []), got)
        check("shared piece flagged (the outer robe skipped)", (got or {}).get("shared") == ["s_kilt"], got)
        check("midi stored open_below", inventory.get_item("midi")["outfit_piece"].get("open_below") is True)
        check("cargo stored closed", inventory.get_item("cargo")["outfit_piece"].get("open_below") is False)
        check("shared marker written", bool(inventory.get_shared_items_meta().get(obm.SHARED_KEY)))
        check("second run: nothing to do", obm.prefill_once() is None)


def _default():
    print("[11] the per-anatomy default for an intimate clip without relations")
    from app.core import hooks

    def ref(pose, names, profiles):
        return cc.refusal(pose, names, profiles=profiles)

    kai0, mia0 = person("Kai", "male"), person("Mia", "female")
    got = ref("p_intimate", ["Kai", "Mia"], {"Kai": person("Kai", "male", "jeans"), "Mia": mia0})
    check("man in trousers: blocked, named", ids(got.get("blockers", [])) == [("Kai", "jeans")]
          and "Kai still wears Jeans" in got.get("message", ""), got)
    got = ref("p_intimate", ["Kai", "Mia"], {"Kai": kai0, "Mia": person("Mia", "female", "jeans_o")})
    check("woman in closed trousers: blocked", ids(got.get("blockers", [])) == [("Mia", "jeans_o")], got)
    got = ref("p_intimate", ["Kai", "Mia"], {"Kai": kai0, "Mia": person("Mia", "female", "skirt")})
    check("woman in a skirt without underwear, man bare: allowed", got == {}, got)
    got = ref("p_intimate", ["Kai", "Mia"], {"Kai": kai0, "Mia": person("Mia", "female", "skirt", "panties")})
    check("skirt + underwear: blocked", ids(got.get("blockers", [])) == [("Mia", "panties")], got)
    got = ref("p_intimate3", ["Kai", "Mia", "Ben"], {"Kai": kai0, "Mia": person("Mia", "female", "panties"),
                                                    "Ben": person("Ben", "male", "jeans")})
    check("three roles: Ben's jeans and Mia's underwear", ids(got.get("blockers", [])) ==
          [("Ben", "jeans"), ("Mia", "panties")], got)
    got = ref("p_mouth", ["Kai", "Mia"], {"Kai": kai0, "Mia": person("Mia", "female", "panties")})
    check("declared mouth relation still exempts the receiver", got == {}, got)
    dressed = {"Kai": person("Kai", "male", "jeans", "boxers"), "Mia": person("Mia", "female", "jeans_o", "panties")}
    check("non-intimate pair never blocked", ref("p_hug", ["Kai", "Mia"], dressed) == {})
    PROFILES.clear()
    PROFILES.update(dressed)
    with patch("app.core.travel_engine.get_journey", return_value=None), \
            patch.object(IE, "get_interaction", return_value=None), \
            patch.object(IE, "together_in", return_value=None), \
            patch.object(IE, "_pose_participation", return_value=""), \
            patch.object(character_model, "is_character_sleeping", return_value=False), \
            patch.object(character_model, "get_character_current_location", return_value="loc"), \
            patch.object(character_model, "get_character_current_room", return_value="room"):
        check("check_can_pair: the hug passes fully dressed", IE.check_can_pair("Kai", "Mia", "p_hug") == "")
        got = IE.check_can_pair("Kai", "Mia", "p_intimate")
        check("check_can_pair: the intimate pose refuses fully dressed", "Kai still wears" in got
              and "Mia still wears" in got, got)
    check("finale by kind only (no pose key) finds the default too",
          cc.refusal(kind="fx_plain", roles={"a": "Kai", "b": "Mia"}, profiles=dressed) != {})

    hooks.unregister_owned_providers("fixture_intimacy")
    try:
        got = ref("p_intimate", ["Kai", "Mia"], {"Kai": person("Kai", "male", "jeans"), "Mia": mia0})
        check("deletion test: without the package nothing is gated", got == {}, got)

        def broken(**_k):
            raise RuntimeError("broken package")
        hooks.register_provider(cc.DEFAULT_CAPABILITY, broken, owner="fixture_broken", multiple=True)
        got = ref("p_intimate", ["Kai", "Mia"], {"Kai": person("Kai", "male", "jeans"), "Mia": mia0})
        check("a raising provider counts as no", got == {}, got)
    finally:
        hooks.unregister_owned_providers("fixture_broken")
        hooks.register_provider(cc.DEFAULT_CAPABILITY, fixture_default, owner="fixture_intimacy", multiple=True)


def _item_api():
    print("[12] item editor round trip (API)")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import inventory as inventory_routes
    app = FastAPI()
    app.include_router(inventory_routes.router)
    client = TestClient(app)
    r = client.post("/inventory/items", json={"name": "Wrap skirt", "category": "outfit_piece", "id": "wrap",
                                               "outfit_piece": {"slots": ["bottom"], "open_below": True}})
    check("create", r.status_code == 200, r.text[:300])
    check("created open_below true", inventory.get_item("wrap")["outfit_piece"].get("open_below") is True)
    r = client.put("/inventory/items/wrap", json={"outfit_piece": {"slots": ["bottom"]}})
    check("update without the key", r.status_code == 200, r.text[:300])
    check("kept true", inventory.get_item("wrap")["outfit_piece"].get("open_below") is True)
    client.put("/inventory/items/wrap", json={"outfit_piece": {"slots": ["bottom"], "open_below": False}})
    check("update false clears", inventory.get_item("wrap")["outfit_piece"].get("open_below") is False)
    client.put("/inventory/items/wrap", json={"outfit_piece": {"slots": ["bottom"], "open_below": "yes"}})
    check("a non-bool is stored false", inventory.get_item("wrap")["outfit_piece"].get("open_below") is False)
    r = client.get("/inventory/items/wrap")
    check("GET returns the flag", r.json()["item"]["outfit_piece"].get("open_below") is False, r.text[:300])
    r = client.get("/inventory/body-under-piece")
    check("body-under-piece lists the declared slots", r.json().get("contact_free_slots") == FREE, r.text[:300])


if __name__ == "__main__":
    sys.exit(main())
