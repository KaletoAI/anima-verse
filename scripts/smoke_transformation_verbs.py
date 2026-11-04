#!/usr/bin/env python3
"""Smoke: the transformation verbs, the avatar's phrases and the scene-state
identity lines (``plugins/transformation/skill.py``, ``intercept.py``,
``prompt_lines.py``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_verbs.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The embedding is stubbed to "no model" so the
transform activity resolves through the catalog default; the package is
loaded the way the server loads it (``packages.enabled = "transformation"``,
``discover_packages()``), the verbs through the skill manager.

FIXTURE
    Location "Inn", room "taproom": Cara (bearer of "amulet"), Kim (knower of
    Cara), Obs (knows nothing), Ava (the avatar, bearer of "ring").
    Persona p1: item amulet, alias "Moonveil", no suit, no condition,
    max 0 (until reverted), cooldown 0.
    Persona p2: item ring, alias "Starlace", activation_phrase
    "by the moonlight", revert_phrase "Moon, rest", max 0, cooldown 0.
    Game clock pinned (factor 0).

THE RULES (task brief) and what follows BY HAND
[A] tick() seeds the holders' secrets; Kim becomes a knower of Cara/p1.
    Visibility: transform is visible for Cara and Ava (they hold a persona
    item), hidden for Kim and Obs (they hold none). reveal_identity likewise.
    Before any transform the tool round for Cara (turn_tools, thought mode,
    present Kim/Obs/Ava) offers "Transform" and not "Revert": revert is
    visible only while a persona is worn (the single-mode tool list has no
    flag gate), and the manifest's state_flags names it the clearing verb of
    is_transformed, so turn_tools would hide it with "state not active" too —
    checked directly on inactive_clearing_tools.
[B] execute('{"agent_name":"Cara"}') on transform -> not an "Error",
    Cara's active persona is p1, flag is_transformed True.
    The next round offers "Revert" and hides "Transform"
    ("already transformed" from available_now).
[C] Scene-state lines while Cara is Moonveil. Everybody stands in the
    taproom; names in a line are sorted (casefold) and joined "A and B".
    - Kim knows Cara/p1, Cara is present and transformed; the others present
      besides Kim and Cara are Ava and Obs, neither knows ->
      'Moonveil here is actually Cara. Ava and Obs do not know — do not call
      Moonveil "Cara" in front of them.'  Kim knows no other bearer, so that
      is Kim's ONLY line.
    - Cara is transformed; her knowers are [Kim]; non-knowers present Ava,
      Obs -> 'You are currently Moonveil. Only Kim knows that you are Cara.
      Ava and Obs do not know — never reveal it in front of them.'
    - Obs knows nothing -> blocks_for("Obs") == [].
    - The rp_first tool step: reveal_identity's menu for Cara lists who
      present is not in on it -> ["Ava", "Obs"]; its state line reads
      "Persona Moonveil. Already in on it: Kim. Not in on it: Ava, Obs."
      Cara carries one power item, so transform has no menu.
    - The chat event (character.prompt_context, mode chat) gives Kim the same
      line; the thought event (character.thought_context) gives Kim one
      section that starts with "=== " and contains the line.
[D] Avatar phrases (say_intercept, through play._run_say_intercepts):
    - Ava says "By the  Moonlight!" -> normalized "by the moonlight" contains
      p2's activation phrase -> consumed, result {"kind": "transformation",
      "ok": True, "reason": "", "alias": "Starlace"}; Ava is active on p2.
      Ava's own line reaches Ava only (no other knower of Ava/p2 is
      present): Obs has NO perception row whose content contains
      "moonlight" (casefold).
    - "What a moonlight night" -> no contiguous "by the moonlight" -> None.
    - Obs says "by the moonlight" -> Obs holds no persona item -> None.
    - Ava says it again -> consumed, ok False, reason "already_transformed";
      a storyteller hint reaches Ava only.
    - Ava says "Moon... rest." -> normalized "moon rest" == revert phrase ->
      consumed, ok True, alias "Starlace"; Ava no longer active.
[E] reveal_identity (Cara still Moonveil):
    - target Obs -> not an "Error"; identity_view.knows("Obs","Cara") True,
      shown_name("Obs","Cara") == "Moonveil (Cara)"; the line
      "Cara reveals to Obs: Cara is Moonveil." reaches exactly {Cara, Obs}.
    - target Obs again -> starts with "Error" (already knows).
    - target "Nobody" (not present) -> starts with "Error".
[F] revert verb: execute -> not an "Error"; Cara no longer active; flag
    False; "Revert" not offered again; a second revert -> "Error".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-verbs-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")

PERSONAS = [
    {"id": "p1", "item_id": "amulet", "alias": "Moonveil",
     "description": "A figure in moonlit silver.",
     "max_duration_minutes": 0, "cooldown_minutes": 0},
    {"id": "p2", "item_id": "ring", "alias": "Starlace",
     "description": "A figure wrapped in starlight.",
     "activation_phrase": "by the moonlight", "revert_phrase": "Moon, rest",
     "max_duration_minutes": 0, "cooldown_minutes": 0},
]
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
    "skills": {"transformation_personas": PERSONAS},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core.db import get_connection  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
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


set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs", "Ava"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = "taproom"
        assert save_character_profile(_name, _p)

inventory.add_item("Amulet", item_id="amulet")
inventory.add_item("Ring", item_id="ring")
assert inventory.add_to_inventory("Cara", "amulet")
assert inventory.add_to_inventory("Ava", "ring")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks, identity_view, perception  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.streaming import turn_tools  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402
from plugins.transformation import engine, knowers, prompt_lines, store  # noqa: E402

manager = get_skill_manager()
transform = manager.get_skill("transform")
revert = manager.get_skill("revert")
reveal = manager.get_skill("reveal_identity")
check("three verbs loaded", [s is not None for s in (transform, revert, reveal)],
      [True, True, True])


def offered(name):
    tools = manager.get_agent_tools(name, check_limits=False, turn="thought")
    present = tuple(perception.addressable_for(name))
    got, hidden = turn_tools(tools, TurnFacts(name, "thought", present), rp_first=False)
    return {getattr(t, "name", t) for t in got}, hidden


def rows_containing(perceiver, needle):
    conn = get_connection()
    return [r[0] for r in conn.execute(
        "SELECT p.content FROM perceptions p JOIN utterances u ON u.id = p.utterance_id "
        "WHERE p.perceiver=?", (perceiver,))
        if needle.casefold() in (r[0] or "").casefold()]


def line_rows(content):
    conn = get_connection()
    ids = [r[0] for r in conn.execute("SELECT id FROM utterances WHERE content=?", (content,))]
    out = set()
    for uid in ids:
        out.update(r[0] for r in conn.execute(
            "SELECT perceiver FROM perceptions WHERE utterance_id=?", (uid,)))
    return ids, out


def is_error(text):
    return str(text).startswith("Error")


# ── [A] visibility, before any transform ────────────────────────────────────
print("[A] visibility")
engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("Cara in the room", sorted(perception.addressable_for("Cara")), ["Ava", "Kim", "Obs"])
for _name, _vis in (("Cara", True), ("Ava", True), ("Kim", False), ("Obs", False)):
    check(f"transform visible for {_name}", transform.visible_for(_name), _vis)
    check(f"reveal_identity visible for {_name}", reveal.visible_for(_name), _vis)
_got, _hidden = offered("Cara")
check("Transform offered before", transform.name in _got, True)
check("Revert not offered before", revert.name in _got, False)
check("revert invisible before", revert.visible_for("Cara"), False)
from app.core.flag_lifecycle import inactive_clearing_tools  # noqa: E402
check("state flag declares revert as its clearing verb (flag unset -> inactive)",
      inactive_clearing_tools("Cara", [revert.name]), {revert.name})
check("transform hidden for Obs (no item)",
      transform.name in offered("Obs")[0], False)

# ── [B] transform verb ──────────────────────────────────────────────────────
print("[B] transform verb")
_res = transform.execute('{"agent_name":"Cara"}')
check("transform result is no error", is_error(_res), False)
check("Cara wears p1", getattr(store.get_active("Cara"), "persona_id", None), "p1")
check("flag set", get_character_profile("Cara").get("is_transformed"), True)
_got, _hidden = offered("Cara")
check("Revert offered while transformed", revert.name in _got, True)
check("flag set -> revert's state active", inactive_clearing_tools("Cara", [revert.name]), set())
check("Transform hidden while transformed",
      (transform.name in _got, _hidden.get(transform.name)), (False, "already transformed"))

# ── [C] scene-state lines ───────────────────────────────────────────────────
print("[C] scene-state lines")
KIM_LINE = ('Moonveil here is actually Cara. Ava and Obs do not know — do not call '
            'Moonveil "Cara" in front of them.')
CARA_LINE = ('You are currently Moonveil. Only Kim knows that you are Cara. '
             'Ava and Obs do not know — never reveal it in front of them.')
_kim = prompt_lines.blocks_for("Kim")
check("Kim's lines", _kim, [KIM_LINE])
check("Kim's line names the identity", any("Moonveil here is actually Cara" in b for b in _kim), True)
check("Cara's lines", prompt_lines.blocks_for("Cara"), [CARA_LINE])
check("Obs gets nothing", prompt_lines.blocks_for("Obs"), [])
check("reveal menu for Cara", reveal.decision_menu("Cara"), ["Ava", "Obs"])
check("reveal state line for Cara", reveal.tool_decision_context("Cara"),
      "Persona Moonveil. Already in on it: Kim. Not in on it: Ava, Obs.")
check("transform menu with one item", transform.decision_menu("Cara"), [])
_blocks = []
hooks.emit("character.prompt_context", character_name="Kim", mode="chat", blocks=_blocks)
check("chat event carries Kim's line", KIM_LINE in _blocks, True)
_blocks = []
hooks.emit("character.prompt_context", character_name="Obs", mode="chat", blocks=_blocks)
check("chat event gives Obs nothing of it", [b for b in _blocks if "Moonveil" in b], [])
_sections = []
hooks.emit("character.thought_context", character_name="Kim", blocks=_sections)
check("thought event: one section for Kim", len(_sections), 1)
check("thought section is headed and holds the line",
      bool(_sections) and _sections[0].startswith("=== ") and KIM_LINE in _sections[0], True)
from app.core.thought_context import build_thought_context  # noqa: E402
check("thought context of Kim carries the line",
      KIM_LINE in build_thought_context("Kim").get("skill_context_blocks", ""), True)
check("thought context of Obs does not",
      "Moonveil" in build_thought_context("Obs").get("skill_context_blocks", ""), False)

# ── [D] avatar phrases ──────────────────────────────────────────────────────
print("[D] avatar phrases")
from app.routes import play  # noqa: E402


def say(avatar, content):
    return play._run_say_intercepts(avatar=avatar, content=content, volume="normal",
                                    addressees=[], location_id=INN, room_id="taproom")


check("activation phrase consumed", say("Ava", "By the  Moonlight!"),
      {"kind": "transformation", "ok": True, "reason": "", "alias": "Starlace"})
check("Ava wears p2", getattr(store.get_active("Ava"), "persona_id", None), "p2")
check("Obs heard nothing of the phrase", rows_containing("Obs", "moonlight"), [])
check("Kim heard nothing of the phrase", rows_containing("Kim", "moonlight"), [])
check("Ava has her own line", rows_containing("Ava", "By the  Moonlight!"), ["By the  Moonlight!"])
check("no contiguous phrase -> not consumed", say("Ava", "What a moonlight night"), None)
check("Obs holds no item -> not consumed", say("Obs", "by the moonlight"), None)
_before = {n: len(rows_containing(n, "")) for n in ("Ava", "Obs", "Kim", "Cara")}
_again = say("Ava", "by the moonlight")
check("phrase again consumed, refused",
      (_again or {}).get("ok"), False)
check("refusal reason", (_again or {}).get("reason"), "already_transformed")
_after = {n: len(rows_containing(n, "")) for n in ("Ava", "Obs", "Kim", "Cara")}
check("refusal hint (+ phrase line) for Ava only",
      {n: _after[n] - _before[n] for n in _after}, {"Ava": 2, "Obs": 0, "Kim": 0, "Cara": 0})
check("revert phrase consumed", say("Ava", "Moon... rest."),
      {"kind": "transformation", "ok": True, "reason": "", "alias": "Starlace"})
check("Ava no longer transformed", store.get_active("Ava"), None)

# ── [E] reveal_identity ─────────────────────────────────────────────────────
print("[E] reveal_identity")
_res = reveal.execute('{"agent_name":"Cara","target":"Obs"}')
check("reveal to Obs is no error", is_error(_res), False)
check("Obs knows now", identity_view.knows("Obs", "Cara"), True)
check("Obs sees both names", identity_view.shown_name("Obs", "Cara"), "Moonveil (Cara)")
_ids, _who = line_rows("Cara reveals to Obs: Cara is Moonveil.")
check("one reveal line", len(_ids), 1)
check("reveal line reaches Cara + Obs only", _who, {"Cara", "Obs"})
check("reveal again -> error", is_error(reveal.execute('{"agent_name":"Cara","target":"Obs"}')), True)
check("absent target -> error",
      is_error(reveal.execute('{"agent_name":"Cara","target":"Nobody"}')), True)

# ── [F] revert verb ─────────────────────────────────────────────────────────
print("[F] revert verb")
_res = revert.execute('{"agent_name":"Cara"}')
check("revert result is no error", is_error(_res), False)
check("Cara no longer active", store.get_active("Cara"), None)
check("flag cleared", get_character_profile("Cara").get("is_transformed"), False)
_got, _hidden = offered("Cara")
check("Revert not offered again", revert.name in _got, False)
check("revert of nobody -> error", is_error(revert.execute('{"agent_name":"Cara"}')), True)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
