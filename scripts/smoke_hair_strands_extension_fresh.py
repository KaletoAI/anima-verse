#!/usr/bin/env python3
"""Smoke: a strand record is stale when the fit body's extension groups change (review 07#4).

Usage:  ./.venv/bin/python scripts/smoke_hair_strands_extension_fresh.py

No world DB, no record build: a strands JSON is written by hand beside a dummy fit file in
``<tmp>/characters/demo/garments/fits/h.glb``, its fit record names ``body_id`` ``ob00000001``, and the body sidecar
``<tmp>/characters/demo/model3d/ob00000001.json`` is written by hand; ``collision.extension_chains`` is replaced by
a function returning the sidecar's ``chains`` list (the real one needs loaded packages).

Expected, by hand (``current_sha`` returns the strands JSON's sha256 when fresh, else ""):
[1] record without ``extension_sig`` (an old record), body sidecar without chains -> fresh (treated as none).
[2] the body sidecar now lists a chain group -> "" (stale; on 69aeeba75 still fresh: the extension was never read).
[3] the record rewritten with ``extension_sig`` of that group list -> fresh again.
[4] the group list changes again (another chain) -> "".
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import collision, hair_strands as hs  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="smoke_hsx_"))
char = TMP / "characters" / "demo"
fit = char / "garments" / "fits" / "h.glb"
fit.parent.mkdir(parents=True)
fit.write_bytes(b"fit-bytes")
fit.with_suffix(".json").write_text(json.dumps({"body_id": "ob00000001"}))
(char / "model3d").mkdir(parents=True)
side = char / "model3d" / "ob00000001.json"
collision.extension_chains = lambda meta: list(meta.get("chains") or [])
fit_sha = hashlib.sha256(b"fit-bytes").hexdigest()
json_path, _ = hs.sidecar_paths(fit)


def write_record(ext_sig=None):
    caps = {"scales": None}
    if ext_sig is not None:
        caps["extension_sig"] = ext_sig
    json_path.write_text(json.dumps({"version": hs.RECORD_VERSION, "fit_sha256": fit_sha, "capsules": caps}))
    st = json_path.stat()
    os.utime(json_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # a new stat identity for the read cache


def fresh():
    return hs.current_sha(fit) != ""


fails = []
side.write_text(json.dumps({}))
write_record()
fails += [] if fresh() else ["[1]"]
group = [{"group": "chest_hair", "op": "hair", "chains": [["a", "b"]]}]
side.write_text(json.dumps({"chains": group}))
fails += ["[2]"] if fresh() else []
write_record(hs.extension_sig(group))
fails += [] if fresh() else ["[3]"]
side.write_text(json.dumps({"chains": group + [{"group": "tail", "op": "hair", "chains": [["t"]]}]}))
fails += ["[4]"] if fresh() else []
print("FAILED", fails) if fails else print("all passed")
sys.exit(1 if fails else 0)
