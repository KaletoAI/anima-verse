#!/usr/bin/env python3
"""The mesher's original (``model3d/unrigged/mesher/<sig>.glb``) goes and stays
with the unrigged source beside it (Finding A38, ``model3d._purge_combination``).

Usage:
    ./.venv/bin/python scripts/smoke_mesher_purge.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no server process.
``mesh_source.validate_source`` accepts everything; ``face_cleanup.clean_face``
is a recorder whose result is set per step (``applied`` appends b"-clean",
``skipped`` returns the bytes unchanged — what a mesh whose eyes are not found
gets).

The incident: a base body was meshed (cleanup applied, so the mesher's bytes
were retained), then meshed AGAIN under the same signature from new views; the
second mesh's cleanup was skipped, so nothing re-wrote the mesher file, and the
purge before the store did not reach the ``unrigged/mesher/`` subfolder. The
mesher file of the FIRST mesh stayed; "Re-apply face cleanup" starts from it
and published the old mesh as the source — its pose no longer matched the new
views, and the body retexture refused the back view.

Expected, derived by hand from the purge rule "the mesher original belongs to
unrigged/ and shares its preserve flags":
[1] Purge of SIG (keep_model SIG.glb) over SIG.glb, unrigged/SIG.glb+.json,
    unrigged/mesher/SIG.glb, facefix/SIG.glb and unrigged/mesher/OTHER.glb:
    left are SIG.glb and unrigged/mesher/OTHER.glb — 2 files.
[2] The same with preserve_unrigged: left SIG.glb, unrigged/SIG.glb,
    unrigged/SIG.json, unrigged/mesher/SIG.glb, unrigged/mesher/OTHER.glb
    (facefix goes) — 5 files.
[3] The same with preserve_sources: [2] plus facefix/SIG.glb — 6 files.
[4] The incident, through ``_store_unrigged_model`` and
    ``_reclean_face_source`` on character Demo, signature SIG:
    mesh 1 b"glTF-mesh-1", cleanup applied -> source b"glTF-mesh-1-clean",
    mesher file b"glTF-mesh-1";
    mesh 2 b"glTF-mesh-2", cleanup skipped -> source b"glTF-mesh-2", NO
    mesher file (the stale b"glTF-mesh-1" on the old code),
    ``face_cleanup_state`` mesher_retained False, can_reapply True;
    re-apply -> clean_face saw b"glTF-mesh-2" (b"glTF-mesh-1" on the old
    code), source b"glTF-mesh-2-clean", mesher file b"glTF-mesh-2".
[5] The store of [4] inside a model stage (``_serial_model``), a stale
    mesher file b"glTF-mesh-1" planted first, mesh 3 b"glTF-mesh-3" with its
    cleanup skipped: the published directory holds source b"glTF-mesh-3" and
    NO mesher file — the stage purged it, the publication drops by absence.

On 0c5f484df (before the fix) [1] keeps unrigged/mesher/0aaaaaaa.glb, and
[4] and [5] keep the stale b"glTF-mesh-1" (re-apply cleans it).
"""
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
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def files(directory: Path):
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mesher-purge-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import face_cleanup, mesh_source, model3d
        from app.models.character import get_character_dir, save_character_profile

        sig, other = "0aaaaaaa", "0bbbbbbb"

        def fixture(directory: Path):
            if directory.exists():
                shutil.rmtree(directory)
            for relative in (f"{sig}.glb", f"unrigged/{sig}.glb", f"unrigged/{sig}.json",
                             f"unrigged/mesher/{sig}.glb", f"facefix/{sig}.glb", f"unrigged/mesher/{other}.glb"):
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"glTF-" + relative.encode())
            return directory / f"{sig}.glb"

        print("[1] purge")
        plain = root / "purge"
        model3d._purge_combination(plain, sig, keep_model=fixture(plain))
        check("left", files(plain), [f"{sig}.glb", f"unrigged/mesher/{other}.glb"])

        print("[2] purge, preserve_unrigged")
        model3d._purge_combination(plain, sig, keep_model=fixture(plain), preserve_unrigged=True)
        check("left", files(plain), sorted([f"{sig}.glb", f"unrigged/{sig}.glb", f"unrigged/{sig}.json",
                                            f"unrigged/mesher/{sig}.glb", f"unrigged/mesher/{other}.glb"]))

        print("[3] purge, preserve_sources")
        model3d._purge_combination(plain, sig, keep_model=fixture(plain), preserve_sources=True)
        check("left", files(plain), sorted([f"{sig}.glb", f"unrigged/{sig}.glb", f"unrigged/{sig}.json",
                                            f"unrigged/mesher/{sig}.glb", f"unrigged/mesher/{other}.glb",
                                            f"facefix/{sig}.glb"]))

        print("[4] a second mesh of the same signature, its cleanup skipped")
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        model3d.set_model3d_options("Demo", {"face_cleanup": True})
        mesh_source.validate_source = lambda blob, **kw: {"ok": True}
        CLEANS = []
        outcome = {"status": "applied"}

        def fake_clean(blob, **kw):
            CLEANS.append(blob)
            if outcome["status"] == "applied":
                return blob + b"-clean", {"status": "applied", "version": face_cleanup.VERSION,
                                          "eyes": {"status": "skipped", "reason": "x"},
                                          "mouth": {"status": "skipped", "reason": "y"}}
            return blob, {"status": "skipped", "reason": "eyes not found"}

        face_cleanup.clean_face = fake_clean
        models = get_character_dir("Demo") / "model3d"
        source = models / "unrigged" / f"{sig}.glb"
        mesher = models / "unrigged" / "mesher" / f"{sig}.glb"

        def store(blob: bytes):
            delivered = root / "delivered.glb"
            delivered.write_bytes(blob)
            return model3d._store_unrigged_model("Demo", sig, {"path": str(delivered), "backend": "mesher"},
                                                 "mixamo", {})

        check("mesh 1 stored", store(b"glTF-mesh-1").get("ok"), True)
        check("mesh 1 source", source.read_bytes(), b"glTF-mesh-1-clean")
        check("mesh 1 mesher file", mesher.read_bytes(), b"glTF-mesh-1")
        outcome["status"] = "skipped"
        check("mesh 2 stored", store(b"glTF-mesh-2").get("ok"), True)
        check("mesh 2 source", source.read_bytes(), b"glTF-mesh-2")
        check("mesh 2 mesher file", mesher.read_bytes() if mesher.is_file() else None, None)
        state = model3d.face_cleanup_state("Demo", sig)
        check("state", (state["mesher_retained"], state["can_reapply"]), (False, True))
        outcome["status"] = "applied"
        del CLEANS[:]
        check("re-apply", model3d._reclean_face_source("Demo", sig).get("ok"), True)
        check("cleaned from", CLEANS, [b"glTF-mesh-2"])
        check("re-applied source", source.read_bytes(), b"glTF-mesh-2-clean")
        check("re-applied mesher file", mesher.read_bytes() if mesher.is_file() else None, b"glTF-mesh-2")

        print("[5] the same store inside a model stage: the publication drops the stale file by absence")
        mesher.write_bytes(b"glTF-mesh-1")
        outcome["status"] = "skipped"

        @model3d._serial_model
        def staged_store(character_name, signature):
            return store(b"glTF-mesh-3")

        check("mesh 3 stored", staged_store("Demo", sig).get("ok"), True)
        check("mesh 3 source", source.read_bytes(), b"glTF-mesh-3")
        check("mesh 3 mesher file", mesher.read_bytes() if mesher.is_file() else None, None)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
