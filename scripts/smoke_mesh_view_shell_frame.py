"""Smoke: the shell's body view does not need the front framing it never uses (A198, review 06 #8).

Usage:
    ./.venv/bin/python scripts/smoke_mesh_view_shell_frame.py

No server, no world DB: the base snapshot, the GLB readers and ``garment_source.fit_masks`` (refusing with
FrameRefused) are stubbed; ``_compute_shell`` is a spy. By hand:
  [1] which "shell"    -> ``_compute_shell`` answers, the framing is never asked (pre-fix e846d7d02: ViewUnavailable
      "The piece cannot be placed on this body")
  [2] which "prepared" -> ViewUnavailable (the placement needs the framing)
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import base_body, garment_mesh_view as gmv, garment_source, glb_mesh  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


body = SimpleNamespace(positions=np.array([[0, 0, 0], [0, 1.7, 0], [0.1, 0, 0]], float), faces=np.array([[0, 1, 2]]))
base_body._snapshot_base_model = lambda c, b: {"unrigged": b"U", "rigged": b"R"}
glb_mesh.body_arrays = lambda data: body
glb_mesh.static_arrays = lambda data: (body.positions, body.faces, None, None, None, None)
asked = []


def refuse(*a, **k):
    asked.append(1)
    raise garment_source.FrameRefused(None)


garment_source.fit_masks = refuse
gmv._compute_shell = lambda inputs, body_r, P, F, started: {"shell": True}


class Mesh:
    name = "m.glb"

    def read_bytes(self):
        return b"M"


inputs = {"bsig": "b", "fsig": "0123456789ab", "front": Path("f.png"), "mesh": Mesh(), "key": "k"}
try:
    got = gmv._compute("Demo", "item_x", {**inputs, "which": "shell"})
    check("[1] shell answers without the framing", got == {"shell": True} and asked == [], (got, asked))
except gmv.ViewUnavailable as e:
    check("[1] shell answers without the framing", False, e)
try:
    gmv._compute("Demo", "item_x", {**inputs, "which": "prepared"})
    check("[2] a placed mesh needs the framing", False, "no error")
except gmv.ViewUnavailable as e:
    check("[2] a placed mesh needs the framing", "cannot be placed" in str(e), e)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
