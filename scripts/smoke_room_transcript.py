#!/usr/bin/env python3
"""Smoke run for the addressee in the room transcript (T5 of
plan-gespraechs-auswahl.md § 3.4).

Pure: no world, no DB, no LLM. Exercised are the pure renderer
``chat_engine._messages_from_room_stream`` and the room branch of the chat
prompt — its rules in ``chat/chat_stream.md``, the per-turn addressee
sentence in ``chat/chat_moment.md``.

Every expectation is derived BY HAND from the rule in § 3.4, not recorded
from an implementation run. The responder is "Rosi" throughout.

Transcript rule: a row is dropped when it has no content or its kind is
``whisper_meta``. The speaker is ``row["speaker"]`` or, missing that,
``row["meta"]["speaker"]``. A row whose speaker IS the responder becomes
role "assistant" with the bare content (no prefix). Every other row becomes
role "user" with the prefix ``<speaker>``, extended by ``(to <list>)`` when
``meta.addressees`` is non-empty; inside that list the responder's own name
is replaced by "you" while the original order is kept.

  [1] Kai, no addressees                -> "Kai: Hallo"
  [2] Kai, addressees ["Liesa"]         -> "Kai (to Liesa): Hallo"
  [3] Kai, addressees ["Rosi"]          -> "Kai (to you): Hallo"
  [4] Kai, addressees ["Rosi", "Karl"]  -> "Kai (to you, Karl): Hallo"
      Kai, addressees ["Karl", "Rosi"]  -> "Kai (to Karl, you): Hallo"
      (order kept: only the responder's name is swapped for "you")
  [5] Rosi (the responder) speaks       -> role "assistant", "Hallo" unchanged
  [6] kind "whisper_meta"               -> no message at all
  [7] speaker only in meta              -> "Kai (to you): Hallo" (same as [3])

Template render [8]-[10] (chat/chat_moment.md, StrictUndefined): the room
branch reads, by hand,

    {% if partner_name and addressed_to_me %}... spoke to YOU directly ...
    {% elif partner_name and addressed_names %}... was speaking to
        {{ addressed_names }}, not to you ...
    {% elif partner_name %}... said that to the room, to nobody in
        particular ... this time it is you ...
    {% endif %}

so with partner_name "Kai":

  [8]  addressed_to_me True                       -> "Kai spoke to YOU directly",
       and the bystander sentence ("not to you") must NOT appear
  [9]  addressed_to_me False, addressed_names "Liesa"
                                                  -> "Kai was speaking to Liesa, not to you"
  [10] addressed_to_me False, addressed_names ""  -> "Kai said that to the room",
       and neither "not to you" nor "spoke to YOU directly" appears (a
       room-wide line is an invitation, not somebody else's conversation)
  [11] the anti-echo paragraph ("Lines with a speaker name in front were said
       by OTHER people.") sits outside the if/elif, so it must appear in all
       three renders

The render context comes from ``jinja2.meta.find_undeclared_variables`` (every
variable the template mentions) filled with "" — under StrictUndefined a
forgotten variable raises, which is exactly what this guards. partner_mode
"room" + present_characters + character_name pick the room branch, so the
render is not an empty shell.

Usage:  ./.venv/bin/python scripts/smoke_room_transcript.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root and the clip library MUST be redirected BEFORE the first
# app import: an app model reaches its world.db through paths, and without a
# storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="room-transcript-clips-")

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="room-transcript-storage-"))

from app.core.chat_engine import _messages_from_room_stream  # noqa: E402

RESPONDER = "Rosi"

FAILURES = []


def check(name, actual, expected):
    """Plain equality assertion that records instead of aborting the run."""
    if actual != expected:
        FAILURES.append(name)
        print(f"  FAIL {name}: {actual!r} != {expected!r}")
        return False
    return True


def row(speaker=None, content="Hallo", addressees=None, kind="", meta_speaker=None):
    """One perception row as the room stream delivers it.

    ``addressees`` is only written into meta when it is non-empty — that is
    how the store keeps the rows (an empty list is simply absent).
    """
    meta = {}
    if meta_speaker is not None:
        meta["speaker"] = meta_speaker
    elif speaker is not None:
        meta["speaker"] = speaker
    if addressees:
        meta["addressees"] = addressees
    r = {"content": content, "meta": meta}
    if speaker is not None:
        r["speaker"] = speaker
    if kind:
        r["kind"] = kind
    return r


def test_room_wide():
    # [1] a line to the room keeps the bare speaker prefix
    got = _messages_from_room_stream(RESPONDER, [row(speaker="Kai")])
    check("[1] room-wide", got, [{"role": "user", "content": "Kai: Hallo"}])
    print("[1] room-wide line")


def test_addressed_to_other():
    # [2] one addressee, not the responder
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker="Kai", addressees=["Liesa"])])
    check("[2] to one", got,
          [{"role": "user", "content": "Kai (to Liesa): Hallo"}])
    print("[2] addressed to one other")


def test_addressed_to_me():
    # [3] the responder is the addressee -> its own name becomes "you"
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker="Kai", addressees=["Rosi"])])
    check("[3] to me", got,
          [{"role": "user", "content": "Kai (to you): Hallo"}])
    print("[3] addressed to the responder")


def test_addressed_to_me_and_other():
    # [4] mixed list, order kept, only the responder's name swapped
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker="Kai", addressees=["Rosi", "Karl"])])
    check("[4] to me + other", got,
          [{"role": "user", "content": "Kai (to you, Karl): Hallo"}])
    # and the other way round the order is kept too
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker="Kai", addressees=["Karl", "Rosi"])])
    check("[4] other + me", got,
          [{"role": "user", "content": "Kai (to Karl, you): Hallo"}])
    print("[4] addressed to the responder and another, order kept")


def test_own_line():
    # [5] the responder's own line: assistant role, no prefix — even when it
    #     carries addressees
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker="Rosi", addressees=["Kai"])])
    check("[5] own line", got,
          [{"role": "assistant", "content": "Hallo"}])
    print("[5] responder's own line")


def test_dropped_rows():
    # [6] whisper meta and empty content never reach the transcript
    got = _messages_from_room_stream(RESPONDER, [
        row(speaker="Kai", content="egal", kind="whisper_meta"),
        row(speaker="Kai", content="   "),
        row(speaker="Kai", addressees=["Liesa"]),
    ])
    check("[6] dropped", got,
          [{"role": "user", "content": "Kai (to Liesa): Hallo"}])
    print("[6] whisper_meta and empty rows dropped")


def test_speaker_only_in_meta():
    # [7] no top-level speaker key — the meta speaker carries the row
    got = _messages_from_room_stream(
        RESPONDER, [row(speaker=None, meta_speaker="Kai", addressees=["Rosi"])])
    check("[7] meta speaker", got,
          [{"role": "user", "content": "Kai (to you): Hallo"}])
    print("[7] speaker only in meta")


def test_template_render():
    # [8]-[10] the room branch must render all three addressee cases; the
    # render call in routes/chat.py supplies both new variables, so a missing
    # one would crash every room turn (StrictUndefined).
    from jinja2 import meta

    from app.core.prompt_templates import _env, render

    def _names(tpl: str):
        return meta.find_undeclared_variables(
            _env.parse(_env.loader.get_source(_env, tpl)[0]))

    stream_names = _names("chat/chat_stream.md")
    moment_names = _names("chat/chat_moment.md")
    for var in ("addressed_to_me", "addressed_names"):
        assert var in moment_names, f"chat_moment.md does not reference {var}"
        check(f"[8] system prompt never takes {var}", var in stream_names, False)

    def _render(addressed_to_me, addressed_names):
        parts = []
        for tpl, names in (("chat/chat_stream.md", stream_names),
                           ("chat/chat_moment.md", moment_names)):
            ctx = {name: "" for name in names}
            ctx.update(partner_mode="room", partner_name="Kai",
                       present_characters="Liesa, Rosi", character_name="Rosi",
                       medium="in_person",
                       addressed_to_me=addressed_to_me,
                       addressed_names=addressed_names,
                       char_lines=[], partner_lines=[], partner_state_lines=[],
                       self_state_lines=[], moment_notes=[])
            parts.append(render(tpl, **{k: v for k, v in ctx.items() if k in names}))
        return "\n".join(parts)

    mine = _render(True, "")
    check("[8] direct sentence", "Kai spoke to YOU directly" in mine, True)
    check("[8] no bystander sentence", "not to you" in mine, False)
    print("[8] addressed_to_me -> 'spoke to YOU directly'")

    other = _render(False, "Liesa")
    check("[9] named addressee",
          "Kai was speaking to Liesa, not to you" in other, True)
    check("[9] no direct sentence",
          "spoke to YOU directly" in other, False)
    print("[9] overheard, addressed to Liesa")

    room = _render(False, "")
    check("[10] room addressee",
          "Kai said that to the room" in room, True)
    check("[10] no bystander sentence", "not to you" in room, False)
    check("[10] no direct sentence", "spoke to YOU directly" in room, False)
    print("[10] overheard, said to the room")

    # the anti-echo paragraph is unconditional in the room branch (system prompt)
    for label, text in (("mine", mine), ("other", other), ("room", room)):
        check(f"[11] anti-echo ({label})",
              "Lines with a speaker name in front were said by OTHER people."
              in text, True)
    print("[11] anti-echo paragraph in every room render")


def main():
    test_room_wide()
    test_addressed_to_other()
    test_addressed_to_me()
    test_addressed_to_me_and_other()
    test_own_line()
    test_dropped_rows()
    test_speaker_only_in_meta()
    test_template_render()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
