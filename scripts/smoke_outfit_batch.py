#!/usr/bin/env python3
"""Smoke run for the outfit batch job (plan-outfit-batch.md).

No test framework, no GPU, no LLM: the outfit store, the item store and the
two cache finders are monkeypatched, so the run exercises the real planning
and worker code (signature computation, duplicate detection, skip handling,
selection dedupe, error isolation, stop-after-current) against canned data.

Usage:  ./.venv/bin/python scripts/smoke_outfit_batch.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="outfit-batch-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import model3d, model_refs, outfit_batch, task_queue  # noqa: E402
from app.models import character as character_model  # noqa: E402
from app.models import inventory  # noqa: E402

CHAR = "demo"
FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── Canned stores ───────────────────────────────────────────────────────

# item_id -> the slots its outfit_piece declares (first one wins, like the
# wardrobe does when an outfit is put on).
ITEMS = {
    "shirt": ["top"],
    "pants": ["bottom"],
    "boots": ["feet"],
    "cloak": ["outer", "top"],   # multi-slot: only "outer" is used
}

OUTFITS = [
    {"id": "o1", "name": "Casual", "pieces": ["shirt", "pants"]},
    # Same pieces, other order + a different name/color meta: same combination.
    {"id": "o2", "name": "Casual (copy)", "pieces": ["pants", "shirt"],
     "pieces_colors": {"top": "red"}},
    {"id": "o3", "name": "Boots", "pieces": ["boots"]},
    {"id": "o4", "name": "Text only", "pieces": []},
    {"id": "o5", "name": "Cloaked", "pieces": ["cloak", "pants"]},
]

# Combinations whose cache entries already exist.
HAVE_REF: set = set()
HAVE_MODEL: set = set()


def install_stores() -> None:
    character_model.get_character_outfits = lambda name: (
        [dict(o) for o in OUTFITS] if name == CHAR else [])
    inventory.get_item = lambda pid: (
        {"id": pid, "outfit_piece": {"slots": ITEMS[pid]}} if pid in ITEMS else None)
    model_refs.find_ref_image = lambda name, kind, signature=None: (
        Path(f"/fake/{kind}_{signature}.png") if signature in HAVE_REF else None)
    model3d.find_model3d = lambda name, signature=None: (
        Path(f"/fake/{signature}.glb") if signature in HAVE_MODEL else None)


class _FakeQueue:
    """track_* no-op — the job must not need a real queue DB to run."""

    def track_start(self, *a, **kw):
        return "task-1"

    def track_update_label(self, *a, **kw):
        pass

    def track_finish(self, *a, **kw):
        pass


def wait_idle(timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = outfit_batch.get_status(CHAR)
        if not status["running"]:
            return status
        time.sleep(0.02)
    return outfit_batch.get_status(CHAR)


def by_id(rows) -> dict:
    return {r["outfit_id"]: r for r in rows}


# ── 1. plan() ───────────────────────────────────────────────────────────

def test_plan() -> dict:
    print("\n[1] plan()")
    rows = by_id(outfit_batch.plan(CHAR))
    check("every saved outfit appears", len(rows) == len(OUTFITS), str(len(rows)))
    check("the piece map stays internal", "pieces" not in rows["o1"])

    check("identical pieces in a different order share a signature",
          rows["o1"]["signature"] == rows["o2"]["signature"],
          f'{rows["o1"]["signature"]} vs {rows["o2"]["signature"]}')
    check("color meta does not change the signature",
          rows["o2"]["signature"] == rows["o1"]["signature"])
    check("different pieces give a different signature",
          len({rows["o1"]["signature"], rows["o3"]["signature"],
               rows["o5"]["signature"]}) == 3)
    check("the signature is a 12-char hex digest",
          len(rows["o1"]["signature"]) == 12
          and all(c in "0123456789abcdef" for c in rows["o1"]["signature"]))
    check("the signature is stable across calls",
          by_id(outfit_batch.plan(CHAR))["o1"]["signature"] == rows["o1"]["signature"])

    check("the second outfit of a combination is marked duplicate",
          rows["o2"]["duplicate_of"] == "o1", str(rows["o2"]["duplicate_of"]))
    check("the first one is not", rows["o1"]["duplicate_of"] is None)

    check("an outfit without pieces is skipped",
          rows["o4"]["skip_reason"] == "no pieces", rows["o4"]["skip_reason"])
    check("...and has no signature to render", rows["o4"]["signature"] is None)
    check("renderable outfits carry no skip reason",
          all(not rows[o]["skip_reason"] for o in ("o1", "o2", "o3", "o5")))
    return rows


def test_cache_flags(rows: dict) -> None:
    print("\n[2] plan() reports the caches")
    HAVE_REF.add(rows["o3"]["signature"])
    HAVE_MODEL.add(rows["o5"]["signature"])
    HAVE_REF.add(rows["o5"]["signature"])
    fresh = by_id(outfit_batch.plan(CHAR))
    check("an existing T-pose render shows up", fresh["o3"]["has_ref"]
          and not fresh["o3"]["has_model"])
    check("an existing mesh shows up", fresh["o5"]["has_model"])
    check("an untouched combination shows neither",
          not fresh["o1"]["has_ref"] and not fresh["o1"]["has_model"])
    HAVE_REF.clear()
    HAVE_MODEL.clear()


# ── 3. start() / worker ─────────────────────────────────────────────────

def run_batch(outfit_ids, force=False, ref_fails=(), mesh_fails=(),
              stop_after_first=False):
    """Runs the job with stubbed renders; returns (result, ref_calls, mesh_calls)."""
    ref_calls, mesh_calls = [], []

    def fake_refs(name, kinds=None, force=False, *, pieces=None, items=None,
                  signature=None):
        ref_calls.append({"signature": signature, "pieces": dict(pieces or {}),
                          "items": list(items or []), "kinds": kinds,
                          "force": force})
        if signature not in ref_fails:
            HAVE_REF.add(signature)
        return {}

    def fake_mesh(name, *, force=False, backend_glob="", prefer_cheapest=False,
                  signature=None):
        mesh_calls.append({"signature": signature, "force": force})
        if signature in mesh_fails:
            return {"ok": False, "error": "backend exploded"}
        if stop_after_first:
            outfit_batch.stop(CHAR)
        return {"ok": True, "cached": False, "path": f"/fake/{signature}.glb"}

    model_refs.generate_model_ref_images = fake_refs
    model3d.generate_for_current_outfit = fake_mesh
    task_queue.get_task_queue = lambda: _FakeQueue()

    res = outfit_batch.start(CHAR, outfit_ids)
    status = wait_idle()
    HAVE_REF.clear()
    return res, status, ref_calls, mesh_calls


def test_worker(rows: dict) -> None:
    print("\n[3] start(): selection, dedupe, overrides")
    res, status, refs, meshes = run_batch(["o1", "o2", "o3", "o4"])
    check("start reports the deduped count", res["ok"] and res["count"] == 2,
          str(res))
    check("a duplicate selection renders once", len(meshes) == 2, str(len(meshes)))
    check("the outfit without pieces is dropped",
          rows["o4"]["signature"] not in [m["signature"] for m in meshes])
    check("reference and mesh use the same signature",
          [r["signature"] for r in refs] == [m["signature"] for m in meshes])
    check("only the T-pose is rendered",
          all(r["kinds"] == ("tpose",) for r in refs), str(refs[0]["kinds"]))
    check("items are ignored (plan decision 1)",
          all(r["items"] == [] for r in refs))
    check("the pieces are slot-mapped",
          refs[0]["pieces"] == {"top": "shirt", "bottom": "pants"},
          str(refs[0]["pieces"]))
    check("all outfits reported ok",
          status["done"] == 2 and all(r["ok"] for r in status["results"]))

    print("\n[4] a multi-slot piece takes its first slot")
    _, _, refs5, _ = run_batch(["o5"])
    check("cloak lands in 'outer', not 'top'",
          refs5[0]["pieces"] == {"outer": "cloak", "bottom": "pants"},
          str(refs5[0]["pieces"]))

    print("\n[5] picking only the duplicate still renders it")
    res, _, _, meshes = run_batch(["o2"])
    check("the second outfit of a combination is renderable on its own",
          res["ok"] and len(meshes) == 1, str(res))

    print("\n[6] a broken outfit does not end the batch")
    _, status, _, meshes = run_batch(["o1", "o3", "o5"],
                                     ref_fails=(rows["o1"]["signature"],),
                                     mesh_fails=(rows["o3"]["signature"],))
    check("all three outfits were processed", status["done"] == 3,
          str(status["done"]))
    results = {r["outfit_id"]: r for r in status["results"]}
    check("the failed reference render is reported",
          not results["o1"]["ok"] and "T-pose" in results["o1"]["error"],
          results["o1"]["error"])
    check("no mesh run without its input",
          rows["o1"]["signature"] not in [m["signature"] for m in meshes])
    check("the failed mesh is reported",
          not results["o3"]["ok"] and "exploded" in results["o3"]["error"],
          results["o3"]["error"])
    check("the outfit after the failures still ran", results["o5"]["ok"])

    print("\n[7] stop after current")
    _, status, _, meshes = run_batch(["o1", "o3", "o5"], stop_after_first=True)
    check("the running outfit finishes", status["done"] == 1, str(status["done"]))
    check("nothing after it starts", len(meshes) == 1, str(len(meshes)))
    check("the job is not running any more", not status["running"])

    print("\n[8] guards")
    res = outfit_batch.start(CHAR, ["o4"])
    check("a selection with nothing renderable is refused",
          not res["ok"] and res["error"] == "no renderable outfits selected",
          str(res))
    res = outfit_batch.start(CHAR, [])
    check("an empty selection is refused", not res["ok"], str(res))
    check("the status of the last run survives",
          outfit_batch.get_status(CHAR)["total"] == 3)
    check("stop() on an idle character is a no-op",
          outfit_batch.stop(CHAR) is False)


def main() -> int:
    install_stores()
    rows = test_plan()
    test_cache_flags(rows)
    test_worker(rows)
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
