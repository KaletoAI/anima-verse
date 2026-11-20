#!/usr/bin/env python3
"""Smoke: A224 — the plain body's texture key is its skin key, byte-identical to the key a figure with nothing on its
texture had before the painted mode was removed (``figure.texture_key``, ``base_body.skin_texture_inputs``).

Usage:
    ./.venv/bin/python scripts/smoke_skin_texture_key.py   (no server, no world DB; temp storage)

Expected by hand. The canonical JSON (keys sorted, separators "," ":") of the inputs for bsig ``base1234abcd``,
variant ``rigged``, side views off (the default) and the two dressed views front/back is

    {"base_signature":"base1234abcd","base_variant":"rigged","dress_text":{"back":"","front":""},"side_views":false,"version":1}

and ``"tex"`` + the first 12 hex of its sha256 is ``tex6bd59933c739`` — the value base commit 6bccac4b3
(``texture_inputs(pieces={}, mesh_effective=[])``) returned for the same character, measured once.

[1] skin_texture_inputs gives exactly that JSON.
[2] texture_key on the plain body gives tex6bd59933c739 — whatever is worn (a set with pieces).
[3] texture_key on a meshed shape gives "" (its texture is the shape's own).
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_skin_key_")
os.environ["STORAGE_DIR"] = TMP
os.environ["INSTANCE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import base_body, figure  # noqa: E402

WANT_JSON = ('{"base_signature":"base1234abcd","base_variant":"rigged","dress_text":{"back":"","front":""},'
             '"side_views":false,"version":1}')
WANT_KEY = "tex6bd59933c739"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


profile = {"name": "Demo"}
inputs = base_body.skin_texture_inputs("Demo", bsig="base1234abcd", variant="rigged", profile=profile)
check("[1] inputs", json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":")), WANT_JSON)
sets = figure.WornSets(in_body=("item_a", "item_b"), off_pipeline=(), own={}, hair_in_body=False, hair_item="",
                       pieces={"top": "item_a", "bottom": "item_b"})
check("[2] plain key", figure.texture_key("Demo", sets, shape="base1234abcd", bsig="base1234abcd", variant="rigged",
                                          profile=profile), WANT_KEY)
check("[3] shape key", figure.texture_key("Demo", sets, shape="shp0123456789ab", bsig="base1234abcd",
                                          variant="rigged", profile=profile), "")
print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
sys.exit(1 if FAILS else 0)
