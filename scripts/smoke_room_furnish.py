#!/usr/bin/env python3
"""Smoke run for the room-furnish state machine (plan-room-furnish.md).

No test framework, no LLM, no GPU: the three ``furnish_*`` tasks are
monkeypatched with canned answers, so one run ticks the whole machine

    start → proposal_ready → confirm → generating → placing → review_ready
          → accept → the placements land in ``layout.props``

against a throwaway world in a temp directory. Everything else is the real
code path (templates, validation, solver, DB, layout sanitizer).

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

from app.core import db, props, room_furnish  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, get_room_by_id,
)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def make_prop(name: str, w: float, d: float, h: float) -> str:
    """A library prop WITH a model file (has_model → the job may place it).
    Goes through the real upload path so the mesh lands in the gallery and is
    selected for the default tier (plan-3d-lod-und-betreten.md)."""
    prop = props.create_prop(name=name, category="table", width_m=w,
                             depth_m=d, height_m=h)
    props.save_uploaded_glb(prop["id"], b"glTF-stub")
    return prop["id"]


def fake_llm(answers):
    """Replace room_furnish's LLM hop with canned answers per task. An answer
    that IS an exception is raised instead (error-path coverage)."""
    calls = []

    def _stub(task, system_prompt, user_prompt, label):
        calls.append((task, user_prompt))
        answer = answers[task]
        if isinstance(answer, Exception):
            raise answer
        return answer

    room_furnish._llm_json = _stub
    return calls


def wait_for(states, tries=80, job="smokeroom"):
    for _ in range(tries):
        status = room_furnish.get_status(job)
        if status is None or status["state"] in states:
            return status
        time.sleep(0.1)
    return room_furnish.get_status(job)


def main() -> int:
    db.init_schema()
    print(f"World: {WORLD}")

    # ── A room with a floor plan and a door ──────────────────────────────
    # METRIC FIXTURE (contract v6 Nr. 2). This used to be the fractions
    # x/y 0, w/d 0.5 of an 8 m plate — the SAME 4 × 4 m room in the NW
    # quadrant of the location, converted once by the retired mapping
    # (x/y → (f − 0.5) × 8, w/d → f × 8). Every expected number below is
    # therefore the one the fraction fixture produced; only the placement
    # coordinates are now stated in the metres the solver already worked in
    # (table [2.0, 0.45] instead of the fractions [0.5, 0.1125] — the very
    # numbers the hand derivation below always spelled out).
    table = make_prop("Table", 1.2, 0.8, 0.75)
    chair = make_prop("Chair", 0.5, 0.5, 0.9)
    loc = add_location("Smoke House", "A test house", rooms=[
        {"id": "smokeroom", "name": "Study", "description": "A quiet study",
         "activity_hint": "reading", "activities": []}])
    data = _load_world_data()
    for entry in data["locations"]:
        if entry["id"] != loc["id"]:
            continue
        entry["map3d"] = {"plan_width_m": 8.0}
        entry["rooms"][0]["layout"] = {
            "x": -4.0, "y": -4.0, "w": 4.0, "d": 4.0, "level": 0,
            "openings": [{"edge": "S", "at": 0.5, "width_m": 1.0,
                          "height_m": 2.1, "sill_m": 0, "type": "door"}],
        }
    _save_world_data(data)
    print("  room 4.0 × 4.0 m (metres in the layout), one south door")

    answers = {
        "furnish_select": {"existing": [{"prop_id": table, "count": 1},
                                        {"prop_id": "does-not-exist", "count": 3}]},
        # No new pieces — the smoke run must not need image/mesh backends.
        "furnish_new": {"new": []},
        "furnish_place": {"plan": [
            {"prop": table, "count": 1, "anchor": "wall_n", "ref": None,
             "facing": "room"},
            {"prop": chair, "count": 1, "anchor": "beside", "ref": table,
             "facing": "ref"}]},
    }
    calls = fake_llm(answers)

    # ── start → proposal_ready ──────────────────────────────────────────
    room_furnish.start("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    check("state proposal_ready", status["state"] == "proposal_ready",
          status.get("error") or "")
    check("unknown prop id dropped",
          [p["prop_id"] for p in status["proposal"]["existing"]] == [table])
    check("select prompt carries the metre size",
          "4.0 × 4.0 m" in calls[0][1])

    # A second job for the same room is refused.
    try:
        room_furnish.start("smokeroom")
        check("second start refused", False)
    except room_furnish.FurnishError as e:
        check("second start refused", e.status == 409, e.message)

    # ── confirm → generating → placing → review_ready ───────────────────
    proposal = dict(status["proposal"])
    proposal["existing"] = [{"prop_id": table, "count": 1},
                            {"prop_id": chair, "count": 2}]
    room_furnish.confirm("smokeroom", proposal)
    status = wait_for(("review_ready", "error"))
    check("state review_ready", status["state"] == "review_ready",
          status.get("error") or "")
    placed = status["placements"]["placed"]
    check("solver placed the plan", len(placed) >= 2,
          json.dumps(status["placements"]))
    check("placements are layout.props entries",
          all(set(p) <= {"prop_id", "at", "yaw", "offset_y"} and len(p["at"]) == 2
              for p in placed))
    check("door zone kept free",
          all(p["at"][1] < 3.4 for p in placed),
          json.dumps([p["at"] for p in placed]))
    # Hand-derived from furnish_solver's wall strategy: the room is 4 × 4 m,
    # the table 1.2 × 0.8 m, anchor wall_n facing the room (yaw 0). The first
    # candidate is the CENTRE of the usable stretch — x = 1.2/2 + 0.5 ×
    # (4 − 1.2) = 2.0 m — pushed off the wall by half the
    # depth plus WALL_GAP_M: y = 0.4 + 0.05 = 0.45 m. Since v6 those metres
    # ARE what is stored, so the placement reads [2.0, 0.45].
    # Nothing blocks it: the only zone is the south door's, at y ≥ 3.4 m.
    # The openings are the only keep-outs (plan-betreten-und-tueren.md
    # § 4.1) — nothing pushes the table off the centre of its wall.
    table_at = next(p["at"] for p in placed if p["prop_id"] == table)
    check("the table stands centred on its wall",
          table_at == [2.0, 0.45], json.dumps(table_at))
    check("place prompt lists the door on wall S",
          "on wall S" in calls[-1][1], calls[-1][1][:200])

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

    # ── error → retry → reset ───────────────────────────────────────────
    answers["furnish_select"] = room_furnish.FurnishError("stage 1 exploded")
    room_furnish.start("smokeroom")
    status = wait_for(("error", "proposal_ready"))
    check("failed stage 1 lands in error", status["state"] == "error")
    check("the message is persisted", status["error"] == "stage 1 exploded")
    check("a dead job counts as stalled, not running",
          not status["running"] and not status["stalled"])
    answers["furnish_select"] = {"existing": [{"prop_id": chair, "count": 1}]}
    room_furnish.retry("smokeroom")
    status = wait_for(("proposal_ready", "error"))
    check("retry re-enters at stage 1", status["state"] == "proposal_ready",
          status.get("error") or "")
    check("the room's own furnishing is known to the LLM",
          "2× " in calls[-1][1] or "1× Table" in calls[-1][1], calls[-1][1][:120])
    room_furnish.reset("smokeroom")
    check("reset drops the job", room_furnish.get_status("smokeroom") is None)

    # ── The YARD as a furnish target (§ A13a) ───────────────────────────
    # The ground has no floor plan: its surface is the drawn boundary and its
    # placements are LOCATION-LOCAL metres. The solver works from a polygon's
    # own min corner, so the whole run is shifted by that corner and back —
    # which is only visible if the boundary does NOT sit on the pin.
    #
    # Boundary: (−6,−6) (4,−6) (4,4) (−6,4) — a 10 × 10 m square whose min
    # corner is (−6, −6), so the solver frame is 0…10 on both axes.
    # Hand-derived placement (furnish_solver wall strategy, same arithmetic as
    # the room above): table 1.2 × 0.8 m, anchor wall_n facing the room →
    # yaw 0, usable stretch 10 − 1.2 = 8.8 m, first candidate at its centre
    # x = 0.6 + 0.5 × 8.8 = 5.0, pushed off the wall by 0.8/2 + 0.05 = 0.45.
    # Solver frame [5.0, 0.45]  →  stored [5.0 − 6, 0.45 − 6] = [−1.0, −5.55].
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
    answers["furnish_select"] = {"existing": [{"prop_id": table, "count": 1}]}
    answers["furnish_place"] = {"plan": [
        {"prop": table, "count": 1, "anchor": "wall_n", "ref": None,
         "facing": "room"}]}
    room_furnish.start(yard_job)
    status = wait_for(("proposal_ready", "error"), job=yard_job)
    check("the yard reaches proposal_ready",
          status and status["state"] == "proposal_ready",
          (status or {}).get("error") or "")
    check("its prompt states the boundary's 10 × 10 m",
          "10.0 × 10.0 m" in calls[-2][1], calls[-2][1][:120])
    check("an unnamed yard is called Yard, not Room",
          "Yard" in calls[-2][1], calls[-2][1][:120])
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


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
