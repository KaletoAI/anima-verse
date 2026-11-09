#!/usr/bin/env python3
"""Image tiles of the character tabs get the model and the creation time.

User feedback 2026-11-09: every image of the Base body / Pose / Hair tabs
shows when it was made and "<model> · <W>×<H>". The server supplies model and
time from the image's sidecar JSON (``<image>.json``); the size is read off
the bitmap in the browser. Expected values, derived by hand from that rule:

[1] ``model_refs.image_tile_meta``:
    a) sidecar ``{"model": "Qwen2.1-Turbo", "service": "Qwen2.1 Turbo",
       "created_at": "2026-11-09T10:00:00+00:00"}`` → exactly
       ``{"model": "Qwen2.1-Turbo", "created_at": "2026-11-09T10:00:00+00:00"}``
       (``model`` wins over ``service``);
    b) sidecar ``{"service": "Flux Dev"}``, file mtime set to 365 days after
       the epoch → ``{"model": "Flux Dev",
       "created_at": "1971-01-01T00:00:00+00:00"}`` (1970 has 365 days);
    c) no sidecar, same mtime → ``{"created_at": "1971-01-01T00:00:00+00:00"}``
       (no ``model`` key — an old render shows the size alone);
    d) ``None`` → ``{}``.
[2] ``model_refs._ref_info`` (model-refs payload ``info``) of a): keeps
    ``filename`` / ``prompt`` / ``backend`` (= the sidecar's ``service``) and
    adds ``model`` "Qwen2.1-Turbo"; of c): ``created_at`` is the mtime stamp,
    ``backend`` "" and no ``model``.
[3] ``garments._image_info`` (garment_info image steps), with the final and
    attempt 1 on disk (sidecars as in a) and b)) and attempt 2 absent: the
    final carries model "Qwen2.1-Turbo" and its created_at; the one attempt
    entry carries model "Flux Dev" and "1971-01-01T00:00:00+00:00"; a step
    with no final on disk carries neither key.
[4] ``base_body.base_info`` (stubbed character: humanoid, signature
    ``base0000abcd``, front stored as in a), the other views missing):
    ``image_meta["front"]`` == the dict of [1a], ``image_meta[v]`` is None for
    back/left/right, and ``images`` still holds the URL / None per view.

Usage: ./.venv/bin/python scripts/smoke_image_tile_meta.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_failures = []

YEAR_1971 = 365 * 86400
STAMP_1971 = "1971-01-01T00:00:00+00:00"
A_SIDECAR = {"model": "Qwen2.1-Turbo", "service": "Qwen2.1 Turbo",
             "created_at": "2026-11-09T10:00:00+00:00", "prompt": "p"}
A_META = {"model": "Qwen2.1-Turbo", "created_at": "2026-11-09T10:00:00+00:00"}


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        _failures.append(label)


def write(path: Path, sidecar=None, old=False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    if sidecar is not None:
        path.with_suffix(".json").write_text(json.dumps(sidecar), encoding="utf-8")
    if old:
        os.utime(path, (YEAR_1971, YEAR_1971))
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_image_tile_meta_"))
    from app.core import paths
    paths.init(str(tmp))
    from app.core import base_body, garments, model_refs

    files = tmp / "files"
    a = write(files / "a.png", A_SIDECAR)
    b = write(files / "b.png", {"service": "Flux Dev"}, old=True)
    c = write(files / "c.png", None, old=True)

    check("[1a] model wins over service", model_refs.image_tile_meta(a), A_META)
    check("[1b] service, mtime", model_refs.image_tile_meta(b), {"model": "Flux Dev", "created_at": STAMP_1971})
    check("[1c] no sidecar", model_refs.image_tile_meta(c), {"created_at": STAMP_1971})
    check("[1d] None", model_refs.image_tile_meta(None), {})

    ra = model_refs._ref_info(a)
    check("[2] ref info a", {k: ra.get(k) for k in ("filename", "prompt", "backend", "model", "created_at")},
          {"filename": "a.png", "prompt": "p", "backend": "Qwen2.1 Turbo", "model": "Qwen2.1-Turbo",
           "created_at": "2026-11-09T10:00:00+00:00"})
    rc = model_refs._ref_info(c)
    check("[2] ref info c", (rc.get("created_at"), rc.get("backend"), "model" in rc), (STAMP_1971, "", False))

    gdir = tmp / "garment"
    write(gdir / "haired_front.png", {**A_SIDECAR, "accepted": True, "attempt": 1})
    write(gdir / "haired_front.try1.png", {"service": "Flux Dev", "gate": {"ok": True}}, old=True)

    def fake_image(character_name, item_id, fsig, step, view, attempt=0):
        return gdir / (f"{step}_{view}.try{attempt}.png" if attempt else f"{step}_{view}.png")

    garments._image = fake_image
    fin = garments._image_info("Demo", "item_hair", "f" * 12, "haired", "front")
    check("[3] final model/time", (fin.get("model"), fin.get("created_at")),
          ("Qwen2.1-Turbo", "2026-11-09T10:00:00+00:00"))
    atts = fin.get("attempts") or []
    check("[3] one attempt with meta", [(x.get("attempt"), x.get("model"), x.get("created_at")) for x in atts],
          [(1, "Flux Dev", STAMP_1971)])
    empty = garments._image_info("Demo", "item_hair", "f" * 12, "ghost", "front")
    check("[3] missing final carries neither", ("model" in empty, "created_at" in empty, empty.get("url")),
          (False, False, None))

    front = write(tmp / "base" / "tpose_base0000abcd.png", A_SIDECAR)
    model_refs.is_humanoid = lambda *a, **k: True
    model_refs.find_ref_image = lambda name, kind, sig=None: front if kind == "tpose" else None
    base_body._profile_of = lambda name, profile: {}
    base_body.base_signature = lambda name, profile=None: "base0000abcd"
    base_body.is_base_pipeline = lambda name, profile=None: False
    base_body.base_status = lambda name: {}
    base_body.base_model_info = lambda name, sig=None: None
    info = base_body.base_info("Demo")
    check("[4] image_meta front", info["image_meta"]["front"], A_META)
    check("[4] image_meta others None", [info["image_meta"][v] for v in ("back", "left", "right")],
          [None, None, None])
    check("[4] images front url / others None",
          (bool(info["images"]["front"]), [info["images"][v] for v in ("back", "left", "right")]),
          (True, [None, None, None]))

    print(f"\n{'OK' if not _failures else f'{len(_failures)} FAILED'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
