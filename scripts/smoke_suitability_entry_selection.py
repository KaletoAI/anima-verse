#!/usr/bin/env python3
"""Check selected suitability routing entries and finite request parameters.

Usage: ./.venv/bin/python scripts/smoke_suitability_entry_selection.py

Uses an in-memory HTTP transport and frozen test case; never calls providers or
writes world/config/model-capability data.
"""
import json
import math
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
from fastapi import HTTPException

from app.core import llm_router, model_suitability
from app.routes import admin
from app.routes.admin_settings import (_llm_suitability_test_start_sync,
                                       _settings_save_sync, _validate_llm_routing,
                                       llm_suitability_test_jobs)


def expect_bad_request(body, status=400):
    try:
        _llm_suitability_test_start_sync(None, body)
    except HTTPException as exc:
        assert exc.status_code == status, exc
        return str(exc.detail)
    raise AssertionError(f"Accepted invalid suitability input: {body!r}")


def finite_parameters():
    for bad in (math.nan, math.inf, -math.inf):
        for payload in ({"nested": [{"value": bad}]},
                        '{"nested":[{"value":1e999}]}'):
            original = repr(payload)
            assert "finite" in _validate_llm_routing([{"extra_params": payload}]).lower()
            assert "finite" in expect_bad_request({"provider": "P", "model": "test",
                                                   "extra_params": payload}).lower()
            assert repr(payload) == original
    for raw in ('{"nested":[NaN]}', '{"nested":{"value":Infinity}}',
                '{"nested":[-Infinity]}'):
        assert "finite" in _validate_llm_routing([{"extra_params": raw}]).lower()
        assert "finite" in expect_bad_request({"provider": "P", "model": "test",
                                               "extra_params": raw}).lower()
    assert llm_router.parse_extra_params('{"nested":[{"value":1.25}]}') == {
        "nested": [{"value": 1.25}]}
    assert not _validate_llm_routing([{"extra_params": {"nested": [1.25]}}])
    # Save validation runs on the prepared candidate, before any persistence.
    with patch("app.core.config_admin.prepare_layer", return_value=(
            {"llm_routing": [{"extra_params": {"nested": [1e999]}}]}, {})), patch(
            "app.core.config_admin._persist_layer") as persist:
        try:
            _settings_save_sync({}, [], [], "revision")
        except HTTPException as exc:
            assert exc.status_code == 400 and "finite" in exc.detail
        else:
            raise AssertionError("Saved non-finite routing parameters")
        persist.assert_not_called()


def selection_on_wire():
    entries = [
        {"name": "Precise", "provider": "P", "model": "same", "enabled": True,
         "temperature": 0.1, "extra_params": {"nested": {"selection": "first"}}},
        {"name": "Creative", "provider": "P", "model": "same", "enabled": True,
         "temperature": 0.9, "extra_params": {"nested": {"selection": "second"}}},
        {"name": "Other", "provider": "P", "model": "different", "enabled": True,
         "extra_params": {"nested": {"selection": "wrong"}}},
        {"name": "Disabled", "provider": "P", "model": "same", "enabled": False,
         "extra_params": {"nested": {"selection": "disabled"}}},
    ]
    wire_bodies = []

    def wire(request):
        wire_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 1, "model": "same",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}]})

    provider = SimpleNamespace(name="P", type="openai", api_base="https://mock.test/v1",
                               api_key="dummy", timeout=10, available=True)
    manager = SimpleNamespace(get_provider=lambda name: provider if name == "P" else None,
                              find_provider_for_model=lambda model: provider,
                              list_all_models=lambda: {"P": {"models": [
                                  {"name": "same"}, {"name": "unsaved"}]}})
    case = {"id": "one", "label": "one", "category": "helper", "fmt": "text",
            "system": "system", "user": "ping", "expect": {}}
    original_client = openai.OpenAI

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    with patch.object(llm_router, "get_provider_manager", return_value=manager), \
         patch.object(llm_router, "_load_routing", return_value=entries), \
         patch("app.routes.admin_settings.config.get", return_value=entries), \
         patch.object(model_suitability, "load_cases", return_value={
             "allowed_tools": [], "cases": [case]}), \
         patch.object(model_suitability, "_persist", return_value=False), \
         patch("app.core.config_admin.layer_revision", return_value="rev-1"), \
         patch.object(model_suitability.threading, "Thread", ImmediateThread), \
         patch.object(openai, "OpenAI", side_effect=lambda **kw: original_client(
             **kw, http_client=httpx.Client(transport=httpx.MockTransport(wire)))):
        with patch.object(admin, "get_provider_manager", return_value=manager), \
             patch.object(admin, "get_all_capabilities", return_value={}), \
             patch.object(admin, "get_all_suitability", return_value={}), \
             patch.object(admin, "get_model_capabilities", return_value={}):
            data = admin.model_capabilities_data()
            assert data["routing_revision"] == "rev-1"
            assert data["routing_entries"] == [
                {"index": 0, "provider": "P", "model": "same", "name": "Precise"},
                {"index": 1, "provider": "P", "model": "same", "name": "Creative"},
                {"index": 2, "provider": "P", "model": "different", "name": "Other"}]
        assert "select" in expect_bad_request({"provider": "P", "model": "same"}).lower()
        for bad in (-1, 2, 3, 999, "1", True):
            assert "entry" in expect_bad_request({"provider": "P", "model": "same",
                                                   "entry_index": bad}).lower()
        assert "entry" in expect_bad_request({"provider": "Other", "model": "same",
                                               "entry_index": 1}).lower()
        assert "reload" in expect_bad_request({
            "provider": "P", "model": "same", "entry_index": 0,
            "routing_revision": "obsolete"}, status=409).lower()
        for index, expected in ((0, "first"), (1, "second")):
            result = _llm_suitability_test_start_sync(None, {
                "provider": "P", "model": "same", "entry_index": index,
                "routing_revision": "rev-1"})
            assert result["status"] == "done", result
            assert wire_bodies[-1]["nested"] == {"selection": expected}
        # An unsaved model remains testable using temporary request parameters.
        result = _llm_suitability_test_start_sync(None, {
            "provider": "P", "model": "unsaved",
            "extra_params": '{"nested":{"selection":"temporary"}}'})
        assert result["status"] == "done", result
        assert wire_bodies[-1]["model"] == "unsaved"
        assert wire_bodies[-1]["nested"] == {"selection": "temporary"}

        # Only a repeat of the same active request may reuse its running job.
        class PausedThread:
            def __init__(self, **kwargs):
                pass

            def start(self):
                pass

        with patch.object(model_suitability.threading, "Thread", PausedThread):
            first = _llm_suitability_test_start_sync(None, {
                "provider": "P", "model": "same", "entry_index": 0,
                "routing_revision": "rev-1"})
            assert first["status"] == "running"
            assert first["entry_index"] == 0 and first["entry_name"] == "Precise"
            assert _llm_suitability_test_start_sync(None, {
                "provider": "P", "model": "same", "entry_index": 0,
                "routing_revision": "rev-1"}) == first
            for conflicting in ({"provider": "P", "model": "same", "entry_index": 1,
                                 "routing_revision": "rev-1"},
                                {"provider": "P", "model": "same", "entry_index": 0,
                                 "routing_revision": "rev-1",
                                 "extra_params": {"nested": {"selection": "changed"}}}):
                try:
                    _llm_suitability_test_start_sync(None, conflicting)
                except HTTPException as exc:
                    assert exc.status_code == 409 and "running" in exc.detail.lower()
                else:
                    raise AssertionError("Reused another active suitability request")
            status = model_suitability.get_job("P::same")
            assert status["entry_index"] == 0 and status["entry_name"] == "Precise"
            assert "_request" not in status
            listed = next(j for j in llm_suitability_test_jobs()["jobs"]
                          if j["model"] == "P::same")
            assert listed["entry_index"] == 0 and listed["entry_name"] == "Precise"


def main():
    finite_parameters()
    selection_on_wire()
    print("Suitability entry selection and finite parameters OK")


if __name__ == "__main__":
    main()
