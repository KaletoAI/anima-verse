#!/usr/bin/env python3
"""Smoke: "Generate video" of the Game-Admin character gallery.

Usage:  ./.venv/bin/python scripts/smoke_gallery_animate.py

Route POST /characters/{name}/images/{file}/animate ->
``character_ops.start_gallery_animation``. Throwaway storage + world DB
(``paths.init`` before any world-DB import), no server; the task queue, the
thread start and ``run_video_op`` are stubbed, so nothing renders.

Expected values, derived by hand from the route contract:

A) Refusals happen BEFORE a track or a thread exists (track_start and
   Thread are never called):
   A1 media switch off -> MediaGenerationDisabled (the server maps it to 409)
   A2 image names "../x.png", "sub/x.png", ".hidden.png", "still.txt", ""
      -> 400 each; "missing.png" -> 404
   A3 prompt "  " -> 422
   A4 explicit service "VidX", require_explicit_backend raises 503 -> 503
   A5 explicit service "VidL", assert_loras_allowed raises
      LoraNotAllowedError -> 400
B) Auto, body {prompt " wave ", loras [{m, "0.5"}, {"None"}, {""}],
   seconds "3"} on still.png of Mara -> answer {status "started", image
   "still.png", video "still.mp4", track_id "t1"}; ONE track_start of type
   "image_animate"; run_video_op once with kind "video_character", subject
   "video:character:Mara:still.mp4" and inputs prompt "wave", service "",
   loras [{m, 0.5}], seconds 3, image_filename "still.png", video_filename
   "still.mp4", source = the still's resolved path; track_finish(t1, error "").
   require_explicit_backend is not called (Auto).
C) Explicit "VidL", loras [{m, "x"}], seconds "" -> require_explicit_backend
   called with ("VidL", media="video"), inputs service "VidL", loras
   [{m, 1.0}], seconds None.
D) The video lands where the gallery finds it: the REAL publisher of
   "video_character" with a fake op writes images/still.mp4 (the rendered
   bytes) and animate_prompt "wave" / animate_backend "VidL" on still.png's
   meta; GET /characters/Mara/images then answers image_videos
   {"still.png": "still.mp4"} (keyed by the FULL image name).
E) Both new routes depend on require_admin.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="gallery-animate-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from fastapi import HTTPException  # noqa: E402
from app.core import db  # noqa: E402
db.init_schema()
from app.core import character_ops  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.imagegen import base as imagegen_base  # noqa: E402
from app.models.character import get_character_dir, get_character_images_dir  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class InlineThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def outcome(fn):
    try:
        return fn()
    except HTTPException as e:
        return e.status_code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


get_character_dir("Mara", create=True)
images = get_character_images_dir("Mara")
images.mkdir(parents=True, exist_ok=True)
(images / "still.png").write_bytes(b"png")
(images / "still.txt").write_bytes(b"txt")
(images / ".hidden.png").write_bytes(b"png")
STILL = (images / "still.png").resolve()

queue = MagicMock()
queue.track_start.return_value = "t1"
video_op = MagicMock(return_value={"ok": True})
patches = [
    patch("app.core.task_queue.get_task_queue", return_value=queue),
    patch("app.skills.animate.run_video_op", video_op),
    patch("threading.Thread", side_effect=InlineThread),
]
for p in patches:
    p.start()
thread_cls = __import__("threading").Thread


def start(name, body):
    return character_ops.start_gallery_animation("Mara", name, body)


def nothing_started(label):
    check(f"{label}: no track, no thread",
          (queue.track_start.call_count, thread_cls.call_count, video_op.call_count), (0, 0, 0))


try:
    print("A) refusals before anything starts")
    with patch.object(imagegen_base, "media_generation_enabled", return_value=False):
        check("A1 media switch off", outcome(lambda: start("still.png", {"prompt": "wave"})),
              "MediaGenerationDisabled")
    nothing_started("A1")
    check("A2 bad names", [outcome(lambda n=n: start(n, {"prompt": "wave"}))
                           for n in ("../x.png", "sub/x.png", ".hidden.png", "still.txt", "",
                                     "missing.png")],
          [400, 400, 400, 400, 400, 404])
    check("A3 empty prompt", outcome(lambda: start("still.png", {"prompt": "  "})), 422)
    with patch("app.core.explicit_backend.require_explicit_backend",
               side_effect=HTTPException(503, "gone")):
        check("A4 dead explicit pick",
              outcome(lambda: start("still.png", {"prompt": "wave", "service": "VidX"})), 503)
    from app.core.lora_library import LoraNotAllowedError
    with patch("app.core.explicit_backend.require_explicit_backend", return_value=object()), \
         patch("app.core.lora_library.assert_loras_allowed",
               side_effect=LoraNotAllowedError("VidL", ["m"])):
        check("A5 foreign LoRA", outcome(lambda: start("still.png", {
            "prompt": "wave", "service": "VidL", "loras": [{"name": "m"}]})), 400)
    nothing_started("A2-A5")

    print("B) Auto")
    with patch("app.core.explicit_backend.require_explicit_backend") as require:
        answer = start("still.png", {"prompt": " wave ", "seconds": "3", "loras": [
            {"name": "m", "strength": "0.5"}, {"name": "None"}, {"name": ""}]})
        check("B require not called", require.call_count, 0)
    check("B answer", answer, {"status": "started", "image": "still.png",
                               "video": "still.mp4", "track_id": "t1"})
    check("B one image_animate track",
          [c.args[0] for c in queue.track_start.call_args_list], ["image_animate"])
    args, kwargs = video_op.call_args
    inputs = args[2]
    check("B kind + subject", args[:2], ("video_character", "video:character:Mara:still.mp4"))
    check("B inputs", {k: inputs[k] for k in ("prompt", "service", "loras", "seconds",
                                               "image_filename", "video_filename", "source")},
          {"prompt": "wave", "service": "", "loras": [{"name": "m", "strength": 0.5}],
           "seconds": 3, "image_filename": "still.png", "video_filename": "still.mp4",
           "source": str(STILL)})
    check("B track finished ok", queue.track_finish.call_args.args[0], "t1")
    check("B track error empty", queue.track_finish.call_args.kwargs.get("error"), "")

    print("C) explicit pick")
    video_op.reset_mock()
    with patch("app.core.explicit_backend.require_explicit_backend",
               return_value=object()) as require, \
         patch("app.core.lora_library.assert_loras_allowed") as allowed:
        start("still.png", {"prompt": "wave", "service": "VidL", "seconds": "",
                            "loras": [{"name": "m", "strength": "x"}]})
        check("C require", (require.call_args.args, require.call_args.kwargs),
              (("VidL",), {"media": "video"}))
        check("C LoRAs checked", allowed.call_args.args[1], [{"name": "m", "strength": 1.0}])
    inputs = video_op.call_args.args[2]
    check("C inputs", (inputs["service"], inputs["loras"], inputs["seconds"]),
          ("VidL", [{"name": "m", "strength": 1.0}], None))
finally:
    for p in patches:
        p.stop()

print("D) the video lands in the gallery")
from app.skills import video_generation_skill  # noqa: E402
rendered = Path(TEMP.name) / "out.mp4"
rendered.write_bytes(b"mp4-bytes")
op = MagicMock()
op.inputs = {"character": "Mara", "image_filename": "still.png",
             "video_filename": "still.mp4", "prompt": "wave"}
with patch("app.core.video_webm.schedule_webm"):
    result = video_generation_skill._publish_character_video(op, rendered, {"backend": "VidL"})
check("D publish ok", result, {"ok": True})
check("D bytes next to the still", (images / "still.mp4").read_bytes(), b"mp4-bytes")
from app.models.character import get_single_image_meta  # noqa: E402
meta = get_single_image_meta("Mara", "still.png") or {}
check("D meta", (meta.get("animate_prompt"), meta.get("animate_backend")), ("wave", "VidL"))
from app.routes import characters as characters_routes  # noqa: E402
listing = characters_routes.get_character_images_list("Mara")
check("D image_videos", listing.get("image_videos"), {"still.png": "still.mp4"})

print("E) admin only")
for path in ("/{character_name}/images/{image_name}/animate",
             "/{character_name}/images/{image_name}/suggest-animate-prompt"):
    route = next(r for r in characters_routes.router.routes if getattr(r, "path", "").endswith(path))
    calls = [d.call for d in route.dependant.dependencies]
    check(f"E {path.rsplit('/', 1)[-1]} requires admin", require_admin in calls, True)

TEMP.cleanup()
print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("all checks passed")
