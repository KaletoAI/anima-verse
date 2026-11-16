#!/usr/bin/env python3
"""Ruling A119 — the 3D view is what the game shows; an old mesh is never shown.

Spec ``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md`` (Ruling A119, replacing the interim rule):
the delivered figure stands on the NEWEST current body, the pieces whose own result is ready for it are worn, every
other piece is left off. This smoke checks the serving side (the resolver itself: ``smoke_figure_delivered.py``):

* ``model3d.find_model3d_serving`` on the pipeline — only the current model of the worn outfit (``"exact"``), else
  the plain body (``"base"``); never ``"stale"`` / ``"nearest"``. Off the pipeline the nearest stand-in stays.
* ``garment_assembly.bare_meta_of`` — the plain body served as the worn figure carries the delivered figure's READY
  own-mesh pieces as ``mesh_items.intended`` (so the CPU assembly puts them on), nothing for a body the figure does
  not stand on, an outfit model's sidecar unchanged.
* ``base_body.mesh_record`` — an in-body piece left off for its unbuilt shape is no own-mesh piece (never grafted);
  an own-mesh piece left off stays intended (grafted as soon as its fit exists); every left-off piece is out of the
  dress text (``unpainted``).

Usage:
    ./.venv/bin/python scripts/smoke_figure_a119.py

Throwaway storage + instance (``paths.init`` before any world import); stubs replace the outfit state, the base and
the delivered figure — no world DB, no hub, no server.

Fixture (all by hand): character "Demo", plain body BSIG = "base0123abcd" (sha "basesha"), worn outfit signature
SIG = "aaaaaaaaaaaa"; files in the model directory: SIG.glb (the current outfit model), OTHER = "bbbbbbbbbbbb".glb
(another outfit, closest by pieces), BSIG.glb (the plain body).

Expected:
[1] SIG current -> (SIG.glb, "exact").
[2] SIG built on an older body / as another figure (``_on_older_base`` True) -> (BSIG.glb, "base") — not the stale
    SIG, not the nearest OTHER (was: (SIG.glb, "stale")).
[3] SIG missing -> (BSIG.glb, "base") (was: (OTHER.glb, "nearest")).
[4] SIG missing and no plain body file -> (None, "").
[5] Off the pipeline (``_current_base`` None), SIG missing -> (OTHER.glb, "nearest") — the img2mesh path is not the
    figure's.
[6] bare_meta_of(BSIG) with the delivered figure on BSIG, own ("boots",), left_out {belt: …, necklace: …} ->
    mesh_items.intended == ["boots"], pieces == the figure's, base_signature BSIG, base_model_sha256 "basesha".
[7] the same with the delivered figure on a meshed shape "ob12345678" -> the base sidecar as stored ({"base": True}).
[8] bare_meta_of(SIG) -> SIG's own sidecar.
[9] mesh_record(figure with own (boots,), left_out {belt: chain failed, coat: "Body shape not built"}) ->
    intended ["belt", "boots"] (coat is an in-body piece), effective ["boots"], unpainted ["belt", "boots", "coat"],
    warnings [].
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
BSIG, SIG, OTHER = "base0123abcd", "aaaaaaaaaaaa", "bbbbbbbbbbbb"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-a119-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import base_body, figure, garment_assembly, model3d
        d = root / "models"
        d.mkdir()
        model3d.get_model3d_dir = lambda _c: d
        pieces = {"top": "shirt"}
        model3d.current_outfit_state = lambda _c: (pieces, [], SIG)
        state = {"base": (BSIG, "basesha"), "older": set()}
        model3d._current_base = lambda _c: state["base"]
        model3d._on_older_base = lambda p, _b: p.stem in state["older"]
        model3d._stored_manifest = lambda _c, _s: {"pieces": pieces, "items": [], "mesh_variant": ""}
        import app.core.model_refs as model_refs
        model_refs.mesh_variant = lambda *_a, **_k: ""

        def write(stem, meta):
            (d / f"{stem}.glb").write_bytes(b"glb")
            (d / f"{stem}.json").write_text(json.dumps(meta))

        write(SIG, {"mesh_items": {"intended": ["x"]}})
        write(OTHER, {})
        write(BSIG, {"base": True})

        print("[1] current outfit model")
        p, m = model3d.find_model3d_serving("Demo")
        check("exact", (p.name, m), (f"{SIG}.glb", "exact"))
        print("[2] outfit model of an older body / another figure")
        state["older"] = {SIG}
        p, m = model3d.find_model3d_serving("Demo")
        check("plain body, not stale / nearest", (p.name, m), (f"{BSIG}.glb", "base"))
        print("[3] no outfit model")
        state["older"] = set()
        (d / f"{SIG}.glb").rename(d / "keep.glb")
        p, m = model3d.find_model3d_serving("Demo")
        check("plain body, not nearest", (p.name, m), (f"{BSIG}.glb", "base"))
        print("[4] no plain body file either")
        (d / f"{BSIG}.glb").rename(d / "keepbase.glb")
        check("nothing", model3d.find_model3d_serving("Demo"), (None, ""))
        (d / "keepbase.glb").rename(d / f"{BSIG}.glb")
        print("[5] off the pipeline")
        state["base"] = None
        p, m = model3d.find_model3d_serving("Demo")
        check("nearest stays for img2mesh", (p.name, m), (f"{OTHER}.glb", "nearest"))
        state["base"] = (BSIG, "basesha")
        (d / "keep.glb").rename(d / f"{SIG}.glb")

        print("[6] the worn plain body carries the ready pieces")
        fig = figure.Figure(signature=SIG, bsig=BSIG, shape=BSIG, texture="", in_body=(), painted=("pants",),
                            own=("boots",), left_out={"belt": "chain failed", "necklace": "chain failed"},
                            pieces={"feet": "boots", "waist": "belt", "neck": "necklace", "legs": "pants"})
        figure.delivered_figure_cached = lambda *_a, **_k: fig
        base_body.base_model_sha256 = lambda *_a, **_k: "basesha"
        meta = garment_assembly.bare_meta_of("Demo", d, BSIG)
        check("intended", meta["mesh_items"]["intended"], ["boots"])
        check("pieces", meta["pieces"], dict(fig.pieces))
        check("base identity", (meta["base_signature"], meta["base_model_sha256"]), (BSIG, "basesha"))
        print("[7] the figure stands on a meshed shape")
        on_shape = figure.Figure(**{**fig.__dict__, "shape": "ob12345678"})
        figure.delivered_figure_cached = lambda *_a, **_k: on_shape
        check("base sidecar as stored", garment_assembly.bare_meta_of("Demo", d, BSIG), {"base": True})
        print("[8] an outfit model keeps its sidecar")
        check("SIG sidecar", garment_assembly.bare_meta_of("Demo", d, SIG), {"mesh_items": {"intended": ["x"]}})

        print("[9] mesh_record")
        rec_fig = figure.Figure(signature=SIG, bsig=BSIG, shape=BSIG, texture="", in_body=(), painted=(),
                                own=("boots",), left_out={"belt": "chain failed", "coat": figure.LEFT_OFF_SHAPE})
        rec = base_body.mesh_record("Demo", rec_fig)
        check("intended / effective / unpainted / warnings",
              (rec["intended"], rec["effective"], rec["unpainted"], rec["warnings"]),
              (["belt", "boots"], ["boots"], ["belt", "boots", "coat"], []))

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
