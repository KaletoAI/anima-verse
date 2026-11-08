#!/usr/bin/env python3
"""Party consent: prose only, once in the prompt, no copied call in the reply.

Usage: ./.venv/bin/python scripts/smoke_consent_prose_once.py

Background (2026-11-08): the player invited the ordinary rp_first NPC Rosi.
``request_consent`` handed the rendered ``party/consent.md`` to
``bump_respond`` as content AND hint. The template told the ROLEPLAY model
"To accept, call JoinParty with leader=…, invite_id=…" — a model that calls no
tool. It wrote ``**JoinParty with leader=Lirien Edwinsdottir,
invite_id=pinv_20cba06349**`` as the first line of its spoken reply (seen in
the player's chat), and the tool step that read the reply took that line for
a yes the prose had declined. Without a room transcript the same block stood
in the chat prompt twice: as the appended incoming user line and as the
``[hint]`` note in the scene state (logs/llm_calls.jsonl 22:19:08, two
occurrences of "Consent is your choice").

Throwaway storage, no server, no LLM. Hand-derived expectations:

  (a) consent.md renders prose only. Inviter "Kai", no destination,
      participants [Kai, Rosi]: contains "Kai invites you to travel
      together.", "There is no fixed destination", "The explicitly included
      group is: Kai, Rosi." and "Decide in character whether to accept this
      exact proposal. Consent is your choice." — the group sentence and the
      decision sentence on SEPARATE lines (the old template glued them:
      "Rosi.Decide"); contains neither "JoinParty", nor "call ", nor
      "invite_id", nor the invite id "pinv_x1". With destination "Cellar"
      and after_arrival_label "sitting": "travel together to Cellar.", no
      no-destination sentence, the after-arrival sentence, same absences.

  (b) run_chat_turn, chat context stubbed, scene state rendered by the REAL
      chat/chat_moment.md from the moment notes run_chat_turn passes:
      content == hint == the consent text.
      - no room transcript (1:1 history ending with an assistant line, the
        logged shape): the consent text occurs exactly ONCE across all
        submitted messages, inside the scene-state user turn (as "[<text>]");
        the last message is a user turn (the scene state).
      - room mode with a transcript: once as well.
      - a different hint ("A spell takes hold.") with an ordinary incoming
        line ("Noch ein Bier"), no transcript: the line is appended as its
        own user turn AND the hint note stands in the scene state — each
        once (unchanged behaviour for real speech).

  (c) strip_pseudo_tool_lines with offered {JoinParty, InteractWith, Sleep}:
      - the exact logged reply "**JoinParty with leader=Lirien Edwinsdottir,
        invite_id=pinv_20cba06349**  \\n\\nIch kann nicht einfach weg,
        Liebes.\\n\\n**I feel neugierig**" -> the JoinParty line is gone, the
        "**I feel neugierig**" marker is still there; clean_response of that
        -> "Ich kann nicht einfach weg, Liebes."
      - "**InteractWith Lirien Edwinsdottir: cellar_invite**\\nKomm mit." ->
        "Komm mit."; "**Sleep**" alone -> "".
      - kept unchanged: "**Wow!**\\nSchön.", "**Sleep tight!**" (no call
        shape), "**SetLocation with target=Cellar**" (SetLocation NOT
        offered), "**I do wipe the counter**", and an inline bold call inside
        a sentence ("Sie sagt **JoinParty with x=1** leise.").

  (d) run_chat_turn in rp_first with the logged reply: the returned and
      published reply is "Ich kann nicht einfach weg, Liebes."; the tool
      step is built from that text — its ``rp_response`` contains no
      "JoinParty" (the line that caused the wrong yes).

  (e) The thought turn of a single-mode character (it calls tools itself)
      appends ``open_questions_note`` to its user turn after
      ``thought_user_input`` — the hint that asks the question is prose now,
      so the exact calls must come from there (rp_first thoughts get them in
      ``build_tool_step_prompt``). Source check: the turn needs a live model.
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="consent-once-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="consent-once-clips-")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig" / "reference.fbx")

from app.core import paths  # noqa: E402
paths.init(STORAGE / "world")
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "world" / "config.json")
db.init_schema()

from app.core import chat_engine, prompt_templates, streaming, tool_step_prompt  # noqa: E402
from app.core import prop_actions  # noqa: E402
from app.core.chat_engine import clean_response  # noqa: E402
from app.core.stat_sources import ReplyReceipt  # noqa: E402
from app.core.tool_formats import strip_pseudo_tool_lines  # noqa: E402
import app.core.llm_queue as llm_queue_mod  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + ("" if ok else f" — {detail!r}"))
    if not ok:
        FAILURES.append(label)


# The consent template lives in the party package; loading the packages
# registers its template directory.
_cfg = config.get_all()
_cfg["packages"] = {"enabled": "party"}
_cfg.setdefault("image_generation", {})["enabled"] = False
config.save(_cfg)
from app.core.dependencies import get_skill_manager  # noqa: E402
get_skill_manager()
from app.models import character as chars  # noqa: E402
for _name in ("Rosi", "Kai"):  # the 1:1 history rows need both characters
    assert chars.save_character_profile(_name, {
        "character_name": _name, "template": "human-roleplay", "language": "de"}, create_new=True)


def consent(**kw):
    base = {"inviter": "Kai", "invite_id": "pinv_x1", "destination_label": "",
            "participants": [], "after_arrival_label": ""}
    return prompt_templates.render("party/consent.md", **{**base, **kw})


# ── (a) consent.md is prose only ───────────────────────────────────────────
print("(a) consent.md renders prose only")
plain = consent(participants=["Kai", "Rosi"])
for needle in ("Kai invites you to travel together.", "There is no fixed destination",
               "The explicitly included group is: Kai, Rosi.",
               "Decide in character whether to accept this exact proposal. Consent is your choice."):
    check(f"keeps {needle[:40]!r}", needle in plain, plain)
check("group and decision on separate lines",
      "Kai, Rosi.\nDecide in character" in plain, plain)
trip = consent(destination_label="Cellar", after_arrival_label="sitting", participants=["Kai", "Rosi"])
check("trip: destination named", "travel together to Cellar." in trip, trip)
check("trip: no no-destination sentence", "There is no fixed destination" not in trip, trip)
check("trip: after-arrival sentence",
      "After arrival, the proposal includes sitting together." in trip, trip)
for text, label in ((plain, "plain"), (trip, "trip")):
    for bad in ("JoinParty", "call ", "invite_id", "pinv_x1", "prose alone"):
        check(f"{label}: no {bad!r}", bad not in text, text)

# ── (b) the consent reaches the chat prompt once ───────────────────────────
print("(b) run_chat_turn: the consent block stands in the prompt once")
prop_actions.prompt_block = lambda actor: ""
prop_actions.narrative_block = lambda actor: ""


def moment_from_notes(notes):
    """The scene state exactly as chat/chat_moment.md renders it for these
    notes (every other block empty)."""
    return prompt_templates.render(
        "chat/chat_moment.md", character_name="Rosi", prop_actions_executable=True,
        partner_mode="character", partner_name="Kai", partner_state_lines=[],
        partner_address="", present_characters="", present_details="",
        situation_block="", self_state_lines=[], condition_reminder="",
        moment_notes=list(notes or []), self_wearing="", partner_wearing="",
        inventory_carrying_section="", inventory_room_section="", focused_items="",
        known_activities="", events_section="", assignment_section="",
        recent_activity_section="", memory_section="", relationships_section="",
        reply_shape_section="", moment_facts=[], addressed_to_me=True,
        addressed_names="", respond_opportunity=False, winding_down=False,
        away_block="", prop_actions_block="")


def make_ctx(history, room_mode, mode="rp_first", tool_llm=None, tools=None):
    def build(owner, name, user_input, **kw):
        return {
            "llm": object(), "system_content": "sys",
            "moment_content": moment_from_notes(kw.get("moment_notes")),
            "messages": list(history), "room_mode": room_mode, "mode": mode,
            "tool_llm": tool_llm, "tools_dict": dict(tools or {}), "agent_tools": [],
            "tool_format": "tag", "deferred_tools": set(), "content_tools": set(),
            "medium": "in_person", "agent_config": {}, "user_display_name": "Kai",
            "full_chat_history": [], "old_history": None,
        }
    return build


class Queue:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.submits = []

    def submit(self, **kwargs):
        self.submits.append(kwargs)
        return SimpleNamespace(content=self.answers[min(len(self.submits), len(self.answers)) - 1])


chat_engine.memory_situational = SimpleNamespace(build_situational_block=lambda *a, **k: "")
import app.core.memory_situational as _ms  # noqa: E402
_ms.build_situational_block = lambda *a, **k: ""


def chat_messages(queue):
    return queue.submits[0]["messages_or_prompt"]


def run(history, room_mode, incoming, hint, reply="Mal sehen."):
    queue = Queue(reply)
    llm_queue_mod.get_llm_queue = lambda: queue
    chat_engine.build_chat_context = make_ctx(history, room_mode)
    chat_engine.run_chat_turn("", "Rosi", "Kai", incoming, "in_person", "character_talk",
                              False, room_stream=[{"x": 1}] if room_mode else None,
                              hint=hint, synthetic_input=True)
    return chat_messages(queue)


CONSENT = consent(participants=["Kai", "Rosi"])
HISTORY = [{"role": "assistant", "content": "Darf's noch etwas sein?"}]
msgs = run(HISTORY, False, CONSENT, CONSENT)
joined = "\n".join(m["content"] for m in msgs)
check("no transcript: consent once", joined.count("Consent is your choice") == 1,
      joined.count("Consent is your choice"))
check("no transcript: inside the scene state as the hint note",
      f"[{CONSENT}]" in msgs[-1]["content"] and "[SCENE STATE" in msgs[-1]["content"],
      msgs[-1]["content"][:200])
check("no transcript: last message is the user turn", msgs[-1]["role"] == "user", msgs[-1])

msgs = run([{"role": "user", "content": "Kai: Hallo"}, {"role": "assistant", "content": "Hallo."}],
           True, CONSENT, CONSENT)
joined = "\n".join(m["content"] for m in msgs)
check("room transcript: consent once", joined.count("Consent is your choice") == 1,
      joined.count("Consent is your choice"))

msgs = run(HISTORY, False, "Noch ein Bier", "A spell takes hold.")
contents = [m["content"] for m in msgs]
check("real speech: the line is its own user turn",
      any(c.startswith("Noch ein Bier") for c in contents if c), contents)
joined = "\n".join(contents)
check("real speech: line once, hint once",
      joined.count("Noch ein Bier") == 1 and joined.count("[A spell takes hold.]") == 1, joined)

# ── (c) strip_pseudo_tool_lines ────────────────────────────────────────────
print("(c) strip_pseudo_tool_lines")
OFFERED = {"JoinParty": None, "InteractWith": None, "Sleep": None}
LOGGED = ("**JoinParty with leader=Lirien Edwinsdottir, invite_id=pinv_20cba06349**  \n\n"
          "Ich kann nicht einfach weg, Liebes.\n\n**I feel neugierig**")
stripped = strip_pseudo_tool_lines(LOGGED, OFFERED)
check("logged: call line gone", "JoinParty" not in stripped, stripped)
check("logged: mood marker kept", "**I feel neugierig**" in stripped, stripped)
check("logged: spoken text", clean_response(stripped) == "Ich kann nicht einfach weg, Liebes.",
      clean_response(stripped))
check("InteractWith line gone",
      strip_pseudo_tool_lines("**InteractWith Lirien Edwinsdottir: cellar_invite**\nKomm mit.",
                              OFFERED) == "Komm mit.")
check("bare bold tool name gone", strip_pseudo_tool_lines("**Sleep**", OFFERED) == "")
for kept in ("**Wow!**\nSchön.", "**Sleep tight!**", "**SetLocation with target=Cellar**",
             "**I do wipe the counter**", "Sie sagt **JoinParty with x=1** leise."):
    out = strip_pseudo_tool_lines(kept, OFFERED)
    check(f"kept {kept[:30]!r}", out == kept, out)
check("no tools offered: unchanged", strip_pseudo_tool_lines(LOGGED, {}) == LOGGED)

# ── (d) rp_first respond turn: spoken reply and tool step without the line ─
print("(d) run_chat_turn (rp_first): publish + tool step see the spoken text")
STEP_INPUTS = []


def fake_step_prompt(character, *, rp_response, **_kw):
    STEP_INPUTS.append(rp_response)
    return SimpleNamespace(system="s", user="u")


tool_step_prompt.build_tool_step_prompt = fake_step_prompt
streaming.tool_step_presence = lambda name: ()
streaming.decision_tools = lambda tools, **kw: tools
PUBLISHED = []
queue = Queue(LOGGED, "")
llm_queue_mod.get_llm_queue = lambda: queue
chat_engine.build_chat_context = make_ctx(HISTORY, False, tool_llm=object(),
                                          tools={"JoinParty": lambda inp: None})
reply = chat_engine.run_chat_turn(
    "", "Rosi", "Kai", CONSENT, "in_person", "character_talk", False,
    hint=CONSENT, synthetic_input=True,
    publish_reply=lambda text: (PUBLISHED.append(text), ReplyReceipt(None))[1])
check("returned reply", reply == "Ich kann nicht einfach weg, Liebes.", reply)
check("published reply", PUBLISHED == ["Ich kann nicht einfach weg, Liebes."], PUBLISHED)
end = time.time() + 3
while not STEP_INPUTS and time.time() < end:
    time.sleep(0.02)
check("tool step ran on the spoken text",
      STEP_INPUTS == ["Ich kann nicht einfach weg, Liebes."], STEP_INPUTS)

# ── (e) single-mode thought turn gets the exact answer calls ──────────────
print("(e) thought turn (single mode): open questions in the user turn")
import inspect  # noqa: E402
from app.core import thoughts  # noqa: E402
_src = inspect.getsource(thoughts.ThoughtRunner.run_thought_turn)
check("thought user turn appends open_questions_note when not rp_first",
      'if mode != "rp_first" and tools_dict:' in _src
      and "open_questions_note, character_name, tools_dict" in _src
      and _src.index("open_questions_note, character_name")
      > _src.index("user_input = thought_user_input("), _src[:0])

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL OK")
