#!/usr/bin/env python3
"""Ruling A30: a CPU refit (a run of the fit step alone) of ANOTHER item does
not wait behind a garment run of the same character — ``garments.start_garment``
starts it at once beside the character's FIFO (``_side``), holding only the
item's run lock (``garment_store.run_item_lock``), never the character's
(``garment_store.char_lock``), which a chain waiting on hub work holds for
minutes (app/core/garments.py, module docstring "Ruling A30").

WHY (live, 2026-11-13): ``refit_pool`` had 8 CPU slots and two other
characters' hair refits ran in parallel, but Ylva's hair refit showed
"Wartet hinter Laced Linen Blouse · Position 1" for minutes: her blouse run
waited on hub image jobs, and the per-character FIFO ran one item's chain at
a time.

Usage:
    ./.venv/bin/python scripts/smoke_refit_bypass_queue.py

Throwaway storage + instance (``paths.init`` before any world module); no
world, no hub, no GPU, no server, no network (every socket connect is
counted and refused — the count must be 0). Stubs: ``garments.check_run``,
``garments._item_order`` (blouse/skirt/coat = clothing with the edit chain,
hair = hair with HairDeck), ``garments._worn_state``, ``garments._run_locked``
(the chain body: marks its step running, waits on a per-item Event = the fake
hub job, returns ``{ok, fsig "", ran [step]}``), ``base_body.
after_mesh_item_ready`` (a recorder) and ``refit_pool.track/activate/finish/
discard`` (recorders). REAL: ``start_garment``, the FIFO worker, the side
worker, ``run_garment`` with its locks, ``queue_state``, ``cancel_garment``,
``busy`` / ``hold_all``, the run status (``garment_store.start/end/status``),
the base-step registries (``base_body.reserve_views``, ``model3d._generating``)
and — for [5] — ``queueText`` of frontend/src/tabs/characters/garmentStyle.ts
(transpiled with esbuild, run in node).

The stubbed chain step of a run: ``wanted[0]`` when steps were named, else
"worn" (clothing) / "hairdeck" (hair).

Expected values, derived by hand from Ruling A30 and ``start_garment``:

[1] Blouse (Demo) runs its default chain and blocks in the fake hub wait.
    - start blouse -> {started True, queued False, position 0, behind None}.
    - start hair, steps "fit" -> {started True, queued False, position 0,
      behind None, beside True}: the FIFO runs ANOTHER item, hair has no run.
    - Inside the hair run (entry): its status is "queued" (the click's mark);
      queue_state(Demo, hair) = {queue_running "blouse", queue [], beside
      ["hair"], queue_position None, queue_beside True}; the character lock
      IS held (by the blouse run — so the refit really did not take it), the
      hair item lock is held (by the refit), the blouse item lock is held (by
      the blouse run); busy(Demo) True; hold_all(Demo) False (the sweep never
      runs beside a refit).
    - The hair run ENDS while the blouse gate is still closed and the blouse
      status is still "worn": runs so far = start blouse, start hair, end hair.
    - Afterwards: hair status running_step None, failed None; queue_state
      (Demo) beside []; the track: track("Demo", "Refit · Demo (1 fit)") once,
      activate once, finish once with error "", discard never.
    - Hair is not a grafted kind (garment_set.GRAFTED_PIECE_KINDS = clothing,
      footwear): after_mesh_item_ready 0 calls. A clothing refit beside (skirt,
      steps "fit") -> beside True, after_mesh_item_ready [("Demo", "skirt")]
      once (what it requests is today's code, unchanged).
    - Peak concurrency 2 (blouse + one refit at a time here).
    - Release the blouse: idle, blouse status None.
[2] The SAME item still waits.
    a. Blouse default blocked; start blouse "fit" -> {started False, queued
       True, position 1, behind "blouse"}; queue_state(Demo, blouse)
       queue_position 1, queue_beside False.
    b. start coat (default) -> position 2; start coat "fit" -> the explicit run
       takes the waiting default's place: {started False, queued True,
       position 2, behind "blouse"}; queue ["blouse", "coat"]; coat status
       "queued"; nothing ran beside (beside []).
       Released: runs blouse(None), blouse("fit"), coat("fit") in this order;
       peak concurrency 1.
    c. A refit beside and a FIFO run of the SAME item: blouse default blocked,
       hair "fit" beside (hair gate closed, it is inside its run),
       enqueue_garment(Demo, hair) -> queue ["hair"]. Releasing the blouse
       makes the hair job the FIFO's run: it holds the character lock and
       waits for the hair item lock — 0.5 s later hair has still started ONCE
       (and cancel_garment(Demo, hair) -> RunStarted: nothing waits, a run is
       in flight). Releasing hair: the side run ends, THEN the FIFO hair run
       starts (step "hairdeck"); hair starts in all 2, the side end before the
       second start.
[3] A base step in flight still holds the refit as before (it queues behind
    the FIFO's run, exactly today's path):
    - blouse default blocked; base_body.reserve_views(Demo, ("front",),
      step=SKIN_STEP) -> start hair "fit" -> {started False, queued True,
      position 1, behind "blouse"}; status "queued"; queue_position 1,
      queue_beside False; the track is NOT activated (still pending).
    - release_views: hair still waits (0.5 s later 0 hair starts — it is in
      the FIFO, not beside).
    - a NAMED generation guard (model3d._generating.add(Demo, "Re-rig")) ->
      start skirt "fit" -> position 2 behind "blouse"; an UNNAMED one (a
      Build's model step, generation_slot) -> start coat "fit" -> position 3.
    - Released: runs blouse(None), hair("fit"), skirt("fit"), coat("fit");
      peak concurrency 1.
[4] Two characters are unaffected:
    - Demo's blouse blocked; a base step of OTHER in flight
      (reserve_views(Other, front)) does not hold Demo's refit: start Demo hair
      "fit" -> beside True.
    - Other's FIFO is idle: start Other hair "fit" -> {started True, queued
      False, position 0, behind None} (the FIFO path: no "beside" key) and it
      runs and ends while Demo's blouse still blocks.
    - queue_state(Other) while Demo's hair refit is held: {queue_running None,
      queue [], beside []}; queue_state(Demo)["beside"] = ["hair"].
    - Released: idle; no character has a run left (_active, _side empty).
[5] The position text (``queueText`` with the payloads [1]-[3] produced; item
    names Laced Linen Blouse / Hair / Skirt / Coat; t = identity):
    - [1] the hair refit at its entry (queued, queue_beside True,
      queue_running "blouse") -> "Starting…" — no "Queued behind".
    - [2b] coat waiting -> "Queued behind Laced Linen Blouse · position 2".
    - [3] hair held by the base step -> "Queued behind Laced Linen Blouse ·
      position 1".
    - [3] skirt -> "… · position 2", coat -> "… · position 3".
[6] No network: 0 socket connects.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _no_network():
    def refuse(self, *args, **kwargs):
        CONNECTS.append(args)
        raise OSError("network disabled in this smoke")
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.getaddrinfo = lambda *a, **k: refuse(None, *a)


def _esbuild() -> str:
    """The esbuild binary of this checkout, or of the main tree when this is a worktree without node_modules."""
    candidates = [ROOT / "node_modules" / ".bin" / "esbuild", ROOT / "frontend" / "node_modules" / ".bin" / "esbuild"]
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True,
                                text=True, check=True).stdout.strip()
        main = (ROOT / common).resolve().parent if not Path(common).is_absolute() else Path(common).parent
        candidates += [main / "node_modules" / ".bin" / "esbuild", main / "frontend" / "node_modules" / ".bin" / "esbuild"]
    except (OSError, subprocess.CalledProcessError):
        pass
    for c in candidates:
        if c.is_file():
            return str(c)
    return shutil.which("esbuild") or ""


def queue_texts(cases, tmp: Path):
    """``queueText`` of garmentStyle.ts for every ``(garment, names)`` case (None when it cannot run)."""
    esbuild = _esbuild()
    if not esbuild or not shutil.which("node"):
        return None
    src = ROOT / "frontend" / "src" / "tabs" / "characters" / "garmentStyle.ts"
    out = tmp / "garmentStyle.mjs"
    subprocess.run([esbuild, str(src), "--loader:.ts=ts", "--format=esm", f"--outfile={out}"], check=True,
                   capture_output=True)
    (tmp / "cases.json").write_text(json.dumps(cases))
    runner = tmp / "run.mjs"
    runner.write_text(
        "import { readFileSync } from 'node:fs'\n"
        "import { queueText } from './garmentStyle.mjs'\n"
        "const cases = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url)))\n"
        "const t = (s) => s\n"
        "const out = cases.map(([garment, names]) => queueText(garment, { pending: null, target: null, queue: null,\n"
        "  refused: null, others: null, names, cancel: { pending: false, done: false, error: null } }, {}, t))\n"
        "process.stdout.write(JSON.stringify(out))\n")
    res = subprocess.run(["node", str(runner)], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def main() -> int:
    _no_network()
    with tempfile.TemporaryDirectory(prefix="refit-bypass-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import base_body, garments, model3d, refit_pool
        from app.core import garment_store as gs

        kinds = {"blouse": "clothing", "skirt": "clothing", "coat": "clothing", "hair": "hair"}
        orders = {"clothing": ("worn", "ghost", "cutout", "mesh", "fit"), "hair": ("hairdeck", "fit")}
        names = {"blouse": "Laced Linen Blouse", "hair": "Hair", "skirt": "Skirt", "coat": "Coat"}

        events = []                      # ("start" | "end", character, item, steps)
        ev_lock = threading.Lock()
        live = {"now": 0, "max": 0}
        gates = {}                       # (character, item) -> Event (closed = the fake hub job runs)
        entered = {}                     # (character, item) -> Event set at the run's entry
        snaps = {}                       # (character, item) -> what the run saw at its entry (first run only)

        def gate(character, item):
            gates[(character, item)] = threading.Event()
            entered[(character, item)] = threading.Event()
            return gates[(character, item)]

        def fake_item_order(character_name, item_id, profile=None):
            kind = kinds[item_id]
            return {"id": item_id, "name": names[item_id]}, kind, orders[kind]

        def fake_run_locked(character_name, item, kind, wanted, view, force, state=None, *, only=False):
            item_id = item["id"]
            key = (character_name, item_id)
            if key not in snaps:
                snaps[key] = {
                    "status": gs.status(character_name, item_id)["running_step"],
                    "queue": garments.queue_state(character_name, item_id),
                    "char_lock": gs.char_lock(character_name).locked(),
                    "item_lock": gs.run_item_lock(character_name, item_id).locked(),
                    "blouse_lock": gs.run_item_lock(character_name, "blouse").locked(),
                    "busy": garments.busy(character_name),
                    "hold_all": garments.hold_all(character_name),
                }
                if snaps[key]["hold_all"]:
                    garments.release_all(character_name)
            step = wanted[0] if wanted else orders[kind][0]
            with ev_lock:
                events.append(("start", character_name, item_id, tuple(wanted or ())))
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            gs.start(character_name, item_id, step)
            if key in entered:
                entered[key].set()
            try:
                if key in gates:
                    gates[key].wait(30)
            finally:
                gs.end(character_name, item_id, step)
                with ev_lock:
                    live["now"] -= 1
                    events.append(("end", character_name, item_id, tuple(wanted or ())))
            return {"ok": True, "fsig": "", "ran": [step]}

        ready = []
        tracks = []

        def fake_track(character_name, label, *, pending=True):
            tracks.append(("track", character_name, label, pending))
            return f"t{len([t for t in tracks if t[0] == 'track'])}"

        garments.check_run = lambda character_name, item_id, steps=None, view=None, state=None: None
        garments._item_order = fake_item_order
        garments._worn_state = lambda character_name, item_id: "closed"
        garments._run_locked = fake_run_locked
        base_body.after_mesh_item_ready = lambda character_name, item_id: ready.append((character_name, item_id))
        refit_pool.track = fake_track
        refit_pool.activate = lambda task_id, label=None: tracks.append(("activate", task_id))
        refit_pool.finish = lambda task_id, error="": tracks.append(("finish", task_id, error))
        refit_pool.discard = lambda task_id: tracks.append(("discard", task_id))

        def wait_for(pred, timeout=10.0):
            done = threading.Event()
            for _ in range(int(timeout / 0.02)):
                if pred():
                    return True
                done.wait(0.02)
            return False

        def starts(character, item):
            with ev_lock:
                return [e for e in events if e[0] == "start" and e[1] == character and e[2] == item]

        def reset():
            check("idle", garments.wait_idle(30), True)
            with ev_lock:
                events.clear()
                live["now"] = live["max"] = 0
            gates.clear()
            entered.clear()
            snaps.clear()
            ready.clear()
            tracks.clear()

        text_cases = []

        def text_case(label, character, item, want):
            info = {"running_step": gs.status(character, item)["running_step"]}
            q = garments.queue_state(character, item)
            info.update(queue_position=q["queue_position"], queue_running=q["queue_running"],
                        queue_beside=q["queue_beside"])
            text_cases.append((label, info, want))

        # --- [1] -----------------------------------------------------------------------------------------
        print("[1] a hair refit finishes while the blouse run waits on the hub")
        blouse = gate("Demo", "blouse")
        check("start blouse", garments.start_garment("Demo", "blouse"),
              {"started": True, "queued": False, "position": 0, "behind": None})
        check("blouse in its hub wait", entered[("Demo", "blouse")].wait(10), True)
        hair_done = threading.Event()
        check("start hair fit", garments.start_garment("Demo", "hair", steps="fit"),
              {"started": True, "queued": False, "position": 0, "behind": None, "beside": True})
        check("hair ended", wait_for(lambda: any(e[0] == "end" and e[2] == "hair" for e in events)), True)
        check("blouse still blocked", (blouse.is_set(), gs.status("Demo", "blouse")["running_step"]),
              (False, "worn"))
        with ev_lock:
            check("order", [(e[0], e[2]) for e in events],
                  [("start", "blouse"), ("start", "hair"), ("end", "hair")])
        snap = snaps[("Demo", "hair")]
        check("hair status at entry", snap["status"], "queued")
        check("hair queue at entry", snap["queue"],
              {"queue_running": "blouse", "queue": [], "beside": ["hair"], "queue_position": None,
               "queue_beside": True})
        text_cases.append(("[1] hair refit beside", {"running_step": snap["status"],
                                                     "queue_position": snap["queue"]["queue_position"],
                                                     "queue_running": snap["queue"]["queue_running"],
                                                     "queue_beside": snap["queue"]["queue_beside"]}, "Starting…"))
        check("locks at entry (char held by blouse, hair item, blouse item)",
              (snap["char_lock"], snap["item_lock"], snap["blouse_lock"]), (True, True, True))
        check("busy / hold_all at entry", (snap["busy"], snap["hold_all"]), (True, False))
        check("side registry empty again", wait_for(lambda: garments.queue_state("Demo")["beside"] == []), True)
        st = gs.status("Demo", "hair")
        check("hair status after", (st["running_step"], st["failed"]), (None, None))
        check("track", tracks, [("track", "Demo", "Refit · Demo (1 fit)", True), ("activate", "t1"),
                                ("finish", "t1", "")])
        check("hair: no piece_ready", ready, [])
        check("start skirt fit (clothing)", garments.start_garment("Demo", "skirt", steps="fit"),
              {"started": True, "queued": False, "position": 0, "behind": None, "beside": True})
        check("skirt ended", wait_for(lambda: any(e[0] == "end" and e[2] == "skirt" for e in events)), True)
        check("skirt: piece_ready asked once", wait_for(lambda: ready == [("Demo", "skirt")]), True)
        check("blouse still blocked (2)", blouse.is_set(), False)
        check("peak concurrency", live["max"], 2)
        blouse.set()
        check("idle", garments.wait_idle(30), True)
        check("blouse status after", gs.status("Demo", "blouse")["running_step"], None)
        reset()

        # --- [2] -----------------------------------------------------------------------------------------
        print("[2a] a refit of the SAME item waits")
        blouse = gate("Demo", "blouse")
        garments.start_garment("Demo", "blouse")
        check("blouse in its hub wait", entered[("Demo", "blouse")].wait(10), True)
        check("start blouse fit", garments.start_garment("Demo", "blouse", steps="fit"),
              {"started": False, "queued": True, "position": 1, "behind": "blouse"})
        q = garments.queue_state("Demo", "blouse")
        check("blouse queue", (q["queue_position"], q["queue_beside"]), (1, False))
        print("[2b] an item with a waiting run: the refit takes its place, no bypass")
        check("start coat", garments.start_garment("Demo", "coat"),
              {"started": False, "queued": True, "position": 2, "behind": "blouse"})
        check("start coat fit", garments.start_garment("Demo", "coat", steps="fit"),
              {"started": False, "queued": True, "position": 2, "behind": "blouse"})
        check("queue", garments.queue_state("Demo"),
              {"queue_running": "blouse", "queue": ["blouse", "coat"], "beside": []})
        check("coat status", gs.status("Demo", "coat")["running_step"], "queued")
        text_case("[2b] coat waiting", "Demo", "coat", "Queued behind Laced Linen Blouse · position 2")
        blouse.set()
        check("idle", garments.wait_idle(30), True)
        with ev_lock:
            check("runs", [(e[2], e[3]) for e in events if e[0] == "start"],
                  [("blouse", ()), ("blouse", ("fit",)), ("coat", ("fit",))])
        check("peak concurrency", live["max"], 1)
        reset()

        print("[2c] a refit beside and a FIFO run of the same item: the item lock serializes them")
        blouse = gate("Demo", "blouse")
        hair = gate("Demo", "hair")
        garments.start_garment("Demo", "blouse")
        check("blouse in its hub wait", entered[("Demo", "blouse")].wait(10), True)
        check("start hair fit", garments.start_garment("Demo", "hair", steps="fit").get("beside"), True)
        check("hair inside its run", entered[("Demo", "hair")].wait(10), True)
        garments.enqueue_garment("Demo", "hair")
        check("queue [hair]", garments.queue_state("Demo")["queue"], ["hair"])
        blouse.set()
        check("hair is the FIFO's run", wait_for(lambda: garments.queue_state("Demo")["queue_running"] == "hair"),
              True)
        threading.Event().wait(0.5)
        check("FIFO hair waits for the item lock (1 start)", len(starts("Demo", "hair")), 1)
        try:
            garments.cancel_garment("Demo", "hair")
            check("cancel refused", "no error", "RunStarted")
        except garments.RunStarted:
            check("cancel refused", "RunStarted", "RunStarted")
        hair.set()
        check("idle", garments.wait_idle(30), True)
        with ev_lock:
            hair_events = [(e[0], e[3]) for e in events if e[2] == "hair"]
        check("hair order", hair_events, [("start", ("fit",)), ("end", ("fit",)), ("start", ()), ("end", ())])
        reset()

        # --- [3] -----------------------------------------------------------------------------------------
        print("[3] a base step in flight holds the refit as before")
        blouse = gate("Demo", "blouse")
        garments.start_garment("Demo", "blouse")
        check("blouse in its hub wait", entered[("Demo", "blouse")].wait(10), True)
        base_body.reserve_views("Demo", ("front",), step=base_body.SKIN_STEP)
        check("start hair fit", garments.start_garment("Demo", "hair", steps="fit"),
              {"started": False, "queued": True, "position": 1, "behind": "blouse"})
        q = garments.queue_state("Demo", "hair")
        check("hair queue", (gs.status("Demo", "hair")["running_step"], q["queue_position"], q["queue_beside"]),
              ("queued", 1, False))
        text_case("[3] hair held by the skin step", "Demo", "hair", "Queued behind Laced Linen Blouse · position 1")
        check("track pending (not activated)", [t[0] for t in tracks], ["track"])
        base_body.release_views("Demo", ("front",))
        threading.Event().wait(0.5)
        check("hair still waits in the FIFO", len(starts("Demo", "hair")), 0)
        model3d._generating.add("Demo", "Re-rig")
        try:
            check("start skirt fit (named guard)", garments.start_garment("Demo", "skirt", steps="fit"),
                  {"started": False, "queued": True, "position": 2, "behind": "blouse"})
        finally:
            model3d._generating.discard("Demo")
        text_case("[3] skirt held by Re-rig", "Demo", "skirt", "Queued behind Laced Linen Blouse · position 2")
        model3d._generating.add("Demo")
        try:
            check("start coat fit (unnamed guard)", garments.start_garment("Demo", "coat", steps="fit"),
                  {"started": False, "queued": True, "position": 3, "behind": "blouse"})
        finally:
            model3d._generating.discard("Demo")
        text_case("[3] coat held by a Build slot", "Demo", "coat", "Queued behind Laced Linen Blouse · position 3")
        blouse.set()
        check("idle", garments.wait_idle(30), True)
        with ev_lock:
            check("runs", [(e[2], e[3]) for e in events if e[0] == "start"],
                  [("blouse", ()), ("hair", ("fit",)), ("skirt", ("fit",)), ("coat", ("fit",))])
        check("peak concurrency", live["max"], 1)
        reset()

        # --- [4] -----------------------------------------------------------------------------------------
        print("[4] two characters are unaffected")
        blouse = gate("Demo", "blouse")
        hair = gate("Demo", "hair")
        garments.start_garment("Demo", "blouse")
        check("blouse in its hub wait", entered[("Demo", "blouse")].wait(10), True)
        base_body.reserve_views("Other", ("front",), step=base_body.SKIN_STEP)
        try:
            check("Demo hair beside (Other's base step)",
                  garments.start_garment("Demo", "hair", steps="fit").get("beside"), True)
        finally:
            base_body.release_views("Other", ("front",))
        check("Demo hair inside its run", entered[("Demo", "hair")].wait(10), True)
        check("start Other hair fit", garments.start_garment("Other", "hair", steps="fit"),
              {"started": True, "queued": False, "position": 0, "behind": None})
        check("Other hair ended", wait_for(lambda: any(e[0] == "end" and e[1] == "Other" for e in events)), True)
        check("Demo blouse still blocked", blouse.is_set(), False)
        check("queue Other", garments.queue_state("Other"), {"queue_running": None, "queue": [], "beside": []})
        check("Demo beside", garments.queue_state("Demo")["beside"], ["hair"])
        hair.set()
        blouse.set()
        check("idle", garments.wait_idle(30), True)
        with garments._lock:
            check("no run left", (set(garments._active), dict(garments._side), dict(garments._current)),
                  (set(), {}, {}))
        reset()

        # --- [5] -----------------------------------------------------------------------------------------
        print("[5] the position text (queueText, garmentStyle.ts)")
        texts = queue_texts([[info, names] for _label, info, _want in text_cases], root)
        if texts is None:
            check("esbuild + node found", False, True)
        else:
            for (label, _info, want), got in zip(text_cases, texts):
                check(label, got, want)

        print("[6] no network")
        check("socket connects", len(CONNECTS), 0)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
