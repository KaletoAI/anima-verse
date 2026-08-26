#!/usr/bin/env python3
"""Smoke run for the temporary-NPC default skill set + the TakePhoto
redirection (plan-npc-leben, task 3).

Throwaway storage, throwaway world DB — no server, no real world is touched.
The image service is replaced by a counting stub: this run must prove that a
photo is NOT generated in the refusal case, and "not generated" is only
provable when nothing can generate.

THE RULES, by hand — from the task brief:

  A) A new temporary NPC gets the standard skill set. The set is TEMPLATE
     DATA (`default_skills` in shared/templates/character/npc-temporary.json),
     read from the same template the NPC is applied with, and it is exactly
     the set the user read off the hand-configured NPC:

       allow_exposed, cancel_travel, consume_item, dry_off, end_intimate,
       enter_water, image_generation, instagram_comment, instagram_reply,
       interact, invite_to_party, join_party, leave_party, require_decency,
       set_pose, start_intimate, talk_to

     THE LIST IS CLOSED, and that follows from the manager's own resolution
     rule (`app/skills/skill_manager.py:173-179`), which decides a verb like
     this:

         config with an "enabled" key -> that key decides
         no config, ALWAYS_LOAD       -> OFF
         no config, ordinary skill    -> ON

     So enabling the list alone would leave every unlisted ordinary verb
     switched on — searx among them, which the brief calls out as
     deliberately off. `apply_npc` therefore writes `enabled: true` for every
     listed id the manager knows, `enabled: false` for every OTHER ordinary
     id it knows, and NOTHING for `ALWAYS_LOAD` ids (they are off already and
     have their own lifecycles). An id nobody installed is skipped silently:
     the list is written for a full installation, and packages that ship in a
     separate repo must not break an NPC spawn. Hand-derived expectations:

       [1] The template carries exactly those 17 ids, in that order.
       [2] After `apply_npc` every id of the list that the running skill
           manager knows has `{"enabled": true}` in the NPC's skill config.
           Which half of the list is installed depends on the installation,
           so the expectation is the INTERSECTION with
           `get_skill_manager().skills`, computed here — plus the ids this
           repo itself ships, which must always be on.
       [2b] Measured at the CONSUMER: `_get_agent_skills` — the routine that
           actually decides which verbs an NPC is offered — returns NOTHING
           outside the list. `searx` in particular is absent AND carries
           `{"enabled": false}`, and so does every other ordinary id the
           manager knows that the list does not name. (The searx package
           needs a configured instance and does not load in a throwaway
           world, so a stand-in of the same shape is registered with the
           manager — the rule under test is the manager's, not the
           package's.) What the list DOES name is offered, minus what a skill
           hides from itself: `leave_party` (a character in no party cannot
           leave one) and `interact` (no pair clips in this throwaway clip
           library) — skill logic, not activation.
       [3] Sleep is not planned for temporary NPCs, and it is off for the
           REAL reason: `sleep`/`wakeup` are `ALWAYS_LOAD`
           (`plugins/sleep/plugin.yaml:10,14`), so a missing config means off
           — which is why the activation must not write one for them. Both
           are installed here, neither is in the list, neither has a config
           file, and neither is offered to the NPC.
       [4] An id nobody installed is skipped SILENTLY: the call returns the
           ids it really enabled, raises nothing, and writes no config for
           the unknown one. Run against a shorter list on its own NPC, it
           also shows both directions at once — the named verb stays on, an
           ordinary verb the list drops is written off.

  B) A temporary NPC's photo belongs to the AVATAR it is talking to.

       [5] No avatar in the NPC's room -> the skill returns a short
           in-character refusal and the image service is NOT called (0 calls).
           Same when an avatar exists but stands in another room, and same
           when the NPC stands nowhere at all.
       [6] An avatar in the same room -> the service IS called, exactly once,
           and the payload carries `gallery_character` = that avatar while
           `agent_name` STAYS THE NPC. That split is the whole point: the
           gallery is the avatar's, the prompt slots (appearance, outfit,
           location, reference images) are the photographer's, and the prompt
           text is passed through untouched.
       [7] An ordinary character is untouched by all of this: no
           `gallery_character` in the payload, service called normally.
       [8] The service really READS the field, checked at the consumer and not
           at the sender: `_parse_input` carries `gallery_character` through,
           and `_resolve_gallery_character` — the one routine that decides
           whose gallery a render lands in — returns the named owner. A name
           nobody in the cast carries is ignored (no ghost gallery), and a
           profile render stays with its agent whatever the field says.

  C) A temporary NPC has no RP values.

       [9] `apply_hourly_status_tick` is gated on `status_effects_enabled`,
           which npc-temporary switches off — the tick is a no-op for the NPC
           and still runs for an ordinary character.
      [10] `sleep_world` skips temporary NPCs (they have no sleep verbs to
           wake them again), puts ordinary NPCs to sleep and leaves the
           avatar alone as before.

Usage:  ./.venv/bin/python scripts/smoke_npc_skills.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcskills-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcskills-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import npc_ops  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.users import create_user, update_user  # noqa: E402
from app.core.world_ops import sleep_world, wake_world  # noqa: E402
from app.imagegen import service as imagegen_service  # noqa: E402
from app.models import character_template, world  # noqa: E402
from app.models.character import (get_character_skill_config,  # noqa: E402
                                  is_character_sleeping,
                                  save_character_current_location,
                                  save_character_current_room,
                                  save_character_profile)

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


# ── world + cast ────────────────────────────────────────────────────────────

LOC = world.add_location("Harbour Inn", "Tar and salt.",
                         rooms=[{"name": "Taproom", "description": "Benches."},
                                {"name": "Cellar", "description": "Barrels."}])
LOC_ID = LOC["id"]
TAPROOM = world.get_location_by_id(LOC_ID)["rooms"][0]["id"]
CELLAR = world.get_location_by_id(LOC_ID)["rooms"][1]["id"]

# The gate of task 1 stays out of the way here — this run is about skills, and
# a held-back NPC would only make the placement noise.
_cfg = config.get_all()
_cfg.setdefault("npc", {})["require_assets"] = False
config.save(_cfg, STORAGE / "config.json")


def make_npc(name: str, *, location_id: str = LOC_ID,
             room_id: str = TAPROOM) -> str:
    """A temporary NPC through the real apply path."""
    apply_npc({"character_name": name,
               "character_appearance": "a wiry deckhand",
               "face_appearance": "a narrow face, salt-bleached brows",
               "standing_task": "coiling rope",
               "outfit_description": "a patched oilskin"},
              location_id, room_id, template="npc-temporary",
              created_by="smoke_npc_skills")
    return name


def make_plain_character(name: str, *, location_id: str = "",
                         room_id: str = "") -> str:
    """An ordinary character — not a temporary NPC. `human-roleplay` is the
    full template: it has the RP layer (`status_effects_enabled`) that section
    [9] compares the NPC against."""
    save_character_profile(name, {"character_name": name,
                                  "template": "human-roleplay"},
                           create_new=True)
    if location_id:
        save_character_current_location(name, location_id)
        if room_id:
            save_character_current_room(name, room_id)
    return name


def make_avatar(name: str, username: str) -> str:
    """Give a character a human driver — that is what makes it an avatar."""
    uid = create_user(username, "smoke-password", allowed_characters=[name])
    update_user(uid, settings={"active_character": name})
    return name


SKILL_MANAGER = get_skill_manager()


class FakeSearxSkill:
    """Stands in for the searx package — an ORDINARY (non-ALWAYS_LOAD) verb
    the standard set does not name, which is the case the closed list exists
    for. The real package needs a configured instance and is therefore not
    loaded in a throwaway world; the rule it demonstrates belongs to the
    manager, not to the package, so a stand-in proves it just as well."""

    SKILL_ID = "searx"
    ALWAYS_LOAD = False
    name = "Searx"

    def visible_for(self, character_name: str) -> bool:
        return True


SKILL_MANAGER.skills.append(FakeSearxSkill())

KNOWN_SKILL_IDS = {getattr(s, "SKILL_ID", "") for s in SKILL_MANAGER.skills}
# The manager's own two classes of verb (skill_manager.py:173-179): an
# ALWAYS_LOAD skill without a per-character config is OFF, an ordinary one is
# ON. Only the second class has to be written off explicitly.
ALWAYS_LOAD_IDS = {getattr(s, "SKILL_ID", "") for s in SKILL_MANAGER.skills
                   if getattr(s, "ALWAYS_LOAD", False)}
ORDINARY_IDS = KNOWN_SKILL_IDS - ALWAYS_LOAD_IDS


def offered_ids(name):
    """The verbs the NPC is actually offered — asked at the consumer."""
    return sorted(getattr(s, "SKILL_ID", "") for s in
                  SKILL_MANAGER._get_agent_skills(name, check_limits=False))

# The set the user read off the hand-configured NPC (task brief).
EXPECTED_SET = ["allow_exposed", "cancel_travel", "consume_item", "dry_off",
                "end_intimate", "enter_water", "image_generation",
                "instagram_comment", "instagram_reply", "interact",
                "invite_to_party", "join_party", "leave_party",
                "require_decency", "set_pose", "start_intimate", "talk_to"]

# The subset THIS repo ships itself — always installed, so always on.
IN_REPO_SET = ["allow_exposed", "cancel_travel", "consume_item", "dry_off",
               "enter_water", "image_generation", "instagram_comment",
               "instagram_reply", "interact", "invite_to_party", "join_party",
               "leave_party", "require_decency", "set_pose", "talk_to"]


# ── [1] the set is template data ────────────────────────────────────────────
print("[1] the standard set lives in the template")
_TMPL = character_template.get_template("npc-temporary") or {}
check("npc-temporary carries the brief's 17 ids",
      _TMPL.get("default_skills"), EXPECTED_SET)

# ── [2] apply_npc switches on what is installed ─────────────────────────────
print("[2] apply_npc enables every installed id of the list")
NPC = make_npc("Sivert")


def enabled_ids(name):
    return sorted(sid for sid in EXPECTED_SET
                  if get_character_skill_config(name, sid).get("enabled") is True)


check("exactly the installed half of the list is on",
      enabled_ids(NPC), sorted(sid for sid in EXPECTED_SET
                               if sid in KNOWN_SKILL_IDS))
check("and that half covers everything this repo ships",
      [sid for sid in IN_REPO_SET if sid not in enabled_ids(NPC)], [])

# ── [2b] the list is CLOSED — measured at the consumer ──────────────────────
print("[2b] nothing outside the list is offered to the NPC")
check("the manager offers no verb the list does not name",
      [sid for sid in offered_ids(NPC) if sid not in EXPECTED_SET], [])
check("searx is installed, unlisted, and therefore NOT offered",
      ("searx" in KNOWN_SKILL_IDS, "searx" in offered_ids(NPC)), (True, False))
check("and its config says so in writing",
      get_character_skill_config(NPC, "searx"), {"enabled": False})
check("every other unlisted ordinary verb is written off too",
      sorted(sid for sid in ORDINARY_IDS if sid not in EXPECTED_SET
             and get_character_skill_config(NPC, sid) != {"enabled": False}),
      [])
check("what the list DOES name is offered, minus what a skill hides itself "
      "(leave_party: nobody in no party can leave one; interact: no pair "
      "clips in this throwaway clip library)",
      sorted(sid for sid in EXPECTED_SET
             if sid in KNOWN_SKILL_IDS and sid not in offered_ids(NPC)),
      ["interact", "leave_party"])

# ── [3] sleep is not planned for temporary NPCs ─────────────────────────────
print("[3] the sleep verbs stay off — because they are ALWAYS_LOAD")
check("sleep + wakeup ARE installed here", sorted(
    sid for sid in ("sleep", "wakeup") if sid in KNOWN_SKILL_IDS),
    ["sleep", "wakeup"])
check("both are ALWAYS_LOAD — a missing config means OFF for them",
      sorted(sid for sid in ("sleep", "wakeup") if sid in ALWAYS_LOAD_IDS),
      ["sleep", "wakeup"])
check("so the activation writes no config for either",
      [sid for sid in ("sleep", "wakeup")
       if get_character_skill_config(NPC, sid)], [])
check("and neither is offered to the NPC",
      [sid for sid in ("sleep", "wakeup") if sid in offered_ids(NPC)], [])
check("no UNLISTED ALWAYS_LOAD verb got a config file at all — they are off "
      "by default and keep their own lifecycles",
      sorted(sid for sid in ALWAYS_LOAD_IDS if sid not in EXPECTED_SET
             and get_character_skill_config(NPC, sid)), [])

# ── [4] an unknown id is skipped silently ───────────────────────────────────
# On its own NPC: the fake one-verb list would switch off everything else,
# which is exactly right and would only wreck the NPC the later sections use.
print("[4] an id nobody installed is skipped without a word")
LONER = make_npc("Eirik")
_real_get_template = character_template.get_template
try:
    character_template.get_template = lambda name=None: {
        "features": {"temporary_npc": True},
        "default_skills": ["talk_to", "no_such_skill_at_all"]}
    _activated = npc_ops.activate_default_skills(LONER, "npc-temporary")
finally:
    character_template.get_template = _real_get_template
check("only the known id is reported as activated", _activated, ["talk_to"])
check("and the unknown one has no config",
      get_character_skill_config(LONER, "no_such_skill_at_all"), {})
check("an ordinary verb the new list does not name is switched off",
      get_character_skill_config(LONER, "image_generation"),
      {"enabled": False})
check("while the one it does name stays on",
      get_character_skill_config(LONER, "talk_to"), {"enabled": True})


# ── the image-service stub ──────────────────────────────────────────────────

class FakeImageService:
    """Counts calls and keeps the payloads. Generates nothing."""

    enabled = True

    def __init__(self):
        self.calls = []

    def generate_from_input(self, raw_input: str) -> str:
        self.calls.append(json.loads(raw_input))
        return "![Generated Image 1](/characters/x/images/y.png)"


SERVICE = FakeImageService()
imagegen_service.get_image_service = lambda: SERVICE

TAKE_PHOTO = next(s for s in get_skill_manager().skills
                  if getattr(s, "SKILL_ID", "") == "image_generation")


def shoot(character_name: str, prompt: str = "the harbour at dusk") -> str:
    """One tool call, shaped the way the chat engine shapes them."""
    return TAKE_PHOTO.execute(json.dumps(
        {"input": prompt, "agent_name": character_name, "user_id": ""}))


# ── [5] no avatar in the room -> no photo ───────────────────────────────────
print("[5] without an avatar in the room the NPC does not shoot")
SERVICE.calls.clear()
_res = shoot(NPC)
check("the service was not called", len(SERVICE.calls), 0)
check("and the answer is a short in-character refusal",
      (_res.startswith(NPC), len(_res) < 200, "camera" in _res.lower()),
      (True, True, True))

AVATAR = make_avatar(make_plain_character("Runa", location_id=LOC_ID,
                                          room_id=CELLAR), "smoke-user")
SERVICE.calls.clear()
shoot(NPC)
check("an avatar in ANOTHER room is not a partner either",
      len(SERVICE.calls), 0)

NOWHERE = make_npc("Alvid", location_id="", room_id="")
SERVICE.calls.clear()
shoot(NOWHERE)
check("an NPC standing nowhere shoots nothing", len(SERVICE.calls), 0)

# ── [6] the avatar in the room owns the picture ─────────────────────────────
print("[6] the photo lands in the avatar's gallery, the prompt stays the NPC's")
save_character_current_room(AVATAR, TAPROOM)
SERVICE.calls.clear()
shoot(NPC)
check("the service was called exactly once", len(SERVICE.calls), 1)
check("gallery = avatar, prompt slots = NPC, prompt text untouched",
      {k: SERVICE.calls[0].get(k) for k in
       ("gallery_character", "agent_name", "input")},
      {"gallery_character": AVATAR, "agent_name": NPC,
       "input": "the harbour at dusk"})

# ── [7] an ordinary character is untouched ──────────────────────────────────
print("[7] an ordinary character keeps its own gallery")
PLAIN = make_plain_character("Halvard", location_id=LOC_ID, room_id=TAPROOM)
SERVICE.calls.clear()
shoot(PLAIN)
check("called, and with no gallery redirect",
      (len(SERVICE.calls), SERVICE.calls[0].get("gallery_character")),
      (1, None))

# ── [8] the service reads the field ─────────────────────────────────────────
print("[8] the ImageService carries gallery_character into the generation")
_svc = imagegen_service.ImageService.__new__(imagegen_service.ImageService)
_parsed = imagegen_service.ImageService._parse_input(
    _svc, json.dumps({"input": "x", "agent_name": NPC,
                      "gallery_character": AVATAR}))
check("_parse_input keeps it", _parsed.get("gallery_character"), AVATAR)
check("and the routing hands the picture to the named owner",
      _svc._resolve_gallery_character(NPC, "the harbour at dusk", "",
                                      {"gallery_character": AVATAR}), AVATAR)
check("a name nobody carries is ignored — no ghost gallery",
      _svc._resolve_gallery_character(NPC, "x", "",
                                      {"gallery_character": "Nobody"}), NPC)
check("a profile render stays with its agent, named or not",
      _svc._resolve_gallery_character(NPC, "x", "",
                                      {"gallery_character": AVATAR},
                                      set_profile=True), NPC)
check("and without a name the creator keeps it",
      _svc._resolve_gallery_character(NPC, "x", "", {}), NPC)

# ── [9] no hourly stat tick for a temporary NPC ─────────────────────────────
print("[9] the hourly stat tick does not reach a temporary NPC")
check("status_effects_enabled is off for the NPC",
      character_template.is_feature_enabled(NPC, "status_effects_enabled"),
      False)
check("and on for an ordinary character",
      character_template.is_feature_enabled(PLAIN, "status_effects_enabled"),
      True)

# ── [10] world sleep skips temporary NPCs ───────────────────────────────────
print("[10] world sleep leaves temporary NPCs awake")
_slept = sleep_world()["slept"]
check("the temporary NPCs stayed awake",
      sorted(n for n in (NPC, NOWHERE) if n in _slept), [])
check("and are really not sleeping",
      [n for n in (NPC, NOWHERE) if is_character_sleeping(n)], [])
check("the ordinary character did fall asleep", PLAIN in _slept, True)
check("the avatar is untouched, as before", AVATAR in _slept, False)
wake_world()

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
