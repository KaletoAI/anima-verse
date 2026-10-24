#!/usr/bin/env python3
"""Smoke run: the room reference image of a render shows the ROOM.

Symptom (2026-10-24): a chat photo taken in the inn's private chamber was
right, but "regenerate" from the gallery sent the inn's EXTERIOR night render
as the room reference, while the prompt text still said "setting: <chamber>".
Two readers picked the reference without the room:

  * ``PromptBuilder._collect_location`` named the character's room in the
    text but asked ``get_background_path(location)`` with NO room — so it got
    the untagged location default (here: the exterior).
  * ``regenerate_image`` without a dialog room override fell back to exactly
    that reader, i.e. to the character's CURRENT location — not to the
    location + room stored in the source image's meta.

Expectations derived by hand from ``get_background_path``'s rules (a room
with its own images gets one of them; a room without falls back to the
untagged location images; ``strict_room`` has no fallback) and from the
regenerate contract (``room_id`` = dialog override, strict; else
``location_id`` + ``source_room_id`` from the image meta):

  world:
    Inn     rooms Chamber, Taproom
            inn_default.png  background, untagged   (location default)
            chamber.png      background, tagged Chamber
    Market  market.png       background, untagged
  No image carries a day/night type, so the clock does not matter.

  [1] character in Inn/Chamber, _collect_location   -> chamber.png
      (old code: inn_default.png — the room was not asked)
  [2] character in Inn/Taproom (no own image)        -> inn_default.png
  [3] character moved on to Market; regenerate of an image rendered in
      Inn/Chamber (location_id=Inn, source_room_id=Chamber, no override)
                                                     -> chamber.png
      (old code: market.png — the current location's default)
  [4] same, but the meta names no room               -> inn_default.png
  [5] dialog override room_id=Taproom (strict, Taproom has no own image)
                                                     -> no room reference
  [6] use_room=False                                 -> no room reference

The render itself never runs: a fake image service captures the request
params at ``backend.generate`` and aborts there.

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_room_reference.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="room-ref-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="room-ref-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.imagegen import service as image_service  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (  # noqa: E402
    save_character_current_location, save_character_current_room,
    save_character_profile)

from app.utils import image_prompt_logger  # noqa: E402

# Offline: no embedding model, no worker threads.
embedding.embed = lambda text: None
get_task_queue()._started = True
# The failed fake render is still logged — into the throwaway dir, never
# into the repo's logs/image_prompts.jsonl.
image_prompt_logger.LOG_DIR = STORAGE / "logs"
image_prompt_logger.LOG_FILE = STORAGE / "logs" / "image_prompts.jsonl"

FAILURES = []
CHECKED = 0
CHAR = "Smoke Guest"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class _Captured(Exception):
    """Raised by the fake backend once the request params are captured."""


class _FakeBackend:
    name = "Smoke Fake"
    api_type = "fake"
    model = ""
    image_family = "natural"
    negative_prompt = ""
    ref_slot_count = 3

    def __init__(self):
        self.params = None

    def generate(self, prompt, negative, params, log_meta=None):
        self.params = dict(params)
        raise _Captured()


class _FakeService:
    enabled = True

    def __init__(self):
        self.backend = _FakeBackend()

    def _wait_for_explicit_backend(self, name):
        return self.backend

    def _get_instance_config(self, character_name, backend):
        return {}

    def run_on_backend_channel(self, backend, fn, **_kw):
        return fn()

    def run_on_backend(self, backend, op, character_name=""):
        return op(backend), backend


def room_ref_of_regenerate(**kwargs):
    """File name of the room reference a regenerate would send ('' = none)."""
    fake = _FakeService()
    image_service.get_image_service = lambda: fake
    from app.skills.image_regenerate import regenerate_image
    out = STORAGE / "out.png"
    try:
        regenerate_image(CHAR, str(out), "Two people talk, setting: Chamber",
                         backend_name="Smoke Fake", character_names=[CHAR],
                         **kwargs)
    except _Captured:
        pass
    except Exception as e:  # noqa: BLE001 — reported as the result
        return f"<{type(e).__name__}: {e}>"
    if fake.backend.params is None:
        return "<generate never reached>"
    refs = fake.backend.params.get("reference_images") or {}
    gallery = [Path(v).name for v in refs.values()
               if v and "world_gallery" in str(v)]
    return gallery[0] if gallery else ""


def main() -> int:
    inn = world.add_location("Smoke Inn", "A stone inn.", rooms=[
        {"name": "Chamber", "description": "A quiet chamber."},
        {"name": "Taproom", "description": "Benches and a fire."}])
    market = world.add_location("Smoke Market", "Stalls in a square.")
    inn = next(x for x in world.list_locations() if x.get("name") == "Smoke Inn")
    market = next(x for x in world.list_locations() if x.get("name") == "Smoke Market")
    inn_id, market_id = inn["id"], market["id"]
    rooms = {r.get("name", ""): r.get("id", "") for r in inn.get("rooms") or []}
    chamber, taproom = rooms["Chamber"], rooms["Taproom"]

    def put(loc_id, name, room=""):
        gallery = STORAGE / "world_gallery" / loc_id
        gallery.mkdir(parents=True, exist_ok=True)
        (gallery / name).write_bytes(b"fake png")
        world.toggle_background_image(loc_id, name)
        if room:
            world.set_gallery_image_room(loc_id, name, room)

    put(inn_id, "inn_default.png")
    put(inn_id, "chamber.png", room=chamber)
    put(market_id, "market.png")

    save_character_profile(CHAR, {"character_name": CHAR,
                                  "template": "human-roleplay"}, create_new=True)
    save_character_current_location(CHAR, inn_id)
    save_character_current_room(CHAR, chamber)

    from app.core.prompt_builder import PromptBuilder, PromptVariables

    def collected_room_ref():
        pv = PromptVariables()
        PromptBuilder(CHAR)._collect_location(pv)
        return Path(pv.ref_image_room).name if pv.ref_image_room else ""

    print("\n[1] _collect_location asks the character's room")
    check("Inn/Chamber", collected_room_ref(), "chamber.png")

    print("\n[2] a room without own images falls back to the location default")
    save_character_current_room(CHAR, taproom)
    check("Inn/Taproom", collected_room_ref(), "inn_default.png")

    print("\n[3] regenerate follows the SOURCE image's location + room")
    save_character_current_location(CHAR, market_id)
    save_character_current_room(CHAR, "")
    check("character at Market, image from Inn/Chamber",
          room_ref_of_regenerate(location_id=inn_id, source_room_id=chamber),
          "chamber.png")

    print("\n[4] an image meta without a room -> that location's default")
    check("image from Inn, no room",
          room_ref_of_regenerate(location_id=inn_id), "inn_default.png")

    print("\n[5] a dialog room override stays strict")
    check("override Taproom",
          room_ref_of_regenerate(location_id=inn_id, source_room_id=chamber,
                                 room_id=taproom), "")

    print("\n[6] use_room=False sends no room reference")
    check("use_room off",
          room_ref_of_regenerate(location_id=inn_id, source_room_id=chamber,
                                 use_room=False), "")

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(os.environ["ANIMATION_CLIPS_DIR"], ignore_errors=True)
