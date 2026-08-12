#!/usr/bin/env python3
"""Smoke run for the outfit-cache GC (Block CV).

Runs against a THROWAWAY storage directory with a stubbed inventory and FAKE
cache files — no renderer, no GPU. What is checked is the judging rule:
reachable vs manifest, deleted pieces, normalisation orphans, the protected
worn combination, and that purge removes exactly the right files.

Usage:  ./.venv/bin/python scripts/smoke_outfit_cache_gc.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="cache-gc-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

import json  # noqa: E402

from app.core import outfit_cache_gc as gc  # noqa: E402

FAILURES = []
CHECKED = 0
CHAR = "demo"


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# Two slots, 2 + 1 pieces → (2+1) · (1+1) − 1 = 5 combinations.
INVENTORY = {"inventory": [
    {"item_id": "shirt", "item_name": "Shirt", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["top"]}},
    {"item_id": "vest", "item_name": "Vest", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["top"]}},
    {"item_id": "jeans", "item_name": "Jeans", "item_category": "outfit_piece",
     "outfit_piece": {"slots": ["bottom"]}},
    {"item_id": "sword", "item_name": "Sword", "item_category": "tool"},
]}

REFS = STORAGE  # filled in main()


def stub(worn=("", "")) -> None:
    """Inventory + the worn state; everything else is real code."""
    import app.models.inventory as inv
    inv.get_character_inventory = lambda name, include_equipped=True: INVENTORY
    import app.core.model_refs as mr
    mr.current_outfit_state = lambda name: ({"top": worn[0]} if worn[0] else {},
                                            [], worn[1])
    gc._worn_signature = lambda name: worn[1]


def write_entry(refs: Path, meshes: Path, signature: str,
                manifest=None) -> None:
    """A fake cache entry: T-pose image + sidecar, mesh + sidecar."""
    (refs / f"tpose_{signature}.png").write_bytes(b"x" * 100)
    meta = {"created_at": "", "prompt": ""}
    if manifest is not None:
        meta["equipped_pieces"] = manifest[0]
        meta["equipped_items"] = manifest[1]
    (refs / f"tpose_{signature}.json").write_text(json.dumps(meta))
    (meshes / f"{signature}.glb").write_bytes(b"y" * 200)
    mmeta = {"signature": signature}
    if manifest is not None:
        mmeta["pieces"] = manifest[0]
        mmeta["items"] = manifest[1]
    (meshes / f"{signature}.json").write_text(json.dumps(mmeta))


def main() -> int:
    from app.models.character import get_character_dir
    stub()
    refs = get_character_dir(CHAR) / "model_refs"
    meshes = get_character_dir(CHAR) / "model3d"
    refs.mkdir(parents=True, exist_ok=True)
    meshes.mkdir(parents=True, exist_ok=True)

    print("\n[1] the reachable set")
    reach = sorted(gc.reachable_signatures(CHAR))
    check("5 combinations → 5 signatures", len(reach) == 5, str(len(reach)))
    import app.models.inventory as inv
    _full = inv.get_character_inventory
    inv.get_character_inventory = lambda name, include_equipped=True: {"inventory": []}
    check("a character without pieces has an empty set",
          gc.reachable_signatures(CHAR) == set())
    inv.get_character_inventory = _full

    print("\n[2] cache entries are judged")
    ok_sig = reach[0]                                  # (a) reachable
    write_entry(refs, meshes, ok_sig)
    write_entry(refs, meshes, "deadbeef1234")          # (b) fantasy signature
    # (c) manifest WITH a carried item — never in the pieces-only set, and
    #     still valid because the manifest re-signs to its own file name.
    item_manifest = ({"top": "shirt"}, ["sword"])
    item_sig = gc._sign(*item_manifest)
    write_entry(refs, meshes, item_sig, manifest=item_manifest)
    # (d) manifest pointing at a piece that no longer exists
    gone_manifest = ({"top": "deleted_hat"}, [])
    write_entry(refs, meshes, gc._sign(*gone_manifest), manifest=gone_manifest)
    # (e) manifest whose signature does NOT match its file name — exactly what
    #     a signature-rule change leaves behind (normalisation orphan).
    write_entry(refs, meshes, "0123456789ab", manifest=({"top": "shirt"}, []))

    rep = gc.verify_cache(CHAR)
    stale = set(rep["stale_signatures"])
    check("5 signatures in each cache", rep["refs"]["total"] == 5
          and rep["meshes"]["total"] == 5,
          f"{rep['refs']['total']}/{rep['meshes']['total']}")
    check("(a) a reachable signature is valid", ok_sig not in stale)
    check("(b) a fantasy signature is stale", "deadbeef1234" in stale)
    check("(c) a manifest with a carried item is valid, though it is NOT in "
          "the pieces-only set", item_sig not in stale and item_sig not in reach)
    check("(d) a manifest with a deleted piece is stale",
          gc._sign(*gone_manifest) in stale)
    check("(e) a manifest that no longer re-signs to its name is stale",
          "0123456789ab" in stale)
    check("3 stale of 5 in both caches",
          rep["refs"]["stale"] == 3 and rep["meshes"]["stale"] == 3,
          f"{rep['refs']['stale']}/{rep['meshes']['stale']}")
    check("stale bytes counted per cache (image 100 + sidecar)",
          rep["refs"]["stale_bytes"] > 300 and rep["meshes"]["stale_bytes"] > 600,
          f"{rep['refs']['stale_bytes']}/{rep['meshes']['stale_bytes']}")

    print("\n[3] the worn combination is protected")
    stub(worn=("shirt", "deadbeef1234"))
    prot = gc.verify_cache(CHAR)
    check("the worn signature is not reported stale, even though it would be",
          "deadbeef1234" not in prot["stale_signatures"],
          str(prot["stale_signatures"]))
    check("...and it is named as protected",
          prot["protected"] == ["deadbeef1234"], str(prot["protected"]))
    check("the other two stay stale", prot["refs"]["stale"] == 2,
          str(prot["refs"]["stale"]))

    print("\n[4] purge")
    stub()
    before = len(list(refs.iterdir())) + len(list(meshes.iterdir()))
    res = gc.purge_stale(CHAR, rep["stale_signatures"])
    after = len(list(refs.iterdir())) + len(list(meshes.iterdir()))
    check("3 signatures × 4 files = 12 files deleted",
          res["deleted_files"] == 12, str(res["deleted_files"]))
    check("files really gone", before - after == 12, f"{before} → {after}")
    check("bytes reported", res["freed_bytes"] > 900, str(res["freed_bytes"]))
    check("the valid entries survive",
          (refs / f"tpose_{ok_sig}.png").exists()
          and (meshes / f"{item_sig}.glb").exists())
    check("purging a signature that is NOT stale does nothing",
          gc.purge_stale(CHAR, [ok_sig])["deleted_files"] == 0)
    check("...and is counted as skipped",
          gc.purge_stale(CHAR, [ok_sig])["skipped"] == 1)
    check("nothing is stale any more",
          gc.verify_cache(CHAR)["stale_signatures"] == [],
          str(gc.verify_cache(CHAR)["stale_signatures"]))

    print("\n[5] the guard")
    big = {"inventory": [
        {"item_id": f"{slot}{i}", "item_name": f"{slot} {i}",
         "item_category": "outfit_piece", "outfit_piece": {"slots": [slot]}}
        for slot in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")
        for i in range(5)]}
    import app.models.inventory as inv
    inv.get_character_inventory = lambda name, include_equipped=True: big
    try:
        gc.reachable_signatures(CHAR)
        check("6^10 combinations are refused", False, "no error raised")
    except ValueError as e:
        check("6^10 combinations are refused with a readable message",
              "too many" in str(e), str(e)[:70])

    print(f"\n{CHECKED} checks, {len(FAILURES)} failure(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
