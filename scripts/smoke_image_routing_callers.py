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

PART B — location family (occasion "location"), end to end through the
REAL routing on a fake pool: "Gw" (family natural, cost 0) fails with
HTTP 500, "Cloud" (family keywords, cost 5) renders; both have one
reference slot. `run_on_backend_channel` runs the job inline.
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
"""
import asyncio
import io
import json
import os
import sys
import tempfile
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

    def check_availability(self):
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
    from app.models import world
    loc = world.add_location("Mill", "A mill by the river.")["id"]

    def gallery(data):
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


if __name__ == "__main__":
    part_a()
    part_b()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
