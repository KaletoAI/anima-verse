#!/usr/bin/env python3
"""Smoke check: pose KEY + DETAIL — the split every LLM producer uses
(development_instructions/plan-pose-key-detail.md).

Usage: ./.venv/bin/python scripts/smoke_pose_key_detail.py

Offline: throwaway storage + world DB, `embedding.embed` stubbed to None so
the resolver falls back by alias equality and never downloads a model.

Stage 1 — split_key_detail, derived BY HAND from the shipped catalog file
(`sitting` is a key, "sitzen" one of its synonyms, "foo" is nothing):
- "sitting: reads a book"      -> ("sitting", "reads a book")
- " Sitzen : liest ein Buch "  -> ("sitting", "liest ein Buch")
- "sitting"                    -> ("sitting", "")
- "leaning against counter"    -> ("", "leaning against counter")
- "foo: bar"                   -> ("", "foo: bar")   (whole text is the detail)
- ""                           -> ("", "")

Stage 2 — set_pose_key_detail against a one-row world ('demo'):
- ("sitting", "reads a book")          -> key sitting, flavor "reads a book",
                                          returns "sitting"
- ("", "smiles", unknown="keep")       -> key STAYS sitting, flavor "smiles",
                                          returns "sitting"
- ("", "", unknown="keep")             -> nothing written, returns ""
- clear_pose_intent, then
  ("", "smiles", unknown="keep")       -> no current key -> nothing written,
                                          pose_key "" and returns ""
- ("", "quantum flux", unknown="resolve") with embed None -> the resolver's
  fallback: key "standing" (the _default), flavor "quantum flux", exactly ONE
  open candidate row "quantum flux" (distance NULL: no vector), returns
  "standing"
- ("leaning against counter", "") with unknown="resolve" -> the free text goes
  through the resolver ONCE: key "standing" (fallback), flavor exactly
  "leaning against counter" — the text must not appear twice in the flavor
- ("dancing together", "") -> raises PairPoseWithoutPartner (catalog pair
  entry, no running interaction)

Stage 3 — the extraction template, derived BY HAND from the template text:
- rendered with is_avatar=False and pose_keys ["standing", "sitting"], the
  system prompt lists exactly "standing, sitting", names both answer fields
  "pose" and "detail", states the no-expression rule ("no facial expression")
  and the language rule ("same language"), and no longer carries the old
  scene example "standing at window"
- rendered with is_avatar=True the system prompt names neither "pose" nor
  "detail" (only the outfit is extracted from user input)

Stage 4 — the marker parser _extract_activity, derived BY HAND (the chat
route module imports offline; 'demo' row from stage 2 is reused):
- "…text… **I do sitting: liest ein Buch**"  -> key sitting, flavor
  "liest ein Buch", returns "sitting: liest ein Buch"
- the SAME marker again -> None (key and detail equal the stored pair)
- "**I do leaning against counter**" (no key) -> the net: with embed None
  the resolver falls back to "standing", flavor "leaning against counter",
  and the candidate "leaning against counter" is counted ONE more time
  (stage 2 saw that text already; (axis, raw_text) is unique, so a repeat
  bumps the count instead of adding a row); returns the marker text
- the SAME keyless marker again -> None: the raw text already equals the
  stored flavor, so no second resolver pass runs and the candidate count of
  "leaning against counter" stays at 2 (1 from stage 2 e2 + 1 from case c)
- "**I do dancing together: mit Kai**" -> pair key without a partner ->
  None, and the pose stays "standing"
- a reply without a marker -> None
- the marker line itself must not be read as a mood: _extract_mood on
  "**I do sitting: liest ein Buch**" returns None

Stage 5 — the SetActivity skill, derived BY HAND from its execute():
- {"agent_name": "demo", "pose": "sitting", "detail": "liest"} -> key
  sitting, flavor "liest", return text "demo: sitting"
- {"agent_name": "demo", "input": "standing: wartet"} (bare text) -> key
  standing, flavor "wartet" (split_key_detail on the text)
- {"agent_name": "demo", "pose": "dancing together"} -> the two-person
  refusal text ("two-person action") and the pose stays standing
- the skill description names both fields and the key rule ("pose key")
  and no longer says "Free-text"

Stage 6 — dismiss all, derived BY HAND: after stages 2 and 4 the open list
holds "quantum flux" and "leaning against counter"; dismiss_all_candidates
("pose") returns 2, the open list is empty, list_candidates(status=
"dismissed") holds both texts; a second call returns 0.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.mkdtemp(prefix="smoke_pose_key_detail_")
from app.core import paths  # noqa: E402
paths.init(_tmp)

from app.core import embedding as _emb  # noqa: E402
_emb.embed = lambda text: None          # offline: alias equality only

from app.core.db import init_schema  # noqa: E402
init_schema()

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def stage1():
    from app.core.pose_catalog import split_key_detail
    cases = [
        ("sitting: reads a book", ("sitting", "reads a book")),
        (" Sitzen : liest ein Buch ", ("sitting", "liest ein Buch")),
        ("sitting", ("sitting", "")),
        ("leaning against counter", ("", "leaning against counter")),
        ("foo: bar", ("", "foo: bar")),
        ("", ("", "")),
    ]
    for text, want in cases:
        got = split_key_detail(text)
        check(got == want, f"stage1 split {text!r}: got {got}, want {want}")


def stage2():
    from app.core import db as _db
    from app.models import character as _ch
    from app.core.pose_catalog import PairPoseWithoutPartner, list_candidates
    from app.core.timeutils import utc_now_iso
    ts = utc_now_iso()
    with _db.transaction() as conn:
        conn.execute(
            "INSERT INTO characters (name, template, profile_json, config_json,"
            " created_at, updated_at) VALUES ('demo', '', '{}', '{}', ?, ?)",
            (ts, ts))

    def state(field):
        row = _db.get_connection().execute(
            f"SELECT {field} FROM character_state WHERE character_name='demo'"
        ).fetchone()
        return row[0] if row else None

    r = _ch.set_pose_key_detail("demo", "sitting", "reads a book")
    check(r == "sitting", f"stage2 a: returned {r!r}")
    check(state("pose_key") == "sitting", f"stage2 a key {state('pose_key')!r}")
    check(state("pose_flavor") == "reads a book", f"stage2 a flavor {state('pose_flavor')!r}")

    r = _ch.set_pose_key_detail("demo", "", "smiles", unknown="keep")
    check(r == "sitting", f"stage2 b: returned {r!r}")
    check(state("pose_key") == "sitting", f"stage2 b key {state('pose_key')!r}")
    check(state("pose_flavor") == "smiles", f"stage2 b flavor {state('pose_flavor')!r}")

    r = _ch.set_pose_key_detail("demo", "", "", unknown="keep")
    check(r == "", f"stage2 c: returned {r!r}")
    check(state("pose_flavor") == "smiles", f"stage2 c flavor changed: {state('pose_flavor')!r}")

    _ch.clear_pose_intent("demo")
    r = _ch.set_pose_key_detail("demo", "", "smiles", unknown="keep")
    check(r == "", f"stage2 d: returned {r!r}")
    check((state("pose_key") or "") == "", f"stage2 d key {state('pose_key')!r}")

    r = _ch.set_pose_key_detail("demo", "", "quantum flux", unknown="resolve")
    check(r == "standing", f"stage2 e: returned {r!r}")
    check(state("pose_key") == "standing", f"stage2 e key {state('pose_key')!r}")
    check(state("pose_flavor") == "quantum flux", f"stage2 e flavor {state('pose_flavor')!r}")
    rows = list_candidates("pose")
    check([x["raw_text"] for x in rows] == ["quantum flux"], f"stage2 e candidates {rows}")

    r = _ch.set_pose_key_detail("demo", "leaning against counter", "")
    check(r == "standing", f"stage2 e2: returned {r!r}")
    check(state("pose_flavor") == "leaning against counter",
          f"stage2 e2 flavor {state('pose_flavor')!r}")

    try:
        _ch.set_pose_key_detail("demo", "dancing together", "")
        check(False, "stage2 f: pair key did not raise")
    except PairPoseWithoutPartner:
        pass


def stage3():
    from app.core.prompt_templates import render_task
    common = dict(target_name="demo", piece_list="", source_label="Character reply",
                  source_text="x", context_text="", outfit_locked=False,
                  stats_enabled=False, stat_list="")
    sys_p, _ = render_task("extraction_chat_state", is_avatar=False,
                           pose_keys=["standing", "sitting"], **common)
    check("standing, sitting" in sys_p, "stage3 key list missing")
    check('"pose"' in sys_p and '"detail"' in sys_p, "stage3 fields missing")
    check("no facial expression" in sys_p, "stage3 no-expression rule missing")
    check("same language" in sys_p, "stage3 language rule missing")
    check("standing at window" not in sys_p, "stage3 old scene example still present")
    sys_a, _ = render_task("extraction_chat_state", is_avatar=True,
                           pose_keys=["standing", "sitting"], **common)
    check('"pose"' not in sys_a and '"detail"' not in sys_a, "stage3 avatar prompt extracts pose")


def stage4():
    from app.core import db as _db
    from app.routes.chat import _extract_activity, _extract_mood
    from app.core.pose_catalog import list_candidates

    def state(field):
        row = _db.get_connection().execute(
            f"SELECT {field} FROM character_state WHERE character_name='demo'"
        ).fetchone()
        return row[0] if row else None

    r = _extract_activity("demo", "Ich setze mich. **I do sitting: liest ein Buch**")
    check(r == "sitting: liest ein Buch", f"stage4 a returned {r!r}")
    check(state("pose_key") == "sitting", f"stage4 a key {state('pose_key')!r}")
    check(state("pose_flavor") == "liest ein Buch", f"stage4 a flavor {state('pose_flavor')!r}")
    r = _extract_activity("demo", "Noch immer. **I do sitting: liest ein Buch**")
    check(r is None, f"stage4 b returned {r!r}")
    def cand_count(text):
        return next((c["count"] for c in list_candidates("pose")
                     if c["raw_text"] == text), 0)

    before = cand_count("leaning against counter")
    r = _extract_activity("demo", "**I do leaning against counter**")
    check(r == "leaning against counter", f"stage4 c returned {r!r}")
    check(state("pose_key") == "standing", f"stage4 c key {state('pose_key')!r}")
    check(state("pose_flavor") == "leaning against counter", f"stage4 c flavor {state('pose_flavor')!r}")
    check(cand_count("leaning against counter") == before + 1,
          "stage4 c no candidate recorded")
    r = _extract_activity("demo", "**I do leaning against counter**")
    check(r is None, f"stage4 c2 returned {r!r}")
    check(cand_count("leaning against counter") == before + 1,
          f"stage4 c2 candidate bumped to {cand_count('leaning against counter')}")
    r = _extract_activity("demo", "**I do dancing together: mit Kai**")
    check(r is None, f"stage4 d returned {r!r}")
    check(state("pose_key") == "standing", f"stage4 d key {state('pose_key')!r}")
    check(_extract_activity("demo", "Nur Text.") is None, "stage4 e no marker")
    check(_extract_mood("demo", "**I do sitting: liest ein Buch**") is None,
          "stage4 f marker read as mood")


def stage5():
    from app.core import db as _db
    from app.core.prompt_templates import load_skill_meta
    from app.plugins.context import PluginContext
    from app.plugins.loader import discover_packages
    from plugins.set_pose.skill import SetPoseSkill
    # The loader is what mounts plugins/*/templates/llm into the Jinja
    # search path — without it load_skill_meta cannot see the package file.
    discover_packages()
    skill = SetPoseSkill({"enabled": True}, PluginContext("set_pose"))

    def state(field):
        row = _db.get_connection().execute(
            f"SELECT {field} FROM character_state WHERE character_name='demo'"
        ).fetchone()
        return row[0] if row else None

    out = skill.execute('{"agent_name": "demo", "pose": "sitting", "detail": "liest"}')
    check(out == "demo: sitting", f"stage5 a out {out!r}")
    check(state("pose_key") == "sitting" and state("pose_flavor") == "liest",
          f"stage5 a state {state('pose_key')!r}/{state('pose_flavor')!r}")
    skill.execute('{"agent_name": "demo", "input": "standing: wartet"}')
    check(state("pose_key") == "standing" and state("pose_flavor") == "wartet",
          f"stage5 b state {state('pose_key')!r}/{state('pose_flavor')!r}")
    out = skill.execute('{"agent_name": "demo", "pose": "dancing together"}')
    check("two-person action" in out, f"stage5 c out {out!r}")
    check(state("pose_key") == "standing", f"stage5 c key {state('pose_key')!r}")
    meta = load_skill_meta("set_pose")
    check("pose key" in meta["description"] and '"detail"' in meta["description"],
          "stage5 d description lacks key/detail")
    check("Free-text" not in meta["description"], "stage5 d description still free-text")


def stage6():
    from app.core.pose_catalog import dismiss_all_candidates, list_candidates
    open_before = sorted(x["raw_text"] for x in list_candidates("pose"))
    check(open_before == ["leaning against counter", "quantum flux"],
          f"stage6 precondition {open_before}")
    n = dismiss_all_candidates("pose")
    check(n == 2, f"stage6 dismissed {n}")
    check(list_candidates("pose") == [], "stage6 open list not empty")
    gone = sorted(x["raw_text"] for x in list_candidates("pose", status="dismissed"))
    check(gone == ["leaning against counter", "quantum flux"], f"stage6 dismissed list {gone}")
    check(dismiss_all_candidates("pose") == 0, "stage6 second call changed rows")


try:
    stage1()
    stage2()
    stage3()
    stage4()
    stage5()
    stage6()
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

print("FAIL:\n" + "\n".join(failures) if failures else "OK smoke_pose_key_detail")
sys.exit(1 if failures else 0)
