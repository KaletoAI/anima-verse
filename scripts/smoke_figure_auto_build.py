#!/usr/bin/env python3
"""Build automatically — today's triggers run the Build, a mode change only
marks (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 8,
rulings 7a/7b; ``app/core/figure_build.py`` ``auto_build_on`` / ``request`` /
``wearers`` / ``set_auto_build``, ``model_refs.schedule_outfit_render``'s
Build timer, ``garments.after_base_model`` / ``base_body.after_mesh_item_ready``
as requests, the routes ``POST /characters/{c}/figure/auto-build``,
``GET /inventory/items/{id}/wearers``, ``POST /inventory/items/{id}/build-wearers``).

Usage:
    ./.venv/bin/python scripts/smoke_figure_auto_build.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no
GPU, no server. The "world" part uses the real resolver, the real plan, the
real queue of ``figure_build.start`` and the real inventory; only the Build's
run body (``figure_build._run``) is a recorder (it can be held in flight per
character), the render threads (``model_refs._fire_kinds``,
``model_refs.trigger_now``) are recorders and the debounce is 0.1 s. Kira and
Kai are on the base-body pipeline without any built body, so their real plan
always has steps (the plain body is missing); Mara is off the pipeline.

Expected, by hand from the brief:

[1] Auto on (no ``figure_auto_build`` key = on): Kira equips the blouse →
    after the debounce ONE run, ``(Kira, "outfit_change", automatic)``; the
    renders fired for Kira are ``pose`` only (no ``tpose`` kind, no
    ``trigger_now(("tpose",))``); Mara (off the pipeline) equips the scarf →
    her renders are ``tpose`` and ``pose``, no Build.
[2] Auto off (``set_auto_build(Kira, False)``): Kira equips the skirt → no
    run after the debounce; ``figure.pending_changes(Kira)`` is not empty; a
    manual ``start`` → "started", run ``(Kira, "manual", manual)``; a manual
    run held in flight, auto switched ON and OFF again meanwhile → the run is
    still going (``state.running``) and ends once released. ``auto_build_on``
    is False also with auto on while the world switch
    (``model_ref_renders_enabled``) is off.
[3] ``garments.after_base_model(Kira)`` → ``request(Kira, "body_change")``;
    ``base_body.after_mesh_item_ready(Kira, blouse)`` (worn) →
    ``request(Kira, "piece_ready")``; for an item Kira does not wear → no
    request. With auto off both answer False and no run starts.
[4] Review Focus 1: the blouse (painted) is worn by Kai and Kira; Kai's Build
    is in flight. ``update_item(blouse, outfit_piece.mesh_mode="own_mesh")``
    → no new run, no render invalidation, Kai still running with 0
    follow-ups; each wearer has exactly one more pending change, keyed
    ``blouse`` with wanted ``own_mesh``. ``GET …/wearers`` (admin) → both,
    each ``changes >= 1``, mode ``own_mesh``; ``POST …/build-wearers`` →
    ``{Kai: "queued", Kira: "started"}``.
[5] An item nobody wears → ``wearers == []``, GET cost ``hub_jobs == 0``.
[6] Auth through the real gate (stubbed session): a player allowed to see
    Kira → 403 on GET wearers, POST build-wearers and POST
    …/figure/auto-build; admin POST auto-build ``{enabled: false}`` →
    ``{"auto_build": false}`` and the profile key stored False.
[7] Ruling 7a (the stubbed world of ``smoke_figure_build_plan``: hair wanted
    HairDeck, its chain failed for its fsig, the model built as delivered):
    ``plan`` = ``[hair]`` with ``failed`` set, label "… — failed — Retry",
    jobs 0 → cost 0; an automatic ``start`` → "current"; GET status
    ``failed``, hair row ``failed``; ``plan(explicit=True)`` = hair, fits,
    assemble; a manual Build runs ``run_queued(…, explicit=True)``, then the
    refit and the assembly. Base older + the cached hair failure, automatic:
    the plain body runs, the hair chain does NOT run, ``failed["hair"]`` is
    the cached error.
[8] Fails on the old code: at 8076597d ``figure_build.py`` has no
    ``def request(`` / ``def wearers(``, ``routes/inventory.py`` no
    ``/wearers`` route, ``schedule_outfit_render`` no Build timer, and
    ``garments.after_base_model`` enqueues chains itself.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BASELINE = "8076597d"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return bool(cond())


def setup(root: Path):
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
    from app.core import config
    config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
    from app.core import db
    db.init_schema()
    plugins = root / "plugins"
    shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
    from app.plugins.loader import discover_packages
    discover_packages(plugins, force=True)


# --- The world part (real plan, real queue, a recording run body) ----------------------------

RUNS = []                 # (name, reason, "auto" | "manual")
HOLD = {}                 # name -> (entered Event, release Event)
FIRED = []                # (name, kinds) of the render threads
NOW = []                  # trigger_now calls (name, kinds)
REQUESTS = []             # (name, trigger, result)


def install_world_stubs():
    from app.core import figure_build as fb, model_refs

    def run(name, reason, *, automatic=False):
        RUNS.append((name, reason, "auto" if automatic else "manual"))
        hold = HOLD.get(name)
        if hold:
            hold[0].set()
            hold[1].wait(10)
    fb._run = run
    model_refs._fire_kinds = lambda name, kinds, force=False, tpose_view=None: FIRED.append((name, tuple(kinds)))
    model_refs.trigger_now = lambda name, kinds=None, **kw: NOW.append((name, kinds))
    model_refs._debounce_seconds = lambda: 0.1
    real_request = fb.request

    def request(name, trigger):
        result = real_request(name, trigger)
        REQUESTS.append((name, trigger, result))
        return result
    fb.request = request


def idle(name):
    from app.core import figure_build as fb
    return wait_for(lambda: not fb.state(name)["running"])


def world_section():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core import auth_dependency, base_body, figure, figure_build as fb, garments, model_refs
    from app.models import inventory
    from app.models.character import get_character_profile, save_character_profile
    from app.routes import figure as figure_route, inventory as inventory_route

    install_world_stubs()
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
    for name in ("Kira", "Kai", "Mara"):
        check(f"create {name}", save_character_profile(name, dict(human), create_new=True), True)
    check("pipeline Kira", base_body.set_pipeline("Kira", True), True)
    check("pipeline Kai", base_body.set_pipeline("Kai", True), True)

    def piece(name, slot, mode="painted"):
        return inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a {name.lower()}",
                                  outfit_piece={"slots": [slot], "covers": [], "outfit_types": ["casual"],
                                                "mesh_mode": mode})["id"]
    blouse, skirt, scarf, hat = piece("Blouse", "top"), piece("Skirt", "bottom"), piece("Scarf", "neck"), \
        piece("Hat", "head")
    for name in ("Kira", "Kai", "Mara"):
        for iid in (blouse, skirt, scarf, hat):
            inventory.add_to_inventory(name, iid)

    print("[1] auto on: an outfit change runs the Build after the debounce")
    check("[1] auto_build_on(Kira) without the key", fb.auto_build_on("Kira"), True)
    check("[1] Kira equips the blouse", inventory.equip_piece("Kira", blouse, source="smoke")["status"], "ok")
    check("[1] one run after the debounce", wait_for(lambda: len(RUNS) >= 1), True)
    time.sleep(0.3)
    check("[1] runs", RUNS, [("Kira", "outfit_change", "auto")])
    check("[1] Kira's renders: pose only", [k for n, k in FIRED if n == "Kira"], [("pose",)])
    check("[1] no trigger_now for Kira", [c for c in NOW if c[0] == "Kira"], [])
    check("[1] Mara equips the scarf", inventory.equip_piece("Mara", scarf, source="smoke")["status"], "ok")
    check("[1] Mara's renders after the debounce",
          wait_for(lambda: len([1 for n, _k in FIRED if n == "Mara"]) >= 2), True)
    check("[1] Mara's renders: tpose and pose", sorted(k for n, k in FIRED if n == "Mara"), [("pose",), ("tpose",)])
    check("[1] still one run (Mara is off the pipeline)", len(RUNS), 1)
    check("[1] Kira idle", idle("Kira"), True)

    print("[2] auto off: the change only stays marked; a manual Build still runs")
    RUNS.clear()
    check("[2] set_auto_build(Kira, False)", fb.set_auto_build("Kira", False), True)
    check("[2] profile key", (get_character_profile("Kira") or {}).get("figure_auto_build"), False)
    check("[2] auto_build_on(Kira)", fb.auto_build_on("Kira"), False)
    check("[2] Kira equips the skirt", inventory.equip_piece("Kira", skirt, source="smoke")["status"], "ok")
    time.sleep(0.5)
    check("[2] no run", RUNS, [])
    check("[2] pending_changes not empty", bool(figure.pending_changes("Kira")), True)
    check("[2] manual start", fb.start("Kira", reason="manual")["status"], "started")
    check("[2] the manual run", wait_for(lambda: RUNS == [("Kira", "manual", "manual")]), True)
    check("[2] idle", idle("Kira"), True)
    entered, release = threading.Event(), threading.Event()
    HOLD["Kira"] = (entered, release)
    check("[2] manual start (held)", fb.start("Kira", reason="manual")["status"], "started")
    check("[2] in flight", entered.wait(5), True)
    fb.set_auto_build("Kira", True)
    fb.set_auto_build("Kira", False)
    check("[2] still running after auto was switched off", fb.state("Kira")["running"], True)
    release.set()
    check("[2] the run ended", idle("Kira"), True)
    HOLD.pop("Kira")
    saved_cfg = model_refs._cfg
    model_refs._cfg = lambda key, default=None: False if key == "model_ref_renders_enabled" else saved_cfg(key, default)
    check("[2] world switch off: auto_build_on(Kai) False", fb.auto_build_on("Kai"), False)
    model_refs._cfg = saved_cfg
    check("[2] world switch on again: auto_build_on(Kai)", fb.auto_build_on("Kai"), True)

    print("[3] body change / piece ready -> request")
    RUNS.clear()
    fb.set_auto_build("Kira", True)
    saved_base = base_body.current_base
    base_body.current_base = lambda name, profile=None: ("bsig", "sha") if name == "Kira" else None
    try:
        REQUESTS.clear()
        check("[3] after_base_model", garments.after_base_model("Kira"), True)
        check("[3] request body_change", REQUESTS, [("Kira", "body_change", True)])
        check("[3] idle", idle("Kira"), True)
        REQUESTS.clear()
        check("[3] after_mesh_item_ready (worn)", base_body.after_mesh_item_ready("Kira", blouse), True)
        check("[3] request piece_ready", REQUESTS, [("Kira", "piece_ready", True)])
        check("[3] idle", idle("Kira"), True)
        REQUESTS.clear()
        check("[3] after_mesh_item_ready (not worn)", base_body.after_mesh_item_ready("Kira", hat), False)
        check("[3] no request", REQUESTS, [])
        check("[3] runs", RUNS, [("Kira", "body_change", "auto"), ("Kira", "piece_ready", "auto")])
        RUNS.clear()
        fb.set_auto_build("Kira", False)
        check("[3] auto off: after_base_model", garments.after_base_model("Kira"), False)
        check("[3] auto off: after_mesh_item_ready", base_body.after_mesh_item_ready("Kira", blouse), False)
        time.sleep(0.2)
        check("[3] auto off: no run", RUNS, [])
        fb.set_auto_build("Kira", True)
    finally:
        base_body.current_base = saved_base

    print("[4] a mode switch on an item worn by two, one of them building")
    check("[4] Kai equips the blouse", inventory.equip_piece("Kai", blouse, source="smoke")["status"], "ok")
    time.sleep(0.4)            # Kai's own outfit-change run after the debounce
    check("[4] Kai idle", idle("Kai"), True)
    RUNS.clear()
    entered, release = threading.Event(), threading.Event()
    HOLD["Kai"] = (entered, release)
    check("[4] Kai's Build", fb.start("Kai", reason="manual")["status"], "started")
    check("[4] Kai in flight", entered.wait(5), True)
    before = {n: [c["key"] for c in figure.pending_changes(n)] for n in ("Kai", "Kira")}
    invalidated = []
    saved_inv = inventory._invalidate_renders_for_item
    inventory._invalidate_renders_for_item = lambda iid: invalidated.append(iid)
    try:
        stored = inventory.get_item(blouse)
        updated = inventory.update_item(blouse, {"outfit_piece": {**stored["outfit_piece"], "mesh_mode": "own_mesh"}})
    finally:
        inventory._invalidate_renders_for_item = saved_inv
    check("[4] mode stored", (updated or {}).get("outfit_piece", {}).get("mesh_mode"), "own_mesh")
    time.sleep(0.4)
    check("[4] no new run", RUNS, [("Kai", "manual", "manual")])
    check("[4] no render invalidation", invalidated, [])
    st = fb.state("Kai")
    check("[4] Kai untouched (running, no follow-up)", (st["running"], st["queued"]), (True, 0))
    for n in ("Kai", "Kira"):
        after = figure.pending_changes(n)
        check(f"[4] {n}: one more change", len(after) - len(before[n]), 1)
        new = [c for c in after if c["key"] not in before[n]]
        check(f"[4] {n}: the blouse, wanted own_mesh", [(c["key"], c["wanted"]) for c in new],
              [(blouse, "own_mesh")])

    users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Kira", "Kai"]},
             "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}
    auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-test-user", ""))
    app = FastAPI()
    app.middleware("http")(auth_dependency.auth_gate_middleware)
    app.middleware("http")(auth_dependency.user_context_middleware)
    app.include_router(inventory_route.router)
    app.include_router(figure_route.router)
    client = TestClient(app)
    admin, player = {"x-test-user": "admin"}, {"x-test-user": "user"}
    r = client.get(f"/inventory/items/{blouse}/wearers", headers=admin)
    check("[4] GET wearers", r.status_code, 200)
    body = r.json() if r.status_code == 200 else {}
    check("[4] wearers names", [w["name"] for w in body.get("wearers") or []], ["Kai", "Kira"])
    check("[4] wearers changes >= 1", all(w["changes"] >= 1 for w in body.get("wearers") or []), True)
    check("[4] wearers keys", sorted(body), ["cost", "item_id", "mode", "wearers"])
    check("[4] mode", body.get("mode"), "own_mesh")
    check("[4] cost keys", sorted(body.get("cost") or {}), ["hub_jobs", "note"])
    r = client.post(f"/inventory/items/{blouse}/build-wearers", headers=admin)
    check("[4] POST build-wearers", (r.status_code, r.json()), (200, {"started": {"Kai": "queued", "Kira": "started"}}))
    release.set()
    check("[4] Kai's follow-up ran", wait_for(lambda: ("Kai", "build_wearers", "manual") in RUNS), True)
    check("[4] idle", idle("Kai") and idle("Kira"), True)
    HOLD.pop("Kai")

    print("[5] an item nobody wears")
    check("[5] wearers", fb.wearers(hat), [])
    r = client.get(f"/inventory/items/{hat}/wearers", headers=admin)
    check("[5] GET", (r.status_code, (r.json() or {}).get("wearers"), ((r.json() or {}).get("cost") or {}).get("hub_jobs")),
          (200, [], 0))

    print("[6] auth")
    check("[6] player GET wearers", client.get(f"/inventory/items/{blouse}/wearers", headers=player).status_code, 403)
    check("[6] player POST build-wearers",
          client.post(f"/inventory/items/{blouse}/build-wearers", headers=player).status_code, 403)
    check("[6] player POST auto-build",
          client.post("/characters/Kira/figure/auto-build", json={"enabled": False}, headers=player).status_code, 403)
    r = client.post("/characters/Kira/figure/auto-build", json={"enabled": False}, headers=admin)
    check("[6] admin POST auto-build", (r.status_code, r.json()), (200, {"auto_build": False}))
    check("[6] stored", (get_character_profile("Kira") or {}).get("figure_auto_build"), False)
    check("[6] GET figure auto_build", client.get("/characters/Kira/figure", headers=admin).json().get("auto_build"),
          False)
    check("[6] admin POST auto-build unknown character",
          client.post("/characters/Nobody/figure/auto-build", json={"enabled": True}, headers=admin).status_code, 404)


# --- Ruling 7a (the stubbed world of smoke_figure_build_plan) --------------------------------

def failure_section():
    import smoke_figure_build_plan as fbp
    from app.core import figure_build as fb, garments
    fbp.install_stubs()
    print("[7] a chain that failed for its input (ruling 7a)")
    cached = {"hair_kira": {"item_id": "hair_kira", "fsig": "f1", "step": "hairdeck", "error": "no hair found"}}
    garments.cached_failure = lambda c, item_id, profile=None: cached.get(item_id)
    explicit_calls = []
    stub_run_queued = garments.run_queued

    def run_queued(c, ids, explicit=False):
        explicit_calls.append((tuple(ids), explicit))
        if explicit:
            for i in ids:
                cached.pop(i, None)
        return stub_run_queued(c, ids)
    garments.run_queued = run_queued

    fbp.W = fbp.World(hair="hairdeck", hair_done=False)
    steps = fb.plan("Kira", profile={})
    check("[7] plan", fbp.names(steps), [("hair", "hair_kira", 0)])
    check("[7] failed text", steps[0].failed, "hairdeck — no hair found")
    check("[7] label", steps[0].label, "Hair · HairDeck — failed — Retry")
    check("[7] cost", fb.cost("Kira", steps)["hub_jobs"], 0)
    check("[7] automatic start", fb.start("Kira", reason="outfit_change", automatic=True)["status"], "current")
    info = fb.figure_info("Kira")
    check("[7] GET status", info["status"], "failed")
    check("[7] hair row", (info["hair"]["state"], info["hair"]["note"]), ("failed", "hairdeck — no hair found"))
    check("[7] explicit plan", fbp.names(fb.plan("Kira", profile={}, explicit=True)),
          [("hair", "hair_kira", 0), ("fits", 0), ("assemble", 0)])
    check("[7] manual start", fb.start("Kira", reason="manual")["status"], "started")
    check("[7] manual run ended", fbp.wait_idle(fb), True)
    check("[7] run_queued explicit", explicit_calls, [(("hair_kira",), True)])
    check("[7] manual run: chain, refit, assembly", [c for c in fbp.W.calls if c != "slot"],
          ["hair_item", "chain hair_kira", "refit", "model no-prepare", "schedule"])
    check("[7] manual run: no failure", fb.state("Kira")["failed"], {})

    print("[7] automatic run with a cached failure next to other work")
    cached["hair_kira"] = {"item_id": "hair_kira", "fsig": "f1", "step": "hairdeck", "error": "no hair found"}
    explicit_calls.clear()
    fbp.W = fbp.World(base="older", hair="hairdeck", hair_done=False)
    check("[7] automatic start", fb.start("Kira", reason="body_change", automatic=True)["status"], "started")
    check("[7] automatic run ended", fbp.wait_idle(fb), True)
    ran = [c for c in fbp.W.calls if c != "slot"]
    check("[7] the plain body ran", ran[:2], ["base_images", "base_model"])
    check("[7] the hair chain did not run", [c for c in ran if c.startswith("chain") or c == "hair_item"], [])
    check("[7] run_queued not called", explicit_calls, [])
    check("[7] failed hair = the cached error", fb.state("Kira")["failed"].get("hair"),
          {"error": "hairdeck — no hair found", "item_id": "hair_kira"})


def baseline_section():
    print(f"[8] fails on {BASELINE}")

    def show(path):
        return subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:{path}"], capture_output=True,
                              text=True).stdout
    fb, inv, refs, gar = (show("app/core/figure_build.py"), show("app/routes/inventory.py"),
                          show("app/core/model_refs.py"), show("app/core/garments.py"))
    check(f"[8] files readable at {BASELINE}", all((fb, inv, refs, gar)), True)
    check(f"[8] no request/wearers at {BASELINE}", ("def request(" in fb, "def wearers(" in fb), (False, False))
    check(f"[8] no wearers route at {BASELINE}", "/wearers" in inv, False)
    check(f"[8] no Build timer at {BASELINE}", "BUILD_TIMER" in refs, False)
    body = gar[gar.index("def after_base_model("):]
    body = body[:body.index("\n# --- ")]
    check(f"[8] after_base_model enqueues chains at {BASELINE}", "enqueue_garment(" in body, True)


def main() -> int:
    part = sys.argv[1] if len(sys.argv) > 1 else ""
    if not part:
        # Each part patches module attributes for good: each runs in its own process.
        codes = [subprocess.run([sys.executable, __file__, p]).returncode for p in ("world", "failures")]
        baseline_section()
        if any(codes) or FAILS:
            print(f"\nFAIL: {', '.join(FAILS) or 'see above'}")
            return 1
        print("\nPASS")
        return 0
    with tempfile.TemporaryDirectory(prefix=f"figure-auto-{part}-") as tmp:
        root = Path(tmp)
        setup(root)
        if part == "world":
            world_section()
        else:
            failure_section()
    if FAILS:
        print(f"FAIL ({part}): {', '.join(FAILS)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
