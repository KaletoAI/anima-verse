#!/usr/bin/env python3
"""Smoke: docs/schnittstellen-3d.md agrees with the code that serves it.

Usage:  ./.venv/bin/python scripts/smoke_docs_schnittstellen_3d.py [doc.md]
        (an explicit path checks another revision of the file, e.g. one
         written out with `git show <rev>:docs/schnittstellen-3d.md`)

The contract is referenced from over two thousand places in `app/`,
`client3d/`, `packages/`, `scripts/` and `frontend/` — always by its section
number ("§ A11a", "§ B1"). Three ways that goes wrong, and this file catches
all three:

A) A SECTION NUMBER IS HANDED OUT TWICE. Then "§ A16" means two things and a
   code comment is ambiguous. Every `§`-id in the document must be unique.

B) A REFERENCED SECTION DOES NOT EXIST. Code and smokes keep pointing at a
   number that a rewrite dropped — that is how `§ A19` became a dead link
   (the "Ein Boden" chapters were merged into § A16 while twenty comments
   still named A19). Every id referenced from the repository must resolve,
   either to a real section or to an explicit "entfällt"-stub.

C) A PAYLOAD FIELD IS UNDOCUMENTED OR DOCUMENTED BUT NOT SENT. The two big
   payloads are built HERE, on throwaway storage, and their key sets are
   compared with the lists the spec prints:
     * the worldmap root + the character row (§ A1.3 / § A1.4 / § A11),
     * the scene root and every one of its sub-objects (§ B1).

   The expected sets are NOT hard-coded: the payload side is composed by
   `world_ops.build_worldmap_payload` / `scene_recipe.compose_scene`, the
   documented side is read out of the spec's own tables and code blocks. The
   only hand-written list is OPTIONAL_* — keys that appear when the data
   calls for them and would otherwise look "missing" in a minimal fixture.

FAILS BEFORE / PASSES AFTER
---------------------------
Against the revision before the 2026-09-21 rework this file reports 5 of 18
checks failed — run it yourself:

    git show f6816edf:docs/schnittstellen-3d.md > /tmp/spec_old.md
    ./.venv/bin/python scripts/smoke_docs_schnittstellen_3d.py /tmp/spec_old.md

namely: § A19 referenced from twenty places and defined nowhere; four scene
root keys absent from the § B1 sketch (`boundary`, `extent_m`, `floor_plan`,
`boundary_openings`) and with them the two sub-object field lists; and the
worldmap root enumeration, which listed eleven of the fifteen keys.

Note that check C reads ONE fixed sentence of § A1.3 ("Wurzelfelder des
Payloads … "). That is deliberate: the list has to stay in one identifiable
place, or a reader has to hunt for it, which is how four keys went missing.

No server, no real world: storage and the clip library are redirected to
temporary directories BEFORE the first app import, exactly as
`scripts/smoke_scene_recipe.py` and `scripts/smoke_worldmap_v2.py` do — an
app import that finds no `--world` falls back to `worlds/demo`, whose
`world.db` is tracked in git.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
DOC = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    REPO / "docs" / "schnittstellen-3d.md"

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="docs3d-clips-")

FAILURES = []
CHECKED = 0


def check(label, ok, detail=""):
    global CHECKED
    CHECKED += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------- the doc --
def headings(text):
    """(level, title) per heading, fenced code blocks skipped."""
    out, infence = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            infence = not infence
            continue
        if infence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


#: Sections that exist only as a stub because their number must never be
#: reused — the heading says "Entfällt", the body says where the rule went.
STUB_RE = re.compile(r"^A(1[89]|20)\b")


def doc_ids(text):
    """Every section id the document defines."""
    ids = set()
    for _, title in headings(text):
        m = re.match(r"^([AB]\d+[a-z]?(?:\.\d+)?)[.)\s]", title)
        if m:
            ids.add(m.group(1))
        # "A18–A20. Entfällt …" — one stub heading standing for a range
        m = re.match(r"^A(\d+)[–-]A(\d+)\.", title)
        if m:
            for n in range(int(m.group(1)), int(m.group(2)) + 1):
                ids.add(f"A{n}")
    return ids


def referenced_ids():
    """Every `§ <id>` the repository points at, outside the document itself."""
    import subprocess
    roots = ["app", "client3d/src", "client3d/scripts", "packages", "scripts",
             "frontend/src", "shared"]
    hits = {}
    for root in roots:
        d = REPO / root
        if not d.is_dir():
            continue
        for path in d.rglob("*"):
            if path.suffix not in (".py", ".ts", ".tsx", ".mjs", ".js", ".md"):
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                txt = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r"§\s*([AB]\d+[a-z]?(?:\.\d+)?)", txt):
                hits.setdefault(m.group(1), str(path.relative_to(REPO)))
    return hits


# ------------------------------------------------------- the two payloads --
def worldmap_payload():
    """Build a worldmap payload on throwaway storage (seed by hand)."""
    from app.core import paths
    paths.init(Path(tempfile.mkdtemp(prefix="docs3d-world-")))
    from app.core import db
    db.init_schema()
    from app.core.world_ops import build_worldmap_payload
    from app.models.world import (_load_world_data, _save_world_data,
                                  add_location)
    add_location("Inn", "inn")
    data = _load_world_data()
    for loc in data["locations"]:
        loc["pos_x"], loc["pos_z"], loc["yaw_deg"] = 50.0, 50.0, 90.0
        loc["map3d"] = {
            "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
            "plan_width_m": 10.0,
            "boundary_openings": [{"edge": 0, "at": 0.5, "width_m": 2}],
        }
        loc["rooms"] = [{"id": "r1", "name": "R1",
                         "layout": {"x": -4, "y": -4, "w": 4, "d": 3,
                                    "level": 0}}]
    _save_world_data(data)
    return build_worldmap_payload(show_all=True)


def scene_payload():
    """Compose a scene from a hand-built location (no world, no DB)."""
    from app.core import scene_recipe
    fixture = {
        "id": "loc",
        "map3d": {
            "plan_width_m": 10.0, "storey_height_m": 3.0,
            "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
            "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
            "boundary_openings": [{"edge": 0, "at": 0.5, "width_m": 2.0}],
            "elevator": [3.0, -3.0], "level_floors": {"0": "parquet"},
            "stairs": [{"at": [2, -2], "dir_deg": 90, "from_level": 0}],
        },
        "rooms": [
            {"id": "a", "name": "A", "layout": {
                "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
                "surfaces": {"floor": "wood", "wall": "plaster"},
                "openings": [
                    {"edge": 0, "at": 0.5, "type": "window",
                     "width_m": 2.0, "height_m": 1.2, "sill_m": 0.9},
                    {"edge": 2, "at": 0.5, "type": "door",
                     "width_m": 1.0, "height_m": 2.1, "to": "outside"},
                ]}},
            {"id": "garden", "name": "G", "layout": {
                "x": -4.0, "y": 1.0, "w": 3.0, "d": 2.0, "level": 0,
                "always_visible": True, "surfaces": {"floor": "grass"}}},
            {"id": "up", "name": "U", "layout": {
                "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 1,
                "surfaces": {"floor": "wood"}}},
        ],
    }
    return scene_recipe.compose_scene(fixture, plan_width_m=10.0)


# ------------------------------------------------- what the spec promises --
def worldmap_root_fields(text):
    """§ A1.3 prints the root keys as one back-ticked enumeration."""
    m = re.search(r"\*\*Wurzelfelder des Payloads[^*]*\*\*(.*?)\n\n",
                  text, re.S)
    if not m:
        return set()
    return set(re.findall(r"`([a-z_]+)`", m.group(1)))


def character_row_fields(text):
    """§ A1.4 prints the character row in payload order."""
    m = re.search(r"Die Reihenfolge lautet(.*?)\n\n", text, re.S)
    if not m:
        return set()
    return set(re.findall(r"`([a-z_]+)`", m.group(1)))


def travel_fields(text):
    """§ A1.4's `travel` row lists the block's fields."""
    m = re.search(r"\| `travel` \|(.*)", text)
    if not m:
        return set()
    head = m.group(1)[:m.group(1).find("—")]
    return set(re.findall(r"`([a-z_]+)`", head))


def scene_block(text):
    """The ``` block under § B1 — the scene payload sketch."""
    i = text.index("## B1. `GET /play/locations/{location_id}/scene`")
    j = text.index("```", i)
    k = text.index("```", j + 3)
    return text[j + 3:k]


def scene_root_fields(text):
    """Top-level keys of the § B1 sketch: a name at indent 2, then `,` or `:`."""
    out = set()
    for line in scene_block(text).split("\n"):
        head = line.split("#")[0]
        if not re.match(r"^  [a-z_]", head):
            continue
        # "  k, storey_m," lists two keys on one line
        for m in re.finditer(r"([a-z_]+)\s*[:,]", head[:head.find("{") + 1
                                                        if "{" in head
                                                        else len(head)]):
            out.add(m.group(1))
            if head.lstrip().startswith(m.group(1)) and ":" in head:
                break
    return out


def scene_sub_fields(text, key):
    """The field names the sketch lists for one sub-object (e.g. `plates`)."""
    block = scene_block(text)
    m = re.search(r"^  %s:?\s*\[?\s*\{(.*?)\}\s*\]?" % re.escape(key),
                  block, re.S | re.M)
    if not m:
        return set()
    body = m.group(1)
    # strip the trailing "# …" comment of every line
    body = "\n".join(l.split("#")[0] for l in body.split("\n"))
    return set(re.findall(r"(?:^|[,\s{])([a-z_][a-z0-9_]*)\??\s*(?::|,|$)",
                          body, re.M))


#: Keys the composer only ships when the data calls for them. A minimal
#: fixture does not produce them, so "documented but not emitted" is right.
OPTIONAL_SCENE_ROOT = {"area_detail"}
#: Sub-object keys that only a richer fixture produces (a prop with a mesh, a
#: hull door, an area location). Their presence is specified in Teil C.
OPTIONAL_SUB = {
    "plates": set(),
    "walls": set(),
    "stairs": set(),
    "doorways": {"hull", "outward_normal"},
    "models": {"width_estimated", "clip_outline", "cutouts", "surface",
               "variant", "model_variants", "walkable", "cut_plane",
               "leaf_bbox", "slots", "door", "hinge", "opening", "swing",
               "size_m", "at_world", "display", "walk_y_world",
               "ground_offset_m"},
    "rooms": {"overlay"},
    "markers": {"facing", "tilt", "roll", "anchor", "diorama"},
    "corridors": set(),
    "floor_plan": {"water_level_effective"},
    "boundary_openings": set(),
}


def main():
    text = DOC.read_text(encoding="utf-8")

    print("\nA) every § number is handed out exactly once")
    seen, dups = set(), []
    for _, title in headings(text):
        m = re.match(r"^([AB]\d+[a-z]?(?:\.\d+)?)[.)\s]", title)
        if m:
            if m.group(1) in seen:
                dups.append(m.group(1))
            seen.add(m.group(1))
    check("no duplicate § id", not dups, str(dups))
    check("the document defines sections at all", len(seen) > 40, str(len(seen)))

    print("\nB) every § the repository references exists in the document")
    have = doc_ids(text)
    refs = referenced_ids()
    dead = {k: v for k, v in refs.items() if k not in have}
    check(f"no dead § reference ({len(refs)} ids referenced)", not dead,
          "; ".join(f"§ {k} (e.g. {v})" for k, v in sorted(dead.items())))

    print("\nC) the worldmap payload (§ A1.3 / § A1.4 / § A11)")
    wm = worldmap_payload()
    doc_root = worldmap_root_fields(text)
    emitted = set(wm)
    # `backdrop` is documented as an optional key and is off in this fixture
    check("no root key missing from the spec", not (emitted - doc_root),
          str(sorted(emitted - doc_root)))
    check("the spec invents no root key", not (doc_root - emitted - {"backdrop"}),
          str(sorted(doc_root - emitted - {"backdrop"})))

    from app.core.world_ops import build_worldmap_payload  # noqa: F401
    # a character row needs a real character; compare the documented order
    # with the keys the builder writes, read off the source instead of a run
    import inspect
    from app.core import world_ops
    src = inspect.getsource(world_ops.build_worldmap_payload)
    row = src[src.index("characters.append({"):]
    row = row[:row.index("\n        })")]
    row_keys = set(re.findall(r'^\s{12}"([a-z_]+)":', row, re.M))
    row_keys |= set(re.findall(r'\{"([a-z_]+)": _model_sig\}', row))
    doc_row = character_row_fields(text)
    check("no character-row key missing from the spec",
          not (row_keys - doc_row), str(sorted(row_keys - doc_row)))
    check("the spec invents no character-row key",
          not (doc_row - row_keys), str(sorted(doc_row - row_keys)))

    travel = src[src.index('travel = {'):]
    travel = travel[:travel.index("\n                }")]
    travel_keys = set(re.findall(r'^\s{20}"([a-z_]+)":', travel, re.M))
    doc_travel = travel_fields(text)
    check("no travel key missing from the spec",
          not (travel_keys - doc_travel), str(sorted(travel_keys - doc_travel)))
    check("the spec invents no travel key",
          not (doc_travel - travel_keys), str(sorted(doc_travel - travel_keys)))

    print("\nD) the scene payload (§ B1)")
    sc = scene_payload()
    doc_scene = scene_root_fields(text)
    emitted = set(sc)
    check("no scene root key missing from the spec",
          not (emitted - doc_scene), str(sorted(emitted - doc_scene)))
    check("the spec invents no scene root key",
          not (doc_scene - emitted - OPTIONAL_SCENE_ROOT),
          str(sorted(doc_scene - emitted - OPTIONAL_SCENE_ROOT)))

    for key, optional in OPTIONAL_SUB.items():
        value = sc.get(key)
        if isinstance(value, list):
            got = set()
            for item in value:
                if isinstance(item, dict):
                    got |= set(item)
        elif isinstance(value, dict):
            got = set(value)
        else:
            got = set()
        if not got:
            continue
        documented = scene_sub_fields(text, key) | optional
        check(f"`{key}[]`: every emitted field is documented",
              not (got - documented), str(sorted(got - documented)))

    print()
    print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        for f in FAILURES:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
