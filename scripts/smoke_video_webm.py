#!/usr/bin/env python3
"""Task 114: WebM (VP9) companions of gallery MP4 videos, temporary storage.

Usage: ./.venv/bin/python scripts/smoke_video_webm.py   (needs ffmpeg/ffprobe)

Hand oracle, nothing here records current output:
* A 64x48, 10 fps, 1 s test clip is generated with ffmpeg ``testsrc`` (no
  audio). Its companion must be probed as codec vp9, container webm, 64x48.
* Companion path is ``<dir>/.video-webm/<stem>.webm``; the hidden dir is not
  listed by get_character_images.
* Single flight: 4 concurrent ensure_webm calls on a missing companion run
  exactly ONE ffmpeg encode (the encoder is wrapped with a counter + delay).
* Route: GET .../images/<clip>.mp4/webm answers exactly like the MP4 route for
  anonymous (401) / user (200) / admin (200); ETag gives 304; a Range request
  answers 206; an unknown clip is 404; a png is 404.
* Deleting the animation removes the companion; an orphan companion is swept;
  a character export zip contains the mp4 but no ".video-webm" entry.
* The publisher hook (schedule_webm) creates the companion in the background.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    print("SKIP: ffmpeg/ffprobe not available")
    sys.exit(0)

_tmp = tempfile.mkdtemp(prefix="task114-webm-")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp
from app.core import paths
paths.init(_tmp)
paths.init_instance(_tmp)
from app.core import config, db
config.load(Path(_tmp) / "config.json")
db.init_schema()

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.core import auth_dependency, video_webm
from app.models.character import (get_character_images, get_character_images_dir,
                                  save_character_profile, remove_image_animation)
from app.routes import characters as characters_route, instagram as instagram_route

FAILS = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILS.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")


auth_dependency._get_session_user = lambda request: {
    "user": {"id": "u1", "username": "demo", "role": "user", "allowed_characters": ["Mara"]},
    "admin": {"id": "u2", "username": "demo", "role": "admin", "allowed_characters": []},
}.get(request.headers.get("x-test-user", ""))
app = FastAPI()
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.middleware("http")(auth_dependency.user_context_middleware)
app.include_router(characters_route.router)
app.include_router(instagram_route.router)
client = TestClient(app)


def get(path, role="", **headers):
    if role:
        headers["x-test-user"] = role
    return client.get(path, headers=headers)


def make_clip(path: Path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x48:rate=10:duration=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def probe(path: Path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height:format=format_name", "-of",
                          "default=nw=1", str(path)], capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.split())


save_character_profile("Ann", {"name": "Ann", "language": "en"}, create_new=True)
images = get_character_images_dir("Ann")
(images / "a_1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
clip = images / "a_1.mp4"
make_clip(clip)

print("A) companion path + hidden dir")
check("path", video_webm.companion_path(clip), (images / ".video-webm" / "a_1.webm").resolve())
try:
    video_webm.companion_path(images / "a_1.png")
    check("png refused", "no error", "ValueError")
except ValueError:
    check("png refused", "ValueError", "ValueError")
check("gallery list ignores hidden dir", get_character_images("Ann"), ["a_1.png"])

print("B) single flight: 4 concurrent calls -> 1 encode")
real_encode = video_webm._encode
calls = []


def slow_encode(video, target):
    calls.append(video.name)
    time.sleep(0.5)
    return real_encode(video, target)


results = []
with patch.object(video_webm, "_encode", slow_encode):
    threads = [threading.Thread(target=lambda: results.append(video_webm.ensure_webm(clip, wait=60)))
               for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
check("encode runs", len(calls), 1)
webm = images / ".video-webm" / "a_1.webm"
check("all callers got the file", sorted(str(r) for r in results), [str(webm.resolve())] * 4)
info = probe(webm)
check("codec", info.get("codec_name"), "vp9")
check("size", (info.get("width"), info.get("height")), ("64", "48"))
check("container", "webm" in info.get("format_name", ""), True)
check("fresh companion not re-encoded", (video_webm.ensure_webm(clip), len(calls)), (webm.resolve(), 1))

print("C) route auth parity + ETag + Range")
mp4_url = "/characters/Ann/images/a_1.mp4"
for role in ("", "user", "admin"):
    check(f"role {role or 'anon'} parity", get(mp4_url + "/webm", role).status_code,
          get(mp4_url, role).status_code)
check("anon 401", get(mp4_url + "/webm").status_code, 401)
r = get(mp4_url + "/webm", "user")
check("200 + webm type", (r.status_code, r.headers["content-type"]), (200, "video/webm"))
check("body is the file", r.content == webm.read_bytes(), True)
check("ETag 304", get(mp4_url + "/webm", "user", **{"if-none-match": r.headers["etag"]}).status_code, 304)
r = get(mp4_url + "/webm", "user", range="bytes=0-9")
check("Range 206", (r.status_code, len(r.content)), (206, 10))
check("unknown clip 404", get("/characters/Ann/images/nope.mp4/webm", "user").status_code, 404)
check("png 404", get("/characters/Ann/images/a_1.png/webm", "user").status_code, 404)
check("traversal refused", get("/characters/Ann/images/..%2Fx.mp4/webm", "user").status_code in (400, 404), True)

print("D) lazy creation on first request")
shutil.rmtree(images / ".video-webm")
r = get(mp4_url + "/webm", "user")
check("lazy 200", r.status_code, 200)
check("created", webm.is_file(), True)

print("E) publisher hook creates it in the background")
clip2 = images / "a_2.mp4"
make_clip(clip2)
video_webm.schedule_webm(clip2)
deadline = time.time() + 60
while time.time() < deadline and not (images / ".video-webm" / "a_2.webm").is_file():
    time.sleep(0.2)
check("background companion", (images / ".video-webm" / "a_2.webm").is_file(), True)

print("F) Instagram route")
from app.models.instagram import get_instagram_dir, _remove_post_media
igdir = get_instagram_dir()
make_clip(igdir / "p1.mp4")
r = get("/instagram/images/p1.mp4/webm", "user")
check("instagram 200", (r.status_code, r.headers.get("content-type")), (200, "video/webm"))
check("instagram anon 401", get("/instagram/images/p1.mp4/webm").status_code, 401)
check("instagram unknown 404", get("/instagram/images/zz.mp4/webm", "user").status_code, 404)
_remove_post_media("p1.png")
check("post media removal drops companion", (igdir / ".video-webm" / "p1.webm").exists(), False)

print("G) export skips it")
from app.core import character_io
data = character_io.export_character_to_zip("Ann")
names = zipfile.ZipFile(io.BytesIO(data)).namelist()
check("mp4 exported", any(n.endswith("images/a_1.mp4") for n in names), True)
check("no companion exported", any(".video-webm" in n for n in names), False)

print("H) delete + orphan sweep")
check("delete animation", remove_image_animation("Ann", "a_1.png"), "a_1.mp4")
check("companion gone", webm.exists(), False)
(images / ".video-webm" / "orphan.webm").write_bytes(b"x")
check("sweep removes orphan, keeps owned", (video_webm.sweep_all_orphans() >= 1,
      (images / ".video-webm" / "orphan.webm").exists(),
      (images / ".video-webm" / "a_2.webm").exists()), (True, False, True))

print("I) ffmpeg missing -> None, no crash")
with patch("shutil.which", return_value=None):
    (images / ".video-webm" / "a_2.webm").unlink()
    check("no ffmpeg", video_webm.ensure_webm(clip2), None)

if FAILS:
    print("\nFAILED:\n" + "\n".join(FAILS))
    sys.exit(1)
print("\nall ok")
