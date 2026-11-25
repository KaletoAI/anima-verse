#!/usr/bin/env python3
"""Smoke: the per-request read scope (plan 2026-11-24-figure-poll-caches, Task 5) — ``read_scope.scope`` / ``memo`` /
``obj_sig`` / ``clear`` and the four memoised reads ``drape_state``, ``cut_key``, ``garment_fsig``,
``get_character_profile``.

Usage:
    ./.venv/bin/python scripts/smoke_read_scope.py

Runs without a server, LLM, HTTP or Blender on a throwaway world (``STORAGE_DIR`` / ``INSTANCE_DIR`` set to temp
dirs and ``paths.init(<tmp>)`` BEFORE any world-DB module is imported). Expected values, by hand:

[S1] Inside ``scope()``: memo("x", 1, f) three times -> the first call misses and runs f, the next two hit -> f ran
     1x. Without a scope memo just calls f -> three calls, f ran 3x.
[S2] scope() inside scope() reuses the outer memo dict: memo("x", 1, f) in the outer, then again in the inner ->
     the inner call hits the outer entry -> f ran 1x in total.
[S3] r = memo("x", 1, lambda: {"a": {"b": 1}}); the FIRST caller sets r["a"]["b"] = 9 -> the entry is a deep copy, so
     the next hit is {"a": {"b": 1}}; that hit mutated likewise -> the third hit is still {"a": {"b": 1}}.
[S4] memo("x", 1, f), clear(), memo("x", 1, f) -> f ran 2x. The same with each writer instead of clear():
     garment_store.write_record(p, {...}) (it calls figure.invalidate), figure.invalidate() itself and
     save_character_profile("demo", ...) (no generation move, an explicit clear) -> 2x each.
[S5] A threading.Thread started inside a scope starts with an empty context: its memo("x", 1, f) computes (f +1,
     nothing inherited, total 2 with the scope's own call). After the scope memo("x", 1, f) computes again
     (+1 -> 3): nothing of the scope survives it.
[S6] f raises KeyError inside a scope -> memo raises KeyError, nothing stored -> the next memo calls f again
     (f ran 2x, the second call answers its value).
[S7] tmp world, a template piece "top6" (the fixture of smoke_template_cut_first.py [6]: ``_key`` stubbed to tsig
     "tz", ``sig_of`` to "cA", an accepted drape GLB + record of "tz" with cut_sig "cA" on disk): drape_state twice
     in one scope -> the inner body runs once (``read_scope.measure`` counts tally "drape_state" = 1), both results
     ``==`` (state "ready", tsig "tz"), and the two ``record`` dicts are not the same object (each call a copy).
[S8] get_character_profile("demo") in a scope, the returned dict mutated (poison key) -> the next read has no poison
     key and the inner body ran once (tally "profile" = 1 for the two reads). save_character_profile("demo", ...
     smoke_marker "two") in the same scope -> the next get_character_profile gives smoke_marker "two" (the save
     cleared the scope). get_item is NOT in the scope (no Task 0 baseline showed a three-digit count), so no item
     check.
[S9] Source guard (ast over every app/**/*.py, a file scan, untracked files included): ``read_scope.scope(`` occurs
     exactly 4x, in figure_build._figure_info, figure_build._compute_open, routes/figure._template_cut_payload and
     routes/characters.get_character_model3d; figure_build._run_step_inner, figure_batch.py, garment_refit.py and
     refit_pool.py contain none.
[S10] Fixture of smoke_template_cut_first.py [3] (item, picture, routing, media and the drape stubbed; the inner
     ``_cut_key`` body stubbed to the ready key "c1" and counting tally "cut_key"; ``gtc.run`` stubbed to a run that
     waits on a threading.Event, then writes the ready cut). Counted with ``measure`` around one request:
     - cut missing: the unscoped body (``_template_cut_body``) computes the cut key 3x — ``gtc.schedule`` (1; it
       starts the waiting run), ``dialog_state`` -> ``status`` -> ``current_csig`` -> ``current_pattern`` -> ``state``
       (2) and ``dialog_state``'s own ``current_pattern`` (3); ``_template_cut_payload`` (scoped) 1x; both answers ==
       (state "cutting" for both: the run started by the first one still waits).
     - the event set, the run ends (ready cut "c1" on disk): unscoped 3x again (``schedule`` returns at "ready" after
       its one key, then the same two), scoped 1x; answers ==.
[S11] obj_sig: the same dict twice inside a scope -> figure._canonical runs 1x; another dict with equal content ->
     the same value (and _canonical +1 for the new object); without a scope the same dict twice -> 2 runs.
"""
import ast
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_read_scope_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "reference.fbx")
for d in ("world", "instance", "clips"):
    (TMP / d).mkdir()

from app.core import paths  # noqa: E402

paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))
(TMP / "world" / "config.json").write_text("{}", encoding="utf-8")
(TMP / "instance" / "config.json").write_text("{}", encoding="utf-8")
from app.core import config as _cfg  # noqa: E402

_cfg.load(TMP / "world" / "config.json", TMP / "instance" / "config.json")
from app.core import db  # noqa: E402

db.init_schema()

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("OK   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        FAILS.append(label)


class Counter:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return {"n": self.n}


def main() -> int:
    from app.core import figure, read_scope
    from app.core.read_scope import clear, memo, scope
    from app.models.character import get_character_profile, save_character_profile

    CHAR = "demo"
    check("fixture: demo created", save_character_profile(CHAR, {"smoke_marker": "one", "language": "en"},
                                                         create_new=True), True)

    print("[S1]")
    f = Counter()
    with scope():
        for _ in range(3):
            memo("x", 1, f)
    check("S1 in a scope f ran", f.n, 1)
    f = Counter()
    for _ in range(3):
        memo("x", 1, f)
    check("S1 without a scope f ran", f.n, 3)

    print("[S2]")
    f = Counter()
    with scope():
        memo("x", 1, f)
        with scope():
            memo("x", 1, f)
    check("S2 nested scope f ran", f.n, 1)

    print("[S3]")
    with scope():
        r = memo("x", 1, lambda: {"a": {"b": 1}})
        r["a"]["b"] = 9
        r2 = memo("x", 1, lambda: {"a": {"b": 2}})
        check("S3 after the first caller's mutation", r2, {"a": {"b": 1}})
        r2["a"]["b"] = 7
        check("S3 after a hit's mutation", memo("x", 1, lambda: {"a": {"b": 3}}), {"a": {"b": 1}})

    print("[S4]")
    from app.core.garment_store import write_record

    def cleared_by(label, action):
        f = Counter()
        with scope():
            memo("x", 1, f)
            action()
            memo("x", 1, f)
        check(f"S4 {label}: f ran", f.n, 2)

    cleared_by("clear()", clear)
    cleared_by("write_record", lambda: write_record(TMP / "rec.json", {"a": 1}))
    cleared_by("figure.invalidate", figure.invalidate)
    cleared_by("save_character_profile", lambda: save_character_profile(CHAR, {**get_character_profile(CHAR),
                                                                                "smoke_marker": "one"}))

    print("[S5]")
    f = Counter()
    with scope():
        memo("x", 1, f)
        t = threading.Thread(target=lambda: memo("x", 1, f))
        t.start()
        t.join()
        check("S5 the thread computed its own", f.n, 2)
    memo("x", 1, f)
    check("S5 after the scope nothing is left", f.n, 3)

    print("[S6]")
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("first")
        return "second"

    with scope():
        try:
            memo("x", 1, boom)
            raised = False
        except KeyError:
            raised = True
        check("S6 raises", raised, True)
        check("S6 the next call computes", memo("x", 1, boom), "second")
    check("S6 f ran", calls["n"], 2)

    print("[S7]")
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)
    TOP = gt.validate_params({"kind": "top", "length_m": 0.53, "sleeves": "long", "neckline": "v",
                              "neck_depth_m": 0.07, "shoulders": "covered", "fit": 0.6, "sleeve_fit": 0.5,
                              "fabric": "medium", "texture": "projection"})[0]
    tz = gt.drape_path(CHAR, "top6", "tz")
    tz.parent.mkdir(parents=True, exist_ok=True)
    tz.write_bytes(b"glb")
    write_record(tz.with_suffix(".json"), {"item_id": "top6", "tsig": "tz", "accepted": True, "cut_sig": "cA",
                                           "created_at": "2026-11-21T09:00:00+00:00"})
    with patch.object(gt, "_key", lambda *a, **k: ("tz", None, {}, TOP, [])), \
            patch.object(gtc, "sig_of", lambda *a, **k: ("cA", "", [])):
        with read_scope.measure() as c, scope():
            d1 = gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])
            d2 = gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])
    check("S7 inner drape_state ran", c.get("drape_state", 0), 1)
    check("S7 results equal", d1 == d2, True)
    check("S7 state / tsig", (d1["state"], d1["tsig"]), ("ready", "tz"))
    check("S7 record is a copy per call", d1["record"] is d2["record"], False)

    print("[S8]")
    with read_scope.measure() as c, scope():
        p = get_character_profile(CHAR)
        p["poison"] = True
        p2 = get_character_profile(CHAR)
        check("S8 a mutated answer does not poison the hit", "poison" in p2, False)
        check("S8 the inner profile read ran", c.get("profile", 0), 1)
        check("S8 saved", save_character_profile(CHAR, {**p2, "smoke_marker": "two"}), True)
        check("S8 after the save", get_character_profile(CHAR).get("smoke_marker"), "two")

    print("[S9]")
    hits = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        def walk(node, fn):
            for child in ast.iter_child_nodes(node):
                name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "scope" and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "read_scope"):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}::{fn}")
                walk(child, name)
        walk(tree, "<module>")
    check("S9 the scope openings", sorted(hits), sorted([
        "app/core/figure_build.py::_figure_info", "app/core/figure_build.py::_compute_open",
        "app/routes/figure.py::_template_cut_payload", "app/routes/characters.py::get_character_model3d"]))
    check("S9 no scope in a build path", [h for h in hits if h.split("::")[1] == "_run_step_inner"
                                          or h.split("::")[0].endswith(("figure_batch.py", "garment_refit.py",
                                                                         "refit_pool.py"))], [])

    print("[S10]")
    check("S10 app.server not imported", "app.server" in sys.modules, False)
    from PIL import Image
    from app.core import garment_cut_texture as gct
    from app.routes import figure as figure_routes
    check("S10 app.server still not imported", "app.server" in sys.modules, False)
    ITEM = "shirtc"
    items = TMP / "items"
    items.mkdir()
    item_png = items / "shirtc.png"
    im = Image.new("RGBA", (1200, 1100), (0, 0, 0, 0))
    im.paste((150, 40, 40, 255), (200, 200, 1000, 900))
    im.save(item_png)
    back_png = items / "shirtc_back.png"
    Image.new("RGBA", (800, 800), (40, 40, 150, 255)).save(back_png)

    def fake_get_item(iid):
        return {"id": iid, "category": "outfit_piece", "image": item_png.name,
                "outfit_piece": {"template": {"params": {"kind": "top", "sleeves": "short", "texture": "cut"},
                                              "source": "user"}}}

    def key_body(character_name, item_id, **_k):
        read_scope.tally("cut_key")
        return {"sig": "c1", "reason": ""}

    def payload():
        def box(name, x0, y0):
            w, h = 200.0, 300.0
            v = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            return {"name": name, "part": 1 if name == "front" else 2, "verts_px": v, "tris": [[0, 1, 2], [0, 2, 3]],
                    "bbox_px": [x0, y0, x0 + w, y0 + h], "loops_px": [v], "area_cm2": 600, "distortion": {}}
        return {"version": 1, "atlas_px": 512, "px_per_cm": 10.0, "margin_cm": 1.5,
                "islands": [box("front", 10, 10), box("back", 250, 10)], "seams": []}

    payload_bytes = json.dumps(payload(), sort_keys=True, separators=(",", ":")).encode()
    gate = threading.Event()

    def fake_run(character_name, item_id):
        gate.wait(20)
        gtc._write_atomic(gtc.islands_file(character_name, item_id, "c1"), payload_bytes)
        gtc._write_atomic(gtc.sheet_file(character_name, item_id, "c1"),
                          gct._png(gct.render_pattern_sheet(json.loads(payload_bytes))))
        rec = {"state": "ready", "cut_sig": "c1", "wall_s": 0.5, "created_at": "2026-11-21T10:00:00+00:00",
               "islands": {"file": gtc.islands_file(character_name, item_id, "c1").name,
                           "sha256": hashlib.sha256(payload_bytes).hexdigest(), "px_per_cm": 10.0}}
        gtc._write_atomic(gtc.record_file(character_name, item_id, "c1"), json.dumps(rec).encode())

    no_drape = {"state": "missing", "reason": "Not draped yet", "tsig": None, "islands_path": None,
                "islands_sha": "", "record": {}, "worn": False}

    def both(label):
        with read_scope.measure() as c_plain:
            plain = figure_routes._template_cut_body(CHAR, ITEM)
        with read_scope.measure() as c_scoped:
            scoped = figure_routes._template_cut_payload(CHAR, ITEM)
        check(f"S10 {label}: cut key without a scope", c_plain.get("cut_key", 0), 3)
        check(f"S10 {label}: cut key in the scope", c_scoped.get("cut_key", 0), 1)
        check(f"S10 {label}: the same answer", scoped == plain, True)
        return plain

    with patch.object(gtc, "_cut_key", key_body), patch.object(gtc, "run", fake_run), \
            patch("app.models.inventory.get_item", fake_get_item), \
            patch("app.models.inventory.get_item_image_path", lambda iid: str(item_png)), \
            patch("app.imagegen.routing.chain_for", lambda occasion, *a, **k: ["FakeCut*"]), \
            patch("app.imagegen.base.media_generation_enabled", lambda: True), \
            patch.object(gct, "back_view", lambda c, i: back_png), \
            patch.object(gct, "current_drape", lambda c, i: dict(no_drape)):
        a = both("cut missing")
        check("S10 cut missing: the answer says cutting", (a.get("cutting"), a.get("pattern_reason")),
              (True, gtc.CUTTING))
        gate.set()
        t0 = time.time()
        while time.time() - t0 < 10:
            with gtc._lock:
                if not gtc._running:
                    break
            time.sleep(0.02)
        b = both("cut ready")
        check("S10 cut ready: the answer's pattern line", (b.get("cutting"), b.get("pattern_reason")), (False, ""))

    print("[S11]")
    real = figure._canonical
    n = {"c": 0}

    def counting(data):
        n["c"] += 1
        return real(data)

    with patch.object(figure, "_canonical", counting):
        obj = {"a": [1, 2], "b": "x"}
        with scope():
            s1 = read_scope.obj_sig(obj)
            s2 = read_scope.obj_sig(obj)
            check("S11 the same object hashed", n["c"], 1)
            s3 = read_scope.obj_sig({"b": "x", "a": [1, 2]})
            check("S11 equal content, equal value", (s1 == s2, s1 == s3), (True, True))
            check("S11 the other object hashed once", n["c"], 2)
        n["c"] = 0
        read_scope.obj_sig(obj)
        read_scope.obj_sig(obj)
        check("S11 without a scope hashed every call", n["c"], 2)

    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
