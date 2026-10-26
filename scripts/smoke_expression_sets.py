#!/usr/bin/env python3
"""Expression sets: specification-derived storage/migration/resolver invariants.
Two shipped sets contain 8 humanoid and 4 animal members. Candidate identity
is (axis,set_id,text), so two sightings in different sets remain two rows and
a dismissal survives catalog edits. All catalog edits use temporary files.
Usage: ./.venv/bin/python scripts/smoke_expression_sets.py [--storage|--resolver]
"""
import os
import sys
import tempfile
import shutil
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-contract-")
STORAGE = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db
config.load(STORAGE / "config.json")
db.init_schema()
from app.core import pose_catalog as pc
catalog_paths = {}
for axis in ("pose", "expression"):
    target = STORAGE / f"{axis}.json"
    shutil.copyfile(pc.catalog_path(axis), target)
    catalog_paths[axis] = target
pc.catalog_path = lambda axis: catalog_paths[axis]
pc.reload_catalogs()
from app.core.expression_sets_migration import migrate_catalog_metadata
migrate_catalog_metadata()

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from app.core import expression_sets as es
from app.core.expression_sets_migration import migrate_candidates
from app.routes.poses import list_entries
from app.core import decision

if '--resolver' not in sys.argv:
    response = list_entries(axis='expression', _={})
    assert len(response['groups']['animal']['members']) == 4
    assert len(response['groups']['humanoid']['members']) == 8
    old = sqlite3.connect(':memory:')
    old.execute("CREATE TABLE pose_candidates(axis TEXT,raw_text TEXT,nearest_key TEXT,distance REAL,count INTEGER,status TEXT,first_seen TEXT,last_seen TEXT,PRIMARY KEY(axis,raw_text))")
    old.execute("INSERT INTO pose_candidates VALUES('expression','unknown','neutral',0.9,7,'dismissed','first','last')")
    old.execute("INSERT INTO pose_candidates VALUES('pose','unknown','standing',0.8,3,'open','first','last')")
    migrate_candidates(old)
    rows = old.execute('SELECT axis,set_id,count,status,first_seen,last_seen FROM pose_candidates ORDER BY axis').fetchall()
    assert rows == [('expression','humanoid',7,'dismissed','first','last'),('pose','',3,'open','first','last')]
    migrate_candidates(old)
    assert old.execute('SELECT count(*) FROM pose_candidates').fetchone()[0] == 2
    old.close()
    base = es.catalog_snapshot()
    try:
        es.edit_entry('create', 'demo_bad_alias', {'prompt':'a calm face','synonyms':['happy'],'store':'world'}, set_id='humanoid')
        raise AssertionError('Ambiguous alias edit must fail')
    except es.ExpressionSetError:
        assert es.catalog_snapshot().revision == base.revision
    es.edit_entry('update', 'positive', {'prompt':'a changed smile','store':'world'}, set_id='humanoid')
    assert es.catalog_snapshot().entries['positive']['_store'] == 'world'
    es.edit_entry('delete', 'positive', {}, set_id='humanoid')
    restored = es.catalog_snapshot()
    assert 'positive' in restored.sets['humanoid'].members
    assert restored.entries['positive']['prompt'] == base.entries['positive']['prompt']
    es.edit_entry('update', 'neutral', {'prompt':'a calm changed face','store':'world'}, set_id='humanoid')
    es.edit_entry('delete', 'neutral', {}, set_id='humanoid')
    assert es.catalog_snapshot().sets['humanoid'].default == 'neutral'
    before = es.catalog_snapshot().revision
    try:
        es.edit_entry('delete', 'neutral', {}, set_id='humanoid')
        raise AssertionError('Effective default deletion must fail')
    except es.ExpressionSetError:
        assert es.catalog_snapshot().revision == before
    es.replace_set('demo', {'label':'Demo','default':'demo_neutral','pose_prompt':'standing naturally','members':['demo_neutral'],
        'entries':{'demo_neutral':{'prompt':'neutral expression','synonyms':['neutral']}}}, store='world')
    assert pc.resolve_to_catalog('neutral','expression',set_id='demo')[0] == 'demo_neutral'
    es.delete_set('demo',store='world')
    assert 'demo' not in es.catalog_snapshot().sets
    original = catalog_paths['expression'].read_text()
    legacy = json.loads(original)
    legacy['entries']['demo_legacy'] = {'prompt':'a contemplative expression','synonyms':['demo contemplative'],'_default':True}
    catalog_paths['expression'].write_text(json.dumps(legacy))
    with db.transaction() as conn:
        conn.execute("DELETE FROM schema_meta WHERE key='expression_sets_v1'")
    pc.reload_catalogs()
    migrate_catalog_metadata()
    assert 'demo_legacy' in es.catalog_snapshot().sets['humanoid'].members
    assert es.catalog_snapshot().sets['humanoid'].default == 'demo_legacy'
    before = es.catalog_snapshot().revision
    migrate_catalog_metadata()
    assert es.catalog_snapshot().revision == before
    catalog_paths['expression'].write_text(original)
    with db.transaction() as conn:
        conn.execute("DELETE FROM pose_catalog_world WHERE axis='expression'")
        conn.execute("DELETE FROM schema_meta WHERE key='expression_sets_v1'")
    pc.reload_catalogs()
    migrate_catalog_metadata()
    print('PASS expression storage, invalid edits, override/default reset, migration and repeat safety')

if '--storage' not in sys.argv:
    none = lambda text: None
    assert pc.resolve_to_catalog('neutral','expression',none,set_id='humanoid')[0] == 'neutral'
    assert pc.resolve_to_catalog('neutral','expression',none,set_id='animal')[0] == 'animal_neutral'
    assert pc.resolve_to_catalog('unknown phrase','expression',none,set_id='animal')[0] == 'animal_neutral'
    assert pc.resolve_to_catalog('unknown phrase','expression',none,set_id='humanoid')[0] == 'neutral'
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM pose_candidates WHERE raw_text='unknown phrase'").fetchone()[0] == 2
    assert pc.set_candidate_status('expression','unknown phrase','dismissed',set_id='animal')
    pc.record_candidate('expression','unknown phrase','animal_neutral',1.0,set_id='animal')
    with db.transaction() as conn:
        status,count = conn.execute("SELECT status,count FROM pose_candidates WHERE axis='expression' AND set_id='animal' AND raw_text='unknown phrase'").fetchone()
        assert (status,count) == ('dismissed',2)
    with patch.object(decision,'is_active',return_value=True), patch.object(decision,'decide',return_value=SimpleNamespace(answers={'entry':SimpleNamespace(value='positive')})):
        assert pc.resolve_to_catalog('new phrase','expression',none,set_id='animal')[0] == 'animal_neutral', 'Decision escaped the animal set'
    try:
        pc.resolve_to_catalog('neutral','expression',none,set_id='missing')
        raise AssertionError('Invalid expression set must not silently fall back')
    except es.ExpressionSetError:
        pass
    print('PASS scoped aliases/defaults, decision rejection, independent candidates and persistent dismissal')
TMP.cleanup()
