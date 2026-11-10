#!/usr/bin/env python3
"""The dark-texel fill after the black-eye check (``app/core/face_polish.py``) and its wiring
(``model3d._face_polish_stage``, ``model_overview._dark_fill_step``, ``base_body.restore_face_texels``), on the
synthetic head of ``smoke_face_cleanup.py``; expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_face_polish.py

No world, no server, no hub. Fixture: the sphere head (R = 55 mm, front hemisphere planar-mapped into the left half
of a 1024^2 PNG, 3.72 texels per mm; skin (200, 150, 130), a lash ellipse 22 x 7 mm of (20, 20, 20) around each eye,
lips (197, 50, 70)). A simulated bake: the "projection" writes every texel of a disc of 30 mm around the face centre
(0, EYE_Y - 10 mm) EXCEPT the lash paint — that is exactly what the hub does on a mesh whose flaps stand outside its
face patch — by adding 20 to the red channel there; ``face_mask`` = the written texels.

Hand-derived expectations:
- fill=True (the gate failed): the candidates are the lash texels — dark (luma 20 < 0.5 x the median face luma ~158),
  unchanged against the original (the projection skipped them), within 8 mm of a projected texel in 3D (they sit
  INSIDE the face disc) — and every one of them is filled: ``filled`` >= 0.9 x the dark texels the front hemisphere
  rasterises (counted from the baked texture itself), and the region's near-black share ends under 0.5 % (it was the
  lash share of the region, above 2 %). A filled texel takes the inverse-distance mean of non-dark neighbours within
  25 mm, i.e. skin (200, 150, 130) or projected skin (220, 150, 130): R in 195..225, G in 145..155, B in 125..135.
  The torso texel (0.5, 0.95) and the back-of-head texel of the eye are untouched. ``changed`` covers every filled
  texel (plus atlas padding), so changed.sum() >= filled.
- fill=False (the gate passed): bytes come back identical, ``changed`` is None, no ``dark_fill`` key — but ``seam``
  is measured (the mask has texels on both sides of its edge on the front of the head): both bands present with
  pairs > 0; the projected tint of +20 red against untouched skin is a step of about dE 7 (CIE76 of (220,150,130)
  vs (200,150,130) = 7.3 at the edge band; median within 4..11 given the band's mix).
- ``_face_polish_stage`` on a fake operation (results face_gate {ok False}, bake {face_meta{baked}, has_mask True};
  files source/<sig>.glb = the bake, source/<sig>.json, bake/mask.npy = the written mask): afterwards the stage is
  done, source/<sig>.glb holds the filled bytes, bake/mask.npy is the written mask OR the changed texels (sum >= old
  + filled), the bake result's and the sidecar's ``baked.face_mask`` decode to that widened mask, ``mask_widened_by``
  >= filled, ``polish.dark_fill.filled`` == the direct run's; with face_gate {ok True} the stage records fill False,
  no dark_fill, and the source bytes stay.
- ``restore_face_texels`` with the WIDENED mask copies the filled lash texels into an outfit atlas that carries the
  projected face but still the dark lashes (the bake before the fill): face_texels_restored >= filled; with the
  unwidened mask nothing differs inside it, so it restores 0 — the lashes lie outside it.
- Overview rows (``model_overview``): ``_face_steps`` of a face record without ``polish`` has no dark_fill row (the
  fixture of smoke_model_overview.py stays as it is); with the stage's record: status done, detail "<n> texels
  filled · <before> → <after> near-black · seam ΔE <edge>"; fill False -> skipped "black-eye check passed · seam
  ΔE …"; status failed -> failed with the error; a share after above DARK_FILL_LIMIT (5 %) -> warning.
  ``_face_cleanup_step`` with a residue (after_mm.residual_max 2.7 > limit 2.0, unanchored 2) -> warning and
  "2 flap vertices left standing up to 2.7 mm" in the detail.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import smoke_face_cleanup as head  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _texture_of(glb):
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import _parse
    parsed = _parse(glb, "Source")
    prims, P, F, U, N, off = fc._body(parsed)
    index, tex, mime = fc._texture(parsed, prims[0])
    return parsed, prims, P, F, U, index, tex, mime


def _with_texture(glb, texture):
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import pack_glb
    parsed, prims, P, F, U, index, tex, mime = _texture_of(glb)
    binary = fc._replace_image(parsed, bytearray(parsed["bin"]), index, fc._encode(texture, mime))
    return pack_glb(parsed["gltf"], bytes(binary))


class FakeOp:
    """The slice of ``hub_ops.Operation`` the stage uses."""

    def __init__(self, root: Path, signature: str):
        self.dir = root
        self.inputs = {"signature": signature}
        self.state = {"done": [], "results": {}}

    def done(self, stage):
        return stage in self.state["done"]

    def result(self, stage):
        return dict(self.state["results"].get(stage) or {})

    def complete(self, stage, result=None):
        self.state["results"][stage] = dict(result or {})
        if stage not in self.state["done"]:
            self.state["done"].append(stage)

    def path(self, *parts):
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def abs(self, rel):
        return self.dir / rel


def main():
    from app.core import face_polish
    from app.core.base_body import restore_face_texels
    from app.core.face_retexture import face_mask_array, _near_black
    from app.core.model_overview import _dark_fill_step, _face_cleanup_step, _face_steps, DONE, FAILED, SKIPPED, WARNING

    glb, P0, F0, U0, ridge, opening = head.build_head()
    parsed, prims, P, F, U, index, tex, mime = _texture_of(glb)
    height, width = tex.shape[:2]
    # The simulated projection: a 30 mm disc around the face centre in planar coordinates, lash texels excluded.
    cols = (np.arange(width) + 0.5) / width
    rows = (np.arange(height) + 0.5) / height
    xs = (cols - 0.25) * head.R / 0.2
    ys = head.HEAD_Y - (rows - 0.5) * head.R / 0.2
    X, Y = np.meshgrid(xs, ys)
    disc = (np.hypot(X, Y - (head.EYE_Y - 10 * head.MM)) < 30 * head.MM) & (cols[None, :] >= 0.05) & (cols[None, :] <= 0.45)
    lash_px = np.all(tex[..., :3] == np.array(head.LASH, np.uint8), axis=2)
    mask = disc & ~lash_px
    baked_tex = tex.copy()
    baked_tex[mask, 0] = np.minimum(baked_tex[mask, 0].astype(int) + 20, 255).astype(np.uint8)
    baked = _with_texture(glb, baked_tex)
    bake_meta = {"face_mask": face_polish.pack_mask(mask), "texels_replaced": int(mask.sum())}
    check(np.array_equal(face_mask_array(bake_meta, width, height), mask), "fixture: face_mask round-trips through pack_mask")
    # The dark texels the front hemisphere rasterises (the candidates the fill must reach).
    covered = face_polish._covered(F, U, width, height)
    dark_covered = int((lash_px & covered & (cols[None, :] < 0.5)).sum())
    check(dark_covered > 1000, f"fixture: {dark_covered} dark lash texels under front triangles")

    out, record, changed = face_polish.polish(baked, glb, bake_meta, fill=True)
    fill = record.get("dark_fill") or {}
    check(out is not baked and changed is not None, "fill=True: bytes and a changed mask come back")
    check(fill.get("filled", 0) >= 0.9 * dark_covered,
          f"filled {fill.get('filled')} >= 0.9 x {dark_covered} dark texels")
    check(fill.get("dark_share_before", 0) > 0.02 and fill.get("dark_share_after", 1) < 0.005,
          f"region near-black {fill.get('dark_share_before')} -> {fill.get('dark_share_after')} (expected > 2 % -> < 0.5 %)")
    out_tex = _texture_of(out)[6]
    filled_px = lash_px & changed
    rgb = out_tex[filled_px][:, :3].astype(int)
    check(len(rgb) and np.all((rgb[:, 0] >= 195) & (rgb[:, 0] <= 225) & (rgb[:, 1] >= 145) & (rgb[:, 1] <= 155) & (rgb[:, 2] >= 125) & (rgb[:, 2] <= 135)),
          f"filled texels are skin-coloured (R {rgb[:, 0].min()}..{rgb[:, 0].max()}, G {rgb[:, 1].min()}..{rgb[:, 1].max()}, B {rgb[:, 2].min()}..{rgb[:, 2].max()})")
    check(int(changed.sum()) >= fill.get("filled", 0), f"changed mask {int(changed.sum())} covers the {fill.get('filled')} filled texels")
    eye_u, eye_v = head.planar_uv(head.EYE_X, head.EYE_Y, True)
    torso = (int(0.95 * height), int(0.5 * width))
    back = (int(eye_v * height), int(0.75 * width))
    check(np.array_equal(out_tex[torso], baked_tex[torso]) and np.array_equal(out_tex[back], baked_tex[back]),
          "torso and back-of-head texels untouched")
    check(float(_near_black(out_tex[..., :3])[lash_px & covered].mean()) < 0.1, "the covered lash paint is no longer near-black")

    same, record_off, changed_off = face_polish.polish(baked, glb, bake_meta, fill=False)
    seam = record_off.get("seam") or {}
    check(same is baked and changed_off is None and "dark_fill" not in record_off, "fill=False: bytes identical, nothing changed, no dark_fill")
    edge = seam.get("edge") or {}
    check(bool(edge) and bool(seam.get("wide")) and edge.get("pairs", 0) > 0 and 4.0 <= edge.get("de76_median", 0) <= 11.0,
          f"seam measured: edge dE {edge.get('de76_median')} ({edge.get('pairs')} pairs), wide {bool(seam.get('wide'))} (expected ~7)")

    # --- the stage ---------------------------------------------------------------------------------------------
    from app.core.model3d import _face_polish_stage
    with tempfile.TemporaryDirectory(prefix="face-polish-") as tmp:
        root = Path(tmp)
        sig = "0abc0abc0abc"
        for gate_ok in (False, True):
            op = FakeOp(root / ("failed" if not gate_ok else "passed"), sig)
            face_meta = {"status": "applied", "baked": dict(bake_meta)}
            op.path("source", f"{sig}.glb").write_bytes(baked)
            op.path("source", f"{sig}.json").write_text(json.dumps({"face_retexture": face_meta, "baked": dict(bake_meta)}))
            with op.path("bake", "mask.npy").open("wb") as handle:
                np.save(handle, mask)
            op.complete("bake", {"face_meta": face_meta, "has_mask": True})
            op.complete("face_gate", {"ok": gate_ok})
            _face_polish_stage("Demo", op, glb)
            polish = op.result("bake")["face_meta"].get("polish") or {}
            label = "gate passed" if gate_ok else "gate failed"
            check(op.done("face_polish") and polish.get("status") == "applied" and polish.get("fill") is (not gate_ok),
                  f"{label}: stage done, polish status {polish.get('status')}, fill {polish.get('fill')}")
            if gate_ok:
                check("dark_fill" not in polish and op.abs(f"source/{sig}.glb").read_bytes() == baked,
                      f"{label}: nothing filled, source bytes unchanged")
                continue
            check((polish.get("dark_fill") or {}).get("filled") == fill.get("filled"),
                  f"{label}: filled {(polish.get('dark_fill') or {}).get('filled')} == direct run {fill.get('filled')}")
            check(op.abs(f"source/{sig}.glb").read_bytes() == out, f"{label}: source/<sig>.glb holds the filled bytes")
            with op.abs("bake/mask.npy").open("rb") as handle:
                widened = np.load(handle)
            check(widened.shape == mask.shape and np.array_equal(widened, mask | changed) and int(widened.sum()) >= int(mask.sum()) + fill.get("filled", 0),
                  f"{label}: bake/mask.npy widened {int(mask.sum())} -> {int(widened.sum())}")
            new_baked = op.result("bake")["face_meta"]["baked"]
            decoded = face_mask_array(new_baked, width, height)
            check(decoded is not None and np.array_equal(decoded, widened) and new_baked.get("texels_replaced") == int(widened.sum()),
                  f"{label}: bake result face_mask decodes to the widened mask, texels_replaced {new_baked.get('texels_replaced')}")
            sidecar = json.loads(op.abs(f"source/{sig}.json").read_text())
            check(sidecar["face_retexture"].get("polish", {}).get("dark_fill") == polish["dark_fill"]
                  and sidecar["face_retexture"]["baked"]["face_mask"] == new_baked["face_mask"]
                  and sidecar["baked"]["face_mask"] == new_baked["face_mask"],
                  f"{label}: sidecar carries polish and the widened mask (both baked copies)")
            check(polish.get("mask_widened_by", 0) >= fill.get("filled", 0), f"{label}: mask_widened_by {polish.get('mask_widened_by')} >= filled")
            # The widened mask is what puts the filled lashes back into an outfit atlas.
            from PIL import Image
            atlas = io.BytesIO()
            Image.fromarray(baked_tex).save(atlas, "PNG")
            base_png = io.BytesIO()
            Image.fromarray(out_tex).save(base_png, "PNG")
            _b, _m, restored = restore_face_texels(atlas.getvalue(), "image/png", base_png.getvalue(),
                                                   {"face_retexture": {"status": "applied", "baked": new_baked}})
            _b, _m, narrow = restore_face_texels(atlas.getvalue(), "image/png", base_png.getvalue(),
                                                 {"face_retexture": {"status": "applied", "baked": bake_meta}})
            check(restored.get("face_texels_restored", 0) >= fill.get("filled", 0),
                  f"restore_face_texels with the widened mask copies {restored.get('face_texels_restored')} texels (>= {fill.get('filled')} filled)")
            check(narrow.get("face_texels_restored") == 0, f"with the unwidened mask it copies {narrow.get('face_texels_restored')} (the lashes lie outside it)")
            stage_record = polish

    # --- overview rows -----------------------------------------------------------------------------------------
    face = {"status": "applied", "backend": "FR", "reference": "face", "baked": {"texels_replaced": 1},
            "dark_gate": {"ok": False, "retried": True, "dark_share": 0.03, "photo_dark_share": 0.004, "warning": "dark"}}
    ids = [r["id"] for r in _face_steps(face)]
    check(ids == ["face_retexture", "dark_gate"], f"no polish record: rows {ids}")
    rows = _face_steps({**face, "polish": stage_record})
    row = rows[-1]
    want = (f"{stage_record['dark_fill']['filled']} texels filled · {stage_record['dark_fill']['dark_share_before'] * 100:.1f} % → "
            f"{stage_record['dark_fill']['dark_share_after'] * 100:.1f} % near-black · seam ΔE {stage_record['seam']['edge']['de76_median']}")
    check([r["id"] for r in rows] == ["face_retexture", "dark_gate", "dark_fill"] and row["status"] == DONE and row["detail"] == want,
          f"dark fill row: {row['status']} · {row['detail']}")
    check(row["numbers"]["filled"] == stage_record["dark_fill"]["filled"] and row["numbers"]["seam_edge_de"] == stage_record["seam"]["edge"]["de76_median"],
          "dark fill row numbers")
    skipped = _dark_fill_step({"version": 1, "fill": False, "status": "applied", "seam": stage_record["seam"]})
    check(skipped["status"] == SKIPPED and skipped["detail"].startswith("black-eye check passed · seam ΔE"), f"skipped row: {skipped['detail']}")
    check(_dark_fill_step({"status": "failed", "error": "boom"})["status"] == FAILED, "failed row")
    warn = _dark_fill_step({"fill": True, "status": "applied", "dark_fill": {"filled": 3, "dark_share_before": 0.2, "dark_share_after": 0.08}})
    check(warn["status"] == WARNING and "8.0 % near-black" in warn["detail"], f"warning above 5 %: {warn['status']} · {warn['detail']}")
    cleanup = {"status": "applied", "eyes": {"status": "applied", "limit_mm": 2.0, "eyes": [
        {"side": "left", "before_mm": {"lash_outer_max": 13.9}, "after_mm": {"lash_weighted_max": 1.6, "residual_max": 2.7},
         "moved_vertices": 180, "unanchored_vertices": 2},
        {"side": "right", "before_mm": {"lash_outer_max": 12.3}, "after_mm": {"lash_weighted_max": 1.9, "residual_max": None},
         "moved_vertices": 206, "unanchored_vertices": 0}]}, "mouth": {"status": "skipped", "reason": "natural"}}
    row = _face_cleanup_step({"face_cleanup": cleanup})
    check(row["status"] == WARNING and "lashes 13.9 → 1.9 mm proud · 2 flap vertices left standing up to 2.7 mm" in row["detail"],
          f"cleanup row with residue: {row['status']} · {row['detail']}")
    cleanup["eyes"]["eyes"][0]["after_mm"]["residual_max"] = None
    cleanup["eyes"]["eyes"][0]["unanchored_vertices"] = 0
    row = _face_cleanup_step({"face_cleanup": cleanup})
    check(row["status"] == DONE and "left standing" not in row["detail"], f"cleanup row without residue: {row['status']} · {row['detail']}")

    print()
    print("FAILED" if FAILS else "ALL OK", f"({len(FAILS)} failures)")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
