#!/usr/bin/env python3
"""Smoke: the character list's "Build all open" (``app/core/figure_batch.py`` + ``/characters/build-all*``).

Usage: ./.venv/bin/python scripts/smoke_figure_batch.py

Runs without a server on a temporary world (``STORAGE_DIR`` / ``INSTANCE_DIR`` set to temp dirs BEFORE
``app.server`` is imported). The per-character work is NOT run: ``figure_build``'s Run all / Build / state
functions are replaced by a small simulation (each started run takes ``DUR`` seconds in a thread), so what is
checked is the runner's order, cap, skips and refusals. Expected values, by hand:

World (base kinds still due · outfit due · hub jobs of the badges):
  A: [plain_body]       · outfit · base 4 + outfit 3
  B: []                 · —      · nothing open            -> not a candidate
  C: [plain_body] (its run fails "views refused") · outfit · 4 + 3
  D: []                 · outfit · 0 + 3
  E: []                 · outfit (its Build records failed texture "view refused") · 0 + 3
  F: [face_retexture]   · —      · Run all's extra kind, 2 hub jobs (the badges do not count it)
  G: []                 · outfit (its Build ends SUPERSEDED: no failed step, the outfit stays planned) · 0 + 3
  A failing or superseded Build leaves its outfit step open (as the real Build does), so E and G still show an
  outfit badge afterwards.

P) Preview: candidates [A, C, D, E, F, G] (B absent); hub jobs 7 + 7 + 3 + 3 + 2 + 3 = 25; F's base count 0 + 1 = 1.
R) Run: 6 candidates, at most 3 at once, each runs >= DUR -> the first three start together: max concurrent == 3.
   A: its base run is logged before its Build -> done.  C: plain body failed -> failed, reason names
   "views refused", and NO Build of C was started.  D: done.  E: failed, reason "texture: view refused" and
   "Left open: 0 base / 1 outfit steps".  F: the face kind ran, the Build answered current -> done (no Build
   logged).  G: its Build recorded no failure, yet a step stays open -> failed (the old verdict, which read only
   state()['failed'], said done), reason "Left open: 0 base / 1 outfit steps" and the superseded note.
   Counts: done 3 (A, D, F), failed 3 (C, E, G). Builds logged: A, D, E, G (4).
   German (lang "de"): G's reason starts "Offen geblieben: 0 Grundkörper- / 1 Outfit-Schritte".
S) A second start while running -> "running"; media switched off -> "media_off" (nothing starts).
X) Cancel: with DUR long, cancel once three characters are in their base/outfit phase -> those three finish,
   the other three are "skipped" (reason "Cancelled before it started"): skipped == 3.
E) Routes: anonymous GET /characters/build-all -> 401; player -> 403; admin -> 200; admin POST start while one
   runs -> 409 with the German detail "Alle offenen bauen läuft bereits" for ?lang=de; "build-all" is a
   reserved route segment.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_figure_batch_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
for sub in ("world", "instance", "clips"):
    (TMP / sub).mkdir()

from app.core import paths  # noqa: E402
paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

from fastapi.testclient import TestClient  # noqa: E402
from app.server import app  # noqa: E402
from app.core import figure_batch, figure_build, sessions, users  # noqa: E402
from app.core.character_name import RESERVED_ROUTE_SEGMENTS  # noqa: E402
import app.imagegen.base as imagegen_base  # noqa: E402
import app.models.character as character_model  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        failures.append(name)


DUR = 0.25
NAMES = ["A", "B", "C", "D", "E", "F", "G"]
sim_lock = threading.Lock()
world, busy, last, log = {}, {}, {}, []
active = {"now": 0, "max": 0}


def reset():
    with sim_lock:
        world.clear()
        world.update({
            "A": {"base": ["plain_body"], "outfit": True},
            "B": {"base": [], "outfit": False},
            "C": {"base": ["plain_body"], "outfit": True, "fail_plain": "views refused"},
            "D": {"base": [], "outfit": True},
            "E": {"base": [], "outfit": True, "fail_build": {"texture": {"error": "view refused"}}},
            "F": {"base": ["face_retexture"], "outfit": False},
            "G": {"base": [], "outfit": True, "supersede": {"step": "texture", "label": "Texture",
                                                            "note": "the figure moved"}},
        })
        busy.clear()
        last.clear()
        log.clear()
        active.update(now=0, max=0)


def _later(fn):
    def run():
        time.sleep(DUR)
        fn()
    threading.Thread(target=run, daemon=True).start()


def base_run_all(name, *, profile=None):
    with sim_lock:
        kinds = world[name]["base"]
        kind = kinds[0] if kinds else ""
        return {"kind": kind, "hub_jobs": (4 if kind == "plain_body" else 2) if kind else 0,
                "last": dict(last[name]) if name in last else None}


def start_base_run_all(name):
    with sim_lock:
        if name in busy:
            return {"status": "busy", "reason": "busy"}
        kinds = world[name]["base"]
        if not kinds:
            return {"status": "current"}
        kind = kinds[0]
        busy[name] = "base"
        log.append((name, "base", kind))

    def done():
        with sim_lock:
            if kind == "plain_body" and world[name].get("fail_plain"):
                last[name] = {"error": world[name]["fail_plain"]}
            else:
                world[name]["base"].pop(0)
                last[name] = {"error": ""}
            busy.pop(name, None)
    _later(done)
    return {"status": "started", "kind": kind}


def base_step_in_flight(name):
    with sim_lock:
        return "Base body Run all" if busy.get(name) == "base" else ""


def running(name):
    with sim_lock:
        return busy.get(name) == "build"


def start(name, *, reason, automatic=False):
    with sim_lock:
        if busy.get(name) == "base":
            return {"status": "base_busy", "reason": "busy"}
        if busy.get(name) == "build":
            return {"status": "queued"}
        if not world[name]["outfit"]:
            return {"status": "current"}
        busy[name] = "build"
        log.append((name, "build", reason))

    def done():
        with sim_lock:
            failed = dict(world[name].get("fail_build") or {})
            sup = world[name].get("supersede")
            world[name]["outfit"] = bool(failed or sup)   # a failed or superseded step stays planned
            world[name]["failed"] = failed
            world[name]["superseded"] = dict(sup) if sup else None
            busy.pop(name, None)
    _later(done)
    return {"status": "started"}


def state(name):
    with sim_lock:
        return {"failed": dict(world[name].get("failed") or {}), "superseded": world[name].get("superseded")}


def open_steps(name):
    with sim_lock:
        w = world[name]
        plain = "plain_body" in w["base"]
        return {"building": busy.get(name) == "build",
                "base": {"count": 1 if plain else 0, "hub_jobs": 4 if plain else 0, "hold": plain, "steps": []},
                "outfit": {"count": 1 if w["outfit"] else 0, "hub_jobs": 3 if w["outfit"] else 0, "hold": False,
                           "steps": []}}


figure_build.base_run_all = base_run_all
figure_build.start_base_run_all = start_base_run_all
figure_build.base_step_in_flight = base_step_in_flight
figure_build.running = running
figure_build.start = start
figure_build.state = state
figure_build.open_steps = open_steps
figure_build.on_pipeline = lambda name, profile=None: True
pushes = {"n": 0}
figure_build._notify_build_changed = lambda: pushes.__setitem__("n", pushes["n"] + 1)
character_model.list_available_characters = lambda include_pooled=False, include_dormant=False, **_: list(NAMES)
media = {"on": True}
imagegen_base.media_generation_enabled = lambda: media["on"]
figure_batch.POLL_S = 0.02

_real_run_character = figure_batch._run_character


def counted_run_character(name):
    with sim_lock:
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
    try:
        _real_run_character(name)
    finally:
        with sim_lock:
            active["now"] -= 1


figure_batch._run_character = counted_run_character


def wait_done(timeout=30.0):
    end = time.monotonic() + timeout
    while figure_batch.status()["running"] and time.monotonic() < end:
        time.sleep(0.02)


# P) preview
reset()
p = figure_batch.candidates()
check("P candidates", [r["name"] for r in p["characters"]], ["A", "C", "D", "E", "F", "G"])
check("P hub jobs", p["hub_jobs"], 25)
check("P F base count", next(r for r in p["characters"] if r["name"] == "F")["base"], 1)

# R) + S)
reset()
check("R start", figure_batch.start()["status"], "started")
check("S second start", figure_batch.start()["status"], "running")
wait_done()
st = figure_batch.status()
rows = {r["name"]: r for r in st["characters"]}
check("R max concurrent", active["max"], 3)
check("R order", [r["name"] for r in st["characters"]], ["A", "C", "D", "E", "F", "G"])
check("R A phase", rows["A"]["phase"], "done")
check("R A base before build", log.index(("A", "base", "plain_body")) < log.index(("A", "build", "build_all")), True)
check("R C phase", rows["C"]["phase"], "failed")
check("R C reason names the failure", "views refused" in rows["C"]["reason"], True)
check("R C no build", [e for e in log if e[0] == "C" and e[1] == "build"], [])
check("R D phase", rows["D"]["phase"], "done")
check("R E phase", rows["E"]["phase"], "failed")
check("R E reason", "texture: view refused" in rows["E"]["reason"], True)
check("R E left open", "Left open: 0 base / 1 outfit steps" in rows["E"]["reason"], True)
check("R G phase (superseded, step still planned)", rows["G"]["phase"], "failed")
check("R G left open", "Left open: 0 base / 1 outfit steps" in rows["G"]["reason"], True)
check("R G superseded note", "Texture was superseded" in rows["G"]["reason"], True)
de_g = next(r for r in figure_batch.status("de")["characters"] if r["name"] == "G")["reason"]
check("R G German", de_g.startswith("Offen geblieben: 0 Grundkörper- / 1 Outfit-Schritte"), True)
check("R F phase", rows["F"]["phase"], "done")
check("R F face ran", ("F", "base", "face_retexture") in log, True)
check("R counts", (st["counts"].get("done"), st["counts"].get("failed")), (3, 3))
check("R builds", sorted(e[0] for e in log if e[1] == "build"), ["A", "D", "E", "G"])
check("R pushed", pushes["n"] > 0, True)
media["on"] = False
check("S media off", figure_batch.start()["status"], "media_off")
check("S media off: nothing runs", figure_batch.status()["running"], False)
media["on"] = True

# X) cancel
reset()
DUR = 1.0
figure_batch.start()
end = time.monotonic() + 10
while time.monotonic() < end:
    phases = [r.get("phase") for r in figure_batch.status()["characters"]]
    if sum(1 for ph in phases if ph in ("base", "outfit")) >= 3:
        break
    time.sleep(0.01)
check("X cancel", figure_batch.cancel(), True)
wait_done()
st = figure_batch.status()
check("X skipped", st["counts"].get("skipped"), 3)
check("X skipped reason", {r["reason"] for r in st["characters"] if r["phase"] == "skipped"},
      {figure_batch.CANCELLED})
check("X cancel when idle", figure_batch.cancel(), False)

# E) routes under the real gate
reset()
DUR = 1.0
check("E reserved", "build-all" in RESERVED_ROUTE_SEGMENTS, True)
admin = users.create_user("demo", "demo-pass-123456", role="admin")
player = users.create_user("demo2", "demo-pass-123456", role="user")
anon = TestClient(app, follow_redirects=False)
check("E anonymous", anon.get("/characters/build-all").status_code, 401)
pc = TestClient(app, follow_redirects=False)
pc.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(player))
check("E player", pc.get("/characters/build-all").status_code, 403)
check("E player start", pc.post("/characters/build-all/start", json={}).status_code, 403)
ac = TestClient(app, follow_redirects=False)
ac.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(admin))
check("E admin status", ac.get("/characters/build-all").status_code, 200)
check("E admin preview", ac.get("/characters/build-all/preview").json().get("hub_jobs"), 25)
check("E admin start", ac.post("/characters/build-all/start", json={}).status_code, 202)
second = ac.post("/characters/build-all/start?lang=de", json={})
check("E admin second start", second.status_code, 409)
check("E admin second start German", second.json().get("detail"), "Alle offenen bauen läuft bereits")
check("E admin cancel", ac.post("/characters/build-all/cancel", json={}).status_code, 200)
wait_done()

print("FAILED: " + ", ".join(failures) if failures else "all ok")
sys.exit(1 if failures else 0)
