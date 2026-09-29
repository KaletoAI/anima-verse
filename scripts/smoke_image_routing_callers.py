#!/usr/bin/env python3
"""Smoke: the image routing reaches every caller (behaviour at the seam).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_callers.py

Spec: development_instructions/plan-image-routing.md § 1 (who uses which
occasion) + review notes. Each part replaces the image service (or the
routing entry point) with a recorder and runs the REAL caller, so the
payload / the occasion the caller hands over is what is checked — the
consumer of the routing. Throwaway storage + world DB, no server.

PART A — messaging frame (occasion "frame", review note: a product shot
without a figure, NOT "photo")
A1 generate_frame("a phone") with no target -> ONE payload with
   occasion "frame" and no "backend" key (routed).
A2 generate_frame("a phone", "Flux2*") -> payload backend "Flux2*" and no
   "occasion" key (an explicit pick: exactly that backend, no fallback).

PART B — location family (occasions "location", "timevariant"), end to end
through the REAL routing on a fake pool: "Gw" (family natural, cost 0)
fails with HTTP 500, "Cloud" (family keywords, cost 5) renders; both have one
reference slot. `run_on_backend_channel` runs the job inline. Gallery file
names are `int(time.time()).png`, so the smoke sleeps 1.1 s before every
render that saves an image — two renders in one second would share a name.
B1 gallery, no backend, rules location ["Gw","Cloud"]: the image is saved;
   its gallery meta has backend "Cloud", routing {"occasion":"location",
   "position":2,"spec":"Cloud"}, fallback_from {"occasion":"location",
   "intended_spec":"Gw","position":1} (Gw failed at runtime and cools down
   -> the intended entry stays Gw, the render is marked).
B2 same render: the prompt Cloud received differs from the one Gw received
   (the second run composed for the keywords family — never the same prompt
   on another backend).
B3 settings_applied + prompt "VERBATIM": the first try (Gw) receives
   exactly "VERBATIM"; after Gw fails, the re-run on Cloud receives a
   composed prompt that is NOT "VERBATIM".
B4 explicit backend "Gw" while Gw cools down -> HTTPException 503, Cloud is
   never asked (an explicit pick is never routed elsewhere).
B5 explicit backend "Cloud" -> rendered on Cloud, meta without "routing".
B6 time variant of a gallery image, no backend, rules timevariant ["Cloud"]
   -> new image, meta routing {"occasion":"timevariant","position":1,
   "spec":"Cloud"}, the reference slot carries the source image.
B7 location background, rules location ["Cloud"] -> exactly one new
   gallery image; its meta has backend "Cloud" and routing
   {"occasion":"location","position":1,"spec":"Cloud"} (checked on the NEW
   file — B1's meta alone would satisfy an "any image" check).
B8 room image of describe_room, rules location ["Cloud"], a room with a
   description -> one image assigned to that room, meta backend "Cloud" and
   routing {"occasion":"location","position":1,"spec":"Cloud"} (the old
   lookup went through the skill manager, found the TakePhoto verb without
   a pool and the room image never rendered).
B9 explicit backend "Gw" that is available but fails at runtime (a fresh Gw,
   not cooled yet) -> HTTPException 500; Gw was asked once, Cloud never (an
   explicit pick is not re-run elsewhere, not even after a failure).
B10 no backend, model_override "m-dialog", rules location ["Gw","Cloud"]:
   the first try (Gw) carries params model "m-dialog"; the re-run on Cloud
   carries no "model" (a dialog's model name belongs to the backend the
   dialog showed). An explicit "Cloud" pick with the same override carries
   it (explicit = the dialog's own backend).
B11 explicit "Cloud" with LoRA "foreign.safetensors" (the library is empty,
   so nothing is associated with Cloud) -> HTTPException 400 whose detail
   says the library "does not associate" it; Cloud is never asked; the
   tracked task finishes with that detail as its error, not a bare
   "refused".
B12 no backend, rules location ["Cloud"], a third backend "Spare" outside
   the chain -> Spare is never probed (check_availability count 0): the
   routing probes only its intended entry, and the gallery core's own
   probe of every backend runs only for an explicit pick.
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = tempfile.mkdtemp(prefix="routing-callers-")
os.environ["STORAGE_DIR"] = _TMP
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="routing-callers-clips-")
from app.core import paths  # noqa: E402
paths.init(_TMP)
from app.core import config, db  # noqa: E402
config.load(Path(_TMP) / "config.json")
db.init_schema()
from app.imagegen import service as service_mod  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class _B:
    def __init__(self, name):
        self.name = name
        self.instance_enabled = True
        self.MEDIA_TYPE = "image"
        self.category = "img2img"


class RecordingService:
    """Records every string payload; answers with an Error so the caller
    stops right after handing it over."""
    enabled = True

    def __init__(self):
        self.payloads = []
        self.backends = [_B("Flux2 A")]

    def generate_from_input(self, raw):
        self.payloads.append(json.loads(raw))
        return "Error: recorded"


from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


class FakeBackend(ImageBackend):
    """Records what it is asked to render; fails with HTTP 500 when `dead`."""

    def __init__(self, name, cost, family, dead=False, ref_slots=1):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_CALLERS_")
        self.image_family = family
        self.category = "img2img"
        self.ref_slot_count = ref_slots
        self.instance_enabled = True
        self._available = True
        self.dead = dead
        self.calls = []
        self.probes = 0

    def check_availability(self):
        self.probes += 1
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        raise AssertionError("generate() is overridden")

    def generate(self, prompt, negative_prompt, params, log_meta=None):
        self.calls.append({"prompt": prompt, "negative": negative_prompt,
                           "params": dict(params)})
        if self.dead:
            raise RuntimeError(f"{self.name}: HTTP 500: gone")
        return [png_bytes()]


def install_pool(*backends):
    """A real ImageService whose pool holds the fakes; jobs run inline."""
    svc = service_mod.ImageService()
    svc.enabled = True
    svc._pool = BackendPool(list(backends), agent_instances_provider=lambda n: {})
    service_mod._service = svc
    service_mod.get_image_service = lambda: svc
    return svc


service_mod.ImageService.run_on_backend_channel = staticmethod(
    lambda backend, gen_fn, **kw: gen_fn())
# No configured instances: the constructor would otherwise probe the default
# backends of the throwaway config over the network.
service_mod.ImageService._load_instances = lambda self: []


def set_routing(rules):
    cfg = config.get_all()
    ig = dict(cfg.get("image_generation") or {})
    ig["routing"] = rules
    cfg["image_generation"] = ig
    config.save(cfg)


def part_a():
    print("A) messaging frame")
    from app.core import messaging_frame
    rec = RecordingService()
    service_mod.get_image_service = lambda: rec
    messaging_frame.generate_frame("a phone")
    check("A1 routed", [(p.get("occasion"), "backend" in p) for p in rec.payloads],
          [("frame", False)])
    rec.payloads.clear()
    messaging_frame.generate_frame("a phone", "Flux2*")
    check("A2 explicit", [(p.get("backend"), "occasion" in p) for p in rec.payloads],
          [("Flux2*", False)])


def part_b():
    print("B) location family")
    from fastapi import HTTPException
    from app.core import world_ops
    from app.core.task_queue import get_task_queue
    from app.models import world
    loc = world.add_location("Mill", "A mill by the river.")["id"]

    track_errors = []
    _tq = get_task_queue()
    _orig_finish = _tq.track_finish

    def _record_finish(task_id, error=""):
        track_errors.append(error)
        return _orig_finish(task_id, error=error)
    _tq.track_finish = _record_finish

    def gallery(data):
        time.sleep(1.1)          # a fresh int(time.time()) file name per render
        return asyncio.run(world_ops.generate_gallery_image_core(loc, dict(data)))

    def meta_of(name):
        return (world.get_gallery_image_metas(loc) or {}).get(name) or {}

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"location": ["Gw", "Cloud"]})
    res = gallery({"prompt": "a mill by the river"})
    m = meta_of(res["image"])
    check("B1 backend", m.get("backend"), "Cloud")
    check("B1 routing", m.get("routing"), {"occasion": "location", "position": 2, "spec": "Cloud"})
    check("B1 fallback_from", m.get("fallback_from"),
          {"occasion": "location", "intended_spec": "Gw", "position": 1})
    check("B2 recomposed for the second backend",
          gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    gallery({"prompt": "VERBATIM", "settings_applied": True})
    check("B3 verbatim on its own backend", gw.calls[0]["prompt"], "VERBATIM")
    check("B3 not verbatim elsewhere", cloud.calls[0]["prompt"] != "VERBATIM", True)

    try:
        gallery({"prompt": "x", "backend": "Gw"})       # Gw cools down since B3
        check("B4 explicit dead", "no exception", "HTTPException 503")
    except HTTPException as e:
        check("B4 explicit dead", e.status_code, 503)
    check("B4 Cloud never asked", len(cloud.calls), 1)   # only the B3 call

    res = gallery({"prompt": "x", "backend": "Cloud"})
    check("B5 explicit renders", meta_of(res["image"]).get("backend"), "Cloud")
    check("B5 no routing meta", "routing" in meta_of(res["image"]), False)

    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    set_routing({"timevariant": ["Cloud"]})
    src = world.get_gallery_dir(loc) / "src.png"
    src.write_bytes(png_bytes())
    time.sleep(1.1)
    res = asyncio.run(world_ops.generate_time_variant_core(
        loc, "src.png", "night", "", ""))
    check("B6 routing", meta_of(res["image"]).get("routing"),
          {"occasion": "timevariant", "position": 1, "spec": "Cloud"})
    check("B6 source in the reference slot",
          cloud.calls[0]["params"].get("reference_images"),
          {"input_reference_image_1": str(src)})

    set_routing({"location": ["Cloud"]})
    before = {p.name for p in world.get_gallery_dir(loc).glob("*.png")}
    time.sleep(1.1)
    asyncio.run(world_ops.generate_location_background(loc, "a mill"))
    new = sorted({p.name for p in world.get_gallery_dir(loc).glob("*.png")} - before)
    check("B7 one background image", len(new), 1)
    bm = meta_of(new[0]) if new else {}
    check("B7 background routed", (bm.get("backend"), bm.get("routing")),
          ("Cloud", {"occasion": "location", "position": 1, "spec": "Cloud"}))

    from app.skills.describe_room_skill import DescribeRoomSkill
    room = world.add_room(loc, "Millroom", "Grinding stones under a timber roof.")
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    before = set(threading.enumerate())
    time.sleep(1.1)
    DescribeRoomSkill._trigger_room_image(loc, room["id"])
    for t in set(threading.enumerate()) - before:
        t.join(timeout=30)
    rooms = world.get_gallery_image_rooms(loc) or {}
    room_images = [n for n, r in rooms.items() if r == room["id"]]
    check("B8 one room image", len(room_images), 1)
    rm = meta_of(room_images[0]) if room_images else {}
    check("B8 room image backend", rm.get("backend"), "Cloud")
    check("B8 room image routing", rm.get("routing"),
          {"occasion": "location", "position": 1, "spec": "Cloud"})

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"location": ["Gw", "Cloud"]})
    try:
        gallery({"prompt": "x", "backend": "Gw"})       # fresh Gw: available, then fails
        check("B9 explicit fails at runtime", "no exception", "HTTPException 500")
    except HTTPException as e:
        check("B9 explicit fails at runtime", e.status_code, 500)
    check("B9 asked Gw once, Cloud never", (len(gw.calls), len(cloud.calls)), (1, 0))

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    gallery({"prompt": "x", "model_override": "m-dialog"})
    check("B10 first try carries the dialog model", gw.calls[0]["params"].get("model"), "m-dialog")
    check("B10 re-run without it", "model" in cloud.calls[0]["params"], False)
    gallery({"prompt": "x", "backend": "Cloud", "model_override": "m-dialog"})
    check("B10 explicit carries it", cloud.calls[1]["params"].get("model"), "m-dialog")

    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    track_errors.clear()
    try:
        gallery({"prompt": "x", "backend": "Cloud",
                 "loras": [{"name": "foreign.safetensors", "strength": 1.0}]})
        check("B11 explicit foreign LoRA", "no exception", "HTTPException 400")
    except HTTPException as e:
        check("B11 explicit foreign LoRA", (e.status_code, "does not associate" in str(e.detail)),
              (400, True))
    check("B11 Cloud never asked", len(cloud.calls), 0)
    check("B11 track error is the real reason",
          [("does not associate" in (e or "")) for e in track_errors], [True])

    cloud, spare = FakeBackend("Cloud", 5, "keywords"), FakeBackend("Spare", 1, "natural")
    install_pool(cloud, spare)
    set_routing({"location": ["Cloud"]})
    res = gallery({"prompt": "x"})
    check("B12 rendered on the chain", meta_of(res["image"]).get("backend"), "Cloud")
    check("B12 Spare never probed", spare.probes, 0)


if __name__ == "__main__":
    part_a()
    part_b()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
