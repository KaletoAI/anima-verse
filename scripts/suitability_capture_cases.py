"""Capture world-local suitability candidates for hand review.

Usage: ./.venv/bin/python scripts/suitability_capture_cases.py --since ISO [--world NAME]
Writes suitability_cases.json in the selected world and prints complete candidates.
After reviewing prompts, sets and expectations, use --review ID to mark a case.
No provider calls are made and no world database is opened.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since')
    parser.add_argument('--world')
    parser.add_argument('--log', type=Path)
    parser.add_argument('--review', action='append', default=[], metavar='ID')
    args = parser.parse_args()
    if not args.since and not args.review:
        parser.error('--since is required when capturing candidates')
    from app.core import paths
    if args.world:
        if Path(args.world).name != args.world or args.world in ('.', '..'):
            parser.error('--world must be a world name')
        paths.init(Path(__file__).resolve().parents[1] / 'worlds' / args.world)
    else:
        paths.init()
    # Initialize storage before importing any world-dependent module.
    from app.core.model_suitability import build_cases_from_log
    from app.core.suitability_scoring import fixture_version
    target = paths.get_storage_dir() / 'suitability_cases.json'
    if args.since:
        try:
            build_cases_from_log(args.log, since=args.since)
        except ValueError as error:
            parser.error(str(error))
    data = json.loads(target.read_text(encoding='utf-8'))
    requested = set(args.review)
    found = {c['id'] for c in data['cases']}
    if requested - found:
        parser.error('Unknown case ids: ' + ', '.join(sorted(requested - found)))
    for case in data['cases']:
        if case['id'] in requested:
            case['reviewed'] = True
    if requested:
        data['fixture_version'] = fixture_version(data['cases'])
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(str(target))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
