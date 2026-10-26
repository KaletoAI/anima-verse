#!/usr/bin/env python3
"""Expression contract regression: four animal members, stable outfit identity,
cache reuse across state/activity changes, atomic force and concurrent producers.
Expected bounds come from design-expression-sets.md: 4 animal members per outfit,
no additional coordinate for state or pose. Uses a local valid-PNG render boundary.
Usage: ./.venv/bin/python scripts/smoke_expression_render_contract.py [--publication]
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

from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch
from PIL import Image
from app.models.character import save_character_profile, get_character_profile
from app.core import expression_regen as er
from app.core.http_files import content_version
from app.core.keyed_lock import keyed_lock
from app.core.expression_sets import catalog_snapshot
assert save_character_profile("demo", {"template": "animal-default", "species": "cat", "character_appearance": "a small brown cat"}, create_new=True)
sequence = 0
sequence_lock = threading.Lock()
def render(character, *, output_stem, **kwargs):
    global sequence
    with sequence_lock:
        sequence += 1
        colour = sequence
    image = output_stem.with_suffix(".png")
    Image.new("RGB", (8, 8), (colour, 0, 0)).save(image)
    image.with_suffix(".json").write_text(json.dumps({"prompt": kwargs["expression_prompt"], "equipped_pieces": kwargs["equipped_pieces"], "equipped_items": kwargs["equipped_items"]}))
    return image
with patch.object(er, "render_character_image", render):
    initial = er.expression_snapshot("demo", "neutral")
    assert initial.set_id == "animal"
    first = er.generate_expression_image(initial)
    before = (first.read_bytes(), first.stat().st_mtime_ns)
    with keyed_lock("character_profile", "demo"):
        profile = get_character_profile("demo")
        profile.update(pose_key="sitting", current_feeling="calm", is_wet=True)
        assert save_character_profile("demo", profile)
    after_state = er.expression_snapshot("demo", "calm")
    assert after_state.stem == initial.stem, "Activity/state/synonyms must not multiply images"
    assert er.generate_expression_image(after_state) == first
    assert (first.read_bytes(), first.stat().st_mtime_ns) == before, "Completed image was rendered again"
    members = catalog_snapshot().sets["animal"].members
    for key in members:
        assert er.generate_expression_image(er.expression_snapshot("demo", key)) is not None
    images = list(er._get_expressions_dir("demo").glob("*.png"))
    assert len(images) == 4, "Exactly four set coordinates for an unchanged empty outfit"
    base_version = content_version(first)
    with patch.object(er, "render_character_image", side_effect=RuntimeError("local render failure")):
        assert er.generate_expression_image(after_state, force=True) is None
    assert content_version(first) == base_version, "Failed force destroyed the last good image"
    assert er.get_cached_expression(after_state) == first
    forced = er.generate_expression_image(after_state, force=True)
    assert forced == first and content_version(first) != base_version
    er.clear_expression_cache("demo")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: er.generate_expression_image(er.expression_snapshot("demo", "neutral")), range(2)))
    assert results[0] == results[1] and results[0] is not None
    assert len(list(er._get_expressions_dir("demo").glob("*.png"))) == 1
    assert er.expression_status(er.expression_snapshot("demo", "neutral"))["state"] == "ready"
from app.models.inventory import add_item
from app.core import embedding
coat = add_item("Demo coat", category="outfit_piece", prompt_fragment="a linen coat", outfit_piece={"slots": ["top"]})
changed = False
def change_outfit_during_match(text):
    global changed
    if not changed:
        changed = True
        with keyed_lock("character_profile", "demo"):
            current = get_character_profile("demo")
            current["equipped_pieces"] = {"top": coat["id"]}
            assert save_character_profile("demo", current)
    return None
with patch.object(embedding, "embed", side_effect=change_outfit_during_match):
    raced = er.expression_snapshot("demo", "a previously unseen expression")
latest = er.expression_snapshot("demo")
assert raced.outfit_raw == latest.outfit_raw and raced.pieces == latest.pieces, "Outfit changed during matching but snapshot was not retried"
import sqlite3
from app.models import character as character_model
profile = get_character_profile("demo")
closed = sqlite3.connect(":memory:")
closed.close()
with patch.object(character_model, "get_connection", return_value=closed):
    assert save_character_profile("demo", profile) is False, "Profile persistence failure must remain a bool result"
print("PASS expression identity, four-member bound, completed reuse, force preservation and concurrent publication")
TMP.cleanup()
