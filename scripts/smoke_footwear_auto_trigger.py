#!/usr/bin/env python3
"""Footwear, Task 21 fix round: an AUTOMATIC trigger never re-spends a refused shoe source.

Usage:
    ./.venv/bin/python scripts/smoke_footwear_auto_trigger.py

The same throwaway storage, stubs and fixture as ``scripts/smoke_footwear_chain.py`` (imported from it: the
wedge pump, the fake edit backend and mesher with their counters, fake rembg / decimation; the gates, the queue
and the inventory are real). No world, no hub, no server.

THE FINDING (clone acceptance, Task 21): the Business Heels chain was refused at ``mesh`` after its two attempts.
One second later a THIRD UniForge job started: equipping the piece had made the outfit resolve its own-mesh items
(``base_body.resolve_mesh_items`` -> ``garments.run_queued``), which queued a plain run of the item BEHIND the run
in flight; ``run_queued`` checks ``cached_failure`` when it ENQUEUES, the refusal was recorded only when the first
run ended, and the queued run then re-ran the refused step from scratch — two more mesher calls on the same
cut-out. And the refusal record is per wearer (``garment_store`` under the character), while the shoe source is
one per item: a second wearer's automatic run would have spent the mesher again.

THE RULE: an automatic trigger (``enqueue_garment`` / ``run_queued`` — equip, ``resolve_mesh_items``, the outfit
build; ``after_base_model`` never queues footwear) never starts a source chain whose last run for the same input
(the item's current ``ssig``) was refused or failed: ``footwear_source.refused_step`` (any wearer; ``LOAD``
failures retry) joins the per-wearer record in ``garments.cached_failure``, and an automatic job re-checks it
when it STARTS (``_Job.automatic``, ``_worker``). Only an explicit Run / Regenerate (``start_garment`` from the
Wardrobe route) runs it again; the Wardrobe chip keeps showing the refusal reason (``garment_info`` status).

Hand derivation (the fixture of smoke_footwear_chain.py: one run from nothing costs (upscale, edit, mesh) =
(1, 1, 1); with the mesher answering {ok False} the mesh step ends after ONE mesher call — an outright failure
earns no second attempt — and the run is {ok False, step "mesh"}):

[A1] the refusal: run_garment(Kira, heels) with the mesher failing -> {ok False, step "mesh", retry_later None},
     counters (1, 1, 1); cached_failure(Kira, heels).step == "mesh"; footwear_source.refused_step(heels) ==
     {ssig: current, step "mesh", failure "backend", error "shoe mesh generation failed: FakeMesh delivered
     nothing"} (the record keeps the mesher's own words).
[A2] THE RACE: the mesher is made slow (0.8 s); an explicit run of heels (start_garment, force from "mesh" —
     a new seed, so the source is NOT refused yet) starts in the worker; while its mesher call is in flight
     (counter grew by 1), run_queued(Kira, [heels]) from the main thread finds no failure (the refusal is not
     recorded yet) and queues an automatic run behind it; the explicit run ends refused. BEFORE the fix the
     automatic run re-ran the mesh: counter +1 more. AFTER: it is skipped at its start — mesher counter grew by
     exactly 1 over the whole step, run_queued's result is {ok False, step "mesh", cached True, ran []}.
[A3] another wearer: run_queued(Mira, [heels]) -> {ok False, step "mesh", cached True} and the counters do not
     move (before the fix Mira had no failure record of her own: the mesher ran again).
     piece_status(garment_info(Mira, heels), worn) — the Wardrobe chip: state "missing" (a shoe's source steps
     are not clothing's image steps; no mesh, no fit) with reason "mesh — <the refusal>", although Mira's own
     runs never recorded one (garment_info reads the source refusal for footwear).
[A4] explicit wins: start_garment(Kira, heels) (a plain, explicit Run all) -> the mesher IS called again
     (counter +1), still refused; start_garment(Kira, heels, steps="mesh", force=True) (Regenerate) -> +1 again
     under a new ssig.
[A5] a load failure is not a refusal: with the mesher busy (BackendBusyError) the record's failure is "load" ->
     refused_step(heels) is None and run_queued(Mira, [heels]) RUNS (counter +1; Mira, because Kira's own A4
     refusal record under the same fsig rightly still holds HER automatic runs back).
[A6] the version: FOOTWEAR_SOURCE_VERSION == 2 and current_ssig(heels) == md5[:12] of {"image": sha256(item
     image), "version": 2, "seed": <seed>} — a record under the version-1 ssig (a pre-fix skipped ``empty``) is
     not the current source: the current ssig's ``empty`` record carries no ``skipped``, the old folder's does.

FAILS BEFORE / PASSES AFTER — on d55c55f0 (``git archive d55c55f0 app plugins shared scripts`` + this file):
[A1] refused_step None (the function does not exist), [A2] mesher (1, 1, 3) instead of (1, 1, 2) — the queued
automatic run re-meshed the refused input — and its result not ``cached``, [A3] Mira's automatic run meshed
again ((1, 1, 4)) and was not ``cached``; [A5] then stops on the missing ``refused_step`` ([A6]'s version 1
would fail too).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_footwear_chain import (EditBackend, Service, fake_decimate, fake_rembg, flat_x4, png,  # noqa: E402
                                  shoe, silhouette_crop, wedge_glb)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


class SlowService(Service):
    """The chain smoke's service with an adjustable mesher delay and a gate on entering the mesher."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mesh_delay = 0.0
        self.entered = threading.Event()

    def generate_mesh(self, source_image_path, output_path, **kw):
        self.entered.set()
        if self.mesh_delay:
            time.sleep(self.mesh_delay)
        return super().generate_mesh(source_image_path, output_path, **kw)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-auto-") as tmp:
        root = Path(tmp)
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

        from app.core import footwear_source as fs
        from app.core import garment_assembly, garments, model_refs
        from app.core import garment_store as gs
        from app.imagegen.routing import Route
        from app.models import inventory
        from app.models.character import save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True

        crop = silhouette_crop()
        edit = EditBackend(png(flat_x4(shoe(crop, False))))
        svc = SlowService(edit, wedge_glb())

        def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
            return render(edit), Route(occasion=occasion, backend=edit, position=1, spec="FakeEdit*",
                                       intended_spec="FakeEdit*", first_position=1)

        for name in ("Kira", "Mira"):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "gender": "female", "age": 30, "height": 168}, create_new=True),
                True)
        heels = inventory.add_item(name="Heels", category="outfit_piece", prompt_fragment="black heels",
                                   outfit_piece={"slots": ["feet"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        folder = inventory._get_item_dir(heels, create=True)
        shoe(crop, True).save(folder / "image.png", format="PNG")
        check("image set", inventory.set_item_image(heels, "image.png"), True)
        for who in ("Kira", "Mira"):
            check(f"{who} holds heels", inventory.add_to_inventory(who, heels), True)
        image_sha = hashlib.sha256((folder / "image.png").read_bytes()).hexdigest()

        with patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", fake_run_routed), \
             patch("app.models.character.run_rembg", fake_rembg), \
             patch("app.blender.refine.decimate_to", fake_decimate):

            print("[A1] the refusal")
            svc.mesh_fails = True
            res = garments.run_garment("Kira", heels)
            check("A1 result", (res.get("ok"), res.get("step"), res.get("retry_later")), (False, "mesh", None))
            check("A1 counters", svc.counts(), (1, 1, 1))
            check("A1 cached_failure", (garments.cached_failure("Kira", heels) or {}).get("step"), "mesh")
            refused = getattr(fs, "refused_step", lambda *_a, **_k: None)(heels)   # absent before the fix round
            check("A1 refused_step", refused, {"ssig": fs.current_ssig(heels), "step": "mesh", "failure": "backend",
                                              "error": "shoe mesh generation failed: FakeMesh delivered nothing"})

            print("[A2] the race: an automatic run queued behind the run that refuses")
            svc.mesh_delay = 0.8
            svc.entered.clear()
            before = svc.counts()
            # an explicit Regenerate from the mesh: a NEW ssig, so nothing is refused yet when the next run is queued
            started = garments.start_garment("Kira", heels, steps="mesh", force=True)
            check("A2 explicit started", started.get("started"), True)
            check("A2 mesher entered", svc.entered.wait(10), True)
            auto = garments.run_queued("Kira", [heels])   # queued behind the explicit run, waits for both
            svc.mesh_delay = 0.0
            check("A2 explicit run refused once (mesher +1)", svc.counts(), (before[0], before[1], before[2] + 1))
            check("A2 automatic run skipped", (auto[heels].get("ok"), auto[heels].get("step"), auto[heels].get("cached"),
                                               auto[heels].get("ran")), (False, "mesh", True, []))
            check("A2 idle", garments.wait_idle(10), True)

            print("[A3] another wearer's automatic run")
            before = svc.counts()
            auto = garments.run_queued("Mira", [heels])
            check("A3 Mira skipped", (auto[heels].get("ok"), auto[heels].get("step"), auto[heels].get("cached")),
                  (False, "mesh", True))
            check("A3 counters unchanged", svc.counts(), before)
            from app.core.garment_set import piece_status
            info = garments.garment_info("Mira", heels)
            status = piece_status(info, worn=True, base_model_ready=False)
            check("A3 the chip: missing, reason names the mesh refusal",
                  (status.get("state"), str(status.get("reason") or "").startswith("mesh — ")), ("missing", True))

            print("[A4] an explicit run still runs")
            before = svc.counts()
            garments.start_garment("Kira", heels)
            check("A4 idle", garments.wait_idle(20), True)
            check("A4 explicit Run all meshed again (+1)", svc.counts(), (before[0], before[1], before[2] + 1))
            old = fs.current_ssig(heels)
            garments.start_garment("Kira", heels, steps="mesh", force=True)
            check("A4 idle", garments.wait_idle(20), True)
            check("A4 Regenerate meshed again (+1) under a new ssig",
                  (svc.counts(), fs.current_ssig(heels) != old), ((before[0], before[1], before[2] + 2), True))

            print("[A5] a load failure retries")
            from app.imagegen.base import BackendBusyError
            svc.mesh_fails = False
            svc.mesh_raise = BackendBusyError("FakeMesh is busy")
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.mesh_raise = None
            check("A5 load result", (res.get("ok"), res.get("step"), res.get("retry_later")), (False, "mesh", True))
            check("A5 refused_step None (load is no refusal)", fs.refused_step(heels), None)
            svc.mesh_fails = True
            before = svc.counts()
            # Mira: no per-wearer record of her own (Kira's A4 refusal is Kira's); the source says "load" only.
            auto = garments.run_queued("Mira", [heels])
            check("A5 automatic run after load RUNS (+1)", svc.counts(), (before[0], before[1], before[2] + 1))
            check("A5 … and is refused", (auto[heels].get("ok"), auto[heels].get("step")), (False, "mesh"))

            print("[A6] the source version")
            check("A6 FOOTWEAR_SOURCE_VERSION", fs.FOOTWEAR_SOURCE_VERSION, 2)
            seed = fs.current(heels)["seed"]
            want = hashlib.md5(json.dumps({"image": image_sha, "version": 2, "seed": seed},
                                          sort_keys=True).encode("utf-8")).hexdigest()[:12]
            check("A6 current ssig = md5 of the version-2 payload", fs.current_ssig(heels), want)
            old_ssig = hashlib.md5(json.dumps({"image": image_sha, "version": 1, "seed": seed},
                                              sort_keys=True).encode("utf-8")).hexdigest()[:12]
            d = fs.source_dir(heels, old_ssig)
            d.mkdir(parents=True, exist_ok=True)
            (d / "record.json").write_text(json.dumps({"steps": {"empty": {"accepted": True, "skipped": True}}}))
            check("A6 a pre-fix skipped empty under the version-1 ssig is not the current source",
                  (old_ssig != fs.current_ssig(heels), fs.step_record(heels, old_ssig, "empty").get("skipped"),
                   fs.step_record(heels, fs.current_ssig(heels), "empty").get("skipped")), (True, True, None))
            check("idle", garments.wait_idle(10), True)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
