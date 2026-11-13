#!/usr/bin/env python3
"""Two meshes per own-mesh piece — open / closed (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 11b; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md`` Addendum A,
rulings A2 / A7): the state in the clothing fingerprint, the prompts, the fit
lookup, the refit source, the run estimate, the garment queue, the cache GC,
the delivered figure, the Build plan and the layering.

Usage:
    ./.venv/bin/python scripts/smoke_piece_state_mesh.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no world, no hub, no GPU, no server. Fit / image /
mesh files are written by hand (``garment_store.garment_path`` + a record).

Stubs: ``base_body.is_base_pipeline`` -> True, ``base_body.base_signature`` ->
BSIG, ``base_body.current_base`` -> (BSIG, "basesha"),
``base_body.base_model_sha256`` -> "basesha" (no base images exist: the base
view sha256 in every edit payload are ""); in [6] ``garments.run_garment``
blocks for item "busy" (a recorder), ``garment_images.run_edit_step``
writes an accepted image (pair gates hem_t 0.65 both views) and
``garment_images.cut_out`` refuses ("stop here — smoke": the run ends there,
no hub); in [8] the resolver's view / shape inputs as in
``smoke_figure_delivered`` (``dress_text`` "wear:<visible ids>", no stored
shape) and the plan's base refresh / views / model as built.

Fixture: "Demo" (human, on the pipeline) holds and wears jacket
``{slots: [outer], covers: [top], mesh_mode: own_mesh, closable: True}``
"Black Jacket" fragment "black jacket", blouse ``{slots: [top], own_mesh}``
"white blouse" (not closable).

Expected, derived by hand from the brief:

[1] ``fsig_inputs(Demo, jacket)`` with the jacket closed == the BASE
    (c7f0a002) function's output — no ``state`` key, fragment "black jacket";
    ``garment_fsig`` closed == the BASE ``garment_fsig`` (BASE store + BASE
    clothing module) value. Open: inputs ``prompt_fragment`` "black jacket, "
    + ``OPEN_IMAGE_WORDS`` (fix round T12-F1, ruling F15 i-2: "worn open at the
    front (unzipped / unbuttoned), its front edges apart so the body or the
    layer underneath shows between them") and ``state`` "open"; the fsig
    differs from the closed one;
    ``garment_fsig(state="open")`` with the profile closed == the fsig with the
    profile open.
[2] ``edit_prompt(Demo, "worn", "front", profile=open)`` starts "Keep the
    image exactly as it is. Only change their clothing: they now wear only
    black jacket, worn open at the front (unzipped / unbuttoned), its front
    edges apart so the body or the layer underneath shows between them."
    (F15 i-2); ``draft_prompt(Demo, "worn", profile=open,
    item_id=jacket)[0]`` — the BACK's draft (the fit prompt is gone with the
    model fit, Task 11g) — has no "worn open" and equals the closed draft
    (Task 11e / F15 i-1: from behind an open piece looks closed); closed:
    neither contains "worn open" nor "worn closed" (A7).
[3] Fits on "basesha": F_c (record without ``state``) at the closed fsig, F_o
    (``state: "open"``) at the open fsig. Profile closed -> F_c, open -> F_o;
    explicit ``state`` overrides the profile. Only F_c (F_o removed) + open ->
    F_c (fix round T12-F1, ruling F13 b: the closed mesh is SERVED until the
    open one is built — was None per A2), an explicit ``state="open"`` -> None
    (the open chain still sees no open fit), and ``newest_accepted_fits(state=
    "open")`` == {}.
[4] One closed group stored on another base ("oldbsig", its fsig =
    ``edit_fsig_on(closed)``) with an accepted fit; ``_complete`` /
    ``ensure_base_copy`` -> True, ``source_of`` -> its origin (oldbsig, no base
    images, its own fsig). ``find_source`` with the profile closed ->
    that group; with the profile open (current = open fsig) -> None (the open
    inputs differ, ``edit_fsig_on`` check).
[5] Nothing open built: ``run_estimate(state="open")`` -> hub_jobs 5 (worn 2 —
    front edit + back draft, the back's composite is CPU work since Task 11g
    — + ghost 2 + mesh 1, ``HUB_JOBS["clothing:edit_chain"]``), steps all 5. The
    closed chain built (images accepted, prepared mesh, F_c with kind, the
    current ``FIT_VERSION`` and the prepared sha256) ->
    ``run_estimate(state="closed")`` hub_jobs 0, steps [].
[6] Queue (worker held by item "busy"): ``start_garment(jacket,
    state="open")`` twice -> one waiting job; + ``start_garment(jacket)``
    (default, worn closed) -> two waiting jobs (the default run is never
    replaced by the open one). An explicit run ``run_garment(jacket,
    steps="worn", state="open")`` while the profile stays closed -> worn and
    ghost made under the open fsig with state "open" and no "inputs changed"
    (the run ends at the stubbed cut-out: step "cutout", "stop here —
    smoke"), result fsig == the open fsig; the
    profile's piece state stays {} (closed). An open run of the blouse ->
    ValueError "has no open / closed state"; of the jacket unworn ->
    ValueError "is not worn now".
[7] GC: the jacket held, F_c and F_o both stored (profile closed) ->
    ``_garment_roots`` keep holds both garment keys (jacket, fsig_c) and
    (jacket, fsig_o).
[8] Figure: the jacket worn open, only F_c -> delivered ``own`` ∋ jacket,
    ``shown_closed`` == (jacket,), no interim (ruling F13 b: the closed mesh
    stands in, never painted while it exists). ``figure_build.plan`` has
    Step("pieces", "Own mesh · Black Jacket (open)", 3, jacket) — worn 1 +
    ghost 1 + mesh 1: [5]'s closed chain has both backs (its worn back
    follows its front), the open state copies them (ruling F15 i-1) — and no
    other pieces step for the jacket.
    The open chain built (as [5]'s closed one) -> ``own`` ∋ jacket, no
    interim, no pieces step.
[9] Layering: the jacket open with F_o over the blouse with its fit F_b ->
    ``garment_layers.plan`` entry for the jacket: ``fsig`` == the open fsig,
    ``inner`` keys == {blouse}; the blouse entry: ``lsig`` "", ``source`` ==
    F_b — the same as with the jacket closed over F_c (nothing under an open
    piece is removed, D-A4).

Fails on c7f0a002: [1] — ``fsig_inputs`` has no ``state`` parameter.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "c7f0a002"
BSIG = "base0123abcd"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def base_module(path: str, name: str) -> types.ModuleType:
    """The module ``path`` as it was at BASE (its absolute ``app.*`` imports resolve to today's modules)."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{path}"], check=True,
                            capture_output=True, text=True).stdout
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / path)
    exec(compile(source, f"{BASE}:{path}", "exec"), module.__dict__)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="piece-state-mesh-") as tmp:
        root = Path(tmp)
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

        from app.core import base_body, garment_assembly, garment_clothing, garment_images, garment_source, garments
        from app.core import garment_store as gs
        from app.core import outfit_options as oo
        from app.models import inventory
        from app.models.character import get_character_profile, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.base_signature = lambda *_a, **_kw: BSIG
        base_body.current_base = lambda *_a, **_kw: (BSIG, "basesha")
        base_body.base_model_sha256 = lambda *_a, **_kw: "basesha"

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)

        def piece(name, slots, fragment, **extra):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=fragment,
                                     outfit_piece={"slots": slots, "outfit_types": ["casual"],
                                                   "mesh_mode": "own_mesh", **extra})["id"]
            check(f"inventory {name}", inventory.add_to_inventory("Demo", iid), True)
            return iid

        jacket = piece("Black Jacket", ["outer"], "black jacket", covers=["top"], closable=True)
        blouse = piece("White Blouse", ["top"], "white blouse")
        check("wear jacket", inventory.equip_piece("Demo", jacket, source="smoke")["status"], "ok")
        J = inventory.get_item(jacket)
        prof = lambda: get_character_profile("Demo")  # noqa: E731

        def set_state(state):
            oo.set_piece_state("Demo", jacket, state)

        # --- [1] fingerprint ---------------------------------------------------------------------------------
        print("[1] fingerprint")
        base_clothing = base_module("app/core/garment_clothing.py", "base_garment_clothing")
        base_store = base_module("app/core/garment_store.py", "base_garment_store")
        closed_inputs = garment_clothing.fsig_inputs("Demo", J, profile=prof())
        check("closed inputs == BASE", closed_inputs, base_clothing.fsig_inputs("Demo", J, profile=prof()))
        check("closed: no state key", "state" in closed_inputs, False)
        fsig_c = gs.garment_fsig("Demo", jacket)
        with patch.object(garment_clothing, "fsig_inputs", base_clothing.fsig_inputs):
            base_fsig = base_store.garment_fsig("Demo", jacket)
        check("closed fsig == BASE", fsig_c, base_fsig)
        set_state("open")
        open_inputs = garment_clothing.fsig_inputs("Demo", J, profile=prof())
        check("open fragment", open_inputs.get("prompt_fragment"), "black jacket, " + oo.OPEN_IMAGE_WORDS)
        check("open state", open_inputs.get("state"), "open")
        fsig_o = gs.garment_fsig("Demo", jacket)
        check("open fsig differs", fsig_o != fsig_c, True)
        check("explicit closed while open", gs.garment_fsig("Demo", jacket, state="closed"), fsig_c)
        set_state("closed")
        check("explicit open while closed", gs.garment_fsig("Demo", jacket, state="open"), fsig_o)

        # --- [2] prompts -------------------------------------------------------------------------------------
        print("[2] prompts")
        open_prof = oo.with_item_state(prof(), jacket, "open")
        text = garment_clothing.edit_prompt("Demo", "worn", "front", profile=open_prof, item_id=jacket)
        text = text[0] if isinstance(text, tuple) else text
        want = ("Keep the image exactly as it is. Only change their clothing: they now wear only "
                "black jacket, worn open at the front (unzipped / unbuttoned), its front edges apart so the body "
                "or the layer underneath shows between them.")
        check("edit prompt open", text.startswith(want), True)
        back_text = garment_clothing.draft_prompt("Demo", "worn", profile=open_prof, item_id=jacket)[0]
        closed_back = garment_clothing.draft_prompt("Demo", "worn", profile=prof(), item_id=jacket)[0]
        # Task 11e (Ruling V1, F15 i-1): the back never says the open words — the open draft is the closed one.
        check("back draft open", ("worn open" in back_text, back_text == closed_back), (False, True))
        closed_text = garment_clothing.edit_prompt("Demo", "worn", "front", profile=prof(), item_id=jacket)
        closed_text = closed_text[0] if isinstance(closed_text, tuple) else closed_text
        check("closed says no state (A7)",
              any(w in t for t in (closed_text, closed_back) for w in ("worn open", "worn closed")), False)

        # --- [3] fits ----------------------------------------------------------------------------------------
        print("[3] fits")

        def put_fit(item_id, fsig, state=None):
            path = gs.garment_path("Demo", item_id, fsig, "fit")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"glb {item_id} {fsig}".encode())
            record = {"accepted": True, "base_model_sha256": "basesha", "method": "edit_chain"}
            if state:
                record["state"] = state
            gs.write_record(path.with_suffix(".json"), record)
            return path

        f_c = put_fit(jacket, fsig_c)
        f_o = put_fit(jacket, fsig_o, "open")
        fit_of = lambda **kw: (gs.accepted_fit("Demo", jacket, base_model_sha="basesha", **kw) or (None,))[0]  # noqa: E731
        check("closed -> F_c", fit_of(), f_c)
        set_state("open")
        check("open -> F_o", fit_of(), f_o)
        check("explicit closed -> F_c", fit_of(state="closed"), f_c)
        f_o.unlink()
        check("only F_c, open -> F_c (served, F13 b)", fit_of(), f_c)
        check("only F_c, explicit open -> None", fit_of(state="open"), None)
        check("newest open == {}", gs.newest_accepted_fits("Demo", jacket, state="open"), {})
        set_state("closed")
        check("explicit open -> None", fit_of(state="open"), None)

        # --- [4] refit source --------------------------------------------------------------------------------
        print("[4] refit source")
        old_images = {"front": "", "back": ""}
        old_fsig = gs.edit_fsig_on("Demo", jacket, "clothing", prof(), bsig="oldbsig", base_images=old_images)
        old_fit = gs.garment_path("Demo", jacket, old_fsig, "fit")
        old_fit.write_bytes(b"old glb")
        gs.write_record(old_fit.with_suffix(".json"),
                        {"accepted": True, "base_model_sha256": "oldsha", "base_signature": "oldbsig",
                         "inputs": {"base_images": old_images}})
        with patch.object(garment_source, "_complete", lambda *a, **k: True), \
                patch.object(garment_source, "ensure_base_copy", lambda *a, **k: True), \
                patch.object(garment_source, "source_of", lambda *a, **k: {
                    "bsig": "oldbsig", "base_images": old_images, "origin_fsig": old_fsig}):
            src = garment_source.find_source("Demo", jacket, "clothing", "edit_chain", prof(), fsig_c)
            check("closed: the old group", (src or {}).get("fsig"), old_fsig)
            src = garment_source.find_source("Demo", jacket, "clothing", "edit_chain",
                                             oo.with_item_state(prof(), jacket, "open"), fsig_o)
            check("open: None", src, None)
        for p in (old_fit, old_fit.with_suffix(".json")):
            p.unlink()

        # --- [5] estimate ------------------------------------------------------------------------------------
        print("[5] estimate")
        est = garments.run_estimate("Demo", jacket, state="open")
        check("open: 5 hub jobs", (est["steps"], est["hub_jobs"], est["refit"]),
              (["worn", "ghost", "cutout", "mesh", "fit"], 5, False))
        def build_chain(fsig, state=None):
            """The whole chain of one state built: images, prepared mesh, the fit of that mesh."""
            from app.core.garment_fit import FIT_VERSION
            for step in ("worn", "ghost", "cutout"):
                for view in gs.GARMENT_VIEWS:
                    path = gs.garment_path("Demo", jacket, fsig, "image", step=step, view=view)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"png")
                    gs.write_record(path.with_suffix(".json"), {"accepted": True, "attempt": 1,
                                                                "gates": {"first": {"ok": True, "hem_t": 0.65}}})
            # The worn back follows its front (drafted): the open state can reuse it (ruling F15 i-1). It is a
            # composite (Task 11g) — a back without ``fit: "composite"`` is a stale model fit (Ruling C2).
            worn_back = gs.garment_path("Demo", jacket, fsig, "image", step="worn", view="back")
            gs.write_record(worn_back.with_suffix(".json"), {
                **gs.read_record(worn_back.with_suffix(".json")), "fit": "composite",
                "front_sha256": base_body.file_sha256(gs.garment_path("Demo", jacket, fsig, "image", step="worn",
                                                                      view="front"))})
            prepared = gs.garment_path("Demo", jacket, fsig, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"glb")
            gs.write_record(prepared.with_suffix(".json"), {"accepted": True})
            fit = put_fit(jacket, fsig, state)
            gs.write_record(fit.with_suffix(".json"), {
                **gs.read_record(fit.with_suffix(".json")), "kind": "clothing",
                "fit_version": FIT_VERSION["clothing"], "inputs": {"prepared_sha256": garments._sha(prepared)}})
            return fit

        f_c = build_chain(fsig_c)
        est = garments.run_estimate("Demo", jacket, state="closed")
        check("closed with F_c: 0", (est["steps"], est["hub_jobs"]), ([], 0))

        # --- [6] queue + run ---------------------------------------------------------------------------------
        print("[6] queue")
        gate = threading.Event()
        runs = []
        real_run, real_check = garments.run_garment, garments.check_run

        def recorder(character_name, item_id, *, steps=None, view=None, force=False, state=None, only=False):
            runs.append((item_id, steps, state))
            if item_id == "busy":
                gate.wait(30)
            return {"ok": True}

        def check_run(character_name, item_id, **kw):
            if item_id != "busy":
                real_check(character_name, item_id, **kw)

        garments.run_garment, garments.check_run = recorder, check_run
        try:
            garments.start_garment("Demo", "busy")
            for _ in range(500):
                if runs:
                    break
                gate.wait(0.01)
            garments.start_garment("Demo", jacket, state="open")
            garments.start_garment("Demo", jacket, state="open")
            check("open twice: one job", garments.queue_state("Demo")["queue"], [jacket])
            garments.start_garment("Demo", jacket)
            check("+ default: two jobs", garments.queue_state("Demo")["queue"], [jacket, jacket])
            with garments._lock:
                states = [j.state for j in garments._queues.get("Demo") or ()]
            check("states", states, ["open", None])
        finally:
            gate.set()
            check("idle", garments.wait_idle(30), True)
            garments.run_garment, garments.check_run = real_run, real_check
        check("runs", runs, [("busy", None, None), (jacket, None, "open"), (jacket, None, None)])

        seen = []

        def edit_step(character_name, item_id, fsig, step, view, *, force=False, pair_check=None,
                      prompt_hints=None, state=None):
            seen.append((fsig, step, view, state))
            path = gs.garment_path(character_name, item_id, fsig, "image", step=step, view=view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")
            gs.write_record(path.with_suffix(".json"),
                            {"accepted": True, "attempt": 1, "gates": {"first": {"ok": True, "hem_t": 0.65}}})
            return path

        def cut_out(*_a, **_kw):
            raise garments._Refused("cutout", "stop here — smoke", None)

        with patch.object(garment_images, "run_edit_step", edit_step), patch.object(garment_images, "cut_out", cut_out):
            result = garments.run_garment("Demo", jacket, steps="worn", state="open")
        # Worn and ghost passed their "inputs changed" checks under the open fsig; the cut-out is where it stops.
        check("open run: no inputs-changed", (result.get("step"), result.get("error")),
              ("cutout", "stop here — smoke"))
        check("open run fsig", result.get("fsig"), fsig_o)
        check("edit steps", sorted({(f, s, st) for f, s, _v, st in seen}),
              [(fsig_o, "ghost", "open"), (fsig_o, "worn", "open")])
        check("profile still closed", oo.piece_states(prof()), {})
        # Back to "nothing open built" for [8].
        gs.clear_failure("Demo", jacket, fsig_o)
        for path in gs.stored_groups("Demo").get((jacket, fsig_o), []):
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
        for label, item_id, want in (("blouse", blouse, "has no open / closed state"),
                                     ("unworn", jacket, "is not worn now")):
            if label == "unworn":
                inventory.unequip_piece("Demo", "outer")
            try:
                garments.check_run("Demo", item_id, state="open")
                check(f"{label} refused", None, want)
            except ValueError as e:
                check(f"{label} refused", want in str(e), True)
        check("wear jacket again", inventory.equip_piece("Demo", jacket, source="smoke")["status"], "ok")

        # --- [7] GC ------------------------------------------------------------------------------------------
        print("[7] GC")
        from app.core import outfit_cache_gc as gc
        f_o = put_fit(jacket, fsig_o, "open")
        roots = gc._garment_roots("Demo")
        keep = roots[0] if roots else set()
        check("keeps closed", gc._garment_key(jacket, fsig_c) in keep, True)
        check("keeps open", gc._garment_key(jacket, fsig_o) in keep, True)

        # --- [8] figure --------------------------------------------------------------------------------------
        print("[8] figure")
        from app.core import figure, figure_build, model_refs

        def dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=()):
            meshed = {str(i) for i in mesh_items or ()}
            visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
            return ("wear:" + "+".join(visible)) if visible else ""

        base_body.dress_text = dress_text
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front", "back")
        base_body.shape_view_shas = lambda *_a, **_kw: {}
        base_body.stored_base_haired = lambda *_a, **_kw: True
        base_body.prompts_current = lambda *_a, **_kw: True
        base_body.base_refresh_plan = lambda *_a, **_kw: {"signature": BSIG, "views": [], "model": False,
                                                          "reason": ""}
        base_body.dressed_image = lambda *_a, **_kw: Path("v")
        real_find = model_refs.find_ref_image
        model_refs.find_ref_image = (lambda c, kind, signature=None:
                                     root / "front.png" if (kind, signature) == ("tpose", BSIG)
                                     else real_find(c, kind, signature))
        f_o.unlink()
        f_o.with_suffix(".json").unlink()
        set_state("open")
        got = figure.delivered_figure("Demo", profile=prof())
        check("own ∋ jacket (closed mesh)", (jacket in got.own, got.shown_closed), (True, (jacket,)))
        check("no interim", (jacket in got.painted, got.interim.get(jacket)), (False, None))
        steps = [s for s in figure_build.plan("Demo", profile=prof()) if s.name == "pieces"]
        check("pieces step", steps, [figure_build.Step("pieces", "Own mesh · Black Jacket (open)", 3, jacket)])
        f_o = build_chain(fsig_o, "open")
        got = figure.delivered_figure("Demo", profile=prof())
        check("with F_o: own", (jacket in got.own, got.interim.get(jacket)), (True, None))
        check("with the open chain built: no pieces step",
              [s for s in figure_build.plan("Demo", profile=prof()) if s.name == "pieces"], [])

        # --- [9] layering ------------------------------------------------------------------------------------
        print("[9] layering")
        from app.core import garment_layers
        check("wear blouse", inventory.equip_piece("Demo", blouse, source="smoke")["status"], "ok")
        fsig_b = gs.garment_fsig("Demo", blouse)
        f_b = put_fit(blouse, fsig_b)
        layered = garment_layers.plan("Demo", [jacket, blouse], base_sha="basesha", profile=prof())
        check("jacket fsig open", layered.get(jacket, {}).get("fsig"), fsig_o)
        check("jacket inner", sorted(layered.get(jacket, {}).get("inner") or {}), [blouse])
        blouse_open = {k: layered.get(blouse, {}).get(k) for k in ("lsig", "source", "fsig")}
        check("blouse under the open jacket", blouse_open, {"lsig": "", "source": f_b, "fsig": fsig_b})
        set_state("closed")
        layered = garment_layers.plan("Demo", [jacket, blouse], base_sha="basesha", profile=prof())
        check("jacket fsig closed", layered.get(jacket, {}).get("fsig"), fsig_c)
        check("blouse the same closed", {k: layered.get(blouse, {}).get(k) for k in ("lsig", "source", "fsig")},
              blouse_open)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
