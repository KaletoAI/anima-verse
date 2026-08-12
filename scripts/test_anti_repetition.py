#!/usr/bin/env python3
"""Check for the anti-repetition net (task A1.4).

Usage:
    ./.venv/bin/python scripts/test_anti_repetition.py

Runs without a server, without a world DB and without network. Exit 0 = all
green, exit 1 = at least one case failed (the failing line names the case, the
expectation and what came out).

Covers the three defects fixed in A1:
  1. the dedup also acts on the room-mode message list (chat_engine),
  2. the thought path gets the same reactive bump (thoughts),
  3. the counter also sees LATE repetitions — a verbatim sentence in otherwise
     new text (history_manager).

Case 9 covers the A2 rebuild: the reactive bump raises the repetition PENALTY
instead of the temperature, and `chat.top_p` clamps the tail. Background: at a
reactively raised temperature of 1.10, two of two replies of one model
collapsed into multi-script token salad, against zero of 26 at its configured
0.80 in the same window — and the client sent no nucleus cut-off at all, so the
whole distribution tail was open.

All expected numbers are derived by hand in the case comments, from the values
pinned in `_pin_config()`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config  # noqa: E402
from app.core.chat_engine import (  # noqa: E402
    _messages_from_room_stream, dedupe_assistant_repeats)
from app.utils.history_manager import (  # noqa: E402
    anti_repetition_overrides, count_assistant_repetitions, fuzzy_signature,
    repetition_keys)

FAILURES = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = ""):
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: {detail}")
        FAILURES.append(name)


def _pin_config():
    """Pin the four anti-rep config values so the expected numbers hold.

    The check must not depend on whatever world config happens to be on disk;
    these are the schema defaults from config_schema.py.
    """
    config._CONFIG = {
        "chat": {
            "frequency_penalty": 0.3,
            # The temperature bump is OFF in the schema since 2026-08-03; it is
            # pinned ON here so the legacy branch keeps being covered. The
            # cases below that assert the DEFAULT behaviour set it to 0
            # themselves.
            "anti_rep_step": 0.1,
            "anti_rep_max": 1.2,
            "anti_rep_lookback": 6,
            "anti_rep_penalty_step": 0.15,
            "anti_rep_penalty_max": 1.0,
            "top_p": 0,
        }
    }


def msgs(*contents):
    """Assistant-only message list in chat order (oldest first)."""
    return [{"role": "assistant", "content": c} for c in contents]


# --- test material -----------------------------------------------------------
# The shared sentence has 65 normalized characters (Der3 Marktplatz10 liegt5
# still5 und3 verlassen9 unter5 dem3 grauen6 Himmel6 von3 Norwich7) and thus
# clears the 60-character threshold — but only just, so the case really tests
# the threshold and not a wall of text.
SHARED = ("Der Marktplatz liegt still und verlassen unter dem grauen "
          "Himmel von Norwich.")
LATE_A = "Ich trete an das Fenster und sehe hinaus in den Regen. " + SHARED
LATE_B = "Ein kalter Windstoss faehrt mir durch das Haar. " + SHARED
OTHER = ("Der Schmied haemmert auf das gluehende Eisen, Funken springen "
         "ueber den Amboss. Ich zaehle die Muenzen in meiner Tasche noch "
         "einmal durch.")
OTHER2 = ("Am Brunnen schoepfe ich Wasser und trinke in langen Zuegen. "
          "Die Sonne steht schon tief zwischen den Daechern.")


def case_1_late_repetition():
    """Two replies with different opening sentences but a verbatim sentence
    after it → one repetition. Exactly the case that used to slip through."""
    print("1. detector sees late repetitions")
    # Hand-derived: the opening signatures differ ("ichtretean…" vs
    # "einkalterwind…"), so the old 60-char opening key found 0.
    check("opening signatures differ (old key would miss it)",
          fuzzy_signature(LATE_A) != fuzzy_signature(LATE_B),
          f"{fuzzy_signature(LATE_A)!r} == {fuzzy_signature(LATE_B)!r}")
    shared_keys = repetition_keys(LATE_A) & repetition_keys(LATE_B)
    check("the verbatim sentence is a shared key", len(shared_keys) == 1,
          f"expected 1 shared key, got {len(shared_keys)}: {shared_keys}")
    n = count_assistant_repetitions(msgs(LATE_A, LATE_B))
    check("counted as 1 repetition", n == 1, f"expected 1, got {n}")


def case_2_no_false_positive():
    """Two entirely different replies → 0."""
    print("2. different replies are not a repetition")
    n = count_assistant_repetitions(msgs(LATE_A, OTHER))
    check("different replies → 0", n == 0, f"expected 0, got {n}")
    n = count_assistant_repetitions(msgs(LATE_A, OTHER, OTHER2))
    check("three different replies → 0", n == 0, f"expected 0, got {n}")


def case_3_identical_replies():
    """Regression of the old behaviour: identical replies still count."""
    print("3. identical replies still count")
    n = count_assistant_repetitions(msgs(LATE_A, LATE_A))
    check("identical replies → 1", n == 1, f"expected 1, got {n}")
    # A short reply has no sentence >= 60 chars — the opening signature has to
    # carry it, otherwise short loops would go unnoticed.
    n = count_assistant_repetitions(msgs("Ich nicke stumm.", "Ich nicke stumm."))
    check("identical SHORT replies → 1", n == 1, f"expected 1, got {n}")


def case_4_counter_scales():
    """The counter is a count, not a flag."""
    print("4. counter rises with the number of repetitions")
    # A A A B → the 2nd and the 3rd repeat something already seen = 2.
    n = count_assistant_repetitions(msgs(LATE_A, LATE_A, LATE_A, OTHER))
    check("A A A B → 2", n == 2, f"expected 2, got {n}")
    # A B A B → the 3rd repeats A, the 4th repeats B = 2.
    n = count_assistant_repetitions(msgs(LATE_A, OTHER, LATE_A, OTHER))
    check("A B A B → 2", n == 2, f"expected 2, got {n}")
    # Lookback 2 only looks at the last two entries: A | A B → 0.
    n = count_assistant_repetitions(msgs(LATE_A, LATE_A, OTHER), lookback=2)
    check("lookback 2 ignores what fell out of the window", n == 0,
          f"expected 0, got {n}")
    # Mixed roles: user lines are ignored, only assistant lines count.
    mixed = [{"role": "user", "content": "Was siehst du?"},
             {"role": "assistant", "content": LATE_A},
             {"role": "user", "content": "Und jetzt?"},
             {"role": "assistant", "content": LATE_B}]
    n = count_assistant_repetitions(mixed)
    check("user lines do not disturb the count", n == 1, f"expected 1, got {n}")


def case_5_dedup_in_room_mode():
    """The dedup acts on the list the caller really sends — the room stream."""
    print("5. dedup acts in room mode")
    stream = [
        {"speaker": "Mira", "content": LATE_A},
        {"speaker": "Tomas", "content": "Und was machen wir jetzt?"},
        {"speaker": "Mira", "content": LATE_A},
        {"speaker": "Tomas", "content": "Mira? Hoerst du mich?"},
    ]
    built = _messages_from_room_stream("Mira", stream)
    check("room stream builds 4 messages", len(built) == 4,
          f"expected 4, got {len(built)}")
    final = dedupe_assistant_repeats(built, drop_preceding_user=False)
    # Hand-derived: Mira's second, identical utterance goes → 3 messages left.
    check("the duplicated own utterance is gone", len(final) == 3,
          f"expected 3 messages, got {len(final)}: {final}")
    own = [m for m in final if m["role"] == "assistant"]
    check("exactly one own utterance remains", len(own) == 1,
          f"expected 1, got {len(own)}")

    # …and the caller really uses that list. build_chat_context cannot run here
    # (world DB, LLM router, system prompt), so this is checked on the source:
    # the dedup has to come AFTER the room-mode replacement, otherwise its work
    # is thrown away again — that was the defect.
    import inspect
    from app.core.chat_engine import build_chat_context
    src = inspect.getsource(build_chat_context)
    i_room = src.find("_messages_from_room_stream(")
    i_dedup = src.find("dedupe_assistant_repeats(")
    check("build_chat_context dedupes after the room-mode replacement",
          i_room != -1 and i_dedup != -1 and i_room < i_dedup,
          f"room-stream at {i_room}, dedup at {i_dedup}")


def case_6_foreign_line_survives():
    """No foreign utterance is dropped because my own reply repeated."""
    print("6. dedup does not delete a foreign utterance")
    stream = [
        {"speaker": "Mira", "content": LATE_A},
        {"speaker": "Tomas", "content": "Ich habe den Reiter kommen sehen."},
        {"speaker": "Mira", "content": LATE_A},
    ]
    built = _messages_from_room_stream("Mira", stream)
    final = dedupe_assistant_repeats(built, drop_preceding_user=False)
    kept = [m["content"] for m in final if m["role"] == "user"]
    check("Tomas' line is still there", kept == ["Tomas: Ich habe den Reiter kommen sehen."],
          f"got {kept}")
    # Counter-check that the flag is what does it: with the 1:1 rule the
    # foreign line would go with the duplicate.
    pairwise = dedupe_assistant_repeats(built, drop_preceding_user=True)
    check("with drop_preceding_user=True the line would be dropped "
          "(1:1 history rule)",
          [m for m in pairwise if m["role"] == "user"] == [],
          f"got {pairwise}")


def case_6b_dedup_key_stays_narrow():
    """The dedup key must NOT get as wide as the counter — a wrongly matched
    message is DELETED, and that costs real context."""
    print("6b. dedup key stays narrow")
    built = [{"role": "assistant", "content": LATE_A},
             {"role": "assistant", "content": LATE_B}]
    final = dedupe_assistant_repeats(built, drop_preceding_user=False)
    check("a mere shared sentence does not delete a message",
          len(final) == 2, f"expected 2 messages, got {len(final)}")
    check("but the counter does see it",
          count_assistant_repetitions(built) == 1,
          "counter should count the pair as 1 repetition")


def case_7_thought_path_bump():
    """The thought path raises the temperature and honours the ceiling."""
    print("7. thought path raises the temperature")
    import inspect
    from app.models import thought_store
    from app.core import thoughts as thoughts_mod

    if not hasattr(thoughts_mod, "thought_anti_repetition_overrides"):
        check("thought path has an anti-repetition entry point", False,
              "app.core.thoughts.thought_anti_repetition_overrides is missing")
        return
    # The turn itself cannot run here (LLM, tools, DB) — so this checks that the
    # entry point is actually wired into run_thought_turn instead of only
    # existing.
    turn_src = inspect.getsource(thoughts_mod.ThoughtRunner.run_thought_turn)
    check("run_thought_turn calls the anti-repetition entry point",
          "thought_anti_repetition_overrides(" in turn_src,
          "run_thought_turn does not use thought_anti_repetition_overrides")

    journal = []

    def fake_list_thoughts(character_name, limit=50, before=None):
        # Same contract as the real one: newest first, capped at limit.
        return [{"content": c} for c in journal[::-1]][:limit]

    original = thought_store.list_thoughts
    thought_store.list_thoughts = fake_list_thoughts
    try:
        # Empty journal → nothing to do.
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("empty journal → no override", ov == {}, f"got {ov}")

        # Three entries that repeat the shared sentence: entries 2 and 3 each
        # repeat something seen before → 2 repetitions.
        # Hand-derived: 0.70 + 2 * 0.10 = 0.90, below the 1.2 ceiling.
        journal[:] = [LATE_A, LATE_B, LATE_B]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("2 repetitions → temperature 0.90",
              abs(ov.get("temperature", 0) - 0.9) < 1e-9, f"got {ov}")
        # The reactive bump IS a penalty since 2026-08-03, and it crosses over
        # to the thought path — but starting from 0, because the STATIC
        # chat.frequency_penalty stays a chat-reply value.
        # Hand-derived: 0 + 2 * 0.15 = 0.30.
        check("thought path penalty 0 + 2×0.15 → 0.30",
              abs(ov.get("frequency_penalty", -1) - 0.3) < 1e-9, f"got {ov}")

        # Same 2 repetitions on a hot base: 1.15 + 0.20 = 1.35 → capped at 1.2.
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 1.15)
        check("ceiling anti_rep_max holds",
              abs(ov.get("temperature", 0) - 1.2) < 1e-9, f"got {ov}")

        # A journal without repetitions leaves the instance alone.
        journal[:] = [LATE_A, OTHER, OTHER2]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("journal without repetition → no override", ov == {}, f"got {ov}")

        # Lookback 6: seven entries, the repeat sits in position 1 and falls
        # out of the window → no bump.
        journal[:] = [LATE_A, OTHER, OTHER2, "Eins.", "Zwei.", "Drei.", "Vier."]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("lookback window limits the journal read", ov == {}, f"got {ov}")
    finally:
        thought_store.list_thoughts = original

    # On the chat path the reactive penalty sits ON TOP of the static one.
    # Hand-derived: 0.30 static + 1 * 0.15 = 0.45.
    ov = anti_repetition_overrides(msgs(LATE_A, LATE_B), 0.7, agent_name="Demo")
    check("chat path penalty 0.3 + 1×0.15 → 0.45",
          abs(ov.get("frequency_penalty", 0) - 0.45) < 1e-9, f"got {ov}")
    check("chat path bumps by 1 repetition → 0.80",
          abs(ov.get("temperature", 0) - 0.8) < 1e-9, f"got {ov}")

    # Without a repetition the static penalty must stay exactly as configured —
    # the reactive part adds nothing.
    ov = anti_repetition_overrides(msgs(LATE_A, OTHER), 0.7, agent_name="Demo")
    check("no repetition → static penalty 0.3 untouched",
          ov == {"frequency_penalty": 0.3}, f"got {ov}")


def case_9_sampler_clamp():
    """The nucleus clamp and the new default: penalty instead of temperature."""
    print("9. sampler clamp and the new default")
    _pin_config()

    # top_p = 0 means "do not send it": a provider whose default differs from
    # 1.0 must keep its own. Sending 1.0 would be a silent behaviour change.
    ov = anti_repetition_overrides(msgs(LATE_A, LATE_B), 0.7, agent_name="Demo")
    check("top_p absent when 0", "top_p" not in ov, f"got {ov}")

    config._CONFIG["chat"]["top_p"] = 0.95
    ov = anti_repetition_overrides(msgs(LATE_A, OTHER), 0.7, agent_name="Demo")
    check("top_p sent when configured", ov.get("top_p") == 0.95, f"got {ov}")

    # The shipped default: temperature bump off, penalty bump on.
    # Hand-derived: 1 repetition → 0.30 + 0.15 = 0.45, no temperature key.
    config._CONFIG["chat"]["anti_rep_step"] = 0
    ov = anti_repetition_overrides(msgs(LATE_A, LATE_B), 0.7, agent_name="Demo")
    check("default: no temperature key", "temperature" not in ov, f"got {ov}")
    check("default: penalty 0.45",
          abs(ov.get("frequency_penalty", 0) - 0.45) < 1e-9, f"got {ov}")

    # The penalty ceiling binds: 0.30 + 1 * 5.0 = 5.30 → capped at 1.0.
    config._CONFIG["chat"]["anti_rep_penalty_step"] = 5.0
    ov = anti_repetition_overrides(msgs(LATE_A, LATE_B), 0.7, agent_name="Demo")
    check("penalty ceiling holds", ov.get("frequency_penalty") == 1.0, f"got {ov}")

    # Both steps at 0 = the net is off; only the standing values remain.
    config._CONFIG["chat"]["anti_rep_penalty_step"] = 0
    ov = anti_repetition_overrides(msgs(LATE_A, LATE_B), 0.7, agent_name="Demo")
    check("both steps 0 → no reactive change",
          ov == {"frequency_penalty": 0.3, "top_p": 0.95}, f"got {ov}")

    # The client sends top_p only when it was set.
    from app.core.llm_client import LLMClient
    plain = LLMClient(model="m", api_key="k", api_base="http://localhost",
                      temperature=0.8)
    check("client omits top_p by default",
          "top_p" not in plain._build_kwargs(), f"got {plain._build_kwargs()}")
    clamped = LLMClient(model="m", api_key="k", api_base="http://localhost",
                        temperature=0.8, top_p=0.95, frequency_penalty=0.3)
    kw = clamped._build_kwargs()
    check("client sends top_p when set", kw.get("top_p") == 0.95, f"got {kw}")
    check("client still sends frequency_penalty",
          kw.get("frequency_penalty") == 0.3, f"got {kw}")
    _pin_config()


def case_8_degenerate_input():
    """Empty / short / broken input must not crash and must count 0."""
    print("8. degenerate input")
    for label, data in [("no messages", []),
                        ("single entry", msgs(LATE_A)),
                        ("empty strings", msgs("", "")),
                        ("whitespace only", msgs("   ", "\n\n")),
                        ("only user lines", [{"role": "user", "content": LATE_A}] * 3),
                        ("missing keys", [{}, {"role": "assistant"}])]:
        try:
            n = count_assistant_repetitions(data)
        except Exception as e:  # noqa: BLE001 — the whole point is "no crash"
            check(f"{label} → no crash", False, f"raised {e!r}")
            continue
        check(f"{label} → 0", n == 0, f"expected 0, got {n}")

    check("repetition_keys('') → empty set", repetition_keys("") == set())
    check("dedup of an empty list → empty list",
          dedupe_assistant_repeats([]) == [])
    check("room stream without content → no messages",
          _messages_from_room_stream("Mira", [{"speaker": "Mira", "content": ""}]) == [])


def case_10_repetition_age_window():
    """Old journal entries stop driving the bump (chat.anti_rep_max_age_hours).

    The measured problem: on 2026-08-02 the duplicates that triggered a bump
    were 1.2 to 91.6 game hours old (median 49). "The last six turns" spans
    days on the thought path, so the same two-day-old pair penalised every
    single turn. Hand-derived expectations below use a fixed fake clock.
    """
    print("10. repetition age window")
    from datetime import datetime, timedelta, timezone
    from app.models import thought_store
    from app.core import thoughts as thoughts_mod
    from app.core import timeutils

    _pin_config()
    config._CONFIG["chat"]["anti_rep_step"] = 0        # shipped default
    config._CONFIG["chat"]["anti_rep_max_age_hours"] = 12

    NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    journal = []  # (content, age_in_hours)

    def fake_list_thoughts(character_name, limit=50, before=None):
        return [{"content": c,
                 "game_ts": (NOW - timedelta(hours=age)).isoformat()}
                for c, age in journal[::-1]][:limit]

    orig_list, orig_now = thought_store.list_thoughts, timeutils.game_now
    thought_store.list_thoughts = fake_list_thoughts
    timeutils.game_now = lambda: NOW
    try:
        # Two repetitions, but all three entries are 49 h old → window drops
        # every one of them → nothing left to compare → no override at all.
        journal[:] = [(LATE_A, 49), (LATE_B, 49), (LATE_B, 49)]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("49 h old duplicates no longer count", ov == {}, f"got {ov}")

        # Same entries, 2 h old → 2 repetitions → 0 + 2 * 0.15 = 0.30.
        journal[:] = [(LATE_A, 2), (LATE_B, 2), (LATE_B, 2)]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("fresh duplicates still count → penalty 0.30",
              abs(ov.get("frequency_penalty", 0) - 0.3) < 1e-9, f"got {ov}")

        # Mixed: the duplicate pair is old, only an unrelated fresh entry
        # survives the window → a single entry cannot repeat anything.
        journal[:] = [(LATE_A, 49), (LATE_B, 49), (OTHER, 1)]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("only the fresh entry survives → no bump", ov == {}, f"got {ov}")

        # Age limit off → the old pair counts again (previous behaviour).
        config._CONFIG["chat"]["anti_rep_max_age_hours"] = 0
        journal[:] = [(LATE_A, 49), (LATE_B, 49), (LATE_B, 49)]
        ov = thoughts_mod.thought_anti_repetition_overrides("Demo", 0.7)
        check("age limit 0 → old duplicates count again",
              abs(ov.get("frequency_penalty", 0) - 0.3) < 1e-9, f"got {ov}")
    finally:
        thought_store.list_thoughts = orig_list
        timeutils.game_now = orig_now
        _pin_config()


def main() -> int:
    _pin_config()
    for fn in (case_1_late_repetition, case_2_no_false_positive,
               case_3_identical_replies, case_4_counter_scales,
               case_5_dedup_in_room_mode, case_6_foreign_line_survives,
               case_6b_dedup_key_stays_narrow, case_7_thought_path_bump,
               case_8_degenerate_input, case_9_sampler_clamp,
               case_10_repetition_age_window):
        fn()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} of {CHECKS} checks — {', '.join(FAILURES)}")
        return 1
    print(f"OK: {CHECKS} checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
