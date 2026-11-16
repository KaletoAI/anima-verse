#!/usr/bin/env python3
"""Ruling A131: a new base body moves a clothing piece onto a new, empty fingerprint (the clothing fsig carries the
base ``bsig``). The meshes made for the earlier body stay stored and the piece dialog's Mesh row shows them
(read-only, ``garments._earlier_meshes``, served by ``garment_mesh_view.mesh_file(fsig=…)``); the Figure tab names
a piece fitted on the earlier body "Waiting for the new body" (``figure.LEFT_OFF_NEW_BODY``,
``garment_store.fitted_on_earlier_body``) instead of "no fit".

Usage:
    ./.venv/bin/python scripts/smoke_garment_new_body.py

Throwaway storage + instance (STORAGE_DIR / INSTANCE_DIR temp dirs); no hub, no server, no world DB read. Stubs:
``garment_store.garment_fsig`` (-> CUR), ``base_body.base_signature`` (-> the test's bsig),
``garments.cached_failure`` (-> the test's failure), ``garments._mesh_use_block``.

Fixture (character Demo, item ``dress``; fsigs are 12 hex digits):
    OLD1 = 111111111111: prepared/dress_OLD1.glb + raw/dress_OLD1.glb, mtime T-100; prepared record created_at "c1";
                         the fit dress_OLD1.glb + .json {accepted: true, base_signature: "bOLD"}
    OLD2 = 222222222222: raw/dress_OLD2.glb only, mtime T-10
    OLD3 = 333333333333: a fit file only (no prepared/raw mesh)          -> no earlier MESH
    CUR  = cccccccccccc: nothing (the new body's fingerprint)
    other_OLD1 (another item)                                           -> never listed

Expected, by hand:
[1] earlier_mesh_fsigs(dress, CUR) = [OLD2, OLD1] (newest mesh first; OLD3 has no mesh; CUR itself excluded);
    with current = OLD1 -> [OLD2].
[2] fitted_on_earlier_body(dress, "bNEW") = True (the OLD1 fit is accepted on bOLD); with "bOLD" -> False;
    after the record says accepted false -> False (restored after).
[3] _not_fitted_reason: bsig bNEW, no failure -> "Waiting for the new body"; bsig bOLD, base_sha "x" ->
    base_body.NO_MESH_FIT; a persisted chain failure wins over both.
[4] mesh_file(which="prepared", fsig=OLD1) -> prepared/dress_OLD1.glb; fsig=OLD2 prepared -> None (no file);
    fsig=OLD3 -> ValueError (no earlier mesh); fsig=OLD1 with attempt 1 -> ValueError; which "shell" -> ValueError.
[5] _earlier_meshes(dress, CUR): 2 entries, fsigs [OLD2, OLD1]; OLD2 prepared None, raw url ends "&fsig=OLD2";
    OLD1 created_at "c1", body_url "" on both files.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_a131_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    (tmp / "world").mkdir()
    (tmp / "instance").mkdir()
    from app.core import paths
    paths.init(str(tmp / "world"))
    from app.core import base_body, figure, garment_mesh_view, garments
    from app.core import garment_store as gs

    C, I = "Demo", "dress"
    OLD1, OLD2, OLD3, CUR = "1" * 12, "2" * 12, "3" * 12, "c" * 12
    state = {"bsig": "bNEW", "failure": None}
    gs.garment_fsig = lambda *a, **k: CUR
    base_body.base_signature = lambda *a, **k: state["bsig"]
    garments.cached_failure = lambda *a, **k: state["failure"]
    garments._mesh_use_block = lambda *a, **k: ""

    def put(path: Path, data: bytes = b"glb", mtime: float = 0.0) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    now = time.time()
    put(gs.garment_path(C, I, OLD1, "prepared"), mtime=now - 100)
    put(gs.garment_path(C, I, OLD1, "raw"), mtime=now - 100)
    put(gs.garment_path(C, I, OLD1, "prepared").with_suffix(".json"), json.dumps({"created_at": "c1"}).encode())
    fit = put(gs.garment_path(C, I, OLD1, "fit"))
    fit_json = fit.with_suffix(".json")
    put(fit_json, json.dumps({"accepted": True, "base_signature": "bOLD"}).encode())
    put(gs.garment_path(C, I, OLD2, "raw"), mtime=now - 10)
    put(gs.garment_path(C, I, OLD3, "fit"))
    put(gs.garment_path(C, "other", OLD1, "prepared"))

    print("[1] earlier meshes")
    check("earlier of CUR", gs.earlier_mesh_fsigs(C, I, CUR), [OLD2, OLD1])
    check("earlier of OLD1", gs.earlier_mesh_fsigs(C, I, OLD1), [OLD2])

    print("[2] fitted on an earlier body")
    check("on bNEW", gs.fitted_on_earlier_body(C, I, "bNEW"), True)
    check("on bOLD", gs.fitted_on_earlier_body(C, I, "bOLD"), False)
    fit_json.write_text(json.dumps({"accepted": False, "base_signature": "bOLD"}))
    check("refused fit", gs.fitted_on_earlier_body(C, I, "bNEW"), False)
    fit_json.write_text(json.dumps({"accepted": True, "base_signature": "bOLD"}))

    print("[3] left-off reason")
    check("new body", figure._not_fitted_reason(C, I, base_sha="", profile={}), "Waiting for the new body")
    check("constant", figure.LEFT_OFF_NEW_BODY, "Waiting for the new body")
    state["bsig"] = "bOLD"
    check("same body", figure._not_fitted_reason(C, I, base_sha="x", profile={}), base_body.NO_MESH_FIT)
    state["bsig"], state["failure"] = "bNEW", {"step": "mesh", "error": "boom"}
    check("failure wins", figure._not_fitted_reason(C, I, base_sha="x", profile={}),
          base_body.MESH_ITEM_CHAIN_FAILED.format(step="mesh", error="boom"))
    state["failure"] = None

    print("[4] serving an earlier mesh")
    check("OLD1 prepared", garment_mesh_view.mesh_file(C, I, "prepared", 0, OLD1),
          gs.garment_path(C, I, OLD1, "prepared"))
    check("OLD2 prepared", garment_mesh_view.mesh_file(C, I, "prepared", 0, OLD2), None)
    for label, args in (("OLD3", ("prepared", 0, OLD3)), ("attempt", ("prepared", 1, OLD1)),
                        ("shell", ("shell", 0, OLD1))):
        try:
            garment_mesh_view.mesh_file(C, I, *args)
            check(f"{label} refused", False, True)
        except ValueError:
            check(f"{label} refused", True, True)

    print("[5] the Mesh row's earlier tiles")
    rows = garments._earlier_meshes(C, I, CUR)
    check("fsigs", [r["fsig"] for r in rows], [OLD2, OLD1])
    check("OLD2 prepared", rows[0]["prepared"], None)
    check("OLD2 raw url", rows[0]["raw"]["url"].endswith(f"&fsig={OLD2}"), True)
    check("OLD1 created_at", rows[1]["created_at"], "c1")
    check("body_url", (rows[1]["prepared"]["body_url"], rows[1]["raw"]["body_url"]), ("", ""))

    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
