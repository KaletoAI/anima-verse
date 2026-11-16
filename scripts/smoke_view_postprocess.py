"""Smoke: the generic post-process of the plain body's full-body REFERENCE (Ruling A146, corrected by A149,
``app/core/view_postprocess.py``).

Usage:
    ./.venv/bin/python scripts/smoke_view_postprocess.py

No server, no world DB: a temp storage dir, stand-in operations registered as contributors of the capability, PNG
files written by hand; the figure matte (BiRefNet in the app) is replaced by a hand-made one.

Expected values, derived by hand:

* The reference: 40 x 20, OPAQUE (alpha 255 everywhere — a picture on a plain background), colour (180, 140, 120)
  everywhere except a 4 x 4 dark disc stand-in at rows 8..11, columns 10..13 = (90, 50, 50). The figure matte
  stand-in is 255 in columns 4..33, else 0 -> 30 x 20 = 600 matte pixels.
* ``stand_in`` turns every pixel inside the matte with R < 100 into (180, 140, 120) and reports how many: it sees
  600 matte pixels (the core handed the matte as alpha), finds 16, the copy has 0 pixels with R < 100 and alpha 255
  everywhere (the picture's own alpha), the original keeps its 16 dark pixels byte for byte.
* No operation on: the original path comes back. Asked again: the same copy, the operation not run again (1 call).
* A reference without a dark pixel: nothing found -> the original path, sidecar ``result_sha256`` None.
* An operation that changes the matte it was handed: ``run`` raises ValueError; ``processed_reference`` falls back
  to the original and records an ``error``.
* Another choice of operations = another copy key; the old copy of that original is dropped (1 png left).
* A146 leftovers: a view processed in place (16 dark pixels removed, original kept in ``postprocessed/``, sidecar
  record) is restored byte for byte and the kept dir removed; a record without a result (nothing was found) is
  only dropped from the sidecar, the bytes unchanged.
* Choices: world default ["stand_in"], character {"stand_in": False} -> on = []; character {} -> ["stand_in"].
* ``full_body_reference.base_source``: without an operation on -> the reference file; with one on -> the copy.
* The front's reason: a front made from the plain reference while the processed one is wanted ->
  ``FRONT_POSTPROCESS_ON``; the other way -> ``FRONT_POSTPROCESS_OFF``; the same record -> "" (current).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke_vpp_"))
os.environ.setdefault("STORAGE_DIR", str(TMP))
from app.core import paths  # noqa: E402
paths.init(str(TMP))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import hooks, view_postprocess as vp  # noqa: E402
from app.core import full_body_reference as fbr  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def png(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def picture(dark: bool = True, opaque: bool = True) -> np.ndarray:
    a = np.zeros((20, 40, 4), np.uint8)
    a[..., :3] = (180, 140, 120)
    if opaque:
        a[..., 3] = 255
    else:
        a[:, 4:34, 3] = 255
    if dark:
        a[8:12, 10:14, :3] = (90, 50, 50)
    return a


def matte(_data, size):
    m = np.zeros((size[1], size[0]), np.uint8)
    m[:, 4:34] = 255
    return Image.fromarray(m, "L")


vp.figure_matte = matte
CALLS = {"stand_in": 0, "seen": None}


def stand_in(image, *, view, params):
    CALLS["stand_in"] += 1
    a = np.asarray(image).copy()
    CALLS["seen"] = int((a[..., 3] > 127).sum())
    hit = (a[..., 0] < 100) & (a[..., 3] > 127)
    a[hit, :3] = (180, 140, 120)
    return {"image": Image.fromarray(a, "RGBA") if hit.any() else None, "found": int(hit.sum()),
            "regions": [], "seconds": 0.0}


def bad(image, *, view, params):
    a = np.asarray(image).copy()
    a[0, 0, 3] = 255 - a[0, 0, 3]
    return {"image": Image.fromarray(a, "RGBA"), "found": 1}


def other(image, *, view, params):
    return {"image": None, "found": 0}


hooks.register_provider(vp.CAPABILITY, lambda: {"id": "stand_in", "label": "x", "views": ["front"],
                                                "params": {}, "apply": stand_in}, owner="smoke_a", multiple=True)
hooks.register_provider(vp.CAPABILITY, lambda: {"id": "bad", "label": "y", "views": ["front"],
                                                "params": {}, "apply": bad}, owner="smoke_b", multiple=True)
hooks.register_provider(vp.CAPABILITY, lambda: {"id": "other", "label": "z", "views": ["front"],
                                                "params": {}, "apply": other}, owner="smoke_c", multiple=True)

CHAR = "Demo"
gallery = TMP / "gallery"
gallery.mkdir()
ref = gallery / "fullbody.png"
ref.write_bytes(png(picture()))
orig = ref.read_bytes()


def pixels(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGBA"))


# --- the processed reference -------------------------------------------------------
check(vp.processed_reference(CHAR, ref, []) == ref, "no operation: the original")
out = vp.processed_reference(CHAR, ref, ["stand_in"])
check(out != ref and out.parent == vp.processed_dir(CHAR), f"copy in references/postprocessed ({out})")
px = pixels(out)
check(CALLS["seen"] == 600, f"the operation saw the figure matte: 600 px (got {CALLS['seen']})")
check(int((px[..., 0] < 100).sum()) == 0, "copy: no dark pixel left")
check(bool((px[..., 3] == 255).all()), "copy: the picture's own (opaque) alpha")
check(ref.read_bytes() == orig and int((pixels(ref)[..., 0] < 100).sum()) == 16, "original untouched (16 dark)")
rec = vp.reference_record(CHAR, ref, ["stand_in"])
check(rec["steps"][0]["found"] == 16 and rec["path"] == out, f"record: found 16 (got {rec['steps']})")
check(rec["source_sha256"] == hashlib.sha256(orig).hexdigest(), "record: source sha = original")
check(vp.processed_reference(CHAR, ref, ["stand_in"]) == out and CALLS["stand_in"] == 1, "asked again: cached")

clean = gallery / "clean.png"
clean.write_bytes(png(picture(dark=False)))
check(vp.processed_reference(CHAR, clean, ["stand_in"]) == clean, "nothing found: the original")
check(vp.reference_record(CHAR, clean, ["stand_in"])["result_sha256"] is None, "nothing found: result None")

try:
    vp.run(orig, "front", vp.operations()["bad"])
    check(False, "matte change refused")
except ValueError:
    check(True, "matte change refused")
check(vp.processed_reference(CHAR, ref, ["bad"]) == ref, "failing operation: the original")
check(bool(vp.reference_record(CHAR, ref, ["bad"])["error"]), "failing operation: error recorded")
pngs = sorted(p.name for p in vp.processed_dir(CHAR).glob("fullbody_pp*.png"))
check(pngs == [], f"another choice dropped the old copy of that original (got {pngs})")
vp.processed_reference(CHAR, ref, ["stand_in", "other"])
pngs = sorted(p.name for p in vp.processed_dir(CHAR).glob("fullbody_pp*.png"))
check(len(pngs) == 1, f"one copy per original (got {pngs})")

# --- A146 leftovers ------------------------------------------------------------------
refs = TMP / "model_refs"
refs.mkdir()
view = refs / "tpose_base0.png"
view_orig = png(picture(opaque=False))
view_done = png(picture(dark=False, opaque=False))
(refs / vp.KEEP_DIR).mkdir()
(refs / vp.KEEP_DIR / view.name).write_bytes(view_orig)
view.write_bytes(view_done)
sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
view.with_suffix(".json").write_text(json.dumps({"base_signature": "base0", "postprocess": {
    "op": "stand_in", "found": 16, "original_sha256": sha(view_orig), "result_sha256": sha(view_done)}}))
back = refs / "tpose_back_base0.png"
back.write_bytes(view_orig)
back.with_suffix(".json").write_text(json.dumps({"postprocess": {"op": "stand_in", "found": 0}}))
done = vp.restore_legacy_views(refs, [back])
check(done == {view.name: "restored", back.name: "dropped"}, f"legacy: restored + dropped (got {done})")
check(view.read_bytes() == view_orig, "legacy: view bytes back byte for byte")
check(back.read_bytes() == view_orig and "postprocess" not in json.loads(back.with_suffix(".json").read_text()),
      "legacy: record without result dropped, bytes unchanged")
check(not (refs / vp.KEEP_DIR).exists(), "legacy: kept dir removed")
check(json.loads(view.with_suffix(".json").read_text()).get("base_signature") == "base0", "legacy: sidecar kept")

# --- choices + base_source --------------------------------------------------------------
vp.world_default_ids = lambda: ["stand_in"]
avail = vp.operations()
check(vp.enabled_ids({"reference_postprocess": {"stand_in": False}}, avail) == [], "own off beats world default")
check(vp.enabled_ids({}, avail)[:1] == ["stand_in"], "world default applies without own choice")

fbr.base_image = lambda c, profile=None: ref
check(fbr.base_source(CHAR, profile={"reference_postprocess": {"stand_in": False}}) == ref,
      "base_source: off -> the reference file")
check(fbr.base_source(CHAR, profile={}) == out, "base_source: on -> the processed copy")

# --- the front's reason (base_body.front_reference_state) ----------------------------------
from app.core import base_body  # noqa: E402
plain = {"method": "reference", "image": "fullbody.png", "sha256": "a", "prompt": "p", "source": "full_body"}
done_ = {**plain, "image": out.name, "sha256": "b", "postprocess": ["stand_in"]}
base_body.base_signature = lambda c, profile=None: "base0"
for stored, wanted, reason in ((plain, done_, base_body.FRONT_POSTPROCESS_ON),
                               (done_, plain, base_body.FRONT_POSTPROCESS_OFF), (done_, done_, "")):
    base_body.front_reference = lambda c, profile=None, _w=wanted: dict(_w)
    base_body.stored_front_reference = lambda c, b, _s=stored: dict(_s)
    got = base_body.front_reference_state(CHAR, "base0", profile={})["reason"]
    check(got == reason, f"front reason {bool(stored.get('postprocess'))}->{bool(wanted.get('postprocess'))}: {got!r}")

print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
