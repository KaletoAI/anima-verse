"""A174 item 4: a refit whose CURRENT base lacks its views/model is a plain missing-input refusal, no offer.

Usage: ./.venv/bin/python scripts/smoke_refit_missing_base.py

Case (live 2026-11-17, Kira / Black Blazer): the base identity moved to a set that is not rendered yet
(base views missing, base model sha ''), the item's accepted source was made on base20d5701a. Before, the
refit reported "keep the old fit, accept the refit anyway or make a new mesh" — nothing was fitted (no 3D
view, nothing to accept). Hand-derived expectations:
- _refit_from_source -> ok False, missing_input True, attempt False, error = BASE_IMAGES_MISSING
- the copied source is dropped again (1 drop call)
- refit_stopped_info with base sha '' -> None (no offer row without a base model)
"""
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import paths
paths.init(tempfile.mkdtemp())
from app.core import base_body, garments, garment_source, garment_store as gs

fails = 0
def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(('OK  ' if ok else 'FAIL'), label, repr(got), '' if ok else f'(want {want!r})')

drops = []
garment_source.has_own_images = lambda *a, **k: False
garment_source.is_materialized = lambda *a, **k: False
garment_source.find_source = lambda *a, **k: {'fsig': '8548fb821c26', 'bsig': 'base20d5701a'}
garment_source.materialize = lambda *a, **k: None
garment_source.drop_materialized = lambda *a, **k: drops.append(a)
gs.start = lambda *a, **k: None
gs.end = lambda *a, **k: None
def fit(*a, **k):
    raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
garments._fit = fit
r = garments._refit_from_source('Demo', 'item_x', 'clothing', gs.EDIT_CHAIN, '19644944d90f', 'basef562426a', {})
check('ok', r['ok'], False)
check('missing_input', r.get('missing_input'), True)
check('attempt', r['attempt'], False)
check('error', r['error'], base_body.BASE_IMAGES_MISSING)
check('copies dropped', len(drops), 1)
check('no offer without a base model', garments.refit_stopped_info('Demo', 'item_x', '19644944d90f', '', {}), None)
print('FAILED' if fails else 'ALL OK')
sys.exit(1 if fails else 0)
