#!/usr/bin/env python3
"""Expression maintenance: keep/adopt/remove/manual-review are derived from the
approved schema-2 contract. A stale revision must mutate zero files; a partial
I/O error must report completed operations. All files and archives are temporary.
Usage: ./.venv/bin/python scripts/smoke_expression_cleanup.py
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

import io
import zipfile
import threading
from unittest.mock import patch
from PIL import Image
from app.models.character import save_character_profile, get_character_profile, delete_character
from app.models.inventory import add_item
from app.core import expression_regen as er
from app.core.expression_cleanup import preview_cleanup, apply_cleanup, inventory, CleanupError
from app.core.character_io import export_character_to_zip, import_character_from_zip
from app.core.keyed_lock import keyed_lock
from app.core.expression_sets import catalog_snapshot
assert save_character_profile('demo', {'template':'animal-default','species':'cat','character_appearance':'a brown cat'}, create_new=True)
coat = add_item(name='Demo coat',category='outfit_piece',prompt_fragment='a linen coat',outfit_piece={'slots':['top']})
entered, release = threading.Event(), threading.Event()
blocking = False
provider_failure = False
def render(character, *, output_stem, **kwargs):
    if blocking:
        entered.set()
        assert release.wait(10)
        if provider_failure:
            raise RuntimeError('provider finished with failure after invalidation')
    p = output_stem.with_suffix('.png')
    Image.new('RGB',(8,8),(40,80,120)).save(p)
    p.with_suffix('.json').write_text(json.dumps({'prompt':kwargs['expression_prompt'],'equipped_pieces':kwargs['equipped_pieces'],'equipped_items':kwargs['equipped_items']}))
    return p

def fingerprint(folder):
    return {p.name:(p.lstat().st_ino,p.lstat().st_mtime_ns,os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None) for p in folder.iterdir()}

with patch.object(er,'render_character_image',render):
    bare = er.generate_expression_image(er.expression_snapshot('demo','neutral'))
    dressed = er.generate_expression_image(er.expression_snapshot('demo','neutral',equipped_pieces={'top':coat['id']},equipped_items=[]))
    assert bare != dressed, 'Visible outfits must remain separate coordinates'
    relaxed = er.generate_expression_image(er.expression_snapshot('demo','animal_relaxed'))
    folder = er._get_expressions_dir('demo')
    adoption = folder/'demo_adopt.png'
    relaxed.rename(adoption)
    relaxed.with_suffix('.json').rename(adoption.with_suffix('.json'))
    archive = export_character_to_zip('demo')
    duplicate = folder/'demo_duplicate.png'
    shutil.copy2(bare,duplicate)
    shutil.copy2(bare.with_suffix('.json'),duplicate.with_suffix('.json'))
    legacy = folder/'demo_legacy.png'
    shutil.copy2(bare,legacy)
    legacy.with_suffix('.json').write_text(json.dumps({'expression_key':'neutral','pose_key':'sitting','equipped_pieces':{},'equipped_items':[]}))
    unknown = folder/'demo_unknown.png'
    shutil.copy2(bare,unknown)
    (folder/'malformed.json').write_text('{broken')
    outside = STORAGE/'outside.png'
    shutil.copy2(bare,outside)
    link = folder/'demo_external.png'
    link.symlink_to(outside)
    # Missing identity/contract proof and mismatching bytes are never deletion proof.
    complete = json.loads(bare.with_suffix('.json').read_text())
    incomplete_files = []
    for index, missing in enumerate(('expression_set', 'expression_key', 'contract', 'neutral_state', 'content_version')):
        metadata = dict(complete)
        metadata.pop(missing)
        image = folder / f'demo_incomplete_{index}.png'
        shutil.copy2(bare, image)
        image.with_suffix('.json').write_text(json.dumps(metadata))
        incomplete_files.append(image)
    mismatched = folder / 'demo_unproven_anatomy.png'
    shutil.copy2(bare, mismatched)
    mismatched.with_suffix('.json').write_text(json.dumps({
        **complete, 'expression_set': 'humanoid', 'expression_key': 'neutral',
        'content_version': 'not-the-image-content-version'}))
    incomplete_files.append(mismatched)
    before = fingerprint(folder)
    preview = preview_cleanup('demo')
    assert fingerprint(folder) == before, 'Preview wrote to the asset directory'
    actions = {row['file']:row['action'] for row in preview['files']}
    assert actions[bare.name] == actions[dressed.name] == 'keep'
    assert actions[adoption.name] == 'adopt'
    assert actions[legacy.name] == actions[duplicate.name] == 'remove'
    assert actions[unknown.name] == actions[link.name] == actions['malformed.json'] == 'review'
    assert all(actions[p.name] == 'review' for p in incomplete_files), 'Incomplete or unbound metadata was marked for deletion'
    # Reject path escapes and directory symlinks without touching their targets.
    external_directory = STORAGE / 'external-directory'
    external_directory.mkdir()
    sentinel = external_directory / 'keep.txt'
    sentinel.write_text('outside expression ownership')
    assert save_character_profile('demo-link', {'template':'animal-default'}, create_new=True)
    linked_character = folder.parent.parent / 'demo-link'
    preserved_character = STORAGE / 'preserved-linked-character'
    linked_character.rename(preserved_character)
    linked_character.symlink_to(external_directory, target_is_directory=True)
    assert save_character_profile('demo-linked-outfits', {'template':'animal-default'}, create_new=True)
    linked_outfits = folder.parent.parent / 'demo-linked-outfits'
    (linked_outfits / 'outfits').symlink_to(external_directory, target_is_directory=True)
    for unsafe_name, expected_status in (('../demo', 404), ('demo-link', 400), ('demo-linked-outfits', 400)):
        try:
            preview_cleanup(unsafe_name)
            raise AssertionError('Unsafe expression directory was accepted')
        except CleanupError as exc:
            assert exc.status == expected_status
    assert sentinel.read_text() == 'outside expression ownership'
    linked_character.unlink()
    preserved_character.rename(linked_character)
    (linked_outfits / 'outfits').unlink()
    # A preexisting adoption target is never overwritten, even in a fresh plan.
    relaxed.mkdir()
    collision_preview = preview_cleanup('demo')
    collision_before = fingerprint(folder)
    try:
        apply_cleanup('demo', collision_preview['revision'])
        raise AssertionError('Adoption collision was accepted')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == collision_before
    relaxed.rmdir()
    # Catalog and explicit selection changes each stale an otherwise unchanged inventory.
    from app.core import expression_sets as sets
    catalog_preview = preview_cleanup('demo')
    animal_set = catalog_snapshot().sets['animal']
    sets.replace_set('animal', {'label':'Demo animal','default':animal_set.default,
        'pose_prompt':animal_set.pose_prompt,'members':list(animal_set.members)}, store='world')
    unchanged_files = fingerprint(folder)
    try:
        apply_cleanup('demo', catalog_preview['revision'])
        raise AssertionError('Changed catalog did not stale cleanup')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == unchanged_files
    sets.delete_set('animal', store='world')
    selection_preview = preview_cleanup('demo')
    profile = get_character_profile('demo')
    profile['expression_set'] = 'humanoid'
    assert save_character_profile('demo', profile)
    try:
        apply_cleanup('demo', selection_preview['revision'])
        raise AssertionError('Changed set selection did not stale cleanup')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == unchanged_files
    profile = get_character_profile('demo')
    profile['expression_set'] = ''
    assert save_character_profile('demo', profile)
    deletion_preview = preview_cleanup('demo')
    assert er.delete_expression('demo', unknown.name)
    after_delete = fingerprint(folder)
    try:
        apply_cleanup('demo', deletion_preview['revision'])
        raise AssertionError('Individual deletion did not stale cleanup')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == after_delete
    shutil.copy2(bare, unknown)
    (folder/'new.txt').write_text('changed')
    changed = fingerprint(folder)
    try:
        apply_cleanup('demo',preview['revision'])
        raise AssertionError('Stale cleanup must be rejected')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == changed
    (folder/'new.txt').unlink()
    current = preview_cleanup('demo')
    original_unlink = Path.unlink
    def failing_unlink(path,*args,**kwargs):
        if path == legacy:
            raise OSError('simulated filesystem refusal')
        return original_unlink(path,*args,**kwargs)
    with patch.object(Path,'unlink',failing_unlink):
        try:
            apply_cleanup('demo',current['revision'])
            raise AssertionError('I/O failure must not report success')
        except CleanupError as exc:
            assert exc.status == 500 and exc.completed['adopted'] == 1
    assert legacy.exists() and unknown.exists() and link.is_symlink()
    fresh = preview_cleanup('demo')
    result = apply_cleanup('demo',fresh['revision'])
    assert result['removed'] == 1 and not legacy.exists()
    assert dressed.exists() and unknown.exists() and link.is_symlink()
    assert all(p.exists() and p.with_suffix('.json').exists() for p in incomplete_files)
    assert len([row for row in inventory('demo') if row['status']=='current']) == 3
    # Invalid imported selection must fail before touching the old character.
    bad_buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as old, zipfile.ZipFile(bad_buffer,'w') as new:
        for item in old.infolist():
            data = old.read(item.filename)
            if item.filename == 'db/characters.json':
                rows = json.loads(data)
                profile = json.loads(rows[0]['profile_json'])
                profile['expression_set'] = 'missing-set'
                rows[0]['profile_json'] = json.dumps(profile)
                data = json.dumps(rows).encode()
            new.writestr(item,data)
    before = fingerprint(folder)
    try:
        import_character_from_zip(bad_buffer.getvalue(),overwrite=True)
        raise AssertionError('Invalid imported set must be refused')
    except ValueError:
        assert fingerprint(folder) == before
    stale = preview_cleanup('demo')
    assert import_character_from_zip(archive,overwrite=True)['status'] == 'success'
    after_import = fingerprint(folder)
    try:
        apply_cleanup('demo',stale['revision'])
        raise AssertionError('Overwrite import must invalidate cleanup')
    except CleanupError as exc:
        assert exc.status == 409 and fingerprint(folder) == after_import
    # A set deletion must observe a selection committed by a concurrent import.
    from app.core import character_io as cio
    sets.replace_set('demo_set', {
        'label': 'Demo set', 'default': 'demo_neutral', 'pose_prompt': 'standing neutrally',
        'members': ['demo_neutral'],
        'entries': {'demo_neutral': {'label': 'Neutral', 'prompt': 'a neutral expression', 'synonyms': ['neutral']}},
    }, store='world')
    profile = get_character_profile('demo')
    profile['expression_set'] = 'demo_set'
    assert save_character_profile('demo', profile)
    selected_archive = export_character_to_zip('demo')
    profile = get_character_profile('demo')
    profile['expression_set'] = ''
    assert save_character_profile('demo', profile)
    restoring, resume, deleting, deleted = [threading.Event() for _ in range(4)]
    outcomes = {}
    original_restore = cio._restore_table
    def paused_restore(conn, table, rows):
        if table == 'characters':
            restoring.set()
            assert resume.wait(10)
        return original_restore(conn, table, rows)
    def import_selected():
        try:
            outcomes['import'] = import_character_from_zip(selected_archive, overwrite=True)
        except Exception as exc:
            outcomes['import_error'] = exc
    def delete_selected_set():
        deleting.set()
        try:
            sets.delete_set('demo_set', store='world')
            outcomes['deleted'] = True
        except sets.ExpressionSetError as exc:
            outcomes['delete_error'] = exc
        finally:
            deleted.set()
    importer = threading.Thread(target=import_selected)
    deleter = threading.Thread(target=delete_selected_set)
    with patch.object(cio, '_restore_table', paused_restore):
        importer.start()
        assert restoring.wait(5)
        deleter.start()
        try:
            assert deleting.wait(5)
            assert not deleted.wait(0.05), 'Set deletion passed an in-flight import'
        finally:
            resume.set()
            importer.join(10)
            deleter.join(10)
    assert not importer.is_alive() and not deleter.is_alive()
    assert outcomes.get('import', {}).get('status') == 'success', outcomes
    assert outcomes['delete_error'].status == 409 and not outcomes.get('deleted'), outcomes
    assert get_character_profile('demo')['expression_set'] == 'demo_set'
    assert 'demo_set' in catalog_snapshot().sets
    # Incoming remote work cannot resurrect a cleared coordinate.
    er.clear_expression_cache('demo')
    blocking = True
    request = er.expression_snapshot('demo','neutral')
    attempt = er.start_expression_attempt(request,force=True)
    assert entered.wait(5)
    er.clear_expression_cache('demo')
    release.set()
    with er.render_lock('demo'):
        pass
    assert er.get_expression_attempt('demo',attempt.attempt_id).state == 'invalidated'
    assert not list(folder.glob('*.png'))
    # A late provider error cannot overwrite a terminal deletion outcome.
    entered.clear(); release.clear(); provider_failure = True
    attempt = er.start_expression_attempt(er.expression_snapshot('demo','neutral'),force=True)
    assert entered.wait(5)
    assert delete_character('demo')
    release.set()
    with er.render_lock('demo'):
        pass
    assert er.get_expression_attempt('demo',attempt.attempt_id).state == 'invalidated', 'Late failure overwrote invalidation outcome'
    assert not folder.parent.exists(), 'Deleted character was recreated'
    # Reusing a deleted name cannot accept an older character's in-flight image.
    assert save_character_profile('demo', {'template':'animal-default',
        'character_appearance':'the original cat'}, create_new=True)
    entered.clear(); release.clear(); provider_failure = False
    prior = er.expression_snapshot('demo')
    attempt = er.start_expression_attempt(prior, force=True)
    assert entered.wait(5)
    assert delete_character('demo')
    assert save_character_profile('demo', {'template':'animal-default',
        'character_appearance':'the replacement cat'}, create_new=True)
    replacement = er.expression_snapshot('demo')
    assert replacement.stem == prior.stem and replacement.epoch != prior.epoch
    release.set()
    with er.render_lock('demo'):
        pass
    assert er.get_expression_attempt('demo', attempt.attempt_id).state == 'invalidated'
    assert get_character_profile('demo')['character_appearance'] == 'the replacement cat'
    assert folder.parent.exists() and not list(folder.glob('*.png'))
print('PASS read-only preview, conservative cleanup/adoption, stale/partial errors, import and invalidation races')
TMP.cleanup()
