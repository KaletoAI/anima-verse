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
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            from animstudio.build import build
            r = build(args.kind)
            print(f"built {args.kind}: {r['fbx']}")
            return 0 if r["ok"] else 1
    except StudioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
