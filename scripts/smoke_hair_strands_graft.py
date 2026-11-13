#!/usr/bin/env python3
"""The strand binding in the served GLB (``glb_mesh.GarmentMesh.extra_attributes`` / ``graft`` /
``garment_arrays``, ``garment_assembly._build`` / ``_state``) — strand-hair plan 2026-11-13, Task 5 (spec § 6.2.3
"Per-vertex binding"). Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_hair_strands_graft.py

No server, no hub, no Blender: a throwaway storage dir (``paths.init``) holds the garment files of the character
``demo``; outbound connections are refused. The body, the two hair cards (A down the back, B to the front, 35 true
rows of 4 vertices each) and the 4-vertex cap are the fixture of ``smoke_hair_strands_record.py`` (imported from
it), its fit written the same way (Task 2's graft path, fit record ``method: hairdeck``,
``report.vertices.hair`` 280). n = 2 * 35 * 4 + 4 = 284 vertices.

[1] Round trip: ``graft(body, g)`` with ``g.extra_attributes = {_STRAND_CARD: [1]*140 + [2]*140 + [0]*4 (uint16),
    _STRAND_U: k * 16 / 283 for k = 0..283 (float32)}`` then ``garment_arrays`` -> both arrays equal, uint16 /
    float32 exact; the primitive's accessors are SCALAR, componentType 5123 (UNSIGNED_SHORT) / 5126 (FLOAT); a
    garment without extra attributes writes neither (``garment_arrays`` reads ``{}``).
[2] The assembled full GLB (``_build`` with the real ``model3d._validator_for("mixamo")``) passes the validator —
    the custom attributes are no reason to refuse it — and ``rig_frames_preserved(bare, assembled)`` is ok.
[3] A 3-element ``_STRAND_U`` on a 4-vertex garment -> ValueError naming ``_STRAND_U``; a name outside
    ``^_STRAND_[A-Z]+$`` (``_strand_x``) -> ValueError; a card id 70000 (> 16 bits) -> ValueError.
[4] The low tier assembly carries no ``_STRAND_*`` attribute (even when its source is the full fit, i.e. no low
    file); the full tier carries both, equal to ``hair_strands.vertex_arrays(fit)`` (card + 1: A 1, B 2, cap 0);
    ``_state(wanted, "full")[item]["strands"]`` == sha256 of the fit's ``.strands.json`` == the sidecar's;
    the low tier's state has no ``strands`` key; the written full assembly is ``_current``; with the record's
    sidecars removed the state reads "" and the assembly is no longer ``_current`` (it re-assembles and the
    build writes the record again). A fit of another method (``edit_chain``) is grafted without attributes and
    ``strands`` "".
"""
import copy
import hashlib
import json
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_hair_strands_record as fx  # noqa: E402  (the Task 4 fixture: body, cards, fit)

FAILS = []
CHAR, ITEM, FSIG, NAME = fx.CHAR, fx.ITEM, fx.FSIG, fx.NAME


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _no_net(*_a, **_k):
    raise OSError("smoke: outbound connections are refused")


def strand_attrs(blob, name):
    from app.core.model_validate import parse_glb
    gltf = parse_glb(blob)["gltf"]
    node = next(n for n in gltf["nodes"] if n.get("name") == name)
    attrs = gltf["meshes"][node["mesh"]]["primitives"][0]["attributes"]
    return {k: gltf["accessors"][v] for k, v in attrs.items() if k.startswith("_STRAND")}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_hair_strands_graft_"))
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import db
    db.init_schema()
    from app.core import garment_assembly as ga, garment_store as gs, glb_mesh, hair_cards, hair_strands as hs
    from app.core.model_validate import rig_frames_preserved
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)
    target = fx.body_fixture()

    # [1] round trip
    g, F = fx.hair_garment()
    textured = hair_cards.texture_garment(g, hair_cards.hairdeck_cards(F, 280, 284))
    card = np.array([1] * 140 + [2] * 140 + [0] * 4, np.uint16)
    u = (np.arange(284) * 16 / 283).astype(np.float32)
    with_attrs = copy.copy(textured)
    with_attrs.extra_attributes = {"_STRAND_CARD": card, "_STRAND_U": u}
    blob = glb_mesh.graft(target, with_attrs, name=NAME, extras={"kind": "hair"})
    back = glb_mesh.garment_arrays(blob, node_prefix=NAME, exact=True).extra_attributes
    check(set(back) == {"_STRAND_CARD", "_STRAND_U"}, f"[1] both attributes read back ({sorted(back)})")
    check(back["_STRAND_CARD"].dtype == np.uint16 and np.array_equal(back["_STRAND_CARD"], card),
          "[1] _STRAND_CARD uint16, equal")
    check(back["_STRAND_U"].dtype == np.float32 and np.array_equal(back["_STRAND_U"], u), "[1] _STRAND_U float32, equal")
    acc = strand_attrs(blob, NAME)
    check(acc["_STRAND_CARD"]["componentType"] == 5123 and acc["_STRAND_CARD"]["type"] == "SCALAR"
          and acc["_STRAND_U"]["componentType"] == 5126 and acc["_STRAND_U"]["type"] == "SCALAR"
          and acc["_STRAND_U"]["count"] == 284, "[1] accessors SCALAR 5123 / 5126, 284 each")
    plain = glb_mesh.graft(target, textured, name=NAME, extras={"kind": "hair"})
    check(strand_attrs(plain, NAME) == {} and glb_mesh.garment_arrays(plain).extra_attributes == {},
          "[1] no extra attributes: none written, none read")

    # [3] refusals
    cap = glb_mesh.GarmentMesh(positions=np.eye(4, 3), normals=None, uvs=np.zeros((4, 2)),
                               indices=np.array([[0, 1, 2], [0, 2, 3]]), joints=np.zeros((4, 4), np.int64),
                               weights=np.tile([1.0, 0, 0, 0], (4, 1)), joint_names=["mixamorig:Head"])

    def refused(extra, word):
        bad = copy.copy(cap)
        bad.extra_attributes = extra
        try:
            glb_mesh.graft(target, bad, name="garment_hair_x", extras={})
        except ValueError as e:
            return word in str(e)
        return False
    check(refused({"_STRAND_U": np.zeros(3, np.float32)}, "_STRAND_U"), "[3] 3 values for 4 vertices -> ValueError naming _STRAND_U")
    check(refused({"_strand_x": np.zeros(4, np.float32)}, "_strand_x"), "[3] a name outside _STRAND_[A-Z]+ -> ValueError")
    check(refused({"_STRAND_CARD": np.array([0, 1, 2, 70000])}, "16 bits"), "[3] a card id beyond 16 bits -> ValueError")

    # the fit, its record and the assembly
    fit, _faces_before, _faces_served = fx.write_fit(target)
    directory = tmp / "model3d"
    directory.mkdir()
    sig = "outfit0123ab"
    bare = ga.bare_path(directory, sig, ga.FULL)
    bare.write_bytes(target)
    bare.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    (directory / ga.LOW).mkdir()
    bare_low = ga.bare_path(directory, sig, ga.LOW)
    bare_low.write_bytes(target)
    bare_low.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    from app.core import model3d
    validator = model3d._validator_for("mixamo", CHAR)
    ga._model3d = lambda: SimpleNamespace(_validator_for=model3d._validator_for, ASSEMBLED_DIR="assembled")
    wanted = [{"item_id": ITEM, "kind": "hair", "fsig": FSIG, "fit": fit, "low": None, "record": {}}]

    # [2] + [4] full tier
    full, side, _rev = ga._build(CHAR, directory, bare, wanted, ga.FULL)
    verdict = validator(full)
    check(verdict.get("ok") is True, f"[2] the assembled full GLB validates ({verdict.get('errors')})")
    check(rig_frames_preserved(target, full).get("ok") is True, "[2] rig_frames_preserved")
    arrays = hs.vertex_arrays(fit)
    got = glb_mesh.garment_arrays(full, node_prefix=NAME, exact=True).extra_attributes
    check(arrays is not None and set(got) == {"_STRAND_CARD", "_STRAND_U"}, f"[4] full tier: both attributes ({sorted(got)})")
    check(np.array_equal(got["_STRAND_CARD"], arrays["card"]) and np.array_equal(got["_STRAND_U"], arrays["u"]),
          "[4] full tier: the record's npz values")
    check(got["_STRAND_CARD"].tolist() == [1] * 140 + [2] * 140 + [0] * 4, "[4] card + 1: A 1, B 2, cap 0")
    json_path, npz_path = hs.sidecar_paths(fit)
    sha = hashlib.sha256(json_path.read_bytes()).hexdigest()
    state = ga._state(wanted, ga.FULL)
    check(state[ITEM].get("strands") == sha, f"[4] _state full strands == the record's sha ({state[ITEM].get('strands')})")
    check(side["garments"][ITEM].get("strands") == sha, "[4] the build's sidecar carries it")
    check(ga._state(wanted, ga.FULL, character_name=CHAR)[ITEM]["strands"] == sha,
          "[4] with the character's collision scales: the same sha")

    # [4] low tier (no low file: the source is the full fit)
    low_blob, low_side, _ = ga._build(CHAR, directory, bare_low, wanted, ga.LOW)
    check(strand_attrs(low_blob, NAME) == {}, "[4] low tier (full fit as source): no _STRAND_* attribute")
    check("strands" not in low_side["garments"][ITEM] and "strands" not in ga._state(wanted, ga.LOW)[ITEM],
          "[4] the low tier's state has no strands")
    low = gs.garment_path(CHAR, ITEM, FSIG, "low")
    low.parent.mkdir(parents=True, exist_ok=True)
    low.write_bytes(full)       # a low file that (wrongly) carried the attributes is grafted without them
    wanted_low = [dict(wanted[0], low=low)]
    low_blob2, _s, _ = ga._build(CHAR, directory, bare_low, wanted_low, ga.LOW)
    check(strand_attrs(low_blob2, NAME) == {}, "[4] low tier from a low file: no _STRAND_* attribute")

    # currency
    assembled = ga.assembled_path(directory, sig, ga.FULL)
    assembled.parent.mkdir(parents=True, exist_ok=True)
    assembled.write_bytes(full)
    assembled.with_suffix(".json").write_text(json.dumps(side))
    check(ga._current(assembled, bare, ga._state(wanted, ga.FULL, character_name=CHAR)) is True, "[4] _current")
    json_path.unlink()
    npz_path.unlink()
    check(ga._state(wanted, ga.FULL)[ITEM]["strands"] == "", "[4] record gone: strands ''")
    check(ga._current(assembled, bare, ga._state(wanted, ga.FULL, character_name=CHAR)) is False,
          "[4] record gone: no longer _current")
    _full2, side2, _ = ga._build(CHAR, directory, bare, wanted, ga.FULL)
    check(json_path.is_file() and side2["garments"][ITEM]["strands"] == hashlib.sha256(json_path.read_bytes()).hexdigest(),
          "[4] the re-assembly writes the record again and carries its sha")

    rec = gs.read_record(fit.with_suffix(".json"))
    gs.write_record(fit.with_suffix(".json"), {**rec, "method": "edit_chain"})
    json_path.unlink()
    npz_path.unlink()
    other, side3, _ = ga._build(CHAR, directory, bare, wanted, ga.FULL)
    check(strand_attrs(other, NAME) == {} and side3["garments"][ITEM]["strands"] == "",
          "[4] a fit of another method: no attributes, strands ''")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
