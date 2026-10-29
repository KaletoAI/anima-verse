"""Conservative offline rescore into a separate NEW file; never call a provider.

Legacy strings are capped at 600 characters, omit repeats and finish metadata,
so only observed local evidence is reported. A full case verdict is undecidable.
Fixture versions that cannot be established from history remain unknown.
"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.suitability_scoring import SCORER_VERSION, prepare_case, score_case, fixture_version, semantic_cases, TAG, MARKERS


def rescore(fixtures, capabilities, outputs, model):
    prepared = [prepare_case(c) for c in fixtures['cases']]
    ids = {c['id'] for c in prepared}
    prepared += [c for c in semantic_cases() if c['id'] not in ids]
    cases = {c['id']: c for c in prepared}
    old = capabilities.get('suitability', {}).get(model.lower(), {})
    raw = outputs.get('outputs', {}).get(model.lower(), {})
    versioned = isinstance(raw.get('cases'), dict)
    checks = old.get('tested_suitability', {}).get('checks', [])
    rows = []
    for check in checks:
        ident = check['id']
        case = cases.get(ident)
        saved = raw.get('cases', {}).get(ident, []) if versioned else raw.get(ident)
        row = {'id': ident, 'verdict': 'undecidable', 'reason': 'missing raw data', 'observations': []}
        if case:
            claimed_unknown = re.search(r'unknown/invented tool\(s\): (.*)', check.get('detail', ''))
            if claimed_unknown:
                names = re.findall(r"'([A-Za-z_]+)'", claimed_unknown.group(1))
                row['catalog_evaluation_error'] = bool(names) and all(n in case.get('allowed_tools', []) for n in names)
        if case and saved:
            runs = saved if versioned else [{'content': saved}]
            row['observations'] = [score_case(case, r.get('content', ''), finish_reason=r.get('finish_reason'), infra_error=bool(r.get('error'))) for r in runs]
            if not versioned:
                for observation in row['observations']:
                    observation['ok'] = None
                    observation['evidence_completeness'] = 'undecidable'
                row['possibly_capped'] = len(saved) >= 600
                # An illegal prose prefix cannot be repaired by an unknown suffix.
                prefix = MARKERS.sub('', TAG.sub('', saved)).strip()
                row['observed_analysis_prefix'] = case.get('category') == 'tool' and bool(prefix and not prefix.startswith(('<tool', 'NONE', 'SKIP', '[', '**I ')))
                row['observed_malformed_marker'] = bool(re.search(r'\*\*I (?:do|feel)\*\*', saved))
                row['observed_none_tool_conflict'] = case.get('category') == 'tool' and bool(TAG.search(saved) and re.search(r'\bNONE\b', prefix))
            if case.get('task') == 'image_analysis':
                row.update(classification='evaluation_error', reason='missing_input: no image was sent')
            elif not versioned:
                row.update(reason='legacy: selected response only; possibly capped at 600 chars; missing repeats, finish metadata and original fixture version')
                if row['observed_analysis_prefix'] or row['observed_none_tool_conflict'] or row['observed_malformed_marker']:
                    row['classification'] = 'observed_model_format_error'
                else:
                    row['classification'] = 'undecidable'
            elif (raw.get('fixture_version') == fixture_version(list(cases.values()))
                  and len(runs) == int(case.get('repeats', 1))
                  and all(r.get('finish_reason') in ('stop', 'length', 'content_filter') and 'content' in r for r in runs)):
                row.update(verdict='rescored', reason='all repetitions and finish metadata present; invalid runs remain excluded')
        elif not case:
            row['reason'] = 'case absent from supplied fixture set'
        rows.append(row)
    return {'kind': 'offline_rescore', 'model': model, 'scorer_version': SCORER_VERSION,
            'fixture_version': fixture_version(list(cases.values())), 'original_fixture_version': raw.get('fixture_version', 'unknown'), 'checks': rows}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('fixtures', 'capabilities', 'outputs', 'model', 'output'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    target = Path(a.output)
    sources = [Path(getattr(a, n)).resolve() for n in ('fixtures', 'capabilities', 'outputs')]
    if target.resolve() in sources or target.name in ('model_capabilities.json', 'model_capabilities_outputs.json'):
        p.error('Choose a separate output file')
    result = rescore(*(json.loads(x.read_text()) for x in sources), a.model)
    with target.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    for row in result['checks']:
        print(row['id'], row['verdict'], row.get('classification', ''), row['reason'])
