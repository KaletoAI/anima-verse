#!/usr/bin/env python3
"""Smoke run for the outfit-piece render invalidation (finding IMG-7).

Runs against a THROWAWAY storage directory with FAKE cache files — no
renderer, no GPU, no real world.

What is at stake: the outfit signature is md5 of "<slot>=<item_id>|…"
(``model_refs.outfit_signature_raw``), i.e. it is built from item IDs, NOT
from what those items look like. Editing a piece's ``prompt_fragment`` from
"red summer dress" to "blue summer dress" therefore renders a DIFFERENT
picture under the SAME signature: the expression variants were dropped, but
``model_refs/tpose_<sig>.png`` and ``model3d/<sig>.glb`` stayed red forever —
and the cache GC calls those entries valid (their pieces still exist and
re-sign to the same hash).

The fix keeps the ID-based signature (a name/price edit must not cost a GPU
minute, and every existing world's cache stays valid — no boot-time
re-mesh) and drops the affected entries actively instead.

Expected values, derived by hand from the rules, not from current output:

* ``_equipped_signature`` joins "<slot>=<id>" of the VISIBLE pieces, sorted
  by slot, with "|". For {"top": "shirt", "bottom": "jeans"} that is
  "bottom=jeans|top=shirt" — independent of every item field, so the
  signature before and after a ``prompt_fragment`` edit must be IDENTICAL.
* A piece with covers=["underwear_top"] hides that slot, so
  {"top": "shirt", "underwear_top": "bra"} signs like {"top": "shirt"}.
* ``invalidate_refs_for_item(char, "shirt")`` deletes exactly the entries
  whose sidecar manifest names "shirt": the tpose entry, its extra view
  (file name prefix "tpose_back_"), and the state fork "<sig>-s<fp>" —
  3 files + 3 sidecars. It returns 2 signatures (sig and sig-s…), because
  the front and back view of one signature are ONE entry.
* An entry whose sidecar records nothing is never deleted on a guess.
* ``invalidate_models_for_item`` purges model + sidecar + the reduced tier.
* ``models.inventory.update_item`` fires the purge for a changed
  ``prompt_fragment`` and for a changed ``partially_covers`` (it rewrites
  ANOTHER slot's fragment as "<piece> underneath <this>"), and NOT for a
  changed name or a changed ``covers`` (the latter changes the signature
  itself, so its old entries are never served again).

Usage:  ./.venv/bin/python scripts/smoke_outfit_piece_invalidation.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="piece-invalidation-smoke-"))

import os  # noqa: E402

os.environ.setdefault("ANIMATION_CLIPS_DIR",
                      str(STORAGE / "clips"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

import json  # noqa: E402

import app.core.expression_regen as er  # noqa: E402
import app.core.model3d as m3d  # noqa: E402
import app.core.model_refs as mr  # noqa: E402
import app.core.outfit_renderer as orr  # noqa: E402
import app.models.inventory as inv  # noqa: E402

FAILURES = []
CHECKED = 0
CHAR = "demo"

#: The stubbed item store — the ONLY source of item fields in this run.
ITEMS = {
    "shirt": {"id": "shirt", "prompt_fragment": "red shirt",
              "outfit_piece": {"slots": ["top"]}},
    "jeans": {"id": "jeans", "prompt_fragment": "blue jeans",
              "outfit_piece": {"slots": ["bottom"]}},
    "vest": {"id": "vest", "prompt_fragment": "leather vest",
             "outfit_piece": {"slots": ["top"]}},
    "bra": {"id": "bra", "prompt_fragment": "white bra",
            "outfit_piece": {"slots": ["underwear_top"]}},
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def write_ref(refs: Path, kind: str, signature: str, manifest=None) -> None:
    """A fake reference render: image + sidecar."""
    (refs / f"{kind}_{signature}.png").write_bytes(b"x" * 100)
    meta = {"created_at": ""}
    if manifest is not None:
        meta["equipped_pieces"] = manifest[0]
        meta["equipped_items"] = manifest[1]
    (refs / f"{kind}_{signature}.json").write_text(json.dumps(meta))


def write_mesh(meshes: Path, signature: str, manifest=None) -> None:
    """A fake mesh: model + sidecar + a reduced tier."""
    (meshes / f"{signature}.glb").write_bytes(b"y" * 200)
    meta = {"signature": signature}
    if manifest is not None:
        meta["pieces"] = manifest[0]
        meta["items"] = manifest[1]
    (meshes / f"{signature}.json").write_text(json.dumps(meta))
    (meshes / "low").mkdir(exist_ok=True)
    (meshes / "low" / f"{signature}.glb").write_bytes(b"z" * 50)


def main() -> int:
    # Items come from the stub, not from the DB — the signature rule reads
    # them through outfit_renderer._get_item (covers normalisation).
    orr._get_item = lambda iid: ITEMS.get(iid)

    print("\n[1] the signature rule — ID-based, not appearance-based")
    sig_a = mr.outfit_signature({"top": "shirt", "bottom": "jeans"}, [], "")
    same = mr.outfit_signature({"bottom": "jeans", "top": "shirt"}, [], "")
    check("same pieces → same signature (slot order irrelevant)",
          sig_a == same, sig_a)
    raw = mr.outfit_signature_raw({"top": "shirt", "bottom": "jeans"}, [], "")
    check("the raw string is 'bottom=jeans|top=shirt'",
          raw == "bottom=jeans|top=shirt", raw)
    ITEMS["shirt"]["prompt_fragment"] = "blue shirt"
    after = mr.outfit_signature({"top": "shirt", "bottom": "jeans"}, [], "")
    check("an edited prompt_fragment does NOT move the signature "
          "(existing worlds keep every cache entry — no boot-time re-mesh)",
          after == sig_a, f"{sig_a} → {after}")
    sig_b = mr.outfit_signature({"top": "vest"}, [], "")
    check("other pieces → other signature", sig_b != sig_a, sig_b)
    ITEMS["shirt"]["outfit_piece"]["covers"] = ["underwear_top"]
    covered = mr.outfit_signature({"top": "shirt", "underwear_top": "bra"},
                                  [], "")
    check("a fully covered piece collapses onto the uncovered signature",
          covered == mr.outfit_signature({"top": "shirt"}, [], ""), covered)
    ITEMS["shirt"]["outfit_piece"].pop("covers")

    print("\n[2] reference renders of the edited piece are dropped")
    from app.models.character import get_character_dir
    base = get_character_dir(CHAR)
    base.mkdir(parents=True, exist_ok=True)
    refs = base / "model_refs"
    meshes = base / "model3d"
    refs.mkdir(parents=True, exist_ok=True)
    meshes.mkdir(parents=True, exist_ok=True)

    man_a = ({"top": "shirt", "bottom": "jeans"}, [])
    man_b = ({"top": "vest"}, [])
    state_sig = f"{sig_a}{mr.STATE_SIG_SEP}abcdef12"
    write_ref(refs, "tpose", sig_a, manifest=man_a)
    write_ref(refs, "tpose_back", sig_a, manifest=man_a)
    write_ref(refs, "tpose", state_sig, manifest=man_a)
    write_ref(refs, "pose", sig_b, manifest=man_b)
    write_ref(refs, "tpose", "0123456789ab")          # no manifest at all
    before_files = len(list(refs.iterdir()))
    check("10 reference files written", before_files == 10, str(before_files))

    purged = mr.invalidate_refs_for_item(CHAR, "shirt")
    check("2 signatures purged (the outfit and its state fork)",
          purged == {sig_a, state_sig}, str(sorted(purged)))
    check("the T-pose of the edited outfit is gone",
          not (refs / f"tpose_{sig_a}.png").exists()
          and not (refs / f"tpose_{sig_a}.json").exists())
    check("its extra view is gone too",
          not (refs / f"tpose_back_{sig_a}.png").exists())
    check("the state fork is gone",
          not (refs / f"tpose_{state_sig}.png").exists())
    check("another outfit is untouched",
          (refs / f"pose_{sig_b}.png").exists()
          and (refs / f"pose_{sig_b}.json").exists())
    check("an entry without a manifest is never deleted on a guess",
          (refs / "tpose_0123456789ab.png").exists())
    check("4 files left", len(list(refs.iterdir())) == 4,
          str(sorted(p.name for p in refs.iterdir())))
    check("a second run finds nothing",
          mr.invalidate_refs_for_item(CHAR, "shirt") == set())
    check("an unrelated item purges nothing",
          mr.invalidate_refs_for_item(CHAR, "boots") == set())

    print("\n[3] meshes of the edited piece are dropped, tiers included")
    write_mesh(meshes, sig_a, manifest=man_a)
    write_mesh(meshes, sig_b, manifest=man_b)
    purged_m = m3d.invalidate_models_for_item(CHAR, "shirt")
    check("1 signature purged", purged_m == {sig_a}, str(sorted(purged_m)))
    check("model + sidecar gone",
          not (meshes / f"{sig_a}.glb").exists()
          and not (meshes / f"{sig_a}.json").exists())
    check("the reduced tier goes with it",
          not (meshes / "low" / f"{sig_a}.glb").exists())
    check("the other outfit's mesh and tier stay",
          (meshes / f"{sig_b}.glb").exists()
          and (meshes / "low" / f"{sig_b}.glb").exists())

    print("\n[4] the worn combination re-arms the outfit render")
    fired = []
    mr.schedule_outfit_render = lambda name: fired.append(name)
    write_ref(refs, "tpose", sig_a, manifest=man_a)
    mr.current_outfit_state = lambda name: ({}, [], sig_a)
    er._invalidate_outfit_caches_for_item(CHAR, "shirt")
    check("the worn outfit was hit → render re-armed", fired == [CHAR],
          str(fired))
    fired.clear()
    write_ref(refs, "tpose", sig_a, manifest=man_a)
    mr.current_outfit_state = lambda name: ({}, [], "ffffffffffff")
    er._invalidate_outfit_caches_for_item(CHAR, "shirt")
    check("another outfit is worn → nothing re-armed", fired == [], str(fired))

    print("\n[5] which item field fires the purge")
    cases = [
        ("prompt_fragment changed", {"prompt_fragment": "green shirt"}, True),
        ("name changed", {"name": "Shirt (old)"}, False),
        ("partially_covers changed",
         {"outfit_piece": {"slots": ["top"], "partially_covers": ["bottom"]}},
         True),
        ("covers changed (the signature moves by itself)",
         {"outfit_piece": {"slots": ["top"], "covers": ["underwear_top"]}},
         False),
    ]
    for label, updates, expect in cases:
        item = inv.add_item(name="Shirt", description="", category="outfit_piece",
                            prompt_fragment="red shirt",
                            outfit_piece={"slots": ["top"]})
        calls = []
        er.invalidate_variants_for_item = lambda iid: calls.append(iid) or 0
        inv.update_item(item["id"], updates)
        check(f"{label} → purge {'fires' if expect else 'does not fire'}",
              bool(calls) == expect, str(calls))

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + "; ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
