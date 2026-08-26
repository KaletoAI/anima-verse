#!/usr/bin/env python3
"""Smoke run for temporary NPCs: feature gates, free-text outfit, TTL sweep.

Usage:
    ./.venv/bin/python scripts/smoke_temporary_npc.py

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

Doctrine under test: a temporary NPC is an ordinary character whose TEMPLATE
switches its subsystems off. Nothing in the core knows what an NPC is, so every
expectation below is really an expectation about a feature FLAG — and every one
is derived by hand from the gate's call site, not recorded from current output.

Sections:

  [1] The marker fails CLOSED. `is_feature_enabled` returns True for a key the
      template omits (character_template.py: `features.get(feature, True)`),
      which would make a POSITIVE marker mark every character in the world.
      `is_temporary_npc` therefore goes through `template_feature`, which
      defaults to False. Asserted for: the NPC (True), a normal roleplay
      character (False), a template that does not exist (False), and a name
      that does not exist (False).

  [2] No memory, at the single write point. `add_memory` is THE place a memory
      row is created — scene consolidation, extraction and the intro memory all
      funnel through it. One call for the NPC must write ZERO rows while the
      identical call for the roleplay character writes one. Checked by counting
      rows in `memories`, not by trusting the return value.

  [3] No extraction and no relationship turn. Both live in
      `chat_engine.post_process_response`'s background pass and both start with
      an LLM call, so the gate has to sit BEFORE the call, not before the write.
      The check stubs `extract_memories_from_exchange` and `record_interaction`
      with counters and runs the real `post_process_response` for both
      characters: for the NPC neither stub may fire.

  [4] No intents. `parse_and_apply_intent_markers` is stubbed the same way and
      must not fire for the NPC even though the response carries a well-formed
      `[INTENT: …]` marker — a marker the roleplay character DOES get parsed.

  [5] Free-text outfit. The NPC owns no wardrobe pieces, so `render_outfit`
      would return `full=""` and every prompt would describe a naked figure.
      The profile's `outfit_description` fills that slot with the `wearing: `
      prefix the consumers expect (chat's `_build_wearing_block` and
      prompt_builder both strip exactly that prefix). `outfit_worn = "false"`
      is the binary undressed state and must empty it again. A character WITH
      pieces must be unaffected — the free text may never outrank a real
      wardrobe.

  [5a] …and it reaches the COMPOSED IMAGE PROMPT. Measured at the consumer:
      the string `generate_model_ref_images(kinds=("tpose",))` hands to the
      image service. `render_outfit` being right is not enough — the T-pose
      render (and therefore the 3D mesh built from it) read only the
      `pieces`/`items`/`fallback` keys and left the free text, which lives in
      `full` alone, on the floor. The prompt must contain
      "<name> is wearing <outfit_description>" verbatim, `outfit_worn=false`
      must take the clause out again, and a wardrobe character must still be
      dressed from its pieces.

  [5b] …and it keys the RENDER CACHE. `current_outfit_state`'s signature is
      the file name of both per-outfit caches (`model_refs/<kind>_<sig>.png`,
      `model3d/<sig>.*`). Hashing only the equipped state gave every
      temporary NPC in the world the same key, so the first NPC's render was
      served to all of them and no edit of `outfit_description` could
      invalidate anything. The signature is md5(<raw>)[:12] of the equipped
      state, or — when nothing structured is worn — of `render_outfit(…)
      ["full"]`. Checked with the hashes derived by hand at the section, and
      with the regression that matters: a character with a structured outfit
      keeps EXACTLY its pre-change signature.

  [5c] …and it keys the EXPRESSION VARIANT too. `expression_regen._cache_key`
      hashed the equipped state alone, which is empty for every temporary NPC
      — one file name for all of them, and no edit of `outfit_description`
      invalidated anything. It now folds in the same raw string
      `outfit_signature` hashes (`model_refs.outfit_signature_raw`, ONE rule,
      no second hash). Two outfit texts give two keys; a character with a
      structured outfit keeps EXACTLY its pre-change key, derived by hand
      from the OLD formula.

  [6] TTL is GAME time. `expiry_stamp(2)` must land exactly 2 game hours after
      now — 7200 game seconds, checked as a number, not as a formatted string.
      No TTL yields "" (lives forever), a negative TTL yields "" as well.

  [7] The sweep takes exactly the expired NPC out of the world. Three
      characters: an expired NPC, an NPC whose TTL is still in the future, and
      a normal character whose profile carries an expired stamp (it is not an
      NPC, so the stamp is meaningless). Exactly one name may disappear from
      the roster. WHERE it goes is the pool's business (§ 3 of
      plan-npc-auto-spawn.md, checked in scripts/smoke_npc_spawn.py) — from
      here it is gone either way.

  [8] The sweep's trace cleanup. `cleanup_npc_traces` deletes what OTHER
      characters remember ABOUT the NPC: the memory whose meta names it as
      `related_character`, and the memory whose text names it as a whole word.
      It must NOT delete the lookalike ("Marenta" is not "Maren"), must NOT
      delete an unrelated memory, and must NOT touch the daily summary that
      merely mentions the name — a daily summary is about the DAY. The
      per-partner summary row DOES go.

  [9] The generation schema resolves completely. `_load_schema` substitutes by
      plain `str.replace` and leaves an unknown placeholder standing as literal
      `{name}`, so the LLM would be told to fill a field list that reads
      "{generable_fields}". Any leftover `{lower_snake_case}` token fails. The
      field list itself is derived from the TEMPLATE, which is what makes a
      second NPC kind a template variant instead of new code — asserted by
      naming every field that must be offered, and every field the LLM must not
      be allowed to set (`expires_at`, `npc_briefing`, `outfit_worn`,
      `roleplay_instructions`).

  [10] Local field validation. `validate_npc_fields` is the free half of the
      validate stage and the gate the apply stage re-runs. It must accept a
      complete NPC, and reject the four shapes that would drag an NPC back into
      the systems it is meant to stay out of: a missing required field, an
      `outfits` array, a soul document, and a personality written as markdown.

  [11] The pipeline end to end. Only the LLM is stubbed — the schema build, the
      ```json:npc fence extraction, both validation passes, the repair turn and
      the real apply all run. The stub's first answer deliberately omits
      `standing_task`, so the run also proves the REPAIR stage is what rescues
      it: with a one-shot generator that is the difference between a usable NPC
      and a rejected run. Exactly three LLM turns may happen (generate,
      validate, repair) — four would mean repair looped, two would mean the
      validator was never asked. The resulting character is then checked
      against everything the decisions promise: the pinned template, the
      standing task doubling as the activity baseline, the free-text outfit
      with no wardrobe pieces, a 3-game-hour TTL, and no memory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npc-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npc-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import config  # noqa: E402
# The FINISH GATE is off here. This run is about the template's feature gates,
# the free-text outfit and the TTL sweep; with the gate armed the pipeline's
# NPC — which has no portrait and no mesh — would be held out of the world,
# which is what scripts/smoke_npc_assets.py checks instead.
config._CONFIG.setdefault("npc", {})["require_assets"] = False

from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import game_time, set_game_time  # noqa: E402

# A fresh world starts at the game epoch, and GameTime refuses to go below it —
# so the "already expired" stamps below would underflow. Anchor the clock a few
# days in so both directions exist.
set_game_time(GameTime.from_parts(1, 10, 12, 0, 0))
from app.models.character import (  # noqa: E402
    delete_character, get_character_profile, is_temporary_npc,
    list_available_characters, list_temporary_npcs, save_character_profile)
from app.models.character_template import is_feature_enabled  # noqa: E402
from app.models.memory import add_memory  # noqa: E402

NPC = "demo_npc"
NPC_ALIVE = "demo_npc_alive"
RP = "demo"
LOOKALIKE_TEXT = "Marenta brought the wine."

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def make_character(name, template, **extra):
    profile = {"character_name": name, "template": template}
    profile.update(extra)
    save_character_profile(name, profile, create_new=True)


def count_memories(name=None):
    conn = db.get_connection()
    if name:
        return conn.execute("SELECT COUNT(*) FROM memories WHERE character_name=?",
                            (name,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]


# ---------------------------------------------------------------------------
print("[1] The temporary marker fails CLOSED")
make_character(NPC, "npc-temporary",
               character_personality="Gruff, economical with words.",
               standing_task="tends the bar",
               outfit_description="grey linen apron, rolled-up white shirt")
make_character(RP, "human-roleplay",
               character_personality="Warm, curious, talks with her hands.")
make_character("demo_broken", "no-such-template-exists")

check("NPC is temporary", is_temporary_npc(NPC), True)
check("roleplay character is not", is_temporary_npc(RP), False)
check("unknown template is not", is_temporary_npc("demo_broken"), False)
check("unknown character is not", is_temporary_npc("demo_ghost"), False)
check("empty name is not", is_temporary_npc(""), False)
# The flags the gates below actually read:
check("NPC memory_enabled", is_feature_enabled(NPC, "memory_enabled"), False)
check("NPC relationships_enabled", is_feature_enabled(NPC, "relationships_enabled"), False)
check("NPC intents_enabled", is_feature_enabled(NPC, "intents_enabled"), False)
check("NPC thoughts_enabled", is_feature_enabled(NPC, "thoughts_enabled"), False)
check("NPC playable_avatar", is_feature_enabled(NPC, "playable_avatar"), False)
check("RP memory_enabled", is_feature_enabled(RP, "memory_enabled"), True)
check("RP intents_enabled (fail-open, flag is new)",
      is_feature_enabled(RP, "intents_enabled"), True)

# ---------------------------------------------------------------------------
print("\n[2] add_memory writes nothing for the NPC")
before = count_memories()
add_memory(NPC, "The stranger ordered a beer.", memory_type="episodic")
check("NPC memory rows", count_memories(NPC), 0)
add_memory(RP, "The stranger ordered a beer.", memory_type="episodic")
check("roleplay memory rows", count_memories(RP), 1)
check("total rows added", count_memories() - before, 1)

# Fail-open on an ABSENT answer. `is_feature_enabled` resolves a profile
# WITHOUT a `template` field against `human-default`, which disables
# everything — so gating the write with it would make any template-less
# character silently stop remembering (scripts/smoke_character_reinit.py seeds
# exactly such profiles and caught this). The write gate therefore uses
# `feature_disabled`, which only fires on an explicit "off".
save_character_profile("demo_no_template", {"character_name": "demo_no_template"},
                       create_new=True)
add_memory("demo_no_template", "Something happened.", memory_type="episodic")
check("a character without a template still remembers",
      count_memories("demo_no_template"), 1)

# ---------------------------------------------------------------------------
print("\n[3]+[4] No extraction, no relationship turn, no intent parse")
import app.core.chat_engine as chat_engine  # noqa: E402
import app.core.memory_service as memory_service  # noqa: E402
import app.models.relationship as relationship_mod  # noqa: E402
import app.models.intents as intents_mod  # noqa: E402
import app.routes.chat as chat_routes  # noqa: E402

CALLS = {"extract": [], "relationship": [], "intent": []}

memory_service.extract_memories_from_exchange = (
    lambda name, *a, **k: CALLS["extract"].append(name) or [])
relationship_mod.record_interaction = (
    lambda char_a, char_b, **k: CALLS["relationship"].append(char_b) or {})
intents_mod.parse_and_apply_intent_markers = (
    lambda name, text: CALLS["intent"].append(name) or [])
# The three post-processing extractors hit config/LLM paths this smoke does not
# care about; the gates under test sit after them.
chat_routes._extract_mood = lambda *a, **k: None
chat_routes._extract_location = lambda *a, **k: None
chat_routes._extract_activity = lambda *a, **k: None


class _NoLoop:
    """post_process_response hands the background pass to a thread pool via
    `asyncio.get_event_loop().run_in_executor` and falls back to running it
    INLINE on RuntimeError. Outside a running loop the executor call schedules
    work onto a loop nobody ever runs, so the gates under test would never
    execute. Forcing the documented inline fallback makes the check
    deterministic without changing what it exercises."""
    @staticmethod
    def get_event_loop():
        raise RuntimeError("no running event loop (smoke: force the inline path)")


chat_engine.asyncio = _NoLoop

RESPONSE = ("I pour the beer and slide it over without a word. "
            "[INTENT: keep the taps clean | wipe down the bar | when=standing | prio=3]")

def run_turn(who, context):
    for key in CALLS:
        CALLS[key].clear()
    chat_engine.post_process_response(
        owner_id="demo", character_name=who, user_input="A beer, please.",
        full_response=RESPONSE, agent_config={}, llm=None,
        user_display_name="Alpha", full_chat_history=[],
        extraction_context=context)


# Two turn kinds, because the two gates live on different branches: memory
# extraction only ever runs on a THOUGHT turn (per-turn extraction for real
# chat was retired — chat memories come from scene consolidation), while the
# relationship update explicitly returns early on a thought turn. Running only
# one kind would leave one gate untested and the other trivially "passing".
for who in (NPC, RP):
    expected = who == RP
    run_turn(who, {"source": "thought"})
    check(f"{who}: extraction call (thought turn)", bool(CALLS["extract"]), expected)
    check(f"{who}: intent parse", bool(CALLS["intent"]), expected)
    run_turn(who, None)
    check(f"{who}: relationship call (chat turn)",
          bool(CALLS["relationship"]), expected)
    check(f"{who}: no extraction on a chat turn", bool(CALLS["extract"]), False)

# ---------------------------------------------------------------------------
print("\n[5] Free-text outfit replaces the wardrobe, and only when empty")
from app.core.outfit_renderer import render_outfit  # noqa: E402

npc_profile = get_character_profile(NPC)
rendered = render_outfit(character_name=NPC).get("full", "")
check("NPC outfit text",
      rendered, "wearing: grey linen apron, rolled-up white shirt")

npc_profile["outfit_worn"] = "false"
save_character_profile(NPC, npc_profile)
check("undressed NPC outfit text", render_outfit(character_name=NPC).get("full", ""), "")
npc_profile["outfit_worn"] = "true"
save_character_profile(NPC, npc_profile)
check("dressed again", render_outfit(character_name=NPC).get("full", ""),
      "wearing: grey linen apron, rolled-up white shirt")

# A character WITH pieces: the free text may never outrank a real wardrobe.
from app.models.inventory import add_item  # noqa: E402
item = add_item(name="Silk Blouse", category="outfit_piece",
                prompt_fragment="white silk blouse",
                outfit_piece={"slots": ["top"]})
item_id = item.get("id") or ""
rp_profile = get_character_profile(RP)
rp_profile["equipped_pieces"] = {"top": item_id}
rp_profile["outfit_description"] = "a sack"
save_character_profile(RP, rp_profile)
check("pieces beat the free text",
      "white silk blouse" in render_outfit(character_name=RP).get("full", ""), True)
check("free text stays out when pieces exist",
      "a sack" in render_outfit(character_name=RP).get("full", ""), False)

# ---------------------------------------------------------------------------
print("\n[5a] The free text reaches the COMPOSED image prompt (T-pose)")
# Measured at the consumer: the string handed to the image service, not at
# render_outfit. The gap this closes was exactly that render_outfit was right
# while the render still asked for an undressed figure.
#
# Hand-derived from the two composition sites:
#   model_refs.generate_model_ref_images  — for kind "tpose" the pose text
#     leads as `prompt_prefix` and the pose layer is empty, so the prompt is
#     "<tpose prompt>, <actor>, <appearance>, <outfit>, <expression>";
#   expression_regen.generate_expression_image — the outfit layer of a
#     character with no carried items is `f"{actor_label} is wearing {text}"`,
#     and `actor_label` is the character name (PromptBuilder
#     ._assign_actor_labels sets `person.actor_label = person.name`).
# So the T-pose prompt of this NPC must contain, verbatim:
#     "demo_npc is wearing grey linen apron, rolled-up white shirt"
# and `outfit_worn = "false"` must take the whole "is wearing" clause out
# again — the same binary state section [5] checks on the text itself.
from types import SimpleNamespace  # noqa: E402

import app.imagegen.service as imagegen_service  # noqa: E402
from app.core.model_refs import generate_model_ref_images  # noqa: E402

PROMPTS = []


class _FakeImageService:
    """Captures the composed prompt and answers with a string that carries no
    ``/images/<file>`` — the renderer then returns None without touching the
    filesystem, which is all this check needs."""

    enabled = True
    last_image_meta: dict = {}

    def match_backend(self, glob, has_input_image=False):
        return SimpleNamespace(name="fake-backend")

    def resolve_imagegen_target(self, spec):
        return SimpleNamespace(name="fake-backend")

    def _wait_for_backend(self, character_name, has_input_image=False):
        return SimpleNamespace(name="fake-backend")

    def generate_from_input(self, input_data):
        PROMPTS.append(json.loads(input_data).get("prompt", ""))
        return "no image (smoke stub)"


imagegen_service.get_image_service = lambda: _FakeImageService()

generate_model_ref_images(NPC, kinds=("tpose",))
check("the T-pose render asked for exactly one image", len(PROMPTS), 1)
check("the T-pose prompt dresses the NPC",
      f"{NPC} is wearing grey linen apron, rolled-up white shirt" in PROMPTS[-1],
      True)

npc_profile = get_character_profile(NPC)
npc_profile["outfit_worn"] = "false"
save_character_profile(NPC, npc_profile)
PROMPTS.clear()
generate_model_ref_images(NPC, kinds=("tpose",))
check("an undressed NPC still renders", len(PROMPTS), 1)
check("...and its prompt carries no outfit clause",
      "is wearing" in PROMPTS[-1], False)
npc_profile["outfit_worn"] = "true"
save_character_profile(NPC, npc_profile)

# A character WITH pieces is untouched by the new branch — its wardrobe text
# is what the prompt says.
PROMPTS.clear()
generate_model_ref_images(RP, kinds=("tpose",))
check("a wardrobe character is dressed from its pieces",
      f"{RP} is wearing white silk blouse" in PROMPTS[-1], True)
check("and its free text stays out of the prompt",
      "a sack" in PROMPTS[-1], False)

# ---------------------------------------------------------------------------
print("\n[5b] The render-cache signature follows the free text")
# `current_outfit_state`'s signature is the cache key of BOTH per-outfit
# caches (model_refs/<kind>_<sig>.png and model3d/<sig>.*). Without the free
# text in it, every temporary NPC in the world shares one key, so the first
# NPC's undressed T-pose and mesh would be served to all of them and no
# change of `outfit_description` could ever invalidate them.
#
# THE RULE, by hand: the signature is md5(<raw>)[:12], where <raw> is
#   * the stably sorted equipped state ("<slot>=<item_id>", "|"-joined,
#     `expression_regen._equipped_signature`) whenever anything structured is
#     worn — unchanged, so no existing model of any wardrobe character moves;
#   * otherwise `render_outfit(...)["full"]`, i.e. exactly the string the
#     prompt above is built from ("wearing: <outfit_description>", and ""
#     when `outfit_worn` is false or no text is set).
# Derived values (md5 hex, first 12):
#   md5("")                                             = d41d8cd98f00
#   md5("wearing: grey linen apron, rolled-up white shirt")
#                                                       = 7fb02bc56061
#   md5("wearing: a patched brown cloak")               = e6c864211db0
import hashlib  # noqa: E402

from app.core.model_refs import current_outfit_state  # noqa: E402

EMPTY_SIG = hashlib.md5(b"").hexdigest()[:12]
check("md5('') is the historical empty signature", EMPTY_SIG, "d41d8cd98f00")

sig_apron = current_outfit_state(NPC)[2]
check("the dressed NPC hashes its outfit line", sig_apron,
      hashlib.md5(b"wearing: grey linen apron, rolled-up white shirt"
                  ).hexdigest()[:12])
check("...which is not the empty signature", sig_apron == EMPTY_SIG, False)

npc_profile["outfit_description"] = "a patched brown cloak"
save_character_profile(NPC, npc_profile)
sig_cloak = current_outfit_state(NPC)[2]
check("a different outfit text gives a different signature",
      sig_cloak, hashlib.md5(b"wearing: a patched brown cloak").hexdigest()[:12])
check("...and the two really differ", sig_apron == sig_cloak, False)

npc_profile["outfit_worn"] = "false"
save_character_profile(NPC, npc_profile)
check("an undressed NPC falls back on the empty signature — its prompt has "
      "no outfit either", current_outfit_state(NPC)[2], EMPTY_SIG)
npc_profile["outfit_worn"] = "true"
npc_profile["outfit_description"] = "grey linen apron, rolled-up white shirt"
save_character_profile(NPC, npc_profile)

# A character with NO wardrobe and NO free text keeps the historical key.
check("a bare character keeps md5('')",
      current_outfit_state("demo_no_template")[2], EMPTY_SIG)

# REGRESSION: a character with a structured outfit must keep EXACTLY the
# signature it had before this change — otherwise every 3D model in every
# world loses its cache. Pre-change value, by hand: md5 of the equipped
# signature "top=<item_id>" (one filled slot, no items).
rp_sig_expected = hashlib.md5(f"top={item_id}".encode()).hexdigest()[:12]
check("a wardrobe character's signature is untouched by the free text",
      current_outfit_state(RP)[2], rp_sig_expected)

# ---------------------------------------------------------------------------
print("\n[5c] …and the EXPRESSION variant key follows the same rule")
# The 2D client shows a temporary NPC through one cached expression variant,
# and `expression_regen._cache_key` used to hash the equipped state ALONE
# (`_equipped_signature`) — empty for every temporary NPC in the world. Every
# one of them therefore pointed at the same file name, and editing
# `outfit_description` invalidated nothing. The key now folds in exactly what
# `outfit_signature` folds in: `model_refs.outfit_signature_raw`, the ONE raw
# string both caches hash (no second hash anywhere).
#
# THE RULE, by hand (`expression_regen.py:172-184`): the key is
#   md5(f"{expression_key}:{pose}:{eq}")[:12], prefixed "<safe_name>_"
# with
#   * expression_key = resolve_expression_key(mood); for "" the expression
#     catalog's default entry answers → "neutral";
#   * pose = _canonical_pose_key(pose_key); for "" the pose catalog's default
#     → "standing";
#   * eq = outfit_signature_raw(pieces, items, name) — the equipped state
#     when anything structured is worn, otherwise render_outfit(…)["full"];
#   * no ":state=…" suffix, because no image_modifier directive is active.
from app.core.expression_regen import _cache_key  # noqa: E402

npc_profile["outfit_description"] = "grey linen apron, rolled-up white shirt"
save_character_profile(NPC, npc_profile)
key_apron = _cache_key("", "", NPC, {}, [])
check("the default variant of a piece-less NPC hashes its outfit line",
      key_apron, f"{NPC}_" + hashlib.md5(
          b"neutral:standing:wearing: grey linen apron, "
          b"rolled-up white shirt").hexdigest()[:12])

npc_profile["outfit_description"] = "a patched brown cloak"
save_character_profile(NPC, npc_profile)
key_cloak = _cache_key("", "", NPC, {}, [])
check("a different outfit text gives a different variant key",
      key_cloak, f"{NPC}_" + hashlib.md5(
          b"neutral:standing:wearing: a patched brown cloak"
          ).hexdigest()[:12])
check("...and the two really differ", key_apron == key_cloak, False)
npc_profile["outfit_description"] = "grey linen apron, rolled-up white shirt"
save_character_profile(NPC, npc_profile)

# REGRESSION: a character with a structured outfit keeps EXACTLY the variant
# key it had before this change — the old formula was
# md5(f"{expression_key}:{pose}:{_equipped_signature(pieces, items)}")[:12],
# and for RP the equipped signature is the single filled slot "top=<item_id>".
rp_key_expected = f"{RP}_" + hashlib.md5(
    f"neutral:standing:top={item_id}".encode()).hexdigest()[:12]
check("a wardrobe character's variant key is untouched by the free text",
      _cache_key("", "", RP, {"top": item_id}, []), rp_key_expected)
check("...and the free-text NPC does NOT share the bare-outfit key any more",
      key_apron == f"{NPC}_" + hashlib.md5(
          b"neutral:standing:").hexdigest()[:12], False)

# ---------------------------------------------------------------------------
print("\n[6] TTL is measured in GAME seconds")
from app.core.npc_ops import expiry_stamp, is_expired  # noqa: E402

now = game_time()
stamp = expiry_stamp(2)
delta = GameTime.parse(stamp) - now
# 2 game hours = 7200 game seconds. The clock advances between the two reads,
# so allow one second of drift and nothing more.
check("2h TTL is 7200 game seconds", round(delta.seconds) in (7199, 7200, 7201), True)
check("no TTL", expiry_stamp(None), "")
check("zero TTL", expiry_stamp(0), "")
check("negative TTL", expiry_stamp(-5), "")
check("garbage TTL", expiry_stamp("soon"), "")
check("future stamp is not expired", is_expired(stamp), False)
check("past stamp is expired",
      is_expired((now - GameDuration.of(hours=1)).canonical()), True)
check("empty stamp is never expired", is_expired(""), False)
check("garbage stamp is never expired", is_expired("whenever"), False)

# ---------------------------------------------------------------------------
print("\n[7] The sweep takes exactly the expired NPC out of the world")
from app.core.npc_ops import sweep_expired_npcs  # noqa: E402

expired = (game_time() - GameDuration.of(hours=1)).canonical()
future = (game_time() + GameDuration.of(hours=10)).canonical()

npc_profile = get_character_profile(NPC)
npc_profile["expires_at"] = expired
save_character_profile(NPC, npc_profile)

make_character(NPC_ALIVE, "npc-temporary", expires_at=future,
               character_personality="Quiet.", standing_task="sweeps the steps")
rp_profile = get_character_profile(RP)
rp_profile["expires_at"] = expired          # meaningless on a normal character
save_character_profile(RP, rp_profile)

check("temporary NPCs found", sorted(list_temporary_npcs()), sorted([NPC, NPC_ALIVE]))
before_names = set(list_available_characters())
removed = sweep_expired_npcs()
after_names = set(list_available_characters())
check("sweep removed", removed, 1)
check("exactly one character gone", before_names - after_names, {NPC})
check("the future NPC survives", NPC_ALIVE in after_names, True)
check("the normal character survives its stale stamp", RP in after_names, True)

# ---------------------------------------------------------------------------
print("\n[8] Trace cleanup deletes what others remembered ABOUT the NPC")
from app.core.memory_service import cleanup_npc_traces  # noqa: E402

TRACE_NPC = "demo_npc_maren"
OBSERVER = "demo_observer"
make_character(TRACE_NPC, "npc-temporary", character_personality="Dry.",
               standing_task="tends the bar")
make_character(OBSERVER, "human-roleplay", character_personality="Attentive.")

add_memory(OBSERVER, "We talked for a while.", memory_type="episodic",
           related_character=TRACE_NPC)
add_memory(OBSERVER, f"{TRACE_NPC} poured the wine.", memory_type="episodic")
add_memory(OBSERVER, LOOKALIKE_TEXT, memory_type="episodic")
add_memory(OBSERVER, "The rain stopped around noon.", memory_type="episodic")
with db.transaction() as conn:
    conn.execute(
        "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
        "VALUES (?,?,?,?,?)",
        (OBSERVER, "daily", "Y0001-D001", TRACE_NPC, "A long talk at the bar."))
    conn.execute(
        "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
        "VALUES (?,?,?,?,?)",
        (OBSERVER, "daily", "Y0001-D001", "",
         f"Rain all morning. {TRACE_NPC} poured the wine."))

check("observer memories before", count_memories(OBSERVER), 4)
result = cleanup_npc_traces(TRACE_NPC)
check("memories deleted", result["memories"], 2)
check("partner summaries deleted", result["summaries"], 1)

conn = db.get_connection()
left = [r[0] for r in conn.execute(
    "SELECT content FROM memories WHERE character_name=? ORDER BY id",
    (OBSERVER,)).fetchall()]
check("lookalike survives", LOOKALIKE_TEXT in left, True)
check("unrelated memory survives", "The rain stopped around noon." in left, True)
check("nothing else survives", len(left), 2)
day_rows = conn.execute(
    "SELECT content FROM summaries WHERE character_name=?", (OBSERVER,)).fetchall()
check("the day summary that merely mentions the name survives", len(day_rows), 1)
check("and it still names the NPC", TRACE_NPC in day_rows[0][0], True)

# The delete path wires it up: deleting the NPC runs the cleanup by itself.
add_memory(OBSERVER, f"{TRACE_NPC} nodded goodbye.", memory_type="episodic")
check("re-seeded trace", count_memories(OBSERVER), 3)
delete_character(TRACE_NPC)
check("delete_character swept the trace", count_memories(OBSERVER), 2)

# ---------------------------------------------------------------------------
print("\n[9] The generation schema comes out fully resolved")
# `_load_schema` substitutes by plain str.replace and leaves an unknown
# placeholder standing as literal `{name}` — the LLM would then be told to fill
# a field list that reads "{generable_fields}". A leftover brace is therefore a
# hard failure, not cosmetics. (`{` inside the JSON examples is fine; the check
# looks only for the `{lower_snake_case}` placeholder shape.)
import re as _re  # noqa: E402
from app.core.npc_ops import build_npc_schema_text, npc_generable_fields  # noqa: E402

schema = build_npc_schema_text("cafe", "back_room")
leftovers = sorted(set(_re.findall(r"\{[a-z_][a-z0-9_]*\}", schema)))
check("no unresolved placeholders", leftovers, [])
check("the field list is in there", "`standing_task`" in schema, True)
check("outfit_description is offered", "`outfit_description`" in schema, True)
# The list is derived from the template, so a field added to the JSON reaches
# the prompt without a code change — that is what makes a second NPC kind a
# template variant rather than a new code path.
fields = npc_generable_fields()
for key in ("character_name", "language", "character_personality",
            "character_appearance", "standing_task", "dialogue_style",
            "arrival_reason", "npc_goals", "outfit_description",
            "face_appearance", "gender", "age", "height"):
    check(f"generable field {key}", f"`{key}`" in fields, True)
# Fields the LLM must NOT set stay out of the list.
for key in ("expires_at", "npc_briefing", "outfit_worn", "roleplay_instructions"):
    check(f"{key} is not offered to the LLM", f"`{key}`" in fields, False)

# ---------------------------------------------------------------------------
print("\n[10] Local field validation")
from app.core.npc_ops import validate_npc_fields  # noqa: E402

complete = {"character_name": "Maren Kolb",
            "language": "en",
            "character_personality": "Dry, economical with words.",
            "character_appearance": "woman, 50s, close-cropped grey hair",
            "standing_task": "tends the bar",
            # REQUIRED since the finish gate (plan-npc-leben § 0 A): the free
            # text IS this character's wardrobe, and every image prompt of a
            # temporary NPC dresses it from here.
            "outfit_description": "a rolled-up white shirt, dark apron"}
check("a complete NPC has no gaps", validate_npc_fields(complete), [])
check("a missing name is a gap",
      any("character_name" in g for g in validate_npc_fields({})), True)
check("a missing standing task is a gap",
      any("standing_task" in g for g in
          validate_npc_fields({**complete, "standing_task": ""})), True)
check("an outfits array is a gap",
      any("outfits" in g for g in
          validate_npc_fields({**complete, "outfits": [{"name": "x"}]})), True)
check("a soul document is a gap",
      any("character_soul" in g for g in
          validate_npc_fields({**complete, "character_soul": "# Soul"})), True)
check("a markdown personality is a gap",
      any("plain prose" in g for g in
          validate_npc_fields({**complete,
                               "character_personality": "# Personality\n\ndry"})), True)

# ---------------------------------------------------------------------------
print("\n[11] The pipeline end to end, against a stubbed LLM")
# The LLM is the only thing stubbed: the schema build, the fence extraction,
# both validation passes, the repair turn and the real apply all run. The first
# answer deliberately omits `standing_task`, so this also proves the repair
# stage is what rescues it — with a one-shot generator that is the difference
# between a usable NPC and a rejected run.
import asyncio  # noqa: E402
import app.core.npc_ops as npc_ops  # noqa: E402

DRAFT = """Here you go.

```json:npc
{"character_name": "Maren Kolb", "language": "en",
 "character_personality": "Dry, economical with words, sizes up every newcomer.",
 "character_appearance": "woman, 50s, heavy-set, close-cropped grey hair",
 "face_appearance": "square face, weathered skin, grey eyes",
 "outfit_description": "grey linen apron over a rolled-up white shirt, dark trousers",
 "dialogue_style": "short, dry sentences", "arrival_reason": "She has run this bar for thirty years.",
 "npc_goals": "get through the shift", "gender": "female", "age": 54, "height": 168,
 "standing_task": ""}
```"""
REPAIRED = DRAFT.replace('"standing_task": ""', '"standing_task": "tends the bar"')

TURNS = []


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """Answers the generate turn with the incomplete draft and every later
    turn with the repaired one. The validator LLM gets its own instance that
    reports no findings, so the ONLY gap is the local one."""

    def __init__(self, answers):
        self._answers = list(answers)

    async def astream(self, messages):
        TURNS.append(messages[0]["content"][:40])
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        for piece in (answer[i:i + 64] for i in range(0, len(answer), 64)):
            yield _Chunk(piece)


def _fake_make_llm(model, provider, max_tokens):
    # 1024 max_tokens is the validator's signature (npc_ops._run_pipeline).
    if max_tokens == 1024:
        return _FakeLLM(["OK"]), object()
    return _FakeLLM([DRAFT, REPAIRED]), object()


npc_ops._make_llm = _fake_make_llm


async def _drive():
    return [f async for f in npc_ops.generate_npc(
        briefing="a weary barkeeper", location_id="cafe", room_id="",
        ttl_hours=3, model="fake-model", provider="fake", created_by="demo")]


frames = asyncio.run(_drive())
by_stage = {}
for f in frames:
    by_stage.setdefault(f.get("stage"), []).append(f)

check("all four stages reported", sorted(by_stage), ["apply", "generate", "repair", "validate"])
# Exactly three LLM turns: generate, validate, repair. Four would mean the
# repair turn ran twice; two would mean the validator never got asked.
check("three LLM turns", len(TURNS), 3)
check("no frame carries an error", [f for f in frames if f.get("error")], [])
check("generate produced a draft",
      by_stage["generate"][-1]["character_data"]["character_name"], "Maren Kolb")
check("validate found the missing standing task",
      any("standing_task" in g for g in by_stage["validate"][-1]["gaps"]), True)
check("repair ran", by_stage["repair"][-1]["status"], "done")
check("apply succeeded", by_stage["apply"][-1]["status"], "done")

created = by_stage["apply"][-1]["applied"]["character"]
check("the NPC exists", created in list_available_characters(), True)
check("it carries the NPC template", is_temporary_npc(created), True)
profile = get_character_profile(created)
check("template pinned", profile.get("template"), "npc-temporary")
check("the repaired standing task landed", profile.get("standing_task"), "tends the bar")
# The standing task IS the activity baseline — one field, two consumers.
check("standing task became the activity", profile.get("current_activity"), "tends the bar")
check("briefing recorded", profile.get("npc_briefing"), "a weary barkeeper")
check("placed at the location", profile.get("current_location"), "cafe")
check("outfit is prompt text, not pieces",
      render_outfit(character_name=created).get("full", ""),
      "wearing: grey linen apron over a rolled-up white shirt, dark trousers")
check("no wardrobe pieces", profile.get("equipped_pieces") or {}, {})
# 3 game hours of TTL, and the NPC is not expired yet.
ttl_delta = GameTime.parse(profile["expires_at"]) - game_time()
check("TTL is 3 game hours", round(ttl_delta.seconds) in (10799, 10800, 10801), True)
check("not expired yet", is_expired(profile["expires_at"]), False)
# And it remembers nothing, through the same central gate as section [2].
add_memory(created, "A customer complained about the beer.", memory_type="episodic")
check("the generated NPC remembers nothing", count_memories(created), 0)

# The whole point of "the standing task is a TEMPLATE FIELD": the chat prompt
# renders it with no code that knows what an NPC is. Same call as
# routes/chat.py:2304, so this is the production shape.
from app.models.character_template import (  # noqa: E402
    build_prompt_section, get_template)

tmpl = get_template("npc-temporary")
lines = build_prompt_section(tmpl, get_character_profile(created),
                             active_features=tmpl.get("features") or {},
                             character_name=created)
joined = "\n".join(lines)
check("chat prompt renders the standing task",
      "Your standing task: tends the bar" in joined, True)
check("chat prompt renders the dialogue style",
      "How you speak: short, dry sentences" in joined, True)
check("chat prompt renders why they are here", "Why you are here:" in joined, True)
check("chat prompt renders the roleplay anchor", "Important rules:" in joined, True)
# Switched-off features must not leak their fields into the prompt.
check("no mood line (mood_tracking_enabled off)",
      "Current feeling" in joined, False)
check("no soul line (soul_enabled off)", "Soul:" in joined, False)

# The list the Game-Admin NPC group renders. Checked because it formats the
# expiry twice (raw stamp + human label) and a bad stamp would raise.
from app.core.npc_ops import list_npcs  # noqa: E402

rows = {r["name"]: r for r in list_npcs()}
check("the generated NPC is listed", created in rows, True)
row = rows.get(created, {})
check("row carries the standing task", row.get("standing_task"), "tends the bar")
check("row carries the template", row.get("template"), "npc-temporary")
check("row is not expired", row.get("expired"), False)
check("row has a human expiry label", bool(row.get("expires_label")), True)
# An NPC without a TTL must render an empty label, not crash on the parse.
save_character_profile(NPC_ALIVE, {**get_character_profile(NPC_ALIVE),
                                   "expires_at": ""})
rows = {r["name"]: r for r in list_npcs()}
check("no-TTL NPC has an empty label", rows[NPC_ALIVE]["expires_label"], "")
check("no-TTL NPC is never expired", rows[NPC_ALIVE]["expired"], False)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
