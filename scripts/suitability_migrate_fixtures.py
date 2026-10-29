"""Add prompt-derived per-case catalogs to a NEW fixture file, never in place."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.suitability_scoring import prepare_case, fixture_version


def migrate(source, output=None):
    source = Path(source)
    output = Path(output) if output else source.with_name(source.stem + '.v2.json')
    if source.resolve() == output.resolve():
        raise ValueError('Source is read-only; choose a separate output')
    data = json.loads(source.read_text())
    data.pop('allowed_tools', None)
    data['cases'] = [prepare_case(c) for c in data.get('cases', [])]
    data['fixture_version'] = fixture_version(data['cases'])
    with output.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--output')
    args = parser.parse_args()
    print(migrate(args.source, args.output))
