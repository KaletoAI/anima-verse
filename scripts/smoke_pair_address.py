#!/usr/bin/env python3
"""Smoke run for the per-pair FORM OF ADDRESS (relationship address_a_to_b/_b_to_a).

Usage:
    ./.venv/bin/python scripts/smoke_pair_address.py

Runs against a THROWAWAY storage directory — never touches a real world, never
starts a server, makes no LLM call. ``ANIMATION_CLIPS_DIR`` is redirected
before the app modules are imported.

WHAT IS UNDER TEST

A relationship row is SYMMETRIC: ``_sort_pair`` puts the two names in
case-insensitive order and stores them as ``from_char``/``to_char``, so the
pair (Alia, Bo) and the pair (Bo, Alia) are the SAME row with
``character_a = "Alia"``. The directional sentiments live on that orientation
(``sentiment_a_to_b`` = a's feeling toward b), and the two new fields
``address_a_to_b`` / ``address_b_to_a`` follow exactly the same rule. One
helper resolves it: ``relationship._address_keys(speaker, addressee)``.

EXPECTATIONS, derived by hand from that rule (not from current output):

 [1] Orientation, pair stored as (A,B) — A sorts first.
     Names: "Alia" < "Bo" case-insensitively, so the row is (Alia, Bo).
       set_address("Alia", "Bo", X)  must land in address_a_to_b
       set_address("Bo", "Alia", Y)  must land in address_b_to_a
     Read back: get_address("Alia","Bo") == X, get_address("Bo","Alia") == Y.
     Never crossed.

 [2] Orientation, pair created from the OTHER side — "Zara" > "Cor", so
     _ensure_relationship("Zara","Cor") still stores (Cor, Zara).
       set_address("Zara","Cor", X)  -> address_b_to_a  (Zara is the b side)
       set_address("Cor","Zara", Y)  -> address_a_to_b
     Read back in both directions, again never crossed. Checked against the
     RAW row so a symmetric bug (both writes into the same key) cannot hide
     behind a symmetric read.

 [3] set_address creates the pair. Before the call get_relationship(...) is
     None; after it the row exists and carries the text.

 [4] Empty / whitespace text CLEARS that direction and leaves the other one
     alone.

 [5] Rejected input (raises relationship.AddressTextError):
       - 121 characters ("x" * 121; 120 is the documented cap and must pass)
       - a newline inside the text
       - a control character (\\x07)
     A rejected write must not change the stored value.

 [6] The ops layer:
       set_relationship_address(A, <unknown>)  -> HTTPException 404
       set_relationship_address(<unknown>, B)  -> HTTPException 404
       set_relationship_address(A, A)          -> HTTPException 400
       build_relationship_addresses(<unknown>) -> HTTPException 404
     and the happy path returns outgoing/incoming for the calling character.

 [7] Both routes carry ``require_admin`` (inspected on the route's dependant
     tree, the way scripts/smoke_admin_controls.py does it):
       GET  /characters/{character_name}/relationships/addresses
       PUT  /characters/{character_name}/relationships/{other}/address
     and "relationships" is NOT in auth_dependency._PUBLIC_CHARACTER_SEGMENTS
     (a character's pair data is sensitive).

 [8] Relationship DECAY leaves the fields intact: handle_relationship_decay
     re-saves every row, and the address notes ride in the meta blob. Run the
     handler on a pair that is old enough to decay and assert both directions
     survive unchanged (and that the row really was touched — strength drops).

 [9] Deleting a character removes the pair — the existing sweep needs no
     extra clause for the new fields.

[10] The PROMPT, through the real builder ``routes.chat._build_chat_prompt``
     (callable server-less; the template must be one with
     ``relationships_enabled``, otherwise the partner block is the plain
     "chatbot" sentence and no partner sheet is rendered at all):
       - A's prompt toward B contains "Form of address: <A's text>" EXACTLY
         once, in the SYSTEM part (the stable partner block), not in the
         scene state.
       - B's prompt toward A shows B's OWN direction, not A's.
       - With nothing set the line is absent from both parts.
       - Room mode (present_characters = [A, B, C]) puts the note into the
         SCENE STATE instead ("How you address B: …"), because there the
         partner changes from turn to turn.

[11] The dead predecessor is gone: neither ``get_character_address_form`` nor
     ``get_character_user_data`` nor the file name ``user_data.json`` appears
     anywhere under app/, plugins/ (pack symlinks and plugins/installed
     skipped) or scripts/ — except in this file.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="pairaddr-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="pairaddr-clips-")
# [7] imports ``app.server`` to read the route table, and that module runs its
# OWN ``paths.init()``. Without STORAGE_DIR it would re-point the process at
# the tracked worlds/demo mid-run and every later write would land there.
os.environ["STORAGE_DIR"] = str(STORAGE)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

import json  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.core import character_ops  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.models import relationship as R  # noqa: E402
from app.models.character import (delete_character,  # noqa: E402
                                  get_character_config,
                                  save_character_profile)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def make_character(name, template="human-roleplay"):
    save_character_profile(name, {
        "character_name": name,
        "template": template,
        "current_location": "harbour",
    }, create_new=True)


def raw_row(a, b):
    """The stored row as (from_char, to_char, address_a_to_b, address_b_to_a)."""
    row = get_connection().execute(
        "SELECT from_char, to_char, meta FROM relationships "
        "WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?) "
        "ORDER BY id DESC LIMIT 1", (a, b, b, a)).fetchone()
    if not row:
        return None
    meta = json.loads(row[2] or "{}")
    return (row[0], row[1], meta.get("address_a_to_b", ""),
            meta.get("address_b_to_a", ""))


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as e:
        return e
    except Exception as e:  # wrong type — report it
        return e
    return None


# --------------------------------------------------------------------------
print("\n[1] orientation — pair stored as (A, B)")
A, B = "Alia", "Bo"
make_character(A)
make_character(B)
A_TEXT = 'formal, calls him Harbour Master'
B_TEXT = 'informal, nickname "Ali"'
R.set_address(A, B, A_TEXT)
R.set_address(B, A, B_TEXT)
row = raw_row(A, B)
check("[1] row stored in sorted order (Alia, Bo)", row[:2] == (A, B), repr(row[:2]))
check("[1] Alia's note landed in address_a_to_b", row[2] == A_TEXT, repr(row[2]))
check("[1] Bo's note landed in address_b_to_a", row[3] == B_TEXT, repr(row[3]))
check("[1] get_address(Alia, Bo)", R.get_address(A, B) == A_TEXT, repr(R.get_address(A, B)))
check("[1] get_address(Bo, Alia)", R.get_address(B, A) == B_TEXT, repr(R.get_address(B, A)))

# --------------------------------------------------------------------------
print("\n[2] orientation — pair addressed from the b side")
C, Z = "Cor", "Zara"
make_character(C)
make_character(Z)
Z_TEXT = 'formal, avoids the first name'
C_TEXT = 'informal, calls her Za'
R.set_address(Z, C, Z_TEXT)      # Zara sorts SECOND -> address_b_to_a
R.set_address(C, Z, C_TEXT)      # Cor sorts FIRST   -> address_a_to_b
row = raw_row(C, Z)
check("[2] row stored in sorted order (Cor, Zara)", row[:2] == (C, Z), repr(row[:2]))
check("[2] Cor's note in address_a_to_b", row[2] == C_TEXT, repr(row[2]))
check("[2] Zara's note in address_b_to_a", row[3] == Z_TEXT, repr(row[3]))
check("[2] get_address(Zara, Cor)", R.get_address(Z, C) == Z_TEXT, repr(R.get_address(Z, C)))
check("[2] get_address(Cor, Zara)", R.get_address(C, Z) == C_TEXT, repr(R.get_address(C, Z)))
check("[2] the two directions differ in the raw row", row[2] != row[3])

# --------------------------------------------------------------------------
print("\n[3] set_address creates a missing pair")
D = "Denn"
make_character(D)
check("[3] no pair before", R.get_relationship(A, D) is None)
R.set_address(A, D, "informal")
check("[3] pair exists after", R.get_relationship(A, D) is not None)
check("[3] text readable", R.get_address(A, D) == "informal", repr(R.get_address(A, D)))

# --------------------------------------------------------------------------
print("\n[4] empty text clears one direction only")
R.set_address(A, B, "   ")
check("[4] Alia's direction cleared", R.get_address(A, B) == "", repr(R.get_address(A, B)))
check("[4] Bo's direction untouched", R.get_address(B, A) == B_TEXT, repr(R.get_address(B, A)))
check("[4] key removed from the row", raw_row(A, B)[2] == "", repr(raw_row(A, B)))
R.set_address(A, B, A_TEXT)      # restore for [10]

# --------------------------------------------------------------------------
print("\n[5] rejected input")
ok120 = "x" * 120
R.set_address(C, D, ok120)
check("[5] 120 characters accepted", R.get_address(C, D) == ok120,
      f"len={len(R.get_address(C, D))}")
for label, bad in (("121 characters", "x" * 121),
                   ("newline", "formal\nand informal"),
                   ("control character", "formal\x07")):
    e = raises(R.AddressTextError, R.set_address, C, D, bad)
    check(f"[5] {label} rejected", isinstance(e, R.AddressTextError), repr(e))
check("[5] the stored value survived every rejected write",
      R.get_address(C, D) == ok120, repr(R.get_address(C, D))[:40])
R.set_address(C, D, "")

# --------------------------------------------------------------------------
print("\n[6] ops layer")
e = raises(HTTPException, character_ops.set_relationship_address, A, "Nobody",
           outgoing="x")
check("[6] unknown other -> 404",
      isinstance(e, HTTPException) and e.status_code == 404, repr(e))
e = raises(HTTPException, character_ops.set_relationship_address, "Nobody", A,
           outgoing="x")
check("[6] unknown character -> 404",
      isinstance(e, HTTPException) and e.status_code == 404, repr(e))
e = raises(HTTPException, character_ops.set_relationship_address, A, A, outgoing="x")
check("[6] self -> 400",
      isinstance(e, HTTPException) and e.status_code == 400, repr(e))
e = raises(HTTPException, character_ops.build_relationship_addresses, "Nobody")
check("[6] listing an unknown character -> 404",
      isinstance(e, HTTPException) and e.status_code == 404, repr(e))
e = raises(HTTPException, character_ops.set_relationship_address, A, B)
check("[6] neither direction given -> 400",
      isinstance(e, HTTPException) and e.status_code == 400, repr(e))
e = raises(HTTPException, character_ops.set_relationship_address, A, B,
           outgoing="y" * 121)
check("[6] too long -> 400",
      isinstance(e, HTTPException) and e.status_code == 400, repr(e))

res = character_ops.set_relationship_address(A, B, incoming="informal, says du")
check("[6] PUT answer carries both directions of the CALLER's view",
      res["outgoing"] == A_TEXT and res["incoming"] == "informal, says du",
      repr(res))
lst = character_ops.build_relationship_addresses(A)
by_other = {i["other"]: i for i in lst["items"]}
check("[6] listing contains the pair", B in by_other, repr(sorted(by_other)))
check("[6] listing outgoing = how Alia addresses Bo",
      by_other.get(B, {}).get("outgoing") == A_TEXT, repr(by_other.get(B)))
check("[6] listing incoming = how Bo addresses Alia",
      by_other.get(B, {}).get("incoming") == "informal, says du", repr(by_other.get(B)))
lst_b = character_ops.build_relationship_addresses(B)
by_other_b = {i["other"]: i for i in lst_b["items"]}
check("[6] mirrored listing is mirrored, not copied",
      by_other_b.get(A, {}).get("outgoing") == "informal, says du"
      and by_other_b.get(A, {}).get("incoming") == A_TEXT, repr(by_other_b.get(A)))
R.set_address(B, A, B_TEXT)      # restore for [10]

# --------------------------------------------------------------------------
print("\n[7] routes are admin-only, segment is sensitive")
import app.server as server  # noqa: E402
from fastapi.routing import _IncludedRouter  # noqa: E402

check("[7] importing app.server kept the throwaway storage",
      paths.get_storage_dir() == STORAGE, str(paths.get_storage_dir()))


def walk_routes(routes, prefix=""):
    for r in routes:
        if isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            yield from walk_routes(r.original_router.routes,
                                   prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(r, "path", None):
            yield prefix + r.path, r


ROUTE_BY_PAIR = {}
for _path, _route in walk_routes(server.app.routes):
    for m in (getattr(_route, "methods", None) or ()):
        ROUTE_BY_PAIR[(m, _path)] = _route


def dependency_names(route):
    names, stack = set(), [getattr(route, "dependant", None)]
    while stack:
        dep = stack.pop()
        if dep is None:
            continue
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", ""))
        stack.extend(getattr(dep, "dependencies", []) or [])
    return names


for method, path in (
        ("GET", "/characters/{character_name}/relationships/addresses"),
        ("PUT", "/characters/{character_name}/relationships/{other}/address")):
    route = ROUTE_BY_PAIR.get((method, path))
    check(f"[7] {method} {path} exists", route is not None)
    check(f"[7] {method} {path} depends on require_admin",
          route is not None and "require_admin" in dependency_names(route),
          repr(sorted(dependency_names(route))) if route else "route missing")

from app.core.auth_dependency import _PUBLIC_CHARACTER_SEGMENTS  # noqa: E402
check("[7] 'relationships' is not a public character segment",
      "relationships" not in _PUBLIC_CHARACTER_SEGMENTS,
      repr(sorted(_PUBLIC_CHARACTER_SEGMENTS)))

# --------------------------------------------------------------------------
print("\n[8] decay keeps the fields")
from app.core.relationship_decay import handle_relationship_decay  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402

# A fresh world starts at the game epoch, and GameTime has no "before the
# epoch" — so stop the clock, stamp the meeting at the epoch and move the
# world four game weeks forward.
set_game_factor(0.0)
set_game_time(GameTime(0))
old_stamp = GameTime(0).canonical()
set_game_time(GameTime(0) + GameDuration.of(days=28))

rel = R.get_relationship(A, B)
# Both stamps at the epoch: without last_decay_game the first run only
# anchors the pair ("do not charge the backlog") and would decay nothing.
rel["last_interaction_game"] = old_stamp
rel["last_decay_game"] = old_stamp
rel["strength"] = 60
R.save_relationships([rel])
strength_before = R.get_relationship(A, B).get("strength")
handle_relationship_decay({})
after = R.get_relationship(A, B)
check("[8] decay actually ran (strength dropped)",
      after.get("strength", 0) < strength_before,
      f"{strength_before} -> {after.get('strength')}")
check("[8] Alia's direction survived", after.get("address_a_to_b") == A_TEXT,
      repr(after.get("address_a_to_b")))
check("[8] Bo's direction survived", after.get("address_b_to_a") == B_TEXT,
      repr(after.get("address_b_to_a")))

# --------------------------------------------------------------------------
print("\n[10] the prompt (before [9], which deletes a character)")
from app.routes.chat import _build_chat_prompt  # noqa: E402

LINE_A = f"Form of address: {A_TEXT}"
LINE_B = f"Form of address: {B_TEXT}"


def build(speaker, partner, **kw):
    return _build_chat_prompt(
        character_name=speaker, lang_instruction="Respond in English.",
        history_summary="", tools_enabled=False,
        agent_config=get_character_config(speaker),
        partner_override=partner, medium="in_person", **kw)


pa = build(A, B)
check("[10] A's system prompt carries A's line exactly once",
      pa.system.count(LINE_A) == 1, f"count={pa.system.count(LINE_A)}")
check("[10] A's system prompt does NOT carry B's line",
      LINE_B not in pa.system)
check("[10] 1:1 scene state stays free of it",
      "Form of address" not in pa.moment)
check("[10] the line sits ABOVE the 'unless a different form of address' rule",
      pa.system.find(LINE_A) < pa.system.find(
          "unless a different form of address is specified above"),
      f"{pa.system.find(LINE_A)} < "
      f"{pa.system.find('unless a different form of address is specified above')}")

pb = build(B, A)
check("[10] B's prompt shows B's OWN direction",
      pb.system.count(LINE_B) == 1 and LINE_A not in pb.system,
      f"B={pb.system.count(LINE_B)} A={pb.system.count(LINE_A)}")

E = "Eno"
make_character(E)
pe = build(A, E)
check("[10] nothing set -> no line at all",
      "Form of address" not in pe.system and "Form of address" not in pe.moment)

pr = build(A, B, present_characters=[A, B, E])
check("[10] room mode puts it into the SCENE STATE",
      pr.moment.count(f"How you address {B}: {A_TEXT}") == 1,
      f"count={pr.moment.count(f'How you address {B}: {A_TEXT}')}")
check("[10] room mode keeps the system prompt free of it",
      "Form of address" not in pr.system)
pr_none = build(A, E, present_characters=[A, B, E])
check("[10] room mode without a note -> no line",
      "How you address" not in pr_none.moment)

# --------------------------------------------------------------------------
print("\n[9] deleting a character removes the pair")
check("[9] pair exists before the delete", R.get_relationship(A, D) is not None)
delete_character(D)
check("[9] pair gone after the delete", R.get_relationship(A, D) is None)
check("[9] the other pairs are untouched", R.get_address(A, B) == A_TEXT,
      repr(R.get_address(A, B)))

# --------------------------------------------------------------------------
print("\n[11] the dead predecessor is gone")
DEAD = ("get_character_address_form", "get_character_user_data", "user_data.json")
SELF = Path(__file__).resolve()
SKIP_DIRS = {"__pycache__", "node_modules", "installed"}
hits = []
for root in ("app", "plugins", "scripts"):
    base = REPO / root
    for p in base.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(REPO).parts):
            continue
        if p.resolve() == SELF:
            continue
        if p.suffix not in (".py", ".md", ".yaml", ".yml", ".json", ".ts", ".tsx", ".js"):
            continue
        # A package under plugins/ may be a symlink into the private packs
        # repo — rglob does not follow those, but guard the file itself too.
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name in DEAD:
            if name in text:
                hits.append(f"{p.relative_to(REPO)}: {name}")
check("[11] no reference left", not hits, repr(hits[:8]))

# --------------------------------------------------------------------------
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All checks passed.")
