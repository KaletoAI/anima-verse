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


try:
    stage1()
    stage2()
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

print("FAIL:\n" + "\n".join(failures) if failures else "OK smoke_pose_key_detail")
sys.exit(1 if failures else 0)
