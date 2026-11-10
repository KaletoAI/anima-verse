#!/usr/bin/env python3
"""The edit-chain hair fit is gated by the hair's LENGTH CLASS (garments._fit -> garment_fit.hair_gates), like
the subtract method's fit (garment_subtract._gates).

Usage:
    ./.venv/bin/python scripts/smoke_garment_hair_fit_gates.py

Throwaway storage + instance with a copy of the repo's ``human`` package — no world, no hub, no Blender, no
server. Stubbed: ``garment_fit.fit_hair`` (records the ``gates`` it gets and gates the fixed metrics M with the
REAL ``garment_fit.gate``), ``base_body._snapshot_base_model``, ``model_refs.find_ref_image`` (a fixture PNG),
``garment_source.ensure_base_copy`` / ``fit_masks`` (no frame work). ``garments._fit`` itself is real.

Why (live case 2026-11-10): "short brunette hair" was refused with "moved_share 1 > 0.9" — short hair lies on
the scalp, so the push-out moves all of it by design; ``hair_gates`` drops ``moved_share`` for the short classes
("very short", "short"), the edit chain called ``fit_hair`` without ``gates=`` and got the default ``GATES``.

Fixture: Shorty (hair slot length "short") and Longa (length "long"), both on the pipeline, hair item worn,
an accepted prepared mesh + ghost front under F = "0123456789ab".
Metrics M = {bib_cm2 60, poke_share 0, scalp_uncovered_share 0.05, max_push_m 0.05, moved_share 1.0,
largest_component_share 1.0}: bib 60 > 50 refuses for both (so both raise ``_Refused`` and the recorded gates
can be read), moved_share 1.0 > 0.90 refuses only where it is gated.

Expected, by hand from ``garment_fit.GATES`` / ``hair_gates``:
[1] Shorty: fit_hair got gates without "moved_share" (5 keys); the refusal's reasons = exactly one, the bib;
    no reason names moved_share; the recorded limits have no "moved_share" key (they are the gates used).
[2] Longa: fit_hair got all 6 GATES keys; reasons = 2: the bib and "moved_share 1 > 0.9 (...)"; the
    recorded limits carry moved_share ["max", 0.9].
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
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-hair-fit-gates-") as tmp:
        root = Path(tmp)
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

        from app.core import base_body, garment_fit, garment_hair, garment_source, garment_store as gs, garments
        from app.core import model_refs
        from app.core.garment_fit import FitResult
        from app.models.character import get_character_profile, save_character_profile

        M = {"bib_cm2": 60.0, "poke_share": 0.0, "scalp_uncovered_share": 0.05, "max_push_m": 0.05,
             "moved_share": 1.0, "largest_component_share": 1.0}
        got = []

        def fit_hair(prepared, unrigged, rigged, bald=None, ghost=None, *, gates=None, **_kw):
            got.append(gates)
            ok, reasons = garment_fit.gate(M, gates)
            return FitResult(garment=None, metrics=dict(M), ok=ok, reasons=reasons, report={})

        garment_fit.fit_hair = fit_hair
        base_body._snapshot_base_model = lambda name, bsig: {"rigged": b"rigged", "unrigged": b"unrigged"}
        front = root / "front.png"
        front.write_bytes(b"\x89PNG-front")
        model_refs.find_ref_image = lambda name, kind, sig=None, *a, **k: front
        garment_source.ensure_base_copy = lambda *a, **k: None
        garment_source.fit_masks = lambda *a, **k: (None, None, {})

        F = "0123456789ab"

        def refusal(name, length):
            human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                     "character_appearance": "slender", "hair_method": "edit_chain",
                     "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                    "build": {"type": "athletic"}, "hair": {"length": length, "color": "brunette"}}}
            check(f"create {name}", save_character_profile(name, human, create_new=True), True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
            hid = garment_hair.ensure_hair_item(name)
            check(f"{name} length class", garment_hair.hair_length_class(name), length)
            prepared = gs.garment_path(name, hid, F, "prepared")
            ghost = gs.garment_path(name, hid, F, "image", step="ghost", view="front")
            for path in (prepared, ghost):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                gs.write_record(path.with_suffix(".json"), {"accepted": True})
            got.clear()
            try:
                garments._fit(name, hid, "hair", F, "base0000000a", get_character_profile(name) or {})
            except garments._Refused as e:
                return got[-1] if got else None, e.gates or {}
            return got[-1] if got else None, {}

        print("[1] short hair")
        gates, recorded = refusal("Shorty", "short")
        check("gates without moved_share", sorted(gates or {}), sorted(k for k in garment_fit.GATES if k != "moved_share"))
        reasons = recorded.get("reasons") or []
        check("one reason, the bib", [r.split(" ")[0] for r in reasons], ["bib_cm2"])
        check("no moved_share reason", any("moved_share" in r for r in reasons), False)
        check("recorded limits = the gates used", sorted(recorded.get("limits") or {}), sorted(gates or {}))

        print("[2] long hair")
        gates, recorded = refusal("Longa", "long")
        check("all GATES", sorted(gates or {}), sorted(garment_fit.GATES))
        reasons = recorded.get("reasons") or []
        check("two reasons", [r.split(" ")[0] for r in reasons], ["bib_cm2", "moved_share"])
        check("moved_share reason", any(r.startswith("moved_share 1 > 0.9") for r in reasons), True)
        check("recorded moved_share limit", (recorded.get("limits") or {}).get("moved_share"), ["max", 0.9])

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
