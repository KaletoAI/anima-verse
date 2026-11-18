#!/usr/bin/env python3
"""Base-body bookkeeping of review 08b: the undressed copy onto the live outfit references is atomic (#5), two
outfit runs of one stage do not unlist each other (#6), and a base view's failure belongs to its base (#4).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_status_and_ref_writes.py

No server, no world DB, no render: a throwaway storage dir (``paths.init``), the character's directories made by
hand, ``model_refs.mesh_variant`` / ``mesh_items_token`` replaced by fixed values.

Expected, derived by hand:

[5] ``_render_views`` with ``dressed`` False (nothing to paint: the shape's views are copied) for the outfit
    ``outfit0001`` on the shape ``baseX``, views front + left. Before the call ``tpose_outfit0001.png`` holds OLD
    bytes (its inode noted) and the left view is stored as ``tpose_left_outfit0001.webp``.
    - the front: the bytes of the shape's front, under a NEW inode — written to a staged file and moved over the
      live one (``os.replace``); the old ``shutil.copyfile`` rewrote the live inode in place (truncate, then
      write), so a reader in between could read a cut PNG -> FAILS on the old code;
    - the left view: ``tpose_left_outfit0001.png`` with the shape's left bytes, the ``.webp`` of the same stem is
      gone (the old code left it beside the new ``.png``) -> FAILS on the old code;
    - each sidecar: ``base_image_sha256`` = sha256 of the copied shape view, ``base_signature`` "baseX",
      ``dressed`` False, ``texture_signature`` "tex1", ``mesh_variant`` "mv", ``mesh_token`` "tok", the shape
      view's own keys kept but its ``outfit_body`` dropped; no staged ``.tex-*.tmp`` file left behind;
    - the results: ``{"tpose": <front>, "tpose_left": <left>}``.
[6] ``_outfit_start`` / ``_outfit_end`` of the stage "images" for ``Demo``:
    - A (sig1) starts, B (sig2) starts, B ends -> A still runs: ``outfit_running`` True and the stage lists sig1;
      the old code popped the entry on B's end (it held sig2) -> False -> FAILS on the old code. A ends -> False.
    - A starts, B starts, A ends -> True (B listed), B ends -> False.
    - sig1 started twice, one ends -> True (the old code: False); the other ends -> False.
    - sig1 runs; a call that found nothing to do ends it with ``started=False`` -> still True; then sig1's own end
      -> False.
[4] ``_record`` of the front failing on the base "baseA": ``base_status(Demo, "baseA")`` front failed with the
    error; ``base_status(Demo, "baseB")`` (the appearance changed, a new base) -> not failed, error None (the old
    code had no signature parameter and reported A's failure on B); ``base_status(Demo)`` (no signature: the callers
    that only read ``running``) -> failed as before. A failure recorded without a signature (a run that ended before
    its base was known) is reported for every base.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def png(path: Path, colour) -> bytes:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), colour).save(path)
    return path.read_bytes()


def section_copy(root: Path):
    from app.core import base_body, model_refs
    from app.models.character import get_character_dir
    print("[5] the undressed copy onto the live references")
    get_character_dir("Demo").mkdir(parents=True, exist_ok=True)
    refs = model_refs.get_model_refs_dir("Demo")
    shape = root / "shape"
    sources = {"front": shape / "tpose_baseX.png", "left": shape / "tpose_left_baseX.png"}
    data = {"front": png(sources["front"], (200, 100, 50, 255)), "left": png(sources["left"], (20, 100, 200, 255))}
    for v, path in sources.items():
        path.with_suffix(".json").write_text(json.dumps({"base_signature": "baseX", "prompt": f"shape {v}",
                                                         "outfit_body": {"built_for": "x"}}))
    old_front = refs / "tpose_outfit0001.png"
    png(old_front, (1, 2, 3, 255))
    old_inode = old_front.stat().st_ino
    old_left = refs / "tpose_left_outfit0001.webp"
    old_left.write_bytes(b"old webp bytes")
    real = model_refs.mesh_variant, model_refs.mesh_items_token
    model_refs.mesh_variant = lambda c, pieces, profile: "mv"
    model_refs.mesh_items_token = lambda c, pieces, profile: "tok"
    try:
        out = base_body._render_views(
            "Demo", signature="outfit0001", pieces={}, items=[], todo=["front", "left"], force=True, on="baseX",
            registrations=dict(sources), texts={}, tsig="tex1", mesh={}, dressed=False, bald=False, profile={},
            raise_load=False, current=lambda v: None)
    finally:
        model_refs.mesh_variant, model_refs.mesh_items_token = real
    front, left = refs / "tpose_outfit0001.png", refs / "tpose_left_outfit0001.png"
    check("results", out, {"tpose": str(front), "tpose_left": str(left)})
    check("front bytes = the shape's front", front.read_bytes() == data["front"], True)
    check("front replaced, not rewritten in place (new inode)", front.stat().st_ino != old_inode, True)
    check("left bytes = the shape's left", left.read_bytes() == data["left"], True)
    check("the .webp of the left stem is gone", old_left.exists(), False)
    for v, path in (("front", front), ("left", left)):
        meta = json.loads(path.with_suffix(".json").read_text())
        check(f"{v} sidecar", {k: meta.get(k) for k in ("base_image_sha256", "base_signature", "dressed",
                                                         "texture_signature", "mesh_variant", "mesh_token",
                                                         "prompt")},
              {"base_image_sha256": hashlib.sha256(data[v]).hexdigest(), "base_signature": "baseX",
               "dressed": False, "texture_signature": "tex1", "mesh_variant": "mv", "mesh_token": "tok",
               "prompt": f"shape {v}"})
        check(f"{v} sidecar: no outfit_body", "outfit_body" in meta, False)
    check("no staged file left", sorted(p.name for p in refs.iterdir() if p.name.startswith(".")), [])


def section_running():
    from app.core import base_body as bb
    print("[6] outfit runs of one stage")
    C = "Demo"

    def listed():
        with bb._status_lock:
            return bb._outfit_running.get((C, "images"))

    bb._outfit_start(C, "sig1", "images")
    bb._outfit_start(C, "sig2", "images")
    bb._outfit_end(C, "sig2", "images", None)
    check("A, B start, B ends: A still runs", (bb.outfit_running(C), listed()), (True, "sig1"))
    bb._outfit_end(C, "sig1", "images", None)
    check("then A ends: none", (bb.outfit_running(C), listed()), (False, None))

    bb._outfit_start(C, "sig1", "images")
    bb._outfit_start(C, "sig2", "images")
    bb._outfit_end(C, "sig1", "images", None)
    check("A, B start, A ends: B runs", (bb.outfit_running(C), listed()), (True, "sig2"))
    bb._outfit_end(C, "sig2", "images", None)
    check("then B ends: none", bb.outfit_running(C), False)

    bb._outfit_start(C, "sig1", "images")
    bb._outfit_start(C, "sig1", "images")
    bb._outfit_end(C, "sig1", "images", None)
    check("sig1 twice, one ends: still runs", bb.outfit_running(C), True)
    bb._outfit_end(C, "sig1", "images", None)
    check("the other ends: none", bb.outfit_running(C), False)

    bb._outfit_start(C, "sig1", "images")
    bb._outfit_end(C, "sig1", "images", None, started=False)
    check("an end that never started leaves the run", bb.outfit_running(C), True)
    bb._outfit_end(C, "sig1", "images", None)
    check("the run's own end: none", (bb.outfit_running(C), bb._outfit_runs), (False, {}))


def section_failure():
    from app.core import base_body as bb
    print("[4] a base view's failure belongs to its base")
    bb._record("Demo", "front", "render failed", signature="baseA")
    check("its own base", (bb.base_status("Demo", "baseA")["front"]["failed"],
                           bb.base_status("Demo", "baseA")["front"]["error"]), (True, "render failed"))
    check("another base", (bb.base_status("Demo", "baseB")["front"]["failed"],
                           bb.base_status("Demo", "baseB")["front"]["error"]), (False, None))
    check("no signature asked: as before", bb.base_status("Demo")["front"]["failed"], True)
    bb._record("Demo", "back", "worker died")
    check("a failure without a base: every base", bb.base_status("Demo", "baseB")["back"]["failed"], True)
    bb._record("Demo", "front", None)
    bb._record("Demo", "back", None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-outfit-status-"))
    try:
        os.environ["STORAGE_DIR"] = str(tmp / "world")
        from app.core import paths
        paths.init(tmp / "world")
        section_copy(tmp)
        section_running()
        section_failure()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
