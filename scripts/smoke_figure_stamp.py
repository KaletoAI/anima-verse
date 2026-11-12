#!/usr/bin/env python3
"""The outfit model figure stamp (Ruling 6a) and the serving memo of the
delivered figure (Ruling 6b) — plan 2026-11-12-unified-worn-pieces Task 6.

Usage:
    ./.venv/bin/python scripts/smoke_figure_stamp.py

Runs against a THROWAWAY storage + instance directory with the ``human``
package copied in — no world, no hub, no GPU, no Blender, no server. Fixture
(the slim cut of scripts/smoke_outfit_rebuild_cost.py): Kira on the pipeline
with a ready base (``model3d/<bsig>.glb`` + sidecar rig mixamo, sha
``base_sha``) and the four base views, wearing six painted pieces (top,
bottom, feet, neck, head, outer) and holding three items; the worn signature
``sig``. Outfit models are hand-written sidecars (``source "base_body"``,
``pieces`` / ``items`` of the worn outfit, ``dressed`` true) WITHOUT a
recorded ``figure``:

  A  ``sig``           — base_signature bsig, base_model_sha256 base_sha, no
                         ``outfit_body_mode`` (retexture)
  B  ``aaaaaaaaaaaa``  — base_signature "base00000000" (an older base)
  C  ``bbbbbbbbbbbb``  — current base, ``outfit_body_mode`` "mesh" with
                         ``body_id`` "ob00000000" (no piece worn is in the
                         body: the rule before Task 6 calls it stale)

Derived by hand from the rule before Task 6 (base, variant, mode, outfit
body, own-mesh pieces — ``figure_migration.legacy_current``):

[S0] Before the stamp every model is stale for the figure rule
     (``base_body.figure_stale``: no figure recorded → "figure" for A and C;
     B is stale by its base first): outfit_info A ("stale", "figure").
[S1] ``stamp_figures_once`` with the re-key flag unset → None, nothing
     written (A still has no figure).
[S2] With the re-key flag set: → {"Kira": {sig: "stamped", aaaaaaaaaaaa:
     "stale", bbbbbbbbbbbb: "stale"}}; A's sidecar ``figure`` ==
     ``delivered_figure(Kira).as_dict()``; outfit_info A ("ready", None),
     its rebuild costs nothing (no hub job for a missing stamp); B and C keep
     no figure: outfit_info B ("stale", "older_base"), C ("stale",
     "figure") — stale as before.
[S3] A second run → None (flag set); A's sidecar unchanged.
[M1] ``delivered_figure_cached`` twice with the same inputs → the SAME
     object, ``delivered_figure`` ran once; after ``figure.invalidate()`` it
     runs again (a new object, equal to the first).
[M2] A worn item's mode changed (``update_item``: the top in_body) → a new
     key without any invalidate (the item content is in the key): no shape
     is built, so the interim rule delivers the top painted with its note —
     the cached figure's ``interim`` is {top: "Shown painted until its body
     shape is built"} (it was {} before).
[M3] Timing: one cold call (memo cleared) and the median warm call are
     printed; warm < 2 ms.
"""
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(rgb) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (8, 8), rgb).save(out, "PNG")
    return out.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-stamp-") as tmp:
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

        from app.core import base_body, figure, figure_migration, glb_delivery, model_refs
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        from app.models.world import set_world_setting

        model_refs.schedule_outfit_render = lambda *a, **k: None
        glb_delivery.delivery_path = lambda path, **kw: path

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
        check("create Kira", save_character_profile("Kira", dict(human), create_new=True), True)
        check("pipeline Kira", base_body.set_pipeline("Kira", True), True)
        bsig = base_body.base_signature("Kira")
        cdir = get_character_dir("Kira")
        mdir, refs = cdir / "model3d", cdir / "model_refs"
        mdir.mkdir(parents=True, exist_ok=True)
        refs.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        base_sha = hashlib.sha256(b"glb-Kira").hexdigest()
        for i, v in enumerate(base_body.BASE_VIEWS):
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png((10 * i, 20, 30)))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

        worn = {}
        for slot, name in (("top", "Blouse"), ("bottom", "Skirt"), ("feet", "Sandals"), ("neck", "Scarf"),
                           ("head", "Hat"), ("outer", "Coat")):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a {name.lower()}",
                                     outfit_piece={"slots": [slot], "covers": [], "outfit_types": ["casual"],
                                                   "mesh_mode": "painted"})["id"]
            inventory.add_to_inventory("Kira", iid)
            check(f"wears {name}", inventory.equip_piece("Kira", iid, source="smoke")["status"], "ok")
            worn[slot] = iid
        for name in ("Book", "Cup", "Lamp"):
            iid = inventory.add_item(name=name, category="tool", prompt_fragment=f"a {name.lower()}")["id"]
            inventory.add_to_inventory("Kira", iid)
        pieces, items, sig = model_refs.current_outfit_state("Kira")

        def model(signature, **extra):
            meta = {"character": "Kira", "signature": signature, "source": "base_body", "rig": "mixamo",
                    "pieces": dict(pieces), "items": list(items), "dressed": True,
                    "base_signature": bsig, "base_model_sha256": base_sha, **extra}
            (mdir / f"{signature}.glb").write_bytes(b"outfit-model")
            (mdir / f"{signature}.json").write_text(json.dumps(meta))

        def sidecar(signature):
            return json.loads((mdir / f"{signature}.json").read_text())

        def info(signature):
            got = base_body.outfit_info("Kira", signature=signature)
            return got["status"], got["stale_reason"]

        model(sig)
        model("aaaaaaaaaaaa", base_signature="base00000000", base_model_sha256="old")
        model("bbbbbbbbbbbb", outfit_body_mode="mesh", body_id="ob00000000", body_sha256="x")

        print("[S0] before the stamp")
        check("A stale: no figure", info(sig), ("stale", "figure"))

        print("[S1] the re-key has not run")
        check("waits", figure_migration.stamp_figures_once(), None)
        check("A unstamped", "figure" in sidecar(sig), False)

        print("[S2] the stamp")
        set_world_setting(figure_migration.REKEY_FLAG, "1")
        check("decisions", figure_migration.stamp_figures_once(),
              {"Kira": {sig: "stamped", "aaaaaaaaaaaa": "stale", "bbbbbbbbbbbb": "stale"}})
        check("A figure = delivered now", sidecar(sig).get("figure"), figure.delivered_figure("Kira").as_dict())
        check("A current", info(sig), ("ready", None))
        cost = base_body.rebuild_cost("Kira", sig)
        check("A costs no hub job", cost["mesh_jobs"], 0)
        check("B unstamped, stale (older base)", ("figure" in sidecar("aaaaaaaaaaaa"), info("aaaaaaaaaaaa")),
              (False, ("stale", "older_base")))
        check("C unstamped, stale (figure)", ("figure" in sidecar("bbbbbbbbbbbb"), info("bbbbbbbbbbbb")),
              (False, ("stale", "figure")))

        print("[S3] once only")
        before = (mdir / f"{sig}.json").read_text()
        check("second run", figure_migration.stamp_figures_once(), None)
        check("A unchanged", (mdir / f"{sig}.json").read_text(), before)

        print("[M1] memo")
        calls = []
        real = figure.delivered_figure

        def counted(*a, **k):
            calls.append(1)
            return real(*a, **k)

        figure.invalidate()
        with patch.object(figure, "delivered_figure", side_effect=counted):
            first = figure.delivered_figure_cached("Kira")
            second = figure.delivered_figure_cached("Kira")
            check("same object, one run", (first is second, len(calls)), (True, 1))
            figure.invalidate()
            third = figure.delivered_figure_cached("Kira")
            check("after invalidate: run again, equal", (third is first, third == first, len(calls)),
                  (False, True, 2))

        print("[M2] an item mode changed")
        op = dict(inventory.get_item(worn["top"])["outfit_piece"])
        op["mesh_mode"] = "in_body"
        inventory.update_item(worn["top"], {"outfit_piece": op})
        check("interim now", figure.delivered_figure_cached("Kira").interim,
              {worn["top"]: figure.INTERIM_PAINTED.format(what=figure.WHAT_SHAPE)})
        op["mesh_mode"] = "painted"
        inventory.update_item(worn["top"], {"outfit_piece": op})

        print("[M3] timing")
        cold = []
        for _ in range(5):
            figure.invalidate()
            t0 = time.perf_counter()
            figure.delivered_figure_cached("Kira")
            cold.append((time.perf_counter() - t0) * 1000)
        warm = []
        for _ in range(50):
            t0 = time.perf_counter()
            figure.delivered_figure_cached("Kira")
            warm.append((time.perf_counter() - t0) * 1000)
        print(f"  delivered_figure: cold median {statistics.median(cold):.2f} ms, "
              f"warm median {statistics.median(warm):.3f} ms (6 worn pieces, 3 held items)")
        check("warm < 2 ms", statistics.median(warm) < 2.0, True)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
