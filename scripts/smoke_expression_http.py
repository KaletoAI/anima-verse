#!/usr/bin/env python3
"""Real HTTP/session expression smoke in a temporary world.
Expected by the approved plan: 401 anonymous, 403 non-owner/maintenance player;
compatible images survive media-off; Force status follows its frozen attempt
across set/mood changes and completes even when image bytes are unchanged.
Usage: ./.venv/bin/python scripts/smoke_expression_http.py
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

import asyncio
import threading
import time
from unittest.mock import patch
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core import auth_dependency as auth, users, sessions
from app.routes.characters import router as character_router
from app.routes.poses import router as poses_router
from app.models.character import save_character_profile, get_character_profile
from app.core.keyed_lock import keyed_lock
from app.core import expression_regen as er
from app.core.http_files import content_version
app = FastAPI()
app.middleware('http')(auth.auth_gate_middleware)
@app.middleware('http')
async def user_context(request, call_next):
    token = auth.current_user_ctx.set(auth._get_session_user(request))
    try:
        return await call_next(request)
    finally:
        auth.current_user_ctx.reset(token)
app.include_router(character_router)
app.include_router(poses_router)
assert save_character_profile('demo', {'template':'animal-default','species':'cat','character_appearance':'a brown cat'}, create_new=True)
uid = users.create_user('demo', 'temporary-demo-password', role='admin', allowed_characters=['demo'])
client = TestClient(app)
assert client.get('/characters/demo/outfit-expression?override=1').status_code == 401
client.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(uid))
entered, release = threading.Event(), threading.Event()
blocked = False
render_failure = False
def render(character, *, output_stem, **kwargs):
    if render_failure:
        raise RuntimeError('deterministic expression provider failure')
    if blocked:
        entered.set()
        assert release.wait(10), 'Force fixture was not released'
    p = output_stem.with_suffix('.png')
    Image.new('RGB',(8,8),(25,50,75)).save(p)
    p.with_suffix('.json').write_text(json.dumps({'prompt':kwargs['expression_prompt'],'equipped_pieces':kwargs['equipped_pieces'],'equipped_items':kwargs['equipped_items']}))
    return p

def select(sid, mood='neutral'):
    with keyed_lock('character_profile','demo'):
        profile = get_character_profile('demo')
        profile.update(expression_set=sid,current_feeling=mood)
        assert save_character_profile('demo',profile)

with patch.object(er,'render_character_image',render):
    animal = er.expression_snapshot('demo','neutral')
    animal_file = er.generate_expression_image(animal)
    old_version = content_version(animal_file)
    select('humanoid','happy')
    human_file = er.generate_expression_image(er.expression_snapshot('demo','happy'))
    assert human_file
    select('animal','neutral')
    blocked = True
    response = client.post('/characters/demo/expression-generation', json={'mood':'neutral','override':True,'force':True})
    assert response.status_code in (200,202), response.text
    attempt = response.json()
    assert entered.wait(5)
    select('humanoid','happy')
    current = client.get('/characters/demo/expression-status').json()
    frozen = client.get('/characters/demo/expression-status',params={'attempt_id':attempt['attempt_id']}).json()
    assert current['state'] == 'ready' and current['identity'] != frozen['identity']
    assert frozen['state'] == 'running' and frozen['identity'] == attempt['identity']
    assert client.get('/characters/demo/expression-status',params={'attempt_id':attempt['attempt_id'],'mood':'happy'}).status_code == 400
    release.set()
    for _ in range(100):
        frozen = client.get('/characters/demo/expression-status',params={'attempt_id':attempt['attempt_id']}).json()
        if frozen['state'] not in ('pending','running'):
            break
        time.sleep(0.01)
    assert frozen['state'] == 'ready', frozen
    assert frozen['content_version'] == old_version, 'Same-byte Force is still a successful completed attempt'
    assert client.get('/characters/demo/expression-status?attempt_id=expr_missing').status_code == 404
    # Ordinary image reads cannot restart a failed identity; explicit POST can.
    select('animal')
    blocked = False
    render_failure = True
    failed_post = client.post('/characters/demo/expression-generation', json={'mood':'animal_defensive','force':True})
    failed_id = failed_post.json()['attempt_id']
    for _ in range(100):
        failed = client.get('/characters/demo/expression-status', params={'attempt_id':failed_id}).json()
        if failed['state'] not in ('pending','running'):
            break
        time.sleep(0.01)
    assert failed['state'] == 'failed', failed
    attempt_ids = set(er._attempts)
    with patch.object(er, '_COALESCE_WINDOW', 0):
        for _ in range(3):
            client.get('/characters/demo/outfit-expression?mood=animal_defensive&fallback=default')
    assert set(er._attempts) == attempt_ids, 'Ordinary GET created a new job after a failed identity'
    render_failure = False
    retry = client.post('/characters/demo/expression-generation', json={'mood':'animal_defensive','force':True}).json()
    assert retry['attempt_id'] != failed_id
    for _ in range(100):
        retried = client.get('/characters/demo/expression-status', params={'attempt_id':retry['attempt_id']}).json()
        if retried['state'] not in ('pending','running'):
            break
        time.sleep(0.01)
    assert retried['state'] == 'ready', retried
    # A new, never-failed coordinate must warm even during another job's cooldown.
    er._last_expression_time['demo'] = time.monotonic()
    with patch.object(er, '_COALESCE_WINDOW', 0):
        fresh = client.get('/characters/demo/outfit-expression?mood=animal_attentive')
    assert fresh.status_code in (200, 202), 'A fresh GET miss was stranded by cooldown'
    for _ in range(100):
        warmed = client.get('/characters/demo/expression-status', params={'mood':'animal_attentive'}).json()
        if warmed['state'] == 'ready':
            break
        time.sleep(0.01)
    assert warmed['state'] == 'ready', warmed
    select('humanoid', 'happy')
    instance = STORAGE/'instance'/'config.json'
    instance.parent.mkdir(exist_ok=True)
    instance.write_text(json.dumps({'image_generation':{'enabled':False}}))
    config.load(STORAGE/'config.json',instance)
    response = client.get('/characters/demo/outfit-expression?mood=angry&fallback=default')
    assert response.status_code == 200, response.text
    assert response.content == animal_file.read_bytes()
    assert client.get('/characters/demo/outfit-expression?mood=angry&fallback=default',headers={'If-None-Match':response.headers['etag']}).status_code == 304
    assert client.post('/characters/demo/expression-generation',json={'force':True}).status_code == 409
    assert users.update_user(uid,role='user')
    assert client.get('/characters/demo/expression-options').status_code == 200
    assert client.get('/characters/demo/expressions').status_code == 403
    assert client.get('/characters/demo/expression-cleanup').status_code == 403
    assert client.post('/characters/demo/expression-cleanup',json={'revision':'bad'}).status_code == 403
    assert users.update_user(uid,allowed_characters=[])
    assert client.post('/characters/demo/expression-generation',json={'force':True}).status_code == 403
    assert client.get('/characters/demo/expression-options').status_code == 403
    assert client.get('/characters/demo/outfit-expression?mood=happy&fallback=default').status_code == 200
    assert users.update_user(uid,role='admin')
    preview = client.get('/characters/demo/expression-cleanup')
    assert preview.status_code == 200, preview.text
    assert client.post('/characters/demo/expression-cleanup',json={'revision':'stale'}).status_code == 409
    assert er.delete_expression('demo',human_file.name)
    assert client.get('/characters/demo/outfit-expression?mood=happy&fallback=default').status_code == 404, 'Historical animal image leaked into humanoid fallback'
print('PASS real HTTP auth, set-local fallback, ETag, disabled generation and frozen same-byte Force attempts')
client.close()
TMP.cleanup()
