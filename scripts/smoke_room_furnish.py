#!/usr/bin/env python3
"""Smoke run for the room-furnish state machine (plan-furnish-v2.md § 2 B3).

No test framework, no LLM, no GPU: the three ``furnish_*`` tasks are
monkeypatched with canned answers, so one run ticks the whole machine

    start → proposal_ready → confirm → generating → placing → review_ready
          → accept → the placements land in ``layout.props``

against a throwaway world in a temp directory. Everything else is the real
code path (templates, validation, solver, DB, layout sanitizer). The mesh
generation is stubbed at ``props.trigger_generation`` (a GLB is attached
instantly) — the phase around it, which creates the prop with its ``mount``
and its ``key_areas``, is the real one.

STAGE 1 IS INVERTED SINCE v2: ``furnish_needs`` writes what the room needs
without seeing the library, ``furnish_match`` maps at most one library piece
onto each need, and everything unmatched is built. The rows below check that
inversion end to end, with every expected number derived by hand:

  * needs 4 × 4 m room, table 1.2 × 0.8 m, anchor ``wall_n`` facing the room
    → the centre of the usable stretch, x = 1.2/2 + 0.5 × (4 − 1.2) = 2.0 m,
    pushed off the wall by depth/2 + WALL_GAP_M = 0.4 + 0.05 = 0.45 m.
  * a wall piece 0.6 m high with no ``base_m`` takes the solver's default
    base 1.5 − h/2 = 1.5 − 0.3 = 1.2 m, which is its stored ``offset_y``.
  * the yard's boundary (−6,−6)…(4,4) is a 10 × 10 m square, so the solver
    frame is 0…10 and the same wall arithmetic gives x = 0.6 + 0.5 × 8.8 =
    5.0, y = 0.4 + 0.05 = 0.45 → stored [5.0 − 6, 0.45 − 6] = [−1.0, −5.55].
  * a match is refused when the mount differs or when the largest dimension
    is more than DIM_TOLERANCE = 40 % of the need's away from it: a need of
    0.5 m against a 1.2 m table is 0.7 m off, and 0.7 > 0.4 × 0.5 = 0.2.

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

from app.core import (db, furnish_needs, props, room_furnish,  # noqa: E402
                      surface_textures)
from app.core.timeutils import utc_now_iso  # noqa: E402
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

    def place_plan(_prompt):
        """The placement plan, built when it is asked for: the ids of the
        pieces that were BUILT only exist by then."""
        status = room_furnish.get_status("smokeroom") or {}
        ids = [n["prop_id"] for n in (status.get("proposal") or {}).get("needs")
               or [] if n.get("prop_id")]
        return {"plan": [{"prop": pid, "count": 1, "anchor": "wall_n",
                          "ref": None, "facing": "room"} for pid in ids]}

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
            ],
            "surfaces": {"floor": "oak_planks", "wall": "does_not_exist"},
        },
        "furnish_match": lambda prompt: {"matches": [
            {"need": "n1", "ref": ref_for(prompt, "Table")},
            {"need": "n2", "ref": None}]},
        "furnish_place": place_plan,
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

    # ── confirm → generating → placing → review_ready ───────────────────
    room_furnish.confirm("smokeroom", proposal)
    status = wait_for(("review_ready", "error"))
    check("state review_ready", status["state"] == "review_ready",
          status.get("error") or "")
    built = [n for n in status["proposal"]["needs"] if n["build"]]
    check("the built need got a prop", bool(built and built[0].get("prop_id")),
          json.dumps(built))
    new_prop = props.get_prop(built[0]["prop_id"]) if built else {}
    check("the new prop carries the need's mount",
          new_prop.get("mount") == "wall", json.dumps(new_prop.get("mount")))
    check("…and its key areas",
          list(new_prop.get("key_areas") or []) == ["picture"],
          json.dumps(new_prop.get("key_areas")))
    check("…and is named after the kind",
          new_prop.get("name") == "Wall Painting", new_prop.get("name") or "")
    check("progress counts the built needs only",
          status["progress"] == {"done": 1, "total": 1},
          json.dumps(status["progress"]))
    placed = status["placements"]["placed"]
    check("solver placed both pieces", len(placed) == 2,
          json.dumps(status["placements"]))
    check("placements are layout.props entries",
          all(set(p) <= {"prop_id", "id", "at", "yaw", "offset_y", "on",
                         "variant"} and len(p["at"]) == 2
              for p in placed))
    check("every placement carries a minted id",
          len({p["id"] for p in placed}) == len(placed),
          json.dumps([p.get("id") for p in placed]))
    check("door zone kept free",
          all(p["at"][1] < 3.4 for p in placed),
          json.dumps([p["at"] for p in placed]))
    # Hand-derived (see the module docstring): the table centres on its wall
    # at [2.0, 0.45]; nothing pushes it off — the only zone is the south
    # door's, at y ≥ 3.4 m.
    table_at = next(p["at"] for p in placed if p["prop_id"] == table)
    check("the table stands centred on its wall",
          table_at == [2.0, 0.45], json.dumps(table_at))
    # The painting is a WALL piece — that is the whole point of `mount`
    # reaching the solver: base 1.5 − 0.6/2 = 1.2 m above the floor.
    painting = next(p for p in placed if p["prop_id"] != table)
    check("the wall piece hangs at its default base",
          painting.get("offset_y") == 1.2, json.dumps(painting))
    check("place prompt lists the door on wall S",
          "on wall S" in last_prompt(calls, "furnish_place"),
          last_prompt(calls, "furnish_place")[:200])

    # ── accept → the props land in layout.props, the job is gone ────────
    room_furnish.accept("smokeroom")
    check("job row deleted", room_furnish.get_status("smokeroom") is None)
    room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == loc["id"]), "smokeroom")
    stored = room["layout"].get("props") or []
    check("layout.props holds the accepted placements",
          len(stored) == len(placed), json.dumps(stored))
    check("sanitizer kept prop_id/at/yaw",
          all(p.get("prop_id") and len(p.get("at") or []) == 2 for p in stored))

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
    room_furnish.discard("smokeroom")

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
                       depth_m=0.2, height_m=0.5, description="an iron torch")],
        "surfaces": {"floor": "oak_planks", "wall": "plaster_wall"}}
    answers["furnish_match"] = lambda prompt: {"matches": [
        {"need": "n1", "ref": ref_for(prompt, "Table")}]}
    answers["furnish_place"] = {"plan": [
        {"prop": table, "count": 1, "anchor": "wall_n", "ref": None,
         "facing": "room"}]}
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
    check("the placement is shifted back into LOCATION-local metres",
          [p["at"] for p in yard_placed] == [[-1.0, -5.55]],
          json.dumps([p["at"] for p in yard_placed]))
    room_furnish.accept(yard_job)
    yard_room = get_room_by_id(
        next(entry for entry in _load_world_data()["locations"]
             if entry["id"] == yard_loc["id"]), "__ground__")
    check("it landed in the GROUND room's layout, props only",
          sorted(yard_room.get("layout") or {}) == ["props"]
          and (yard_room["layout"]["props"] or [{}])[0].get("at") == [-1.0, -5.55],
          json.dumps(yard_room.get("layout")))
    check("the yard job row is gone", room_furnish.get_status(yard_job) is None)
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
          all(not (3.8 - 0.6 < p["at"][0] + 6 < 6.2 + 0.6) for p in blocked),
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


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
