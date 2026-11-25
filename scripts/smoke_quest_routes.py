#!/usr/bin/env python3
"""Smoke: the admin quest routes (`app/routes/quests.py`) and their gate.

Quest system stage 1, Task 6. The REAL `app.server` app through a `TestClient` without `with` (the lifespan does
not run, so the smoke calls `init_schema()`, `quest_types.register()` and `quest_engine.register()` itself).
`STORAGE_DIR` / `INSTANCE_DIR` point at a throwaway directory before `app.server` is imported. The session lookup is
stubbed: the header `x-test-user` names the user — "admin" (a dict, role admin), "player" (the REAL `users` row of
user "demo", allowed_characters [A], settings.active_character A), anything else nobody.

Usage:
    ./.venv/bin/python scripts/smoke_quest_routes.py

FIXTURE
    Location L1 with room r1 (entry). Characters A (the player's avatar) and N (an NPC), both in L1/r1. Item "Lamp".
    "Errand" = the plan's reference quest (giver: character, place: room, thing: item; steps ① spoke_with giver
    ② at_place place ③ holds_item thing count=1). Bindings E = giver {name: N}, place L1/r1, thing Lamp.

WHAT FOLLOWS BY HAND (plan D12, D13, Task 6 brief)
 1. Gate (D12 — /quests is admin-only for reads AND writes; templates carry GM notes):
    anonymous GET /quests/templates -> 401 (default-deny gate, no session).
    player GET /quests/templates, GET /quests/catalog, POST /quests/templates -> 403 (`"/quests"` on _ADMIN_PREFIXES).
 2. Catalog: the built-in types of quest_types are registered -> "at_place" is in "conditions",
    "relationship_at_least" in "prerequisites"; "role_kinds" == ["character", "location", "room", "item"] (D6).
 3. Create: POST {"title": "Empty"} -> 200, state "draft", revision 1, origin "admin" (a new template is always a draft
    of the admin). It has no steps, so its issues contain the path "steps".
 4. Revision (D13): PUT {"state": "ready"} without base_revision -> 428, detail.code "revision_required".
    PUT {"state": "ready", "base_revision": 1} on "Empty" -> its issues are not empty (no steps) -> 422, detail.code
    "invalid", an issue at path "steps"; nothing written (GET still revision 1, state "draft").
    PUT {"summary": "x", "base_revision": 1} -> 200, revision 2. Again with base_revision 1 -> 409 "stale".
    PUT {"bogus": 1, "base_revision": 2} -> 400 "bad_request" (not an editable key; every error detail has a code).
    POST /quests/templates with the body "{not json" -> 400 "bad_json" (never a 500), with an empty body the same.
 5. Errand: POST the reference quest -> draft, revision 1, issues [] (validate_template of the reference quest is
    empty, Task 5). PUT {"state": "ready", "base_revision": 1} -> 200, state "ready", revision 2, issues [].
    GET /quests/templates/<id> -> gm_notes "GM ONLY" (the admin reads everything); unknown id -> 404.
 5b. The ready rule checks the RESULTING template (module docstring): a second Errand E2, made ready (revision 2).
    PUT {"steps": [], "base_revision": 2} does not name state, yet the result is ready with no steps -> 422
    "invalid" with an issue at "steps"; nothing written (revision 2, three steps). The way out, the same body plus
    "state": "draft" -> 200, state "draft", revision 3, no steps.
 6. Start: bindings without "thing" -> 422, detail.code "refused", an issue at "bindings.thing".
    Starting the draft "Empty" -> 422 "refused" with issue code "not_ready". Unknown template -> 404.
    Bindings E -> 200, a run R1 in state "open" (no start condition), current_step 0 (nobody spoke with N).
    GET /quests/templates -> the Errand row has open_runs 1, the Empty row 0.
 7. Runs: R2 = a second start with E, then POST /quests/runs/R2/cancel -> {"ok": true}. GET /quests/runs ->
    [R1, R2]: R1 is open and older, R2 ended and newer — open first, so R1 leads although newest-first would put R2
    first. R1: title "Errand" (from the snapshot), step_count 3, current_step 0, step_log [], issues [],
    started_game_label == GameTime.parse(R1.started_game_ts).display_label("en") and not empty, expires_label ""
    (time_limit_s 0). GET /quests/runs?state=cancelled -> [R2] only.
 8. Delete while open (Review Focus 2): DELETE the Errand -> 409, detail.code "has_open_runs"; the template is still
    there. Cancel R1 -> {"ok": true}; a second cancel -> {"ok": false} (already ended). DELETE -> 200 {"ok": true},
    GET -> 404, DELETE again -> 404. The runs keep their snapshot: R1 still lists with title "Errand".
 9. Final fix wave (review R5, R6, R7, R15; item A):
    R5: a template whose steps[0].condition is "not" nested 100 deep -> POST 200 (a draft), its issues hold
    ("shape", "steps.0.condition" + ".not" x 17) — the cap of 16 group levels; GET 200 with the same issue. Nested
    1200 deep -> SQLite's json_valid CHECK refuses the row (its JSON depth limit is 1000; measured: IntegrityError)
    -> 400 "bad_request", not a 500, and no row. A body nested 20000 deep -> json.loads raises RecursionError ->
    400 "bad_json", not a 500.
    R6: POST {"title": "x", "summary": {"a": 1}} -> 400 "bad_request"; POST with time_limit_s 10**19 (over the
    SQLite integer) -> 400; the raw body {"title": "x", "time_limit_s": 1e400} (parsed as float inf) -> 400; PUT
    {"time_limit_s": 10**19} on the Empty template -> 400; nothing of it is a 500.
    R7: a body of 300 KiB (a gm_notes string) -> 413 "too_large".
    A + R15: template "Errand for {giver}" with one step at_place place (step text "Go to {place}."), ready, started
    with E; A already stands in L1/r1, so quest_engine.evaluate("A") records it -> GET /quests/runs: that run's row
    has title "Errand for N", binding_labels {"giver": "N", "place": "Front", "thing": "Lamp"}, and its one
    step_log entry carries game_label == GameTime.parse(entry.game_ts).display_label("en") (not empty).
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


ERRAND = {
    "title": "Errand", "summary": "Run an errand for someone.", "gm_notes": "GM ONLY",
    "roles": [{"key": "giver", "kind": "character", "description": "who asks"},
              {"key": "place", "kind": "room", "description": "where to go"},
              {"key": "thing", "kind": "item", "description": "what to bring"}],
    "steps": [{"id": "s1", "text": "Talk to the giver.", "hint": "HINT ONE",
               "condition": {"type": "spoke_with", "params": {"character": "giver"}}},
              {"id": "s2", "text": "Go to the place.", "hint": "HINT TWO",
               "condition": {"type": "at_place", "params": {"place": "place"}}},
              {"id": "s3", "text": "Hold the thing.", "hint": "HINT THREE",
               "condition": {"type": "holds_item", "params": {"item": "thing", "count": 1}}}],
    "start_condition": {}, "prerequisites": {}, "time_limit_s": 0,
}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-routes-")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = tmp
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(tmp)
    import app
    assert Path(app.__file__).resolve().is_relative_to(ROOT), app.__file__
    from app.server import app as server_app
    from app.core import auth_dependency, quest_engine, quest_types
    from app.core.db import init_schema
    from app.core.game_time import GameTime
    from app.core.timeutils import set_game_time
    from app.core.users import create_user, get_user_by_id, update_user
    from app.models import character as chars, inventory, world
    from fastapi.testclient import TestClient
    import logging
    logging.disable(logging.INFO)  # request/event chatter; warnings still show
    init_schema()
    quest_types.register()
    quest_engine.register()

    world.upsert_location({"id": "L1", "name": "Hall", "entry_room": "r1",
                           "rooms": [{"id": "r1", "name": "Front"}]}, sync_world=False)
    for name in ("A", "N"):
        assert chars.save_character_profile(name, {"current_location": "L1", "current_room": "r1"},
                                            create_new=True), name
    player_id = create_user("demo", "smoke-password", allowed_characters=["A"])
    update_user(player_id, settings={"active_character": "A"})
    lamp = inventory.add_item("Lamp")["id"]
    set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
    bindings = {"giver": {"name": "N"}, "place": {"location_id": "L1", "room_id": "r1"},
                "thing": {"item_id": lamp}}

    def session_user(request):
        who = request.headers.get("x-test-user", "")
        if who == "admin":
            return {"id": "u_admin", "username": "admin", "role": "admin", "allowed_characters": []}
        if who == "player":
            return get_user_by_id(player_id)
        return None

    with patch.object(auth_dependency, "_get_session_user", side_effect=session_user):
        client = TestClient(server_app)

        def call(method, path, body=None, role="admin"):
            return client.request(method, path, json=body, headers={"x-test-user": role} if role else {})

        def code(resp):
            detail = resp.json().get("detail")
            return detail.get("code") if isinstance(detail, dict) else detail

        print("[1] gate")
        check("anonymous GET /quests/templates", call("GET", "/quests/templates", role="").status_code, 401)
        check("player is a real user row", (get_user_by_id(player_id) or {}).get("role"), "user")
        check("player GET /quests/templates", call("GET", "/quests/templates", role="player").status_code, 403)
        check("player GET /quests/catalog", call("GET", "/quests/catalog", role="player").status_code, 403)
        check("player POST /quests/templates",
              call("POST", "/quests/templates", {"title": "x"}, role="player").status_code, 403)

        print("[2] catalog")
        cat = call("GET", "/quests/catalog")
        check("catalog 200", cat.status_code, 200)
        cat = cat.json()
        check("at_place is a condition", "at_place" in {t["id"] for t in cat.get("conditions", [])}, True)
        check("relationship_at_least is a prerequisite",
              "relationship_at_least" in {t["id"] for t in cat.get("prerequisites", [])}, True)
        check("role kinds", cat.get("role_kinds"), ["character", "location", "room", "item"])

        print("[3] create")
        resp = call("POST", "/quests/templates", {"title": "Empty"})
        check("create 200", resp.status_code, 200)
        empty = resp.json() if resp.status_code == 200 else {}
        check("draft, revision 1, admin", (empty.get("state"), empty.get("revision"), empty.get("origin")),
              ("draft", 1, "admin"))
        check("issues name steps", "steps" in {i["path"] for i in empty.get("issues", [])}, True)
        eid = empty.get("id", "missing")

        print("[4] revision")
        resp = call("PUT", f"/quests/templates/{eid}", {"state": "ready"})
        check("no base_revision", (resp.status_code, code(resp)), (428, "revision_required"))
        resp = call("PUT", f"/quests/templates/{eid}", {"state": "ready", "base_revision": 1})
        check("ready without steps", (resp.status_code, code(resp)), (422, "invalid"))
        detail = resp.json().get("detail") if resp.status_code == 422 else {}
        check("invalid names steps", "steps" in {i["path"] for i in (detail or {}).get("issues", [])}, True)
        got = call("GET", f"/quests/templates/{eid}").json()
        check("nothing written", (got.get("revision"), got.get("state")), (1, "draft"))
        resp = call("PUT", f"/quests/templates/{eid}", {"summary": "x", "base_revision": 1})
        check("edit -> revision 2", (resp.status_code, resp.json().get("revision")), (200, 2))
        resp = call("PUT", f"/quests/templates/{eid}", {"summary": "y", "base_revision": 1})
        check("stale", (resp.status_code, code(resp)), (409, "stale"))
        resp = call("PUT", f"/quests/templates/{eid}", {"bogus": 1, "base_revision": 2})
        check("not editable", (resp.status_code, code(resp)), (400, "bad_request"))
        resp = client.request("POST", "/quests/templates", content=b"{not json",
                              headers={"x-test-user": "admin", "content-type": "application/json"})
        check("malformed JSON", (resp.status_code, code(resp)), (400, "bad_json"))
        resp = client.request("POST", "/quests/templates", content=b"",
                              headers={"x-test-user": "admin", "content-type": "application/json"})
        check("empty body", (resp.status_code, code(resp)), (400, "bad_json"))

        print("[5] errand")
        resp = call("POST", "/quests/templates", ERRAND)
        errand = resp.json() if resp.status_code == 200 else {}
        check("create errand", (resp.status_code, errand.get("state"), errand.get("issues")), (200, "draft", []))
        tid = errand.get("id", "missing")
        resp = call("PUT", f"/quests/templates/{tid}", {"state": "ready", "base_revision": 1})
        got = resp.json()
        check("ready", (resp.status_code, got.get("state"), got.get("revision"), got.get("issues")),
              (200, "ready", 2, []))
        check("admin reads gm_notes", call("GET", f"/quests/templates/{tid}").json().get("gm_notes"), "GM ONLY")
        check("unknown template", call("GET", "/quests/templates/qt_nope").status_code, 404)

        print("[5b] the ready rule and its way out")
        e2 = call("POST", "/quests/templates", ERRAND).json().get("id", "missing")
        check("E2 ready", call("PUT", f"/quests/templates/{e2}", {"state": "ready", "base_revision": 1}).status_code,
              200)
        resp = call("PUT", f"/quests/templates/{e2}", {"steps": [], "base_revision": 2})
        detail = resp.json().get("detail") if resp.status_code == 422 else {}
        check("emptying a ready template", (resp.status_code, code(resp)), (422, "invalid"))
        check("invalid names steps", "steps" in {i["path"] for i in (detail or {}).get("issues", [])}, True)
        got = call("GET", f"/quests/templates/{e2}").json()
        check("nothing written", (got.get("revision"), got.get("state"), len(got.get("steps") or [])),
              (2, "ready", 3))
        resp = call("PUT", f"/quests/templates/{e2}", {"steps": [], "state": "draft", "base_revision": 2})
        got = resp.json()
        check("with state draft", (resp.status_code, got.get("state"), got.get("revision"), got.get("steps")),
              (200, "draft", 3, []))

        print("[6] start")
        partial = {k: v for k, v in bindings.items() if k != "thing"}
        resp = call("POST", f"/quests/templates/{tid}/start", {"bindings": partial})
        check("missing binding", (resp.status_code, code(resp)), (422, "refused"))
        issues = (resp.json().get("detail") or {}).get("issues", []) if resp.status_code == 422 else []
        check("issue at bindings.thing", "bindings.thing" in {i["path"] for i in issues}, True)
        resp = call("POST", f"/quests/templates/{eid}/start", {"bindings": {}})
        issues = (resp.json().get("detail") or {}).get("issues", []) if resp.status_code == 422 else []
        check("draft refused", (resp.status_code, code(resp), [i["code"] for i in issues]),
              (422, "refused", ["not_ready"]))
        check("start unknown", call("POST", "/quests/templates/qt_nope/start", {"bindings": {}}).status_code, 404)
        resp = call("POST", f"/quests/templates/{tid}/start", {"bindings": bindings})
        r1 = resp.json() if resp.status_code == 200 else {}
        check("started", (resp.status_code, r1.get("state"), r1.get("current_step")), (200, "open", 0))
        rows = {t["id"]: t for t in call("GET", "/quests/templates").json().get("templates", [])}
        check("open_runs", (rows.get(tid, {}).get("open_runs"), rows.get(eid, {}).get("open_runs")), (1, 0))
        check("list row keys", sorted(rows.get(tid, {})),
              sorted(["id", "title", "state", "origin", "revision", "updated_at", "open_runs"]))

        print("[7] runs")
        r2 = call("POST", f"/quests/templates/{tid}/start", {"bindings": bindings}).json()
        check("cancel R2", call("POST", f"/quests/runs/{r2.get('id')}/cancel").json(), {"ok": True})
        runs = call("GET", "/quests/runs").json().get("runs", [])
        check("open first", [(r["id"], r["state"]) for r in runs],
              [(r1.get("id"), "open"), (r2.get("id"), "cancelled")])
        first = runs[0] if runs else {}
        check("R1 row", (first.get("title"), first.get("step_count"), first.get("current_step"),
                         first.get("step_log"), first.get("issues"), first.get("expires_label")),
              ("Errand", 3, 0, [], [], ""))
        want = GameTime.parse(r1.get("started_game_ts") or "Y0001-D001T00:00:00").display_label("en")
        check("started label", (first.get("started_game_label"), bool(want)), (want, True))
        check("bindings", first.get("bindings"), bindings)
        only = call("GET", "/quests/runs?state=cancelled").json().get("runs", [])
        check("filter by state", [r["id"] for r in only], [r2.get("id")])
        check("bad state filter", call("GET", "/quests/runs?state=nope").status_code, 400)

        print("[8] delete")
        resp = call("DELETE", f"/quests/templates/{tid}")
        check("delete with an open run", (resp.status_code, code(resp)), (409, "has_open_runs"))
        check("still there", call("GET", f"/quests/templates/{tid}").status_code, 200)
        check("cancel R1", call("POST", f"/quests/runs/{r1.get('id')}/cancel").json(), {"ok": True})
        check("cancel R1 again", call("POST", f"/quests/runs/{r1.get('id')}/cancel").json(), {"ok": False})
        resp = call("DELETE", f"/quests/templates/{tid}")
        check("delete", (resp.status_code, resp.json()), (200, {"ok": True}))
        check("gone", call("GET", f"/quests/templates/{tid}").status_code, 404)
        check("delete again", call("DELETE", f"/quests/templates/{tid}").status_code, 404)
        titles = {r["id"]: r["title"] for r in call("GET", "/quests/runs").json().get("runs", [])}
        check("run keeps its snapshot", titles.get(r1.get("id")), "Errand")

        print("[9] final fix wave")
        def nested(depth):
            expr = {"type": "at_place", "params": {"place": "place"}}
            for _ in range(depth):
                expr = {"not": expr}
            return {**ERRAND, "title": f"Deep {depth}", "steps": [{"id": "s1", "text": "Deep.", "condition": expr}]}

        before = len(call("GET", "/quests/templates").json().get("templates", []))
        resp = call("POST", "/quests/templates", nested(1200))
        check("1200 deep: refused, no row", (resp.status_code, code(resp),
                                             len(call("GET", "/quests/templates").json().get("templates", []))),
              (400, "bad_request", before))
        resp = call("POST", "/quests/templates", nested(100))
        deep_t = resp.json() if resp.status_code == 200 else {}
        want_issue = ("shape", "steps.0.condition" + ".not" * 17)
        check("100 deep: POST", (resp.status_code,
                                  want_issue in {(i["code"], i["path"]) for i in deep_t.get("issues", [])}),
              (200, True))
        resp = call("GET", f"/quests/templates/{deep_t.get('id', 'missing')}")
        check("100 deep: GET", (resp.status_code, want_issue in {
            (i["code"], i["path"]) for i in (resp.json().get("issues", []) if resp.status_code == 200 else [])}),
              (200, True))
        raw = ('{"title": "x", "summary": ' + "[" * 20000 + "]" * 20000 + "}").encode()
        resp = client.request("POST", "/quests/templates", content=raw,
                              headers={"x-test-user": "admin", "content-type": "application/json"})
        check("20000 deep body", (resp.status_code, code(resp)), (400, "bad_json"))
        resp = call("POST", "/quests/templates", {"title": "x", "summary": {"a": 1}})
        check("summary not text", (resp.status_code, code(resp)), (400, "bad_request"))
        resp = call("POST", "/quests/templates", {"title": "x", "time_limit_s": 10 ** 19})
        check("time limit over the SQLite integer", (resp.status_code, code(resp)), (400, "bad_request"))
        resp = client.request("POST", "/quests/templates", content=b'{"title": "x", "time_limit_s": 1e400}',
                              headers={"x-test-user": "admin", "content-type": "application/json"})
        check("time limit inf", (resp.status_code, code(resp)), (400, "bad_request"))
        rev = call("GET", f"/quests/templates/{eid}").json().get("revision")
        resp = call("PUT", f"/quests/templates/{eid}", {"time_limit_s": 10 ** 19, "base_revision": rev})
        check("PUT time limit over the SQLite integer", (resp.status_code, code(resp)), (400, "bad_request"))
        resp = call("POST", "/quests/templates", {"title": "big", "gm_notes": "x" * (300 * 1024)})
        check("300 KiB body", (resp.status_code, code(resp)), (413, "too_large"))
        labelled = {**ERRAND, "title": "Errand for {giver}",
                    "steps": [{"id": "s1", "text": "Go to {place}.", "hint": "",
                               "condition": {"type": "at_place", "params": {"place": "place"}}}]}
        lt = call("POST", "/quests/templates", labelled).json()
        call("PUT", f"/quests/templates/{lt.get('id')}", {"state": "ready", "base_revision": 1})
        lr = call("POST", f"/quests/templates/{lt.get('id')}/start", {"bindings": bindings}).json()
        quest_engine.evaluate("A")
        row = next((r for r in call("GET", "/quests/runs").json().get("runs", []) if r["id"] == lr.get("id")), {})
        check("run row title rendered", row.get("title"), "Errand for N")
        check("run row labels", row.get("binding_labels"), {"giver": "N", "place": "Front", "thing": "Lamp"})
        log = row.get("step_log") or [{}]
        want = GameTime.parse(log[0].get("game_ts") or "Y0001-D001T00:00:00").display_label("en")
        check("step log game_label", (log[0].get("game_label"), bool(want)), (want, True))

    quest_engine.drain()
    if FAILURES:
        print(f"FAIL smoke_quest_routes: {len(FAILURES)} failed")
        return 1
    print("PASS smoke_quest_routes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
