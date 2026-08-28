#!/usr/bin/env python3
"""Smoke: the marker-repair script lifts at[1] by the COMPOSED metre factor.

Usage:
    ./.venv/bin/python scripts/smoke_lift_prop_markers.py

Runs WITHOUT the server and WITHOUT a world DB: it builds a throwaway world
tree in a temp dir and drives ``scripts/lift_prop_markers.py`` over it as a
subprocess. Nothing under ``worlds/`` is touched.

Metres per unit of ``at[1]`` are NOT ``height_m``. ``compose_prop_marker``
scales the raw box uniformly, so

    per_frac = bbox[1] * max(width_m, depth_m, height_m) / max(bbox)

The expected numbers are derived BY HAND from that, rounded to 4 decimals like
``props.sanitize_markers`` — never copied from a run:

    seat delta = +0.2715 m   (drawn buttock height 0.8053 - applied drop 0.5338)
    bed  delta = -0.2802 m   (drop 1.0727 - laying's lowest point 0.7925)

    wingback (bbox [0.956, 1.0, 0.95] — NOT proportional to the dims)
      v0  dims 0.9 / 0.9 / 0.79   per_frac = 1.0 x 0.9  / 1.0 = 0.9000
          0.155 + 0.2715/0.9  = 0.155 + 0.301667 = 0.456667 -> 0.4567
          (with the old height_m factor this would be 0.155 + 0.2715/0.79
           = 0.498671 -> 0.4987, a 3.8 cm error — asserted ABSENT)
      v1  dims 0.45 / 0.45 / 0.57  per_frac = 1.0 x 0.57 / 1.0 = 0.5700
          0.155 + 0.2715/0.57 = 0.155 + 0.476316 = 0.631316 -> 0.6313

    king bed (bbox [2.0, 1.25, 2.1], dims 2.0 / 2.1 / 1.25 — proportional)
          per_frac = 1.25 x 2.1 / 2.1 = 1.2500 = height_m
          0.660 - 0.2802/1.25 = 0.660 - 0.224160 = 0.435840 -> 0.4358

    stand  untouched, whatever the delta

The two wingback variants carry the SAME old fraction and must land on
different new fractions — that is the per-variant check; and the same fraction
in the same prop converts by the VARIANT's dims, not the prop's box alone.

Composed metres (the column the report compares against the finding's
expectation table) are ``at[1] * per_frac``:

    wingback v0   0.155 x 0.9  = 0.13950 m  ->  0.4567 x 0.9  = 0.411030 m
                  the rise is 0.271530 m ~ the requested 0.2715 m (rounding)
    king bed      0.660 x 1.25 = 0.82500 m  ->  0.4358 x 1.25 = 0.544750 m

Fallback + clamp case (``props.MARKER_AT_MAX`` = 1.5, index 1 has its own
lower bound ``MARKER_AT_Y_MIN`` = -1.0): a prop WITHOUT a measured ``bbox``
falls back to ``height_m`` and says so —

    stool  h = 0.50 m   1.400 + 0.2715/0.50 = 1.400 + 0.543 = 1.943 -> clamp 1.5

Orientation fix: a variant whose mesh carries a non-zero ``rotation``
(``props.ROTATION_KEY``, on the FILE sidecar named by ``selection.json``, or
inline on the variant) has its vertical in another ``at`` component and is
skipped untouched; an all-zero fix is not a fix and does not skip.

Non-idempotency is deliberate and is pinned here: the script stores no "already
lifted" mark, so running it twice with the same delta shifts twice
(0.4567 + 0.301667 = 0.758367 -> 0.7584). The user runs it exactly once.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "lift_prop_markers.py"

SEAT_DELTA = "0.2715"
BED_DELTA = "-0.2802"

_failures: List[str] = []


def _short(value: Any, limit: int = 70) -> str:
    """File snapshots are dicts of raw bytes — readable only when trimmed."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + f"...({len(text)} chars)"


def check(label: str, got: Any, want: Any) -> None:
    if got != want:
        _failures.append(f"{label}: got {_short(got)}, want {_short(want)}")
        print(f"  FAIL {label}: got {_short(got)}, want {_short(want)}")
    else:
        print(f"  ok   {label}: {_short(got)}")


def check_true(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        _failures.append(f"{label}{': ' + detail if detail else ''}")
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
    else:
        print(f"  ok   {label}")


# ── Fixture ──────────────────────────────────────────────────────────────

def _sidecar(name: str, variants: List[Dict[str, Any]],
             bbox: Any = None) -> Dict[str, Any]:
    """A prop master record trimmed to what the script reads — plus a few
    unrelated keys, so the rewrite is proven to keep the rest of the file.
    ``bbox`` is the top-level raw AABB the recipe scales from."""
    out: Dict[str, Any] = {
        "name": name,
        "category": "furniture",
        "tags": ["demo"],
        "created_at": "2026-08-29T00:00:00+00:00",
    }
    if bbox is not None:
        out["bbox"] = bbox
    out["model_variants"] = variants
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def build_world(root: Path) -> None:
    props = root / "props"
    for name in ("wingback-chair-aaa111", "king-size-bed-bbb222",
                 "wooden-stool-ccc333", "tilted-shelf-eee555",
                 # A prop dir without a sidecar — skipped silently.
                 "broken-ddd444"):
        (props / name).mkdir(parents=True)

    # Box NOT proportional to the dims: per_frac 0.9 for v0, 0.57 for v1.
    _write_json(props / "wingback-chair-aaa111" / "sidecar.json",
                _sidecar("Wingback chair", [
                    {"stem": "wingback", "active": True,
                     "width_m": 0.9, "depth_m": 0.9, "height_m": 0.79,
                     "markers": [
                         {"id": "q4zmnmq4", "group": "seat",
                          "at": [0.505, 0.155, 0.786]},
                         {"id": "s7ta9d1x", "group": "stand",
                          "at": [0.5, 0.3, 0.2], "facing": 90},
                     ]},
                    {"stem": "wingback-low", "active": False,
                     "width_m": 0.45, "depth_m": 0.45, "height_m": 0.57,
                     "markers": [
                         {"id": "b2c3d4e5", "group": "seat",
                          "at": [0.505, 0.155, 0.786],
                          "capacity": 2, "spacing_m": 0.6},
                     ]},
                ], bbox=[0.956, 1.0, 0.95]))

    # Proportional box: per_frac == height_m == 1.25. Its selected mesh file
    # carries an ALL-ZERO orientation fix, which must not count as a fix.
    _write_json(props / "king-size-bed-bbb222" / "sidecar.json",
                _sidecar("King size bed", [
                    {"stem": "kingbed", "active": True,
                     "width_m": 2.0, "depth_m": 2.1, "height_m": 1.25,
                     "markers": [
                         {"id": "ymzz7gz6", "group": "bed", "at": [0.5, 0.66, 0.5]},
                     ]},
                ], bbox=[2.0, 1.25, 2.1]))
    _write_json(props / "king-size-bed-bbb222" / "selection.json",
                {"kingbed": {"full": "kingbed_1787877866.glb"}})
    _write_json(props / "king-size-bed-bbb222" / "kingbed_1787877866.json",
                {"rotation": {"x": 0.0, "y": 0.0, "z": 0.0}})

    # No measured bbox -> falls back to height_m with a note; and clamps.
    # The second marker's `at` is malformed and must be reported, not dropped.
    _write_json(props / "wooden-stool-ccc333" / "sidecar.json",
                _sidecar("Wooden stool", [
                    {"stem": "stool", "active": True,
                     "width_m": 0.4, "depth_m": 0.4, "height_m": 0.5,
                     "markers": [
                         {"id": "clampme1", "group": "seat", "at": [0.5, 1.4, 0.5]},
                         {"id": "badat001", "group": "seat", "at": [0.5, 0.5]},
                     ]},
                ]))

    # Two ways an orientation fix reaches a variant: on the FILE sidecar its
    # selection names, and inline on the variant entry. Both must skip.
    _write_json(props / "tilted-shelf-eee555" / "sidecar.json",
                _sidecar("Tilted shelf", [
                    {"stem": "tilted", "active": True,
                     "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0,
                     "markers": [
                         {"id": "rot90aaa", "group": "seat", "at": [0.5, 0.2, 0.5]},
                     ]},
                    {"stem": "tilted-inline", "active": False,
                     "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0,
                     "rotation": {"x": 0, "y": 180, "z": 0},
                     "markers": [
                         {"id": "rot180bb", "group": "seat", "at": [0.5, 0.2, 0.5]},
                     ]},
                ], bbox=[1.0, 1.0, 1.0]))
    _write_json(props / "tilted-shelf-eee555" / "selection.json",
                {"tilted": {"full": "tilted_1787000000.glb"}})
    _write_json(props / "tilted-shelf-eee555" / "tilted_1787000000.json",
                {"rotation": {"x": 90.0, "y": 0.0, "z": 0.0}})


def snapshot(root: Path) -> Dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("sidecar.json"))}


def markers(root: Path, prop: str) -> List[List[Dict[str, Any]]]:
    data = json.loads((root / "props" / prop / "sidecar.json")
                      .read_text(encoding="utf-8"))
    return [v.get("markers") or [] for v in data["model_variants"]]


def run(worlds_dir: Path, *args: str) -> Tuple[int, str, str]:
    """Drives the script over the fixture. ``--worlds-dir`` is the only reason
    that option exists — no env var, and the real ``worlds/`` stays out of
    reach of this test."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--worlds-dir", str(worlds_dir), *args],
        capture_output=True, text=True, cwd=str(REPO))
    return proc.returncode, proc.stdout, proc.stderr


# ── Parts ────────────────────────────────────────────────────────────────

def part1_dry_run(worlds: Path, world: Path) -> None:
    print("\n1) dry run — reports, writes nothing")
    before = snapshot(world)
    rc, out, err = run(worlds, "--world", "fixture",
                       "--group", "seat", "--delta-m", SEAT_DELTA,
                       "--group", "bed", "--delta-m", BED_DELTA)
    check("exit code", rc, 0)
    check("files byte-identical", snapshot(world), before)
    check_true("table shows the composed factor 0.9000", "0.9000" in out, out)
    check_true("table shows the new seat fraction 0.4567", "0.4567" in out, out)
    check_true("the height_m factor's 0.4987 is NOT used",
               "0.4987" not in out, out)
    check_true("table shows the per-variant 0.6313", "0.6313" in out, out)
    check_true("table shows the new bed fraction 0.4358", "0.4358" in out, out)
    check_true("table shows composed metres 0.411", "0.411" in out, out)
    check_true("column is named 'marker height (m)'",
               "marker height (m)" in out, out)
    check_true("clamp is reported", "clamped" in out.lower(), out)
    check_true("the bbox-less prop says it fell back to height_m",
               "no measured bbox" in out and "height_m 0.5" in out, out)
    check_true("the orientation fix is reported",
               out.count("orientation fix") == 2, out)
    check_true("the malformed at is reported",
               "badat001" in out and "not three numbers" in out, out)
    check_true("closing line names the server",
               "dry run — nothing written; stop the server before --apply" in out,
               out)
    check_true("no stray stderr", err.strip() == "", err)
    check_true("stand marker absent from the table", "s7ta9d1x" not in out, out)
    check_true("skipped rotated markers absent from the table",
               "rot90aaa" not in out and "rot180bb" not in out, out)


def part2_apply(worlds: Path, world: Path) -> None:
    print("\n2) --apply — hand-derived values land in the files")
    rc, out, err = run(worlds, "--world", "fixture", "--apply",
                       "--group", "seat", "--delta-m", SEAT_DELTA,
                       "--group", "bed", "--delta-m", BED_DELTA)
    check("exit code", rc, 0)
    check_true("summary counts markers and files",
               "written 4 markers in 3 files" in out, out)
    for prop in ("wingback-chair-aaa111", "king-size-bed-bbb222",
                 "wooden-stool-ccc333"):
        check_true(f"names the file it wrote ({prop})",
                   f"wrote {world}/props/{prop}/sidecar.json" in out, out)
    check_true("the skipped prop is not written",
               "tilted-shelf-eee555/sidecar.json" not in out, out)

    chair = markers(world, "wingback-chair-aaa111")
    check("wingback v0 seat at[1]", chair[0][0]["at"][1], 0.4567)
    check("wingback v0 seat at[0] untouched", chair[0][0]["at"][0], 0.505)
    check("wingback v0 seat at[2] untouched", chair[0][0]["at"][2], 0.786)
    check("stand marker untouched", chair[0][1]["at"], [0.5, 0.3, 0.2])
    check("stand facing kept", chair[0][1].get("facing"), 90)
    check("wingback v1 uses ITS dims", chair[1][0]["at"][1], 0.6313)
    check("capacity/spacing kept", (chair[1][0].get("capacity"),
                                    chair[1][0].get("spacing_m")), (2, 0.6))

    bed = markers(world, "king-size-bed-bbb222")
    check("king bed at[1] (zero rotation is not a fix)",
          bed[0][0]["at"][1], 0.4358)

    stool = markers(world, "wooden-stool-ccc333")
    check("stool clamped to MARKER_AT_MAX", stool[0][0]["at"][1], 1.5)
    check("malformed at left alone", stool[0][1]["at"], [0.5, 0.5])

    tilted = markers(world, "tilted-shelf-eee555")
    check("file-sidecar rotation: marker untouched", tilted[0][0]["at"],
          [0.5, 0.2, 0.5])
    check("inline rotation: marker untouched", tilted[1][0]["at"],
          [0.5, 0.2, 0.5])

    data = json.loads((world / "props" / "wingback-chair-aaa111" / "sidecar.json")
                      .read_text(encoding="utf-8"))
    check("unrelated keys survive", data["name"], "Wingback chair")
    check("variant keys survive", sorted(data["model_variants"][0]),
          ["active", "depth_m", "height_m", "markers", "stem", "width_m"])
    check("the prop's bbox survives", data["bbox"], [0.956, 1.0, 0.95])
    raw = (world / "props" / "wingback-chair-aaa111" / "sidecar.json").read_bytes()
    check_true("written like props._write_sidecar (indent 2, no trailing NL)",
               raw.startswith(b"{\n  \"name\"") and not raw.endswith(b"\n"),
               repr(raw[:20]) + " ... " + repr(raw[-8:]))
    check_true("no temp file left behind",
               not list((world / "props" / "wingback-chair-aaa111").glob("*.tmp")))


def part3_not_idempotent(worlds: Path, world: Path) -> None:
    print("\n3) the script remembers nothing — a second run shifts again")
    rc, out, err = run(worlds, "--world", "fixture", "--apply",
                       "--group", "seat", "--delta-m", SEAT_DELTA)
    check("exit code", rc, 0)
    chair = markers(world, "wingback-chair-aaa111")
    # 0.4567 + 0.2715/0.9 = 0.4567 + 0.301667 = 0.758367 -> 0.7584
    check("wingback v0 shifted a second time", chair[0][0]["at"][1], 0.7584)
    bed = markers(world, "king-size-bed-bbb222")
    check("bed untouched without its group", bed[0][0]["at"][1], 0.4358)

    print("   and a zero delta is a no-op")
    before = snapshot(world)
    rc, out, err = run(worlds, "--world", "fixture", "--apply",
                       "--group", "seat", "--delta-m", "0")
    check("exit code", rc, 0)
    check("nothing rewritten", snapshot(world), before)
    check_true("summary says zero", "written 0 markers in 0 files" in out, out)


def part4_guards(worlds: Path) -> None:
    print("\n4) guards")
    rc, out, err = run(worlds, "--group", "seat", "--delta-m", SEAT_DELTA)
    check_true("--world is required", rc != 0, out + err)

    rc, out, err = run(worlds, "--world", "nope",
                       "--group", "seat", "--delta-m", SEAT_DELTA)
    check_true("unknown world fails", rc != 0, out + err)

    rc, out, err = run(worlds, "--world", "fixture",
                       "--group", "stand", "--delta-m", SEAT_DELTA)
    check_true("stand is refused", rc != 0, out + err)
    check_true("stand refusal names the group", "stand" in (out + err), out + err)

    rc, out, err = run(worlds, "--world", "fixture",
                       "--group", "seat", "--group", "bed",
                       "--delta-m", SEAT_DELTA)
    check_true("unpaired --group/--delta-m fails", rc != 0, out + err)

    rc, out, err = run(worlds, "--world", "fixture",
                       "--group", "seat", "--delta-m", SEAT_DELTA,
                       "--group", "seat", "--delta-m", BED_DELTA)
    check_true("a repeated --group fails", rc != 0, out + err)
    check_true("the repeat message names the group",
               "seat" in (out + err), out + err)

    rc, out, err = run(worlds, "--world", "fixture")
    check_true("no group at all fails", rc != 0, out + err)


def main() -> int:
    if not SCRIPT.exists():
        print(f"missing {SCRIPT}")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="smoke_lift_markers_"))
    try:
        worlds = tmp / "worlds"
        world = worlds / "fixture"
        build_world(world)
        part1_dry_run(worlds, world)
        part2_apply(worlds, world)
        part3_not_idempotent(worlds, world)
        part4_guards(worlds)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("smoke_lift_prop_markers: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
