#!/usr/bin/env python3
"""Temporary-NPC fallback: automatic variants stay off, but a completed
set-local default stays visible. A different worn outfit must not reuse it.
Usage: ./.venv/bin/python scripts/smoke_expression_fallback.py
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

from unittest.mock import patch
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes.characters import router
from app.models.character import save_character_profile,get_character_profile
from app.models.character_template import is_feature_enabled
from app.core.keyed_lock import keyed_lock
from app.core import expression_regen as er
assert save_character_profile('demo',{'template':'npc-temporary','outfit_description':'a linen apron','character_appearance':'a person'},create_new=True)
request = er.expression_snapshot('demo')
assert not is_feature_enabled('demo','expression_variants_enabled')
assert er.trigger_expression_generation(request,ignore_cooldown=True,coalesce=False) is False
assert er.expression_status(request)['state'] == 'missing'
def render(character,*,output_stem,**kwargs):
    image = output_stem.with_suffix('.png')
    Image.new('RGB',(8,8),(10,20,30)).save(image)
    image.with_suffix('.json').write_text(json.dumps({'prompt':kwargs['expression_prompt'],'equipped_pieces':{},'equipped_items':[]}))
    return image
with patch.object(er,'render_character_image',render):
    image = er.generate_expression_image(request)
app = FastAPI()
app.include_router(router)
client = TestClient(app)
assert client.get('/characters/demo/outfit-expression?mood=angry').status_code == 404
fallback = client.get('/characters/demo/outfit-expression?mood=angry&fallback=default')
assert fallback.status_code == 200 and fallback.content == image.read_bytes()
assert er.expression_status(request)['state'] == 'ready'
with keyed_lock('character_profile','demo'):
    profile = get_character_profile('demo')
    profile['outfit_description'] = 'a brown cloak'
    assert save_character_profile('demo',profile)
assert client.get('/characters/demo/outfit-expression?fallback=default').status_code == 404
assert image.exists(), 'Changing outfit should not automatically delete history'
print('PASS closed variant gate, compatible default fallback and exact free-text outfit boundary')
client.close()
TMP.cleanup()
