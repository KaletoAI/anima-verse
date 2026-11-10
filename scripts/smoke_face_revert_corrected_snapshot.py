#!/usr/bin/env python3
""""Revert face retexture" never restores a snapshot that already carries a face correction.

The incident (Lirien, 2026-11-10, Base body tab): the base model was face-corrected during its
generation ("Improve face before rigging"), so ``facefix/<sig>.glb`` existed before any explicit face
retexture. The re-applied face cleanup then ran a face retexture, whose ``_serial_model`` stage took the
rollback snapshot of the model AS IT WAS — the corrected one (its manifest lists ``facefix/<sig>.glb``).
The deterministic hub produced the same bytes again, and Revert restored that snapshot: byte-identical
files, the same content-versioned model URL, no preview reload, and a sidecar that claims ``reverted``
over a corrected face.

Hand-derived expectations on four fixture states of one signature (no hub, no Blender, no network):

1. corrected model + snapshot WITH ``facefix/<sig>.glb`` + retained ``unrigged/<sig>.glb``:
   ``face_info`` advertises ``rerig`` (b1c42502 advertised ``snapshot``); ``revert_face_retexture``
   re-rigs from ``unrigged/`` (``_rig_from_source`` receives a source under ``unrigged/``), the
   publication drops ``facefix/<sig>.*`` AND the stale snapshot, and the served model bytes change.
2. the same without ``unrigged/<sig>.glb``: nothing uncorrected is left — ``face_info`` advertises no
   revert (None) and the revert refuses with ``ok: False``, files untouched.
3. uncorrected model + snapshot WITHOUT ``facefix`` (the first explicit retexture's case): still
   ``snapshot`` — the byte-exact restore of smoke_face_retexture_rollback.py is unchanged.
4. a damaged snapshot (checksum mismatch) still refuses, also beside a retained unrigged source.

Usage: ./.venv/bin/python scripts/smoke_face_revert_corrected_snapshot.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

SIG = "base0123abcd"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        paths.init(Path(tmp) / "world")
        paths.init_instance(Path(tmp) / "instance")
        from app.core import db, face_retexture, model3d
        db.init_schema()
        root = Path(os.environ["STORAGE_DIR"]) / "characters" / "demo" / "model3d"

        def seed(*, corrected: bool, unrigged: bool, snapshot: bool = True) -> None:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True)
            face = {"status": "applied", "at": "2026-11-10T22:16:59+00:00"} if corrected else None
            (root / f"{SIG}.glb").write_bytes(b"rigged-corrected" if corrected else b"rigged-plain")
            (root / f"{SIG}.json").write_text(json.dumps({"rig": "mixamo", **({"face_retexture": face} if face else {})}))
            if corrected:
                (root / "facefix").mkdir()
                (root / "facefix" / f"{SIG}.glb").write_bytes(b"facefix-source")
                (root / "facefix" / f"{SIG}.json").write_text(json.dumps({"face_retexture": face}))
            if unrigged:
                (root / "unrigged").mkdir()
                (root / "unrigged" / f"{SIG}.glb").write_bytes(b"unrigged-source")
                (root / "unrigged" / f"{SIG}.json").write_text("{}")
            if snapshot:
                # Exactly what the face-retexture stage does: snapshot every
                # signature file as it stands, then park it under rollback/.
                face_retexture.prepare_snapshot(root, SIG)
                (root / "rollback").mkdir()
                os.replace(root / ".face-snapshot", root / "rollback" / SIG)

        def files() -> dict:
            return {str(r): p.read_bytes() for r, p in model3d._signature_files(root, SIG).items()}

        rig_sources = []

        def fake_rig(character_name, signature, source, **kwargs):
            # The real rig publishes a rigged model; the fake writes new
            # bytes and a sidecar without a face correction into the stage.
            rig_sources.append(Path(source).parent.name)
            out = model3d.get_model3d_dir(character_name)
            (out / f"{signature}.glb").write_bytes(b"rigged-from-unrigged")
            (out / f"{signature}.json").write_text(json.dumps({"rig": "mixamo"}))
            return {"ok": True, "path": str(out / f"{signature}.glb")}

        with patch.object(model3d, "_rig_from_source", side_effect=fake_rig), \
                patch.object(model3d, "required_rig", return_value="mixamo"), \
                patch.object(model3d, "_character_rig_options", return_value={"tail_motion": ""}):
            # 1. corrected snapshot + unrigged source -> re-rig, snapshot and facefix gone.
            seed(corrected=True, unrigged=True)
            manifest = json.loads((root / "rollback" / SIG / "manifest.json").read_text())
            assert f"facefix/{SIG}.glb" in {e["path"] for e in manifest["files"]}, manifest
            info = model3d.face_info("demo", root / f"{SIG}.glb")
            assert info["face_retexture_snapshot"]["ok"], info
            assert info["face_retexture_revert"] == "rerig", info["face_retexture_revert"]
            result = model3d.revert_face_retexture("demo", SIG)
            assert result.get("ok"), result
            assert rig_sources == ["unrigged"], rig_sources
            assert (root / f"{SIG}.glb").read_bytes() == b"rigged-from-unrigged"
            assert not (root / "facefix" / f"{SIG}.glb").exists()
            assert not (root / "rollback" / SIG).exists()
            assert model3d.face_info("demo", root / f"{SIG}.glb")["face_retexture_revert"] is None

            # 2. corrected snapshot, no unrigged source -> no revert offered, refused, untouched.
            seed(corrected=True, unrigged=False)
            assert model3d.face_info("demo", root / f"{SIG}.glb")["face_retexture_revert"] is None
            before = files()
            result = model3d.revert_face_retexture("demo", SIG)
            assert result.get("ok") is False and "face correction" in result.get("error", ""), result
            assert files() == before and len(rig_sources) == 1

            # 3. uncorrected snapshot -> the byte-exact snapshot restore stays.
            seed(corrected=False, unrigged=True)
            snapshot_bytes = (root / "rollback" / SIG / f"{SIG}.glb").read_bytes()
            (root / f"{SIG}.glb").write_bytes(b"rigged-after-a-retexture")
            meta = json.loads((root / f"{SIG}.json").read_text())
            (root / f"{SIG}.json").write_text(json.dumps({**meta, "face_retexture": {"status": "applied"}}))
            assert model3d.face_info("demo", root / f"{SIG}.glb")["face_retexture_revert"] == "snapshot"
            result = model3d.revert_face_retexture("demo", SIG)
            assert result.get("ok"), result
            assert (root / f"{SIG}.glb").read_bytes() == snapshot_bytes == b"rigged-plain"
            assert len(rig_sources) == 1, rig_sources

            # 4. damaged snapshot -> refused even with an unrigged source.
            seed(corrected=True, unrigged=True)
            (root / "rollback" / SIG / f"{SIG}.glb").write_bytes(b"corrupt")
            assert model3d.face_info("demo", root / f"{SIG}.glb")["face_retexture_revert"] is None
            before = files()
            assert not model3d.revert_face_retexture("demo", SIG).get("ok")
            assert files() == before and len(rig_sources) == 1
    print("PASS: a face-corrected rollback snapshot re-rigs the unrigged source (snapshot + facefix dropped), "
          "refuses without one, an uncorrected snapshot still restores byte-exact, a damaged one refuses")


if __name__ == "__main__":
    main()
