#!/usr/bin/env python3
"""Smoke run for the hearing radius in the wilderness (Seamless World, E6 Task 1).

Runs against a THROWAWAY storage directory — never touches a real world.

The wilderness is a room without walls: a location-less speaker is heard by
every other location-less character within ``game.hearing_radius_m`` metres.
Location speakers are unaffected — walls still stop everything.

The inn sits INSIDE the hearing radius of the wilderness characters on purpose.
A far-away location would let a wall case pass on distance alone: "D hears
nothing" would also hold if speech leaked into locations, and "the wilderness
hears nothing from D" would also hold if the location branch wrongly computed
`nearby`. Only a neighbouring inn separates walls from metres.

Seed (all distances hand-derived, radius default 20 m):
  npc_a  wilderness at (0, 0)
  npc_b  wilderness at (15, 0)   — hypot(15, 0) = 15  <= 20  → in A's earshot
  npc_c  wilderness at (30, 0)   — hypot(30, 0) = 30  >  20  → out of A's earshot
                                   (but 15 m from B, so B's whisper case below
                                   is the one that proves whisper has no
                                   bystander line in the open)
  npc_e  wilderness at (0, 17)   — hypot(0, 17) = 17  <= 20  → in A's earshot,
                                   and only 5 m from the inn
  npc_d  INSIDE "Smoke Inn", centre (0, 12), footprint side 6 → the square
         x ∈ [-3, 3], z ∈ [9, 15]. None of the four wilderness points falls
         inside it (a: z=0, b: x=15, c: x=30, e: z=17), which case [0]
         asserts rather than assumes.

Wall distances, all WITHIN the 20 m radius — so every wall check below fails
if the walls stop mattering:
  npc_d (0,12) ↔ npc_e (0,17)  = 5
  npc_d (0,12) ↔ npc_a (0,0)   = 12
  npc_d (0,12) ↔ npc_b (15,0)  = hypot(15, 12) = 19.21
  npc_d (0,12) ↔ npc_c (30,0)  = hypot(30, 12) = 32.31  (outside anyway)

[1] A speaks normal → A `spoken_self`; B (15) and E (17) `nearby`; C nothing
    (30 > 20); D nothing although it stands 12 m away — the walls, not the
    distance, keep it out.
[2] B whispers at A (addressee A): hypot(15, 0) = 15 <= 20 → A gets the
    CONTENT with kind `nearby`. C is 15 m from B and therefore inside B's
    radius, yet gets NOTHING: in the open a whisper reaches its addressee
    only — there is no `whisper_meta` bystander line without a room to
    carry it. E is hypot(15, 17) = 22.67 > 20 away and out regardless.
    So the utterance has exactly 2 perceptions.
[3] The utterance row of [1] carries pos_x = 0.0, pos_z = 0.0 and
    location_id = "" — the wilderness encoding is the empty location plus
    the two position columns.
[4] D speaks in its location → E (5 m), A (12 m) and B (19.21 m) are all
    inside the hearing radius and STILL get nothing; the utterance has
    exactly one perception (D itself) and its row has pos_x/pos_z NULL —
    rooms keep writing NULL.
[5] game.hearing_radius_m = 10 → B (15) and E (17) fall out of A's earshot;
    only A itself perceives.
[6] Garbage setting (-5) → the default 20.0 and EXACTLY one warning, however
    often the getter is called. Plus the clamp table:
      unset → 20.0 | 40 → 40.0 | 0.5 → 1.0 | 1000 → 500.0
      0 / -5 / "loud" / True / NaN / None → 20.0
[7] The bulk read shares the roster rule of the room path: a positioned
    system row (leading underscore) and a positioned reserved name are both
    invisible to the wilderness earshot.

E6 Task 2 — the context/prompt/reaction guards downstream of the core.
Cases [8]-[14] continue on the same seed (the brief numbers them [7]-[10];
[7] was already taken by the Task-1 hardening round, so they shift by one):

[8] The wilderness stream is "what I heard out there", NOT a room bucket:
    B's stream carries both [1] (heard) and [2] (its own whisper) = 2 rows,
    C's is empty, A's has all three of its lines. D's WILDERNESS stream is
    empty although D perceived "in the inn" — that line is located, so it
    belongs to the room stream, which still returns it.
[9] B walks to (100, 0) — hypot(100, 0) = 100 > 20 — and its stream KEEPS
    the two old rows: perception was decided when the words were spoken.
    A new line from A does NOT reach B any more (so [9] is not vacuous).
[10] dispatch_room_reactions in the open. After [9] the neighbours of A
    (0,0) are: E (0,17) → 17 <= 20 in; C (30,0) → 30 out; B (100,0) → out;
    D behind walls. So addressing E yields obligatory=[E], nobody else is
    queued; without an addressee E gets the chime. C as speaker (nearest
    other: A at 30, E at hypot(30,17) = 34.48, B at 70) bumps NOBODY.
    No LLM runs: dispatch only queues into the respond lane and returns.
[11] TalkTo in the open: A → E (17 m) goes through, A → C (30 m) is
    refused for distance, A → D (12 m, inside the inn) is refused because
    D is not out here at all.
[12] No wilderness scene bucket: after all the open-air talk there is not
    ONE scene row with an empty location_id, while D's line inside the inn
    did open its scene (exactly 1 row) — the skip is a wilderness rule, not
    a broken scene manager.
[13] Prompt presence in the open: A sees E as present (alone_here False),
    C is alone and KNOWS it (alone_here True), and a character without a
    point gets the honest "unknown" ("", "", False). The place name is the
    wilderness label, not "Unknown".
[15] OFF-MAP is a third state, not "outdoors". A character with no location
    AND no point (auto-sleep, a reaped avatar — both awake and chattable)
    must get NEITHER the wilderness label NOR "you are alone out here":
    its prompt says "Unknown" and stays silent about presence, exactly as
    before E6. The thought path already gates on alone_here; the system
    prompt is checked here to be symmetric with it.
[16] The outdoor chime budget is per CELL, not global. Cell edge =
    max(50, radius) = 50 m, so floor(x/50):floor(z/50):
      A (0,0) and E (0,17)   -> open:0:0   — one conversation, one budget
      B (100,0) and G (110,0) -> open:2:0  — a different budget entirely
    Exhausting A's cell must swallow A's dispatch (winddown once, then
    nothing at all — obligatory answers included) while B/G, 100 m away,
    still get their mandatory answer. With the old single key "/" the
    second group would have been silenced with the first.

[14] announce_action no longer returns early outside: the narrator line is
    recorded location-less, the radius neighbour is queued for a reaction —
    and the line ARRIVES. The storyteller has no point of its own, so it
    borrows the ACTING character's (E7/D1): npc_a at (0, 0) → the row
    carries that point and A itself plus E (17 m) perceive it, while C
    (30 m), B (100 m after [9]) and the walled-in D do not. Two red
    counter-probes: the same line WITHOUT an anchor still reaches nobody
    (the old behaviour, and proof the fan-out did not simply stop caring
    about positions out here), and an anchor never moves a speaker that has
    a point of its own (C anchored on A stays at (30, 0), out of A's ear).

[17] The wilderness prune (E7/D2). A located line ends with its scene; a
    location-less one has no scene, so AGE is its only exit —
    ``WILDERNESS_RETENTION_DAYS`` = 7 days, cutoff = now − 7 d, and the
    comparison is strict (``ts < cutoff``). Four rows placed by hand around
    that edge: 8 days out and one minute past it fall (perceptions
    included), one minute short of it survives, and an equally 8-day-old
    line INSIDE the inn is untouched — the prune is a wilderness rule, not a
    global sweep. It rides on ``run_idle_consolidation`` and must run even
    when no scene is idle at all (the scene query is stubbed empty here, so
    no LLM is involved), and a second sweep drops nothing.

Usage:  ./.venv/bin/python scripts/smoke_earshot.py
"""
import json
import logging
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="earshot-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="earshot-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
db.init_schema()

from app.core import perception  # noqa: E402
from app.core.agent_loop import AgentLoop  # noqa: E402
from app.core import agent_loop as _agent_loop_mod  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.perception import (  # noqa: E402
    KIND_NEARBY, KIND_SPOKEN_SELF, STORYTELLER_SPEAKER, UNKNOWN_LOCATION_LABEL,
    VOLUME_NORMAL, VOLUME_WHISPER, WILDERNESS_LOCATION_LABEL, announce_action,
    get_hearing_radius_m, prompt_place, record_utterance)
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.system_prompt_builder import (  # noqa: E402
    PRESENCE, _load_presence, load_prompt_data)
from app.core.thought_context import _build_presence  # noqa: E402
from app.models import perception_store  # noqa: E402
from app.models.character import (  # noqa: E402
    _write_character_pos, get_character_current_location,
    get_character_current_room, get_character_pos, list_wilderness_positions,
    save_character_current_location, save_character_profile, set_character_pos)
from app.plugins.context import PluginContext  # noqa: E402
from plugins.talk_to.skill import TalkToSkill  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def stream(name):
    """(kind, content) pairs of a character's subjective perception stream."""
    return [(r["kind"], r["content"])
            for r in perception_store.get_character_stream(name, limit=50)]


def open_stream(name, room="ignored-room"):
    """(kind, content) pairs of the WILDERNESS stream — the location-less
    lines the character perceived. A deliberately bogus room is passed in:
    out there rooms do not exist, so the room argument must not filter."""
    return [(r["kind"], r["content"])
            for r in perception_store.get_character_room_stream(name, "", room, 50)]


def _set_agent_loop(loop):
    """Pin the AgentLoop singleton so a smoke can read what got queued."""
    _agent_loop_mod._agent_loop = loop


def set_plan_width(location_id: str, width: float) -> None:
    """DRAW the location's boundary as the centred square of edge ``width``
    (contract v6) and store the width the sanitizer derives from its bounding
    box. Since 2026-08-19 the width alone is no shape: without a drawn outline
    a location has no area anywhere. The square's corners are the ones the
    deleted synthesis produced, so every hand-derived number stays put."""
    half = round(float(width) / 2.0, 2)
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            map3d["boundary"] = [[-half, -half], [half, -half],
                                 [half, half], [-half, half]]
            loc["map3d"] = map3d
    _save_world_data(data)


def utterance_row(uid):
    row = get_connection().execute(
        "SELECT location_id, room_id, pos_x, pos_z FROM utterances WHERE id=?",
        (uid,)).fetchone()
    return dict(row) if row else None


def perceptions_of(uid):
    rows = get_connection().execute(
        "SELECT perceiver, kind, content FROM perceptions WHERE utterance_id=? "
        "ORDER BY perceiver", (uid,)).fetchall()
    return [(r["perceiver"], r["kind"], r["content"]) for r in rows]


# ── Seed ────────────────────────────────────────────────────────────────
inn = add_location(name="Smoke Inn", description="earshot smoke")
INN_ID = inn["id"]
# Right next door, not far away: the wall cases have to run at a distance the
# radius would otherwise bridge (see the docstring).
update_location_position(INN_ID, 0.0, 12.0)
set_plan_width(INN_ID, 6.0)

for name in ("npc_a", "npc_b", "npc_c", "npc_d", "npc_e"):
    save_character_profile(name, {"current_location": ""}, create_new=True)

set_character_pos("npc_a", 0, 0)
set_character_pos("npc_b", 15, 0)
set_character_pos("npc_c", 30, 0)
set_character_pos("npc_e", 0, 17)
save_character_current_location("npc_d", INN_ID)

print("[0] seed")
check("npc_a pos", get_character_pos("npc_a"), {"x": 0.0, "z": 0.0})
check("npc_b pos", get_character_pos("npc_b"), {"x": 15.0, "z": 0.0})
check("npc_c pos", get_character_pos("npc_c"), {"x": 30.0, "z": 0.0})
check("npc_e pos", get_character_pos("npc_e"), {"x": 0.0, "z": 17.0})
check("npc_a is location-less", get_character_current_location("npc_a"), "")
check("npc_b is location-less", get_character_current_location("npc_b"), "")
check("npc_c is location-less", get_character_current_location("npc_c"), "")
check("npc_e is location-less next to the inn",
      get_character_current_location("npc_e"), "")
check("npc_d sits in the inn", get_character_current_location("npc_d"), INN_ID)
check("npc_d stands on the inn centre",
      get_character_pos("npc_d"), {"x": 0.0, "z": 12.0})
check("default hearing radius", get_hearing_radius_m(), 20.0)
check("bulk read lists only the location-less with a point",
      sorted((w["name"], w["x"], w["z"]) for w in list_wilderness_positions()),
      [("npc_a", 0.0, 0.0), ("npc_b", 15.0, 0.0), ("npc_c", 30.0, 0.0),
       ("npc_e", 0.0, 17.0)])
check("everyone outside is within the radius of npc_d",
      sorted(n for n in ("npc_a", "npc_b", "npc_e")
             if math.dist((0.0, 12.0), (get_character_pos(n)["x"],
                                        get_character_pos(n)["z"])) <= 20.0),
      ["npc_a", "npc_b", "npc_e"])

# ── [1] normal speech carries to everyone inside the radius ─────────────
print("[1] A speaks normally — B (15 m) and E (17 m) hear it, C (30 m) does not,"
      "\n    and D at 12 m is kept out by the walls, not by the distance")
uid1 = record_utterance(speaker="npc_a", content="hello wilderness",
                        volume=VOLUME_NORMAL)
check("utterance written", uid1 is not None, True)
check("A hears itself", stream("npc_a"),
      [(KIND_SPOKEN_SELF, "hello wilderness")])
check("B is nearby and gets the content", stream("npc_b"),
      [(KIND_NEARBY, "hello wilderness")])
check("E is nearby and gets the content", stream("npc_e"),
      [(KIND_NEARBY, "hello wilderness")])
check("C is out of earshot", stream("npc_c"), [])
check("D behind walls hears nothing at 12 m", stream("npc_d"), [])
check("the open speech reached exactly A, B and E", perceptions_of(uid1),
      [("npc_a", KIND_SPOKEN_SELF, "hello wilderness"),
       ("npc_b", KIND_NEARBY, "hello wilderness"),
       ("npc_e", KIND_NEARBY, "hello wilderness")])

# ── [2] a whisper in the open reaches its addressee only ────────────────
print("[2] B whispers at A — C is 15 m away and still gets nothing")
uid2 = record_utterance(speaker="npc_b", content="psst",
                        volume=VOLUME_WHISPER, addressees=["npc_a"])
check("A gets the whispered content", stream("npc_a")[-1],
      (KIND_NEARBY, "psst"))
check("B hears itself", stream("npc_b")[-1], (KIND_SPOKEN_SELF, "psst"))
check("C still has an empty stream", stream("npc_c"), [])
check("no bystander line in the open", perceptions_of(uid2),
      [("npc_a", KIND_NEARBY, "psst"), ("npc_b", KIND_SPOKEN_SELF, "psst")])

# ── [3] the utterance row carries the speaker's point ───────────────────
print("[3] the wilderness utterance row is empty location + position")
check("row of [1]", utterance_row(uid1),
      {"location_id": "", "room_id": "", "pos_x": 0.0, "pos_z": 0.0})
check("row of [2]", utterance_row(uid2),
      {"location_id": "", "room_id": "", "pos_x": 15.0, "pos_z": 0.0})

# ── [4] walls still stop everything ─────────────────────────────────────
print("[4] a location speaker is not heard outside — E at 5 m, A at 12 m and"
      "\n    B at 19.21 m are all inside the radius and still hear nothing")
before = {n: len(stream(n)) for n in ("npc_a", "npc_b", "npc_c", "npc_e")}
uid4 = record_utterance(speaker="npc_d", content="in the inn",
                        volume=VOLUME_NORMAL)
check("D hears itself", stream("npc_d")[-1], (KIND_SPOKEN_SELF, "in the inn"))
check("E unchanged at 5 m", len(stream("npc_e")), before["npc_e"])
check("A unchanged at 12 m", len(stream("npc_a")), before["npc_a"])
check("B unchanged at 19.21 m", len(stream("npc_b")), before["npc_b"])
check("C unchanged", len(stream("npc_c")), before["npc_c"])
check("the location branch computed no nearby at all", perceptions_of(uid4),
      [("npc_d", KIND_SPOKEN_SELF, "in the inn")])
row4 = utterance_row(uid4)
check("location row keeps NULL position",
      (row4["pos_x"], row4["pos_z"]), (None, None))
check("location row carries the location", row4["location_id"], INN_ID)

# ── [5] the setting really is the radius ────────────────────────────────
print("[5] radius 10 — B at 15 m and E at 17 m drop out")
config._CONFIG.setdefault("game", {})["hearing_radius_m"] = 10
check("getter reads the override", get_hearing_radius_m(), 10.0)
b_before = len(stream("npc_b"))
e_before = len(stream("npc_e"))
uid5 = record_utterance(speaker="npc_a", content="quiet call",
                        volume=VOLUME_NORMAL)
check("A still hears itself", stream("npc_a")[-1],
      (KIND_SPOKEN_SELF, "quiet call"))
check("B no longer in earshot", len(stream("npc_b")), b_before)
check("E no longer in earshot", len(stream("npc_e")), e_before)
check("only the speaker perceives it", perceptions_of(uid5),
      [("npc_a", KIND_SPOKEN_SELF, "quiet call")])
config._CONFIG["game"].pop("hearing_radius_m", None)

# ── [6] the setting's boundaries ────────────────────────────────────────
print("[6] default, clamps, garbage — and exactly ONE warning")
check("the schema offers the hearing radius",
      "hearing_radius_m" in SECTIONS["game"]["fields"], True)
check("the schema offers the discovery range",
      "discovery_range_m" in SECTIONS["game"]["fields"], True)
check("unset → default", get_hearing_radius_m(), 20.0)
for raw, expected in ((40, 40.0), (0.5, 1.0), (1000, 500.0), (0, 20.0),
                      (-5, 20.0), ("loud", 20.0), (True, 20.0),
                      (float("nan"), 20.0), (None, 20.0)):
    config._CONFIG["game"]["hearing_radius_m"] = raw
    check(f"{raw!r} → {expected}", get_hearing_radius_m(), expected)

perception._radius_warned = False
records = []


class _Capture(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            records.append(record.getMessage())


handler = _Capture()
perception.logger.addHandler(handler)
config._CONFIG["game"]["hearing_radius_m"] = -5
for _ in range(3):
    check("garbage → default", get_hearing_radius_m(), 20.0)
perception.logger.removeHandler(handler)
check("warned exactly once", len(records), 1)
config._CONFIG["game"].pop("hearing_radius_m", None)

# ── [7] one roster rule for both presence paths ─────────────────────────
print("[7] system rows with a stray position stay out of the earshot list")
_write_character_pos("_system_probe", 1.0, 1.0)
_write_character_pos("system", 2.0, 2.0)
listed = sorted(w["name"] for w in list_wilderness_positions())
check("underscore row filtered", "_system_probe" in listed, False)
check("reserved name filtered", "system" in listed, False)
check("the real characters are all still there", listed,
      ["npc_a", "npc_b", "npc_c", "npc_e"])

# ── [8] the wilderness stream is what I heard, not a room ───────────────
print("[8] the location-less stream returns the heard wilderness lines")
D_ROOM = get_character_current_room("npc_d")
check("B heard [1] and spoke [2]", open_stream("npc_b"),
      [(KIND_NEARBY, "hello wilderness"), (KIND_SPOKEN_SELF, "psst")])
check("C heard nothing out there", open_stream("npc_c"), [])
check("A has all three of its own/heard lines", open_stream("npc_a"),
      [(KIND_SPOKEN_SELF, "hello wilderness"), (KIND_NEARBY, "psst"),
       (KIND_SPOKEN_SELF, "quiet call")])
check("D's wilderness stream is empty — its line is located", open_stream("npc_d"), [])
check("D's ROOM stream still returns it (location mode untouched)",
      [(r["kind"], r["content"]) for r in
       perception_store.get_character_room_stream("npc_d", INN_ID, D_ROOM, 50)],
      [(KIND_SPOKEN_SELF, "in the inn")])

# ── [9] walking away does not un-hear ───────────────────────────────────
print("[9] B walks 100 m away — what it heard stays heard")
set_character_pos("npc_b", 100, 0)
check("B is far out now", get_character_pos("npc_b"), {"x": 100.0, "z": 0.0})
check("B keeps its two rows", open_stream("npc_b"),
      [(KIND_NEARBY, "hello wilderness"), (KIND_SPOKEN_SELF, "psst")])
uid9 = record_utterance(speaker="npc_a", content="still there?",
                        volume=VOLUME_NORMAL)
check("but a NEW line no longer reaches B", open_stream("npc_b"),
      [(KIND_NEARBY, "hello wilderness"), (KIND_SPOKEN_SELF, "psst")])
check("only A and E perceived it", perceptions_of(uid9),
      [("npc_a", KIND_SPOKEN_SELF, "still there?"),
       ("npc_e", KIND_NEARBY, "still there?")])

# ── [10] reactions in the open ──────────────────────────────────────────
print("[10] dispatch_room_reactions bumps the radius neighbours")
loop = AgentLoop()
res = loop.dispatch_room_reactions(speaker="npc_a", content="anyone there?",
                                   volume="normal", location_id="", room_id="",
                                   addressees=["npc_e"], is_avatar=False)
check("E must answer", res, {"obligatory": ["npc_e"], "chime": []})
check("nobody else was queued", list(loop._respond_queue), ["npc_e"])
loop = AgentLoop()
res = loop.dispatch_room_reactions(speaker="npc_a", content="hm",
                                   volume="normal", location_id="", room_id="",
                                   addressees=[], is_avatar=False)
check("E may chime in", res, {"obligatory": [], "chime": ["npc_e"]})
loop = AgentLoop()
res = loop.dispatch_room_reactions(speaker="npc_c", content="hello?",
                                   volume="normal", location_id="", room_id="",
                                   addressees=[], is_avatar=False)
check("C stands alone — nobody is bumped", res, {"obligatory": [], "chime": []})
check("C's lane stayed empty", list(loop._respond_queue), [])

# ── [11] TalkTo needs the radius, not just "no location" ────────────────
print("[11] TalkTo in the open: E (17 m) yes, C (30 m) no, D (walls) no")
talk = TalkToSkill({"enabled": True}, PluginContext("talk_to"))


def talk_to(sender, target, message="hey"):
    return talk.execute(json.dumps({"agent_name": sender, "name": target,
                                    "message": message}))


check("A reaches E", talk_to("npc_a", "npc_e").startswith("Spoke to npc_e"), True)
_far = talk_to("npc_a", "npc_c")
check("A does not reach C", "too far" in _far, True)
_walled = talk_to("npc_a", "npc_d")
check("A does not reach D inside the inn", "not out here" in _walled, True)

# ── [12] no global wilderness scene bucket ──────────────────────────────
print("[12] wilderness talk opens NO scene, the inn line did open one")
scene_rows = get_connection().execute(
    "SELECT location_id, room_id FROM scenes").fetchall()
check("no scene without a location",
      [dict(r) for r in scene_rows if not r["location_id"]], [])
check("exactly the inn scene exists",
      [(r["location_id"], r["room_id"]) for r in scene_rows],
      [(INN_ID, D_ROOM)])

# ── [13] prompt presence in the open ────────────────────────────────────
print("[13] the prompt says who is around out there")
save_character_profile("npc_f", {"current_location": ""}, create_new=True)
a_block, a_elsewhere, a_alone = _build_presence("npc_a", "", "")
check("A is told about E", "npc_e" in a_block, True)
check("no 'elsewhere' out here", a_elsewhere, "")
check("A is not alone", a_alone, False)
check("C is alone and knows it", _build_presence("npc_c", "", ""),
      ("", "", True))
check("a character without a point stays unknown",
      _build_presence("npc_f", "", ""), ("", "", False))
lines, elsewhere_lines, anyone = _load_presence("npc_a", "")
check("the system prompt lists E", [l for l in lines if "npc_e" in l] != [], True)
check("no elsewhere lines", elsewhere_lines, [])
check("someone is nearby", anyone, True)
check("C's system prompt knows it is alone", _load_presence("npc_c", ""),
      ([], [], False))
check("the place name is the wilderness label",
      prompt_place("npc_a", "")[0], WILDERNESS_LOCATION_LABEL)
check("a real location still resolves by name",
      prompt_place("npc_d", INN_ID)[0], "Smoke Inn")
prompt_data = load_prompt_data("npc_a", {PRESENCE})
check("prompt location name", prompt_data["location_name"],
      WILDERNESS_LOCATION_LABEL)
check("the nearby hint names E", "npc_e" in prompt_data["nearby_hint"], True)
check("C's nearby hint says it is alone",
      "alone" in load_prompt_data("npc_c", {PRESENCE})["nearby_hint"].lower(),
      True)

# ── [14] announce_action works outside ──────────────────────────────────
print("[14] a direct action outside is narrated INTO the actor's radius")
loop = AgentLoop()
_set_agent_loop(loop)
announce_action("npc_a", "npc_a changes clothes.")
narr = get_connection().execute(
    "SELECT id, location_id, pos_x, pos_z FROM utterances WHERE speaker=? "
    "ORDER BY id DESC LIMIT 1", (STORYTELLER_SPEAKER,)).fetchone()
check("the narrator line was recorded", narr is not None, True)
check("it is location-less", narr["location_id"], "")
check("E is queued for a reaction", list(loop._respond_queue), ["npc_e"])
# E7/D1: the storyteller has no point of its own, so the line borrows the
# ACTING character's — npc_a at (0, 0). Its circle is then npc_a's own: E
# (0, 17) is 17 m away and in; C (30 m) and B (moved to (100, 0) in [9]) are
# out; D sits behind the inn's walls. The actor is in its own circle, so the
# player who triggered the action finally sees the narration of it.
check("the line is anchored on the actor's point",
      (narr["pos_x"], narr["pos_z"]), (0.0, 0.0))
check("the actor and its neighbour perceive the narration",
      perceptions_of(narr["id"]),
      [(STORYTELLER_SPEAKER, KIND_SPOKEN_SELF, "npc_a changes clothes."),
       ("npc_a", KIND_NEARBY, "npc_a changes clothes."),
       ("npc_e", KIND_NEARBY, "npc_a changes clothes.")])
check("…and it is in the actor's own wilderness stream",
      ("nearby", "npc_a changes clothes.") in open_stream("npc_a"), True)
# Red counter-probe: the SAME line without an anchor is the old behaviour —
# a speaker with no point has an empty circle and narrates to nobody. Without
# this the case above would also pass if the fan-out had simply started
# ignoring positions out here.
_unanchored = record_utterance(speaker=STORYTELLER_SPEAKER,
                               content="nobody hears this.",
                               volume=VOLUME_NORMAL, location_id="", room_id="",
                               source="counter_probe")
check("without an anchor the narrator still reaches nobody",
      perceptions_of(_unanchored),
      [(STORYTELLER_SPEAKER, KIND_SPOKEN_SELF, "nobody hears this.")])
check("…and its row carries no point at all",
      dict(get_connection().execute(
          "SELECT pos_x, pos_z FROM utterances WHERE id=?",
          (_unanchored,)).fetchone()), {"pos_x": None, "pos_z": None})
# An anchor never overrides a speaker that HAS a point: npc_c (30, 0) speaks
# anchored on npc_a (0, 0), and the circle stays C's own — A does not hear it.
_anchored_c = record_utterance(speaker="npc_c", content="C speaks for itself.",
                               volume=VOLUME_NORMAL, location_id="", room_id="",
                               source="counter_probe", anchor="npc_a")
check("an anchor does not move a speaker that has a point",
      perceptions_of(_anchored_c),
      [("npc_c", KIND_SPOKEN_SELF, "C speaks for itself.")])

# ── [15] off-map is neither a location nor the open country ─────────────
print("[15] a character without a point is NOT 'alone out here'")
check("npc_f has no point at all", get_character_pos("npc_f"), None)
check("off-map keeps the old place label",
      prompt_place("npc_f", ""), (UNKNOWN_LOCATION_LABEL, False))
check("a placed location-less character IS in the open",
      prompt_place("npc_a", ""), (WILDERNESS_LOCATION_LABEL, True))
check("a location wins over both",
      prompt_place("npc_d", INN_ID), ("Smoke Inn", False))
off_map = load_prompt_data("npc_f", {PRESENCE})
check("off-map prompt says Unknown", off_map["location_name"],
      UNKNOWN_LOCATION_LABEL)
check("off-map prompt claims no solitude",
      "alone out here" in off_map["nearby_hint"], False)
check("off-map prompt claims no wilderness",
      "Wilderness" in off_map["nearby_hint"], False)
check("off-map prompt says nothing about presence at all",
      off_map["nearby_hint"], "")
check("and the thought path agrees (it always did)",
      _build_presence("npc_f", "", ""), ("", "", False))

# ── [16] the outdoor budget is per cell, not global ─────────────────────
print("[16] two distant outdoor groups do not share a chime budget")
save_character_profile("npc_g", {"current_location": ""}, create_new=True)
set_character_pos("npc_g", 110, 0)
loop = AgentLoop()
a_key = loop._room_key("", "", "npc_a")
check("A's cell", a_key, "open:0:0")
check("E is in A's cell — one conversation, one budget",
      loop._room_key("", "", "npc_e"), a_key)
b_key = loop._room_key("", "", "npc_b")
check("B's cell is a different one", b_key, "open:2:0")
check("G shares B's cell", loop._room_key("", "", "npc_g"), b_key)
check("off-map falls back to the shared key",
      loop._room_key("", "", "npc_f"), "/")
check("a location key is untouched",
      loop._room_key(INN_ID, D_ROOM, "npc_d"), f"{INN_ID}/{D_ROOM}")

# Exhaust ONLY A's cell — the counter is what an autonomous outdoor turn
# raises (respond turn), so it is set directly here; no LLM in a smoke.
loop._room_ai_turns[a_key] = loop._chime_backstop
first = loop.dispatch_room_reactions(speaker="npc_a", content="hello?",
                                     volume="normal", location_id="", room_id="",
                                     addressees=["npc_e"], is_avatar=False)
check("exhausted cell: one visible exit beat", first.get("winddown"), ["npc_e"])
second = loop.dispatch_room_reactions(speaker="npc_a", content="still hello?",
                                      volume="normal", location_id="", room_id="",
                                      addressees=["npc_e"], is_avatar=False)
check("exhausted cell: even the mandatory answer is swallowed", second,
      {"obligatory": [], "chime": []})
far = loop.dispatch_room_reactions(speaker="npc_b", content="over here",
                                   volume="normal", location_id="", room_id="",
                                   addressees=["npc_g"], is_avatar=False)
check("the far group answers regardless", far,
      {"obligatory": ["npc_g"], "chime": []})
check("only A's cell is wound down", sorted(loop._room_winddown_done), [a_key])
check("the far cell has no budget spent",
      loop._room_ai_turns.get(b_key, 0), 0)
# The avatar reset works per cell too: an avatar utterance in A's cell frees
# A's budget and does not touch B's.
loop.dispatch_room_reactions(speaker="npc_a", content="fresh start",
                             volume="normal", location_id="", room_id="",
                             addressees=[], is_avatar=True)
check("an avatar line refills its OWN cell", loop._room_ai_turns.get(a_key), 0)

# ── [17] the wilderness prune ───────────────────────────────────────────
print("[17] old location-less lines fall, the room and the recent ones stay")
from app.core import scene_manager  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from datetime import timedelta  # noqa: E402
import app.models.scene_store as _scene_store_mod  # noqa: E402

_now = utc_now()


def _at(delta):
    return (_now + delta).isoformat(timespec="seconds")


check("the horizon is a week", scene_manager.WILDERNESS_RETENTION_DAYS, 7)
# Four rows around the cutoff (now − 7 d), hand-placed: 8 d out, 1 min past
# the edge, 1 min short of it, and one INSIDE the inn that is just as old as
# the oldest wilderness row.
_old_wild = record_utterance(speaker="npc_a", content="ancient open-air talk",
                             volume=VOLUME_NORMAL, ts=_at(-timedelta(days=8)))
_edge_out = record_utterance(speaker="npc_a", content="a minute too old",
                             volume=VOLUME_NORMAL,
                             ts=_at(-timedelta(days=7, minutes=1)))
_edge_in = record_utterance(speaker="npc_a", content="a minute young enough",
                            volume=VOLUME_NORMAL,
                            ts=_at(-timedelta(days=7) + timedelta(minutes=1)))
_old_room = record_utterance(speaker="npc_d", content="ancient inn talk",
                             volume=VOLUME_NORMAL, ts=_at(-timedelta(days=8)))
check("the old outdoor line was heard by A and E", len(perceptions_of(_old_wild)), 2)
check("the old inn line was heard by D alone", len(perceptions_of(_old_room)), 1)

# The prune hangs on the consolidation pass, NOT on there being a scene to
# consolidate: with the scene query answering "nothing idle" (no LLM is
# reachable in a smoke) the sweep must still happen.
_real_idle = _scene_store_mod.get_idle_open_scenes
_scene_store_mod.get_idle_open_scenes = lambda *a, **k: []
try:
    scene_manager.run_idle_consolidation()
finally:
    _scene_store_mod.get_idle_open_scenes = _real_idle


def _utterance_ids():
    return [r["id"] for r in get_connection().execute(
        "SELECT id FROM utterances").fetchall()]


_left = _utterance_ids()
check("the 8-day-old outdoor line is gone", _old_wild in _left, False)
check("…and so are its perceptions", perceptions_of(_old_wild), [])
check("a minute past the edge falls too", _edge_out in _left, False)
check("a minute short of it survives", _edge_in in _left, True)
check("…with its perceptions", len(perceptions_of(_edge_in)), 2)
check("the equally old ROOM line is untouched", _old_room in _left, True)
check("…with its perception", len(perceptions_of(_old_room)), 1)
check("and today's outdoor lines are all still there",
      all(u in _left for u in (uid1, uid2, uid5, uid9)), True)
# Idempotent: the second sweep finds nothing left to drop.
check("a second sweep drops nothing", scene_manager.prune_wilderness_stream(), 0)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
