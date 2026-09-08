#!/usr/bin/env python3
"""Convert a FRACTION-ERA location pack into a contract-v6 (metre) pack.

Usage:
    ./.venv/bin/python scripts/convert_fraction_location_pack.py <in.zip> <out.zip>

A one-off rescue tool for archives whose source world no longer exists. It
is NOT a fallback reader: the importer refuses fraction-era packs
(``content_io._fraction_era_reason``), and this script rewrites the archive
OUTSIDE the world so the rewritten ZIP goes through the ordinary import like
any current pack. Nothing here touches a world.

What a fraction-era pack means (state before the metre wave, commit
8672c756, 2026-08-19 — read from the pre-wave ``world_ops`` and
``scene_recipe._w``):

  * the location's area was a REFERENCE SQUARE of side ``plan_width_m``,
    CENTRED on the anchor pin: a fraction f of it is ``(f - 0.5) * W`` local
    metres (``scene_recipe._w`` of that time);
  * a room's ``x``/``y`` were the min corner as fractions of that square,
    ``w``/``d`` its size as fractions of the square's side;
  * a room's ``outline`` points, ``markers[].at``, ``props[].at`` and
    ``model_at`` were fractions of the ROOM RECTANGLE;
  * ``map3d.outline`` (the building footprint) and ``map3d.elevator`` were
    fractions of the square;
  * an opening's ``at`` was — and still is — a ratio along its edge.

What comes out (contract v6, metres, the frame ``map3d.boundary`` lives in):

  * ``map3d.boundary`` = the reference square itself, in local metres, so the
    derived ``plan_width_m`` is exactly the old one and the location keeps
    the area it had;
  * ``map3d.outline`` and ``elevator`` in local metres;
  * room ``x``/``y`` in local metres (negative is normal), ``w``/``d`` in
    metres; ``outline``, ``markers[].at``, ``props[].at``, ``model_at`` in
    metres relative to the room's min corner;
  * a boundary opening on a LETTER edge (N/E/S/W) becomes the index of that
    edge of the square (the square is emitted N, E, S, W = 0, 1, 2, 3 in the
    winding the sanitizer keeps);
  * ``rotation``/``size``/``plan_width_m`` on map3d and ``grid_x``/``grid_y``
    on the location are dropped (no reader since v6 / the metre map; the
    width is derived from the boundary again on import).

Everything else in the archive (gallery, 3D models, props, items, the
manifest) is copied byte for byte. Values are rounded to the centimetre, as
the sanitizer would.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.world_geometry import polygon_signed_area  # noqa: E402


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _cm(v: float) -> float:
    return round(v, 2)


def square_boundary(width: float) -> List[List[float]]:
    """The reference square around the pin, ordered N, E, S, W as edges
    0..3 — in the winding the sanitizer keeps (positive signed area), so
    the indices survive the import unchanged."""
    h = width / 2.0
    pts = [[-h, -h], [h, -h], [h, h], [-h, h]]      # NW, NE, SE, SW
    if polygon_signed_area(pts) < 0:
        # Reversed the edges would read W, S, E, N — keep the letters right.
        pts = [[h, -h], [-h, -h], [-h, h], [h, h]]
        assert polygon_signed_area(pts) > 0
        return pts
    return pts


def convert_location(loc: Dict[str, Any]) -> List[str]:
    """Rewrite ``loc`` in place. Returns human-readable notes."""
    notes: List[str] = []
    m3 = loc.get("map3d")
    if not isinstance(m3, dict):
        raise ValueError("no map3d — nothing says how wide the plan was")
    width = _f(m3.get("plan_width_m"))
    if not width or width <= 0:
        raise ValueError("map3d.plan_width_m missing — the scale is unknown")
    if m3.get("boundary"):
        raise ValueError("map3d.boundary present — this is not a fraction-era pack")

    def sq(f: Any) -> Optional[float]:
        """Square fraction → local metre."""
        v = _f(f)
        return None if v is None else _cm((v - 0.5) * width)

    boundary = square_boundary(width)
    m3["boundary"] = [[_cm(u), _cm(v)] for u, v in boundary]
    notes.append(f"boundary = the {width} m reference square around the pin")

    # Letter index in the emitted square: point i = corner i, edge i = i→i+1.
    # For the NW,NE,SE,SW order that is N=0, E=1, S=2, W=3; for the reversed
    # fallback order (NE,NW,SW,SE) it is N=0, W=1, S=2, E=3.
    first_is_nw = boundary[0][0] < 0
    letter_index = {"N": 0, "E": 1, "S": 2, "W": 3} if first_is_nw \
        else {"N": 0, "W": 1, "S": 2, "E": 3}

    ol = m3.get("outline")
    if isinstance(ol, list):
        pts = [[sq(p[0]), sq(p[1])] for p in ol
               if isinstance(p, (list, tuple)) and len(p) == 2]
        m3["outline"] = [p for p in pts if None not in p]
        notes.append(f"map3d.outline: {len(m3['outline'])} point(s) to local metres")
    ev = m3.get("elevator")
    if isinstance(ev, (list, tuple)) and len(ev) == 2:
        m3["elevator"] = [sq(ev[0]), sq(ev[1])]
        notes.append(f"elevator → {m3['elevator']}")
    for op in (m3.get("boundary_openings") or []):
        if isinstance(op, dict) and isinstance(op.get("edge"), str):
            letter = op["edge"].strip().upper()
            if letter in letter_index:
                op["edge"] = letter_index[letter]
                notes.append(f"boundary opening edge {letter!r} → index {op['edge']}")
    for key in ("rotation", "size"):
        if key in m3:
            m3.pop(key)
            notes.append(f"map3d.{key} dropped (no reader since v6)")
    # Not an input since v6: the importer derives it from the boundary (the
    # centimetre-rounded square gives 22.92 for a stored 22.91) and would
    # otherwise warn about the stale value.
    m3.pop("plan_width_m", None)
    for key in ("grid_x", "grid_y"):
        if key in loc:
            loc.pop(key)

    for room in (loc.get("rooms") or []):
        lay = room.get("layout") if isinstance(room, dict) else None
        if not isinstance(lay, dict):
            continue
        label = room.get("name") or room.get("id") or "?"
        x, y, w, d = (_f(lay.get(k)) for k in ("x", "y", "w", "d"))
        if None in (x, y, w, d):
            continue
        w_m, d_m = w * width, d * width
        lay["x"], lay["y"] = _cm((x - 0.5) * width), _cm((y - 0.5) * width)
        lay["w"], lay["d"] = _cm(w_m), _cm(d_m)

        def rect(f: Any) -> Optional[List[float]]:
            """Room-rectangle fraction pair → metres from the min corner."""
            if not (isinstance(f, (list, tuple)) and len(f) == 2):
                return None
            u, v = _f(f[0]), _f(f[1])
            if u is None or v is None:
                return None
            return [_cm(u * w_m), _cm(v * d_m)]

        if isinstance(lay.get("outline"), list):
            lay["outline"] = [p for p in (rect(pt) for pt in lay["outline"]) if p]
        for entry in (lay.get("outline_curves") or []):
            if isinstance(entry, dict) and rect(entry.get("c")):
                entry["c"] = rect(entry["c"])
        for key in ("markers", "props"):
            for entry in (lay.get(key) or []):
                if isinstance(entry, dict) and rect(entry.get("at")):
                    entry["at"] = rect(entry["at"])
        if rect(lay.get("model_at")):
            lay["model_at"] = rect(lay["model_at"])
        notes.append(f"room '{label}': x {lay['x']} y {lay['y']} w {lay['w']} d {lay['d']}")
    return notes


def convert_zip(src: bytes) -> tuple[bytes, List[str]]:
    zin = zipfile.ZipFile(io.BytesIO(src))
    manifest = json.loads(zin.read("manifest.json"))
    if manifest.get("type") != "location":
        raise ValueError(f"not a location pack: {manifest.get('type')!r}")
    loc = json.loads(zin.read("db/location.json"))
    notes = convert_location(loc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename == "db/location.json":
                zout.writestr(info, json.dumps(loc, ensure_ascii=False, indent=2))
            else:
                zout.writestr(info, zin.read(info.filename))
    return buf.getvalue(), notes


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1])
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    out, notes = convert_zip(src.read_bytes())
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    for line in notes:
        print(" -", line)
    print(f"written: {dst} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
