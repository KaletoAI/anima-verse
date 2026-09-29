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
"""
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


if __name__ == "__main__":
    part_a()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
