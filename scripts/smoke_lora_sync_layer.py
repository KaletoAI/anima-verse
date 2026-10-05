"""Regression: discovery saves world chat.top_p=0.9 before returning one LoRA.
Hand-derived expectation: sync preserves that world override and writes the
new discovered entry only to the instance, with added=1 and scanned=[fake].
Temporary paths are initialized before any world-DB imports.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="lora-sync-layer-") as tmp:
    root = Path(tmp)
    world = root / "world"
    instance = root / "instance"
    world.mkdir()
    instance.mkdir()
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin, lora_library
    from app.imagegen import service
    for folder in (world, instance):
        (folder / "config.json").write_text("{}")
    config.load(world / "config.json", instance / "config.json")
    class Backend:
        name = "fake"
        instance_enabled = True
        lora_url = "fake://loras"
        def fetch_loras(self):
            config_admin.save_layer("world", {"chat": {"top_p": 0.9}})
            return ["new-lora"]
    class Service:
        enabled = True
        backends = [Backend()]
    previous = service.get_image_service
    service.get_image_service = lambda: Service()
    try:
        result = lora_library.sync_lora_library()
    finally:
        service.get_image_service = previous
    assert json.loads((world / "config.json").read_text())["chat"]["top_p"] == 0.9
    assert json.loads((instance / "config.json").read_text())["image_generation"]["lora_triggers"] == [
        {"lora": "new-lora", "word": "", "source": "discovered",
         "backends": ["fake"], "missing_on": []}]
    assert result == {"changed": True, "added": 1, "removed": 0, "missing": 0, "scanned": ["fake"]}
    print("PASS: concurrent world save preserved; instance LoRA persisted")
