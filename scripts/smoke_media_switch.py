"""Smoke the narrow instance media switch using temporary storage only.

Usage: ./.venv/bin/python scripts/smoke_media_switch.py

Hand-derived expectations from plan-config-save-guard.md Task 5:
A False changes only image_generation.enabled; all sections and secret bytes
  survive and the live predicate is False. Fails on old code ec6e4121:
  case A cannot call the missing set_media_switch function.
B True is the shipped default, so pruning restores the original JSON content.
C Non-bools (including "false", 0, missing and null) are HTTP 400; the core
  setter rejects non-bools too, without writing anything.
D A changes the layer once, so exactly one backup contains its prior bytes.
E Both methods are admin-only under /admin and depend on require_admin;
  smoke_auth_gate.py separately exercises the default-deny middleware.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


with tempfile.TemporaryDirectory(prefix="media-switch-") as root:
    world = Path(root) / "world"
    instance = Path(root) / "instance"
    world.mkdir()
    instance.mkdir()
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin, config_scope
    from app.imagegen.base import media_generation_enabled
    from app.routes import admin_settings as routes
    from app.core.auth_dependency import is_admin_only_path, require_admin
    from fastapi import HTTPException

    seed = {
        "providers": [{"name": "p1"}, {"name": "p2"}],
        "llm_routing": [{"name": "e1", "provider": "p1", "model": "m1"}],
        "image_generation": {
            "backends": [{"name": "b1", "api_type": "openai_diffusion"},
                         {"name": "b2", "api_type": "openai_diffusion"}],
            "routing": {"profile": ["b1"]}},
        "server": {"timezone": "Europe/Berlin"},
    }
    (world / "config.json").write_text('{"game_seasons": [{"name": "warm", "days": 20}]}')
    (instance / "config.json").write_text(json.dumps(seed))
    (instance / "secrets.json").write_text(json.dumps({
        "providers": {"p1": {"api_key": "sk-1"}},
        "image_generation": {"backends": {"b1": {"api_key": "sk-b"}}}}))
    config.load(world / "config.json", instance / "config.json")
    # Normalize loader migrations before measuring the switch's only change.
    config.save_part(config_scope.INSTANCE, config_admin.layer_part(config_scope.INSTANCE))
    assert config.get("providers")[0]["api_key"] == "sk-1"
    assert config.get("image_generation.backends")[0]["api_key"] == "sk-b"
    original = json.loads((instance / "config.json").read_text())
    # The normalizing save itself must not lose any seeded section.
    # A provider keeps the blank api_key placeholder; the value lives in secrets.json.
    assert [p["name"] for p in original["providers"]] == ["p1", "p2"]
    assert original["llm_routing"] == seed["llm_routing"]
    assert original["server"] == seed["server"]
    assert original["image_generation"]["routing"]["profile"] == ["b1"]
    assert [b["name"] for b in original["image_generation"]["backends"]][:2] == ["b1", "b2"]
    before =(instance / "config.json").read_bytes()
    secrets = (instance / "secrets.json").read_bytes()
    world_before = (world / "config.json").read_bytes()
    snapshots = set(config.list_snapshots(instance))
    assert config_admin.set_media_switch(False) is False
    expected = copy.deepcopy(original)
    expected.setdefault("image_generation", {})["enabled"] = False
    assert json.loads((instance / "config.json").read_text()) == expected
    assert (instance / "secrets.json").read_bytes() == secrets
    assert media_generation_enabled() is False
    print("PASS A switch off preserves sections and secrets")
    added = set(config.list_snapshots(instance)) - snapshots
    assert len(added) == 1
    backup = added.pop()
    assert (backup / "config.json").read_bytes() == before
    assert (backup / "secrets.json").read_bytes() == secrets
    print("PASS D exactly one backup before switch off")
    assert config_admin.set_media_switch(True) is True
    assert json.loads((instance / "config.json").read_text()) == original
    assert (instance / "secrets.json").read_bytes() == secrets
    print("PASS B switch on restores original JSON content")
    validation_before = [(p.read_bytes(), p.stat().st_mtime_ns)
                         for p in (instance / "config.json", instance / "secrets.json")]
    validation_snapshots = config.list_snapshots(instance)
    for body in ({"enabled": "false"}, {"enabled": 0}, {}, {"enabled": None}, [], None):
        try:
            routes._media_switch_set(body)
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "enabled must be true or false"
        else:
            raise AssertionError("Expected HTTP 400")
    for value in ("false", 0, None):
        try:
            config_admin.set_media_switch(value)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("Expected non-bool refusal")
    assert json.loads((instance / "config.json").read_text()) == original
    assert [(p.read_bytes(), p.stat().st_mtime_ns)
            for p in (instance / "config.json", instance / "secrets.json")] == validation_before
    assert config.list_snapshots(instance) == validation_snapshots
    assert routes.media_switch_get(user=None) == {"enabled": True}
    assert routes._media_switch_set({"enabled": False}) == {"enabled": False}
    assert routes.media_switch_get(user=None) == {"enabled": False}
    assert routes._media_switch_set({"enabled": True}) == {"enabled": True}
    assert (world / "config.json").read_bytes() == world_before
    print("PASS C strict validation and route responses")
    for route in routes.router.routes:
        if route.path == "/admin/settings/media-switch":
            assert any(dep.call is require_admin for dep in route.dependant.dependencies)
    for method in ("GET", "POST"):
        assert is_admin_only_path("/admin/settings/media-switch", method)
        assert any(r.path == "/admin/settings/media-switch" and method in r.methods
                   for r in routes.router.routes)
    print("PASS E GET and POST require admin")
