"""Smoke content revisions and three-way layer saves using temporary storage.

Usage: ./.venv/bin/python scripts/smoke_config_revision.py

Hand-derived expectations from plan-config-revision.md, Task 1:
A Identical pruned content hashes to the same 16 hex digits; changing the
  timezone changes the content and therefore the revision.
B A view's default enabled=True is unchanged relative to its base, so the
  foreign False survives alongside our new p2. Old-code proof: c131288a
  has no issue_revision, so this case cannot preserve a revision-based edit.
C Both sides choosing UTC agree and must save without conflict.
D UTC versus Asia/Tokyo changes the same unit differently: exactly
  server.timezone conflicts, and refusal must leave UTC bytes untouched.
E A masked key means the base key, not a new edit; foreign k2 survives while
  our independent timezone edit saves UTC.
F Reloading unchanged files preserves the content revision: an empty cache
  cannot prevent a save on the equal-revision fast path.
G Reloading changed content with no cached base refuses unknown_base with
  no conflict paths and no file writes.
H Disjoint timezone/provider edits from two threads both survive; two
  different timezone edits yield exactly one success and one conflict.
I game_seasons is one top-level list unit, independent of chat.top_p;
  editing both from the same base retains both foreign and own changes.
J routing is one image_generation.routing unit; removing an occasion
  replaces that subtree, so the removed occasion cannot reappear.
K A stale page resetting server.timezone after a foreign save stored UTC
  there conflicts on exactly server.timezone and leaves UTC; the same stale
  page resetting it when the foreign save touched only providers succeeds
  and drops the stored timezone (no shipped default stays in the file).
L Raw's header equals the revision of the instance view it returns.
M Missing revision refuses with the exact 428 contract, non-strings with 400.
N Foreign UTC versus own Tokyo conflicts on server.timezone and writes nothing.
O Success returns the content revision; equal revision needs no cached base.
  Reads, validation and persistence must hold the lock; two independent
  route edits from the same base retain both timezone and provider edits.
P World GET returns its revision; missing base refuses with 428 and different
  chat.top_p edits conflict with 409, preserving the foreign value.
Route contract missing on Task 1 commit 5523db30.
"""
import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import threading
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="config-revision-") as root:
    world = Path(root) / "world"
    instance = Path(root) / "instance"
    world.mkdir()
    instance.mkdir()
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin as adm, config_scope

    # Service reloads may contact providers; this smoke tests persistence only.
    def reloads(keys, scope):
        assert not config._LOCK._is_owned(), "service reload under config lock"
        return []

    adm.apply_section_reloads = reloads
    seed = {"providers": [{"name": "p1", "api_key": "k1"}],
            "image_generation": {"backends": [{"name": "b1", "api_type": "openai_diffusion"}],
                                 "routing": {"profile": ["b1"]}},
            "server": {"timezone": "Europe/Berlin"}}

    def clear_cache():
        adm._REVISION_CACHE.clear()

    def load():
        for directory in (world, instance):
            (directory / "secrets.json").unlink(missing_ok=True)
        (instance / "config.json").write_text(json.dumps(seed))
        (world / "config.json").write_text(json.dumps({"game_seasons": [{"name": "warm", "days": 20}]}))
        config.load(world / "config.json", instance / "config.json")

    def issued(scope="instance"):
        with config._LOCK:
            return adm.issue_revision(scope), adm.layer_view(scope)

    def stored(scope="instance"):
        return json.loads(((instance if scope == "instance" else world) / "config.json").read_text())

    def foreign_timezone(value):
        view = adm.layer_view("instance")
        view["server"]["timezone"] = value
        adm.save_layer("instance", view)

    def snapshot():
        return {str(p): p.read_bytes() for directory in (instance, world)
                for p in directory.glob("*.json")}

    def stale(fn, expected, reason="conflict"):
        before = snapshot()
        try:
            fn()
        except adm.LayerStale as exc:
            assert exc.paths == expected, exc.paths
            assert exc.reason == reason, exc.reason
        else:
            raise AssertionError("expected LayerStale")
        assert snapshot() == before

    load()
    r0, view0 = issued()
    assert issued()[0] == r0 and re.fullmatch(r"[0-9a-f]{16}", r0)
    foreign_timezone("UTC")
    assert issued()[0] != r0
    print("PASS A")

    # Pin the old-code proof to the pre-revision implementation, never HEAD.
    old_source = subprocess.run(
        ["timeout", "300", "git", "show", "c131288a:app/core/config_admin.py"],
        check=True, capture_output=True, text=True).stdout
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "issue_revision"
                   for node in ast.parse(old_source).body), "B: old code already issues revisions"
    load()
    r0, view0 = issued()
    assert view0["image_generation"]["enabled"] is True
    adm.set_media_switch(False)
    view0["providers"].append({"name": "p2"})
    result = adm.save_layer("instance", view0, base_revision=r0)
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p2"]
    assert stored()["image_generation"]["enabled"] is False
    assert result["revision"] == adm.layer_revision("instance")
    print("PASS B")

    for case, timezone in (("C", "UTC"), ("D", "Asia/Tokyo")):
        load()
        r0, view0 = issued()
        foreign_timezone("UTC")
        view0["server"]["timezone"] = timezone
        if case == "C":
            adm.save_layer("instance", view0, base_revision=r0)
        else:
            stale(lambda: adm.save_layer("instance", view0, base_revision=r0), ["server.timezone"])
        assert stored()["server"]["timezone"] == "UTC"
        print("PASS", case)

    load()
    r0, view0 = issued()
    foreign = adm.layer_view("instance")
    foreign["providers"][0]["api_key"] = "k2"
    adm.save_layer("instance", foreign)
    view0["providers"][0]["api_key"] = "***"
    view0["server"]["timezone"] = "UTC"
    adm.save_layer("instance", view0, base_revision=r0)
    secrets = json.loads((instance / "secrets.json").read_text())
    assert secrets["providers"]["p1"]["api_key"] == "k2", secrets
    assert stored()["server"]["timezone"] == "UTC"
    print("PASS E")

    load()
    r0, view0 = issued()
    config.load(world / "config.json", instance / "config.json")
    clear_cache()
    assert adm.layer_revision("instance") == r0
    view0["server"]["timezone"] = "UTC"
    adm.save_layer("instance", view0, base_revision=r0)
    assert stored()["server"]["timezone"] == "UTC"
    print("PASS F")

    load()
    r0, view0 = issued()
    foreign_timezone("UTC")
    config.load(world / "config.json", instance / "config.json")
    clear_cache()
    stale(lambda: adm.save_layer("instance", view0, base_revision=r0), [], "unknown_base")
    print("PASS G")

    def concurrent(views, revision):
        barrier = threading.Barrier(2)
        def save(view):
            barrier.wait(timeout=10)
            try:
                return adm.save_layer("instance", view, base_revision=revision)
            except adm.LayerStale as exc:
                return exc
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(save, views))

    load()
    r0, first = issued()
    second = copy.deepcopy(first)
    first["server"]["timezone"] = "UTC"
    second["providers"].append({"name": "p3"})
    assert all(isinstance(r, dict) for r in concurrent([first, second], r0))
    assert stored()["server"]["timezone"] == "UTC"
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p3"]
    r0, first = issued()
    second = copy.deepcopy(first)
    first["server"]["timezone"] = "Asia/Tokyo"
    second["server"]["timezone"] = "America/New_York"
    results = concurrent([first, second], r0)
    assert sum(isinstance(r, dict) for r in results) == 1
    failure = next(r for r in results if isinstance(r, adm.LayerStale))
    assert failure.paths == ["server.timezone"] and failure.reason == "conflict"
    winner = "Asia/Tokyo" if isinstance(results[0], dict) else "America/New_York"
    assert stored()["server"]["timezone"] == winner
    print("PASS H")

    load()
    r0, view0 = issued("world")
    foreign = adm.layer_view("world")
    foreign.setdefault("chat", {})["top_p"] = 0.37
    adm.save_layer("world", foreign)
    view0["game_seasons"] = [{"name": "cold", "days": 30}]
    adm.save_layer("world", view0, base_revision=r0)
    assert stored("world")["chat"]["top_p"] == 0.37
    assert stored("world")["game_seasons"] == [{"name": "cold", "days": 30}]
    print("PASS I")

    base = {"image_generation": {"routing": {"profile": ["b1"], "scene": ["b1"]}}}
    own = copy.deepcopy(base)
    del own["image_generation"]["routing"]["profile"]
    result = adm.rebase_layer("instance", own, base, copy.deepcopy(base))
    assert result == {"image_generation": {"routing": {"scene": ["b1"]}}}
    assert adm.change_units(base) == {"image_generation.routing": base["image_generation"]["routing"]}
    assert config_scope.prune({"image_generation": {"lora_triggers": [{"name": "virtual"}]}}) == {}
    print("PASS J")

    load()
    r0, view0 = issued()
    foreign_timezone("UTC")
    try:
        adm.save_layer("instance", view0, resets=["server.timezone"], base_revision=r0)
    except adm.LayerStale as exc:
        assert exc.paths == ["server.timezone"] and exc.reason == "conflict"
    else:
        raise AssertionError("K: stale reset overwrote a foreign edit")
    assert stored()["server"]["timezone"] == "UTC"
    load()
    r0, view0 = issued()
    foreign = adm.layer_view("instance")
    foreign["providers"].append({"name": "p9"})
    adm.save_layer("instance", foreign)
    adm.save_layer("instance", view0, resets=["server.timezone"], base_revision=r0)
    assert "timezone" not in stored().get("server", {})
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p9"]
    print("PASS K")
    from fastapi import HTTPException, Response
    from app.routes import admin_settings, world_settings

    def locked(fn):
        def call(*args, **kwargs):
            assert config._LOCK._is_owned(), f"{fn.__name__} outside config lock"
            return fn(*args, **kwargs)
        return call

    def raw():
        response = Response()
        with patch.object(adm, "layer_view", locked(adm.layer_view)), \
                patch.object(adm, "issue_revision", locked(adm.issue_revision)):
            view = admin_settings.settings_raw(response=response, user=None)
        return response.headers["X-Config-Revision"], view

    def http_error(fn, status, code=None, conflict_paths=None):
        before = snapshot()
        try:
            fn()
        except HTTPException as exc:
            assert exc.status_code == status, (exc.status_code, exc.detail)
            if code:
                assert exc.detail["code"] == code, exc.detail
            if conflict_paths is not None:
                assert exc.detail["paths"] == conflict_paths and exc.detail["reason"] == "conflict"
            if status == 428:
                assert exc.detail["code"] == "revision_required"
                assert exc.detail["message"].startswith(
                    "base_revision missing — load the settings first (GET /admin/")
        else:
            raise AssertionError(f"expected HTTP {status}")
        assert snapshot() == before

    class Request:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    load()
    revision, view = raw()
    assert revision == adm.layer_revision("instance")
    print("PASS L")
    http_error(lambda: admin_settings._settings_save_sync(view, [], []), 428, "revision_required")
    http_error(lambda: asyncio.run(admin_settings.settings_save(
        Request({"values": view, "resets": []}), user=None)), 428, "revision_required")
    for invalid in (None, False, 1, [], {}):
        http_error(lambda: asyncio.run(admin_settings.settings_save(
            Request({"values": view, "resets": [], "base_revision": invalid}), user=None)), 400)
        http_error(lambda: admin_settings._settings_save_sync(view, [], [], invalid), 400)
    print("PASS M")
    foreign_timezone("UTC")
    view["server"]["timezone"] = "Asia/Tokyo"
    http_error(lambda: admin_settings._settings_save_sync(view, [], [], revision),
               409, "stale", ["server.timezone"])
    print("PASS N")
    load()
    revision, view = raw()
    view["server"]["timezone"] = "UTC"
    with patch.object(adm, "prepare_layer", locked(adm.prepare_layer)), \
            patch.object(adm, "_persist_layer", locked(adm._persist_layer)), \
            patch.object(admin_settings, "_validate_llm_routing", locked(admin_settings._validate_llm_routing)), \
            patch.object(admin_settings, "_validate_image_routing", locked(admin_settings._validate_image_routing)):
        result = admin_settings._settings_save_sync(view, [], [], revision)
    assert result["revision"] == adm.layer_revision("instance")
    clear_cache()
    result = admin_settings._settings_save_sync(view, [], [], result["revision"])
    assert result["revision"] == adm.layer_revision("instance")
    load()
    revision, first = raw()
    second = copy.deepcopy(first)
    first["server"]["timezone"] = "UTC"
    second["providers"].append({"name": "p3"})
    barrier = threading.Barrier(2)
    def route_save(view):
        barrier.wait(timeout=10)
        return admin_settings._settings_save_sync(view, [], [], revision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(r["status"] == "success" for r in pool.map(route_save, [first, second]))
    assert stored()["server"]["timezone"] == "UTC"
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p3"]
    print("PASS O")
    load()
    with patch.object(adm, "layer_part", locked(adm.layer_part)), \
            patch.object(adm, "issue_revision", locked(adm.issue_revision)):
        payload = world_settings.get_world_settings()
    assert payload["revision"] == adm.layer_revision("world")
    http_error(lambda: world_settings._put_sync({"values": payload["values"]}), 428, "revision_required")
    for invalid in (None, False, 1, [], {}):
        http_error(lambda: world_settings._put_sync({"values": payload["values"], "base_revision": invalid}), 400)
    foreign = copy.deepcopy(payload["values"])
    foreign.setdefault("chat", {})["top_p"] = 0.37
    result = world_settings._put_sync({"values": foreign, "base_revision": payload["revision"]})
    assert result["revision"] == adm.layer_revision("world")
    payload["values"].setdefault("chat", {})["top_p"] = 0.63
    http_error(lambda: world_settings._put_sync({"values": payload["values"], "base_revision": payload["revision"]}),
               409, "stale", ["chat.top_p"])
    print("PASS P")
    print("ALL OK")
