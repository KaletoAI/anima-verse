#!/usr/bin/env python3
"""Smoke: the clip-inbox upload never damages an inbox file it does not
finish replacing, and refuses an oversized request before parsing it
(review 04#9).

The route is called with a real multipart ``starlette`` Request (no server);
the inbox and both libraries are temporary (ANIMATION_CLIPS_INBOX_DIR,
ANIMATION_CLIPS_DIR, ANIMATION_CLIPS_LICENSED_DIR, ANIMATION_RIG_FILE).
``assets.MAX_UPLOAD_BYTES`` is lowered to CAP = 1000 bytes for the run.

Usage: ./.venv/bin/python scripts/smoke_clips_inbox_upload.py

[1] ``walk.fbx`` = b"original" (8 bytes) lies in the inbox — say a scene
    source a pair sidecar names. An upload of a different ``walk.fbx`` of
    1500 bytes (> CAP; the request is below CAP + 1 MiB of framing slack, so
    the Content-Length guard lets it through and the STREAMING cap decides)
    → 413, and ``walk.fbx`` still holds b"original". The old handler opened
    the inbox file with "wb" (truncated it) before the check and unlinked it
    on 413 — the source was gone.
[2] an upload of ``walk.fbx`` with 600 bytes (≤ CAP) → 200, stored
    ``[{name: walk.fbx, size: 600}]``, the file holds the 600 new bytes and
    is 0644.
[3] no stage file (``.walk.fbx.*.tmp``) is left in the inbox after [1]/[2].
[4] a request declaring Content-Length CAP + 1 MiB + 1 → 413 before the
    body is read (the receive callable is never awaited). The old handler had
    no ``guard_content_length``.
[5] a request with no ``files`` part → 400.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="clips-inbox-upload-"))
INBOX = TMP / "inbox"
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "free")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(TMP / "licensed")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app.routes import assets  # noqa: E402

CAP = 1000
FAIL = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def multipart(parts, declared=None):
    """A POST Request with a multipart body of ``parts`` = [(field, filename, bytes)];
    ``declared`` overrides the Content-Length header. ``read`` records whether
    the body was ever pulled."""
    boundary = b"smokeboundary"
    body = b""
    for field, filename, data in parts:
        body += (b"--" + boundary + b"\r\nContent-Disposition: form-data; name=\"" + field.encode()
                 + b"\"; filename=\"" + filename.encode() + b"\"\r\n"
                 b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n")
    body += b"--" + boundary + b"--\r\n"
    read = []

    async def receive():
        read.append(True)
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", b"multipart/form-data; boundary=" + boundary),
               (b"content-length", str(declared if declared is not None else len(body)).encode())]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers}, receive), read


def call(request):
    try:
        return 200, asyncio.run(assets.post_clips_inbox_upload(request, None))
    except HTTPException as e:
        return e.status_code, e.detail


def main():
    INBOX.mkdir(parents=True)
    (INBOX / "walk.fbx").write_bytes(b"original")
    assets.MAX_UPLOAD_BYTES = CAP

    code, _detail = call(multipart([("files", "walk.fbx", b"x" * 1500)])[0])
    check("[1] a file past the cap is refused with 413", code == 413, str(code))
    check("[1] the inbox file of that name is untouched",
          (INBOX / "walk.fbx").read_bytes() == b"original", repr((INBOX / "walk.fbx").read_bytes()[:20]))

    code, answer = call(multipart([("files", "walk.fbx", b"y" * 600)])[0])
    check("[2] a file within the cap is stored", code == 200
          and answer.get("stored") == [{"name": "walk.fbx", "size": 600}], f"{code} {answer}")
    check("[2] it replaced the inbox file, readable 0644",
          (INBOX / "walk.fbx").read_bytes() == b"y" * 600
          and (INBOX / "walk.fbx").stat().st_mode & 0o777 == 0o644)
    check("[3] no stage file is left", sorted(p.name for p in INBOX.iterdir()) == ["walk.fbx"],
          str(sorted(p.name for p in INBOX.iterdir())))

    request, read = multipart([("files", "run.fbx", b"z" * 10)], declared=CAP + 1024 * 1024 + 1)
    code, _detail = call(request)
    check("[4] an oversized declared length is refused before the body is read",
          code == 413 and not read and not (INBOX / "run.fbx").exists(), f"{code} read={read}")

    code, _detail = call(multipart([])[0])
    check("[5] no file part → 400", code == 400, str(code))

    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
