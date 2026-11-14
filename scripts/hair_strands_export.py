#!/usr/bin/env python3
"""Export the strand record of one HairDeck hair fit, for the real-hair checks (strand-hair plan 2026-11-13, Task 9).

Usage:
    ./.venv/bin/python scripts/hair_strands_export.py FIT.glb FIT.json OUT_DIR [--scales JSON]

FIT.glb / FIT.json are a HairDeck fit and its fit record (``garments/<item>_<fsig>.{glb,json}``), COPIED read-only out
of a world — never point it at a running world's files to write anything: it only reads them. Writes into OUT_DIR:

- ``<fit stem>.strands.json``: the strand record (``app/core/hair_strands.build_record``, Task 4 — the same bytes
  ``hair_strands.encode`` serves), with the HairDeck layout of the fit's hair primitive (``hairdeck_layout``, the
  hair vertex count from the record's ``report.vertices.hair``);
- ``<fit stem>.strands.glb``: the fit GLB with the record's per-vertex binding ``_STRAND_CARD`` / ``_STRAND_U`` on its
  hair primitive (``glb_mesh.add_vertex_attributes``) — what the Hairstyles preview serves (``preview_glb``, Ruling
  H-R5): a skinned fit body with the hair, the input of ``scripts/check_hair_sim.mjs`` and of a 3D-client check.

``--scales`` = the character's collision region scales as JSON (default ``{}``: the default capsules). The fit body's
extension capsules (Ruling H-R4) need the character's model sidecar and are not added here. CPU only; no world, no
world DB, no server, no network. Prints the card / row / vertex counts and the build time.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fit_glb", type=Path)
    ap.add_argument("fit_json", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--scales", default="{}", help="collision region scales as JSON (default {})")
    args = ap.parse_args()

    from app.core import hair_strands
    from app.core.glb_mesh import add_vertex_attributes, garment_arrays

    blob = args.fit_glb.read_bytes()
    record = json.loads(args.fit_json.read_text(encoding="utf-8"))
    if record.get("method") != "hairdeck":
        print(f"{args.fit_json.name}: method {record.get('method')!r} — only HairDeck fits have a record", file=sys.stderr)
        return 2
    n_hair = int(((record.get("report") or {}).get("vertices") or {})["hair"])
    t0 = time.perf_counter()
    garment = garment_arrays(blob, node_prefix="garment_hair_")
    layout = hair_strands.hairdeck_layout(garment.positions, garment.indices, n_hair)
    strands, arrays = hair_strands.build_record(
        blob, mode="hairdeck", item_id=str(record.get("item_id") or ""), fsig=str(record.get("fsig") or ""),
        layout=layout, scales=json.loads(args.scales))
    built = time.perf_counter() - t0
    glb = add_vertex_attributes(blob, {hair_strands.VERTEX_ATTRIBUTES["card"]: arrays["card"],
                                       hair_strands.VERTEX_ATTRIBUTES["u"]: arrays["u"]}, node_prefix="garment_hair_")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.fit_glb.stem
    (args.out_dir / f"{stem}.strands.json").write_bytes(hair_strands.encode(strands))
    (args.out_dir / f"{stem}.strands.glb").write_bytes(glb)
    print(f"{stem}: {strands['cards']} cards, {strands['cards'] * strands['rows']} rows, "
          f"{len(arrays['card'])} vertices ({int((arrays['card'] == 0).sum())} rigid), "
          f"{len(strands['capsules']['capsules'])} capsules, record {built:.2f} s -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
