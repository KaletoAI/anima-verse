#!/usr/bin/env python3
"""Smoke run for the WORLDMAP HOT PATH (py-spy, 2026-11-07).

``GET /play/worldmap`` is polled every 2–3 s by every client and was the
biggest Python CPU consumer. Three reads inside it did far more work than the
answer needed, and this file pins that the cheap paths answer exactly what the
expensive ones did:

  * ``_inject_soul_md_values`` (every ``get_character_profile``) deep-copied
    the WHOLE character template to find the fields with a ``source_file``;
    it now asks ``character_template.soul_source_fields``. The feature checks
    (``is_feature_enabled``, the body-slot/extension-rig selectors) did the
    same deep copy three times per character for ``features`` alone; they ask
    ``template_features``.
  * ``resolve_location`` / ``_location_id_of`` parsed EVERY location to find
    one; they now answer from an index built beside the read cache and parse
    only the location they return (``_location_id_of`` parses none).

Runs against a THROWAWAY storage directory and a THROWAWAY templates
directory (``character_template.get_templates_dir`` is patched) — never a real
world, never the shipped templates, no server, no LLM.

Hand-derived expectations
-------------------------

[1] soul_source_fields on the temp template ``hot-smoke``:

      section 1: personality (source_file soul/personality.md)
                 plain       (no source_file)              -> skipped
                 ""          (source_file soul/x.md, no key) -> skipped
                 beliefs     (source_file soul/beliefs.md)
      section 2: task        (source_file soul/tasks.md)

    -> (("personality", "soul/personality.md"),
        ("beliefs", "soul/beliefs.md"), ("task", "soul/tasks.md"))
    The second call hands back the SAME tuple object (cached). Rewriting the
    file without a clear changes nothing (still cached, 3 pairs); after
    ``clear_template_cache`` the rewritten template (beliefs dropped) answers
    (("personality", ...), ("task", ...)). ``save_template`` clears on its
    own: adding "goals" (soul/goals.md) after "task" gives 3 pairs again.
    An unknown template answers (). A clear that lands BETWEEN reading the
    template and publishing (simulated by a get_template that clears) must
    leave nothing cached for that name.

[1b] template_features: ``hot-smoke`` declares {"thoughts_enabled": False};
    the answer equals that, a mutation of it does not reach the next caller,
    an unknown template is None. is_feature_enabled(profile with template
    hot-smoke, "thoughts_enabled") -> False; "memory_enabled" (absent) -> True.

[1c] the profile read, file always wins: character "Kestrel" on hot-smoke,
    files personality.md = "## Core\nCalm and dry.", tasks.md =
    "## Now\nMend the nets.", goals.md = "" and STALE blob values
    personality = "OLD", beliefs = "stale belief" written straight into
    profile_json (``load_source_file`` keeps only text under a ``## `` heading,
    so the bodies carry one):
      personality -> "## Core\nCalm and dry."  (file beats blob)
      task        -> "## Now\nMend the nets."
      goals       -> ""                        (empty file reads empty)
      beliefs     -> "stale belief"  (not a source field of the template any
                                     more since [1], so the blob is the value)
    then personality.md emptied -> personality "" (an empty file clears).

[2] resolve_location on a temp world. Locations come back ORDER BY name:

      "Market"   (M)   "Mill" (L)   "Old Mill Tavern" (T)
      plus Z, NAMED after L's id (8 random hex digits, so it may sort before
      or after them — no case below depends on where: a hex name contains
      none of "mill", "tavern", "nowhere" and is in none of them)

    case                     pass        expected
    L.id                     id          L   (id beats Z's equal NAME)
    "Old Mill Tavern"        name        T   (exact name beats L's substring)
    "Mill - Cellar"          substring   L   ("mill" in "mill - cellar";
                                              Market is first and does not match)
    "tavern"                 substring   T   (Market/Mill do not match)
    "mill"                   substring   L   (no exact name: "Mill" != "mill")
    M.id                     id          M
    "Nowhere"                -           None
    ""                       -           None
    Each case also equals the verbatim pre-change scan (reference copy below),
    and ``_location_id_of`` answers the matched id ("" for None).
    get_location_by_id("deadbeef") -> None (warm index, string id unknown).

    Copies: two resolves of "Mill" are equal and not the same object; setting
    name and a room's name on one leaves the next resolve at "Mill"/"Cellar".

[3] a generation bump is seen by the index:
      rename T -> "Old Mill Inn":  "Old Mill Tavern" now resolves to L by
                                   substring ("mill" in it), "Old Mill Inn" to T
      add "Quarry" (Q):            "Quarry" -> Q
      delete M:                    M.id -> None, "Market" -> None
    And the publish rule: a fill whose generation was captured before a bump
    does not publish (the cache stays cold).

[4] _build_lookup refuses what it cannot mirror: a location whose name is the
    number 5 -> subs None (the scan raises there, only the scan may say
    where); a non-dict entry -> the whole index None.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_hot_path.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-hot-smoke-"))
TEMPLATES = Path(tempfile.mkdtemp(prefix="worldmap-hot-templates-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="worldmap-hot-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.models import character_template as ct  # noqa: E402

patch.object(ct, "get_templates_dir", return_value=TEMPLATES).start()

from app.models import world as W  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_dir, get_character_profile, save_character_profile)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def write_template(name, body):
    (TEMPLATES / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


SECTIONS = [
    {"fields": [
        {"key": "personality", "source_file": "soul/personality.md"},
        {"key": "plain", "type": "text"},
        {"key": "", "source_file": "soul/x.md"},
        {"key": "beliefs", "source_file": "soul/beliefs.md"},
    ]},
    {"fields": [{"key": "task", "source_file": "soul/tasks.md"}]},
]
write_template("hot-smoke", {"features": {"thoughts_enabled": False},
                             "sections": SECTIONS})

# ── [1] ────────────────────────────────────────────────────────────────────
print("[1] soul_source_fields")
FULL = (("personality", "soul/personality.md"),
        ("beliefs", "soul/beliefs.md"), ("task", "soul/tasks.md"))
first = ct.soul_source_fields("hot-smoke")
check("pairs of the temp template", first, FULL)
check("second call is the cached tuple", ct.soul_source_fields("hot-smoke") is first, True)

no_beliefs = json.loads(json.dumps(SECTIONS))
no_beliefs[0]["fields"] = [f for f in no_beliefs[0]["fields"] if f["key"] != "beliefs"]
write_template("hot-smoke", {"features": {"thoughts_enabled": False},
                             "sections": no_beliefs})
check("file rewritten, no clear -> still cached", ct.soul_source_fields("hot-smoke"), FULL)
ct.clear_template_cache()
check("after clear_template_cache", ct.soul_source_fields("hot-smoke"),
      (("personality", "soul/personality.md"), ("task", "soul/tasks.md")))

with_goals = json.loads(json.dumps(no_beliefs))
with_goals[1]["fields"].append({"key": "goals", "source_file": "soul/goals.md"})
ct.save_template("hot-smoke", {"features": {"thoughts_enabled": False},
                               "sections": with_goals})
WITH_GOALS = (("personality", "soul/personality.md"), ("task", "soul/tasks.md"),
              ("goals", "soul/goals.md"))
check("save_template clears on its own", ct.soul_source_fields("hot-smoke"), WITH_GOALS)
check("unknown template", ct.soul_source_fields("no-such-template"), ())

_real_get_template = ct.get_template


def _clearing_get_template(name="default"):
    tmpl = _real_get_template(name)
    ct.clear_template_cache()   # a save landing mid-read
    return tmpl


ct.clear_template_cache()
with patch.object(ct, "get_template", _clearing_get_template):
    check("mid-read clear: the read still answers", ct.soul_source_fields("hot-smoke"),
          WITH_GOALS)
check("mid-read clear: nothing published", "hot-smoke" in ct._soul_fields_cache, False)
with patch.object(ct, "get_template", _clearing_get_template):
    ct.template_features("hot-smoke")
check("mid-read clear: no features published", "hot-smoke" in ct._features_cache, False)

print("[1b] template_features")
feats = ct.template_features("hot-smoke")
check("features", feats, {"thoughts_enabled": False})
feats["thoughts_enabled"] = True
check("a caller's mutation stays its own", ct.template_features("hot-smoke"),
      {"thoughts_enabled": False})
check("unknown template", ct.template_features("no-such-template"), None)
check("is_feature_enabled: declared False",
      ct.is_feature_enabled("nobody", "thoughts_enabled",
                            profile={"template": "hot-smoke"}, config={}), False)
check("is_feature_enabled: absent -> True",
      ct.is_feature_enabled("nobody", "memory_enabled",
                            profile={"template": "hot-smoke"}, config={}), True)

print("[1c] the profile read: the file always wins")
check("Kestrel created", save_character_profile(
    "Kestrel", {"template": "hot-smoke"}, create_new=True), True)
soul = get_character_dir("Kestrel") / "soul"
soul.mkdir(parents=True, exist_ok=True)
for fname, text in (("personality.md", "## Core\nCalm and dry."),
                    ("tasks.md", "## Now\nMend the nets."), ("goals.md", "")):
    path = soul / fname
    path.write_text(text, encoding="utf-8")
    ct.invalidate_source_file(path)
conn = db.get_connection()
blob = json.loads(conn.execute("SELECT profile_json FROM characters WHERE name=?",
                               ("Kestrel",)).fetchone()[0])
blob.update(personality="OLD", beliefs="stale belief")
conn.execute("UPDATE characters SET profile_json=? WHERE name=?",
             (json.dumps(blob), "Kestrel"))
conn.commit()
prof = get_character_profile("Kestrel")
check("personality: file beats blob", prof.get("personality"), "## Core\nCalm and dry.")
check("beliefs: no longer a source field -> blob value stays",
      prof.get("beliefs"), "stale belief")
check("task", prof.get("task"), "## Now\nMend the nets.")
check("goals: empty file reads empty", prof.get("goals"), "")
(soul / "personality.md").write_text("", encoding="utf-8")
ct.invalidate_source_file(soul / "personality.md")
check("personality: empty file clears the blob value",
      get_character_profile("Kestrel").get("personality"), "")


# ── [2] ────────────────────────────────────────────────────────────────────
def reference_resolve(identifier):
    """The pre-change scan of ``resolve_location``, verbatim."""
    if not identifier:
        return None
    locations = W.list_locations()
    for location in locations:
        if location.get("id") == identifier:
            return location
    for location in locations:
        if location.get("name") == identifier:
            return location
    id_lower = identifier.lower()
    for location in locations:
        loc_name = location.get("name", "").lower()
        if loc_name and (loc_name in id_lower or id_lower in loc_name):
            return location
    return None


print("[2] resolve_location — id, name, substring")
M = W.add_location(name="Market", description="Stalls.")["id"]
L = W.add_location(name="Mill", description="A mill.",
                   rooms=[{"name": "Cellar"}])["id"]
T = W.add_location(name="Old Mill Tavern", description="Ale.")["id"]
Z = W.add_location(name=L, description="Named after L's id.")["id"]
check("list order of M, L, T (ORDER BY name)",
      [loc["id"] for loc in W.list_locations() if loc["id"] != Z], [M, L, T])

CASES = [(L, L), ("Old Mill Tavern", T), ("Mill - Cellar", L), ("tavern", T),
         ("mill", L), (M, M), ("Nowhere", None), ("", None)]


def run_cases(cases, label):
    for ident, want in cases:
        got = W.resolve_location(ident)
        check(f"{label} {ident!r} -> id", (got or {}).get("id"), want)
        check(f"{label} {ident!r} == reference scan", got, reference_resolve(ident))
        check(f"{label} _location_id_of({ident!r})", W._location_id_of(ident), want or "")


run_cases(CASES, "")
check("get_location_by_id(stale string id)", W.get_location_by_id("deadbeef"), None)
check("get_location_by_id(T) name", (W.get_location_by_id(T) or {}).get("name"),
      "Old Mill Tavern")

a, b = W.resolve_location("Mill"), W.resolve_location("Mill")
check("two resolves are equal", a == b, True)
check("…and not the same object", a is b, False)
a["name"] = "mutated"
a["rooms"][0]["name"] = "mutated room"
c = W.resolve_location(L)
check("mutation not visible: name", c.get("name"), "Mill")
check("mutation not visible: room name", [r.get("name") for r in c.get("rooms", [])
                                          if r.get("name") == "Cellar"], ["Cellar"])

# ── [3] ────────────────────────────────────────────────────────────────────
print("[3] a generation bump is seen")
W.rename_location(T, "Old Mill Inn")
run_cases([("Old Mill Tavern", L), ("Old Mill Inn", T)], "after rename")
Q = W.add_location(name="Quarry", description="Stone.")["id"]
run_cases([("Quarry", Q)], "after add")
check("delete M", W.delete_location_row(M), True)
run_cases([(M, None), ("Market", None)], "after delete")

W.list_locations()   # warm
gen = W.world_generation()
W._bump_world_generation()
W._fill_world_cache([{"id": "ghost", "name": "Ghost"}], gen)
check("a fill captured before a bump does not publish",
      W._world_cache["texts"] is None and W._world_cache["lookup"] is None, True)
check("…and the next read is the real world", W.resolve_location("Ghost"), None)

# ── [4] ────────────────────────────────────────────────────────────────────
print("[4] _build_lookup refuses what it cannot mirror")
lk = W._build_lookup([{"id": "a1", "name": "Alpha"}, {"id": "b2", "name": 5}],
                     ['{"id": "a1"}', '{"id": "b2"}'])
check("numeric name -> no substring index", lk[2], None)
check("…the exact id index still stands", sorted(lk[0]), ["a1", "b2"])
check("non-dict entry -> no index at all",
      W._build_lookup([{"id": "a1", "name": "Alpha"}, "junk"], ["{}", "{}"]), None)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
