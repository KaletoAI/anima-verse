"""Usage: .venv/bin/python scripts/smoke_mesh_part_panel.py

Hand-derived: no attached op means no row. 12 mm equals the default threshold
and is green; 13 exceeds it and is yellow. A 20 mm threshold keeps 13 green.
A failed operation exposes its literal reason. All four English UI labels
must have German translations and live calls in the Part row source.
"""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.model3d import attached_part_info
    assert attached_part_info({'group_ops': {'part': 'appendage_chain'}}) is None
    def info(**metrics):
        return attached_part_info({'group_ops': {'part': 'attached_part'}, 'metrics': {'part': metrics}})
    assert info(status='built', protrusion_mm=12) == dict(status='built', reason='', protrusion_mm=12, warning=False)
    assert info(status='built', protrusion_mm=13)['warning'] is True
    assert info(status='built', protrusion_mm=13, protrusion_warn_mm=20)['warning'] is False
    assert attached_part_info({'group_ops': {'part': 'attached_part'},
        'group_params': {'part': {'protrusion_warn_mm': 20}},
        'metrics': {'part': {'status': 'built', 'protrusion_mm': 13}}})['warning'] is False
    assert info(status='failed', reason='fixture failure')['reason'] == 'fixture failure'
    root = Path(__file__).resolve().parents[1]
    de = json.loads((root/'shared/languages/de.json').read_text())['translations']
    source = (root/'frontend/src/tabs/characters/FieldModel3D.tsx').read_text()
    for text in ('Part', 'built', 'not built', 'built — body still shows a protrusion of {n} mm; regenerate the T-pose'):
        assert text in de and f"t('{text}')" in source, text
    assert "!partBuilt ? 'red' : part.warning ? 'yellow' : 'green'" in source
print('PASS mesh_part panel/i18n: absent, built, threshold 12/13/20, failed, German keys')
