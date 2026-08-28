#!/usr/bin/env python3
"""Smoke: the marker-repair script lifts at[1] by metres, per variant height.

Usage:
    ./.venv/bin/python scripts/smoke_lift_prop_markers.py

Runs WITHOUT the server and WITHOUT a world DB: it builds a throwaway world
tree in a temp dir and drives ``scripts/lift_prop_markers.py`` over it as a
subprocess. Nothing under ``worlds/`` is touched.

The expected numbers are derived BY HAND from the conversion the script
performs (``at[1] += delta_m / height_m``, rounded to 4 decimals like
``props.sanitize_markers``) — never copied from a run:

    seat delta = +0.2715 m   (drawn buttock height 0.8053 - applied drop 0.5338)
    bed  delta = -0.2802 m   (drop 1.0727 - laying's lowest point 0.7925)

    wingback  v0  h = 1.14 m   0.155 + 0.2715/1.14 = 0.155 + 0.238158 = 0.393158 -> 0.3932
    wingback  v1  h = 0.57 m   0.155 + 0.2715/0.57 = 0.155 + 0.476316 = 0.631316 -> 0.6313
    king bed  v0  h = 1.25 m   0.660 - 0.2802/1.25 = 0.660 - 0.224160 = 0.435840 -> 0.4358
    stand         h = 1.14 m   untouched, whatever the delta

The two wingback variants carry the SAME old fraction at DIFFERENT heights and
must land on different new fractions — that is the per-variant-height check.

Composed metres (the column the report compares against the finding's
expectation table) are ``at[1] * height_m``:

    wingback v0   0.155 x 1.14 = 0.17670 m  ->  0.3932 x 1.14 = 0.448248 m
                  the rise is 0.271548 m ~ the requested 0.2715 m (rounding)
    king bed      0.660 x 1.25 = 0.82500 m  ->  0.4358 x 1.25 = 0.544750 m

Clamp case (``props.MARKER_AT_MAX`` = 1.5, and index 1 has its own lower bound
``MARKER_AT_Y_MIN`` = -1.0):

    stool  h = 0.50 m   1.400 + 0.2715/0.50 = 1.400 + 0.543 = 1.943 -> clamped 1.5

Non-idempotency is deliberate and is pinned here: the script stores no "already
lifted" mark, so running it twice with the same delta shifts twice
(0.3932 + 0.238158 = 0.631358 -> 0.6314). The user runs it exactly once.
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

def _sidecar(name: str, variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A prop master record trimmed to what the script reads — plus a few
    unrelated keys, so the rewrite is proven to keep the rest of the file."""
    return {
        "name": name,
        "category": "furniture",
        "tags": ["demo"],
        "created_at": "2026-08-29T00:00:00+00:00",
        "model_variants": variants,
    }


def build_world(root: Path) -> None:
    props = root / "props"
    (props / "wingback-chair-aaa111").mkdir(parents=True)
    (props / "king-size-bed-bbb222").mkdir(parents=True)
    (props / "wooden-stool-ccc333").mkdir(parents=True)
    # A prop dir without a sidecar — must be skipped silently.
    (props / "broken-ddd444").mkdir(parents=True)

    (props / "wingback-chair-aaa111" / "sidecar.json").write_text(
        json.dumps(_sidecar("Wingback chair", [
            {"stem": "wingback", "active": True, "height_m": 1.14,
             "width_m": 0.9, "depth_m": 0.95, "markers": [
                 {"id": "q4zmnmq4", "group": "seat", "at": [0.505, 0.155, 0.786]},
                 {"id": "s7ta9d1x", "group": "stand", "at": [0.5, 0.3, 0.2],
                  "facing": 90},
             ]},
            {"stem": "wingback-low", "active": False, "height_m": 0.57,
             "width_m": 0.9, "depth_m": 0.95, "markers": [
                 {"id": "b2c3d4e5", "group": "seat", "at": [0.505, 0.155, 0.786],
                  "capacity": 2, "spacing_m": 0.6},
             ]},
        ]), indent=2, ensure_ascii=False), encoding="utf-8")

    (props / "king-size-bed-bbb222" / "sidecar.json").write_text(
        json.dumps(_sidecar("King size bed", [
            {"stem": "kingbed", "active": True, "height_m": 1.25,
             "width_m": 2.0, "depth_m": 2.1, "markers": [
                 {"id": "ymzz7gz6", "group": "bed", "at": [0.5, 0.66, 0.5]},
             ]},
        ]), indent=2, ensure_ascii=False), encoding="utf-8")

    (props / "wooden-stool-ccc333" / "sidecar.json").write_text(
        json.dumps(_sidecar("Wooden stool", [
            {"stem": "stool", "active": True, "height_m": 0.5,
             "width_m": 0.4, "depth_m": 0.4, "markers": [
                 {"id": "clampme1", "group": "seat", "at": [0.5, 1.4, 0.5]},
             ]},
        ]), indent=2, ensure_ascii=False), encoding="utf-8")


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
    check_true("table shows the new seat fraction 0.3932", "0.3932" in out, out)
    check_true("table shows the per-variant 0.6313", "0.6313" in out, out)
    check_true("table shows the new bed fraction 0.4358", "0.4358" in out, out)
    check_true("table shows composed metres 0.448",
               "0.448" in out, out)
    check_true("clamp is reported", "clamped" in out.lower(), out)
    check_true("closing line names the server",
               "dry run — nothing written; stop the server before --apply" in out,
               out)
    check_true("no stray stderr", err.strip() == "", err)
    check_true("stand marker absent from the table", "s7ta9d1x" not in out, out)


def part2_apply(worlds: Path, world: Path) -> None:
    print("\n2) --apply — hand-derived values land in the files")
    rc, out, err = run(worlds, "--world", "fixture", "--apply",
                       "--group", "seat", "--delta-m", SEAT_DELTA,
                       "--group", "bed", "--delta-m", BED_DELTA)
    check("exit code", rc, 0)
    check_true("summary counts markers and files",
               "written 4 markers in 3 files" in out, out)

    chair = markers(world, "wingback-chair-aaa111")
    check("wingback v0 seat at[1]", chair[0][0]["at"][1], 0.3932)
    check("wingback v0 seat at[0] untouched", chair[0][0]["at"][0], 0.505)
    check("wingback v0 seat at[2] untouched", chair[0][0]["at"][2], 0.786)
    check("stand marker untouched", chair[0][1]["at"], [0.5, 0.3, 0.2])
    check("stand facing kept", chair[0][1].get("facing"), 90)
    check("wingback v1 uses ITS height", chair[1][0]["at"][1], 0.6313)
    check("capacity/spacing kept", (chair[1][0].get("capacity"),
                                    chair[1][0].get("spacing_m")), (2, 0.6))

    bed = markers(world, "king-size-bed-bbb222")
    check("king bed at[1]", bed[0][0]["at"][1], 0.4358)

    stool = markers(world, "wooden-stool-ccc333")
    check("stool clamped to MARKER_AT_MAX", stool[0][0]["at"][1], 1.5)

    data = json.loads((world / "props" / "wingback-chair-aaa111" / "sidecar.json")
                      .read_text(encoding="utf-8"))
    check("unrelated keys survive", data["name"], "Wingback chair")
    check("variant keys survive", sorted(data["model_variants"][0]),
          ["active", "depth_m", "height_m", "markers", "stem", "width_m"])
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
    # 0.3932 + 0.2715/1.14 = 0.3932 + 0.238158 = 0.631358 -> 0.6314
    check("wingback v0 shifted a second time", chair[0][0]["at"][1], 0.6314)
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
