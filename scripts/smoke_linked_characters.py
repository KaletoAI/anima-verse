#!/usr/bin/env python3
"""Smoke: linked characters — the link map, locked fields, shared soul
sections, the dormant status and link/unlink/create (task 3 of the
linked-characters plan).

Usage:  ./.venv/bin/python scripts/smoke_linked_characters.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM.

THE SPEC (docs/superpowers/specs/2026-11-05-linked-characters-design.md:
Terms, "Core: app/core/linked_characters.py", "Core: dormant status", "Locked
fields (read-through)", rulings R2/R3, task-3 brief + ruling P2):
  * a body names its leader in ``linked_to``; a leader may have several
    bodies; no chains; ``mind_of(body)`` = leader, else the name itself;
    ``family_of`` = leader first, then the bodies sorted;
  * ``gender``/``age`` of a body are read LIVE from the leader and never
    stored on the body; the editor note is "from <leader>";
  * ``soul``/``beliefs``/``lessons`` (default) are read from and written to
    the leader; the body's soul editor refuses writing them;
  * ``dormant`` is out of every roster, but EXISTS (character_exists, name
    checks, the admin list with its status);
  * linking an existing character makes it dormant (placement cleared, no
    off-map marker); unlinking a dormant body puts it at the leader's
    location/room; a present body cannot be unlinked; a leader with bodies
    cannot be deleted.

FIXTURE
    Location "Inn": rooms taproom (the declared entry room) and cellar.
    Characters (template human-roleplay): Tilda (gender female, age 30, in
    Inn/cellar), Kim (in Inn/taproom at point (1, 2), seat {"id": "bench"},
    off-map marker "_offmap_return_location": "Inn"), Obs (in Inn/taproom),
    Tess (template npc-temporary). User "demo" (role user) allowed [Tilda].

WHAT FOLLOWS BY HAND
[A] Constants: DORMANT_STATUS "dormant", OUT_OF_WORLD_STATUSES {pooled,
    dormant}; is_out_of_world: "dormant" True, "pooled" True, "" False;
    LOCKED_PROFILE_FIELDS ("gender", "age"); SHAREABLE_SOUL_SECTIONS the seven
    without goals; DEFAULT_SHARED_SOUL ("soul", "beliefs", "lessons").
[B] Validation (each refused, nothing stored, nobody linked):
      link(Tilda, Tilda)   -> "A character cannot be linked to itself."
      link(Kim, Nobody)    -> "Unknown character: Nobody."
      link(Nobody, Tilda)  -> "Unknown character: Nobody."
      link(Tess, Tilda)    -> "Temporary NPCs cannot be linked."
      link(Kim, Tilda, shared [goals]) -> "This soul section cannot be shared: goals."
      Kim is the ACTIVE character of user "play" (settings.active_character)
      -> "Pick another avatar for play first: Kim is their active character."
      (avatar_owner(Kim) "play"); the setting cleared again -> avatar_owner "".
      Kim with a movement target -> "Cannot link Kim right now: Travelling
      right now — wait until the journey ends."  (swap_refusal(Kim) "journey")
[C] create_linked(Tilda, "Glut") -> ok. Glut: linked_to Tilda in the stored
    blob, shared default [soul, beliefs, lessons], status "dormant", no
    location; demo now allowed [Tilda, Glut]. create_linked(Tilda, "kim") ->
    'A character named "kim" already exists.'
    Then link(Kim, Tilda) -> ok (movement target cleared first).
[D] Map: mind_of(Glut) Tilda, mind_of(Tilda) Tilda, mind_of(Obs) Obs;
    leader_of(Tilda) None; bodies_of(Tilda) [Glut, Kim]; family_of(Kim)
    [Tilda, Glut, Kim]; is_linked(Glut) True, is_linked(Tilda) False;
    present_member(Glut) Tilda.
    Chain: link(Obs, Glut) -> "Glut is itself linked to Tilda — link to Tilda
    instead."; body is leader: link(Tilda, Obs) -> "Tilda leads linked
    characters and cannot be linked to another one."; re-link elsewhere:
    link(Glut, Obs) -> "Glut is already linked to Tilda — unlink it first.";
    swap_refusal(Obs) "" (idle).
[E] Kim's dormancy cleared its placement: location "", room "", point None,
    no "place", no "_offmap_return_location"; status "dormant".
[F] Locked fields: Glut reads gender "female", age 30. Tilda saves gender
    "male", age 31 -> Glut reads "male"/31. Glut's own save with gender "x"
    -> the stored blob of Glut has neither gender nor age; the read still
    says "male". build_profile_payload(Glut).field_overrides.gender =
    {"value": "male", "label": "Tilda", "linked_from": "Tilda"}; Tilda's
    payload has no gender override.
[G] Soul: Tilda's soul/beliefs.md holds "- Fire is honest."; Glut's
    soul/goals.md holds "- Find the comet.". soul_owner(Glut, beliefs) Tilda,
    (Glut, soul/beliefs.md) Tilda, (Glut, goals) Glut, (Tilda, beliefs) Tilda.
    Glut's profile character_beliefs contains "Fire is honest";
    soul_writer.get_soul_file_path(Glut, beliefs) is Tilda's file and
    load_section_lines(Glut, beliefs, about_self) = ["- Fire is honest."]
    (its contract: the non-empty body lines, stripped);
    read_soul_file(Glut, beliefs) raw = Tilda's raw, shared_from "Tilda";
    write_soul_file(Glut, beliefs) -> 409 "This section is shared with Tilda
    — edit it on Tilda."; write_soul_file(Glut, goals) -> success.
    build_soul_files(Glut): beliefs shared_from "Tilda", goals shared_from "".
    A read-modify-write save of Glut leaves Glut's OWN soul/beliefs.md without
    "Fire is honest" (the mind is never copied into the body).
[H] Rosters with Glut + Kim dormant: list_available_characters() =
    [Obs, Tess, Tilda]; character_exists(Glut) True, ("glut") True;
    list_available_characters(include_dormant=True) adds Glut, Kim;
    npc_ops.name_is_taken("glut") True; create_character_core("Glut") ->
    409; admin list rows: Glut status "dormant", Tilda status "". A stale raw
    location on dormant Glut (Inn/taproom) -> places._census(Inn, None) has
    no Glut; a raw journey on Glut + movement target on Obs ->
    list_active_journeys names [Obs].
[I] npc_pool: revive_from_pool on a temporary NPC with status "dormant"
    (Tess, raw) -> False, Tess still "dormant"; pool_npc(Tess) -> False.
[J] Unlink: Tilda in Inn/cellar; unlink(Glut) -> ok: status "", location
    Inn, room cellar, not linked; bodies_of(Tilda) [Kim]; Glut's stored blob
    now holds gender "male" (what it showed, its own from now on). Tilda's room
    cleared (raw) -> unlink(Kim) -> room "taproom" (the entry room).
    Re-link Kim, then make it present by status (as a swap would): unlink
    -> "Kim stands in the world right now — revert first.".
[K] Delete: delete_refusal(Tilda) "Tilda leads linked characters (Kim) —
    unlink or delete the linked characters first."; delete_character(Tilda)
    False, row kept. Tilda dormant while Kim present: delete_refusal(Kim)
    "Kim stands in the world for Tilda right now — revert first.". Kim dormant
    again, Tilda present: delete_character(Kim) True; bodies_of(Tilda) [].
[L] Routes: GET/PUT/DELETE /characters/{name}/link and POST
    /characters/{leader}/linked exist and depend on require_admin.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="linked-characters-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core.keyed_lock import keyed_lock  # noqa: E402
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


def section(title):
    print(title)


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        for k, v in values.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
        assert ch.save_character_profile(name, p), name


def stored_blob(name):
    row = db.get_connection().execute(
        "SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else None


def raw_state(name, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with db.transaction() as conn:
        conn.execute(f"UPDATE character_state SET {sets} WHERE character_name=?",
                     (*cols.values(), name))


def raw_status(name, status):
    with db.transaction() as conn:
        conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))


class Req:
    cookies: dict = {}
    headers: dict = {}

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


# ── fixture ─────────────────────────────────────────────────────────────────
INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."},
                         {"id": "cellar", "name": "Cellar", "description": "Barrels."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)

for _name, _tmpl in (("Tilda", "human-roleplay"), ("Kim", "human-roleplay"),
                     ("Obs", "human-roleplay"), ("Tess", "npc-temporary")):
    assert ch.save_character_profile(_name, {"character_name": _name, "template": _tmpl},
                                     create_new=True), _name
edit("Tilda", current_location=INN, current_room="cellar", gender="female", age=30)
edit("Kim", current_location=INN, current_room="taproom", place={"id": "bench"},
     _offmap_return_location=INN)
ch._write_character_pos("Kim", 1.0, 2.0)
edit("Obs", current_location=INN, current_room="taproom")

from app.core import users  # noqa: E402
DEMO = users.create_user("demo", "demo-password-1", allowed_characters=["Tilda"])

from app.core import linked_characters as lc  # noqa: E402

# ── [A] ─────────────────────────────────────────────────────────────────────
section("[A] constants")
check("DORMANT_STATUS", ch.DORMANT_STATUS, "dormant")
check("OUT_OF_WORLD_STATUSES", set(ch.OUT_OF_WORLD_STATUSES), {"pooled", "dormant"})
check("is_out_of_world(dormant)", ch.is_out_of_world("dormant"), True)
check("is_out_of_world(pooled)", ch.is_out_of_world("pooled"), True)
check("is_out_of_world('')", ch.is_out_of_world(""), False)
check("LOCKED_PROFILE_FIELDS", lc.LOCKED_PROFILE_FIELDS, ("gender", "age"))
check("SHAREABLE_SOUL_SECTIONS", lc.SHAREABLE_SOUL_SECTIONS,
      ("soul", "beliefs", "lessons", "personality", "presence", "tasks", "roleplay_rules"))
check("DEFAULT_SHARED_SOUL", lc.DEFAULT_SHARED_SOUL, ("soul", "beliefs", "lessons"))

# ── [B] ─────────────────────────────────────────────────────────────────────
section("[B] validation")
check("self", lc.link("Tilda", "Tilda")["error"], "A character cannot be linked to itself.")
check("unknown leader", lc.link("Kim", "Nobody")["error"], "Unknown character: Nobody.")
check("unknown body", lc.link("Nobody", "Tilda")["error"], "Unknown character: Nobody.")
check("temporary NPC", lc.link("Tess", "Tilda")["error"], "Temporary NPCs cannot be linked.")
check("goals not shareable", lc.link("Kim", "Tilda", shared=["goals"])["error"],
      "This soul section cannot be shared: goals.")
PLAY = users.create_user("play", "play-password-1", allowed_characters=["Kim"])
users.update_user(PLAY, settings={"active_character": "Kim"})
check("avatar_owner(Kim)", lc.avatar_owner("Kim"), "play")
check("active avatar refused", lc.link("Kim", "Tilda")["error"],
      "Pick another avatar for play first: Kim is their active character.")
users.update_user(PLAY, settings={"active_character": ""})
check("avatar_owner(Kim) cleared", lc.avatar_owner("Kim"), "")
edit("Kim", movement_target="somewhere")
check("swap_refusal(Kim)", lc.swap_refusal("Kim"), "journey")
check("refusal state", lc.link("Kim", "Tilda")["error"],
      "Cannot link Kim right now: Travelling right now — wait until the journey ends.")
check("nobody linked", lc.bodies_of("Tilda"), [])
check("SWAP_REFUSAL_TEXT keys", sorted(lc.SWAP_REFUSAL_TEXT),
      sorted(["journey", "sleeping", "interaction", "prop_action", "reading", "party"]))

# ── [C] ─────────────────────────────────────────────────────────────────────
section("[C] create_linked + link")
res = lc.create_linked("Tilda", "Glut")
check("create ok", (res["ok"], res["error"]), (True, ""))
_glut = stored_blob("Glut") or {}
check("Glut linked_to stored", _glut.get("linked_to"), "Tilda")
check("Glut shared default", _glut.get("shared_soul_sections"), ["soul", "beliefs", "lessons"])
check("Glut template = Tilda's", _glut.get("template"), "human-roleplay")
check("Glut dormant", ch.get_character_status("Glut"), "dormant")
check("Glut no location", ch.get_character_current_location("Glut"), "")
check("demo allowed", users.get_user_by_id(DEMO)["allowed_characters"], ["Tilda", "Glut"])
check("taken name", lc.create_linked("Tilda", "kim")["error"],
      'A character named "kim" already exists.')
edit("Kim", movement_target="")
res = lc.link("Kim", "Tilda")
check("link Kim ok", (res["ok"], res["error"]), (True, ""))

# ── [D] ─────────────────────────────────────────────────────────────────────
section("[D] the map")
check("mind_of(Glut)", lc.mind_of("Glut"), "Tilda")
check("mind_of(Tilda)", lc.mind_of("Tilda"), "Tilda")
check("mind_of(Obs)", lc.mind_of("Obs"), "Obs")
check("leader_of(Tilda)", lc.leader_of("Tilda"), None)
check("bodies_of(Tilda)", lc.bodies_of("Tilda"), ["Glut", "Kim"])
check("family_of(Kim)", lc.family_of("Kim"), ["Tilda", "Glut", "Kim"])
check("is_linked(Glut)", lc.is_linked("Glut"), True)
check("is_linked(Tilda)", lc.is_linked("Tilda"), False)
check("present_member(Glut)", lc.present_member("Glut"), "Tilda")
check("chain", lc.link("Obs", "Glut")["error"],
      "Glut is itself linked to Tilda — link to Tilda instead.")
check("body is leader", lc.link("Tilda", "Obs")["error"],
      "Tilda leads linked characters and cannot be linked to another one.")
check("already linked", lc.link("Glut", "Obs")["error"],
      "Glut is already linked to Tilda — unlink it first.")
check("swap_refusal(Obs)", lc.swap_refusal("Obs"), "")

# ── [E] ─────────────────────────────────────────────────────────────────────
section("[E] dormancy cleared the placement")
_kim = ch.get_character_profile("Kim")
check("Kim status", ch.get_character_status("Kim"), "dormant")
check("Kim location", _kim.get("current_location", ""), "")
check("Kim room", _kim.get("current_room", ""), "")
check("Kim point", ch.get_character_pos("Kim"), None)
check("Kim seat", _kim.get("place"), None)
check("Kim off-map marker", "_offmap_return_location" in (stored_blob("Kim") or {}), False)

# ── [F] ─────────────────────────────────────────────────────────────────────
section("[F] locked fields")
_g = ch.get_character_profile("Glut")
check("Glut gender from Tilda", (_g.get("gender"), _g.get("age")), ("female", 30))
edit("Tilda", gender="male", age=31)
_g = ch.get_character_profile("Glut")
check("Glut follows live", (_g.get("gender"), _g.get("age")), ("male", 31))
edit("Glut", gender="x")
_gb = stored_blob("Glut") or {}
check("Glut blob without gender/age", ("gender" in _gb, "age" in _gb), (False, False))
check("Glut read still leader's", ch.get_character_profile("Glut").get("gender"), "male")
from app.core import character_ops  # noqa: E402
check("payload note", character_ops.build_profile_payload("Glut")["field_overrides"].get("gender"),
      {"value": "male", "label": "Tilda", "linked_from": "Tilda"})
check("leader has no note",
      "gender" in character_ops.build_profile_payload("Tilda")["field_overrides"], False)

# ── [G] ─────────────────────────────────────────────────────────────────────
section("[G] shared soul sections")
_tdir = ch.get_character_dir("Tilda")
_gdir = ch.get_character_dir("Glut")
(_tdir / "soul").mkdir(parents=True, exist_ok=True)
(_gdir / "soul").mkdir(parents=True, exist_ok=True)
(_tdir / "soul" / "beliefs.md").write_text("# Beliefs\n\n## About myself\n- Fire is honest.\n",
                                           encoding="utf-8")
(_gdir / "soul" / "goals.md").write_text("# Goals\n\n## Short-term\n- Find the comet.\n",
                                         encoding="utf-8")
from app.models.character_template import invalidate_source_file  # noqa: E402
invalidate_source_file(_tdir / "soul" / "beliefs.md")
invalidate_source_file(_gdir / "soul" / "goals.md")
check("soul_owner(Glut, beliefs)", lc.soul_owner("Glut", "beliefs"), "Tilda")
check("soul_owner(Glut, soul/beliefs.md)", lc.soul_owner("Glut", "soul/beliefs.md"), "Tilda")
check("soul_owner(Glut, goals)", lc.soul_owner("Glut", "goals"), "Glut")
check("soul_owner(Tilda, beliefs)", lc.soul_owner("Tilda", "beliefs"), "Tilda")
check("Glut profile beliefs from Tilda",
      "Fire is honest" in (ch.get_character_profile("Glut").get("character_beliefs") or ""), True)
check("Glut profile goals own",
      "Find the comet" in (ch.get_character_profile("Glut").get("character_goals") or ""), True)
from app.core import soul_writer  # noqa: E402
check("soul_writer path", soul_writer.get_soul_file_path("Glut", "beliefs"),
      _tdir / "soul" / "beliefs.md")
check("soul_writer lines", soul_writer.load_section_lines("Glut", "beliefs", "about_self"),
      ["- Fire is honest."])
_rs = character_ops.read_soul_file("Glut", "beliefs")
check("read_soul_file raw", _rs["raw"], (_tdir / "soul" / "beliefs.md").read_text(encoding="utf-8"))
check("read_soul_file shared_from", _rs.get("shared_from"), "Tilda")
try:
    asyncio.run(character_ops.write_soul_file("Glut", "beliefs", Req({"content": "# B\n- no"})))
    check("write shared refused", "no error", 409)
except HTTPException as e:
    check("write shared refused", (e.status_code, e.detail),
          (409, "This section is shared with Tilda — edit it on Tilda."))
check("Tilda's beliefs untouched",
      "Fire is honest" in (_tdir / "soul" / "beliefs.md").read_text(encoding="utf-8"), True)
_w = asyncio.run(character_ops.write_soul_file("Glut", "goals", Req({"content": "# G\n- Fly."})))
check("write own section", _w.get("status"), "success")
_files = {f["section"]: f for f in character_ops.build_soul_files("Glut")["files"]}
check("soul files beliefs shared_from", _files["beliefs"].get("shared_from"), "Tilda")
check("soul files goals shared_from", _files["goals"].get("shared_from"), "")
edit("Glut", current_feeling="calm")
_own = _gdir / "soul" / "beliefs.md"
check("mind not copied into the body",
      "Fire is honest" in (_own.read_text(encoding="utf-8") if _own.exists() else ""), False)

# ── [H] ─────────────────────────────────────────────────────────────────────
section("[H] rosters")
check("list_available_characters()", ch.list_available_characters(), ["Obs", "Tess", "Tilda"])
check("character_exists(Glut)", ch.character_exists("Glut"), True)
check("character_exists(glut)", ch.character_exists("glut"), True)
check("include_dormant", ch.list_available_characters(include_dormant=True),
      ["Glut", "Kim", "Obs", "Tess", "Tilda"])
from app.core import npc_ops  # noqa: E402
check("name_is_taken(glut)", npc_ops.name_is_taken("glut"), True)
try:
    asyncio.run(character_ops.create_character_core(
        Req({"character_name": "Glut", "template": "human-roleplay"})))
    check("create_character_core(Glut)", "created", 409)
except HTTPException as e:
    check("create_character_core(Glut)", e.status_code, 409)
except Exception as e:  # noqa: BLE001 — got past the name check
    check("create_character_core(Glut)", f"past the name check ({type(e).__name__})", 409)
from app.routes import characters as char_routes  # noqa: E402
_rows = {r["name"]: r for r in char_routes._roster_rows()}
check("admin list Glut", _rows.get("Glut", {}).get("status"), "dormant")
check("admin list Tilda", _rows.get("Tilda", {}).get("status"), "")
raw_state("Glut", current_location=INN, current_room="taproom")
from app.core import places  # noqa: E402
check("census ignores dormant", "Glut" in [n for n, _r, _p in places._census(INN, None)], False)
with db.transaction() as _conn:
    _conn.execute("UPDATE characters SET profile_json=json_set(profile_json, '$.journey', "
                  "json('{\"target\": \"x\"}')) WHERE name='Glut'")
edit("Obs", movement_target="somewhere")
check("journeys ignore dormant", [j["name"] for j in ch.list_active_journeys()], ["Obs"])
edit("Obs", movement_target="")
raw_state("Glut", current_location="", current_room="")
with db.transaction() as _conn:
    _conn.execute("UPDATE characters SET profile_json=json_remove(profile_json, '$.journey') "
                  "WHERE name='Glut'")

# ── [I] ─────────────────────────────────────────────────────────────────────
section("[I] the pool never touches a dormant character")
raw_status("Tess", "dormant")
from app.core import npc_pool  # noqa: E402
check("revive_from_pool(dormant)", npc_pool.revive_from_pool("Tess", INN, "taproom"), False)
check("Tess still dormant", ch.get_character_status("Tess"), "dormant")
check("pool_npc(dormant)", npc_pool.pool_npc("Tess"), False)
check("Tess still dormant after pool_npc", ch.get_character_status("Tess"), "dormant")
raw_status("Tess", "")

# ── [J] ─────────────────────────────────────────────────────────────────────
section("[J] unlink")
res = lc.unlink("Glut")
check("unlink Glut ok", (res["ok"], res["error"]), (True, ""))
check("Glut status", ch.get_character_status("Glut"), "")
check("Glut at Tilda's place", (ch.get_character_current_location("Glut"),
                                ch.get_character_current_room("Glut")), (INN, "cellar"))
check("Glut not linked", lc.is_linked("Glut"), False)
check("bodies_of(Tilda)", lc.bodies_of("Tilda"), ["Kim"])
check("Glut keeps the shown gender", (stored_blob("Glut") or {}).get("gender"), "male")
raw_state("Tilda", current_room="")
res = lc.unlink("Kim")
check("unlink Kim ok", (res["ok"], res["error"]), (True, ""))
check("Kim entry room", (ch.get_character_current_location("Kim"),
                         ch.get_character_current_room("Kim")), (INN, "taproom"))
raw_state("Tilda", current_room="cellar")
check("relink Kim", lc.link("Kim", "Tilda")["ok"], True)
ch.set_character_status("Kim", "")
check("unlink present", lc.unlink("Kim")["error"],
      "Kim stands in the world right now — revert first.")

# ── [K] ─────────────────────────────────────────────────────────────────────
section("[K] delete")
check("delete_refusal(Tilda)", lc.delete_refusal("Tilda"),
      "Tilda leads linked characters (Kim) — unlink or delete the linked characters first.")
check("delete_character(Tilda)", ch.delete_character("Tilda"), False)
check("Tilda row kept", stored_blob("Tilda") is not None, True)
ch.set_character_status("Tilda", "dormant")
check("delete_refusal(present Kim)", lc.delete_refusal("Kim"),
      "Kim stands in the world for Tilda right now — revert first.")
check("delete_character(present Kim)", ch.delete_character("Kim"), False)
ch.set_character_status("Tilda", "")
ch.set_character_status("Kim", "dormant")
check("delete dormant Kim", ch.delete_character("Kim"), True)
check("bodies_of(Tilda) after delete", lc.bodies_of("Tilda"), [])

# ── [L] ─────────────────────────────────────────────────────────────────────
section("[L] routes are admin-only")
from app.core.auth_dependency import require_admin  # noqa: E402
_want = {("GET", "/characters/{character_name}/link"), ("PUT", "/characters/{character_name}/link"),
         ("DELETE", "/characters/{character_name}/link"),
         ("POST", "/characters/{character_name}/linked")}
_found = set()
for _r in char_routes.router.routes:
    for _m in getattr(_r, "methods", ()) or ():
        if (_m, _r.path) in _want:
            _deps = [d.call for d in _r.dependant.dependencies]
            if require_admin in _deps:
                _found.add((_m, _r.path))
check("admin routes", sorted(_found), sorted(_want))

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
