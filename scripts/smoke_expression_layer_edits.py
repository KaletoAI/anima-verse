#!/usr/bin/env python3
"""Shared edits must remain valid in an already migrated world without overrides.
World group promotion must take effect without erasing seeded entry overrides.
A failed SQLite commit must leave Shared definitions and World rows unchanged.
Usage: ./.venv/bin/python scripts/smoke_expression_layer_edits.py [--case NAME]
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

import argparse
import sqlite3
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from app.core import expression_sets as es

SECOND = STORAGE / 'second-world'
SECOND_PROGRAM = r"""
import json, os, sys
from pathlib import Path
world, catalog, key, present = sys.argv[1:]
os.environ['STORAGE_DIR'] = world
os.environ['INSTANCE_DIR'] = str(Path(world)/'instance')
from app.core import paths
paths.init(world)
paths.init_instance(Path(world)/'instance')
from app.core import config, db
config.load(Path(world)/'config.json', Path(world)/'instance/config.json')
db.init_schema()
from app.core import pose_catalog as pc
original_path = pc.catalog_path
pc.catalog_path = lambda axis: Path(catalog) if axis == 'expression' else original_path(axis)
from app.core.expression_sets_migration import migrate_catalog_metadata
migrate_catalog_metadata()
from app.core.expression_sets import catalog_snapshot
snapshot = catalog_snapshot()
assert (key in snapshot.entries) == (present == 'yes')
assert all(member in snapshot.entries for spec in snapshot.sets.values() for member in spec.members)
print(json.dumps(db.get_connection().execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()[0]))
"""

def second_world(key, present):
    result = subprocess.run([sys.executable, '-c', SECOND_PROGRAM, str(SECOND),
        str(catalog_paths['expression']), key, 'yes' if present else 'no'],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])

marker = second_world('positive', True)

def world_override():
    es.edit_entry('update', 'positive', {'prompt':'a world-specific smile', 'store':'world'}, set_id='humanoid')

def create():
    world_override()
    es.edit_entry('create', 'demo_shared', {'prompt':'a contemplative face', 'store':'shared'}, set_id='humanoid')
    assert 'demo_shared' in es.catalog_snapshot().sets['humanoid'].members
    assert second_world('demo_shared', True) == marker

def approve():
    world_override()
    pc.record_candidate('expression', 'demo curiosity', '', None, set_id='humanoid')
    es.approve_candidate({'set_id':'humanoid','raw_text':'demo curiosity','key':'demo_approved',
                          'prompt':'a curious face','store':'shared'})
    assert 'demo_approved' in es.catalog_snapshot().sets['humanoid'].members
    assert second_world('demo_approved', True) == marker

def delete():
    es.edit_entry('create', 'demo_deleted', {'prompt':'a contemplative face', 'store':'shared'}, set_id='humanoid')
    world_override()
    es.edit_entry('delete', 'demo_deleted', {}, set_id='humanoid')
    assert 'demo_deleted' not in es.catalog_snapshot().entries
    assert second_world('demo_deleted', False) == marker

def promote():
    animal = es.catalog_snapshot().sets['animal']
    document = {'label':'World animal','default':animal.default,'pose_prompt':animal.pose_prompt,
                'members':list(animal.members)}
    es.replace_set('animal', document, store='world')
    es.edit_entry('update', 'animal_neutral', {'prompt':'a world-specific neutral animal face','store':'world'}, set_id='animal')
    es.replace_set('animal', {**document, 'label':'Published animal'}, store='shared')
    snapshot = es.catalog_snapshot()
    assert snapshot.sets['animal'].store == 'shared' and snapshot.sets['animal'].label == 'Published animal'
    assert snapshot.entries['animal_neutral']['_store'] == 'world'
    assert snapshot.entries['animal_neutral']['prompt'] == 'a world-specific neutral animal face'
    custom = {'label':'Demo','default':'demo_neutral','pose_prompt':'standing neutrally',
              'members':['demo_neutral'], 'entries':{'demo_neutral':{'prompt':'a neutral expression'}}}
    es.replace_set('demo', custom, store='world')
    es.replace_set('demo', {k:v for k,v in custom.items() if k != 'entries'}, store='shared')
    assert es.catalog_snapshot().entries['demo_neutral']['_store'] == 'shared'
    assert second_world('demo_neutral', True) == marker

def commit():
    world_override()
    conn = db.get_connection()
    before_shared = json.loads(catalog_paths['expression'].read_text())
    before_rows = [tuple(r) for r in conn.execute("SELECT * FROM pose_catalog_world ORDER BY axis,kind,key")]
    def fail_commit():
        raise sqlite3.OperationalError('simulated commit I/O failure')
    proxy = SimpleNamespace(execute=conn.execute, commit=fail_commit, rollback=conn.rollback)
    with patch.object(db, 'get_connection', return_value=proxy):
        try:
            es.edit_entry('rename','positive',{'new_key':'demo_positive'},set_id='humanoid')
            raise AssertionError('Failed commit must surface')
        except sqlite3.OperationalError:
            pass
    assert json.loads(catalog_paths['expression'].read_text()) == before_shared, 'Shared definitions survived a failed SQLite commit'
    assert [tuple(r) for r in conn.execute("SELECT * FROM pose_catalog_world ORDER BY axis,kind,key")] == before_rows
    assert es.catalog_snapshot().entries['positive']['_store'] == 'world'

def set_delete():
    es.replace_set('demo', {'label':'Demo','default':'demo_neutral','pose_prompt':'standing neutrally',
        'members':['demo_neutral'], 'entries':{'demo_neutral':{'prompt':'a neutral face'}}}, store='shared')
    es.edit_entry('update', 'demo_neutral', {'prompt':'world neutral face','store':'world'}, set_id='demo')
    es.edit_entry('create', 'demo_extra', {'prompt':'a curious face','store':'world'}, set_id='demo')
    es.delete_set('demo', store='world')
    snapshot = es.catalog_snapshot()
    assert snapshot.sets['demo'].store == 'shared' and 'demo_extra' not in snapshot.entries
    assert snapshot.entries['demo_neutral']['_store'] == 'world'
    es.edit_entry('create', 'demo_extra', {'prompt':'a curious face','store':'world'}, set_id='demo')
    es.delete_set('demo', store='shared')
    snapshot = es.catalog_snapshot()
    assert 'demo' not in snapshot.sets
    assert not {'demo_neutral','demo_extra'}.intersection(snapshot.entries)
    assert second_world('demo_neutral', False) == marker

def world_only():
    es.replace_set('demo', {'label':'Demo','default':'demo_neutral','pose_prompt':'standing neutrally',
        'members':['demo_neutral'], 'entries':{'demo_neutral':{'prompt':'a neutral face'}}}, store='world')
    before = es.catalog_snapshot().revision
    try:
        es.edit_entry('create','demo_shared',{'prompt':'a curious face','store':'shared'},set_id='demo')
        raise AssertionError('Shared member in a World-only set must be rejected')
    except es.ExpressionSetError:
        assert es.catalog_snapshot().revision == before
    assert second_world('demo_shared', False) == marker

def legacy():
    document = json.loads(catalog_paths['expression'].read_text())
    document['entries']['demo_legacy'] = {'prompt':'a contemplative face'}
    catalog_paths['expression'].write_text(json.dumps(document))
    with db.transaction() as conn:
        conn.execute("DELETE FROM schema_meta WHERE key='expression_sets_v1'")
    migrate_catalog_metadata()
    marker_before = db.get_connection().execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()[0]
    assert json.loads(marker_before) == ['demo_legacy']
    es.edit_entry('create','demo_shared',{'prompt':'a curious face','store':'shared'},set_id='humanoid')
    assert db.get_connection().execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()[0] == marker_before
    assert {'demo_shared','demo_legacy'}.issubset(es.catalog_snapshot().sets['humanoid'].members)
    es.edit_entry('rename','demo_legacy',{'new_key':'demo_renamed'},set_id='humanoid')
    assert 'demo_legacy' not in es.catalog_snapshot().entries
    assert 'demo_renamed' in es.catalog_snapshot().sets['humanoid'].members
    assert db.get_connection().execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()[0] == marker_before
    assert second_world('demo_renamed', True) == marker

cases = {'create':create, 'approve':approve, 'delete':delete, 'promote':promote,
         'commit':commit, 'set_delete':set_delete, 'world_only':world_only, 'legacy':legacy}
parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=cases)
args = parser.parse_args()
original = catalog_paths['expression'].read_bytes()
original_marker = db.get_connection().execute("SELECT value FROM schema_meta WHERE key='expression_sets_v1'").fetchone()[0]
for name in ([args.case] if args.case else cases):
    catalog_paths['expression'].write_bytes(original)
    with db.transaction() as conn:
        conn.execute("DELETE FROM pose_catalog_world WHERE axis='expression'")
        conn.execute("DELETE FROM pose_candidates WHERE axis='expression'")
        conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('expression_sets_v1',?)", (original_marker,))
    pc.reload_catalogs()
    cases[name]()
    print('PASS expression layer ' + name)
TMP.cleanup()
