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

PART D — scene view + event image (occasions "scene_view", "event"; plan
Task 14 + binding review note B2). Same fake pool as part B.
D1 the scene-view cache key is sha1("<state sig>|scene_view|<intended
   spec>")[:16], the intended spec being `routing.intended_spec_for` — the
   first chain entry that passes the CONFIGURATION filters (matched, fits,
   enabled, allowed); availability is ignored. Rules scene_view
   ["Gw","Cloud"] with both backends present -> key of "abc|scene_view|Gw".
   Gw put into a cooldown -> the intended entry is still Gw (a cooldown is a
   runtime state, not configuration) -> the key does NOT change (a fallback
   render is served until the chain changes). Rules ["Nope","Cloud"]: "Nope"
   matches no backend (no_match = configuration skip) -> intended "Cloud"
   -> key of "abc|scene_view|Cloud". Rules ["Cloud"] -> the same key as
   ["Nope","Cloud"], and a different one from the Gw key (another chain,
   another render).
D2 event image: a location with a background image, rules event
   ["Gw","Cloud"], Gw fails at runtime -> _do_generate returns a path; its
   sidecar "<image>.json" has backend "Cloud", backend_type "fake",
   routing {"occasion":"event","position":2,"spec":"Cloud"}, fallback_from
   {"occasion":"event","intended_spec":"Gw","position":1}; Cloud got the
   background in reference slot 1.
D3 scene render (build_scene_state replaced by a fixed state, mode
   "only_background", no persons): rules scene_view ["Gw","Cloud"], Gw fails
   at runtime -> {"ok": True, "cached": False} with sig ==
   _scene_sig(<state sig>) (computed while Gw was still the intended entry);
   the scene sidecar has location + room + backend "Cloud", routing position
   2 and fallback_from intended_spec "Gw"; Cloud got the background in
   reference slot 1 and a prompt recomposed for its family (differs from
   Gw's). A second render_scene of the same state (no force) is served from
   the cache: {"cached": True} with the same sig, nobody asked again.
D4 event image, rules event ["Gw"] with Gw cooling -> None, Gw never asked
   (a chain with nothing usable does not fall back to another backend).

PART E — gallery regenerate (occasion "regenerate") and scene photo
("photo"; plan Task 15 + the Task 14 carry-over: the one-click scene photo
must not pre-resolve a backend and pass it as an explicit pick). Same fake
pool as part B (Gw dead, family natural; Cloud ok, family keywords).
Character "Mara" has one gallery image and NO profile image (so the render
slots no identity reference: has_ref False).
E1 regenerate_image("Mara", <img>, "a portrait", create_new=True), rules
   regenerate ["Gw","Cloud"] -> ok and a NEW file (create_new); Gw is the
   intended entry, fails at runtime, the re-run lands on Cloud at position 2
   -> the new file's meta: backend "Cloud", routing position 2,
   fallback_from.intended_spec "Gw".
E2 explicit backend_name "Gw" (cooling since E1) -> RuntimeError, Cloud not
   asked again (still its one E1 call) — an explicit pick is never routed.
E3 explicit backend_name "Cloud" -> the new file's meta routing None and
   fallback_from None (an explicit render writes neither; stored as None so
   an overwritten file loses an old marker too).
E4 occasion="photo", rules photo ["Cloud"] and NO regenerate rules ->
   routing {"occasion":"photo","position":1,"spec":"Cloud"} (the occasion
   parameter is what gets routed, not a fixed "regenerate").
E5 take_scene_photo("Mara") with no dialog backend, prepare_scene_photo
   replaced by a stub whose dialog preselection default_backend is "Cloud",
   regenerate_image replaced by a recorder -> the recorder got
   backend_name "" and occasion "photo" (the preselection is NOT handed over
   as an explicit pick — the one-click photo keeps its fallback).
E6 take_scene_photo("Mara", backend_name="Gw") -> backend_name "Gw",
   occasion "photo" (a backend the user picked stays explicit).
E7 (fix round 1) explicit "Cloud" with LoRA "foreign.safetensors" (the LoRA
   library of the throwaway world is empty, so nothing is associated with
   Cloud) -> LoraNotAllowedError (the hard gate of an explicit pick,
   CLAUDE.md), raised before any render: Cloud's call count unchanged.
E8 (fix round 1) the source image's meta carries source_file "older.png"
   (it was itself a re-render); an explicit create_new regenerate on Cloud
   -> the NEW file's meta has no "source_file" (the marker belongs to the
   image it was written for, not to a variant copied from it), and
   variant_of names the source.
E9 (fix round 1) take_scene_photo whose regenerate raises
   LoraNotAllowedError -> the error propagates (a refusal, like the media
   master switch; /play/scene-photo maps it to 400), it is NOT folded into
   {"ok": False}.

PART F — video (occasion "video"; plan Task 16a). Labels F-V<n>; the mesh
half (Task 16b) adds its own F cases. Fake pool of video backends: "VDead"
(cost 0, fails with HTTP 500) and "VOk" (cost 3, renders b"mp4-or-glb");
`run_on_backend_channel` runs the job inline.
F-V1 generate_video, no glob, rules video ["VDead","VOk"] -> True; the file
   holds VOk's bytes; route_out == {"backend": "VOk", "routing":
   {"occasion": "video", "position": 2, "spec": "VOk"}, "fallback_from":
   {"occasion": "video", "intended_spec": "VDead", "position": 1}} (VDead
   is the intended entry, fails at RUNTIME and cools down -> marked,
   coordinator decision 2).
F-V2 generate_video, explicit "VDead" (cooling since F-V1) -> False; VOk is
   not asked again (still its one F-V1 call) — an explicit pick is never
   routed elsewhere.
F-V3 explicit "VOk" with route_out -> True, route_out == {"backend": "VOk"}
   (an explicit render writes neither "routing" nor "fallback_from").
F-V4 LoRA "foreign.safetensors" (the throwaway LoRA library is empty, so no
   backend has it): routed (rules video ["VOk"]) -> True, VOk's params carry
   no "lora_inputs" (soft half of the gate on a routed render); explicit
   "VOk" -> LoraNotAllowedError before any render (VOk's call count
   unchanged) — the hard half for a dialog pick.
F-V5 the video skill: declares no config fields (get_config_fields() == {},
   `animate_service` gone, not in _defaults). A stale stored skill value
   {"animate_service": "VDead"} (fresh pool: VDead fresh and dead), rules
   video ["VOk"]; the still render is replaced by a stub that saves one
   gallery image -> the skill answers with the video link, VDead is NEVER
   asked (the stored value is ignored, not migrated — the named feature
   loss) and the image's meta has animate_backend "VOk", animate_routing
   {"occasion": "video", "position": 1, "spec": "VOk"},
   animate_fallback_from None, and no "animate_service" key.
F-V6 get_character_image_metadata exposes animate_backend /
   animate_routing / animate_fallback_from for that image (whitelist), and
   the IMAGE's own "routing" is not the video's (the stub's still carries
   no routing -> absent).
F-V7 Instagram animate (the background thread runs inline): no service,
   rules video ["VDead","VOk"] (fresh pool) -> the post gets its video; the
   image meta: animate_backend "VOk", animate_routing position 2,
   animate_fallback_from.intended_spec "VDead". Then explicit service "VOk"
   -> animate_backend "VOk", animate_routing None, animate_fallback_from
   None (a re-animation drops the old marks). Explicit "VDead" (cooling)
   -> HTTPException 503 before anything starts, VOk's calls unchanged.
   Explicit "VOk" with LoRA "foreign.safetensors" -> HTTPException 400.
F-V8 deleting the animation scrubs the three keys: the Instagram route
   (delete_instagram_animation) and the gallery's remove_image_animation.
Fails on commit 462007bc (before Task 16a): F-V1 aborts with
   "generate_video() got an unexpected keyword argument 'route_out'".

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


def part_d():
    import hashlib
    print("D) scene view + event image")
    from app.core import event_images, scene_render
    from app.imagegen import routing
    from app.models import world

    def key(spec):
        return hashlib.sha1(f"abc|scene_view|{spec}".encode("utf-8")).hexdigest()[:16]

    gw, cloud = FakeBackend("Gw", 0, "natural"), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"scene_view": ["Gw", "Cloud"]})
    check("D1 sig from the intended entry", scene_render._scene_sig("abc"), key("Gw"))
    gw.mark_unhealthy("smoke", 300)
    check("D1 cooldown keeps the intended entry",
          routing.intended_spec_for("scene_view"), "Gw")
    check("D1 cooldown keeps the sig", scene_render._scene_sig("abc"), key("Gw"))
    set_routing({"scene_view": ["Nope", "Cloud"]})
    check("D1 no_match is not intended", routing.intended_spec_for("scene_view"), "Cloud")
    check("D1 sig of the configured entry", scene_render._scene_sig("abc"), key("Cloud"))
    set_routing({"scene_view": ["Cloud"]})
    check("D1 another chain, another sig",
          (scene_render._scene_sig("abc"), scene_render._scene_sig("abc") != key("Gw")),
          (key("Cloud"), True))

    loc = world.add_location("Harbour", "A small harbour.")["id"]
    gdir = world.get_gallery_dir(loc)
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "bg.png").write_bytes(png_bytes())
    world.toggle_background_image(loc, "bg.png")
    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"event": ["Gw", "Cloud"]})
    out = event_images._do_generate("ev-smoke", loc, "a storm rolls in", False)
    side = json.loads(Path(out).with_suffix(".json").read_text(encoding="utf-8")) if out else {}
    check("D2 sidecar", side,
          {"backend": "Cloud", "backend_type": "fake",
           "routing": {"occasion": "event", "position": 2, "spec": "Cloud"},
           "fallback_from": {"occasion": "event", "intended_spec": "Gw", "position": 1}})
    check("D2 background slotted",
          cloud.calls[0]["params"].get("reference_images", {})
          .get("input_reference_image_1", "").endswith("bg.png") if cloud.calls else False,
          True)

    bg = gdir / "bg.png"
    state = {"location": loc, "room": "", "label": "Harbour", "mode": "only_background",
             "setting": "harbour", "conditions": "", "bg_path": bg, "chars": [],
             "event_text": "", "sig": "state-d3"}
    scene_render.build_scene_state = lambda avatar: dict(state)
    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"scene_view": ["Gw", "Cloud"]})
    want_sig = scene_render._scene_sig("state-d3")
    res = scene_render.render_scene("demo", force=True)
    check("D3 rendered", (res.get("ok"), res.get("cached"), res.get("sig")),
          (True, False, want_sig))
    try:
        meta = json.loads(scene_render._scene_meta_path(want_sig).read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    check("D3 scene sidecar", (meta.get("location"), meta.get("room"), meta.get("backend"),
                               (meta.get("routing") or {}).get("position"),
                               (meta.get("fallback_from") or {}).get("intended_spec")),
          (loc, "", "Cloud", 2, "Gw"))
    check("D3 background slotted on Cloud",
          cloud.calls[0]["params"].get("reference_images") if cloud.calls else None,
          {"input_reference_image_1": str(bg)})
    check("D3 recomposed for Cloud", bool(gw.calls) and bool(cloud.calls)
          and gw.calls[0]["prompt"] != cloud.calls[0]["prompt"], True)
    res = scene_render.render_scene("demo")
    check("D3 cached under the same sig", (res.get("cached"), res.get("sig")),
          (True, want_sig))
    check("D3 nobody asked again", (len(gw.calls), len(cloud.calls)), (1, 1))

    gw = FakeBackend("Gw", 0, "natural")
    gw.mark_unhealthy("smoke", 300)
    cloud = FakeBackend("Cloud", 5, "keywords")
    install_pool(gw, cloud)
    set_routing({"event": ["Gw"]})
    check("D4 nothing usable -> None",
          event_images._do_generate("ev-smoke-2", loc, "fog", False), None)
    check("D4 nobody asked", (len(gw.calls), len(cloud.calls)), (0, 0))


def part_e():
    print("E) regenerate + scene photo")
    from app.models.character import (get_character_images_dir, get_single_image_meta,
                                      save_character_profile)
    from app.skills import image_regenerate
    from app.skills.image_regenerate import regenerate_image
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    img_dir = get_character_images_dir("Mara")
    img_dir.mkdir(parents=True, exist_ok=True)
    src = img_dir / "Mara_1_a.png"
    src.write_bytes(png_bytes())

    gw, cloud = FakeBackend("Gw", 0, "natural", dead=True), FakeBackend("Cloud", 5, "keywords")
    svc = install_pool(gw, cloud)
    svc._generate_image_analysis = lambda *a, **k: None
    set_routing({"regenerate": ["Gw", "Cloud"], "photo": ["Cloud"]})
    ok, _p, new_path = regenerate_image("Mara", str(src), "a portrait", create_new=True)
    meta = get_single_image_meta("Mara", Path(new_path).name)
    check("E1 new file", (ok, Path(new_path).name != src.name), (True, True))
    check("E1 meta", (meta.get("backend"), (meta.get("routing") or {}).get("position"),
                      (meta.get("fallback_from") or {}).get("intended_spec")),
          ("Cloud", 2, "Gw"))
    try:
        regenerate_image("Mara", str(src), "a portrait", backend_name="Gw", create_new=True)
        check("E2 explicit dead", "no exception", "RuntimeError")
    except RuntimeError:
        check("E2 explicit dead", True, True)
    check("E2 Cloud not asked again", len(cloud.calls), 1)
    ok, _p, p3 = regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                                  create_new=True)
    m3 = get_single_image_meta("Mara", Path(p3).name)
    check("E3 explicit: no marker",
          (ok, m3.get("backend"), m3.get("routing"), m3.get("fallback_from")),
          (True, "Cloud", None, None))
    set_routing({"photo": ["Cloud"]})
    ok, _p, p4 = regenerate_image("Mara", str(src), "a photo", create_new=True,
                                  occasion="photo")
    check("E4 occasion photo", get_single_image_meta("Mara", Path(p4).name).get("routing"),
          {"occasion": "photo", "position": 1, "spec": "Cloud"})

    from app.core.lora_library import LoraNotAllowedError
    n_cloud = len(cloud.calls)
    try:
        regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                         loras=[{"name": "foreign.safetensors", "strength": 1.0}],
                         create_new=True)
        check("E7 foreign LoRA refused", "no exception", "LoraNotAllowedError")
    except LoraNotAllowedError:
        check("E7 foreign LoRA refused", True, True)
    check("E7 no backend called", len(cloud.calls) - n_cloud, 0)

    from app.models.character import add_character_image_metadata
    add_character_image_metadata("Mara", src.name, {"source_file": "older.png"})
    ok, _p, p8 = regenerate_image("Mara", str(src), "a portrait", backend_name="Cloud",
                                  create_new=True)
    m8 = get_single_image_meta("Mara", Path(p8).name)
    check("E8 no inherited source_file", (ok, "source_file" in m8, m8.get("variant_of")),
          (True, False, src.name))

    from app.core import scene_photo
    calls = []

    def _recorder(**kw):
        calls.append((kw.get("backend_name"), kw.get("occasion")))
        return (False, "", "")
    _orig_prep, _orig_regen = scene_photo.prepare_scene_photo, image_regenerate.regenerate_image
    scene_photo.prepare_scene_photo = lambda avatar: {
        "ok": True, "prompt": "Candid photograph", "subjects": ["Mara"],
        "present": ["Mara"], "location": "", "room": "", "default_backend": "Cloud"}
    image_regenerate.regenerate_image = _recorder
    try:
        scene_photo.take_scene_photo("Mara")
        check("E5 one-click photo is routed", calls, [("", "photo")])
        calls.clear()
        scene_photo.take_scene_photo("Mara", backend_name="Gw")
        check("E6 a picked backend stays explicit", calls, [("Gw", "photo")])

        def _refuse(**kw):
            raise LoraNotAllowedError("Cloud", ["foreign.safetensors"])
        image_regenerate.regenerate_image = _refuse
        try:
            got = scene_photo.take_scene_photo("Mara", backend_name="Cloud")
            check("E9 LoRA refusal propagates", got, "LoraNotAllowedError")
        except LoraNotAllowedError:
            check("E9 LoRA refusal propagates", True, True)
    finally:
        scene_photo.prepare_scene_photo = _orig_prep
        image_regenerate.regenerate_image = _orig_regen


class FakeMedia(FakeBackend):
    """A video / mesh backend of the fake pool (plan Task 16): MEDIA_TYPE
    and category set, ``mesh_rig`` for a mesh backend."""

    def __init__(self, name, cost, media, rig="", dead=False):
        super().__init__(name, cost, "", dead=dead)
        self.MEDIA_TYPE = media
        self.category = "img2mesh" if media == "mesh" else "txt2img"
        if rig:
            self.mesh_rig = rig

    def generate(self, prompt, negative_prompt, params, log_meta=None):
        self.calls.append({"params": dict(params)})
        if self.dead:
            raise RuntimeError(f"{self.name}: HTTP 500: gone")
        self.last_result_files = [{"name": f"{self.name}.glb"}]
        return [b"mp4-or-glb"]


class _InlineThread:
    """Stands in for threading.Thread: start() runs the target right away."""

    def __init__(self, target=None, daemon=None, args=(), kwargs=None, **_kw):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


def part_f_video():
    print("F) video")
    from fastapi import HTTPException
    from app.core.lora_library import LoraNotAllowedError
    tmp = Path(_TMP)
    (tmp / "still.png").write_bytes(png_bytes())

    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VDead", "VOk"]})
    ro = {}
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v.mp4"), route_out=ro)
    check("F-V1 routed video", (ok, ro), (True, {
        "backend": "VOk",
        "routing": {"occasion": "video", "position": 2, "spec": "VOk"},
        "fallback_from": {"occasion": "video", "intended_spec": "VDead", "position": 1}}))
    check("F-V1 file written", (tmp / "v.mp4").read_bytes(), b"mp4-or-glb")
    check("F-V2 explicit dead", svc.generate_video(str(tmp / "still.png"), "wave",
                                                   str(tmp / "v2.mp4"), backend_glob="VDead"),
          False)
    check("F-V2 VOk not asked again", len(vo.calls), 1)
    ro = {}
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v3.mp4"),
                            backend_glob="VOk", route_out=ro)
    check("F-V3 explicit: no routing meta", (ok, ro), (True, {"backend": "VOk"}))

    foreign = [{"name": "foreign.safetensors", "strength": 1.0}]
    set_routing({"video": ["VOk"]})
    ok = svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v4.mp4"),
                            loras=foreign)
    check("F-V4 routed: LoRA filtered", (ok, "lora_inputs" in vo.calls[-1]["params"]),
          (True, False))
    n = len(vo.calls)
    try:
        svc.generate_video(str(tmp / "still.png"), "wave", str(tmp / "v5.mp4"),
                           backend_glob="VOk", loras=foreign)
        check("F-V4 explicit: LoRA refused", "no exception", "LoraNotAllowedError")
    except LoraNotAllowedError:
        check("F-V4 explicit: LoRA refused", True, True)
    check("F-V4 explicit: nothing rendered", len(vo.calls) - n, 0)

    # -- F-V5/F-V6: the video skill -------------------------------------
    from app.models.character import (get_character_image_metadata,
                                      get_character_images_dir, get_single_image_meta,
                                      remove_image_animation, save_character_profile,
                                      save_character_skill_config)
    from app.skills.video_generation_skill import VideoGenerationSkill
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    skill = VideoGenerationSkill({})
    check("F-V5 no config fields", (skill.get_config_fields(),
                                    "animate_service" in skill._defaults), ({}, False))
    save_character_skill_config("Mara", "video_generation", {"animate_service": "VDead"})
    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VOk"]})
    img_dir = get_character_images_dir("Mara")
    img_dir.mkdir(parents=True, exist_ok=True)
    still = "Mara_2_still.png"
    (img_dir / still).write_bytes(png_bytes())
    svc.generate_from_input = lambda raw: (
        f"![Generated Image 1](/characters/Mara/images/{still}?user_id=u)")
    reply = skill.execute(json.dumps({"prompt": "a portrait", "action_prompt": "she waves",
                                      "agent_name": "Mara", "user_id": "u"}))
    meta = get_single_image_meta("Mara", still)
    check("F-V5 video link", "Mara_2_still.mp4" in reply, True)
    check("F-V5 stored animate_service ignored", len(vd.calls), 0)
    check("F-V5 image meta", (meta.get("animate_backend"), meta.get("animate_routing"),
                              meta.get("animate_fallback_from"), "animate_service" in meta),
          ("VOk", {"occasion": "video", "position": 1, "spec": "VOk"}, None, False))
    listed = get_character_image_metadata("Mara").get(still, {})
    check("F-V6 whitelist", (listed.get("animate_backend"),
                             (listed.get("animate_routing") or {}).get("occasion"),
                             "animate_fallback_from" in listed, "routing" in listed),
          ("VOk", "video", True, False))

    # -- F-V7/F-V8: Instagram animate -----------------------------------
    import threading as _threading
    from app.models.instagram import create_post, get_instagram_dir, load_image_meta
    from app.routes import instagram as ig_routes
    ig_dir = get_instagram_dir()
    ig_dir.mkdir(parents=True, exist_ok=True)
    (ig_dir / "ig_1.png").write_bytes(png_bytes())
    post = create_post("Mara", "ig_1.png", "a caption", image_prompt="a beach")
    vd, vo = FakeMedia("VDead", 0, "video", dead=True), FakeMedia("VOk", 3, "video")
    svc = install_pool(vd, vo)
    set_routing({"video": ["VDead", "VOk"]})
    _orig_thread = _threading.Thread
    _threading.Thread = _InlineThread
    try:
        ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves"})
        m = load_image_meta("ig_1.png") or {}
        check("F-V7 routed", ((ig_dir / "ig_1.mp4").exists(), m.get("animate_backend"),
                              (m.get("animate_routing") or {}).get("position"),
                              (m.get("animate_fallback_from") or {}).get("intended_spec")),
              (True, "VOk", 2, "VDead"))
        ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves",
                                                            "service": "VOk"})
        m = load_image_meta("ig_1.png") or {}
        check("F-V7 explicit: old marks dropped",
              (m.get("animate_backend"), m.get("animate_routing"),
               m.get("animate_fallback_from")), ("VOk", None, None))
        n = len(vo.calls)
        try:
            ig_routes._animate_instagram_post_sync(post["id"], {"prompt": "waves",
                                                                "service": "VDead"})
            check("F-V7 explicit dead", "no exception", 503)
        except HTTPException as e:
            check("F-V7 explicit dead", e.status_code, 503)
        try:
            ig_routes._animate_instagram_post_sync(post["id"], {
                "prompt": "waves", "service": "VOk",
                "loras": [{"name": "foreign.safetensors", "strength": 1.0}]})
            check("F-V7 explicit foreign LoRA", "no exception", 400)
        except HTTPException as e:
            check("F-V7 explicit foreign LoRA", e.status_code, 400)
        check("F-V7 nothing rendered by the refusals", len(vo.calls) - n, 0)
    finally:
        _threading.Thread = _orig_thread

    ig_routes.delete_instagram_animation(post["id"])
    m = load_image_meta("ig_1.png") or {}
    check("F-V8 instagram scrub", sorted(k for k in m if k.startswith("animate_")), [])
    remove_image_animation("Mara", still)
    m = get_single_image_meta("Mara", still)
    check("F-V8 gallery scrub", sorted(k for k in m if k.startswith("animate_")), [])


if __name__ == "__main__":
    part_a()
    part_c(*part_b())
    part_p()
    part_d()
    part_e()
    part_f_video()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
