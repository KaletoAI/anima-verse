#!/usr/bin/env python3
"""Person-reference selection uses current set/exact outfit before the existing
profile-only identity fallback. A near outfit or legacy state image is not a
compatible expression reference. Uses actual cache files and PromptBuilder.
Usage: ./.venv/bin/python scripts/smoke_expression_same_outfit.py
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
from app.models.character import save_character_profile,get_character_images_dir
from app.models.inventory import add_item
from app.core import expression_regen as er, prompt_builder as pb
from app.models import inventory
assert save_character_profile('demo',{'template':'human-default','character_appearance':'a person'},create_new=True)
coat = add_item('Demo coat',category='outfit_piece',prompt_fragment='a linen coat',outfit_piece={'slots':['top']})
shirt = add_item('Demo shirt',category='outfit_piece',prompt_fragment='a cotton shirt',outfit_piece={'slots':['top']})
A,B = {'top':coat['id']},{'top':shirt['id']}
def render(character,*,output_stem,**kwargs):
    image = output_stem.with_suffix('.png')
    Image.new('RGB',(8,8),(20,40,60)).save(image)
    image.with_suffix('.json').write_text(json.dumps({'prompt':kwargs['expression_prompt'],'equipped_pieces':kwargs['equipped_pieces'],'equipped_items':kwargs['equipped_items']}))
    return image
with patch.object(er,'render_character_image',render):
    image = er.generate_expression_image(er.expression_snapshot('demo','neutral',equipped_pieces=A,equipped_items=[]))
images = get_character_images_dir('demo')
portrait = images/'profile.png'
Image.new('RGB',(8,8),(100,0,0)).save(portrait)
person = pb.Person(name='demo',appearance='',gender='')
with patch.object(pb,'get_character_profile_image',return_value='profile.png'), patch.object(pb,'get_character_current_feeling',return_value='angry'), patch.object(inventory,'get_equipped_items',return_value=[]):
    with patch.object(inventory,'get_equipped_pieces',return_value=A):
        assert pb.PromptBuilder('demo')._resolve_person_ref_image(person) == str(image)
    with patch.object(inventory,'get_equipped_pieces',return_value=B):
        assert pb.PromptBuilder('demo')._resolve_person_ref_image(person) == str(portrait), 'A different outfit leaked as an expression reference'
    with patch.object(inventory,'get_equipped_pieces',side_effect=RuntimeError('inventory unreadable')):
        assert pb.PromptBuilder('demo')._resolve_person_ref_image(person) == str(portrait)
print('PASS exact-outfit expression reference and independent profile-only identity fallback')
TMP.cleanup()
