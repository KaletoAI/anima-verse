"""Smoke the Task 3 config save drop guard, using temporary layers only.

Usage: ./.venv/bin/python scripts/smoke_config_drop_guard.py

Hand-derived expectations from plan-config-save-guard.md, Task 3:
A The partial image toggle omits providers, llm_routing and server, and
  omits the nested backends object list: exactly those four sorted paths
  are refused, without changing bytes. Fails on old code eb12ea08: case A
  prepare_layer accepts the destructive candidate without raising.
B A full view changes only enabled and retains every stored section.
C Removing p2, b2 and the profile string chain leaves nonempty object lists,
  so it saves p1 and custom b1, plus the loader-seeded quadruped-local
  backend, and no profile without a refusal.
D Empty providers is one dropped path; explicit confirmation stores [],
  while a reset restores _DEFAULT_PROVIDERS.
E Two custom world seasons -> [] is one dropped path; confirmation saves [].
F A stale view predating catalogs c1 drops content_marketplace (and its
  catalogs object list), and the refusal advises Reload the page.
G Both route adapters return 409 with code would_drop for partial bodies.
H A string confirm_drop is HTTP 400 on both routes; null, objects and
  non-string elements are invalid too, including falsey values.
Additional boundary checks: exemptions match complete path segments; only
nonempty all-dict lists reached through dictionaries count. String lists,
empty lists and lists within list entries do not count. Missing false/zero
scalars remain stored settings; only empty containers/strings/null are empty.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return copy.deepcopy(self.body)


with tempfile.TemporaryDirectory(prefix="config-drop-guard-") as root:
    world = Path(root) / "world"
    instance = Path(root) / "instance"
    world.mkdir()
    instance.mkdir()
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin as adm
    from app.routes import admin_settings, world_settings
    from fastapi import HTTPException, Response

    adm.apply_section_reloads = lambda keys, scope: []
    seed = {
        "providers": [{"name": "p1"}, {"name": "p2"}],
        "llm_routing": [{"name": "e1", "provider": "p1", "model": "m1"}],
        "image_generation": {
            "backends": [{"name": "b1", "api_type": "openai_diffusion"},
                         {"name": "b2", "api_type": "openai_diffusion"}],
            "routing": {"profile": ["b1"]}},
        "server": {"timezone": "Europe/Berlin"},
    }
    seasons = [{"name": "warm", "days": 20}, {"name": "cold", "days": 30}]

    def load(inst=None, w=None):
        (instance / "config.json").write_text(json.dumps(seed if inst is None else inst))
        (world / "config.json").write_text(json.dumps({"game_seasons": seasons} if w is None else w))
        config.load(world / "config.json", instance / "config.json")

    def snapshot():
        return [(p.read_bytes(), p.stat().st_mtime_ns)
                for p in (instance / "config.json", world / "config.json")]

    def refused(fn, expected):
        before = snapshot()
        try:
            fn()
        except adm.LayerDropRefused as exc:
            assert exc.paths == expected, exc.paths
            assert str(exc) == (
                f"save would remove {len(expected)} stored setting(s): {expected}. "
                "Reload the page if it is stale, or confirm the removal.")
        else:
            raise AssertionError("Expected LayerDropRefused")
        assert snapshot() == before

    def http_refused(fn, status):
        before = snapshot()
        try:
            fn()
        except HTTPException as exc:
            assert exc.status_code == status, (exc.status_code, exc.detail)
            if status == 409:
                assert exc.detail["code"] == "would_drop"
                assert exc.detail["paths"]
                assert "Reload the page" in exc.detail["message"]
        else:
            raise AssertionError("Expected HTTP refusal")
        assert snapshot() == before

    load()
    refused(lambda: adm.prepare_layer("instance", {"image_generation": {"enabled": False}}),
            ["image_generation.backends", "llm_routing", "providers", "server"])
    print("PASS A partial toggle refused; bytes unchanged")

    view = adm.layer_view("instance")
    view["image_generation"]["enabled"] = False
    adm.save_layer("instance", view)
    assert all(key in adm.layer_part("instance") for key in seed)
    assert config.get("image_generation.enabled") is False
    print("PASS B full view preserves sections")

    load()
    view = adm.layer_view("instance")
    view["providers"] = [p for p in view["providers"] if p["name"] != "p2"]
    view["image_generation"]["backends"] = [b for b in view["image_generation"]["backends"]
                                               if b["name"] != "b2"]
    del view["image_generation"]["routing"]["profile"]
    adm.save_layer("instance", view)
    stored = json.loads((instance / "config.json").read_text())
    assert [p["name"] for p in stored["providers"]] == ["p1"]
    assert [b["name"] for b in stored["image_generation"]["backends"]] == ["b1", "quadruped-local"]
    assert "profile" not in stored.get("image_generation", {}).get("routing", {})
    print("PASS C individual entries and occasion removable")

    load()
    view = adm.layer_view("instance")
    view["providers"] = []
    refused(lambda: adm.save_layer("instance", view), ["providers"])
    adm.save_layer("instance", view, confirm_drop=["providers"])
    assert json.loads((instance / "config.json").read_text())["providers"] == []
    load()
    adm.save_layer("instance", view, resets=["providers"])
    assert adm.layer_part("instance")["providers"] == config._DEFAULT_PROVIDERS
    print("PASS D providers clear confirmed or reset")

    load()
    view = adm.layer_view("world")
    view["game_seasons"] = []
    refused(lambda: adm.save_layer("world", view), ["game_seasons"])
    adm.save_layer("world", view, confirm_drop=["game_seasons"])
    assert json.loads((world / "config.json").read_text())["game_seasons"] == []
    print("PASS E world list clear confirmed")

    load()
    stale = adm.layer_view("instance")
    stale.pop("content_marketplace", None)
    newer = copy.deepcopy(seed)
    newer["content_marketplace"] = {"catalogs": [{"name": "c1", "url": "https://example.invalid"}]}
    load(newer)
    refused(lambda: adm.prepare_layer("instance", stale),
            ["content_marketplace", "content_marketplace.catalogs"])
    print("PASS F stale tab advised to reload")

    def revision():
        response = Response()
        admin_settings.settings_raw(response, user=None)
        return response.headers["X-Config-Revision"]

    load()
    http_refused(lambda: admin_settings._settings_save_sync(
        {"image_generation": {"enabled": False}}, [], [], revision()), 409)
    http_refused(lambda: world_settings._put_sync({"values": {}, "resets": [], "base_revision": world_settings.get_world_settings()["revision"]}), 409)
    print("PASS G both routes map would_drop to 409")

    for invalid in ("providers", None, {}, [1], False, 0, ("providers",)):
        body = {"values": {}, "resets": [], "confirm_drop": invalid, "base_revision": revision()}
        http_refused(lambda: asyncio.run(admin_settings.settings_save(Request(body), user=None)), 400)
        http_refused(lambda: admin_settings._settings_save_sync({}, [], invalid, revision()), 400)
        http_refused(lambda: world_settings._put_sync({**body, "base_revision": world_settings.get_world_settings()["revision"]}), 400)
    print("PASS H both routes validate confirm_drop")

    reference = {"section": {"objects": [{"nested": [{"name": "n"}]}],
                             "strings": ["x"], "empty": []}, "zero": 0, "false": False}
    assert adm.find_dropped_paths(reference, {}, []) == ["false", "section", "section.objects", "zero"]
    assert adm.find_dropped_paths(reference, {"section": {} , "zero": 0, "false": False}, []) == ["section.objects"]
    assert adm.find_dropped_paths(reference, {}, ["section"]) == ["false", "zero"]
    assert adm.find_dropped_paths(reference, {}, ["sect", "section.object"]) == ["false", "section", "section.objects", "zero"]
    assert adm.find_dropped_paths({"rows": [{"nested": [{"name": "n"}]}]}, {"rows": [{}]}, []) == []
    print("PASS dictionary traversal and segment-boundary exemptions")
    print("ALL OK")
