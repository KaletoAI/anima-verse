#!/usr/bin/env python3
"""Lift the place markers of a world's props by a real-metre amount.

Usage:
    # dry run (default) — prints the table, writes nothing
    ./.venv/bin/python scripts/lift_prop_markers.py --world demo \\
        --group seat --delta-m 0.2715 \\
        --group bed  --delta-m -0.2802

    # the same run, writing the sidecars atomically
    ./.venv/bin/python scripts/lift_prop_markers.py --world demo --apply \\
        --group seat --delta-m 0.2715 \\
        --group bed  --delta-m -0.2802

STOP THE SERVER FIRST when using --apply. This rewrites
``worlds/<world>/props/<prop>/sidecar.json`` behind the running app, which
holds prop records in memory and writes the whole file back on the next
admin save — a save while the server runs would clobber the repair.

Runs WITHOUT the server, without the world DB, and without any app import
(standard library only), so it is safe to read a world while the server is up
as long as --apply stays off.

What it changes
---------------
Only ``model_variants[].markers[].at[1]`` — the vertical fraction of the raw
model box. ``at[0]``/``at[2]``, ``group``, ``id``, ``facing``, ``capacity``
and every other key stay exactly as they were, as does every prop, variant or
marker of a group that was not asked for.

Metres per unit of at[1] — NOT ``height_m``
-------------------------------------------
``room_recipe.compose_prop_marker`` (~line 398) scales the raw model box
UNIFORMLY: ``s = max(dims) / max(oriented extents of the raw bbox)``, and the
marker's Y offset is ``at[1] * bbox[1] * s``. So one unit of ``at[1]`` is worth

    per_frac = bbox[1] * max(width_m, depth_m, height_m) / max(bbox)

metres — ``bbox`` = the sidecar's top-level raw AABB edge lengths (one per
prop), ``width_m``/``depth_m``/``height_m`` = the dims of THIS variant, which
is why two variants of one prop convert differently. Same chain as the
in-repo precedent ``props.py`` ~5417 (``per_frac = size_y * scale``).

``height_m`` is only equal to that when the box is proportional to the stated
dims. It usually is not: the dining chair of the field world measures
bbox [0.956, 1.000, 0.950] at dims 0.9/0.9/0.79 and therefore composes
0.900 m per fraction, not 0.79 — using ``height_m`` there would have lifted
the marker 3.8 cm too high. A prop without a measured ``bbox`` falls back to
``height_m`` with a printed note; that prop draws no composed marker today
(``room_recipe`` skips markers of a prop without a bbox), so the fallback is
only a best guess for a mesh that has not been measured yet.

The lift of ``delta_m`` metres is therefore

    at[1] += delta_m / per_frac

clamped to the range ``props.sanitize_markers`` accepts for index 1
(``MARKER_AT_Y_MIN`` -1.0 .. ``MARKER_AT_MAX`` 2.0) and rounded to 4 decimals
like that sanitizer, so nothing this script writes can be rejected on the next
admin save. Clamped rows are marked in the table.

A missing or non-positive ``height_m`` is REFUSED (the marker is left alone)
even though the app substitutes ``DEFAULT_DIM_M`` = 1.0 for it
(``props._coerce_dim_m``, ~line 848). That substitution is a display default
for an unmeasured prop; taking it as the truth here would move a real marker
by an amount derived from a placeholder, and a repair may not invent a size.

Variants with an orientation fix are SKIPPED
--------------------------------------------
When the variant's mesh file carries a ``rotation`` fix (``props.ROTATION_KEY``,
per FILE sidecar), ``compose_prop_marker`` turns the box BEFORE taking the Y
component, so the vertical of that prop lives in another ``at`` component and
``at[1]`` is not the height at all. Such a variant is skipped with a printed
note and must be corrected by hand in the repaired preview.

Why the two deltas (finding 2026-08-29, development_instructions/plan-sitzhoehe.md)
----------------------------------------------------------------------------------
The admin prop preview stripped the clip's hips track and never put the height
back, so every marker authored in it was placed against a figure drawn too
high. The markers therefore sit low by exactly that error:

    seat: drawn buttock height 0.8053 m - applied drop 0.5338 m = +0.2715 m
    bed:  applied drop 1.0727 m - laying's lowest point 0.7925 m = -0.2802 m

``stand`` markers were never affected (the standing figure's hips track is the
reference itself) and this script REFUSES the group, so a mistyped run cannot
move them; the three of them are corrected by hand in the repaired preview.

This script keeps no memory
---------------------------
Nothing is stamped into the sidecar to say a marker was already lifted. Run it
with the same delta twice and the markers move twice. It is a one-shot repair:
run it once, verify in the preview. A delta of 0 is a safe no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Mirrored from app/core/props.py (MARKER_AT_Y_MIN / MARKER_AT_MAX, ~line 499)
# — this script imports nothing from the app so it stays standard library only.
AT_Y_MIN = -1.0
AT_MAX = 2.0
AT_ROUND = 4

# app/core/props.py SIDECAR_NAME / ROTATION_KEY, and the per-variant mesh
# choice the recipe draws (``<prop>/selection.json``: stem -> {"full": file}).
SIDECAR_NAME = "sidecar.json"
SELECTION_NAME = "selection.json"
ROTATION_KEY = "rotation"

# The group whose markers were never wrong; refused outright, see the docstring.
FORBIDDEN_GROUPS = {"stand"}

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Row:
    """One marker considered by the run — changed or not."""

    prop: str
    stem: str
    marker_id: str
    group: str
    per_frac: float
    old_at: float
    new_at: float
    clamped: bool

    @property
    def changed(self) -> bool:
        return self.new_at != self.old_at

    @property
    def old_m(self) -> float:
        return self.old_at * self.per_frac

    @property
    def new_m(self) -> float:
        return self.new_at * self.per_frac


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Lift prop place markers by a real-metre amount, per group.",
        epilog="--group and --delta-m are repeatable and are paired in order: "
               "the first --group belongs to the first --delta-m. Default is a "
               "dry run; --apply writes. Stop the server before --apply.")
    ap.add_argument("--world", required=True,
                    help="world name under the worlds directory, e.g. demo")
    ap.add_argument("--worlds-dir", default=str(REPO / "worlds"),
                    help="where the worlds live (default: <repo>/worlds); pass "
                         "it for a storage dir outside the repo, and the smoke "
                         "test points it at its fixture")
    ap.add_argument("--group", action="append", default=[], metavar="NAME",
                    help="marker group to lift (seat, bed, ...); repeatable")
    ap.add_argument("--delta-m", action="append", default=[], type=float,
                    metavar="METRES",
                    help="metres to lift the matching --group by; repeatable")
    ap.add_argument("--apply", action="store_true",
                    help="write the sidecars (atomically) instead of only "
                         "reporting")
    return ap.parse_args(argv)


def build_deltas(args: argparse.Namespace) -> Dict[str, float]:
    """Pairs --group with --delta-m in order and rejects what must not run."""
    if len(args.group) != len(args.delta_m):
        raise SystemExit("each --group needs exactly one --delta-m "
                         f"(got {len(args.group)} groups, "
                         f"{len(args.delta_m)} deltas)")
    if not args.group:
        raise SystemExit("nothing to do — pass at least one "
                         "--group NAME --delta-m METRES pair")
    deltas: Dict[str, float] = {}
    for name, delta in zip(args.group, args.delta_m):
        group = name.strip().lower()
        if not group:
            raise SystemExit("empty --group")
        if group in FORBIDDEN_GROUPS:
            raise SystemExit(
                f"refusing --group {group}: standing markers were never "
                "affected by the preview bug and are corrected by hand")
        if group in deltas:
            raise SystemExit(f"--group {group} given twice")
        deltas[group] = delta
    return deltas


def _floats(raw: Any, count: int) -> Optional[List[float]]:
    """``count`` finite positive numbers, or ``None``."""
    if not isinstance(raw, (list, tuple)) or len(raw) < count:
        return None
    out: List[float] = []
    for i in range(count):
        try:
            v = abs(float(raw[i]))
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        out.append(v)
    return out


def per_fraction_m(bbox: Any, variant: Dict[str, Any]) -> Tuple[float, str]:
    """Metres per unit of ``at[1]``, plus a note ("" when nothing to say).

    ``bbox[1] * max(dims) / max(bbox)`` — the vertical term of
    ``room_recipe.compose_prop_marker``'s uniform real-size scale. Without a
    measured ``bbox`` (a prop the recipe draws no composed marker for) it falls
    back to ``height_m`` and says so."""
    dims = _floats([variant.get("width_m"), variant.get("depth_m"),
                    variant.get("height_m")], 3)
    box = _floats(bbox, 3)
    if box and dims:
        return box[1] * max(dims) / max(box), ""
    height = _floats([variant.get("height_m")], 1)
    if not height:
        return 0.0, (f"height_m is {variant.get('height_m')!r} — no metre "
                     "scale, markers left alone (the app's 1.0 default is a "
                     "display fallback, not a measurement)")
    why = "no measured bbox" if not box else "incomplete dims"
    return height[0], (
        f"{why} — falling back to height_m {height[0]}, which equals the "
        "composed factor only while the raw box is proportional to the dims")


def variant_rotation(prop_dir: Path, variant: Dict[str, Any]) -> Optional[Any]:
    """The orientation fix of the mesh this variant draws, if any.

    The fix lives on the FILE sidecar (``props.ROTATION_KEY``), and the recipe
    reads it from the variant's PUBLISHED file — the ``full`` entry of
    ``selection.json``. When the selection names no file for this stem, every
    ``<stem>_*.json`` of the prop is consulted instead, so an unresolvable
    selection errs towards skipping rather than towards a wrong lift."""
    if isinstance(variant.get(ROTATION_KEY), dict):
        return variant[ROTATION_KEY]
    stem = str(variant.get("stem") or "")
    if not stem:
        return None
    sidecars: List[Path] = []
    try:
        selection = json.loads((prop_dir / SELECTION_NAME)
                               .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        selection = {}
    chosen = (selection or {}).get(stem) if isinstance(selection, dict) else None
    if isinstance(chosen, dict) and chosen.get("full"):
        sidecars = [prop_dir / (Path(str(chosen["full"])).stem + ".json")]
    if not sidecars or not sidecars[0].is_file():
        sidecars = sorted(p for p in prop_dir.glob(f"{stem}_*.json")
                          if not p.name.endswith(".glb.surface.json"))
    for path in sidecars:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rot = meta.get(ROTATION_KEY) if isinstance(meta, dict) else None
        if isinstance(rot, dict) and any(_nonzero(v) for v in rot.values()):
            return rot
    return None


def _nonzero(value: Any) -> bool:
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return False


def lift_sidecar(data: Dict[str, Any], prop: str, prop_dir: Path,
                 deltas: Dict[str, float]) -> Tuple[List[Row], bool]:
    """Applies the deltas to ``data`` IN PLACE. Returns the rows it looked at
    and whether anything actually moved. Notes go to stdout — they belong to
    the report, not to the error channel."""
    rows: List[Row] = []
    touched = False
    variants = data.get("model_variants")
    if not isinstance(variants, list):
        return rows, touched
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        stem = str(variant.get("stem") or "?")
        markers = variant.get("markers")
        if not isinstance(markers, list):
            continue
        wanted = [m for m in markers if isinstance(m, dict)
                  and str(m.get("group") or "").strip().lower() in deltas]
        if not wanted:
            continue
        rotation = variant_rotation(prop_dir, variant)
        if rotation is not None and any(_nonzero(v) for v in
                                        (rotation.values()
                                         if isinstance(rotation, dict) else [])):
            print(f"  ! {prop} / {stem}: variant has an orientation fix "
                  f"{rotation} — skipped, at[1] is not vertical there")
            continue
        per_frac, note = per_fraction_m(data.get("bbox"), variant)
        if note:
            print(f"  ! {prop} / {stem}: {note}")
        if per_frac <= 0:
            continue
        for marker in wanted:
            group = str(marker.get("group") or "").strip().lower()
            at = marker.get("at")
            old_at: Optional[float] = None
            if isinstance(at, list) and len(at) == 3:
                try:
                    old_at = float(at[1])
                except (TypeError, ValueError):
                    old_at = None
            if old_at is None:
                print(f"  ! {prop} / {stem} / "
                      f"{marker.get('id') or '?'}: 'at' is {at!r}, not three "
                      "numbers — marker left alone")
                continue
            raw = old_at + deltas[group] / per_frac
            clamped_raw = min(max(raw, AT_Y_MIN), AT_MAX)
            new_at = round(clamped_raw, AT_ROUND)
            rows.append(Row(prop, stem, str(marker.get("id") or "?"), group,
                            per_frac, old_at, new_at,
                            clamped=clamped_raw != raw))
            if new_at != old_at:
                at[1] = new_at
                touched = True
    return rows, touched


def write_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Temp file in the SAME directory, then ``os.replace`` — the pattern of
    ``app/routes/poses.py::_write``. An in-place open("w") truncates the
    sidecar before writing it, and a crash mid-write would take the prop's
    master record with it. The mode of the replaced file is carried over,
    because ``mkstemp`` creates 0600. The payload is formatted exactly like
    ``app/core/props._write_sidecar`` (indent 2, no ASCII escaping, no
    trailing newline), so the file the app writes next is not reformatted."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def print_table(rows: List[Row]) -> None:
    header = ("prop", "variant", "marker", "group", "m per at[1]",
              "at[1] old -> new", "marker height (m)", "")
    lines: List[Tuple[str, ...]] = [header]
    for r in rows:
        note = "clamped" if r.clamped else ("" if r.changed else "unchanged")
        lines.append((r.prop, r.stem, r.marker_id, r.group,
                      f"{r.per_frac:.4f}",
                      f"{r.old_at:.4f} -> {r.new_at:.4f}",
                      f"{r.old_m:.3f} -> {r.new_m:.3f}",
                      note))
    widths = [max(len(line[i]) for line in lines) for i in range(len(header))]
    for i, line in enumerate(lines):
        print("  " + "  ".join(cell.ljust(widths[c])
                               for c, cell in enumerate(line)).rstrip())
        if i == 0:
            print("  " + "  ".join("-" * w for w in widths).rstrip())


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    deltas = build_deltas(args)

    world_dir = Path(args.worlds_dir) / args.world
    props_dir = world_dir / "props"
    if not props_dir.is_dir():
        print(f"no props directory: {props_dir}", file=sys.stderr)
        return 1

    print(f"world: {world_dir}")
    print("lift:  " + ", ".join(f"{g} {d:+.4f} m" for g, d in deltas.items()))
    print()

    all_rows: List[Row] = []
    pending: List[Tuple[Path, Dict[str, Any]]] = []
    for prop_dir in sorted(p for p in props_dir.iterdir() if p.is_dir()):
        sidecar = prop_dir / SIDECAR_NAME
        if not sidecar.is_file():
            continue
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  ! {prop_dir.name}: unreadable sidecar ({exc}) — skipped",
                  file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        rows, touched = lift_sidecar(data, prop_dir.name, prop_dir, deltas)
        all_rows.extend(rows)
        if touched:
            pending.append((sidecar, data))

    if all_rows:
        print_table(all_rows)
    else:
        print("  (no marker of these groups found)")
    print()

    changed = sum(1 for r in all_rows if r.changed)
    clamped = sum(1 for r in all_rows if r.clamped)
    if clamped:
        print(f"{clamped} marker(s) hit the sanitizer range "
              f"[{AT_Y_MIN}, {AT_MAX}] and were clamped")

    if not args.apply:
        print("dry run — nothing written; stop the server before --apply")
        return 0

    # Each path as it goes down: if the run dies halfway, this is the list of
    # files that already carry the lift and must not get it a second time.
    for sidecar, data in pending:
        write_atomic(sidecar, data)
        print(f"  wrote {sidecar}")
    print(f"written {changed} markers in {len(pending)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
