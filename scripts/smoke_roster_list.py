#!/usr/bin/env python3
"""Smoke: GET /characters/list is ONE query and answers byte-identically.

Usage:
    ./.venv/bin/python scripts/smoke_roster_list.py

Throwaway storage (tempfile + ``paths.init``), no server, no real world DB, no
LLM — the route function is called directly.

WHY (DATA-11 of the 2026-09-20 review)
--------------------------------------
The answer is ``{name, template, temporary}`` per character. ``template`` is a
COLUMN of the ``characters`` table, ``temporary`` is a property of the TEMPLATE
(``character_template.template_feature(…, "temporary_npc")``). The handler
nevertheless loaded a full profile per character AND called
``is_temporary_npc``, which loads the profile a SECOND time and deepcopies the
template — 80 profile loads and 40 template deepcopies for a 40-character
roster feeding the Game-Admin roster and the player sidebar.

FIXTURE (a throwaway world, 6 rows in ``characters``)
-----------------------------------------------------
Two templates are written into a throwaway template directory
(``character_template.get_templates_dir`` is redirected at it — the real
shared/templates/character is never touched):

    plain-smoke      features: {}                     -> temporary False
    temp-smoke       features: {"temporary_npc": true} -> temporary True

    Ann    template column "plain-smoke", nothing in the blob
    Bob    template column "temp-smoke",  nothing in the blob
    Cid    column "plain-smoke", blob template "temp-smoke"   (the BLOB wins)
    Dee    column "", blob has no template key at all
    Pia    column "temp-smoke", status 'pooled'
    _sys   column "temp-smoke", underscore name

EXPECTED, derived by hand from ``get_character_profile`` +
``template_feature`` (both read below, not guessed):

  [1] The payload is exactly, in name order (the query orders by name, as
      ``list_available_characters`` did):
        {"characters": [
           {"name": "Ann", "template": "plain-smoke", "temporary": False},
           {"name": "Bob", "template": "temp-smoke",  "temporary": True},
           {"name": "Cid", "template": "temp-smoke",  "temporary": True},
           {"name": "Dee", "template": "",            "temporary": False}]}
      Pia is pooled and _sys is no character — the roster gate of
      ``list_available_characters``. Cid shows the BLOB value because
      ``get_character_profile`` only injects the column when the key is absent
      from the blob. Dee has no template at all, so ``template_feature`` falls
      back to "human-default", which this throwaway world does not define ->
      False.

  [2] BYTE-IDENTICAL to the old implementation: the old handler body is
      re-implemented verbatim in this file and both answers are compared as
      ``json.dumps(..., sort_keys=False)`` strings.

  [3] THE LOAD COUNTER. ``character.get_character_profile`` is wrapped:
        * new handler:  0 profile loads
        * old handler:  8 loads for these 4 characters — one per character in
          the handler plus one per character inside ``is_temporary_npc`` ->
          ``template_feature``. (Pia and _sys are filtered by the roster gate
          before any load.)
      The check asserts 0, so this file fails on the old code by construction.

  [4] ``get_template`` is called ONCE PER DISTINCT TEMPLATE NAME, not once per
      character: 3 distinct names here (plain-smoke, temp-smoke,
      human-default) -> at most 3 calls for 4 characters.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="roster-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models import character as ch  # noqa: E402
from app.models import character_template as ct  # noqa: E402
from app.routes import characters as route  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixture: two templates in the world's own template directory ───────
TMPL_DIR = Path(tempfile.mkdtemp(prefix="roster-tmpl-"))
for tid, features in (("plain-smoke", {}), ("temp-smoke", {"temporary_npc": True})):
    (TMPL_DIR / f"{tid}.json").write_text(json.dumps({
        "id": tid, "name": tid, "features": features, "sections": []}),
        encoding="utf-8")

# The real shared/templates/character must not be touched — redirect the
# loader at the throwaway directory instead.
ct.get_templates_dir = lambda: TMPL_DIR

PEOPLE = [
    ("Ann", "plain-smoke", None, ""),
    ("Bob", "temp-smoke", None, ""),
    ("Cid", "plain-smoke", "temp-smoke", ""),
    ("Dee", "", None, ""),
    ("Pia", "temp-smoke", None, "pooled"),
    ("_sys", "temp-smoke", None, ""),
]

for name, column, blob_template, status in PEOPLE:
    profile = {"character_name": name}
    if blob_template is not None:
        profile["template"] = blob_template
    ch.save_character_profile(name, profile, create_new=True)
    with db.transaction() as conn:
        conn.execute("UPDATE characters SET template=? WHERE name=?", (column, name))
    if status:
        ch.set_character_status(name, status)


# ── the OLD handler body, verbatim as of commit 1a578a48 ───────────────
def old_list_characters():
    out = []
    for name in ch.list_available_characters():
        profile = ch.get_character_profile(name) or {}
        out.append({
            "name": name,
            "template": profile.get("template") or "",
            "temporary": ch.is_temporary_npc(name),
        })
    return {"characters": out}


# ── counters ────────────────────────────────────────────────────────────
_real_get_profile = ch.get_character_profile
_real_get_template = ct.get_template
COUNT = {"profiles": 0, "templates": 0}


def counting_get_profile(name):
    COUNT["profiles"] += 1
    return _real_get_profile(name)


def counting_get_template(tid, *a, **kw):
    COUNT["templates"] += 1
    return _real_get_template(tid, *a, **kw)


ch.get_character_profile = counting_get_profile
ct.get_template = counting_get_template

EXPECTED = {"characters": [
    {"name": "Ann", "template": "plain-smoke", "temporary": False},
    {"name": "Bob", "template": "temp-smoke", "temporary": True},
    {"name": "Cid", "template": "temp-smoke", "temporary": True},
    {"name": "Dee", "template": "", "temporary": False},
]}

print("[1] the payload")
COUNT["profiles"] = COUNT["templates"] = 0
new_payload = route.list_characters()
new_loads, new_templates = COUNT["profiles"], COUNT["templates"]
check("payload as derived by hand", new_payload == EXPECTED,
      json.dumps(new_payload, ensure_ascii=False))

print("[2] byte-identical to the old handler")
COUNT["profiles"] = COUNT["templates"] = 0
old_payload = old_list_characters()
old_loads = COUNT["profiles"]
check("same JSON bytes",
      json.dumps(new_payload, ensure_ascii=False)
      == json.dumps(old_payload, ensure_ascii=False),
      json.dumps(old_payload, ensure_ascii=False))

print("[3] the load counter")
check("new handler: 0 profile loads", new_loads == 0, f"{new_loads} loads")
check("old handler: 2 loads per character (8)", old_loads == 8, f"{old_loads} loads")

print("[4] one template lookup per distinct template name")
check("at most 3 get_template calls for 4 characters",
      new_templates <= 3, f"{new_templates} calls")

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
