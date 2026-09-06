#!/usr/bin/env python3
"""Smoke run for the room-furnish state machine (plan-furnish-v2.md § 2, § 6 E6).

No test framework, no LLM, no GPU: the three ``furnish_*`` tasks are
monkeypatched with canned answers, so one run ticks the whole machine

    start → proposal_ready → confirm → placing → review_ready
          → accept (the placements land in ``layout.props``) → generating
          → the row is gone

against a throwaway world in a temp directory. Everything else is the real
code path (templates, validation, solver, DB, layout sanitizer). The mesh
generation is stubbed at ``props.trigger_generation`` (a GLB is attached
instantly) — the phase around it is the real one.

PLACING COMES BEFORE GENERATING (E6). A need without a library piece is
placed under the temporary id ``need:<key>`` with its own dimensions; only
``accept`` turns it into a prop, rewrites that id in the placements and
starts the meshes. The rows below walk exactly that order.

Every expected number is derived by hand from the rule:

  * 4 × 4 m room, table 1.2 × 0.8 m, anchor ``wall_n`` facing the room → the
    centre of the usable stretch, x = 1.2/2 + 0.5 × (4 − 1.2) = 2.0 m, pushed
    off the wall by depth/2 + FLOOR_GAP_M = 0.4 + 0.05 = 0.45 m.
  * a wall piece 0.6 m high whose kind says "painting" gets the E2 fallback
    base BEFORE the call: centre 1.5 − h/2 = 1.5 − 0.3 = 1.2 m, and the
    solver stores that as its ``offset_y``. A shelf hangs at a flat 1.3, an
    unclassified 0.4 m piece centres at 1.5 too → 1.5 − 0.2 = 1.3, and a
    1.0 m mirror centres at 1.6 → 1.6 − 0.5 = 1.1.
  * the candle stands ON the table: the child frame's raster starts at the
    support's middle, inset by half the candle — 0.08/2 = 0.04 ≤ the 0.15 m
    step, so the first cell is (0, 0) and the candle is stored ``at [0, 0]``,
    ``on`` the table's placement id, with NO ``offset_y``. A child's
    ``offset_y`` is a TRIM above its support's top (§ 4), and the top itself
    (0 + 0.75 m) is composed by ``room_recipe`` out of
    ``props.stack_on_support`` — storing it would be that formula's second
    copy.
  * the yard's boundary (−6,−6)…(4,4) is a 10 × 10 m square, so the solver
    frame is 0…10 and the same wall arithmetic gives x = 0.6 + 0.5 × 8.8 =
    5.0, y = 0.4 + 0.05 = 0.45 → stored [5.0 − 6, 0.45 − 6] = [−1.0, −5.55].
    The candle on it keeps [0, 0]: a child's metres are its SUPPORT's, and
    the origin shift must not touch them (task 2 note).
  * a match is refused when the mount differs or when the largest dimension
    is more than DIM_TOLERANCE = 40 % of the need's away from it: a need of
    0.5 m against a 1.2 m table is 0.7 m off, and 0.7 > 0.4 × 0.5 = 0.2.
  * build only what was PLACED (controller ruling): a run whose plan names one
    of two built needs creates exactly ONE prop — 6 props before, 7 after —
    and the accept's notification names the other kind. The empty-accept case
    is the same rule with an empty placement set: 0 props, 0 generating.
  * a job stranded in `generating` (accepted, its mesh delivered by the
    persistent queue while no thread watched) is FINISHED, not stuck: nothing
    is pending, so continue/discard/a plain status read each close the row and
    the room can be furnished again. Reached in the smoke by accepting with
    the orchestrator frozen and then attaching the GLB from outside.
  * a layout write that fails must not cost the created props: accept persists
    their ids on the row BEFORE the write, so the refused accept leaves 8 props
    and the retry still leaves 8 — AND the retry's layout entry names that very
    prop id. The retry re-reads the placements from the row, where they still
    say "need:n1", so the rewrite map has to cover every built need that has a
    prop, not only the props this call made.
  * the repair loop (canned solver results, section 2c): run 1 places
    floor 1/2 and wall 1/1 and fails one floor and one surface piece, so two
    passes have errors and exactly two re-plan calls follow. The floor
    re-plan places 0 of 2 — 0 < 1, so it is discarded; the surface re-plan
    places 1 of 1 — 1 ≥ 0 and 0 ≤ 1, so it is kept. Final: 3 placed, 1
    unplaced, phase counts floor 1/1, wall 1/0, ceiling 0/0, surface 1/0.

Usage:  ./.venv/bin/python scripts/smoke_room_furnish.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="furnish-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import (db, furnish_needs, furnish_place,  # noqa: E402
                      furnish_solver, props, room_furnish, surface_textures)
from app.core.timeutils import utc_now_iso  # noqa: E402
from app.models.notifications import get_notifications  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, get_room_by_id,
)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def make_prop(name: str, w: float, d: float, h: float, *, category: str = "table",
              mount: str = "", model: bool = True) -> str:
    """A library prop WITH a model file (has_model → the job may place it).
    Goes through the real upload path so the mesh lands in the gallery and is
    selected for the default tier (plan-3d-lod-und-betreten.md)."""
    prop = props.create_prop(name=name, category=category, width_m=w,
                             depth_m=d, height_m=h, mount=mount)
    if model:
        props.save_uploaded_glb(prop["id"], b"glTF-stub")
    return prop["id"]


def need(key="n1", kind="dining chair", **kw):
    """One raw need as the LLM would answer it — the validator's input."""
    entry = {"key": key, "kind": kind, "category": "chair", "count": 4,
             "mount": "floor", "width_m": 0.45, "depth_m": 0.5,
             "height_m": 0.9, "style": "rustic oak", "description": "a chair",
             "marker": None, "key_areas": [], "from_description": False}
    entry.update(kw)
    return entry


def fake_llm(answers):
    """Replace room_furnish's LLM hop with canned answers per task. An answer
    that IS an exception is raised instead (error-path coverage); a callable
    is asked for its answer with the rendered user prompt in hand (the ids of
    freshly generated props are only known then)."""
    calls = []

    def _stub(task, system_prompt, user_prompt, label):
        calls.append((task, user_prompt))
        answer = answers[task]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(user_prompt)
        return answer

    room_furnish._llm_json = _stub
    return calls


def fake_surface_library():
    """The surface-texture library lives under ``shared/`` and is the same for
    every world — a smoke must not write into it. The two kinds this run needs
    are handed to the reader instead; ``room_furnish._surface_kinds`` (the
    code under test) reads them through the very function it always reads."""
    surface_textures.list_textures = lambda: [
        {"kind": "oak_planks", "name": "Oak planks", "url": "/x.png"},
        {"kind": "plaster_wall", "name": "Plaster", "url": "/y.png"},
    ]


def instant_meshes():
    """Stub the mesh chain: a generated prop gets its GLB immediately, so the
    generation phase is walked without an image or a mesh backend."""
    def _trigger(prop_id, **_kw):
        props.save_uploaded_glb(prop_id, b"glTF-stub")
        return True
    props.trigger_generation = _trigger


def last_prompt(calls, task):
    for t, prompt in reversed(calls):
        if t == task:
            return prompt
    return ""


def ref_for(prompt: str, name: str) -> str:
    """The catalog ref (#n) the rendered match prompt gave one prop — which
    only works because every catalog entry IS its own line."""
    for line in prompt.splitlines():
        if line.startswith("#") and f"| {name} |" in line:
            return line.split(" |")[0].strip()
    return ""


def suppress_spawn():
    """Freeze the orchestrator: the phase function is never started, so a
    state the job only passes through can be inspected. Answers the real
    ``_spawn`` for the caller to put back."""
    real = room_furnish._spawn
    room_furnish._spawn = lambda room_id, phase, label: True
    return real


def notification_texts():
    return [n.get("content") or "" for n in get_notifications(limit=20)]


def wait_for(states, tries=80, job="smokeroom"):
    for _ in range(tries):
        status = room_furnish.get_status(job)
        if status is None or status["state"] in states:
            return status
        time.sleep(0.1)
    return room_furnish.get_status(job)


def main() -> int:
    db.init_schema()
    instant_meshes()
    fake_surface_library()
    print(f"World: {WORLD}")

    # ── The library ─────────────────────────────────────────────────────
    table = make_prop("Table", 1.2, 0.8, 0.75)
    chair = make_prop("Chair", 0.5, 0.5, 0.9, category="chair")
    sconce = make_prop("Wall Sconce", 0.2, 0.15, 0.4, category="lamp",
                       mount="wall")
    make_prop("Evergreen Pine", 2.0, 2.0, 5.0, category="Evergreen Trees")
    library = {p["id"]: p for p in props.list_props()}

    # ── 1. Need validation (pure) ───────────────────────────────────────
    print("\n  need validation")
    raw_needs = [
        need("x9", "dining chair", count=40),                # count clamped
        need("x9", "wall clock", mount="roof"),              # unknown mount
        need("x3", "giant table", width_m=7.0),              # dims out of range
        need("x4", "nameless", description=""),              # no subject
        {"kind": "", "description": "d"},                    # nothing at all
    ] + [need(f"y{i}", f"filler {i}") for i in range(20)]
    got, dropped = furnish_needs.valid_needs(raw_needs, ["seat", "bed"])
    check("keys are re-minted n1..nN in order",
          [n["key"] for n in got[:3]] == ["n1", "n2", "n3"],
          json.dumps([n["key"] for n in got[:3]]))
    check("count 40 is clamped to 12", got[0]["count"] == 12, str(got[0]["count"]))
    check("mount 'roof' falls back to floor", got[1]["mount"] == "floor",
          got[1]["mount"])
    check("a 7 m piece is dropped with a reason",
          any(d["kind"] == "giant table" and "size" in d["reason"]
              for d in dropped), json.dumps(dropped))
    check("a need without a description is dropped",
          any(d["kind"] == "nameless" for d in dropped), json.dumps(dropped))
    check("the list is capped at MAX_NEEDS",
          len(got) == furnish_needs.MAX_NEEDS == 16, str(len(got)))
    yard_needs, yard_dropped = furnish_needs.valid_needs(
        [need("n1", "wall torch", mount="wall"),
         need("n2", "pendant lamp", mount="ceiling"),
         need("n3", "bench")], ["seat"], is_yard=True)
    check("the yard keeps only what it can hold",
          [n["kind"] for n in yard_needs] == ["bench"],
          json.dumps([n["kind"] for n in yard_needs]))
    check("and says why the wall piece went",
          [d["reason"] for d in yard_dropped]
          == ["the yard has no walls/ceiling"] * 2, json.dumps(yard_dropped))
    check("key_areas keep only real kinds",
          furnish_needs.valid_needs(
              [need(key_areas=["picture", "sticker"])], [])[0][0]["key_areas"]
          == ["picture"])

    # ── 2. Catalog + match validation (pure) ────────────────────────────
    print("\n  catalog and match validation")
    catalog, by_ref = furnish_needs.build_catalog(library, indoor=True)
    names = [c["name"] for c in catalog]
    check("an indoor catalog has no outdoor category",
          "Evergreen Pine" not in names, json.dumps(names))
    check("an open-air catalog keeps it",
          "Evergreen Pine" in [c["name"] for c in
                               furnish_needs.build_catalog(
                                   library, indoor=False)[0]])
    check("refs are #n, never the slug",
          [c["ref"] for c in catalog] == [f"#{i + 1}" for i in range(len(catalog))],
          json.dumps([c["ref"] for c in catalog]))
    table_ref = next(c["ref"] for c in catalog if c["name"] == "Table")
    sconce_ref = next(c["ref"] for c in catalog if c["name"] == "Wall Sconce")
    match_needs = [
        need("n1", "table", mount="floor", width_m=1.2, depth_m=0.8, height_m=0.75),
        need("n2", "wall picture", mount="wall", width_m=0.5, depth_m=0.05,
             height_m=0.6),
        need("n3", "stool", mount="floor", width_m=0.5, depth_m=0.5, height_m=0.5),
        need("n4", "chest", mount="floor"),
    ]
    matches = furnish_needs.valid_matches(
        [{"need": "n1", "ref": table_ref},     # fits: same mount, same size
         {"need": "n2", "ref": table_ref},     # wall need vs floor prop
         {"need": "n3", "ref": table_ref},     # 1.2 m vs 0.5 m → 140 % > 40 %
         {"need": "n4", "ref": "#99"}],        # no such ref
        match_needs, by_ref, library)
    check("a fitting match keeps the prop id", matches.get("n1") == table,
          json.dumps(matches))
    check("a mount mismatch is refused", "n2" not in matches)
    check("a size mismatch is refused", "n3" not in matches)
    check("an unknown ref is refused", "n4" not in matches)
    check("the wall sconce matches the wall need",
          furnish_needs.valid_matches([{"need": "n2", "ref": sconce_ref}],
                                      match_needs, by_ref, library)
          .get("n2") == sconce)
    furnish_needs.attach_matches(match_needs, matches)
    check("build is derived from the match, never trusted",
          [n["build"] for n in match_needs] == [False, True, True, True],
          json.dumps([n["build"] for n in match_needs]))
    check("an unknown surface kind is dropped",
          furnish_needs.valid_surfaces({"floor": "oak_planks", "wall": "nope"},
                                       ["oak_planks", "plaster_wall"])
          == {"floor": "oak_planks"})

    # ── 2b. Wall base defaults (pure, E2) ───────────────────────────────
    # Fallback BEFORE the LLM call: the keyword table over kind/category/name.
    # picture-like → centre 1.5, mirror → centre 1.6, shelf-like → flat 1.3,
    # lamp-like → flat 1.6, anything else → centre 1.5. `base = centre − h/2`.
    print("\n  wall base defaults")
    check("a 0.6 m painting hangs at 1.5 − 0.3 = 1.2",
          furnish_place.wall_base_default(kind="framed painting",
                                          category="decor", height_m=0.6) == 1.2,
          str(furnish_place.wall_base_default(kind="framed painting",
                                              category="decor", height_m=0.6)))
    check("a wall shelf hangs at a flat 1.3",
          furnish_place.wall_base_default(kind="wall shelf",
                                          category="storage",
                                          height_m=0.3) == 1.3)
    check("an unclassified 0.4 m piece centres at 1.5 → 1.3",
          furnish_place.wall_base_default(kind="odd thing",
                                          height_m=0.4) == 1.3)
    check("a sconce hangs at a flat 1.6",
          furnish_place.wall_base_default(kind="iron sconce", category="lamp",
                                          height_m=0.4) == 1.6)
    check("a 1.0 m mirror centres at 1.6 → 1.1",
          furnish_place.wall_base_default(kind="mirror", category="decor",
                                          height_m=1.0) == 1.1)
    base_items = furnish_place.build_items(
        [need("n1", "framed painting", mount="wall", width_m=0.5, depth_m=0.05,
              height_m=0.6),
         need("n2", "oak table", mount="floor", width_m=1.2, depth_m=0.8,
              height_m=0.75)], {})
    check("build_items gives the wall piece its base, the floor piece none",
          [it["base_m"] for it in base_items] == [1.2, None],
          json.dumps([it["base_m"] for it in base_items]))
    check("an unbuilt need travels under its temporary id",
          [it["id"] for it in base_items] == ["need:n1", "need:n2"],
          json.dumps([it["id"] for it in base_items]))

    # ── 2c. The repair loop, one call per pass (pure, B6) ───────────────
    # Canned solver results (derivation in the module docstring): run 1 fails
    # one floor and one surface piece → two re-plan calls; the floor re-plan
    # is worse and is discarded, the surface re-plan is better and is kept.
    print("\n  per-pass repair")
    repair_needs = [
        need("n1", "oak table", category="table", count=2, mount="floor",
             width_m=1.2, depth_m=0.8, height_m=0.75),
        need("n2", "framed painting", category="decor", count=1, mount="wall",
             width_m=0.5, depth_m=0.05, height_m=0.6),
        need("n3", "candle", category="tableware", count=1, mount="surface",
             width_m=0.08, depth_m=0.08, height_m=0.2)]
    repair_items = furnish_place.build_items(repair_needs, {})
    p_floor = {"prop_id": "need:n1", "id": "p1", "at": [2.0, 0.45], "yaw": 0.0}
    p_wall = {"prop_id": "need:n2", "id": "p2", "at": [2.0, 0.03],
              "yaw": 0.0, "offset_y": 1.2}
    p_surface = {"prop_id": "need:n3", "id": "p3", "at": [0.0, 0.0],
                 "yaw": 0.0, "offset_y": 0.75, "on": "p1"}
    e_floor = {"name": "need:n1", "pass": "floor",
               "reason": "no free spot on wall_n — try wall_e or another wall"}
    e_surface = {"name": "need:n3", "pass": "surface",
                 "reason": "surface of 'need:n1' is full — use another support"}
    canned = [
        {"placed": [p_floor, p_wall], "unplaced": [e_floor, e_surface]},
        {"placed": [p_wall], "unplaced": [e_floor, e_floor, e_surface]},
        {"placed": [p_floor, p_wall, p_surface], "unplaced": [e_floor]},
    ]
    solver_calls = []

    def _canned_solve(**kw):
        solver_calls.append(kw)
        return json.loads(json.dumps(canned[min(len(solver_calls) - 1,
                                                len(canned) - 1)]))

    ask_calls = []

    def _ask(system_prompt, user_prompt, suffix):
        ask_calls.append((suffix, system_prompt, user_prompt))
        return {"plan": [{"prop": it["id"], "count": it["count"],
                          "anchor": "center", "ref": None, "facing": "room"}
                         for it in repair_items]}

    real_solve = furnish_solver.solve
    furnish_solver.solve = _canned_solve
    try:
        repaired = furnish_place.run(
            room_name="Repair Room", room_description="",
            geom={"outline_m": [[0, 0], [4, 0], [4, 4], [0, 4]], "w_m": 4.0,
                  "d_m": 4.0, "is_rect": True, "openings": []},
            storey_height_m=3.0, items=repair_items,
            props=furnish_place.solver_props(repair_items, {}),
            existing=[], template_existing=[], template_openings=[],
            ask=_ask)
    finally:
        furnish_solver.solve = real_solve
    check("one plan call plus one re-plan per failing pass",
          [c[0] for c in ask_calls]
          == ["", " (re-plan floor)", " (re-plan surface)"],
          json.dumps([c[0] for c in ask_calls]))
    check("a re-plan prompt shows only its own pass's errors",
          "[floor pass]" in ask_calls[1][1]
          and "[surface pass]" not in ask_calls[1][1])
    check("…and says which group is re-planned",
          "Re-plan ONLY the floor group" in ask_calls[1][1])
    check("the other groups reach the re-plan as already standing",
          "(id p1)" in ask_calls[2][2] and "(id p2)" in ask_calls[2][2],
          ask_calls[2][2][:400])
    check("the worse floor re-plan is discarded, the better surface one kept",
          [p["id"] for p in repaired["placed"]] == ["p1", "p2", "p3"],
          json.dumps([p["id"] for p in repaired["placed"]]))
    check("phase_counts are per mount, ceiling separate",
          repaired["phase_counts"] == {"floor": {"placed": 1, "unplaced": 1},
                                       "wall": {"placed": 1, "unplaced": 0},
                                       "ceiling": {"placed": 0, "unplaced": 0},
                                       "surface": {"placed": 1, "unplaced": 0}},
          json.dumps(repaired["phase_counts"]))
    check("three solver runs — one per plan, none extra",
          len(solver_calls) == 3, str(len(solver_calls)))

    # ── 3. A room with a floor plan and a door ──────────────────────────
    # METRIC FIXTURE (contract v6 Nr. 2): a 4 × 4 m room in the NW quadrant of
    # the location, one door in the middle of the south wall.
    loc = add_location("Smoke House", "A test house", rooms=[
        {"id": "smokeroom", "name": "Study", "description": "A quiet study",
         "activity_hint": "reading", "indoor": "indoor", "activities": []}])
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] != loc["id"]:
            continue
        entry["map3d"] = {"plan_width_m": 8.0, "storey_height_m": 3.0}
        entry["rooms"][0]["layout"] = {
            "x": -4.0, "y": -4.0, "w": 4.0, "d": 4.0, "level": 0,
            "openings": [{"edge": "S", "at": 0.5, "width_m": 1.0,
                          "height_m": 2.1, "sill_m": 0, "type": "door"}],
        }
    _save_world_data(data)
    print("\n  room 4.0 × 4.0 m (metres in the layout), one south door")

    answers = {
        "furnish_needs": {
            "needs": [
                need("a", "table", category="table", count=1, mount="floor",
                     width_m=1.2, depth_m=0.8, height_m=0.75,
                     description="a plain oak table"),
                need("b", "wall painting", category="decor", count=1,
                     mount="wall", width_m=0.5, depth_m=0.05, height_m=0.6,
                     description="a framed landscape painting",
                     key_areas=["picture"], from_description=True,
                     marker={"group": "nonsense", "at": [0.5, 0.5, 0.5]}),
                need("c", "candle", category="tableware", count=1,
                     mount="surface", width_m=0.08, depth_m=0.08,
                     height_m=0.2, description="a beeswax candle"),
            ],
            "surfaces": {"floor": "oak_planks", "wall": "does_not_exist"},
        },
        "furnish_match": lambda prompt: {"matches": [
            {"need": "n1", "ref": ref_for(prompt, "Table")},
            {"need": "n2", "ref": None}]},
        # The plan names the two unbuilt pieces by their TEMPORARY ids — no
        # prop exists for them yet (E6), and none has to.
        "furnish_place": {"plan": [
            {"prop": table, "count": 1, "anchor": "wall_n", "ref": None,
             "facing": "room"},
            {"prop": "need:n2", "count": 1, "anchor": "wall_n", "ref": None,
             "facing": "room", "base_m": None},
            {"prop": "need:n3", "count": 1, "anchor": "on", "ref": table,
             "facing": "ref"}]},
    }
    calls = fake_llm(answers)

    # ── start → proposal_ready ──────────────────────────────────────────
    room_furnish.start("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    check("state proposal_ready", status["state"] == "proposal_ready",
          status.get("error") or "")
    proposal = status["proposal"]
    needs_out = proposal["needs"]
    check("needs prompt carries the metre size",
          "4.0 × 4.0 m" in last_prompt(calls, "furnish_needs"))
    check("needs prompt never shows the library",
          "Table" not in last_prompt(calls, "furnish_needs"))
    match_prompt = last_prompt(calls, "furnish_match")
    check("match prompt uses refs, not slugs",
          "#1 |" in match_prompt and table not in match_prompt,
          match_prompt[-300:])
    # The trim_blocks trap: a loop row ending in a block tag loses its
    # newline and the whole catalog collapses into ONE line. Three indoor
    # props (the outdoor one is filtered) must be three lines.
    catalog_lines = [ln for ln in match_prompt.splitlines() if ln.startswith("#")]
    check("one catalog entry per line",
          len(catalog_lines) == len(catalog) == 3, json.dumps(catalog_lines))
    check("the indoor match prompt drops the outdoor prop",
          "Evergreen Pine" not in match_prompt)
    check("the table need took the library piece",
          needs_out[0]["prop_id"] == table and needs_out[0]["build"] is False,
          json.dumps(needs_out[0]))
    check("the painting is built",
          needs_out[1]["prop_id"] is None and needs_out[1]["build"] is True)
    check("an invalid marker group is dropped",
          needs_out[1]["marker"] is None)
    check("surfaces keep only known kinds",
          proposal["surfaces"] == {"floor": "oak_planks"},
          json.dumps(proposal["surfaces"]))

    # A second job for the same room is refused.
    try:
        room_furnish.start("smokeroom")
        check("second start refused", False)
    except room_furnish.FurnishError as e:
        check("second start refused", e.status == 409, e.message)

    # ── confirm → placing → review_ready (NOTHING generated yet, E6) ────
    props_before_confirm = len(props.list_props())
    room_furnish.confirm("smokeroom", proposal)
    status = wait_for(("review_ready", "error"))
    check("state review_ready", status["state"] == "review_ready",
          status.get("error") or "")
    check("placing created no props — that is accept's job",
          len(props.list_props()) == props_before_confirm,
          str(len(props.list_props())))
    check("progress stays 0/0 until the meshes are ordered",
          status["progress"] == {"done": 0, "total": 0},
          json.dumps(status["progress"]))
    check("the built needs still carry no prop id",
          [n["prop_id"] for n in status["proposal"]["needs"]]
          == [table, None, None],
          json.dumps([n["prop_id"] for n in status["proposal"]["needs"]]))
    placed = status["placements"]["placed"]
    check("solver placed all three pieces", len(placed) == 3,
          json.dumps(status["placements"]))
    check("phase counts are grouped by mount",
          status["phase_counts"] == {"floor": {"placed": 1, "unplaced": 0},
                                     "wall": {"placed": 1, "unplaced": 0},
                                     "ceiling": {"placed": 0, "unplaced": 0},
                                     "surface": {"placed": 1, "unplaced": 0}},
          json.dumps(status["phase_counts"]))
    check("placements are layout.props entries",
          all(set(p) <= {"prop_id", "id", "at", "yaw", "offset_y", "on",
                         "variant"} and len(p["at"]) == 2
              for p in placed))
    check("every placement carries a minted id",
          len({p["id"] for p in placed}) == len(placed),
          json.dumps([p.get("id") for p in placed]))
    check("door zone kept free",
          all(p["at"][1] < 3.4 for p in placed if not p.get("on")),
          json.dumps([p["at"] for p in placed]))
    # Hand-derived (see the module docstring): the table centres on its wall
    # at [2.0, 0.45]; nothing pushes it off — the only zone is the south
    # door's, at y ≥ 3.4 m.
    table_place = next(p for p in placed if p["prop_id"] == table)
    check("the table stands centred on its wall",
          table_place["at"] == [2.0, 0.45], json.dumps(table_place["at"]))
    # The painting is a WALL piece placed under its PLACEHOLDER id, hanging
    # at the base the keyword table handed the plan: 1.5 − 0.6/2 = 1.2 m.
    painting = next(p for p in placed if p["prop_id"] == "need:n2")
    check("the unbuilt wall piece is placed under its temporary id",
          painting.get("offset_y") == 1.2, json.dumps(painting))
    # The candle is a CHILD: stored in the table's frame, first raster cell.
    candle = next(p for p in placed if p["prop_id"] == "need:n3")
    check("the surface piece is stored in its support's frame, trim 0",
          candle.get("on") == table_place["id"] and candle["at"] == [0.0, 0.0]
          and "offset_y" not in candle, json.dumps(candle))
    place_prompt = last_prompt(calls, "furnish_place")
    check("place prompt lists the door on wall S",
          "on wall S" in place_prompt, place_prompt[:300])
    check("place prompt groups the pieces by mount",
          all(head in place_prompt for head in (
              "Floor pieces to place:", "Wall pieces to place",
              "Ceiling pieces to place:", "Surface pieces to place")),
          place_prompt[:300])
    check("a review notification names the pass split",
          any("floor 1/1, wall 1/1, surface 1/1" in t
              for t in notification_texts()),
          json.dumps(notification_texts()[:3]))

    # ── accept → props are created, ids rewritten, meshes ordered ───────
    # The orchestrator is frozen here so the `generating` state can be looked
    # at — a restart in exactly that state is what the rows below simulate.
    real_spawn = suppress_spawn()
    accepted = room_furnish.accept("smokeroom")
    check("accept reports what it placed and what it now generates",
          accepted == {"status": "accepted", "placed": 3, "generating": 2},
          json.dumps(accepted))
    status = room_furnish.get_status("smokeroom")
    check("the job waits in generating", status["state"] == "generating",
          json.dumps(status["state"]))
    check("the row remembers that the layout write happened",
          status["placements"].get("accepted") is True)
    built = [n for n in status["proposal"]["needs"] if n["build"]]
    check("both built needs got a prop", len(built) == 2
          and all(n.get("prop_id") for n in built), json.dumps(built))
    new_prop = props.get_prop(built[0]["prop_id"])
    check("the new prop carries the need's mount",
          new_prop.get("mount") == "wall", json.dumps(new_prop.get("mount")))
    check("…and its key areas",
          list(new_prop.get("key_areas") or []) == ["picture"],
          json.dumps(new_prop.get("key_areas")))
    check("…and is named after the kind",
          new_prop.get("name") == "Wall Painting", new_prop.get("name") or "")
    room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == loc["id"]), "smokeroom")
    stored = room["layout"].get("props") or []
    check("layout.props holds the accepted placements",
          len(stored) == 3, json.dumps(stored))
    check("no placeholder id survived into the layout",
          not any(str(p.get("prop_id") or "").startswith("need:")
                  for p in stored),
          json.dumps([p.get("prop_id") for p in stored]))
    check("the child still names its support by PLACEMENT id",
          next(p for p in stored if p.get("on"))["on"] == table_place["id"],
          json.dumps([p.get("on") for p in stored]))
    check("progress counts the built needs once they are ordered",
          room_furnish.get_status("smokeroom")["progress"]
          == {"done": 0, "total": 2},
          json.dumps(room_furnish.get_status("smokeroom")["progress"]))
    check("discarding a room whose meshes are running is refused",
          _refused_with(room_furnish.discard, 409, "smokeroom"))
    check("a restart resumes into the mesh phase",
          room_furnish._resume_phase(
              room_furnish._get_row("smokeroom")) == "generate")

    # ── generating → the row is gone, nothing was created twice ─────────
    props_before_resume = len(props.list_props())
    room_furnish._spawn = real_spawn
    room_furnish.resume("smokeroom")
    status = wait_for(("error",), tries=100)
    check("the job closes itself when every mesh is there", status is None,
          json.dumps(status))
    check("the resume created no second prop",
          len(props.list_props()) == props_before_resume,
          str(len(props.list_props())))
    room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == loc["id"]), "smokeroom")
    check("and appended the placements only once",
          len(room["layout"].get("props") or []) == 3,
          json.dumps(room["layout"].get("props")))
    check("sanitizer kept prop_id/at/yaw",
          all(p.get("prop_id") and len(p.get("at") or []) == 2
              for p in room["layout"]["props"]))
    check("a mesh notification closes the run",
          any("Meshes ready — 2 models" in t for t in notification_texts()),
          json.dumps(notification_texts()[:3]))

    # ── error → retry → reset, and the surfaces gate ────────────────────
    print("\n  error, retry and the surfaces gate")
    answers["furnish_needs"] = room_furnish.FurnishError("stage 1 exploded")
    room_furnish.start("smokeroom")
    status = wait_for(("error", "proposal_ready"))
    check("failed stage 1 lands in error", status["state"] == "error")
    check("the message is persisted", status["error"] == "stage 1 exploded")
    check("a dead job counts as stalled, not running",
          not status["running"] and not status["stalled"])
    # The room now HAS a floor kind — the surface proposal must stay away.
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] == loc["id"]:
            entry["rooms"][0]["layout"]["surfaces"] = {"floor": "oak_planks"}
    _save_world_data(data)
    answers["furnish_needs"] = {
        "needs": [need("a", "stool", count=2, mount="floor", width_m=0.4,
                       depth_m=0.4, height_m=0.5, description="a low stool")],
        "surfaces": {"floor": "plaster_wall", "wall": "plaster_wall"}}
    answers["furnish_match"] = {"matches": []}
    room_furnish.retry("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    check("retry re-enters at stage 1", status["state"] == "proposal_ready",
          status.get("error") or "")
    check("a dressed room gets no surface proposal",
          status["proposal"]["surfaces"] is None,
          json.dumps(status["proposal"]["surfaces"]))
    check("the prompt asks for null instead of a kind list",
          'answer "surfaces": null' in last_prompt(calls, "furnish_needs"))
    check("the room's own furnishing is known to the LLM",
          "1× Table" in last_prompt(calls, "furnish_needs"),
          last_prompt(calls, "furnish_needs")[:200])
    check("confirming an empty list is refused",
          _refused(room_furnish.confirm, "smokeroom", {"needs": []}))
    room_furnish.reset("smokeroom")
    check("reset drops the job", room_furnish.get_status("smokeroom") is None)

    # ── accept with nothing placed builds nothing ───────────────────────
    # Not a special case any more, just the "build only what was placed" rule
    # with an empty placement list: a prop nobody put in a room is a library
    # entry the admin never asked for.
    print("\n  accepting an empty result")
    answers["furnish_needs"] = {
        "needs": [need("a", "iron kettle", count=1, mount="floor",
                       width_m=0.3, depth_m=0.3, height_m=0.3,
                       description="a black iron kettle")],
        "surfaces": None}
    answers["furnish_match"] = {"matches": []}
    answers["furnish_place"] = {"plan": []}
    props_before_empty = len(props.list_props())
    room_furnish.start("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    room_furnish.confirm("smokeroom", status["proposal"])
    status = wait_for(("review_ready", "error"))
    check("an empty plan still reaches review_ready",
          status["state"] == "review_ready" and not status["placements"]["placed"],
          json.dumps(status.get("placements")))
    empty_accept = room_furnish.accept("smokeroom")
    check("accepting nothing places nothing and generates nothing",
          empty_accept == {"status": "accepted", "placed": 0, "generating": 0},
          json.dumps(empty_accept))
    check("…and creates no prop for the unplaced need",
          len(props.list_props()) == props_before_empty
          and room_furnish.get_status("smokeroom") is None,
          str(len(props.list_props())))
    check("…and says which kind it did not build",
          any("not built: iron kettle" in t for t in notification_texts()),
          json.dumps(notification_texts()[:2]))

    # ── start_direct: admin picks become needs ──────────────────────────
    print("\n  start_direct (admin picks, no LLM)")
    answers["furnish_place"] = {"plan": [
        {"prop": chair, "count": 2, "anchor": "wall_w", "ref": None,
         "facing": "room"}]}
    room_furnish.start_direct("smokeroom", {"existing": [
        {"prop_id": chair, "count": 2}, {"prop_id": "does-not-exist", "count": 1}]})
    status = wait_for(("review_ready", "error"))
    check("the direct job reaches review_ready",
          status and status["state"] == "review_ready",
          (status or {}).get("error") or "")
    direct_needs = status["proposal"]["needs"]
    check("a pick became a need that is NOT built",
          [(n["kind"], n["prop_id"], n["build"]) for n in direct_needs]
          == [("Chair", chair, False)], json.dumps(direct_needs))
    check("the unknown pick was dropped", len(direct_needs) == 1)
    check("two chairs were placed",
          len(status["placements"]["placed"]) == 2,
          json.dumps(status["placements"]))
    direct_accept = room_furnish.accept("smokeroom")
    check("a job with nothing to build closes at accept",
          direct_accept == {"status": "accepted", "placed": 2,
                            "generating": 0}
          and room_furnish.get_status("smokeroom") is None,
          json.dumps(direct_accept))

    # ── build only what was PLACED (controller ruling 2026-09-07) ───────
    # A need the solver could not fit gets no prop and no mesh — the accept
    # names it instead, so a kind never vanishes silently between the proposal
    # and the room.
    print("\n  only a placed need is built")
    answers["furnish_needs"] = {
        "needs": [need("a", "wooden stool", category="chair", count=1,
                       mount="floor", width_m=0.4, depth_m=0.4, height_m=0.5,
                       description="a small wooden stool"),
                  need("b", "iron kettle", category="tableware", count=1,
                       mount="floor", width_m=0.3, depth_m=0.3, height_m=0.3,
                       description="a black iron kettle")],
        "surfaces": None}
    answers["furnish_match"] = {"matches": []}
    # The plan names only the stool; the kettle stays unplaced.
    answers["furnish_place"] = {"plan": [
        {"prop": "need:n1", "count": 1, "anchor": "wall_e", "ref": None,
         "facing": "room"}]}
    props_before_ruling = len(props.list_props())
    room_furnish.start("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    room_furnish.confirm("smokeroom", status["proposal"])
    status = wait_for(("review_ready", "error"))
    check("only the planned piece is placed",
          len(status["placements"]["placed"]) == 1,
          json.dumps(status["placements"]))
    ruling = room_furnish.accept("smokeroom")
    check("accept builds the placed need and only that one",
          ruling == {"status": "accepted", "placed": 1, "generating": 1}
          and len(props.list_props()) == props_before_ruling + 1,
          f'{json.dumps(ruling)} / {len(props.list_props())}')
    check("…and names the piece it did not build",
          any("not built: iron kettle" in t for t in notification_texts()),
          json.dumps(notification_texts()[:2]))
    wait_for(("error",), tries=100)
    check("the job closes once its one mesh is there",
          room_furnish.get_status("smokeroom") is None)

    # ── a failed layout write leaves the created props on the row ───────
    # Otherwise a second accept (the state is still review_ready) would make
    # every prop twice — the ids only live on the row.
    print("\n  a layout write that fails")
    import app.models.world as world_module

    def one_build_job(kind: str) -> dict:
        """Drive one job with a single built floor need up to review_ready."""
        answers["furnish_needs"] = {
            "needs": [need("a", kind, category="chair", count=1,
                           mount="floor", width_m=0.3, depth_m=0.3,
                           height_m=0.4, description=f"a {kind}")],
            "surfaces": None}
        answers["furnish_match"] = {"matches": []}
        answers["furnish_place"] = {"plan": [
            {"prop": "need:n1", "count": 1, "anchor": "wall_e", "ref": None,
             "facing": "room"}]}
        room_furnish.start("smokeroom")
        st = wait_for(("proposal_ready", "error"))
        room_furnish.confirm("smokeroom", st["proposal"])
        return wait_for(("review_ready", "error"))

    status = one_build_job("oak footstool")
    check("the fixture job is ready to accept",
          len(status["placements"]["placed"]) == 1,
          json.dumps(status["placements"]))
    real_append = world_module.append_room_props
    world_module.append_room_props = lambda *a, **kw: False
    props_before_fail = len(props.list_props())
    check("a layout write that fails refuses the accept",
          _refused_with(room_furnish.accept, 409, "smokeroom"))
    props_after_fail = len(props.list_props())
    check("the prop was created and its id kept on the row",
          props_after_fail == props_before_fail + 1
          and all(n.get("prop_id") for n in
                  room_furnish.get_status("smokeroom")["proposal"]["needs"]),
          str(props_after_fail))
    stuck_pid = next(
        n["prop_id"] for n in
        room_furnish.get_status("smokeroom")["proposal"]["needs"]
        if n.get("build"))
    world_module.append_room_props = real_append
    retry_accept = room_furnish.accept("smokeroom")
    check("the retry reuses that prop instead of making a second one",
          len(props.list_props()) == props_after_fail
          and retry_accept["placed"] == 1,
          f'{len(props.list_props())} / {json.dumps(retry_accept)}')
    # THE PLACEMENT MUST NAME THE REAL PROP. The retry re-reads the entries
    # from the row, so they still say "need:n1"; a rewrite map built only from
    # the props created in THIS call would leave that id standing, the layout
    # sanitizer would drop the placement (props.safe_prop_id rejects the
    # colon) and a mesh would be baked for an empty room.
    room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == loc["id"]), "smokeroom")
    check("…and the layout entry names the real prop, not the placeholder",
          any(p.get("prop_id") == stuck_pid
              for p in room["layout"].get("props") or []),
          json.dumps([p.get("prop_id")
                      for p in room["layout"].get("props") or []][-3:]))
    wait_for(("error",), tries=100)

    # ── a job stranded in generating closes itself ──────────────────────
    # The NORMAL outcome of a server restart during generation: the task queue
    # is persistent and delivers the mesh, the furnish thread is not and never
    # sees it. Without a terminal case the row would sit in `generating`, and
    # every verb refuses that state — the room could never be furnished again.
    print("\n  a job stranded in generating")

    def stranded(kind: str) -> str:
        """Accept a one-piece job with the orchestrator frozen, then hand the
        prop its mesh from outside — the queue's job, done without a thread."""
        one_build_job(kind)
        real = suppress_spawn()
        room_furnish.accept("smokeroom")
        room_furnish._spawn = real
        row = room_furnish._get_row("smokeroom")
        pid = next(n["prop_id"] for n in room_furnish._needs(row["proposal"])
                   if n.get("build"))
        props.save_uploaded_glb(pid, b"glTF-stub")
        return pid

    stranded("birch stool")
    check("the stranded job is what a restart leaves behind",
          (room_furnish._get_row("smokeroom") or {}).get("state") == "generating")
    check("continue closes it instead of refusing it",
          room_furnish.resume("smokeroom") == {"status": "finished"}
          and room_furnish._get_row("smokeroom") is None)
    check("…and posts the mesh notification once",
          sum(1 for t in notification_texts()
              if "Meshes ready — 1 model generated" in t) >= 1,
          json.dumps(notification_texts()[:2]))
    check("the room can be furnished again",
          room_furnish.start("smokeroom")["state"] in ("selecting",
                                                       "proposal_ready"))
    wait_for(("proposal_ready", "error"))
    room_furnish.reset("smokeroom")

    stranded("ash stool")
    check("discard goes through once every ordered mesh is there",
          room_furnish.discard("smokeroom") == {"status": "discarded"}
          and room_furnish._get_row("smokeroom") is None)

    stranded("pine stool")
    check("a plain status read heals the row on its own",
          room_furnish.get_status("smokeroom") is None
          and room_furnish._get_row("smokeroom") is None)

    # ── legacy job rows ─────────────────────────────────────────────────
    print("\n  the boot-time cleanup of v1 job rows")
    now = utc_now_iso()
    with db.transaction() as conn:
        for room_id, proposal_json in (
                ("legacy-room", json.dumps({"existing": [], "new": []})),
                ("modern-room", json.dumps({"needs": [need()]}))):
            conn.execute(
                "INSERT INTO room_furnish (room_id, location_id, state, "
                "proposal, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (room_id, loc["id"], "proposal_ready", proposal_json, now, now))
    dropped_rows = room_furnish.drop_legacy_jobs()
    check("exactly the v1 row is dropped", dropped_rows == 1, str(dropped_rows))
    check("the v1 job is gone", room_furnish.get_status("legacy-room") is None)
    check("the need-shaped job survives",
          room_furnish.get_status("modern-room") is not None)
    check("running it again changes nothing",
          room_furnish.drop_legacy_jobs() == 0)
    room_furnish.discard("modern-room")

    # ── The YARD as a furnish target (§ A13a) ───────────────────────────
    # The ground has no floor plan: its surface is the drawn boundary and its
    # placements are LOCATION-LOCAL metres. The solver works from a polygon's
    # own min corner, so the whole run is shifted by that corner and back —
    # which is only visible if the boundary does NOT sit on the pin.
    # Boundary: (−6,−6) (4,−6) (4,4) (−6,4) — 10 × 10 m, min corner (−6, −6),
    # so the solver frame is 0…10 and the table lands at [−1.0, −5.55]
    # (derivation in the module docstring).
    print("\n  the yard (ground room) as a furnish target")
    yard_loc = add_location("Smoke Yard", "A test plot", rooms=[])
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] == yard_loc["id"]:
            entry["map3d"] = {
                "boundary": [[-6.0, -6.0], [4.0, -6.0], [4.0, 4.0], [-6.0, 4.0]],
                "plan_width_m": 10.0,
                # South pass-through — far from the north wall the table takes.
                "boundary_openings": [{"edge": 2, "at": 0.5, "width_m": 2.0,
                                       "type": "passage"}]}
    _save_world_data(data)
    yard_job = room_furnish.ground_job_id(yard_loc["id"])
    check("the yard job id is the composite one",
          yard_job == f"__ground__@{yard_loc['id']}", yard_job)
    answers["furnish_needs"] = {
        "needs": [need("a", "table", category="table", count=1, mount="floor",
                       width_m=1.2, depth_m=0.8, height_m=0.75,
                       description="a plain oak table"),
                  need("b", "wall torch", mount="wall", width_m=0.2,
                       depth_m=0.2, height_m=0.5, description="an iron torch"),
                  need("c", "candle", category="tableware", count=1,
                       mount="surface", width_m=0.08, depth_m=0.08,
                       height_m=0.2, description="a beeswax candle")],
        "surfaces": {"floor": "oak_planks", "wall": "plaster_wall"}}
    answers["furnish_match"] = lambda prompt: {"matches": [
        {"need": "n1", "ref": ref_for(prompt, "Table")}]}
    # The wall torch is dropped, so the candle is need n2 after re-minting.
    answers["furnish_place"] = {"plan": [
        {"prop": table, "count": 1, "anchor": "wall_n", "ref": None,
         "facing": "room"},
        {"prop": "need:n2", "count": 1, "anchor": "on", "ref": table,
         "facing": "ref"}]}
    room_furnish.start(yard_job)
    status = wait_for(("proposal_ready", "error"), job=yard_job)
    check("the yard reaches proposal_ready",
          status and status["state"] == "proposal_ready",
          (status or {}).get("error") or "")
    check("its prompt states the boundary's 10 × 10 m",
          "10.0 × 10.0 m" in last_prompt(calls, "furnish_needs"),
          last_prompt(calls, "furnish_needs")[:120])
    check("an unnamed yard is called Yard, not Room",
          "Yard" in last_prompt(calls, "furnish_needs"),
          last_prompt(calls, "furnish_needs")[:120])
    check("the wall torch was dropped with its reason",
          status["proposal"]["dropped"]
          == [{"kind": "wall torch", "reason": "the yard has no walls/ceiling"}],
          json.dumps(status["proposal"]["dropped"]))
    check("the yard gets no surface proposal",
          status["proposal"]["surfaces"] is None)
    check("the open-air catalog keeps the outdoor prop",
          "Evergreen Pine" in last_prompt(calls, "furnish_match"))
    room_furnish.confirm(yard_job, status["proposal"])
    status = wait_for(("review_ready", "error"), job=yard_job)
    check("the yard reaches review_ready",
          status and status["state"] == "review_ready",
          (status or {}).get("error") or "")
    yard_placed = status["placements"]["placed"]
    yard_table = next(p for p in yard_placed if p["prop_id"] == table)
    yard_candle = next(p for p in yard_placed if p.get("on"))
    check("the placement is shifted back into LOCATION-local metres",
          yard_table["at"] == [-1.0, -5.55], json.dumps(yard_table["at"]))
    # THE ORIGIN SHIFT SKIPS A CHILD (task 2 note): the candle's metres are
    # its support's, not the yard's, so they stay [0, 0] while the table
    # underneath moves by (−6, −6).
    check("the child on it is NOT shifted with the origin",
          yard_candle["at"] == [0.0, 0.0]
          and yard_candle["on"] == yard_table["id"], json.dumps(yard_candle))
    room_furnish.accept(yard_job)
    yard_room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == yard_loc["id"]), "__ground__")
    check("it landed in the GROUND room's layout, props only",
          sorted(yard_room.get("layout") or {}) == ["props"]
          and (yard_room["layout"]["props"] or [{}])[0].get("at") == [-1.0, -5.55],
          json.dumps(yard_room.get("layout")))
    check("the yard job stays open while its candle is baked",
          (room_furnish.get_status(yard_job) or {}).get("state") == "generating"
          or room_furnish.get_status(yard_job) is None,
          json.dumps(room_furnish.get_status(yard_job)))
    status = wait_for(("error",), job=yard_job, tries=100)
    check("the yard job row is gone", status is None, json.dumps(status))
    # A boundary pass-through IS the yard's doorway: with the opening moved
    # onto the north edge the very same plan cannot use the wall's centre.
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] == yard_loc["id"]:
            entry["map3d"]["boundary_openings"] = [
                {"edge": 0, "at": 0.5, "width_m": 2.0, "type": "passage"}]
            entry["rooms"] = [r for r in entry["rooms"]
                              if r.get("id") != "__ground__"] + [
                {"id": "__ground__", "name": "", "description": "",
                 "activities": []}]
    _save_world_data(data)
    room_furnish.start(yard_job)
    status = wait_for(("proposal_ready", "error"), job=yard_job)
    room_furnish.confirm(yard_job, status["proposal"])
    status = wait_for(("review_ready", "error"), job=yard_job)
    blocked = (status["placements"] or {}).get("placed") or []
    # Zone: edge 0 runs (0,0) → (10,0) in the solver frame, so the passage
    # centre is (5, 0) with the inward normal (0, 1); it blocks
    # x 5 ± (2.0 + 0.4)/2 = 3.8…6.2 and y 0…0.6. The table's footprint at the
    # wall centre would be x 4.4…5.6 / y 0.05…0.85 — an overlap, so the
    # centre spot is out and the piece has to slide sideways (or fail).
    check("the boundary opening keeps its own stretch of the yard free",
          all(not (3.8 - 0.6 < p["at"][0] + 6 < 6.2 + 0.6)
              for p in blocked if not p.get("on")),
          json.dumps([p["at"] for p in blocked]))
    room_furnish.discard(yard_job)
    check("discarding the yard job leaves the accepted placement alone",
          room_furnish.get_status(yard_job) is None)

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


def _refused(fn, *args) -> bool:
    """True when the call raised a FurnishError — the job's way of saying no."""
    try:
        fn(*args)
    except room_furnish.FurnishError:
        return True
    return False


def _refused_with(fn, status: int, *args) -> bool:
    """True when the call was refused with exactly that HTTP status."""
    try:
        fn(*args)
    except room_furnish.FurnishError as e:
        return e.status == status
    return False


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
