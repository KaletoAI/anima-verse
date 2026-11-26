#!/usr/bin/env python3
"""World Dev free mode — add_secret / delete_secret (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 4).

Usage: ./.venv/bin/python scripts/smoke_world_dev_secrets.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR temp), no server.

WHAT IS CHECKED, and where every expected value comes from:

Fixture: Demo Smith, Demo Lad (template human-roleplay,
save_character_profile create_new=True) and the place Demo Forge (id
"demo_forge", written with app.models.world.upsert_location, no run). A
secret id is "sec_" + 8 hex digits (app.models.secrets.add_secret, uuid4) —
read at runtime from the result line, which names it.
app.models.secrets.VALID_CATEGORIES = ("personal", "relationship",
"location", "criminal"); SEVERITY_LABELS[2] = "embarrassing".

Run 1 (turn 1 unless named):
  (a) add_secret{Demo Lad, "He broke the anvil.", personal, 2, known_by
      [Demo Smith], related_location demo_forge} -> ok, line
      'added secret <id> of Demo Lad (personal, severity 2 embarrassing),
      known by Demo Smith'; list_secrets(Demo Lad) has 1 entry with known_by
      == ["Demo Smith"], severity 2, source "manual", related_location
      "demo_forge"; one write journal row, target kind "secret", target id
      <id>, inverse {"op": "delete_secret", "owner": "Demo Lad", "id": <id>}.
      get_character{Demo Lad, fields:["secrets"]} names <id> and
      "personal/2"; the overview of get_character{Demo Lad} has "secrets: 1".
  (b) refusals (each leaves the write rows at 1 and the secrets at 1):
      severity 7 (the writer would clamp it to 5); category "heist" (the
      line lists "personal, relationship, location, criminal");
      known_by ["Demo Lad"] (the owner); known_by ["Nobody"] (no such
      character); content " padded " (the writer strips); content "" ;
      related_location "nowhere"; known_by ["Demo Smith", "Demo Smith"].
  (c) discard_preview(run) == ['secret <id> of "Demo Lad" (personal)'].
  (d) delete_created{kind:"secret", id:<id>} in turn 1 -> ok, the secret
      is gone (list_secrets == []). A second secret S2 added in turn 1 and
      delete_created in turn 2 -> refused "created in an earlier turn".
  (e) changed since: update_secret(Demo Lad, S2, {severity: 3}) directly ->
      discard_preview == ['secret <S2> was changed since — the discard
      leaves it alone']; undo(run) -> not complete, one skip "changed since"
      with keys ["severity"]; S2 stays with severity 3.
Run 2:
  (f) add_secret{Demo Smith, "Owes the miller money."} on a clean run ->
      undo(run) complete; list_secrets(Demo Smith) == [] and no secret of
      Demo Lad besides S2 (run 1's foreign-changed one, removed by hand
      before run 2).
Run 3 (references, same turn):
  (g) turn 1: create_location Demo Shed, create_character Demo Witness,
      add_secret{Demo Lad, …, known_by [Demo Witness], related_location
      <shed>} -> delete_created{location, <shed>} refused "still named by:"
      and "secret <id> of Demo Lad"; delete_created{character, Demo Witness}
      refused naming "secret <id> of Demo Lad"; delete_created{secret, <id>}
      -> ok; then both deletes -> ok.
Run 4 (references, earlier-turn path):
  (g2) turn 1: create_location Demo Shed, create_character Demo Witness;
      turn 2: add_secret naming both -> delete_created{location} and
      {character} refused as in (g) (both created in turn 1: the
      earlier-turn path); delete_created{secret} (same turn) -> ok; then
      both deletes -> ok. undo(run) -> complete; no Demo Shed, no Demo
      Witness, no secret of Demo Lad.
Run 5 (linked body, letter case):
  (h) Demo Body linked to Demo Smith (linked_characters.link(Body, Smith)).
      add_secret{Demo Lad, known_by [Demo Body]} -> refused "name the leader
      Demo Smith instead of Demo Body". add_secret{Demo Lad, known_by
      ["demo smith"]} and {related_characters ["demo smith"]} -> refused,
      the line names "demo smith" (no character of that exact name: the
      tool stores names exactly as the character rows spell them).
      add_secret{Demo Body, …} -> ok, the line ends "(stored on Demo
      Smith)"; the journal inverse is {"op": "delete_secret", "owner": "Demo
      Smith", "id": <id>}; discard_preview == ['secret <id> of "Demo Smith"
      (personal)']. add_secret{Demo Body, known_by [Demo Smith]} -> refused
      (one family; the line names "Demo Smith"). undo -> complete,
      list_secrets(Demo Smith) == [].
Run 6 (accepted residual: the writer re-saves the whole mind):
  (i) a foreign sparse row of Demo Lad inserted raw: content "old",
      visibility NULL, meta '{"content": "old"}' (no id). secret_exists
      ("sec_<rowid>") is True (the id the reader shows). add_secret{Demo
      Lad, "New one."} + undo -> complete; discard_preview before the undo
      == only the run's own line; the foreign row still reads content "old",
      id "sec_<rowid>", known_by [] — but its raw meta now carries "id"
      (the reader's defaults filled in; documented residual, same meaning).
Run 7 (acceptance fixes):
  (j) secrets_naming compares character names casefolded: a raw foreign
      row of Demo Smith whose meta known_by is ["demo lad"] and
      related_characters ["DEMO LAD"] -> secrets_naming(name="Demo Lad")
      has exactly that row (owner Demo Smith) with why ["knows it",
      "related"]; secrets_naming(location="DEMO_FORGE") is [] (ids stay
      exact). The row is removed by hand afterwards.
  (k) a raw row of Demo Lad with meta "{broken" -> add_secret{Demo Lad}
      refused, the line has "cannot be read"; no write journal row in that
      run (the refusal comes before step.prepare). Row removed by hand.
  (l) the undo reads its delete back: add_secret{Demo Smith, "Hums."} ok;
      secrets.delete_secret patched to return True without deleting (a
      swallowed DB error) -> undo(run) not complete, one skip
      "delete refused"; the secret is still stored. Patch restored, the
      secret removed by hand.
  (m) the preview survives an unreadable keeper: add_secret{Demo Smith,
      "Whistles."} ok (id SM); then a raw row of Demo Smith with meta
      "{broken" (list_secrets(strict=True) raises for the whole mind) ->
      discard_preview(run) == ['secret <SM> of "Demo Smith" — its keeper's
      secrets cannot be read; the discard will report it'] (no exception);
      undo -> not complete, exactly one skip whose reason starts "undo
      failed" (the same case, as the preview said). Broken row and SM
      removed by hand.
"""
import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_secrets_"))
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

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import secrets as sec  # noqa: E402
from app.models.world import get_location_by_id, list_locations, upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


SMITH, LAD = "Demo Smith", "Demo Lad"
FORGE = "demo_forge"
for name in (SMITH, LAD):
    assert ch.save_character_profile(
        name, {"character_name": name, "template": "human-roleplay"}, create_new=True), name
upsert_location({"id": FORGE, "name": "Demo Forge", "rooms": []}, sync_world=False)
assert get_location_by_id(FORGE) is not None

SID = re.compile(r"secret (sec_[0-9a-f]{8})")


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("secrets")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def sid_of(res):
    m = SID.search(res.line or "")
    return m.group(1) if m else ""


BASE = {"name": LAD, "content": "He broke the anvil.", "category": "personal",
        "severity": 2, "known_by": [SMITH], "related_location": FORGE}

# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) add_secret")
r = call("add_secret", dict(BASE))
check("(a) ok", r.ok and r.wrote, r)
S1 = sid_of(r)
check("(a) line", r.line == (f"added secret {S1} of Demo Lad (personal, severity 2 "
                             "embarrassing), known by Demo Smith"), r.line)
rows = sec.list_secrets(LAD)
check("(a) one secret", len(rows) == 1, rows)
if rows:
    s = rows[0]
    check("(a) known_by", s.get("known_by") == [SMITH], s)
    check("(a) severity", s.get("severity") == 2, s)
    check("(a) source manual", s.get("source") == "manual", s)
    check("(a) related_location", s.get("related_location") == FORGE, s)
w = writes()
check("(a) one write row", len(w) == 1, w)
if w:
    check("(a) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("secret", S1), w[0])
    check("(a) inverse", w[0].get("inverse") == {"op": "delete_secret", "owner": LAD,
                                                 "id": S1}, w[0].get("inverse"))
g = call("get_character", {"name": LAD, "fields": ["secrets"]})
check("(a) get_character secrets", g.ok and S1 in g.line and "personal/2" in g.line, g.line)
g = call("get_character", {"name": LAD})
check("(a) overview secrets: 1", "secrets: 1" in g.line, g.line)
cat = call("list_catalog", {"name": "secret_categories"})
check("(a) catalog secret_categories", cat.ok and "criminal" in cat.line
      and "embarrassing" in cat.line, cat.line)

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) refusals")
for label, patch, needle in (
        ("severity 7", {"severity": 7}, "severity"),
        ("category heist", {"category": "heist"}, "personal, relationship, location, criminal"),
        ("known_by owner", {"known_by": [LAD]}, "Demo Lad"),
        ("known_by unknown", {"known_by": ["Nobody"]}, "Nobody"),
        ("padded content", {"content": " padded "}, "content"),
        ("empty content", {"content": ""}, "content"),
        ("unknown location", {"related_location": "nowhere"}, "nowhere"),
        ("duplicate knower", {"known_by": [SMITH, SMITH]}, "twice")):
    res = call("add_secret", {**BASE, **patch})
    check(f"(b) {label} refused", not res.ok and not res.wrote and needle in res.line, res.line)
check("(b) still one write row", len(writes()) == 1, len(writes()))
check("(b) still one secret", len(sec.list_secrets(LAD)) == 1)

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) discard_preview")
pv = wu.discard_preview(run)
check("(c) preview", pv == [f'secret {S1} of "Demo Lad" (personal)'], pv)

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) delete_created")
r = call("delete_created", {"kind": "secret", "id": S1})
check("(d) same-turn delete ok", r.ok, r.line)
check("(d) gone", sec.list_secrets(LAD) == [], sec.list_secrets(LAD))
r = call("add_secret", {**BASE, "content": "He hid the hammer."})
S2 = sid_of(r)
check("(d) S2 ok", r.ok and S2, r.line)
r = call("delete_created", {"kind": "secret", "id": S2}, turn=2)
check("(d) earlier turn refused", not r.ok and "created in an earlier turn" in r.line, r.line)
check("(d) S2 still there", sec.get_secret(LAD, S2) is not None)

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) changed since")
sec.update_secret(LAD, S2, {"severity": 3})
pv = wu.discard_preview(run)
check("(e) preview", pv == [f"secret {S2} was changed since — the discard leaves it alone"], pv)
u = wu.undo(run)
check("(e) not complete", not u["complete"], u)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(e) one changed-since skip, keys [severity]",
      len(sk) == 1 and sk[0].get("keys") == ["severity"], u["skipped"])
cur = sec.get_secret(LAD, S2)
check("(e) S2 stays with severity 3", cur is not None and cur.get("severity") == 3, cur)
sec.delete_secret(LAD, S2)

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) clean run undo")
run = new_run("secrets 2")
r = call("add_secret", {"name": SMITH, "content": "Owes the miller money."})
check("(f) ok", r.ok, r.line)
check("(f) defaults", r.ok and "(personal, severity 2 embarrassing), known by nobody" in r.line,
      r.line)
u = wu.undo(run)
check("(f) undo complete", u["complete"], u)
check("(f) no secrets left", sec.list_secrets(SMITH) == [] and sec.list_secrets(LAD) == [],
      (sec.list_secrets(SMITH), sec.list_secrets(LAD)))


# ── (g) ──────────────────────────────────────────────────────────────────
def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


def refs_case(tag, create_turn, secret_turn):
    global run
    run = new_run(f"secrets {tag}")
    r = call("create_location", {"data": {"name": "Demo Shed"}, "x": 60, "z": 0},
             turn=create_turn)
    check(f"({tag}) shed", r.ok, r.line)
    shed = loc_id("Demo Shed")
    r = call("create_character", {"data": {"name": "Demo Witness"}}, turn=create_turn)
    check(f"({tag}) witness", r.ok, r.line)
    r = call("add_secret", {"name": LAD, "content": "He broke the anvil.",
                            "known_by": ["Demo Witness"], "related_location": shed},
             turn=secret_turn)
    sid = sid_of(r)
    check(f"({tag}) secret ok", r.ok and sid, r.line)
    r = call("delete_created", {"kind": "location", "id": shed}, turn=secret_turn)
    check(f"({tag}) location delete refused",
          not r.ok and "still named by" in r.line and f"secret {sid} of Demo Lad" in r.line,
          r.line)
    check(f"({tag}) shed still there", get_location_by_id(shed) is not None)
    r = call("delete_created", {"kind": "character", "id": "Demo Witness"}, turn=secret_turn)
    check(f"({tag}) character delete refused",
          not r.ok and f"secret {sid} of Demo Lad" in r.line, r.line)
    check(f"({tag}) witness still there", ch.character_row_exists("Demo Witness"))
    r = call("delete_created", {"kind": "secret", "id": sid}, turn=secret_turn)
    check(f"({tag}) secret delete ok", r.ok, r.line)
    r = call("delete_created", {"kind": "location", "id": shed}, turn=secret_turn)
    check(f"({tag}) location delete ok", r.ok, r.line)
    r = call("delete_created", {"kind": "character", "id": "Demo Witness"}, turn=secret_turn)
    check(f"({tag}) character delete ok", r.ok, r.line)
    check(f"({tag}) gone", get_location_by_id(shed) is None
          and not ch.character_row_exists("Demo Witness"))
    u = wu.undo(run)
    check(f"({tag}) undo complete", u["complete"], u)
    check(f"({tag}) nothing left", loc_id("Demo Shed") == ""
          and not ch.character_row_exists("Demo Witness") and sec.list_secrets(LAD) == [],
          (loc_id("Demo Shed"), ch.character_row_exists("Demo Witness"), sec.list_secrets(LAD)))


print("(g) references, same turn")
refs_case("g", 1, 1)
print("(g2) references, earlier turn")
refs_case("g2", 1, 2)

# ── (h) ──────────────────────────────────────────────────────────────────
from app.core import linked_characters as lc  # noqa: E402

print("(h) linked body, letter case")
BODY = "Demo Body"
assert ch.save_character_profile(
    BODY, {"character_name": BODY, "template": "human-roleplay"}, create_new=True)
res = lc.link(BODY, SMITH)
check("(h) fixture link", res.get("ok"), res)
run = new_run("secrets h")
r = call("add_secret", {"name": LAD, "content": "x", "known_by": [BODY]})
check("(h) body as knower refused",
      not r.ok and "name the leader Demo Smith instead of Demo Body" in r.line, r.line)
for key in ("known_by", "related_characters"):
    r = call("add_secret", {"name": LAD, "content": "x", key: ["demo smith"]})
    check(f"(h) lower-case {key} refused", not r.ok and "demo smith" in r.line, r.line)
r = call("add_secret", {"name": BODY, "content": "Sings at night."})
SB = sid_of(r)
check("(h) body keeper ok", r.ok and SB and r.line.endswith("(stored on Demo Smith)"), r.line)
w = writes()
check("(h) inverse owner is the mind",
      len(w) == 1 and w[0].get("inverse") == {"op": "delete_secret", "owner": SMITH, "id": SB},
      w)
pv = wu.discard_preview(run)
check("(h) preview names the mind", pv == [f'secret {SB} of "Demo Smith" (personal)'], pv)
r = call("add_secret", {"name": BODY, "content": "y", "known_by": [SMITH]})
check("(h) family knower refused", not r.ok and "Demo Smith" in r.line, r.line)
u = wu.undo(run)
check("(h) undo complete", u["complete"], u)
check("(h) nothing left", sec.list_secrets(SMITH) == [], sec.list_secrets(SMITH))

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) accepted residual: foreign sparse row re-saved")
from app.core.db import get_connection, transaction  # noqa: E402

with transaction() as conn:
    rid = conn.execute("INSERT INTO secrets (character_name, content, visibility, meta) "
                       "VALUES (?, ?, NULL, ?)", (LAD, "old", '{"content": "old"}')).lastrowid
check("(i) secret_exists for a meta-less legacy id", sec.secret_exists(f"sec_{rid}"))
check("(i) secret_exists stays False for an unknown id", not sec.secret_exists("sec_ffffffff"))
run = new_run("secrets i")
r = call("add_secret", {"name": LAD, "content": "New one."})
SI = sid_of(r)
check("(i) ok", r.ok and SI, r.line)
pv = wu.discard_preview(run)
check("(i) preview only own line", pv == [f'secret {SI} of "Demo Lad" (personal)'], pv)
u = wu.undo(run)
check("(i) undo complete", u["complete"], u)
left = sec.list_secrets(LAD)
check("(i) foreign row same meaning",
      len(left) == 1 and left[0].get("content") == "old"
      and left[0].get("id") == f"sec_{rid}" and left[0].get("known_by") == [], left)
raw_meta = get_connection().execute("SELECT meta FROM secrets WHERE id=?", (rid,)).fetchone()
check("(i) residual pinned: meta now carries the id",
      raw_meta is not None and '"id"' in (raw_meta[0] or ""), raw_meta)

# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) secrets_naming casefolded")
with transaction() as conn:
    rj = conn.execute(
        "INSERT INTO secrets (character_name, content, visibility, meta) VALUES (?, ?, NULL, ?)",
        (SMITH, "case", '{"content": "case", "id": "sec_cafe0001", "known_by": ["demo lad"], '
                        '"discovered_by": [], "related_characters": ["DEMO LAD"]}')).lastrowid
hits = sec.secrets_naming(name=LAD)
check("(j) other letter case matches",
      len(hits) == 1 and hits[0]["owner"] == SMITH
      and hits[0]["why"] == ["knows it", "related"], hits)
check("(j) location id stays exact", sec.secrets_naming(location="DEMO_FORGE") == [])
with transaction() as conn:
    conn.execute("DELETE FROM secrets WHERE id=?", (rj,))

# ── (k) ──────────────────────────────────────────────────────────────────
print("(k) broken row refused before prepare")
with transaction() as conn:
    rk = conn.execute(
        "INSERT INTO secrets (character_name, content, visibility, meta) VALUES (?, ?, NULL, ?)",
        (LAD, "broken", "{broken")).lastrowid
run = new_run("secrets k")
r = call("add_secret", {"name": LAD, "content": "Never stored."})
check("(k) refused", not r.ok and "cannot be read" in (r.line or ""), r.line)
check("(k) no write row", writes() == [], writes())
with transaction() as conn:
    conn.execute("DELETE FROM secrets WHERE id=?", (rk,))

# ── (l) ──────────────────────────────────────────────────────────────────
print("(l) undo reads its delete back")
run = new_run("secrets l")
r = call("add_secret", {"name": SMITH, "content": "Hums."})
SL = sid_of(r)
check("(l) ok", r.ok and SL, r.line)
_real_delete = sec.delete_secret
sec.delete_secret = lambda owner, sid: True
try:
    u = wu.undo(run)
finally:
    sec.delete_secret = _real_delete
check("(l) not complete", not u["complete"], u)
check("(l) one delete-refused skip",
      [s.get("reason") for s in u["skipped"]] == [wu.REASON_REFUSED], u["skipped"])
check("(l) secret still stored", sec.get_secret(SMITH, SL) is not None)
sec.delete_secret(SMITH, SL)

# ── (m) ──────────────────────────────────────────────────────────────────
print("(m) preview with an unreadable keeper")
run = new_run("secrets m")
r = call("add_secret", {"name": SMITH, "content": "Whistles."})
SM = sid_of(r)
check("(m) ok", r.ok and SM, r.line)
with transaction() as conn:
    rm = conn.execute(
        "INSERT INTO secrets (character_name, content, visibility, meta) VALUES (?, ?, NULL, ?)",
        (SMITH, "broken", "{broken")).lastrowid
try:
    pv = wu.discard_preview(run)
    pv_err = ""
except Exception as e:  # noqa: BLE001 — the check reports it
    pv, pv_err = None, repr(e)
check("(m) preview line, no exception",
      pv == [f'secret {SM} of "Demo Smith" — its keeper\'s secrets cannot be read; '
             "the discard will report it"], (pv, pv_err))
u = wu.undo(run)
skips = u.get("skipped") or []
check("(m) undo not complete, one 'undo failed' skip",
      not u["complete"] and len(skips) == 1
      and str(skips[0].get("reason") or "").startswith("undo failed"), u)
with transaction() as conn:
    conn.execute("DELETE FROM secrets WHERE id=?", (rm,))
sec.delete_secret(SMITH, SM)

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
