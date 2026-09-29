"""``python -m animstudio <command>`` — run from animation-studio/ with the
repository's venv: ``../.venv/bin/python -m animstudio build wave``.

Exit codes: 0 done; 1 the checks failed (``build``/``check``, also a
build.json that recorded no checks); 2 an error (printed, nothing
committed); 3 ``publish`` committed, but the shared git index could not be
re-synced — the commit IS on HEAD, run the printed ``git reset`` command
(rerunning publish is not needed).
"""
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
    p = sub.add_parser("publish", help="publish out/<kind> into shared/ + pose catalog + commit")
    p.add_argument("kind")
    p.add_argument("--replace", action="store_true", help="overwrite an OWN earlier studio clip")
    p.add_argument("--no-commit", action="store_true")
    p.add_argument("--trailer", default="", help="commit trailer lines (see the repo CLAUDE.md, Git)")
    p = sub.add_parser("list", help="existing clip kinds and pose keys (optional filter)")
    p.add_argument("text", nargs="?", default="")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            from app.core.animation_clips import clip_entries
            from app.core.pose_catalog import get_catalog
            q = args.text.strip().lower()
            kinds = sorted({(e["kind"], e["source"]) for e in clip_entries()})
            print("clips:")
            for k, src in kinds:
                if q in k:
                    print(f"  {k:<28} {src}")
            print("poses:")
            for key, e in sorted(get_catalog("pose").items()):
                hay = " ".join([key, e.get("animation", "")] + e.get("synonyms", [])).lower()
                if q in hay:
                    syn = ", ".join(e.get("synonyms", [])[:4])
                    print(f"  {key:<24} -> {e.get('animation', ''):<22} [{e.get('group', '')}] {syn}")
            return 0
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
            if not r.get("checks"):
                print("no checks recorded — build again")
                return 1
            _print_report(r)
            return 0 if r["ok"] else 1
        if args.cmd == "sheet":
            from animstudio.sheet import sheet
            print(f"sheet: {sheet(args.kind, args.columns)}")
            return 0
        if args.cmd == "publish":
            from animstudio.publish import publish
            r = publish(args.kind, replace=args.replace, commit=not args.no_commit,
                        trailer=args.trailer)
            if not r["commit"]:
                tail = " (not committed)"
            elif r["commit_created"]:
                tail = f", commit {r['commit']}"
            else:
                tail = f", nothing new to commit - HEAD {r['commit']} already has it"
            print(f"published {r['kind']} as pose '{r['key']}'{tail}")
            print(f"note: {r['note']}")
            if r["warning"]:
                print(f"warning: {r['warning']}", file=sys.stderr)
                return 3
            return 0
    except StudioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
