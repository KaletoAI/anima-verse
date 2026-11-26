#!/usr/bin/env python3
"""Smoke: World Dev free mode — the routes and the unfreeze guard.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_free_routes.py

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 8
(Review Focus 5: the header unfreeze while a run is open is refused with
409). A temp world (paths.init BEFORE any world-DB import, STORAGE_DIR and
INSTANCE_DIR temp dirs); no server: a throwaway FastAPI app carries the auth
middlewares exactly as smoke_auth_gate.py mounts them, with the session
lookup stubbed (role via the "x-test-user" header), plus the real
`world_dev` and `world` routers. No real LLM: the run manager's
`llm_factory` returns a FakeLLM for model "fake-model" and None for any
other model (= "cannot be resolved"). Every start takes the next reply
script from SCRIPTS; a "GATE:<name>" reply blocks until the smoke sets that
threading.Event and then hands out the next reply. Run 1: GATE g1, create
"Demo R1", final "Built R1.". Run 2: create "Demo R2", "Built R2.", then
(turn 2) GATE g2. Run 3: GATE g3, then "Done." (no tool call). The TestClient is used as a context
manager, so one event loop carries the run's turn task across requests.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Start state: world not frozen, no run.

 1. The schema modes are gone (plan 2026-11-25-world-dev-free-remove-schema-
    modes.md, Task 4): GET /world-dev/schemas, POST /world-dev/chat, POST
    /world-dev/apply-json and GET /world-dev/character-templates (admin)
    -> 404 each (no route of that path left on the router; the admin passes
    the gate, so a 404 is the router's, not a refusal). And the router's
    whole (method, path) set is exactly the 14 the plan keeps (Task 4):
    POST pause-all, POST resume-all, GET pause-status, POST trigger-thought,
    GET free/defaults, POST free/start, GET free/runs, GET free/open,
    GET free/{run_id}, POST free/{run_id}/message, POST free/{run_id}/stop,
    POST free/{run_id}/accept, POST free/{run_id}/discard,
    GET free/{run_id}/events — all under /world-dev; plus the three media
    routes of plan 2026-11-25-world-dev-free-media Task 10: GET
    free/{run_id}/media, POST free/{run_id}/media-switch, POST
    free/{run_id}/media/retry (17 in all). A removed route that comes back
    fails here.
 2. GET /world-dev/free/defaults (admin) -> {"max_steps": 60,
    "max_tokens_total": 600000} (DEFAULT_MAX_STEPS / DEFAULT_MAX_TOKENS_TOTAL
    of world_dev_agent).
 3. player POST /world-dev/free/start -> 403 (router-wide require_admin);
    anonymous -> 401 (default-deny gate). Nothing frozen, no open run.
 4. admin start with model "nope" -> 400 (llm_factory returns None ->
    ValueError in RunManager.start before create_run); world NOT frozen, no
    open run. Empty task -> 400 likewise. Budgets are checked by the route
    before the manager (finding 1): max_steps -3, max_steps 0,
    max_tokens_total true and max_steps "abc" -> 400 each; still nothing
    frozen and no open run.
 5. admin start {task, model "fake-model", provider "fake"} -> 200
    {"run_id": "wdr_..."}; world frozen (start froze it).
 6. second start -> 409, body {"detail": ..., "run_id": <the same id>}
    (RunOpenError from create_run); world still frozen.
 7. GET /world-dev/free/open -> {"run": {...id = run_id, status running}}.
 8. POST /world/unfreeze while the run is open -> 409 with body run_id =
    run_id; GET /world/freeze-status -> frozen True (the guard refused
    BEFORE set_world_frozen).
 9. message / accept / discard while running -> 409 (state table: message
    only from awaiting_review, accept/discard only from awaiting_review or
    interrupted), body run_id = run_id.
10. release the gate; poll GET /world-dev/free/{id} until status
    awaiting_review (turn 1: create + final reply -> awaiting_review), note
    "Built R1."; the detail carries steps (1 row, tool create_location,
    seq 1, turn 1, kind write, a line; its keys exactly seq/turn/tool/kind/
    line/state/undone_at — no args/before/written/inverse),
    skipped [] and discard_preview naming "Demo R1" (the created location
    still exists). The detail's per-turn summary (finding C): turns ==
    [{turn 1, status "kept" (the manager recorded the final reply), reason
    "", writes 1, undone 0}], remaining_writes 1 (the one create row, not
    undone), turn_usage {turn 1, steps 1, tokens > 0} (one write step this
    turn; the token estimate is positive for any prompt).
11. stop while awaiting_review -> 409 (stop only while running).
12. GET /world-dev/free/{id}/events?after=0 -> SSE "data:" frames; at least
    one step and one status frame; ?after=999 -> first frame {"ev": 0,
    "type": "reset"} (counter beyond this process's buffer, passed through).
13. GET /world-dev/free/runs -> the run listed. Unknown run id -> 404.
14. accept -> 200; world unfrozen (was_frozen False restored by _close);
    open -> {"run": null}.
15. after accept: freeze, then POST /world/unfreeze -> 200 {"frozen": false}
    and freeze-status false (no open run any more).
16. player GET /world-dev/free/runs -> 403.

Run 2 — a PRE-FROZEN world (set_world_frozen(True) before the start):
17. start -> 200; turn 1 (create "Demo R2" + final reply) -> awaiting_review,
    note "Built R2."; run.was_frozen True (is_world_frozen() read True).
18. message {"text": "more", "max_steps": 0} -> 400 (finding 1, budget
    < 1); the run stays awaiting_review.
19. message {"text": "more"} -> 200 {"ok": true}; status running (the route
    returns after _spawn); the turn blocks in GATE g2.
20. unfreeze during turn 2 -> 409 with run_id; still frozen.
21. stop while running -> 200 {"ok": true}; the stream races stop_ev, the
    turn fails with "stopped by the admin", _fail undoes turn 2 (no step)
    and, turn != 1, returns to awaiting_review with note
    "stopped by the admin — turn 2 was rolled back" (no step unreversed).
    Detail: turns == [turn 1 kept 1 write 0 undone; turn 2 rolled_back,
    reason "stopped by the admin" (the _fail note), 0 writes 0 undone];
    remaining_writes 1 (turn 1's create still stands).
22. discard -> 200 {"ok": true, "report": {"reversed": [1], "skipped": [],
    "complete": true}}: the run's only step is seq 1 (create Demo R2, turn
    1); the undo reverses it. Status rolled_back; "Demo R2" no longer in
    list_locations() ("Demo R1" of the accepted run 1 still is); world still
    frozen (was_frozen True restored by _close).

Run 3 — a freeze click during an open run is kept (finding 6):
23. world unfrozen, start -> 200 (was_frozen False recorded); while turn 1
    blocks in GATE g3, POST /world/freeze -> 200 {"frozen": true} and the
    run's was_frozen is now True (world_ops.freeze_world records it).
24. release g3: reply "Done." has no tool call -> turn 1 hard failure ->
    _fail undoes nothing (complete) -> _close("rolled_back") restoring
    was_frozen True -> the world STAYS frozen (before the fix it was thawed
    to the pre-run False and the click was lost).

The unfreeze race (finding 2):
25. app.models.world.set_world_frozen is wrapped so that right after the
    thaw (False) a run is created (wr.create_run) — a start landing between
    unfreeze_world's check and its write. POST /world/unfreeze -> 409 with
    that run's id, and the world is frozen again (the re-check after the
    thaw re-freezes). Unwrapped, the race run closed: unfreeze -> 200.

Run 4 — the media routes (plan 2026-11-25-world-dev-free-media, Task 10).
The lane is stubbed (world_dev_media._ensure_lane_locked -> False): no lane
task is submitted, no producer runs, rows stay where the smoke puts them.
Turn 1 creates "Demo R4" with the rooms Main and Back.
26. (a) start with generate_media false -> run.media_enabled False; GET
    .../media -> enabled False, state "open", elements [] (the turn-end
    schedule queued nothing: the switch is off), waiting [] (listed only
    for an interrupted run with the switch on — fixes plan Task 1, F1). generate_media "yes" (not a
    bool) -> 400 before the manager is called.
27. (c) media-switch {enabled: true} in review -> 200, one queued row (the
    created place is due). Its steps, counted by hand from _location_steps:
    building-front, day:, night:, day:<Main>, night:<Main>, day:<Back>,
    night:<Back>, mesh = 8. media-switch {enabled: false} -> that row
    cancelled with the note "media switched off", run.media_enabled False;
    on again -> one NEW queued row (a cancelled row's undone steps hold
    nothing, so all 8 are due again).
28. (b) that row set done with every step done (wr.update_media_row) ->
    GET .../media: elements == one element {kind location, id = the place's
    id, name "Demo R4", row_id = the new row, status done, note "", 8 steps
    each {id, label, status, note} (no fp), produced 0}.
29. (d) the row set skipped (every step skipped) -> retry -> 200 with ONE new
    row id; that row is queued with the 8 steps. Then a done row whose mesh
    step alone is skipped (the others done): retry clears the skipped step's
    fingerprint (the done row would otherwise hold it) -> one new row with
    exactly the step "mesh"; the done steps are not re-queued.
29b. retry refused (409, nothing cleared or added) BEFORE any fingerprint is
    cleared when the media switch is off or the media state is closed (the
    discard window); switch-on 409 in that window too, the switch stays off.
30. (f) wr.set_status(run, "running") -> retry 409 and switch-on 409 (both
    with run_id, nothing queued, media_enabled unchanged True); switch-off
    200 (media_enabled False, the queued row cancelled).
31. (e) a player session -> 403 on GET media, media-switch and media/retry;
    an unknown run -> 404 on all three.
32. status back to awaiting_review, discard -> 200; on the closed run
    media-switch (on and off) and retry -> 409; GET media still 200.
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_free_routes_"))
os.environ["STORAGE_DIR"] = str(STORAGE)
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_free_routes_inst_"))
os.environ["INSTANCE_DIR"] = str(INSTANCE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_free_routes_clips_")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(INSTANCE)
from app.core import config  # noqa: E402
config.load(STORAGE / "config.json")
from app.core import db  # noqa: E402
db.init_schema()

import asyncio  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth_dependency  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.llm_client import LLMChunk  # noqa: E402
from app.models.world import is_world_frozen, set_world_frozen  # noqa: E402
from app.routes import world as world_route  # noqa: E402
from app.routes import world_dev as world_dev_route  # noqa: E402

FAILS = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        FAILS.append(label)


# ── auth stub (as smoke_auth_gate.py) ────────────────────────────────────
_USERS = {
    "user": {"id": "u_user", "username": "demo", "role": "user",
             "allowed_characters": []},
    "admin": {"id": "u_admin", "username": "demo", "role": "admin",
              "allowed_characters": []},
}
auth_dependency._get_session_user = lambda request: _USERS.get(
    request.headers.get("x-test-user", ""))

# ── fake LLM ─────────────────────────────────────────────────────────────
GATES = {name: threading.Event() for name in ("g1", "g2", "g3")}


def create(name):
    return ('<tool name="create_location">{"data": {"name": "' + name + '", '
            '"rooms": [{"name": "Main"}]}}</tool>')


SCRIPTS = [
    ["GATE:g1", create("Demo R1"), "Built R1."],
    [create("Demo R2"), "Built R2.", "GATE:g2", "Never read."],
    ["GATE:g3", "Done."],
    ['<tool name="create_location">{"data": {"name": "Demo R4", '
     '"rooms": [{"name": "Main"}, {"name": "Back"}]}}</tool>', "Built R4."],
]


class FakeLLM:
    """Takes its reply script at its FIRST call, not at construction: a
    start refused after the model resolved (409) never streams and so
    consumes no script."""

    def __init__(self):
        self.replies = None

    async def astream(self, messages):
        if self.replies is None:
            self.replies = SCRIPTS.pop(0)
        reply = self.replies.pop(0) if self.replies else "Done."
        if reply.startswith("GATE:"):
            await asyncio.to_thread(GATES[reply[5:]].wait, 30)
            reply = self.replies.pop(0)
        yield LLMChunk(content=reply)


def factory(model, provider, max_tokens):
    if model != "fake-model":
        return None
    return FakeLLM(), None


async def _active(llm_instance):
    return None


wa._chat_active = _active
wa._chat_done = lambda task_id: None
wa.get_run_manager().llm_factory = factory

# ── the throwaway app ────────────────────────────────────────────────────
app = FastAPI()
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(auth_dependency.user_context_middleware)
app.include_router(world_dev_route.router)
app.include_router(world_route.router)

ADMIN = {"x-test-user": "admin"}
USER = {"x-test-user": "user"}


def frames(text):
    return [json.loads(line[5:].strip()) for line in text.splitlines()
            if line.startswith("data:")]


def settle(c, run_id):
    """Poll the detail until the turn is no longer working."""
    detail = {}
    for _ in range(500):
        detail = c.get(f"/world-dev/free/{run_id}", headers=ADMIN).json()
        if (detail.get("run") or {}).get("status") != "running" and not detail.get("busy"):
            break
        time.sleep(0.02)
    return detail


def location_names():
    from app.models.world import list_locations
    return {loc.get("name") for loc in list_locations()}


def main(c):
    set_world_frozen(False)

    for method, path in (("get", "/world-dev/schemas"), ("post", "/world-dev/chat"),
                         ("post", "/world-dev/apply-json"),
                         ("get", "/world-dev/character-templates")):
        r = getattr(c, method)(path, headers=ADMIN)
        check(f"1 removed route {method.upper()} {path} -> 404",
              r.status_code == 404, r.status_code)
    kept = {("POST", "/world-dev/pause-all"), ("POST", "/world-dev/resume-all"),
            ("GET", "/world-dev/pause-status"), ("POST", "/world-dev/trigger-thought"),
            ("GET", "/world-dev/free/defaults"), ("POST", "/world-dev/free/start"),
            ("GET", "/world-dev/free/runs"), ("GET", "/world-dev/free/open"),
            ("GET", "/world-dev/free/{run_id}"),
            ("POST", "/world-dev/free/{run_id}/message"),
            ("POST", "/world-dev/free/{run_id}/stop"),
            ("POST", "/world-dev/free/{run_id}/accept"),
            ("POST", "/world-dev/free/{run_id}/discard"),
            ("GET", "/world-dev/free/{run_id}/events"),
            ("GET", "/world-dev/free/{run_id}/media"),
            ("POST", "/world-dev/free/{run_id}/media-switch"),
            ("POST", "/world-dev/free/{run_id}/media/retry")}
    have = {(m, rt.path) for rt in world_dev_route.router.routes
            for m in (getattr(rt, "methods", None) or ()) if m != "HEAD"}
    check("1 the router's (method, path) set is exactly the 17 kept routes",
          len(kept) == 17 and have == kept,
          {"extra": sorted(have - kept), "missing": sorted(kept - have)})

    r = c.get("/world-dev/free/defaults", headers=ADMIN)
    check("2 defaults", r.status_code == 200
          and r.json() == {"max_steps": 60, "max_tokens_total": 600000}, r.text)

    body = {"task": "build a pond", "model": "fake-model", "provider": "fake"}
    r = c.post("/world-dev/free/start", headers=USER, json=body)
    check("3 player start -> 403", r.status_code == 403, r.status_code)
    r = c.post("/world-dev/free/start", json=body)
    check("3 anonymous start -> 401", r.status_code == 401, r.status_code)
    check("3 nothing frozen, no run", not is_world_frozen() and wr.open_run() is None)

    r = c.post("/world-dev/free/start", headers=ADMIN, json={**body, "model": "nope"})
    check("4 unknown model -> 400", r.status_code == 400, r.text)
    r = c.post("/world-dev/free/start", headers=ADMIN, json={**body, "task": "  "})
    check("4 empty task -> 400", r.status_code == 400, r.text)
    for bad in ({"max_steps": -3}, {"max_steps": 0}, {"max_tokens_total": True},
                {"max_steps": "abc"}):
        r = c.post("/world-dev/free/start", headers=ADMIN, json={**body, **bad})
        check(f"4 bad budget {bad} -> 400", r.status_code == 400, r.text)
    check("4 nothing frozen, no run", not is_world_frozen() and wr.open_run() is None)

    r = c.post("/world-dev/free/start", headers=ADMIN, json=body)
    run_id = r.json().get("run_id", "") if r.status_code == 200 else ""
    check("5 start -> 200 run_id", r.status_code == 200 and run_id.startswith("wdr_"), r.text)
    check("5 frozen", is_world_frozen())

    r = c.post("/world-dev/free/start", headers=ADMIN, json=body)
    check("6 second start -> 409 with the run_id",
          r.status_code == 409 and r.json().get("run_id") == run_id
          and bool(r.json().get("detail")), r.text)
    check("6 still frozen", is_world_frozen())

    r = c.get("/world-dev/free/open", headers=ADMIN)
    run = r.json().get("run") or {}
    check("7 open run", run.get("id") == run_id and run.get("status") == "running", r.text)

    r = c.post("/world/unfreeze", headers=ADMIN)
    check("8 unfreeze during run -> 409 with run_id",
          r.status_code == 409 and r.json().get("run_id") == run_id, r.text)
    r = c.get("/world/freeze-status", headers=ADMIN)
    check("8 still frozen", r.json() == {"frozen": True} and is_world_frozen(), r.text)

    for action, payload in (("message", {"text": "more"}), ("accept", None),
                            ("discard", None)):
        r = c.post(f"/world-dev/free/{run_id}/{action}", headers=ADMIN, json=payload)
        check(f"9 {action} while running -> 409",
              r.status_code == 409 and r.json().get("run_id") == run_id, r.text)

    GATES["g1"].set()
    detail = settle(c, run_id)
    run = detail.get("run") or {}
    check("10 awaiting_review", run.get("status") == "awaiting_review", run.get("status"))
    check("10 note", run.get("note") == "Built R1.", run.get("note"))
    steps = detail.get("steps") or []
    check("10 one create_location step",
          [s.get("tool") for s in steps] == ["create_location"], steps)
    # Expected: exactly the keys of world_dev._STEP_ROW_KEYS — the panel's
    # seq/tool/kind/line/undone_at plus turn/state; never the journal's
    # args/before/written/inverse (finding: a recreate inverse is megabytes).
    check("10 step rows trimmed to seq/turn/tool/kind/line/state/undone_at",
          all(set(s) == {"seq", "turn", "tool", "kind", "line", "state", "undone_at"}
              for s in steps) and steps and steps[0].get("seq") == 1
          and steps[0].get("turn") == 1 and steps[0].get("kind") == "write"
          and steps[0].get("line"), steps)
    check("10 skipped []", detail.get("skipped") == [], detail.get("skipped"))
    check("10 discard_preview names Demo R1",
          any("Demo R1" in line for line in detail.get("discard_preview") or []),
          detail.get("discard_preview"))
    check("10 turns: turn 1 kept, 1 write",
          detail.get("turns") == [{"turn": 1, "status": "kept", "reason": "",
                                   "writes": 1, "undone": 0}], detail.get("turns"))
    check("10 remaining_writes 1", detail.get("remaining_writes") == 1,
          detail.get("remaining_writes"))
    tu = detail.get("turn_usage") or {}
    check("10 turn_usage: turn 1, 1 step, tokens > 0",
          tu.get("turn") == 1 and tu.get("steps") == 1 and (tu.get("tokens") or 0) > 0, tu)

    r = c.post(f"/world-dev/free/{run_id}/stop", headers=ADMIN)
    check("11 stop while awaiting_review -> 409", r.status_code == 409, r.text)

    r = c.get(f"/world-dev/free/{run_id}/events?after=0", headers=ADMIN)
    evs = frames(r.text)
    types = {e.get("type") for e in evs}
    check("12 SSE content type", r.headers.get("content-type", "").startswith(
        "text/event-stream"), r.headers.get("content-type"))
    check("12 events carry step + status", {"step", "status"} <= types, types)
    r = c.get(f"/world-dev/free/{run_id}/events?after=999", headers=ADMIN)
    evs = frames(r.text)
    check("12 after beyond buffer -> reset first",
          bool(evs) and evs[0] == {"ev": 0, "type": "reset"}, evs[:2])

    r = c.get("/world-dev/free/runs", headers=ADMIN)
    check("13 runs lists it", any(x.get("id") == run_id for x in r.json().get("runs", [])),
          r.text)
    r = c.get("/world-dev/free/wdr_unknown", headers=ADMIN)
    check("13 unknown run -> 404", r.status_code == 404, r.status_code)

    r = c.post(f"/world-dev/free/{run_id}/accept", headers=ADMIN)
    check("14 accept -> 200", r.status_code == 200, r.text)
    check("14 unfrozen (was_frozen False)", not is_world_frozen())
    r = c.get("/world-dev/free/open", headers=ADMIN)
    check("14 no open run", r.json() == {"run": None}, r.text)

    set_world_frozen(True)
    r = c.post("/world/unfreeze", headers=ADMIN)
    check("15 unfreeze after accept -> 200",
          r.status_code == 200 and r.json() == {"frozen": False}, r.text)
    check("15 unfrozen", not is_world_frozen())

    r = c.get("/world-dev/free/runs", headers=USER)
    check("16 player runs -> 403", r.status_code == 403, r.status_code)

    run2(c, body)
    run3(c, body)
    race(c)
    run4(c, body)


def run2(c, body):
    set_world_frozen(True)
    r = c.post("/world-dev/free/start", headers=ADMIN, json=body)
    run_id = r.json().get("run_id", "") if r.status_code == 200 else ""
    check("17 pre-frozen start -> 200", bool(run_id), r.text)
    run = settle(c, run_id).get("run") or {}
    check("17 awaiting_review, note Built R2.",
          run.get("status") == "awaiting_review" and run.get("note") == "Built R2.", run)
    check("17 was_frozen True", run.get("was_frozen") is True, run.get("was_frozen"))

    r = c.post(f"/world-dev/free/{run_id}/message", headers=ADMIN,
               json={"text": "more", "max_steps": 0})
    check("18 message max_steps 0 -> 400", r.status_code == 400, r.text)
    check("18 still awaiting_review", wr.get_run(run_id)["status"] == "awaiting_review")

    r = c.post(f"/world-dev/free/{run_id}/message", headers=ADMIN, json={"text": "more"})
    check("19 message -> 200", r.status_code == 200 and r.json() == {"ok": True}, r.text)
    check("19 running", wr.get_run(run_id)["status"] == "running")

    r = c.post("/world/unfreeze", headers=ADMIN)
    check("20 unfreeze in turn 2 -> 409",
          r.status_code == 409 and r.json().get("run_id") == run_id, r.text)
    check("20 still frozen", is_world_frozen())

    r = c.post(f"/world-dev/free/{run_id}/stop", headers=ADMIN)
    check("21 stop while running -> 200", r.status_code == 200 and r.json() == {"ok": True},
          r.text)
    detail = settle(c, run_id)
    run = detail.get("run") or {}
    check("21 back to awaiting_review with the rollback note",
          run.get("status") == "awaiting_review"
          and run.get("note") == "stopped by the admin — turn 2 was rolled back", run)
    check("21 turns: turn 1 kept, turn 2 rolled_back by the stop",
          detail.get("turns") == [
              {"turn": 1, "status": "kept", "reason": "", "writes": 1, "undone": 0},
              {"turn": 2, "status": "rolled_back", "reason": "stopped by the admin",
               "writes": 0, "undone": 0}], detail.get("turns"))
    check("21 remaining_writes 1", detail.get("remaining_writes") == 1,
          detail.get("remaining_writes"))

    r = c.post(f"/world-dev/free/{run_id}/discard", headers=ADMIN)
    rep22 = dict((r.json() if r.status_code == 200 else {}).get("report") or {})
    media22 = rep22.pop("media", None)
    check("22 discard -> 200 with the report",
          r.status_code == 200 and r.json().get("ok") is True
          and rep22 == {"reversed": [1], "skipped": [], "complete": True},
          r.text)
    # The media part (plan 2026-11-25-world-dev-free-media Task 9): the empty
    # temp instance routes nothing, so the run produced no media to remove.
    check("22 the report's media part: nothing removed or kept",
          isinstance(media22, dict) and media22.get("removed") == []
          and media22.get("kept") == [], media22)
    check("22 rolled_back", wr.get_run(run_id)["status"] == "rolled_back",
          wr.get_run(run_id)["status"])
    names = location_names()
    check("22 Demo R2 gone, Demo R1 kept", "Demo R2" not in names and "Demo R1" in names,
          sorted(n for n in names if n))
    check("22 still frozen (was_frozen True)", is_world_frozen())
    GATES["g2"].set()  # free the thread the stopped stream left waiting


def run3(c, body):
    set_world_frozen(False)
    r = c.post("/world-dev/free/start", headers=ADMIN, json=body)
    run_id = r.json().get("run_id", "") if r.status_code == 200 else ""
    check("23 start on a thawed world -> 200", bool(run_id), r.text)
    check("23 was_frozen False", wr.get_run(run_id)["was_frozen"] is False)
    r = c.post("/world/freeze", headers=ADMIN)
    check("23 freeze during the run -> 200",
          r.status_code == 200 and r.json() == {"frozen": True}, r.text)
    check("23 the wish is recorded (was_frozen True)", wr.get_run(run_id)["was_frozen"] is True)
    GATES["g3"].set()
    run = settle(c, run_id).get("run") or {}
    check("24 turn 1 without a tool -> rolled_back", run.get("status") == "rolled_back",
          run.get("status"))
    check("24 world stays frozen after the close", is_world_frozen())


def race(c):
    from app.models import world as world_model
    real = world_model.set_world_frozen
    made = []

    def racing(frozen):
        real(frozen)
        if not frozen and not made:
            made.append(wr.create_run("race", "fake-model", "fake", "u_admin", 1, 1))

    world_model.set_world_frozen = racing
    try:
        r = c.post("/world/unfreeze", headers=ADMIN)
    finally:
        world_model.set_world_frozen = real
    race_id = made[0] if made else None
    check("25 unfreeze racing a start -> 409 with that run",
          r.status_code == 409 and race_id is not None
          and r.json().get("run_id") == race_id, r.text)
    check("25 re-frozen", is_world_frozen())
    if race_id:
        wr.set_status(race_id, "rolled_back")
    r = c.post("/world/unfreeze", headers=ADMIN)
    check("25 race run closed: unfreeze -> 200", r.status_code == 200, r.text)


def run4(c, body):
    from app.core import world_dev_media as wm
    wm._ensure_lane_locked = lambda: False  # no lane task, no producer
    set_world_frozen(False)

    r = c.post("/world-dev/free/start", headers=ADMIN, json={**body, "generate_media": "yes"})
    check("26 generate_media not a bool -> 400", r.status_code == 400, r.text)
    check("26 no open run after the refusal", wr.open_run() is None)
    r = c.post("/world-dev/free/start", headers=ADMIN, json={**body, "generate_media": False})
    run_id = r.json().get("run_id", "") if r.status_code == 200 else ""
    check("26 start with generate_media false -> 200", bool(run_id), r.text)
    detail = settle(c, run_id)
    run = detail.get("run") or {}
    check("26 awaiting_review, media_enabled False",
          run.get("status") == "awaiting_review" and run.get("media_enabled") is False, run)
    loc_id = next((loc.get("id") for loc in __import__("app.models.world", fromlist=["x"])
                   .list_locations() if loc.get("name") == "Demo R4"), None)
    check("26 Demo R4 exists", bool(loc_id), loc_id)
    r = c.get(f"/world-dev/free/{run_id}/media", headers=ADMIN)
    check("26 GET media -> enabled False, state open, elements [], waiting []",
          r.status_code == 200 and r.json() == {"enabled": False, "state": "open",
                                                "elements": [], "waiting": []}, r.text)

    url = f"/world-dev/free/{run_id}"
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": "on"})
    check("27 media-switch with a non-bool -> 400", r.status_code == 400, r.text)
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": True})
    rows = wr.media_rows(run_id)
    check("27 switch on in review -> 200, one queued row",
          r.status_code == 200 and r.json().get("enabled") is True
          and r.json().get("queued") == [rows[0]["id"] if rows else None]
          and [x["status"] for x in rows] == ["queued"], (r.text, rows))
    want_ids = ["building-front", "day:", "night:"]
    loc = __import__("app.models.world", fromlist=["x"]).get_location_by_id(loc_id) or {}
    room_ids = {rm.get("name"): rm.get("id") for rm in loc.get("rooms") or []}
    for nm in ("Main", "Back"):
        want_ids += [f"day:{room_ids.get(nm)}", f"night:{room_ids.get(nm)}"]
    want_ids.append("mesh")
    check("27 the row's 8 steps", rows and [s["id"] for s in rows[0]["steps"]] == want_ids,
          rows and [s["id"] for s in rows[0]["steps"]])
    first = rows[0]["id"] if rows else None
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": False})
    row = wr.media_row(first) if first else {}
    check("27 switch off -> 200, the queued row cancelled",
          r.status_code == 200 and r.json().get("enabled") is False
          and r.json().get("cancelled") == 1 and row.get("status") == "cancelled"
          and row.get("note") == "media switched off", (r.text, row))
    check("27 run.media_enabled False", wr.get_run(run_id)["media_enabled"] is False)
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": True})
    rows = wr.media_rows(run_id)
    second = rows[-1]["id"] if rows else None
    check("27 on again -> one NEW queued row",
          r.status_code == 200 and r.json().get("queued") == [second] and second != first
          and [x["status"] for x in rows] == ["cancelled", "queued"], (r.text, rows))

    steps = [dict(s, status="done") for s in wr.media_row(second)["steps"]]
    wr.update_media_row(second, status="done", steps=steps)
    r = c.get(url + "/media", headers=ADMIN)
    els = r.json().get("elements") if r.status_code == 200 else None
    el = (els or [{}])[0]
    check("28 one element, the newest row", r.status_code == 200 and len(els or []) == 1
          and el.get("row_id") == second, r.text)
    check("28 element fields", {k: el.get(k) for k in ("kind", "id", "name", "status",
                                                        "note", "produced")}
          == {"kind": "location", "id": loc_id, "name": "Demo R4", "status": "done",
              "note": "", "produced": 0}, el)
    check("28 8 steps {id, label, status, note}, all done",
          len(el.get("steps") or []) == 8
          and all(set(s) == {"id", "label", "status", "note"} and s["status"] == "done"
                  for s in el.get("steps") or [])
          and [s["id"] for s in el.get("steps") or []] == want_ids, el.get("steps"))
    check("28 the run's state", r.json().get("enabled") is True
          and r.json().get("state") == "open", r.text)

    steps = [dict(s, status="skipped", note="stub") for s in steps]
    wr.update_media_row(second, status="skipped", steps=steps)
    r = c.post(url + "/media/retry", headers=ADMIN)
    new = (r.json() if r.status_code == 200 else {}).get("queued") or []
    third = wr.media_row(new[0]) if len(new) == 1 else {}
    check("29 retry on a skipped row -> one new id",
          r.status_code == 200 and len(new) == 1 and third.get("status") == "queued"
          and [s["id"] for s in third.get("steps") or []] == want_ids, (r.text, third))
    check("29 the skipped row keeps its status", wr.media_row(second)["status"] == "skipped")
    steps = [dict(s, status="skipped" if s["id"] == "mesh" else "done")
             for s in third.get("steps") or []]
    wr.update_media_row(new[0], status="done", steps=steps)
    r = c.post(url + "/media/retry", headers=ADMIN)
    new2 = (r.json() if r.status_code == 200 else {}).get("queued") or []
    fourth = wr.media_row(new2[0]) if len(new2) == 1 else {}
    check("29 retry on a done row with a skipped step -> a row with only that step",
          r.status_code == 200 and len(new2) == 1
          and [s["id"] for s in fourth.get("steps") or []] == ["mesh"], (r.text, fourth))
    check("29 the done row keeps its status and its done steps' fps",
          wr.media_row(new[0])["status"] == "done"
          and all(s.get("fp") for s in wr.media_row(new[0])["steps"] if s["id"] != "mesh"),
          wr.media_row(new[0]))

    # 29b: a retry that schedule would turn into nothing is refused BEFORE any
    # fingerprint is cleared — else the cleared step became due at the next
    # turn end without a retry. A skipped step with an fp is put on the done
    # row for the probe and taken back afterwards.
    probe_row = new[0] if new else None
    saved = list(wr.media_row(probe_row)["steps"]) if probe_row else []
    wr.update_media_row(probe_row, steps=[dict(s, fp="fp-probe") if s["id"] == "mesh" else s
                                          for s in saved])
    snap = lambda: [(x["id"], x["status"], json.dumps(x.get("steps"), sort_keys=True))
                    for x in wr.media_rows(run_id)]
    wr.set_media_enabled(run_id, False)
    before = snap()
    r = c.post(url + "/media/retry", headers=ADMIN)
    check("29b retry with the switch off -> 409 with run_id, no fp cleared, no row",
          r.status_code == 409 and r.json().get("run_id") == run_id and snap() == before,
          r.text)
    wr.set_media_enabled(run_id, True)
    wr.set_media_state(run_id, "closed")
    before = snap()
    r = c.post(url + "/media/retry", headers=ADMIN)
    check("29b retry with media closed (discard window) -> 409, no fp cleared",
          r.status_code == 409 and r.json().get("run_id") == run_id and snap() == before,
          r.text)
    wr.set_media_enabled(run_id, False)
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": True})
    check("29b switch-on with media closed -> 409, the switch stays off",
          r.status_code == 409 and r.json().get("run_id") == run_id
          and wr.get_run(run_id)["media_enabled"] is False and snap() == before, r.text)
    wr.set_media_state(run_id, "open")
    wr.set_media_enabled(run_id, True)
    wr.update_media_row(probe_row, steps=saved)

    wr.set_status(run_id, "running")
    n_rows = len(wr.media_rows(run_id))
    r = c.post(url + "/media/retry", headers=ADMIN)
    check("30 retry while running -> 409 with run_id",
          r.status_code == 409 and r.json().get("run_id") == run_id, r.text)
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": True})
    check("30 switch-on while running -> 409 with run_id",
          r.status_code == 409 and r.json().get("run_id") == run_id, r.text)
    check("30 nothing queued, the switch unchanged",
          len(wr.media_rows(run_id)) == n_rows and wr.get_run(run_id)["media_enabled"] is True)
    r = c.post(url + "/media-switch", headers=ADMIN, json={"enabled": False})
    check("30 switch-off while running -> 200, the queued row cancelled",
          r.status_code == 200 and wr.get_run(run_id)["media_enabled"] is False
          and wr.media_row(new2[0])["status"] == "cancelled" if new2 else False, r.text)

    for method, path, payload in (("get", "/media", None),
                                  ("post", "/media-switch", {"enabled": True}),
                                  ("post", "/media/retry", None)):
        kw = {"json": payload} if payload is not None else {}
        r = getattr(c, method)(url + path, headers=USER, **kw)
        check(f"31 player {method.upper()} {path} -> 403", r.status_code == 403, r.status_code)
        r = getattr(c, method)("/world-dev/free/wdr_unknown" + path, headers=ADMIN, **kw)
        check(f"31 unknown run {method.upper()} {path} -> 404", r.status_code == 404,
              r.status_code)

    wr.set_status(run_id, "awaiting_review")
    r = c.post(url + "/discard", headers=ADMIN)
    check("32 discard -> 200", r.status_code == 200, r.text)
    for path, payload in (("/media-switch", {"enabled": True}),
                          ("/media-switch", {"enabled": False}), ("/media/retry", None)):
        r = c.post(url + path, headers=ADMIN, **({"json": payload} if payload else {}))
        check(f"32 closed run {path} {payload} -> 409",
              r.status_code == 409 and r.json().get("run_id") == run_id, r.text)
    r = c.get(url + "/media", headers=ADMIN)
    check("32 GET media on the closed run -> 200", r.status_code == 200, r.text)


with TestClient(app, follow_redirects=False) as client:
    main(client)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
