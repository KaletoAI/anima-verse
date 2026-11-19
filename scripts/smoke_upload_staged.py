#!/usr/bin/env python3
"""An uploaded piece-only view is staged and gated BESIDE its attempt slot and moves in only after the Undo
snapshot was taken (A207, review finding 05#6): ``garment_images.stage_upload`` / ``commit_upload`` /
``discard_upload`` and ``garments._use_attempt_locked(..., staged=)``.

Usage:
    ./.venv/bin/python scripts/smoke_upload_staged.py

No server, no world DB, no gate model: a throwaway storage + instance root (``paths.init`` first); the store root,
``garment_path`` and the gate's inputs are stubbed onto a temp folder; ``crop_back`` and the gate are stubs
(the gate writes a raw sibling like a registration does). Slot 2 holds an OLD stored attempt (bytes ``OLD``,
sidecar ``{"gate": {"ok": true, "old": 1}}``) and is the slot ``_upload_slot`` picks.

EXPECTED, from the rule (the slot is touched only by ``commit_upload``, which runs after the snapshot):
[U1] ``stage_upload`` -> slot 2 image, raw sibling and sidecar byte-identical to before; the staged image is
     ``.upload_<slot name>`` and holds the upload; the returned gate is the stub's record with ``attempt`` 2.
     FAILS on the old code (commit 8fa2d763f, ``store_upload``): the slot image was the upload right after the
     call (the slot was overwritten before and regardless of the gate).
[U2] the gate raises -> the exception propagates, slot 2 unchanged, no ``.upload_*`` file left in the folder.
[U3] ``_use_attempt_locked`` with the staged upload, ``use_attempt`` publishes -> slot 2 holds the upload, its
     sidecar the new gate; the committed Undo manifest names slot 2's image with sha256(``OLD``); ``undo`` puts
     slot 2 back to ``OLD`` (image) and the old sidecar.
[U4] ``use_attempt`` raises after the upload moved in -> the error propagates, slot 2 is ``OLD`` again (image,
     raw, sidecar), no pending snapshot left, no ``.upload_*`` file left (``upload_view``'s discard).
"""
import hashlib
import io
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_upload_staged_")).resolve()
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
from app.core import paths  # noqa: E402
paths.init(str(TMP / "storage"))
paths.init_instance(str(TMP / "instance"))

from PIL import Image  # noqa: E402
from app.core import garment_images as gi  # noqa: E402
from app.core import garment_store as gs  # noqa: E402
from app.core import garment_use_undo as gu  # noqa: E402
from app.core import garments, garment_mesh, figure, figure_build, base_body, model_refs  # noqa: E402
import app.models.character as mc  # noqa: E402

fails = []


def check(tag, ok, msg=""):
    print(f"[{tag}] {'PASS' if ok else 'FAIL'} {msg}")
    if not ok:
        fails.append(tag)


def sha(b):
    return hashlib.sha256(b).hexdigest()


G = TMP / "garments"
ITEM, FSIG, STEP, VIEW = "item_x", "0123456789ab", "ghost", "front"


def garment_path(c, item, fsig, part, step=None, view=None, attempt=None):
    if part == "image":
        if attempt:
            return G / "attempts" / f"{item}_{fsig}_{step}_{view}.try{attempt}.png"
        return G / "images" / f"{item}_{fsig}_{step}_{view}.png"
    return G / part / f"{item}_{fsig}.bin"


gs._root = lambda c: G
gs.garment_path = garment_path
gu._targets = lambda c, i, f, s, v: [garment_path(c, i, f, "image", step=s, view=v),
                                     garment_path(c, i, f, "image", step=s, view=v).with_suffix(".json")]
gu._mesh_attempts = lambda c, i, f: []


@contextmanager
def _lock(c, i):
    yield


garment_mesh.mesh_lock = _lock
figure.invalidate = lambda *a, **k: None


class Kind:
    FROM_WORN_STEP = STEP
    EDIT_STEPS = {STEP: {"source": "worn"}}


gi._kind_module = lambda item: Kind
gi._open_state = lambda *a, **k: False
gi._accepted = lambda p: True
gi._upload_slot = lambda *a: 2
gi._gate_inputs = lambda *a, **k: ((8, 8), {}, None)
gi._source_sha = lambda *a: "src"
gi.square_frame = lambda size: (8, (0, 0))
mc.get_character_profile = lambda c: {}
base_body.base_signature = lambda c, profile=None: "b"
base_body._kind = lambda v: "base"
model_refs.find_ref_image = lambda *a: TMP / "base.png"
model_refs.get_model_refs_dir = lambda c: TMP


def crop_back(src, dst, side, offset, size):
    dst.write_bytes(Path(src).read_bytes())


gi.crop_back = crop_back
GATE = {"view": VIEW, "ok": False, "reasons": ["hem"]}
gate_raises = False


def gate(kind, step, view, path, *a):
    if gate_raises:
        raise RuntimeError("gate broke")
    gi.raw_path(path).write_bytes(b"RAW-UPLOAD")
    return dict(GATE)


gi._gate_attempt = gate

slot = garment_path("C", ITEM, FSIG, "image", step=STEP, view=VIEW, attempt=2)
slot_json, slot_raw = slot.with_suffix(".json"), gi.raw_path(slot)
OLD_JSON = {"gate": {"ok": True, "old": 1}}


def reset_slot():
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_bytes(b"OLD")
    slot_raw.write_bytes(b"RAW-OLD")
    slot_json.write_text(json.dumps(OLD_JSON))


def slot_is_old():
    return (slot.read_bytes() == b"OLD" and slot_raw.read_bytes() == b"RAW-OLD"
            and json.loads(slot_json.read_text()) == OLD_JSON)


def leftovers():
    return sorted(p.name for p in slot.parent.glob(".upload_*"))


buf = io.BytesIO()
Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, format="PNG")
DATA = buf.getvalue()
src = garment_path("C", ITEM, FSIG, "image", step="worn", view=VIEW)
src.parent.mkdir(parents=True, exist_ok=True)
Image.new("RGB", (8, 8), (0, 0, 0)).save(src)

# U1
reset_slot()
st = gi.stage_upload("C", ITEM, FSIG, STEP, VIEW, DATA)
staged_bytes = st["staged"].read_bytes() if st["staged"].is_file() else b""
check("U1", slot_is_old() and st["staged"].name == f".upload_{slot.name}" and staged_bytes != b"OLD"
      and Image.open(st["staged"]).size == (8, 8) and st["gate"].get("attempt") == 2
      and st["gate"].get("reasons") == ["hem"], f"slot old {slot_is_old()} staged {st['staged'].name}")
gi.discard_upload(st)

# U2
gate_raises = True
reset_slot()
try:
    gi.stage_upload("C", ITEM, FSIG, STEP, VIEW, DATA)
    raised = False
except RuntimeError:
    raised = True
gate_raises = False
check("U2", raised and slot_is_old() and leftovers() == [], f"raised {raised} leftovers {leftovers()}")

# U3
final = garment_path("C", ITEM, FSIG, "image", step=STEP, view=VIEW)


def use_ok(c, i, f, s, v, n):
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(slot.read_bytes())
    final.with_suffix(".json").write_text(json.dumps({"attempt": n}))
    return {"changed": True, "passing": False, "user_accepted": True}


gi.use_attempt = use_ok
garments._drop_mesh = lambda *a, **k: None
gs.image_steps = lambda kind: ("worn", "ghost")
gs.chain_failure = lambda *a: None
gs.status = lambda *a: {}
figure_build.answer_piece_failure = lambda *a, **k: None

reset_slot()
st = gi.stage_upload("C", ITEM, FSIG, STEP, VIEW, DATA)
upload_png = st["staged"].read_bytes()
try:
    garments._use_attempt_locked("C", ITEM, "clothing", FSIG, STEP, VIEW, 2, staged=st)
finally:
    gi.discard_upload(st)
in_slot = slot.read_bytes() == upload_png and json.loads(slot_json.read_text()).get("gate", {}).get("reasons") == ["hem"]
man = json.loads((gu.undo_dir("C", ITEM, FSIG) / gu.MANIFEST).read_text())
rel = slot.relative_to(G).as_posix()
named = man["files"].get(rel) == sha(b"OLD")
gu.undo("C", ITEM, FSIG)
check("U3", in_slot and named and slot_is_old(), f"in slot {in_slot} manifest {named} undone {slot_is_old()}")

# U4


def use_fail(*a):
    raise RuntimeError("use broke")


gi.use_attempt = use_fail
reset_slot()
st = gi.stage_upload("C", ITEM, FSIG, STEP, VIEW, DATA)
try:
    try:
        garments._use_attempt_locked("C", ITEM, "clothing", FSIG, STEP, VIEW, 2, staged=st)
    finally:
        gi.discard_upload(st)
    raised = False
except RuntimeError:
    raised = True
pending = gu._pending(gu.undo_dir("C", ITEM, FSIG))
check("U4", raised and slot_is_old() and not pending.exists() and leftovers() == [],
      f"raised {raised} old {slot_is_old()} pending {pending.exists()} leftovers {leftovers()}")

print("FAIL" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
