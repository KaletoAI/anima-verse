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
   routing probes only its intended entry. An explicit "Cloud" pick does not
   probe Spare either (only the backends matching the pick are probed).
   The B8 room image is named "<unix seconds>_<6 hex>.png" (a suffix, so
   two room images in one second cannot overwrite each other).

PART C — when describe_room renders a room image (coordinator ruling on the
12b review). The render prompt of a room is its image_prompt_day, else its
description. describe_room renders only when the room has no gallery image
yet OR that render prompt changed; the reply says "Bildgenerierung
gestartet." exactly when it renders. `_trigger_room_image` is replaced by a
recorder. Room "Millroom" holds the B8 image; image_prompt_day empty.
C1 same description again -> render prompt unchanged, image present
   -> no render, no "gestartet" in the reply.
C2 new description -> render prompt changed -> one render.
C3 image_prompt "A mill interior, warm light" -> render prompt becomes that
   (was the description) -> one render.
C4 another new description while the image prompt stays -> the render
   prompt is still the image prompt, image present -> no render.
C5 room "Loft" (added with a description, no image) described with the SAME
   description -> no image yet -> one render.
C6 new room "Cellar" -> created, no image yet -> one render.

PART P — prop source + item image (occasions "prop", "item"; plan Task 13,
whose smoke cases the plan numbers C1-C6 — renamed P here because C is the
describe_room gate above). Same fake pool as part B (Gw dead, family
natural; Cloud ok, family keywords). A new prop's variant None is its
primary variant, whose front image is recorded on the MASTER record
(backend_image / image_routing / image_fallback_from).
P1 prop source, no glob, rules prop ["Gw","Cloud"] -> True. Gw is the
   intended entry (ok until it fails), fails at runtime, the re-run lands on
   Cloud at position 2 -> master record backend_image "Cloud",
   image_routing {"occasion":"prop","position":2,"spec":"Cloud"},
   image_fallback_from {"occasion":"prop","intended_spec":"Gw","position":1};
   the prompt Cloud got differs from Gw's (the "prop" style differs per
   family: natural prose vs keywords -> recomposed for the new backend).
P2 prop source with a dialog prompt "DIALOG" (no key areas on the prop, so
   nothing is appended) -> Gw (first try) receives exactly "DIALOG"; the
   re-run on Cloud receives a composed prompt, not "DIALOG" (decision 1:
   a dialog-final prompt is verbatim on the FIRST attempt only).
P3 prop source, explicit glob "Gw" while Gw cools down since P2 -> False;
   Cloud not asked (still its one P2 call) — an explicit pick is never
   routed elsewhere.
P4 an explicit re-render on Cloud after P1/P2 -> master record backend_image
   "Cloud" and NO image_routing / image_fallback_from (an explicit pick writes
   neither, and a new write of the front replaces the old marks).
P5 item image, no backend, rules item ["Cloud"] -> True; item meta
   backend "Cloud", routing {"occasion":"item","position":1,"spec":"Cloud"},
   no fallback_from (position 1 is the intended entry).
P6 item image, explicit backend "Gw" (cooling via mark_unhealthy) -> False,
   Cloud not asked. BEHAVIOUR CHANGE: the old path soft-warned and fell back
   to the automatic pick; an explicit pick now renders there or nowhere.
P7 item image, explicit "Cloud" with LoRA "foreign.safetensors" (the LoRA
   library is empty, nothing is associated with Cloud) -> False, Cloud not
   asked (the hard LoRA gate of an explicit dialog pick, CLAUDE.md).
P8 item image, no backend, rules item ["Gw","Cloud"], dialog prompt "DIALOG"
   + model_override "m-dialog" -> True. Gw (first try) receives exactly
   "DIALOG" with params model "m-dialog"; the re-run on Cloud receives the
   item's OWN subject composed for Cloud (it names "Lantern" — the item has
   no image_prompt / prompt_fragment, so its name is the subject — and is
   not "DIALOG") and no "model"; item meta routing position 2 and
   fallback_from {"occasion":"item","intended_spec":"Gw","position":1}.
P9 (fix round 1) POST /inventory/items/{id}/generate-image with explicit
   backend "Gw" while Gw cools down -> HTTPException 503 whose detail names
   'Gw' and "no automatic fallback"; no background thread is started and no
   backend is asked (the fire-and-forget thread could only log it).
P10 (fix round 1) the prop chain `_generate(image_only)` with explicit glob
   "Gw" while Gw cools down -> {"ok": False, "error": "source render failed:
   backend 'Gw' is not available — no automatic fallback"}, and the tracked
   task finishes with that same text (not a bare "source render failed").
P11 (fix round 1) the prop chain with explicit glob "Busy" whose render
   raises BackendBusyError("gpu busy") -> the exception propagates out of
   `_generate`, and the tracked task finishes with error
   "BackendBusyError: gpu busy" (it used to finish with "" = success).
P12 (fix round 1) back view of a prop WITHOUT a front image, front_reference
   on, rules prop ["Q*"] matching "Q-txt" (txt2img, cost 0) and "Q-ref"
   (img2img, cost 5): there is no picture to slot, so the routing is asked
   without a reference -> the cheaper Q-txt renders, Q-ref is never asked,
   and Q-txt gets no reference_images. (With has_ref=True — the old
   bool(front_reference) — the img2img preference would have picked Q-ref.)
DEFERRED: the surface-texture case of the plan (its C4, occasion
"surface_texture") waits until app/core/surface_textures.py — which carries
another session's uncommitted change — is routed.
Item renders pass through postprocess_outfit_image (rembg); the smoke
replaces it with the identity so no model is loaded or downloaded.
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
    import re
    check("B8 room image name has a suffix",
          bool(room_images) and bool(re.fullmatch(r"\d+_[0-9a-f]{6}\.png", room_images[0])),
          True)

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
    gallery({"prompt": "x", "backend": "Cloud"})
    check("B12 explicit pick does not probe Spare", spare.probes, 0)
    return loc, room["id"]


def part_c(loc, millroom_id):
    print("C) describe_room renders only on a change or a missing image")
    from app.models import world
    from app.skills.describe_room_skill import DescribeRoomSkill
    triggered = []
    DescribeRoomSkill._trigger_room_image = staticmethod(
        lambda location_id, room_id: triggered.append(room_id))
    skill = DescribeRoomSkill({})
    skill._get_allowed_location_ids = lambda character: [loc]

    def describe(room, **fields):
        triggered.clear()
        reply = skill.execute(json.dumps(dict(agent_name="demo", location_id=loc,
                                              room=room, **fields)))
        return list(triggered), "Bildgenerierung gestartet." in reply

    check("C1 unchanged description", describe(
        "Millroom", description="Grinding stones under a timber roof."), ([], False))
    check("C2 changed description", describe(
        "Millroom", description="Flour sacks by the grinding stones."), ([millroom_id], True))
    check("C3 new image prompt", describe(
        "Millroom", image_prompt="A mill interior, warm light"), ([millroom_id], True))
    check("C4 description changed, image prompt kept", describe(
        "Millroom", description="An empty millroom."), ([], False))
    loft = world.add_room(loc, "Loft", "Beams and dusty grain sacks.")
    check("C5 room without an image", describe(
        "Loft", description="Beams and dusty grain sacks."), ([loft["id"]], True))
    rendered, said = describe("Cellar", description="A cool stone cellar.")
    cellar = world.get_room_by_name(world.get_location_by_id(loc), "Cellar") or {}
    check("C6 new room", (rendered, said), ([cellar.get("id")], True))


def part_p():
    print("P) prop source / item image")
    from app.core import props
    from app.models import character as character_mod
    from app.models import inventory
    from app.routes import inventory as inventory_routes

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"prop": ["Gw", "Cloud"], "item": ["Cloud"]})
    pid = props.create_prop(name="Crate", description="a wooden crate")["id"]
    ok = props._render_source(pid, "", "", "")
    rec = props.read_sidecar(pid)
    check("P1 rendered", ok, True)
    check("P1 master record", (rec.get("backend_image"), rec.get("image_routing"),
                               rec.get("image_fallback_from")),
          ("Cloud", {"occasion": "prop", "position": 2, "spec": "Cloud"},
           {"occasion": "prop", "intended_spec": "Gw", "position": 1}))
    check("P1 recomposed", bool(gw.calls) and bool(cloud.calls)
          and gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    props._render_source(pid, "", "DIALOG", "")
    check("P2 first try verbatim", gw.calls[0]["prompt"] if gw.calls else None, "DIALOG")
    check("P2 re-run composed", bool(cloud.calls) and cloud.calls[0]["prompt"] != "DIALOG",
          True)
    check("P3 explicit dead", props._render_source(pid, "Gw", "", ""), False)
    check("P3 Cloud not asked", len(cloud.calls), 1)

    check("P4 explicit renders", props._render_source(pid, "Cloud", "", ""), True)
    rec = props.read_sidecar(pid)
    check("P4 explicit clears the marks", (rec.get("backend_image"),
                                           "image_routing" in rec,
                                           "image_fallback_from" in rec),
          ("Cloud", False, False))

    character_mod.postprocess_outfit_image = lambda p: p   # no rembg model
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(cloud)
    item = inventory.add_item("Lantern", description="a brass lantern")
    iid = item["id"] if isinstance(item, dict) else item
    check("P5 rendered", inventory_routes.generate_item_image_sync(iid, {}), True)
    im = (inventory.get_item(iid) or {}).get("image_meta") or {}
    check("P5 item meta", (im.get("backend"), im.get("routing"), "fallback_from" in im),
          ("Cloud", {"occasion": "item", "position": 1, "spec": "Cloud"}, False))

    gw = FakeBackend("Gw", 0, "natural", dead=True)
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    check("P6 explicit dead", inventory_routes.generate_item_image_sync(iid, {"backend": "Gw"}),
          False)
    check("P6 nobody asked", (len(gw.calls), len(cloud.calls)), (0, 0))

    check("P7 explicit foreign LoRA", inventory_routes.generate_item_image_sync(
        iid, {"backend": "Cloud",
              "loras": [{"name": "foreign.safetensors", "strength": 1.0}]}), False)
    check("P7 Cloud not asked", len(cloud.calls), 0)

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"prop": ["Gw", "Cloud"], "item": ["Gw", "Cloud"]})
    check("P8 rendered", inventory_routes.generate_item_image_sync(
        iid, {"prompt": "DIALOG", "model_override": "m-dialog"}), True)
    check("P8 first try verbatim", [(c["prompt"], c["params"].get("model")) for c in gw.calls],
          [("DIALOG", "m-dialog")])
    cp = cloud.calls[0] if cloud.calls else {"prompt": "", "params": {}}
    check("P8 re-run own subject", ("Lantern" in cp["prompt"], "DIALOG" in cp["prompt"],
                                    "model" in cp["params"]), (True, False, False))
    im = (inventory.get_item(iid) or {}).get("image_meta") or {}
    check("P8 item meta", ((im.get("routing") or {}).get("position"), im.get("fallback_from")),
          (2, {"occasion": "item", "intended_spec": "Gw", "position": 1}))

    from fastapi import HTTPException
    gw = FakeBackend("Gw", 0, "natural", dead=True)
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)

    class _Req:
        async def json(self):
            return {"backend": "Gw", "prompt": "x"}
    # The background thread's target is the module-level function, looked up
    # when the route starts it: a recorder there sees every started render.
    # (threading.Thread itself must stay real — asyncio.to_thread needs it.)
    started = []
    _real_sync = inventory_routes.generate_item_image_sync
    inventory_routes.generate_item_image_sync = lambda *a, **kw: started.append(a)
    try:
        asyncio.run(inventory_routes.generate_item_image_route(iid, _Req()))
        check("P9 explicit dead -> 503", "no exception", "HTTPException 503")
    except HTTPException as e:
        check("P9 explicit dead -> 503", (e.status_code, "'Gw'" in str(e.detail),
                                          "no automatic fallback" in str(e.detail)),
              (503, True, True))
    finally:
        time.sleep(0.2)          # a wrongly started thread would have run by now
        inventory_routes.generate_item_image_sync = _real_sync
    check("P9 no thread, nobody asked", (started, len(gw.calls), len(cloud.calls)),
          ([], 0, 0))

    from app.core.task_queue import get_task_queue
    from app.imagegen.base import BackendBusyError
    track_errors = []
    _tq = get_task_queue()
    _orig_finish = _tq.track_finish

    def _record_finish(task_id, error=""):
        track_errors.append(error)
        return _orig_finish(task_id, error=error)
    _tq.track_finish = _record_finish
    try:
        res = props._generate(pid, "", "", "Gw", "", image_only=True)
        why = ("source render failed: backend 'Gw' is not available"
               " — no automatic fallback")
        check("P10 chain error names the reason", res, {"ok": False, "error": why})
        check("P10 track error", track_errors, [why])

        class _BusyBackend(FakeBackend):
            def generate(self, prompt, negative_prompt, params, log_meta=None):
                self.calls.append({"prompt": prompt})
                raise BackendBusyError("gpu busy")
        install_pool(_BusyBackend("Busy", 0, "natural"))
        track_errors.clear()
        try:
            props._generate(pid, "", "", "Busy", "", image_only=True)
            check("P11 busy propagates", "no exception", "BackendBusyError")
        except BackendBusyError:
            check("P11 busy propagates", True, True)
        check("P11 track error", track_errors, ["BackendBusyError: gpu busy"])
    finally:
        _tq.track_finish = _orig_finish

    q_txt, q_ref = FakeBackend("Q-txt", 0, "keywords"), FakeBackend("Q-ref", 5, "keywords")
    q_txt.category = "txt2img"
    install_pool(q_txt, q_ref)
    set_routing({"prop": ["Q*"]})
    bare = props.create_prop(name="Stool", description="a three-legged stool")["id"]
    check("P12 rendered", props._render_source(bare, "", "", "", view="back",
                                               front_reference=True), True)
    check("P12 no reference -> cheapest, no slot",
          (len(q_txt.calls), len(q_ref.calls),
           "reference_images" in (q_txt.calls[0]["params"] if q_txt.calls else {})),
          (1, 0, False))


if __name__ == "__main__":
    part_a()
    part_c(*part_b())
    part_p()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
