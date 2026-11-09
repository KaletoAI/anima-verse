#!/usr/bin/env python3
"""Exposed-only rig groups and the face protections of the base body, by hand.

Usage:
    ./.venv/bin/python scripts/smoke_base_body_detail_face.py

No world, no server, no Blender, no hub. The model-level flow (covered
variant, outfit choice, staleness, the forced extension rig of an outfit) is
scenario [12] of scripts/smoke_base_body_outfit.py; this script covers the
pure pieces.

[1] RigSpec.parse: ``exposed_only`` defaults to False, ``true`` parses, a
    non-boolean ("yes", 1) is a ValueError naming ``rig.exposed_only``.
[2] piece_covering_slots(occupied {top}, piece {slots [top], covers [neck],
    partially_covers [hip]}) = {top, neck, hip}.
    hides_exposed_detail with ONE exposed_only group covered_by [chest_c]
    (and a plain group covered_by [legs] that never counts):
      nothing worn                                   -> False
      shirt slot chest_c, no flag                    -> True
      shirt slot chest_c, exposed_detail true        -> False
      sheer top (flag) + jacket covers chest_c       -> True  (ANY hiding piece)
      sheer top (flag) + vest partially_covers it    -> True  (partial counts)
      trousers slot legs (plain group's slot only)   -> False
      exposed_detail "true" (a string, not True)     -> True  (only real true)
    without an exposed_only group                    -> False
[3] _extension_groups_for: a base drops PART_OPS (attached_part); a covered
    variant (base + base_variant covered) also drops exposed_only; an outfit
    built from it (base_variant covered, no base) keeps the part, drops the
    exposed_only group; a rigged outfit keeps all three.
[4] restore_face_texels, base colour 4x4 (100,50,25,255), atlas 4x4
    (0,0,0,255) with (0,0) already (100,50,25,255); face mask texels 0,1,4
    (row-major: (0,0),(1,0),(0,1)) -> packbits bytes C8 00:
    restored 2 (texel 0 already equal), mask 3; atlas (1,0) and (0,1) now
    (100,50,25), (2,0) stays black; mime image/png. A mask that matches
    nothing changed -> 0 restored and the input bytes unchanged. No face
    correction -> 0 + "no face mask"; an 8x8 atlas against the 4x4 base ->
    0 + "face mask does not match the atlas size". face_mask_array of the
    4x4 mask at 5x5 -> None.
[5] Dark gate. Photo 20x20 white, subject square x/y 2..17 (180,140,120;
    luma 147.0), a black 3x3 block at 8..10. Subject eroded by 3 px (7x7
    MinFilter) = 5..14 -> 100 pixels, 9 near-black -> photo_dark_share 0.09.
    dark_share 0.104 -> excess 0.014 <= 0.015 ok; 0.106 -> 0.016 fail;
    no dark_share -> ok, skipped.
[6] _dark_face_gate on a fake hub record (signature s1, photo of [5]):
    (a) first bake 0.10 -> passes, no retry, chosen first, bake result keeps
        its files, face_meta.dark_gate ok; the source sidecar gains it.
    (b) first 0.20 (excess 0.11) -> one retry with yaw 0 + 3 = 3.0 (no head
        twist recorded); retry 0.12 (excess 0.03, still failing but darker
        less) -> chosen retry, its source glb/json and mask copied over the
        first, ok False, warning DARK_FACE_WARNING.
    (c) first 0.20, retry 0.30 -> chosen first, files of the first kept,
        warning.
    (d) first 0.20, prerig head twist -4.0 -> retry yaw 10 - 3 = 7.0;
        retry 0.095 (excess 0.005) -> ok True, no warning.
    (e) the retry raises RuntimeError -> first kept, retry_error recorded,
        warning; the gate never fails the correction.
"""
import base64
import io
import json
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def png(size, fill, pixels=None):
    im = Image.new("RGBA", size, fill)
    for xy, rgba in (pixels or {}).items():
        im.putpixel(xy, rgba)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def px(data, xy):
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGBA").getpixel(xy)


def photo():
    im = Image.new("RGB", (20, 20), (255, 255, 255))
    for x in range(2, 18):
        for y in range(2, 18):
            im.putpixel((x, y), (180, 140, 120))
    for x in range(8, 11):
        for y in range(8, 11):
            im.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


class FakeOp:
    """The parts of a hub record ``_dark_face_gate`` touches."""

    def __init__(self, root: Path, signature: str):
        self.dir, self.inputs, self.results = root, {"signature": signature}, {}

    def path(self, *parts):
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def abs(self, rel):
        return self.dir / rel

    def done(self, name):
        return name in self.results

    def result(self, name):
        return self.results.get(name) or {}

    def complete(self, name, data):
        self.results[name] = data


def main() -> int:
    from app.plugins.registry import RigSpec
    from app.core.rig_contract import BASE_JOINT_NAMES
    from app.core import extension_rig, face_retexture, model3d
    from app.core.base_body import restore_face_texels

    print("[1] RigSpec exposed_only")
    rig = {"id": "g", "op": "jiggle", "chains": [[{"bone": "ExtraOne", "parent": BASE_JOINT_NAMES[0]}]]}
    check("default", RigSpec.parse(rig).exposed_only, False)
    check("true", RigSpec.parse({**rig, "exposed_only": True}).exposed_only, True)
    for bad in ("yes", 1):
        try:
            RigSpec.parse({**rig, "exposed_only": bad})
            check(f"{bad!r} refused", "accepted", "ValueError")
        except ValueError as exc:
            check(f"{bad!r} refused", "rig.exposed_only" in str(exc), True)

    print("[2] covering pieces")
    check("piece_covering_slots", extension_rig.piece_covering_slots(
        {"top"}, {"slots": ["top"], "covers": ["neck"], "partially_covers": ["hip"]}), {"top", "neck", "hip"})
    groups = [{"id": "d", "exposed_only": True, "covered_by": ["chest_c"]},
              {"id": "p", "covered_by": ["legs"]}]
    items = {
        "shirt": {"outfit_piece": {"slots": ["chest_c"]}},
        "sheer": {"outfit_piece": {"slots": ["chest_c"], "exposed_detail": True}},
        "jacket": {"outfit_piece": {"slots": ["outer"], "covers": ["chest_c"]}},
        "vest": {"outfit_piece": {"slots": ["outer"], "partially_covers": ["chest_c"]}},
        "trousers": {"outfit_piece": {"slots": ["legs"]}},
        "stringy": {"outfit_piece": {"slots": ["chest_c"], "exposed_detail": "true"}},
    }
    cases = [("nothing worn", {}, False), ("shirt", {"chest_c": "shirt"}, True),
             ("sheer", {"chest_c": "sheer"}, False),
             ("sheer + jacket", {"chest_c": "sheer", "outer": "jacket"}, True),
             ("sheer + vest (partial)", {"chest_c": "sheer", "outer": "vest"}, True),
             ("trousers", {"legs": "trousers"}, False), ("string flag", {"chest_c": "stringy"}, True)]
    for label, pieces, want in cases:
        check(f"hides: {label}", extension_rig.hides_exposed_detail(groups, pieces, items), want)
    check("hides: no exposed_only group", extension_rig.hides_exposed_detail(groups[1:], {"chest_c": "shirt"}, items),
          False)

    print("[3] _extension_groups_for")
    decl = [{"id": "part", "op": "attached_part"}, {"id": "d", "op": "pair_tip", "exposed_only": True},
            {"id": "j", "op": "jiggle"}]
    ids = lambda meta: [g["id"] for g in model3d._extension_groups_for(meta, decl)]  # noqa: E731
    check("base", ids({"base": True}), ["d", "j"])
    check("covered variant", ids({"base": True, "base_variant": "covered"}), ["j"])
    check("outfit on covered", ids({"base_variant": "covered"}), ["part", "j"])
    check("outfit on rigged", ids({"base_variant": "rigged"}), ["part", "d", "j"])

    print("[4] restore_face_texels")
    skin = (100, 50, 25, 255)
    base_img = png((4, 4), skin)
    atlas = png((4, 4), (0, 0, 0, 255), {(0, 0): skin})
    packed = bytes([0xC8, 0x00])
    meta = {"face_retexture": {"status": "applied",
                               "baked": {"face_mask": base64.b64encode(zlib.compress(packed)).decode()}}}
    out, mime, record = restore_face_texels(atlas, "image/png", base_img, meta)
    check("record", record, {"face_texels_restored": 2, "face_mask_texels": 3})
    check("restored texels", [px(out, xy) for xy in ((0, 0), (1, 0), (0, 1), (2, 0))],
          [skin, skin, skin, (0, 0, 0, 255)])
    check("mime", mime, "image/png")
    same, _, record = restore_face_texels(base_img, "image/png", base_img, meta)
    check("nothing to restore", (record["face_texels_restored"], same == base_img), (0, True))
    _, _, record = restore_face_texels(atlas, "image/png", base_img, {})
    check("no face correction", record, {"face_texels_restored": 0, "face_texels_skipped": "no face mask"})
    _, _, record = restore_face_texels(png((8, 8), (0, 0, 0, 255)), "image/png", base_img, meta)
    check("size mismatch", record, {"face_texels_restored": 0,
                                    "face_texels_skipped": "face mask does not match the atlas size"})
    check("face_mask_array other size", face_retexture.face_mask_array(meta["face_retexture"]["baked"], 5, 5), None)

    print("[5] dark gate")
    photo_bytes = photo()
    check("photo_dark_share", round(face_retexture.photo_dark_share(photo_bytes), 6), 0.09)
    gate = face_retexture.dark_face_gate({"dark_share": 0.104}, photo_bytes)
    check("0.104 passes", (gate["ok"], gate["excess"]), (True, 0.014))
    gate = face_retexture.dark_face_gate({"dark_share": 0.106}, photo_bytes)
    check("0.106 fails", (gate["ok"], gate["excess"], gate["limit"]), (False, 0.016, 0.015))
    check("unmeasured passes", face_retexture.dark_face_gate({}, photo_bytes), {"ok": True, "skipped": "not measured"})

    print("[6] _dark_face_gate")
    tmp = Path(tempfile.mkdtemp(prefix="detail-face-"))
    twist = {}
    original_dir = model3d.get_model3d_dir
    model3d.get_model3d_dir = lambda name: tmp / "model3d"
    (tmp / "model3d" / "prerig").mkdir(parents=True)

    def run(first, retry, *, yaw=0.0, head=None, raises=False):
        root = tmp / f"op{len(list(tmp.iterdir()))}"
        op = FakeOp(root, "s1")
        sidecar = tmp / "model3d" / "prerig" / "s1.json"
        sidecar.write_text(json.dumps({"blender": {"head_twist": {"before": {"head": head}}}} if head is not None else {}))
        op.path("source", "s1.glb").write_bytes(b"first-glb")
        op.path("source", "s1.json").write_text(json.dumps({"face_retexture": {"status": "applied"}, "baked": {}}))
        op.path("bake", "mask.npy").write_bytes(b"first-mask")
        op.complete("bake", {"face_meta": {"status": "applied", "baked": {"dark_share": first}}, "has_mask": True})
        seen = []

        def attempt(face_stage, bake_stage, prefix, controls):
            seen.append((face_stage, bake_stage, prefix, controls.get("yaw")))
            if raises:
                raise RuntimeError("hub lost")
            op.path(*prefix, "source", "s1.glb").write_bytes(b"retry-glb")
            op.path(*prefix, "source", "s1.json").write_text(json.dumps({"baked": {}}))
            op.path(*prefix, "bake", "mask.npy").write_bytes(b"retry-mask")
            op.complete(bake_stage, {"face_meta": {"status": "applied", "baked": {"dark_share": retry}},
                                     "has_mask": True})
            return {"ok": True}

        model3d._dark_face_gate("Demo", op, attempt, {"yaw": yaw, "strength": 1.0}, photo_bytes)
        record = op.result("face_gate")
        files = (op.abs("source/s1.glb").read_bytes(), op.abs("bake/mask.npy").read_bytes())
        stored = json.loads(op.abs("source/s1.json").read_text())["face_retexture"]["dark_gate"]
        return seen, record, files, op.result("bake"), stored

    try:
        seen, record, files, bake, stored = run(0.10, None)
        check("(a) no retry", (seen, record["retried"], record["chosen"], record["ok"]), ([], False, "first", True))
        check("(a) files kept", files, (b"first-glb", b"first-mask"))
        check("(a) dark_gate in face_meta and sidecar", (bake["face_meta"]["dark_gate"] == record, stored == record),
              (True, True))
        seen, record, files, bake, _ = run(0.20, 0.12)
        check("(b) one retry, yaw 3", seen, [("face_retry", "bake_retry", ("retry",), 3.0)])
        check("(b) retry chosen", (record["chosen"], record["ok"], record.get("warning")),
              ("retry", False, model3d.DARK_FACE_WARNING))
        check("(b) retry files", files, (b"retry-glb", b"retry-mask"))
        check("(b) bake result = retry", bake["face_meta"]["baked"]["dark_share"], 0.12)
        _, record, files, bake, _ = run(0.20, 0.30)
        check("(c) first kept", (record["chosen"], files, bake["face_meta"]["baked"]["dark_share"]),
              ("first", (b"first-glb", b"first-mask"), 0.20))
        check("(c) warning", record.get("warning"), model3d.DARK_FACE_WARNING)
        seen, record, _, _, _ = run(0.20, 0.095, yaw=10.0, head=-4.0)
        check("(d) yaw against the head twist", seen[0][3], 7.0)
        check("(d) retry passes", (record["chosen"], record["ok"], "warning" in record), ("retry", True, False))
        _, record, files, _, _ = run(0.20, None, raises=True)
        check("(e) failed retry keeps the first", (record["chosen"], files, record.get("retry_error"),
                                                   record.get("warning")),
              ("first", (b"first-glb", b"first-mask"), "hub lost", model3d.DARK_FACE_WARNING))
    finally:
        model3d.get_model3d_dir = original_dir
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print(f"\nFAILED: {len(FAILS)}: " + "; ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
