#!/usr/bin/env python3
"""World Dev free mode — set_address / restore_address (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 3).

Usage: ./.venv/bin/python scripts/smoke_world_dev_address.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR temp), no server.

WHAT IS CHECKED, and where every expected value comes from:

Fixture: Demo Smith, Demo Lad (template human-roleplay, save_character_profile
create_new=True), later Demo Body linked to Demo Smith (linked_characters.link).

Orientation (relationship._sort_pair compares lowercased names):
"demo lad" < "demo smith", so the pair row is (Demo Lad, Demo Smith), the pair
key is "Demo Lad|Demo Smith", Demo Lad's OWN direction is "address_a_to_b"
and Demo Smith's is "address_b_to_a" (relationship._address_keys).

  (a) set_address{Demo Lad -> Demo Smith, "calls him Master"} -> ok, line
      'Demo Lad addresses Demo Smith: "calls him Master"'; get_address(Lad,
      Smith) == "calls him Master", get_address(Smith, Lad) == "". Journal:
      one write row, target kind "relationship", target id "Demo Lad|Demo
      Smith", inverse op restore_address with row_created True, key
      address_a_to_b, before ABSENT, row_id == the row's _db_id.
  (b) the same again -> refused "already set"; text "a\nb" -> refused with
      clean_address's own message ("must not contain line breaks"); " x " ->
      refused "would be stored as"; speaker == addressee -> refused; an
      unknown speaker -> refused; text 5 (not a string) -> refused. Every
      refusal leaves only "refused" journal rows (the write rows stay 1).
  (c) set_address{Demo Smith -> Demo Lad, "calls him lad"} -> ok (same row
      as (a): row_created False, before ABSENT, key address_b_to_a).
  (c2) get_character{Demo Lad, fields:["addresses"]} lists both directions:
      'Demo Lad → Demo Smith: "calls him Master"' and
      'Demo Smith → Demo Lad: "calls him lad"'.
  (c3) set_address{Demo Smith -> Demo Lad, ""} -> ok, line ends
      "form of address cleared"; get_address(Smith, Lad) == "".
  (d) discard_preview(run) == ['form of address Demo Lad|Demo Smith (created
      by the run)'] — world_dev_undo._address_preview_lines walks newest-
      first like the undo: (c3) and (c) put Smith's key back (no line), (a)
      finds the row it created unchanged apart from its key -> it goes.
  (e) undo(run) -> complete; newest-first: (c3) restores "calls him lad",
      (c) pops Smith's key, (a) finds the row it created unchanged apart from
      its key -> the row is deleted: pair_row(Lad, Smith) is None.
  (f) pre-existing row: record_interaction(Lad, Smith, "talkto") makes the
      row; P0 = pair_row before; (a) again -> undo complete -> the row still
      exists and pair_row == P0 (_norm compare — the address key absent, every
      other key byte-equal). discard_preview before that undo == [] (a key put
      back on a row that existed: nothing goes).
  (g) changed since: (a) again on that row, then relationship.set_address
      (Lad, Smith, "calls him Sir") directly -> undo NOT complete, one skip
      "changed since" with keys ["address_a_to_b"]; the value stays
      "calls him Sir". discard_preview before that undo == ['form of address
      Demo Lad → Demo Smith was changed since — the discard leaves it alone'].
  (g2) row created by the run and changed by someone else: on a new pair
      (Demo Lad, Demo Cook — "demo cook" < "demo lad", so Lad's key is
      address_b_to_a) set_address{Lad -> Cook, "calls her Chef"}, then
      record_interaction(Lad, Cook) changes the row -> undo: skip
      "changed since" keys ["row"]; the address is cleared (get_address == "")
      and the row stays (it is someone else's now). discard_preview before that
      undo == ['form of address Demo Cook|Demo Lad: the relationship row was
      changed since — the discard clears Demo Lad → Demo Cook and leaves the
      row'].
  (i) sparse foreign row, byte-for-byte: a row (Demo Cook, Demo Smith) is
      inserted raw ("demo cook" < "demo smith": Cook's key address_a_to_b,
      Smith's address_b_to_a) with content {"type": "friend", "character_a":
      "Demo Cook", "character_b": "Demo Smith"}, meta {"address_a_to_b":
      " padded "} and ts "T0" — no id, history, strength. set_address{Cook ->
      Smith, "x"} -> refused "cannot be restored exactly" (the stored value
      is not what clean_address keeps); set_address{Smith -> Cook, "calls her
      Cook"} -> ok, the writer added an "id" to the meta; undo -> complete
      and relationship.raw_pair_row(row id) == the inserted columns exactly.
      The meta value set to 121 "x" (over ADDRESS_MAX_LEN 120) -> Cook ->
      Smith refused "cannot be restored exactly" as well.
  (j) rest changed since on a row that existed: the row's columns are reset to
      RAW_J (RAW with meta "{}"); set_address{Smith -> Cook, "calls her
      Cook"} -> ok; then a foreign raw write sets the content to the sparse
      {"type": "rival", "character_a": "Demo Cook", "character_b": "Demo
      Smith"} (no strength, ...). X = raw_pair_row(rid) after that; X's meta
      holds the key plus the reader defaults the step's writer added to the
      sparse row (relationship._row_to_rel setdefaults: "id", "history",
      "last_interaction", "created_at" — none of them in RAW_J's meta "{}").
      Preview == [] (a key put back on a row that existed, every added key
      still as written). undo -> complete and raw_pair_row(rid) == X with the
      key AND those added keys gone from its meta: from_char/to_char/content/ts
      equal X's, meta == "{}" (json.dumps of the empty object, the
      serialisation set_pair_row_meta_key uses) — the row's meta is RAW_J's
      again. The sparse content stays sparse (the merging writer would have
      put the reader's defaults back).
  (j2) the same, but the foreign write ALSO changes one added meta key
      ("history" -> ["foreign"]) -> preview == ['form of address Demo Smith →
      Demo Cook: the relationship row was changed since — the discard puts the
      form of address back and leaves the rest of the row']; undo -> not
      complete, one "changed since" skip with keys ["row"]; afterwards the
      meta has no "address_b_to_a", no "id"/"last_interaction"/"created_at"
      (still as written, popped) and "history" == ["foreign"] (theirs).
  (k) pending step on a row that existed: columns reset to RAW_J again;
      set_address{Smith -> Cook, "calls her Cook"} with wr.attach AND
      wr.complete raising a BaseException (a dying process) -> the call
      raises, one pending set_address row, its inverse the one begin stored:
      text "calls her Cook", row_id == rid. get_address(Smith, Cook) ==
      "calls her Cook" (the write happened). Preview == []. undo -> complete
      and raw_pair_row(rid) == RAW_J exactly (the key held the sent text, so
      the raw columns go back — no "id" or other default left behind).
  (h) linked body: Demo Body linked to Demo Smith. set_address{Demo Body ->
      Demo Lad, "calls him boy"} -> ok, line contains "stored on Demo Smith";
      get_address(Smith, Lad) == "calls him boy" (the mind's direction,
      address_b_to_a). Demo Body -> Demo Smith refused (one family). undo ->
      complete, get_address(Smith, Lad) == "" again; the row stays (it existed).
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_address_"))
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import linked_characters as lc  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import relationship as rel  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


SMITH, LAD, COOK, BODY = "Demo Smith", "Demo Lad", "Demo Cook", "Demo Body"
PAIR = "Demo Lad|Demo Smith"
LAD_KEY, SMITH_KEY = "address_a_to_b", "address_b_to_a"

for name in (SMITH, LAD, COOK, BODY):
    assert ch.save_character_profile(
        name, {"character_name": name, "template": "human-roleplay"}, create_new=True), name

run = wr.create_run("address", "m", "p", "u", 80, 300000)


def call(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=1), tool, args)


def writes():
    return wr.entries(run, include_undone=True)


def pair_row(a, b):
    return rel.pair_row(a, b)


# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) Lad -> Smith")
r = call("set_address", {"speaker": LAD, "addressee": SMITH, "text": "calls him Master"})
check("(a) ok", r.ok, r.line)
check("(a) line", r.line == 'Demo Lad addresses Demo Smith: "calls him Master"', r.line)
check("(a) stored", rel.get_address(LAD, SMITH) == "calls him Master", rel.get_address(LAD, SMITH))
check("(a) other direction empty", rel.get_address(SMITH, LAD) == "", rel.get_address(SMITH, LAD))
w = writes()
check("(a) one write row", len(w) == 1, len(w))
if w:
    e = w[0]
    inv = e.get("inverse") or {}
    row = pair_row(LAD, SMITH) or {}
    check("(a) target", (e.get("target_kind"), e.get("target_id")) == ("relationship", PAIR),
          (e.get("target_kind"), e.get("target_id")))
    check("(a) inverse", (inv.get("op"), inv.get("speaker"), inv.get("addressee"),
                          inv.get("pair"), inv.get("key"), inv.get("before"),
                          inv.get("row_created"))
          == ("restore_address", LAD, SMITH, PAIR, LAD_KEY, wu.ABSENT, True), inv)
    check("(a) row_id attached", inv.get("row_id") == row.get("_db_id") and row.get("_db_id"),
          (inv.get("row_id"), row.get("_db_id")))

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) refusals")
for label, args, want in (
        ("again", {"speaker": LAD, "addressee": SMITH, "text": "calls him Master"}, "already set"),
        ("newline", {"speaker": LAD, "addressee": SMITH, "text": "a\nb"},
         "must not contain line breaks"),
        ("blanks", {"speaker": LAD, "addressee": SMITH, "text": " x "}, "would be stored as"),
        ("self", {"speaker": LAD, "addressee": LAD, "text": "me"}, "error"),
        ("unknown", {"speaker": "Demo Nobody", "addressee": LAD, "text": "x"}, "error"),
        ("not a string", {"speaker": LAD, "addressee": SMITH, "text": 5}, "error")):
    r = call("set_address", args)
    check(f"(b) {label} refused", not r.ok and want in r.line, r.line)
check("(b) still one write row", len(writes()) == 1, len(writes()))
check("(b) value unchanged", rel.get_address(LAD, SMITH) == "calls him Master")

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) Smith -> Lad")
r = call("set_address", {"speaker": SMITH, "addressee": LAD, "text": "calls him lad"})
check("(c) ok", r.ok, r.line)
inv = (writes()[0].get("inverse") or {}) if writes() else {}
check("(c) inverse", (inv.get("key"), inv.get("before"), inv.get("row_created"))
      == (SMITH_KEY, wu.ABSENT, False), inv)
check("(c) stored", rel.get_address(SMITH, LAD) == "calls him lad")

print("(c2) get_character addresses")
r = call("get_character", {"name": LAD, "fields": ["addresses"]})
check("(c2) ok", r.ok, r.line)
check("(c2) outgoing", 'Demo Lad → Demo Smith: "calls him Master"' in r.line, r.line)
check("(c2) incoming", 'Demo Smith → Demo Lad: "calls him lad"' in r.line, r.line)

print("(c3) clear")
r = call("set_address", {"speaker": SMITH, "addressee": LAD, "text": ""})
check("(c3) ok", r.ok, r.line)
check("(c3) line", r.line.endswith("form of address cleared"), r.line)
check("(c3) cleared", rel.get_address(SMITH, LAD) == "")

# ── (d) / (e) ────────────────────────────────────────────────────────────
print("(d) discard_preview")
check("(d) created row listed", wu.discard_preview(run)
      == ["form of address Demo Lad|Demo Smith (created by the run)"], wu.discard_preview(run))
print("(e) undo")
rep = wu.undo(run)
check("(e) complete", rep.get("complete"), rep)
check("(e) row gone", pair_row(LAD, SMITH) is None, pair_row(LAD, SMITH))

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) pre-existing row")
rel.record_interaction(LAD, SMITH, "talkto", "met at the forge")
P0 = pair_row(LAD, SMITH)
check("(f) fixture row", P0 is not None)
r = call("set_address", {"speaker": LAD, "addressee": SMITH, "text": "calls him Master"})
check("(f) ok", r.ok, r.line)
check("(f) preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(f) complete", rep.get("complete"), rep)
P1 = pair_row(LAD, SMITH)
check("(f) row stays", P1 is not None)
check("(f) key absent", LAD_KEY not in (P1 or {}), P1)
check("(f) row equal", wu._norm(P1) == wu._norm(P0), (P0, P1))

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) changed since")
r = call("set_address", {"speaker": LAD, "addressee": SMITH, "text": "calls him Master"})
check("(g) ok", r.ok, r.line)
rel.set_address(LAD, SMITH, "calls him Sir")
check("(g) preview changed", wu.discard_preview(run) == [
    "form of address Demo Lad → Demo Smith was changed since — the discard leaves it alone"],
      wu.discard_preview(run))
rep = wu.undo(run)
sk = rep.get("skipped") or []
check("(g) not complete", not rep.get("complete"), rep)
check("(g) one changed skip", len(sk) == 1 and sk[0].get("reason") == "changed since"
      and sk[0].get("keys") == [LAD_KEY], sk)
check("(g) value stays", rel.get_address(LAD, SMITH) == "calls him Sir")

print("(g2) created row changed by someone else")
r = call("set_address", {"speaker": LAD, "addressee": COOK, "text": "calls her Chef"})
check("(g2) ok", r.ok, r.line)
inv = (writes()[0].get("inverse") or {}) if writes() else {}
check("(g2) key + created", (inv.get("key"), inv.get("row_created"), inv.get("pair"))
      == ("address_b_to_a", True, "Demo Cook|Demo Lad"), inv)
rel.record_interaction(LAD, COOK, "talkto", "asked for bread")
check("(g2) preview row changed", wu.discard_preview(run) == [
    "form of address Demo Cook|Demo Lad: the relationship row was changed since — "
    "the discard clears Demo Lad → Demo Cook and leaves the row"], wu.discard_preview(run))
rep = wu.undo(run)
sk = rep.get("skipped") or []
check("(g2) changed row skip", len(sk) == 1 and sk[0].get("reason") == "changed since"
      and sk[0].get("keys") == ["row"], sk)
check("(g2) address cleared", rel.get_address(LAD, COOK) == "")
check("(g2) row stays", pair_row(LAD, COOK) is not None)

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) linked body")
res = lc.link(BODY, SMITH)
check("(h) fixture link", res.get("ok"), res)
r = call("set_address", {"speaker": BODY, "addressee": LAD, "text": "calls him boy"})
check("(h) ok", r.ok, r.line)
check("(h) stored on mind", "stored on Demo Smith" in r.line, r.line)
check("(h) mind's direction", rel.get_address(SMITH, LAD) == "calls him boy")
r = call("set_address", {"speaker": BODY, "addressee": SMITH, "text": "x"})
check("(h) one family refused", not r.ok, r.line)
rep = wu.undo(run)
check("(h) complete", rep.get("complete"), rep)
check("(h) cleared again", rel.get_address(SMITH, LAD) == "")
check("(h) row stays", pair_row(LAD, SMITH) is not None)

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) sparse foreign row")
from app.core.db import transaction  # noqa: E402

RAW = {"from_char": COOK, "to_char": SMITH,
       "content": '{"type": "friend", "character_a": "Demo Cook", "character_b": "Demo Smith"}',
       "ts": "T0", "meta": '{"address_a_to_b": " padded "}'}
with transaction() as conn:
    rid = conn.execute("INSERT INTO relationships (from_char, to_char, content, ts, meta) "
                       "VALUES (?, ?, ?, ?, ?)", tuple(RAW[k] for k in
                       ("from_char", "to_char", "content", "ts", "meta"))).lastrowid
r = call("set_address", {"speaker": COOK, "addressee": SMITH, "text": "x"})
check("(i) padded stored value refused", not r.ok and "cannot be restored exactly" in r.line, r.line)
r = call("set_address", {"speaker": SMITH, "addressee": COOK, "text": "calls her Cook"})
check("(i) ok", r.ok, r.line)
check("(i) writer added an id", "id" in (rel.pair_row(COOK, SMITH) or {}), rel.pair_row(COOK, SMITH))
check("(i) preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(i) complete", rep.get("complete"), rep)
check("(i) raw columns back", rel.raw_pair_row(rid) == RAW, rel.raw_pair_row(rid))
with transaction() as conn:
    conn.execute("UPDATE relationships SET meta=? WHERE id=?",
                 ('{"address_a_to_b": "' + "x" * 121 + '"}', rid))
r = call("set_address", {"speaker": COOK, "addressee": SMITH, "text": "x"})
check("(i) over-long stored value refused",
      not r.ok and "cannot be restored exactly" in r.line, r.line)

# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) rest of an existing row changed since")
import json  # noqa: E402

COLS = ("from_char", "to_char", "content", "ts", "meta")
RAW_J = {**RAW, "meta": "{}"}


def reset_row():
    with transaction() as conn:
        conn.execute("UPDATE relationships SET from_char=?, to_char=?, content=?, ts=?, "
                     "meta=? WHERE id=?", (*(RAW_J[k] for k in COLS), rid))


reset_row()
check("(j) fixture reset", rel.raw_pair_row(rid) == RAW_J, rel.raw_pair_row(rid))
r = call("set_address", {"speaker": SMITH, "addressee": COOK, "text": "calls her Cook"})
check("(j) ok", r.ok, r.line)
SPARSE = '{"type": "rival", "character_a": "Demo Cook", "character_b": "Demo Smith"}'
with transaction() as conn:
    conn.execute("UPDATE relationships SET content=? WHERE id=?", (SPARSE, rid))
X = rel.raw_pair_row(rid)
check("(j) preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(j) complete", rep.get("complete"), rep)
xmeta = json.loads(X["meta"])
check("(j) fixture: the step's key in the meta", xmeta.get("address_b_to_a") == "calls her Cook",
      xmeta)
check("(j) fixture: the writer added its defaults",
      {"id", "history", "last_interaction", "created_at"} <= set(xmeta), xmeta)
want = {**X, "meta": "{}"}
check("(j) the key and the step's added keys left the row", rel.raw_pair_row(rid) == want,
      (rel.raw_pair_row(rid), want))
check("(j) content stays sparse", (rel.raw_pair_row(rid) or {}).get("content") == SPARSE)

# ── (j2) ─────────────────────────────────────────────────────────────────
print("(j2) an added key changed by someone else too")
reset_row()
r = call("set_address", {"speaker": SMITH, "addressee": COOK, "text": "calls her Cook"})
check("(j2) ok", r.ok, r.line)
xmeta = json.loads(rel.raw_pair_row(rid)["meta"])
xmeta["history"] = ["foreign"]
with transaction() as conn:
    conn.execute("UPDATE relationships SET content=?, meta=? WHERE id=?",
                 (SPARSE, json.dumps(xmeta, ensure_ascii=False), rid))
want_line = ("form of address Demo Smith → Demo Cook: the relationship row was changed "
             "since — the discard puts the form of address back and leaves the rest of the row")
check("(j2) preview line", wu.discard_preview(run) == [want_line], wu.discard_preview(run))
rep = wu.undo(run)
skips = rep.get("skipped") or []
check("(j2) not complete, changed since ['row']",
      not rep.get("complete") and len(skips) == 1
      and "changed since" in str(skips[0].get("reason")) and skips[0].get("keys") == ["row"],
      rep)
after = json.loads(rel.raw_pair_row(rid)["meta"])
check("(j2) key and still-written defaults gone, the foreign history stays",
      after == {"history": ["foreign"]}, after)

# ── (k) ──────────────────────────────────────────────────────────────────
print("(k) pending step on a row that existed")


class Crash(BaseException):
    """Ends a tool call the way a dying process would: the row stays pending."""


def _crash(*a, **k):
    raise Crash()


reset_row()
_orig = (wr.attach, wr.complete)
wr.attach = wr.complete = _crash
try:
    call("set_address", {"speaker": SMITH, "addressee": COOK, "text": "calls her Cook"})
    crashed = False
except Crash:
    crashed = True
finally:
    wr.attach, wr.complete = _orig
pend = [s for s in wr.steps(run) if s.get("tool") == "set_address" and s.get("state") == "pending"]
check("(k) crash leaves one pending row", crashed and len(pend) == 1, pend)
inv = (pend[0].get("inverse") or {}) if pend else {}
check("(k) begin's inverse: text + existing row id",
      (inv.get("text"), inv.get("row_id"), inv.get("row_created"))
      == ("calls her Cook", rid, False), inv)
check("(k) the write happened", rel.get_address(SMITH, COOK) == "calls her Cook")
check("(k) preview empty", wu.discard_preview(run) == [], wu.discard_preview(run))
rep = wu.undo(run)
check("(k) complete", rep.get("complete"), rep)
check("(k) raw columns back exactly", rel.raw_pair_row(rid) == RAW_J, rel.raw_pair_row(rid))

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all address checks passed")
