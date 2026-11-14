#!/usr/bin/env python3
"""The Base body tab's status follows only the base body's own steps, never an outfit build (Ruling A55).

User report: while a character's outfit model was being built (a Build at its body-shape step), the Base body tab
showed the base body as "Building now" — the head took `figure.build.running`, true for EVERY step of a Build.
Now the server splits the character's 3D work (`figure_build.base_activity`, `plain_body.activity`): `base` names
base-body work in flight, `other` is one neutral line while only outfit work runs; the head reads `activity.base`.

Usage:
    ./.venv/bin/python scripts/smoke_base_status_isolated.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no
world, no hub, no server, no thread that renders. The running states are set in the registries the real runs
keep (a Build's ``_active`` / ``_current`` step, the generation guard ``model3d._generating``, the outfit mark
``base_body._outfit_running``, the base model mark ``base_body._model_running``, Run all's ``_run_all_active``).
The tab's head is computed in node from ``frontend/src/tabs/characters/baseBodyModel.ts`` (esbuild bundle) with
FieldBaseBody's wiring: the four view rows (``baseViewRow``), the model row (``baseModelRow``), then
``baseHead(run_all, lights, !!activity.base)``.

Fixture: character "demo", base signature "base0a1b2c3d", four stored current views (their rows green), a stored
rigged base model ``model3d/base0a1b2c3d.glb`` (sidecar rig "mixamo" → ``base_model_info`` status "ready"), Run all
with nothing to do (kind "", hub_jobs 0).

Expected, by hand from the brief and the code:

[1] Idle → activity {base "", other ""}; model status "ready"; every light green → head green "Up to date".
[2] An outfit-body build runs — a Build at its ``shape`` step, the guard held UNNAMED (the Build's
    ``generation_slot``), the outfit mark of stage "body" — → activity {base "", other OUTFIT_BUILDING = "An outfit
    model is building — the base body is not affected"}; model status still "ready"; head green "Up to date"
    (the base status stays current).
[3] The same outfit model's run outside a Build (only the outfit mark, stage "model") → other OUTFIT_BUILDING,
    base ""; an unnamed guard alone (an outfit rebuild) → the same.
[4] A base-mesh run — ``base_body._model_running[demo] = base0a1b2c3d`` and the guard named "Base body model (mesh +
    rig)", as ``start_base_model`` holds them — → activity.base "Base body model (mesh + rig)" (``base_steps_running``),
    other ""; model status "running" → its row blue → head blue "Building now".
[5] A Build at a base step: ``plain_body`` (label "Plain body: views 4 + mesh + rig") → activity.base is that label,
    head blue "Building now"; ``base_repair`` (label "Base mesh repair (local)"), with NO row running (the repair runs
    inside the Build, no registry of its own) → activity.base "Base mesh repair (local)", head blue — the head reads
    the activity, not only the rows; ``tip_smoothing`` → base too.
[6] A Build that has not reached its first step (step None) and nothing else → activity {"", ""} → head green.
[7] Base Run all active (``_run_all_active``) while a Build would be at an outfit step → base "Base body Run all"
    (``base_step_in_flight``), other "" (base work wins; the outfit line is not shown beside it).
[8] The reverse check on the Figure tab (``figureModel.bodyRows(body, [], [], t, buildStep)``, every body row
    ready): step "shape" → the body-shape row blue "Building now", plain and texture green "Current"; "interim" →
    shape row blue; "base_repair" → plain row blue; "texture" → texture row blue; "pieces" (a worn piece's own row)
    → no body row blue; null → none blue.
[9] Wiring by source: FieldBaseBody calls ``baseHead(runAll, lights, !!activity?.base, t)``, hands
    ``activity={info.activity}`` and shows ``t(activity.other)``; ``BUILD_RUNNING_NOTE`` only with
    ``info.activity?.base``; FieldFigure hands ``data.build.step?.name`` to ``bodyRows``; routes/figure.py sets
    ``info["activity"] = figure_build.base_activity(…)``; de.json has the OUTFIT_BUILDING key.
[10] FAILS ON THE OLD CODE — main at 9813f8ab8766c7f18a360712e05bc0400854c500 (the commit this fix starts from):
    its FieldBaseBody passes ``buildRunning={!!figure?.build.running}`` and its RunAllHeader calls
    ``baseHead(runAll, lights, buildRunning, t)``; its routes/figure.py sets no ``activity``. Its ``baseHead`` (bundled
    from that commit) on state [2] — all lights green, Run all current, ``build.running`` true — gives blue "Building
    now": the report. Skipped (not failed) when that commit is not in the repository (a shallow clone).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD = "9813f8ab8766c7f18a360712e05bc0400854c500"

_tmp = Path(tempfile.mkdtemp(prefix="smoke_base_status_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))

import app.models.character as character  # noqa: E402
from app.core import base_body, figure_build, model3d, model_refs  # noqa: E402

FAILS = []
NAME, BSIG = "demo", "base0a1b2c3d"
OUTFIT_BUILDING = "An outfit model is building — the base body is not affected"
BASE_MODEL_HOLDER = "Base body model (mesh + rig)"


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


# --- fixture -----------------------------------------------------------------------------------------------
character.get_character_profile = lambda name, *a, **k: {"name": NAME, "template": "human-roleplay"}
base_body.base_signature = lambda name, *a, **k: BSIG
model_refs.is_humanoid = lambda *a, **k: True
# The served URL would build a delivery copy in Blender — not what is checked here.
model3d.signature_model_url = lambda name, sig: f"/m/{sig}.glb"
model_dir = _tmp / "characters" / NAME / "model3d"
model_dir.mkdir(parents=True)
(model_dir / f"{BSIG}.glb").write_bytes(b"glTF")
(model_dir / f"{BSIG}.json").write_text(json.dumps({"signature": BSIG, "rig": "mixamo", "base": True,
                                                     "created_at": "2026-11-14T19:01:50+00:00"}))
CURRENT = {"state": "current"}


def plain_body() -> dict:
    """The fields the tab's head reads, from the real registries; the stored views are the fixture's."""
    return {"status": base_body.base_status(NAME),
            "images": {v: f"/img/{v}.png" for v in base_body.BASE_VIEWS},
            "image_meta": {v: {"freshness": CURRENT} for v in base_body.BASE_VIEWS},
            "model": base_body.base_model_info(NAME, BSIG),
            "run_all": {"kind": "", "steps": [], "hub_jobs": 0, "note": "",
                        "running": NAME in figure_build._run_all_active, "last": None},
            "activity": figure_build.base_activity(NAME)}


def build_at(step_name, label):
    with figure_build._lock:
        figure_build._active.add(NAME)
        figure_build._current[NAME] = {"reason": "body_change", "steps": [], "step": None if step_name is None else {
            "name": step_name, "label": label, "jobs": 0, "item_id": "", "failed": "", "manual": "", "index": 1,
            "count": 3}}


def reset():
    with figure_build._lock:
        figure_build._active.discard(NAME)
        figure_build._current.pop(NAME, None)
        figure_build._run_all_active.discard(NAME)
    model3d._generating.discard(NAME)
    with base_body._status_lock:
        base_body._model_running.pop(NAME, None)
        for key in [k for k in base_body._outfit_running if k[0] == NAME]:
            base_body._outfit_running.pop(key, None)


states = {}
reset()
states["idle"] = plain_body()

build_at("shape", "Body shape · in the body: Leggings")
model3d._generating.add(NAME)
with base_body._status_lock:
    base_body._outfit_running[(NAME, "body")] = "outfit01"
states["outfit_build"] = plain_body()
reset()

with base_body._status_lock:
    base_body._outfit_running[(NAME, "model")] = "outfit01"
states["outfit_model_alone"] = plain_body()
reset()
model3d._generating.add(NAME)
states["unnamed_guard"] = plain_body()
reset()

with base_body._status_lock:
    base_body._model_running[NAME] = BSIG
model3d._generating.add(NAME, BASE_MODEL_HOLDER)
states["base_mesh"] = plain_body()
reset()

build_at("plain_body", "Plain body: views 4 + mesh + rig")
states["build_plain_body"] = plain_body()
reset()
build_at("base_repair", "Base mesh repair (local)")
states["build_base_repair"] = plain_body()
reset()
build_at("tip_smoothing", "Tip smoothing (local)")
states["build_tip_smoothing"] = plain_body()
reset()
build_at(None, "")
states["build_starting"] = plain_body()
reset()
build_at("shape", "Body shape")
with figure_build._lock:
    figure_build._run_all_active.add(NAME)
states["run_all_beside"] = plain_body()
reset()

# --- server half --------------------------------------------------------------------------------------------
act = {k: v["activity"] for k, v in states.items()}
check("[0] the module's line is the brief's", figure_build.OUTFIT_BUILDING, OUTFIT_BUILDING)
check("[1] idle: no activity", act["idle"], {"base": "", "other": ""})
check("[1] idle: base model ready", states["idle"]["model"]["status"], "ready")
check("[2] outfit-body build: the neutral line, no base work", act["outfit_build"],
      {"base": "", "other": OUTFIT_BUILDING})
check("[2] outfit-body build: base model still ready", states["outfit_build"]["model"]["status"], "ready")
check("[2] outfit-body build: no base view running",
      any(s["running"] for s in states["outfit_build"]["status"].values()), False)
check("[3] the outfit model's own run", act["outfit_model_alone"], {"base": "", "other": OUTFIT_BUILDING})
check("[3] an unnamed guard alone", act["unnamed_guard"], {"base": "", "other": OUTFIT_BUILDING})
check("[4] base mesh run: base work named", act["base_mesh"], {"base": BASE_MODEL_HOLDER, "other": ""})
check("[4] base mesh run: model status running", states["base_mesh"]["model"]["status"], "running")
check("[5] Build at plain_body", act["build_plain_body"], {"base": "Plain body: views 4 + mesh + rig", "other": ""})
check("[5] Build at base_repair", act["build_base_repair"], {"base": "Base mesh repair (local)", "other": ""})
check("[5] Build at base_repair: no row of its own runs",
      [states["build_base_repair"]["model"]["status"],
       any(s["running"] for s in states["build_base_repair"]["status"].values())], ["ready", False])
check("[5] Build at tip_smoothing", act["build_tip_smoothing"], {"base": "Tip smoothing (local)", "other": ""})
check("[6] Build before its first step", act["build_starting"], {"base": "", "other": ""})
check("[7] Run all beside an outfit step", act["run_all_beside"], {"base": "Base body Run all", "other": ""})

# --- client half (node) -------------------------------------------------------------------------------------
JS = r"""
import * as m from %(base)s
import * as f from %(figure)s
const states = JSON.parse(process.argv[2])
const VIEWS = ['front', 'back', 'left', 'right']
const head = (info, third) => {
  const views = VIEWS.map((v) => m.baseViewRow({ running: !!info.status?.[v]?.running, failed: !!info.status?.[v]?.failed,
    error: info.status?.[v]?.error, warning: info.status?.[v]?.warning, stored: !!info.images?.[v],
    freshness: info.image_meta?.[v]?.freshness }))
  const lights = [...views.map((r) => r.light), m.baseModelRow(info.model).light]
  const h = m.baseHead(info.run_all, lights, third(info))
  return [h.light, h.words]
}
const out = { heads: {}, body: {} }
for (const [k, info] of Object.entries(states)) out.heads[k] = head(info, (i) => !!i.activity?.base)
if (f.bodyRows) {
  const body = { plain: { key: 'b', state: 'ready', note: '' }, shape: { key: 's', state: 'ready' },
    texture: { key: 't', state: 'ready' } }
  for (const step of ['shape', 'interim', 'base_repair', 'texture', 'pieces', null]) {
    out.body[String(step)] = f.bodyRows(body, [], [], undefined, step).map((r) => [r.key, r.light, r.state])
  }
}
// The old wiring: the third argument was `figure.build.running` — true in the outfit-build state.
out.oldHead = head(states.outfit_build, () => true)
console.log(JSON.stringify(out))
"""


def run_node(base_ts: Path, figure_ts: Path):
    esbuild = next((ROOT / p for p in ("node_modules/.bin/esbuild", "frontend/node_modules/.bin/esbuild",
                                       "client3d/node_modules/.bin/esbuild") if (ROOT / p).exists()), None)
    if esbuild is None or shutil.which("node") is None:
        check(False, "esbuild and node available")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        entry, bundle = Path(tmp) / "head.mjs", Path(tmp) / "head.bundle.mjs"
        entry.write_text(JS % {"base": json.dumps(str(base_ts)), "figure": json.dumps(str(figure_ts))})
        built = subprocess.run([str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm",
                                "--log-level=error", f"--outfile={bundle}"], cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stderr)
            check(False, "bundle")
            return None
        run = subprocess.run(["node", str(bundle), json.dumps(states)], cwd=ROOT, capture_output=True, text=True)
    try:
        return json.loads((run.stdout.strip().splitlines() or [""])[-1])
    except ValueError:
        print(run.stdout, run.stderr)
        check(False, "node run")
        return None


TABS = ROOT / "frontend/src/tabs/characters"
got = run_node(TABS / "baseBodyModel.ts", TABS / "figureModel.ts")
if got:
    h = got["heads"]
    UP, BUSY = ["green", "Up to date"], ["blue", "Building now"]
    check("[1] head idle", h["idle"], UP)
    check("[2] head while the outfit-body build runs — the base status stays current", h["outfit_build"], UP)
    check("[3] head while the outfit model runs alone / an unnamed guard", [h["outfit_model_alone"], h["unnamed_guard"]],
          [UP, UP])
    check("[4] head while the base mesh runs", h["base_mesh"], BUSY)
    check("[5] head while a Build is at a base step",
          [h["build_plain_body"], h["build_base_repair"], h["build_tip_smoothing"]], [BUSY, BUSY, BUSY])
    check("[6] head while a Build has not reached a step", h["build_starting"], UP)
    check("[7] head with Run all beside an outfit step", h["run_all_beside"], BUSY)
    b = got["body"]
    G, Y = "green", "Current"
    check("[8] Figure body rows, shape step", b["shape"],
          [["plain", G, Y], ["shape", "blue", "Building now"], ["texture", G, Y]])
    check("[8] interim step → shape row", b["interim"][1], ["shape", "blue", "Building now"])
    check("[8] base_repair step → plain row", b["base_repair"][0], ["plain", "blue", "Building now"])
    check("[8] texture step → texture row", b["texture"][2], ["texture", "blue", "Building now"])
    check("[8] a piece's step / none → no body row blue", [b["pieces"], b["null"]],
          [[["plain", G, Y], ["shape", G, Y], ["texture", G, Y]]] * 2)

# --- wiring -------------------------------------------------------------------------------------------------
src = lambda rel: (ROOT / rel).read_text(encoding="utf-8")  # noqa: E731
base_tab = src("frontend/src/tabs/characters/FieldBaseBody.tsx")
check("[9] FieldBaseBody: head from activity.base",
      [("baseHead(runAll, lights, !!activity?.base, t)" in base_tab), ("activity={info.activity}" in base_tab),
       ("t(activity.other)" in base_tab), ("figure?.build.running && info.activity?.base ?" in base_tab),
       ("baseHead(runAll, lights, buildRunning, t)" in base_tab)], [True, True, True, True, False])
check("[9] FieldFigure hands the Build's step to bodyRows",
      "data.build.running ? data.build.step?.name ?? null : null)" in src("frontend/src/tabs/characters/FieldFigure.tsx"))
check("[9] routes/figure.py sets activity",
      'info["activity"] = figure_build.base_activity(character_name)' in src("app/routes/figure.py"))
de = json.loads(src("shared/languages/de.json"))
check("[9] de.json key of the line", OUTFIT_BUILDING in (de.get("translations") or de))

# --- [10] fails on the old code -----------------------------------------------------------------------------
present = subprocess.run(["git", "cat-file", "-e", f"{OLD}^{{commit}}"], cwd=ROOT, capture_output=True).returncode == 0
if not present:
    print(f"SKIP  [10] {OLD[:9]} not in this repository")
else:
    def old(rel):
        return subprocess.run(["git", "show", f"{OLD}:{rel}"], cwd=ROOT, capture_output=True, text=True).stdout
    old_tab = old("frontend/src/tabs/characters/FieldBaseBody.tsx")
    check("[10] old FieldBaseBody: head from build.running",
          [("buildRunning={!!figure?.build.running}" in old_tab), ("baseHead(runAll, lights, buildRunning, t)" in old_tab)],
          [True, True])
    check("[10] old routes/figure.py: no activity", 'info["activity"]' in old("app/routes/figure.py"), False)
    with tempfile.TemporaryDirectory() as tmp:
        old_base, old_fig = Path(tmp) / "baseBodyModel.ts", Path(tmp) / "figureModel.ts"
        old_base.write_text(old("frontend/src/tabs/characters/baseBodyModel.ts"))
        old_fig.write_text(old("frontend/src/tabs/characters/figureModel.ts"))
        old_got = run_node(old_base, old_fig)
    if old_got:
        check("[10] old head on the outfit-body build: blue \"Building now\" (the report)", old_got["oldHead"],
              ["blue", "Building now"])
        check("[10] old Figure body rows ignore the Build's step (shape row stays green)", old_got["body"]["shape"][1][1],
              "green")

shutil.rmtree(_tmp, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
