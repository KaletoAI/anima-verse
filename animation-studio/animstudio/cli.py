"""``python -m animstudio <command>`` — run from animation-studio/ with the
repository's venv: ``../.venv/bin/python -m animstudio build wave``."""
import argparse
import json
import sys

import animstudio
from animstudio import StudioError


def _print_report(r: dict) -> None:
    for c in r["checks"]:
        mark = "ok  " if c["ok"] else "FAIL"
        print(f"  {mark} {c['name']:<14} {c['value']:>8} ({c['limit']}) {c['detail']}")
    print("PASSED" if r["ok"] else "FAILED")


def main(argv=None) -> int:
    animstudio.bootstrap()
    ap = argparse.ArgumentParser(prog="animstudio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="compile + bake anims/<kind>.py into out/<kind>/")
    p.add_argument("kind")
    p = sub.add_parser("sheet", help="render out/<kind>/sheet.png (front + left view)")
    p.add_argument("kind")
    p.add_argument("--columns", type=int, default=6)
    p = sub.add_parser("check", help="print the report of the last build")
    p.add_argument("kind")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            from animstudio.build import build
            r = build(args.kind)
            print(f"built {args.kind}: {r['fbx']}")
            _print_report(r)
            return 0 if r["ok"] else 1
        if args.cmd == "check":
            path = animstudio.OUT / args.kind / "build.json"
            if not path.is_file():
                raise StudioError(f"{path} missing - build first")
            r = json.loads(path.read_text(encoding="utf-8"))
            _print_report(r)
            return 0 if r["ok"] else 1
        if args.cmd == "sheet":
            from animstudio.sheet import sheet
            print(f"sheet: {sheet(args.kind, args.columns)}")
            return 0
    except StudioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
