#!/usr/bin/env python3
"""Footwear, task 6: the shoe chain inside the garment run, the footwear info (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 6; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.2, § 5.6).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_chain.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no GPU, no server. Stubbed:
``get_image_service()`` (counters for ``upscale_image``, the edit backend's
``generate`` and ``generate_mesh``; each sleeps 0.1 s so two runs really
overlap), ``routing.run_routed`` (calls ``render`` once with the fake edit
backend, a real ``Route`` at position 1), ``character.run_rembg`` (matte =
every pixel whose darkest channel is < 200 and not transparent) and
``refine.decimate_to`` (copies the raw GLB). The gates, the insole analysis,
``prompt_compose.compose``, the inventory and the garment queue are real.

Fixture. The wedge pump of ``scripts/_footwear_fixtures.py`` (closed pump,
length 0.26, heel at x = 0) is what the stub mesher delivers. Its side
silhouette (``footwear_gates.side_silhouette``, size 200) crops to 200 x 92 px
(the heel end 92 rows tall, the toe end 31: heel left). ``shoe(leg)``: an RGBA
canvas 232 x 160, transparent, the silhouette in (30, 30, 30) at x [16, 216),
y [60, 152); with ``leg`` a skin (225, 180, 150) column x [16 + 90, 16 + 104)
= [0.45 w, 0.52 w) of the shoe, from row 0 down to row 120 where it is not
shoe. The item image is ``shoe(True)``; the stub editor answers ``shoe(False)``
x4 NEAREST flattened on white.

Hand derivation of the steps (every number from the fixture, the gates are
the real ones; measured once by a prototype, the values only confirm it):
- source: 232 x 160 < 1024 -> exactly 1 upscale (x4 NEAREST -> 928 x 640, long
  side < 1024 -> Lanczos top-up to 1024 x 706).
- empty: the edit always runs (no shortcut for an item image that is already
  one shoe) -> exactly 1 edit; the edit's matte is the silhouette alone: one
  component (single_share 1.0), aspect 200/92 = 2.17 in 1.1..2.4, no leg; IoU
  with the item below the empty shoe's own top edge: the leg column stands
  above the wedge's top in every column it crosses and drops out, the rest
  is the same silhouette -> ~1.0 >= 0.85 -> accepted at attempt 1.
- cutout: local (no service call).
- mesh: exactly 1 mesher call; the wedge is one welded component
  (component_share 1.0) and its side silhouette is the cut-out's alpha up to
  resampling (IoU ~1 >= 0.80) -> accepted at attempt 1.
- insole: the wedge pump's insole is accepted (smoke_footwear_insole [I1]),
  no service call.
So ONE run of an item from nothing costs (upscale, edit, mesh) = (1, 1, 1).

[C1] run_garment(Kira, heels) -> {ok True, fsig = garment_fsig(Kira, heels),
     ran ["source", "empty", "cutout", "mesh", "insole"]} (Kira has no base
     model: no "fit" in ran, ``fit`` "no_base" — the fit step itself is
     smoke_footwear_fit_step.py); counters (1, 1, 1); no
     running step left; status not failed; a second run_garment(Kira, heels)
     -> ran [], counters still (1, 1, 1).
[C2] Mira holds heels too: run_garment(Mira, heels) -> ok, ran [], counters
     still (1, 1, 1) — one source per item, whoever wears it; the fsig of both
     wearers is the same (no base in it).
[C3] A second item ``pumps`` (same image file bytes, another item id -> its
     own source), held by Kira AND Mira. Two threads start run_garment(Kira,
     pumps) and run_garment(Mira, pumps) behind one barrier: the counters grow
     by exactly (1, 1, 1) — the item lock serializes the steps, the later run
     finds them done — both results ok, and the two ``ran`` lists together
     hold each of the five item steps exactly once.
[C4] start_garment(Kira, heels, steps="mesh", force=True) -> started; idle
     after it; the item's ssig is ssig_for(heels, 1) (seed 0 -> 1, not the old
     one); counters grew by (0, 0, 1) — only the mesher; the new folder's
     source/empty/cutout records carry ``copied_from`` = the old ssig.
     start_garment(Kira, heels, steps="mesh", view="front") -> ValueError
     (footwear has no views).
[C5] garment_info(Kira, heels): kind "footwear", method "shoe", ssig = the C4
     ssig, steps.empty {status "accepted", freshness {state "current",
     reason ""}}, steps.mesh.status "accepted", steps.insole.status
     "accepted", steps.fit.status "missing" (no base model), insole.nominal
     present, mesh_url and item_image_url set, stale_reasons [].
     The item image file is replaced (one pixel changed) -> the current ssig
     changes, nothing exists under it yet -> the info still shows the C4
     source: ssig the C4 one, current_ssig the new one, steps.empty.status
     "accepted" with freshness {state "stale", reason "Item image changed"},
     stale_reasons ["item_image_changed"].
[C6] Load is no defect: the next default run of heels (new item image -> new
     ssig) meets a BackendBusyError from the upscaler -> {ok False, step
     "source", error_type "BackendBusyError", retry_later True}; no failure
     record under the fsig (cached_failure None), counters unchanged except
     the busy upscale attempt (the stub raised before counting).
     A refusal IS a defect: with the mesher answering {ok False} the same run
     goes source (1 upscale), empty (1 edit), cutout, then 1 mesher call (an
     outright failure ends the step at once, footwear_source._step_mesh; only
     a gate refusal earns the second attempt) -> {ok False, step "mesh"}, no retry_later, and cached_failure(Kira,
     heels).step == "mesh" (automatic triggers wait for an explicit run).
[C7] The helper of the pre-Task-6 skip is gone: garments has no
     ``_footwear_unavailable`` / ``FOOTWEAR_NOT_AVAILABLE``.
[C8] The step record names the real cause and the Wardrobe tells a failed
     backend from a refusal (P1 fix round):
     - after the C6 mesher {ok False}: garment_info steps.mesh.status "failed"
       (a backend failure, not "refused"), error "shoe mesh generation
       failed: FakeMesh delivered nothing".
     - the real routing shape of a dead backend: generate_mesh raises
       NoRouteError("mesh_footwear", FakeMesh* cooling down) chained FROM
       BackendFailedError(FakeMesh, "FakeMesh: job j1 failed: ComfyUI: node
       10 UniForge3DGenerate: UniForge3D worker exited with status 1") ->
       the default run reruns only the mesh (1 mesher call): res.error =
       "shoe mesh failed: " + the BackendFailedError text (no "cooling
       down"), no retry_later; steps.mesh {status "failed", error = that
       text}; the attempt record carries failure "backend".
     - load: generate_mesh raises BackendBusyError("FakeMesh is busy") ->
       retry_later True, steps.mesh.status "waiting".
     - a gate refusal: the mesher delivers the wedge plus a box 0.1 m on a
       side 5 m away (area 6 * 0.01 = 0.06 m^2, its own component outside the
       wedge's bbox) -> component_share = wedge / (wedge + 0.06) < 0.98 for
       any wedge area below 2.94 m^2 (the wedge is a 0.26 m shoe) -> refused
       after 2 mesher calls; steps.mesh.status "refused".
"""
import io
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

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def silhouette_crop():
    import numpy as np
    from _footwear_fixtures import wedge
    from app.core import footwear_gates
    P, F = wedge()
    sil = footwear_gates.side_silhouette(P, F, size=200)
    rows = np.nonzero(sil.any(1))[0]
    cols = np.nonzero(sil.any(0))[0]
    return sil[rows.min():rows.max() + 1, cols.min():cols.max() + 1]


def shoe(crop, leg: bool):
    import numpy as np
    from PIL import Image
    h, w = crop.shape
    mask = np.zeros((160, 232), bool)
    mask[60:60 + h, 16:16 + w] = crop
    arr = np.zeros((160, 232, 4), np.uint8)
    arr[mask] = (30, 30, 30, 255)
    if leg:
        col = np.zeros_like(mask)
        col[0:120, 16 + int(0.45 * w):16 + int(0.52 * w)] = True
        arr[col & ~mask] = (225, 180, 150, 255)
    return Image.fromarray(arr, "RGBA")


def flat_x4(im):
    from PIL import Image
    big = im.resize((im.width * 4, im.height * 4), Image.NEAREST)
    out = Image.new("RGB", big.size, (255, 255, 255))
    out.paste(big.convert("RGB"), mask=big.getchannel("A"))
    return out


def wedge_glb() -> bytes:
    from _footwear_fixtures import wedge
    from app.core import glb_mesh
    P, F = wedge()
    return glb_mesh.static_glb(P.tolist(), F.tolist(), [(0.0, 0.0)] * len(P))


# --- stubs --------------------------------------------------------------------------------------------------------------

class EditBackend:
    name = "FakeEdit"
    api_type = "fake"
    image_family = "natural"
    model = ""
    ref_slot_count = 1
    max_side = 2048

    def __init__(self, answer):
        self.calls = 0
        self.answer = answer
        self._lock = threading.Lock()

    def generate(self, prompt, negative, params, log_meta=None):
        time.sleep(0.1)
        with self._lock:
            self.calls += 1
        return [self.answer]


class Service:
    enabled = True

    def __init__(self, edit, mesh_bytes):
        self.pool = object()
        self.edit = edit
        self.mesh_bytes = mesh_bytes
        self.upscales = 0
        self.meshes = 0
        self.busy = False
        self.mesh_fails = False
        self.mesh_raise = None
        self._lock = threading.Lock()

    def upscale_image(self, image_bytes, *, character_name="", **_kw):
        from PIL import Image
        if self.busy:
            from app.imagegen.base import BackendBusyError
            raise BackendBusyError("FakeUp is busy")
        time.sleep(0.1)
        with self._lock:
            self.upscales += 1
        with Image.open(io.BytesIO(image_bytes)) as im:
            up = im.convert("RGB").resize((im.width * 4, im.height * 4), Image.NEAREST)
        return {"bytes": png(up), "backend": "FakeUp", "status": "applied",
                "routing": {"occasion": "upscale", "position": 1, "spec": "FakeUp*"}}

    def run_on_backend(self, backend, op, character_name=""):
        return op(backend), backend

    def run_on_backend_channel(self, backend, gen_fn, **_kw):
        return gen_fn()

    def generate_mesh(self, source_image_path, output_path, **kw):
        time.sleep(0.1)
        with self._lock:
            self.meshes += 1
        if self.mesh_raise is not None:
            raise self.mesh_raise
        if self.mesh_fails:
            return {"ok": False, "error": "FakeMesh delivered nothing"}
        Path(output_path).write_bytes(self.mesh_bytes)
        return {"ok": True, "path": output_path, "backend": "FakeMesh",
                "routing": {"occasion": kw.get("occasion"), "position": 1, "spec": "FakeMesh*"}}

    def counts(self):
        return (self.upscales, self.edit.calls, self.meshes)


def fake_rembg(data, model="u2net", **kwargs):
    import numpy as np
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    matte = ((arr[..., :3].min(axis=2) < 200) & (arr[..., 3] > 0)).astype(np.uint8) * 255
    if kwargs.get("only_mask"):
        return png(Image.fromarray(matte, "L"))
    out = rgba.copy()
    out.putalpha(Image.fromarray(matte, "L"))
    return png(out)


def fake_decimate(path_in, target_tris, out, *, merge_vertices=False):
    shutil.copyfile(path_in, out)
    return {"ok": True, "path": str(out), "tris_before": 1, "tris": 1, "ratio": 1.0, "error": ""}


ITEM_STEPS = ["source", "empty", "cutout", "mesh", "insole"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-chain-") as tmp:
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
        check("silhouette crop 200 x 92", crop.shape, (92, 200))
        edit = EditBackend(png(flat_x4(shoe(crop, False))))
        svc = Service(edit, wedge_glb())

        def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
            return render(edit), Route(occasion=occasion, backend=edit, position=1, spec="FakeEdit*",
                                       intended_spec="FakeEdit*", first_position=1)

        for name in ("Kira", "Mira"):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "gender": "female", "age": 30, "height": 168}, create_new=True),
                True)

        def shoe_item(name):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"black {name.lower()}",
                                     outfit_piece={"slots": ["feet"], "outfit_types": ["casual"],
                                                   "own_mesh": True})["id"]
            folder = inventory._get_item_dir(iid, create=True)
            shoe(crop, True).save(folder / "image.png", format="PNG")
            check(f"{name} image set", inventory.set_item_image(iid, "image.png"), True)
            return iid

        heels = shoe_item("Heels")
        pumps = shoe_item("Pumps")
        for who, item in (("Kira", heels), ("Mira", heels), ("Kira", pumps), ("Mira", pumps)):
            check(f"{who} holds {item}", inventory.add_to_inventory(who, item), True)

        with patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", fake_run_routed), \
             patch("app.models.character.run_rembg", fake_rembg), \
             patch("app.blender.refine.decimate_to", fake_decimate):

            print("[C1] the shoe chain runs in the garment run")
            res = garments.run_garment("Kira", heels)
            fsig = gs.garment_fsig("Kira", heels)
            check("C1 result", (res.get("ok"), res.get("fsig"), res.get("ran"), res.get("fit")),
                  (True, fsig, ITEM_STEPS, "no_base"))
            if not res.get("ok"):
                print("     ", res)
            check("C1 counters", svc.counts(), (1, 1, 1))
            st = gs.status("Kira", heels)
            check("C1 status idle, not failed", (st["running_step"], st["failed"]), (None, None))
            res = garments.run_garment("Kira", heels)
            check("C1 second run cached", (res.get("ok"), res.get("ran")), (True, []))
            check("C1 counters unchanged", svc.counts(), (1, 1, 1))

            print("[C2] a second wearer shares the source")
            res = garments.run_garment("Mira", heels)
            check("C2 Mira", (res.get("ok"), res.get("ran")), (True, []))
            check("C2 counters", svc.counts(), (1, 1, 1))
            check("C2 same fsig", gs.garment_fsig("Mira", heels), fsig)

            print("[C3] two wearers start together: one job per step")
            barrier = threading.Barrier(2)
            results = {}

            def run(who):
                barrier.wait(10)
                results[who] = garments.run_garment(who, pumps)
            threads = [threading.Thread(target=run, args=(w,)) for w in ("Kira", "Mira")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            check("C3 counters +1 per step", svc.counts(), (2, 2, 2))
            check("C3 both ok", (results.get("Kira", {}).get("ok"), results.get("Mira", {}).get("ok")),
                  (True, True))
            ran = (results.get("Kira", {}).get("ran") or []) + (results.get("Mira", {}).get("ran") or [])
            check("C3 every step once", sorted(ran), sorted(ITEM_STEPS))

            print("[C4] forced mesh: new ssig, only the mesher")
            old = fs.current_ssig(heels)
            out = garments.start_garment("Kira", heels, steps="mesh", force=True)
            check("C4 started", out.get("started"), True)
            check("C4 idle", garments.wait_idle(30), True)
            new = fs.current_ssig(heels)
            check("C4 new ssig", (new != old, new), (True, fs.ssig_for(heels, 1)))
            check("C4 counters", svc.counts(), (2, 2, 3))
            check("C4 copied", [fs.step_record(heels, new, s).get("copied_from") for s in ("source", "empty",
                                                                                         "cutout")],
                  [old, old, old])
            check("C4 status not failed", gs.status("Kira", heels)["failed"], None)
            try:
                garments.start_garment("Kira", heels, steps="mesh", view="front")
                check("C4 view refused", "no error", "ValueError")
            except ValueError:
                check("C4 view refused", "ValueError", "ValueError")

            print("[C5] info and freshness")
            info = garments.garment_info("Kira", heels)
            steps = info.get("steps") or {}
            check("C5 kind/method/ssig", (info.get("kind"), info.get("method"), info.get("ssig")),
                  ("footwear", "shoe", new))
            check("C5 empty", (steps.get("empty", {}).get("status"), steps.get("empty", {}).get("freshness")),
                  ("accepted", {"state": "current", "reason": ""}))
            check("C5 mesh/insole", (steps.get("mesh", {}).get("status"), steps.get("insole", {}).get("status")),
                  ("accepted", "accepted"))
            check("C5 fit missing (no base model)", steps.get("fit", {}).get("status"), "missing")
            check("C5 step order", list(steps), ITEM_STEPS + ["fit"])
            check("C5 insole nominal", isinstance((info.get("insole") or {}).get("nominal"), dict), True)
            check("C5 overlay", sorted((info.get("insole") or {}).get("overlay") or {}), ["insole", "topline"])
            check("C5 urls", (bool(info.get("mesh_url")), bool(info.get("item_image_url"))), (True, True))
            check("C5 stale_reasons", info.get("stale_reasons"), [])
            json.dumps(info, allow_nan=False)
            image = inventory.get_item_image_path(heels)
            from PIL import Image
            with Image.open(image) as im:
                changed = im.convert("RGBA")
            changed.putpixel((0, 0), (1, 2, 3, 255))
            changed.save(image, format="PNG")
            current = fs.current_ssig(heels)
            check("C5 image -> new current ssig", current != new, True)
            info = garments.garment_info("Kira", heels)
            steps = info.get("steps") or {}
            check("C5 shows the last source", (info.get("ssig"), info.get("current_ssig")), (new, current))
            check("C5 empty stale", (steps.get("empty", {}).get("status"), steps.get("empty", {}).get("freshness")),
                  ("accepted", {"state": "stale", "reason": "Item image changed"}))
            check("C5 stale_reasons after", info.get("stale_reasons"), ["item_image_changed"])

            print("[C6] load is no defect")
            svc.busy = True
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.busy = False
            check("C6 result", (res.get("ok"), res.get("step"), res.get("error_type"), res.get("retry_later")),
                  (False, "source", "BackendBusyError", True))
            check("C6 no failure record", garments.cached_failure("Kira", heels), None)
            check("C6 no failed file", gs.garment_path("Kira", heels, gs.garment_fsig("Kira", heels),
                                                       "failed").exists(), False)
            check("C6 counters", svc.counts(), (2, 2, 3))
            svc.mesh_fails = True
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.mesh_fails = False
            check("C6 refusal", (res.get("ok"), res.get("step"), res.get("retry_later"), res.get("ran")),
                  (False, "mesh", None, ["source", "empty", "cutout"]))
            check("C6 refusal counters", svc.counts(), (3, 3, 4))
            check("C6 refusal persisted", (garments.cached_failure("Kira", heels) or {}).get("step"), "mesh")

            print("[C8] real causes, failed vs refused vs waiting")
            from app.imagegen.base import BackendBusyError, BackendFailedError
            from app.imagegen.routing import NoRouteError

            def mesh_step():
                return (garments.garment_info("Kira", heels).get("steps") or {}).get("mesh") or {}

            m = mesh_step()
            check("C8 mesher ok False -> failed", (m.get("status"), m.get("error")),
                  ("failed", "shoe mesh generation failed: FakeMesh delivered nothing"))
            cause_text = ("FakeMesh: job j1 failed: ComfyUI: node 10 UniForge3DGenerate: "
                          "UniForge3D worker exited with status 1")
            failed = BackendFailedError(type("B", (), {"name": "FakeMesh"})(), RuntimeError(cause_text))
            no_route = NoRouteError("mesh_footwear", [{"spec": "FakeMesh*", "status": "cooldown"}])
            no_route.__cause__ = failed
            check("C8 the routing text says cooling down", "cooling down" in str(no_route), True)
            c0 = svc.counts()
            svc.mesh_raise = no_route
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.mesh_raise = None
            check("C8 one mesher call", tuple(b - a for a, b in zip(c0, svc.counts())), (0, 0, 1))
            check("C8 result names the real cause", (res.get("ok"), res.get("step"), res.get("error"),
                                                     res.get("retry_later")),
                  (False, "mesh", "shoe mesh failed: " + cause_text, None))
            m = mesh_step()
            check("C8 mesh failed with the cause", (m.get("status"), m.get("error")), ("failed", cause_text))
            check("C8 attempt failure backend", [(a.get("failure"), a.get("error")) for a in m.get("attempts") or []],
                  [("backend", cause_text)])
            svc.mesh_raise = BackendBusyError("FakeMesh is busy")
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.mesh_raise = None
            check("C8 load retry later", (res.get("ok"), res.get("retry_later")), (False, True))
            check("C8 load -> waiting", mesh_step().get("status"), "waiting")
            from _footwear_fixtures import wedge
            from app.core import glb_mesh
            wp, wf = wedge()
            far = [(x + 5.0, y, z) for x in (0, 0.1) for y in (0, 0.1) for z in (0, 0.1)]
            far_f = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
                     (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)]
            n = len(wp)
            good = svc.mesh_bytes
            svc.mesh_bytes = glb_mesh.static_glb(wp.tolist() + far, wf.tolist() + [(a + n, b + n, c + n)
                                                                               for a, b, c in far_f],
                                                 [(0.0, 0.0)] * (n + 8))
            c0 = svc.counts()
            try:
                res = garments.run_garment("Kira", heels)
            finally:
                svc.mesh_bytes = good
            check("C8 gate refusal: 2 mesher calls", tuple(b - a for a, b in zip(c0, svc.counts())), (0, 0, 2))
            m = mesh_step()
            check("C8 gate -> refused", (res.get("ok"), m.get("status"), m.get("gates", {}).get("component_share", 1) < 0.98),
                  (False, "refused", True))

        print("[C7] the temporary skip is gone")
        check("C7 no helper", (hasattr(garments, "_footwear_unavailable"),
                               hasattr(garments, "FOOTWEAR_NOT_AVAILABLE")), (False, False))
        check("idle", garments.wait_idle(10), True)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
