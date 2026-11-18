"""Smoke: the cut-out's upscale under load / with media off is retried, not cached as Lanczos-only (A198, review 05
#5).

Usage:
    ./.venv/bin/python scripts/smoke_cutout_load_and_regenerate.py

No server, no world DB, no hub: the image service is stubbed. By hand:
  [1] upscale raises BackendBusyError        -> it propagates (pre-fix e846d7d02: cached ``lanczos``)
  [2] upscale raises MediaGenerationDisabled -> it propagates
  [3] upscale raises RuntimeError("boom")    -> (None, {status lanczos, reason boom}) — the documented fallback
  [4] upscale answers {bytes, backend: x}    -> (result, {backend: x})
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_images as gi  # noqa: E402
from app.imagegen import base as ibase, service  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


class Svc:
    def __init__(self, exc=None):
        self.exc = exc

    def upscale_image(self, png, character_name=""):
        if self.exc:
            raise self.exc
        return {"bytes": b"PNG", "backend": "x"}


for label, exc, kind in (("[1] busy", ibase.BackendBusyError("busy"), ibase.BackendBusyError),
                         ("[2] media off", ibase.MediaGenerationDisabled("off"), ibase.MediaGenerationDisabled)):
    service.get_image_service = lambda e=exc: Svc(e)
    try:
        got = gi._upscale_cutout(b"x", "Demo", "front")
        check(f"{label} propagates", False, got)
    except kind:
        check(f"{label} propagates", True)
service.get_image_service = lambda: Svc(RuntimeError("boom"))
check("[3] failure -> lanczos", gi._upscale_cutout(b"x", "Demo", "front") == (None, {"status": "lanczos",
                                                                                     "reason": "boom"}))
service.get_image_service = lambda: Svc()
res, rec = gi._upscale_cutout(b"x", "Demo", "front")
check("[4] result", res["bytes"] == b"PNG" and rec == {"backend": "x"}, (res, rec))

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
