#!/usr/bin/env python3
"""Smoke run for the first-person normaliser of the pose flavor
(plan-befundrunde-2026-09-29 B7.4, binding review note).

Usage:  ./.venv/bin/python scripts/smoke_flavor_first_person.py

Offline: throwaway storage + world DB (``paths.init`` before any world-DB
import), ``embedding.embed`` stubbed to None so the resolver never loads a
model.

THE RULE
---------------------------------------------------------------------------
The flavor is what a BYSTANDER sees, in the third person. An RP line copied
over ("ich greife nach meiner Tasche") rendered as "Vallerie is ich greife …".
``pose_catalog.sanitize_flavor`` therefore drops a first-person sentence
(returns ""), so the caller keeps the KEY and loses only the detail. The word
list, verbatim from the binding note: ``\\bI\\b`` case-SENSITIVE, and
``\\b(ich|mich|mir|mein(e[mnrs]?)?|wir|uns|unser(e[mnrs]?)?|my|me|we|us|our)\\b``
case-insensitive. The keep branch of ``set_pose_key_detail`` must not wipe a
good flavor with such a dropped detail.

Hand-derived expectations
---------------------------------------------------------------------------
[1] dropped (→ ""):
      "greift nach meiner Tasche"  (meiner = mein+e+r)
      "Ich lehne mich zurück"      (Ich, case-insensitive; mich)
      "I lean back"                (I)
      "holding my cup"             (my)
      "sits next to us"            (us)
      "wir tanzen"                 (wir)
      "hält unsere Karte"          (unsere)
      "gibt mir das Glas"          (mir)
    kept unchanged:
      "leans back in the chair"
      "greift nach ihrer Tasche"
      "i lean back"                (lowercase i is no pronoun by the list)
      "watches the dust swirl in the museum"   (no whole-word hit:
                                                museum ≠ us, swirl ≠ wir)
      "Iris lehnt am Tresen"      (Iris ≠ I)
    quoted speech goes first: 'says "I am tired" and yawns' → "says and yawns"
    only the FIRST sentence counts: "leans back. I wait." → "leans back."
[2] set_pose_key_detail on a one-row world ('demo'):
    a ("sitting", "reads a book")                 → flavor "reads a book"
    b ("", "greife nach meiner Tasche", keep)     → nothing written, returns
                                                    "", flavor STAYS "reads a book"
    c ("", "reaches for her bag", keep)           → flavor "reaches for her bag"
    d ("sitting", "ich lese ein Buch")            → key sitting, flavor ""
                                                    (key kept, detail dropped)
    e ("", "I stand up", resolve)                 → a pose key is written
                                                    (the resolver's fallback
                                                    "standing"), flavor ""
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.mkdtemp(prefix="smoke_flavor_first_person_")
from app.core import paths  # noqa: E402
paths.init(_tmp)

from app.core import embedding as _emb  # noqa: E402
_emb.embed = lambda text: None

from app.core.db import init_schema  # noqa: E402
init_schema()

from app.core import db as _db  # noqa: E402
from app.core.pose_catalog import sanitize_flavor  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402
from app.models import character as _ch  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


print("\n[1] sanitize_flavor")
for text in ("greift nach meiner Tasche", "Ich lehne mich zurück", "I lean back",
             "holding my cup", "sits next to us", "wir tanzen",
             "hält unsere Karte", "gibt mir das Glas"):
    got = sanitize_flavor(text)
    check(f"dropped: {text!r}", got == "", repr(got))
for text in ("leans back in the chair", "greift nach ihrer Tasche", "i lean back",
             "watches the dust swirl in the museum", "Iris lehnt am Tresen"):
    got = sanitize_flavor(text)
    check(f"kept: {text!r}", got == text, repr(got))
got = sanitize_flavor('says "I am tired" and yawns')
check("quoted speech removed before the check", got == "says and yawns", repr(got))
got = sanitize_flavor("leans back. I wait.")
check("only the first sentence counts", got == "leans back.", repr(got))

print("\n[2] set_pose_key_detail")
ts = utc_now_iso()
with _db.transaction() as conn:
    conn.execute(
        "INSERT INTO characters (name, template, profile_json, config_json,"
        " created_at, updated_at) VALUES ('demo', '', '{}', '{}', ?, ?)", (ts, ts))


def state(field):
    row = _db.get_connection().execute(
        f"SELECT {field} FROM character_state WHERE character_name='demo'").fetchone()
    return row[0] if row else None


r = _ch.set_pose_key_detail("demo", "sitting", "reads a book")
check("a key sitting, flavor 'reads a book'",
      r == "sitting" and state("pose_flavor") == "reads a book",
      f"{r!r} {state('pose_flavor')!r}")
r = _ch.set_pose_key_detail("demo", "", "greife nach meiner Tasche", unknown="keep")
check("b first-person detail in keep: nothing written", r == "", repr(r))
check("b the good flavor stays", state("pose_flavor") == "reads a book",
      repr(state("pose_flavor")))
check("b the key stays", state("pose_key") == "sitting", repr(state("pose_key")))
r = _ch.set_pose_key_detail("demo", "", "reaches for her bag", unknown="keep")
check("c third-person detail in keep refreshes the flavor",
      r == "sitting" and state("pose_flavor") == "reaches for her bag",
      f"{r!r} {state('pose_flavor')!r}")
r = _ch.set_pose_key_detail("demo", "sitting", "ich lese ein Buch")
check("d key kept, first-person detail dropped",
      r == "sitting" and state("pose_key") == "sitting" and (state("pose_flavor") or "") == "",
      f"{r!r} {state('pose_key')!r} {state('pose_flavor')!r}")
r = _ch.set_pose_key_detail("demo", "", "I stand up", unknown="resolve")
check("e resolve path writes the fallback key, no first-person flavor",
      r == "standing" and (state("pose_flavor") or "") == "",
      f"{r!r} {state('pose_flavor')!r}")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
