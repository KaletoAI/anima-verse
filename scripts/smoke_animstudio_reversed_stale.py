#!/usr/bin/env python3
"""Smoke: publishing a ``Reversed`` bridge refuses a build whose SOURCE clip
changed after the build, not only a changed ``anims/<kind>.py``.

Usage: ./.venv/bin/python scripts/smoke_animstudio_reversed_stale.py

No Blender, no git commit: a fake build (FBX bytes + sidecar + build.json)
stands in for ``build_reversed``; library, anims and out are temp dirs.
Source clip ``smoke-src`` (FBX bytes b"SRC-1", sidecar {"kind": "smoke-src",
"loop": false, "pair": false}) and ``anims/smoke-rev.py`` =
``Reversed(kind='smoke-rev', source='smoke-src')``.

By hand:
[0] source_sha is SHA-256 over (len(fbx) as 8 bytes big-endian, fbx,
    len(side) as 8 bytes, side). For fbx = b"A", side = b"B" that is
    sha256(b"\\0"*7 + b"\\x01" + b"A" + b"\\0"*7 + b"\\x01" + b"B"); moving the
    byte across the boundary (fbx = b"AB", side = b"") gives a different
    hash, because the length prefixes differ (2/0 instead of 1/1).
[1] build.json with the right spec_sha but NO source_sha (a stamp written
    before the source identity existed) -> StudioError "build again",
    smoke-rev.fbx not in the library.
[2] build.json stamped with the source_sha of the CURRENT source, then the
    source FBX is republished (bytes b"SRC-2"): spec_sha is unchanged (the
    anim file was not touched) -> on the old code the publish went through
    (it compared spec_sha only); now StudioError naming 'smoke-src',
    nothing written.
[3] same, but only the source SIDECAR changes (a "credit" field added) ->
    StudioError, nothing written.
[4] stamped again against the current source -> publish succeeds: the
    library holds smoke-rev.fbx with the built bytes b"REV".
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="animstudio-revstale-"))
# smoke_scripts_storage_lint accepts only a literal paths.init(...) or
# STORAGE_DIR before a world-DB import - bootstrap() is a wrapper it cannot see.
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(TMP / "licensed")
sys.path.insert(0, str(ROOT / "animation-studio"))

import animstudio                                                     # noqa: E402
animstudio.bootstrap()
animstudio.OUT = TMP / "out"
animstudio.ANIMS = TMP / "anims"

from animstudio import StudioError                                    # noqa: E402
from animstudio.build import spec_sha                                 # noqa: E402
from animstudio.publish import publish                                # noqa: E402
from animstudio.reverse import source_sha                             # noqa: E402

FAIL = []
LIB = TMP / "clips"
OUT = animstudio.OUT / "smoke-rev"


def stamp(with_source=True):
    doc = {"kind": "smoke-rev", "spec_sha": spec_sha("smoke-rev"), "ok": True,
           "checks": [{"name": "sidecar", "ok": True, "value": 0, "limit": "0 mismatches",
                       "detail": ""}]}
    if with_source:
        doc["source_sha"] = source_sha(LIB / "smoke-src.fbx", LIB / "smoke-src.json")
    (OUT / "build.json").write_text(json.dumps(doc))


def refused(label, needle):
    try:
        publish("smoke-rev", commit=False)
    except StudioError as e:
        if needle not in str(e):
            FAIL.append(f"{label} wrong refusal: {e}")
    else:
        FAIL.append(f"{label} stale reversal published")
    if (LIB / "smoke-rev.fbx").exists():
        FAIL.append(f"{label} smoke-rev.fbx written although refused")


# [0]
a = tempfile.NamedTemporaryFile(dir=TMP, delete=False); a.write(b"A"); a.close()
b = tempfile.NamedTemporaryFile(dir=TMP, delete=False); b.write(b"B"); b.close()
want = hashlib.sha256(b"\0" * 7 + b"\x01" + b"A" + b"\0" * 7 + b"\x01" + b"B").hexdigest()
if source_sha(a.name, b.name) != want:
    FAIL.append("[0] source_sha differs from the hand-derived hash")
Path(a.name).write_bytes(b"AB"); Path(b.name).write_bytes(b"")
if source_sha(a.name, b.name) == want:
    FAIL.append("[0] moving a byte across the file boundary kept the hash")

LIB.mkdir(parents=True)
(TMP / "licensed").mkdir()
animstudio.ANIMS.mkdir(parents=True)
OUT.mkdir(parents=True)
(LIB / "smoke-src.fbx").write_bytes(b"SRC-1")
(LIB / "smoke-src.json").write_text(json.dumps({"kind": "smoke-src", "loop": False, "pair": False}))
(animstudio.ANIMS / "smoke-rev.py").write_text(
    "from animstudio.dsl import Reversed\n"
    "ANIM = Reversed(kind='smoke-rev', source='smoke-src')\n")
(OUT / "smoke-rev.fbx").write_bytes(b"REV")
(OUT / "smoke-rev.json").write_text(json.dumps({"kind": "smoke-rev", "loop": False, "pair": False}))

# [1]
stamp(with_source=False)
refused("[1]", "build again")

# [2]
stamp()
(LIB / "smoke-src.fbx").write_bytes(b"SRC-2")
refused("[2]", "'smoke-src'")

# [3]
stamp()
(LIB / "smoke-src.json").write_text(json.dumps(
    {"kind": "smoke-src", "loop": False, "pair": False, "credit": "x"}))
refused("[3]", "'smoke-src'")

# [4]
stamp()
try:
    publish("smoke-rev", commit=False)
except StudioError as e:
    FAIL.append(f"[4] fresh build refused: {e}")
if not (LIB / "smoke-rev.fbx").exists() or (LIB / "smoke-rev.fbx").read_bytes() != b"REV":
    FAIL.append("[4] the fresh reversal is not in the library")

if FAIL:
    print("FAIL")
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("OK reversed publish refuses a stale source (missing stamp, FBX, sidecar); fresh build publishes")
