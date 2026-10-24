#!/usr/bin/env python3
"""Smoke: what is uncovered on a body reaches the chat prompt, uncut.

Usage:
    ./.venv/bin/python scripts/smoke_uncovered_prompt.py

Runs without a server, without a world DB and without network. Exit 0 = all
green, exit 1 = at least one check failed.

Background (2026-10-24, logged chat prompts of a scene where two characters
wore nothing):
  - a wardrobe character with not one piece on got NO line about its own
    body in the scene state, and went on describing a dress it did not wear;
  - what it saw of the others rode at the END of a description capped at
    180 characters, so the cap cut it ("exposed large breasts, expos…");
  - a triggered state was appended by its internal NAME ("visibly <label>").
Now ``outfit_renderer.uncovered_state`` / ``uncovered_summary`` say what is
uncovered, ``present_people_details`` puts it after the cap as
``uncovered: …`` with the states' visible text as ``looks: …``, and the chat
scene state hands the uncovered bodies to packages (``chat.moment_facts``).

The fragments, states and profiles below are invented; the expected strings
follow from the f-strings in the code by hand.
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="uncovered-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="uncovered-storage-"))

from app.core import outfit_renderer as orr  # noqa: E402
from app.core import thought_context as tc  # noqa: E402

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


def state(profile, *, exposed, pieces="", free_text=False, undressed="",
          replacements=()):
    with patch("app.core.body_slots.prompt_fragments",
               return_value={"general": [], "exposed": list(exposed)}), \
            patch("app.core.prompt_filters.collect_image_modifiers",
                  return_value=(list(replacements), [])), \
            patch.object(orr, "is_free_text_wardrobe", return_value=free_text), \
            patch.object(orr, "render_outfit", return_value={"pieces": pieces}), \
            patch("app.core.body_slots.undressed_prompt", return_value=undressed):
        return (orr.uncovered_state("Demo", profile),
                orr.uncovered_summary("Demo", profile))


def main() -> int:
    print("1. uncovered_state / uncovered_summary")
    st, summ = state({}, exposed=["bare arms"], undressed="bare",
                     replacements=[("bare arms", "bare tanned arms")])
    check("nothing worn + fragment → wears nothing, replacement applied",
          st == (True, "bare tanned arms"), f"got {st}")
    check("summary = undressed text, then the fragments",
          summ == "bare, bare tanned arms", f"got {summ!r}")
    st, summ = state({}, exposed=[], undressed="")
    check("no fragment, no undressed_prompt (a species never dressed) → nothing to say",
          st == (False, "") and summ == "", f"got {st} {summ!r}")
    st, _ = state({}, exposed=[], undressed="bare")
    check("no fragment but a declared undressed_prompt → wears nothing",
          st == (True, ""), f"got {st}")
    st, summ = state({}, exposed=["bare feet"], pieces="shirt, trousers")
    check("dressed with an uncovered slot → only the fragment",
          st == (False, "bare feet") and summ == "bare feet", f"got {st} {summ!r}")
    st, _ = state({"equipped_pieces": {"top": "piece_gone"}}, exposed=["bare feet"])
    check("an equipped piece id that no longer resolves still counts as worn",
          st == (False, "bare feet"), f"got {st}")
    st, _ = state({"outfit_worn": False}, exposed=[], free_text=True)
    check("free-text wardrobe undressed → wears nothing",
          st == (True, ""), f"got {st}")
    st, _ = state({}, exposed=[], free_text=True)
    check("free-text wardrobe without the key is dressed",
          st == (False, ""), f"got {st}")

    print("2. present_people_details")
    long_desc = "tall person, " + "x" * 200
    with patch("app.core.prompt_builder.person_description",
               return_value=long_desc) as pd, \
            patch("app.core.prompt_filters.collect_image_modifiers",
                  return_value=([("tall", "very tall")], ["flushed cheeks"])), \
            patch("app.core.outfit_renderer.uncovered_summary",
                  return_value="bare feet") as us:
        out = tc.present_people_details([("Lukas", "Lukas")], "loc")
    cut = ("very tall person, " + "x" * 200)[:180].rstrip(", ") + "…"
    check("description capped, replacement applied before the cap",
          out.startswith(f"- Lukas: {cut}; "), f"got {out[:80]!r}")
    check("uncovered and looks come after the cap, uncut",
          out.endswith("; uncovered: bare feet; looks: flushed cheeks"), f"got {out[-80:]!r}")
    check("description asked WITHOUT exposed fragments and state modifiers",
          pd.call_args.kwargs.get("include_exposed") is False
          and pd.call_args.kwargs.get("apply_state_modifiers") is False,
          f"got {pd.call_args}")
    check("uncovered gets the same replacements",
          us.call_args.kwargs.get("replacements") == [("tall", "very tall")],
          f"got {us.call_args}")
    check("no state label is appended any more", "visibly" not in out, out)
    from app.core import prompt_filters
    check("triggered_state_labels is gone",
          not hasattr(prompt_filters, "triggered_state_labels"))

    print("3. chat scene state")
    from app.core.prompt_templates import render
    from jinja2 import meta
    from app.core.prompt_templates import _env
    names = meta.find_undeclared_variables(_env.parse(
        _env.loader.get_source(_env, "chat/chat_moment.md")[0]))
    ctx = dict.fromkeys(names, "")
    ctx.update(moment_notes=[], self_state_lines=[], partner_state_lines=[],
               moment_facts=["Uncovered right now: you (bare feet)."])
    moment = render("chat/chat_moment.md", **ctx)
    check("a moment fact renders under 'This moment:' without a reply shape",
          "This moment:\n- Uncovered right now: you (bare feet).\n" in moment,
          repr(moment[-200:]))
    ctx.update(reply_shape_section="- The incoming line is brief.")
    moment = render("chat/chat_moment.md", **ctx)
    check("… and after the reply-shape lines when there are some",
          "This moment:\n- The incoming line is brief.\n- Uncovered right now:" in moment,
          repr(moment[-200:]))
    from app.routes import chat as chat_route
    src = inspect.getsource(chat_route._build_chat_prompt)
    check("chat prompt emits chat.moment_facts with the uncovered bodies",
          'emit("chat.moment_facts"' in src and "uncovered=uncovered" in src
          and "moment_facts=moment_facts" in src)
    check("own body: uncovered lines in the self wearing block",
          "lines.extend(_uncovered_lines(_cname, _label))" in src)
    check("room mode drops the partner's uncovered line (presence carries it)",
          "with_uncovered=False" in src)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} of {CHECKS} checks — {', '.join(FAILURES)}")
        return 1
    print(f"OK: {CHECKS} checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
