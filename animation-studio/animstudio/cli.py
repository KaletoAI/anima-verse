"""``python -m animstudio <command>`` — run from animation-studio/ with the
repository's venv: ``../.venv/bin/python -m animstudio build wave``."""
import argparse
import sys

import animstudio
from animstudio import StudioError


def main(argv=None) -> int:
    animstudio.bootstrap()
    ap = argparse.ArgumentParser(prog="animstudio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="compile + bake anims/<kind>.py into out/<kind>/")
    p.add_argument("kind")
    p = sub.add_parser("sheet", help="render out/<kind>/sheet.png (front + left view)")
    p.add_argument("kind")
    p.add_argument("--columns", type=int, default=6)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            from animstudio.build import build
            r = build(args.kind)
            print(f"built {args.kind}: {r['fbx']}")
            return 0 if r["ok"] else 1
        if args.cmd == "sheet":
            from animstudio.sheet import sheet
            print(f"sheet: {sheet(args.kind, args.columns)}")
            return 0
    except StudioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
