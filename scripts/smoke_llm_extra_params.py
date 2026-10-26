#!/usr/bin/env python3
"""Verify routed request-body overrides against the real SDK serialization.

Usage: ./.venv/bin/python scripts/smoke_llm_extra_params.py

MockTransport intercepts requests before the network: no provider calls or world DB.
The expected JSON is derived from explicit defaults and overrides below, not from
recorded SDK output. Both client implementations and the suitability runner use
exactly the same body assembly as normal sync/stream calls.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpx
import httpx2
import openai
from fastapi import HTTPException

from app.core import embedding, llm_client, llm_log_replay, llm_router, model_suitability
from app.imagegen.service import ImageService
from plugins.instagram.skill_post import InstagramSkill
from app.routes.admin_settings import (
    _llm_suitability_test_start_sync, _settings_save_sync, _validate_llm_routing)


BODIES = []



def rejecting_stream_options(request):
    body = json.loads(request.content)
    if "stream_options" in body:
        BODIES.append(body)
        return httpx.Response(400, json={"error": {"message": "unknown stream_options"}})
    return transport(request)

def transport(request, response_class=httpx.Response):
    body = json.loads(request.content)
    BODIES.append(body)
    if "/messages" in request.url.path:
        if body.get("stream"):
            payload = ('event: message_start\ndata: {"type":"message_start","message":{"id":"msg_test",'
                       '"type":"message","role":"assistant","content":[],"model":"test",'
                       '"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,'
                       '"output_tokens":0}}}\n\n'
                       'event: content_block_start\ndata: {"type":"content_block_start",'
                       '"index":0,"content_block":{"type":"text","text":""}}\n\n'
                       'event: content_block_delta\ndata: {"type":"content_block_delta",'
                       '"index":0,"delta":{"type":"text_delta","text":"ok"}}\n\n'
                       'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
                       'event: message_delta\ndata: {"type":"message_delta","delta":'
                       '{"stop_reason":"end_turn","stop_sequence":null},"usage":'
                       '{"output_tokens":1}}\n\n'
                       'event: message_stop\ndata: {"type":"message_stop"}\n\n')
            return response_class(200, text=payload, headers={"content-type": "text/event-stream"})
        return response_class(200, json={"id": "msg_test", "type": "message", "role": "assistant",
                                         "model": "test", "content": [{"type": "text", "text": "ok"}],
                                         "stop_reason": "end_turn", "stop_sequence": None,
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})
    if body.get("stream"):
        return response_class(200, text='data: {"id":"test","choices":[{"index":0,'
                            '"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
                            'data: [DONE]\n\n', headers={"content-type": "text/event-stream"})
    return response_class(200, json={"id": "test", "object": "chat.completion", "created": 1,
                                     "model": "test", "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": "ok"}}]})


async def stream_body(client):
    async for _ in client.astream([{"role": "user", "content": "ping"}]):
        pass
    return BODIES[-1]


def main():
    wire = httpx.MockTransport(transport)
    anth_wire = httpx2.MockTransport(lambda request: transport(request, httpx2.Response))
    real_openai, real_async_openai = openai.OpenAI, openai.AsyncOpenAI
    real_anthropic, real_async_anthropic = anthropic.Anthropic, anthropic.AsyncAnthropic
    # Supply transport to actual SDKs, not fake completions.create implementations.
    with patch.object(openai, "OpenAI", side_effect=lambda **kw: real_openai(
            **kw, http_client=httpx.Client(transport=wire))), patch.object(
            openai, "AsyncOpenAI", side_effect=lambda **kw: real_async_openai(
                **kw, http_client=httpx.AsyncClient(transport=wire))), patch.object(
            anthropic, "Anthropic", side_effect=lambda **kw: real_anthropic(
                **kw, http_client=httpx2.Client(transport=anth_wire))), patch.object(
            anthropic, "AsyncAnthropic", side_effect=lambda **kw: real_async_anthropic(
                **kw, http_client=httpx2.AsyncClient(transport=anth_wire))):
        saved = {"temperature": 0, "chat_template_kwargs": {"enable_thinking": True,
                 "extra": "retained"}, "repetition_penalty": 1.2, "nested": {"a": 1, "b": 2},
                 "stream_options": {"probe": True}, "max_tokens": 1800}
        first = {"provider": "P", "model": "qwen3-test", "tasks": [{"task": "intent", "order": 1}],
                 "temperature": 0.8, "extra_params": saved}
        second = {"provider": "P", "model": "backup", "tasks": [{"task": "intent", "order": 2}],
                  "extra_params": {"nested": {"a": 99}}}
        provider = SimpleNamespace(name="P", type="openai", api_base="https://mock.test/v1",
                                   api_key="not-a-real-key", timeout=10, available=True)
        manager = SimpleNamespace(get_provider=lambda name: provider if name == "P" else None,
                                  find_provider_for_model=lambda model: provider)
        original = {"nested": {"a": 1, "b": 2}, "temperature": 0,
                    "chat_template_kwargs": {"enable_thinking": True, "extra": "retained"},
                    "repetition_penalty": 1.2, "stream_options": {"probe": True},
                    "max_tokens": 1800}
        with patch.object(llm_router, "get_provider_manager", return_value=manager), patch.object(
                llm_router, "_load_routing", return_value=[first, second]), patch.object(
                llm_router, "disabled_providers", return_value=set()), patch.object(
                llm_router, "_model_cooled_down", return_value=False), patch(
                "app.core.llm_task_state.is_enabled", return_value=True):
            routed = llm_router.resolve_llm("intent")
            assert routed.extra_params == saved
            client = routed.create_llm()
            assert client.invoke([{"role": "user", "content": "ping"}]).content == "ok"
            body = BODIES[-1]
            assert body["temperature"] == 0
            assert body["chat_template_kwargs"] == {"enable_thinking": True, "extra": "retained"}
            assert body["nested"] == {"a": 1, "b": 2}
            assert body["repetition_penalty"] == 1.2
            assert body["max_tokens"] == 1800
            assert routed.create_llm(max_tokens=77).invoke(
                [{"role": "user", "content": "ping"}]).content == "ok"
            assert BODIES[-1]["max_tokens"] == 1800  # Explicit extra_body wins on normal calls.
            streamed = asyncio.run(stream_body(client))
            assert streamed["chat_template_kwargs"] == body["chat_template_kwargs"]
            assert streamed["stream_options"] == {"probe": True}
            # The routed vision clients use the same SDK request assembly.
            with patch.object(llm_router, "_load_routing", return_value=[
                    {**first, "tasks": [{"task": "image_recognition", "order": 1}]}]), patch.object(
                    llm_router, "_resolve_character_override", return_value=None), patch(
                    "app.core.llm_queue.get_llm_queue",
                    return_value=SimpleNamespace(submit=lambda **kw: kw["llm"].invoke(
                        kw["messages_or_prompt"]))), patch(
                    "app.models.character.is_outfit_locked", return_value=False):
                service = ImageService.__new__(ImageService)
                with TemporaryDirectory() as folder:
                    image = Path(folder) / "photo.png"
                    image.write_bytes(b"\x89PNG\r\n\x1a\n")
                    assert service._generate_image_analysis(str(image), "demo") == "ok"
                    assert BODIES[-1]["nested"] == {"a": 1, "b": 2}
                assert service._generate_comment(
                    "demo", "*demo takes a photograph of the room*") == "ok"
                assert BODIES[-1]["nested"] == {"a": 1, "b": 2}
                before = len(BODIES)
                service._extract_rp_scene_context("*demo walks across the room*", "demo")
                assert len(BODIES) == before + 1
                assert BODIES[-1]["nested"] == {"a": 1, "b": 2}
                with TemporaryDirectory() as folder, patch(
                        "plugins.instagram.skill_post.get_character_personality", return_value=""), patch(
                        "app.core.prompt_templates.render_task", return_value=("Rules", "Describe")):
                    image = Path(folder) / "post.png"
                    image.write_bytes(b"\x89PNG\r\n\x1a\n")
                    instagram = InstagramSkill.__new__(InstagramSkill)
                    instagram._get_effective_config = lambda name: {"caption_language": "en"}
                    assert instagram._generate_caption(str(image), "demo", "photo") == "ok"
                    assert BODIES[-1]["nested"] == {"a": 1, "b": 2}
                    assert instagram._analyze_image(str(image), "demo") == "ok"
                    assert BODIES[-1]["nested"] == {"a": 1, "b": 2}
            expensive = {**first, "extra_params": {**saved, "max_tokens": 9999}}
            asyncio.run(llm_router._warmup_one(expensive))
            assert BODIES[-1]["max_tokens"] == 9999
            assert BODIES[-1]["temperature"] == 0
            assert saved == original  # Neither SDK call mutates saved configuration.
            explicit = llm_router.get_llm_instance_by_name("P::qwen3-test")
            assert explicit.extra_params == saved
            direct = llm_router.create_llm_instance("suitability_test", "P::unrouted")
            assert direct.extra_params == {}
            assert direct.create_llm().invoke([{"role": "user", "content": "ping"}]).content == "ok"
            assert "nested" not in BODIES[-1] and BODIES[-1]["model"] == "unrouted"
            with patch.object(llm_router, "_usable", side_effect=lambda e, *a, **kw:
                              None if e is first else provider):
                fallback = llm_router.resolve_llm("intent")
                assert fallback.extra_params == second["extra_params"]
                assert fallback.create_llm().invoke([{"role": "user", "content": "ping"}]).content == "ok"
                assert BODIES[-1]["nested"] == {"a": 99}
                assert "chat_template_kwargs" not in BODIES[-1]  # backup is not Qwen3
            with patch.object(model_suitability, "load_cases", return_value={
                    "allowed_tools": [], "cases": [{"id": "one", "label": "one", "category": "helper",
                    "fmt": "text", "system": "system", "user": "ping", "expect": {}}]}), patch.object(
                    model_suitability, "_persist", return_value=False):
                temporary = {"nested": {"b": 3}, "temperature": 0.2}
                events = list(model_suitability.iter_suitability_results(
                    "P::qwen3-test", extra_params=temporary))
                assert events[0]["type"] == "start" and events[-1]["type"] == "done"
                assert BODIES[-1]["nested"] == {"a": 1, "b": 3}
                assert BODIES[-1]["temperature"] == 0.2
                assert BODIES[-1]["max_tokens"] == 1800
                assert saved == original and temporary == {"nested": {"b": 3}, "temperature": 0.2}
                list(model_suitability.iter_suitability_results(
                    "P::qwen3-test", extra_params={"max_tokens": 9999}))
                assert BODIES[-1]["max_tokens"] == 9999
            default_anth = llm_client.AnthropicLLMClient(
                "test", "not-a-real-key", "https://mock.test/v1", temperature=0.4)
            assert default_anth.invoke([{"role": "user", "content": "ping"}]).content == "ok"
            assert BODIES[-1]["temperature"] == 0.4
            anth = llm_client.AnthropicLLMClient("test", "not-a-real-key", "https://mock.test/v1",
                                                extra_params={"temperature": 0, "metadata": {"user_id": "demo"}})
            assert anth.invoke([{"role": "user", "content": "ping"}]).content == "ok"
            assert BODIES[-1]["temperature"] == 0 and BODIES[-1]["metadata"] == {"user_id": "demo"}
            assert asyncio.run(stream_body(anth))["temperature"] == 0
            anth_provider = SimpleNamespace(
                name="P", type="anthropic", api_base="https://mock.test/v1",
                api_key="not-a-real-key", timeout=10, available=True)
            anth_manager = SimpleNamespace(get_provider=lambda name: anth_provider,
                                           find_provider_for_model=lambda model: anth_provider)
            with patch.object(llm_router, "get_provider_manager", return_value=anth_manager), patch.object(
                    llm_router, "_load_routing", return_value=[{
                        "provider": "P", "model": "claude-test", "tasks": [
                            {"task": "image_recognition", "order": 1}],
                        "extra_params": {"metadata": {"user_id": "demo"}}}]), patch.object(
                    llm_router, "_resolve_character_override", return_value=None), patch(
                    "app.core.llm_queue.get_llm_queue",
                    return_value=SimpleNamespace(submit=lambda **kw: kw["llm"].invoke(
                        kw["messages_or_prompt"]))), patch(
                    "app.core.prompt_templates.render_task", return_value=("Rules", "Describe")):
                with TemporaryDirectory() as folder:
                    image = Path(folder) / "post.png"
                    image.write_bytes(b"\x89PNG\r\n\x1a\n")
                    instagram = InstagramSkill.__new__(InstagramSkill)
                    instagram._get_effective_config = lambda name: {"caption_language": "en"}
                    assert instagram._analyze_image(str(image), "demo") == "ok"
                    assert BODIES[-1]["metadata"] == {"user_id": "demo"}
                    assert BODIES[-1]["max_tokens"] == 500
                    assert BODIES[-1]["messages"][0]["content"][1]["type"] == "image"
            source = {"prompt": {"request_messages": [{"role": "user", "content": "ping"}]}}
            identifier = llm_log_replay.entry_id(source)
            rows = [source]

            def replay_submit(**kw):
                kw["llm"].invoke(kw["messages_or_prompt"])
                rows.append({"replay_of": identifier, "replay_id": kw["llm"].replay_id})

            replay_manager = SimpleNamespace(get_provider=manager.get_provider,
                                             get_queue_for_provider=lambda name: SimpleNamespace(
                                                 submit=replay_submit))
            with patch("app.core.provider_manager.get_provider_manager",
                       return_value=replay_manager), patch.object(
                       llm_log_replay, "read_entries", side_effect=lambda path: rows), patch.object(
                       llm_router, "_load_routing", return_value=[{**first, "max_tokens": 321,
                       "extra_params": {"nested": {"keep": 1}}}]):
                llm_log_replay.replay_entry(Path("unused"), entry_id=identifier, provider="P",
                                            model="qwen3-test", temperature=0.1, max_tokens=0)
                assert "max_tokens" not in BODIES[-1]
                llm_log_replay.replay_entry(Path("unused"), entry_id=identifier, provider="P",
                                            model="qwen3-test", temperature=0.1, max_tokens=64)
                assert BODIES[-1]["max_tokens"] == 64
            with patch("app.core.provider_manager.get_provider_manager",
                       return_value=replay_manager), patch.object(
                       llm_log_replay, "read_entries", side_effect=lambda path: rows), patch.object(
                       llm_router, "_load_routing", return_value=[{**first, "max_tokens": 321,
                       "extra_params": {"max_tokens": 700}}]):
                llm_log_replay.replay_entry(Path("unused"), entry_id=identifier, provider="P",
                                            model="qwen3-test", temperature=0.1, max_tokens=0)
                assert "max_tokens" not in BODIES[-1]
                llm_log_replay.replay_entry(Path("unused"), entry_id=identifier, provider="P",
                                            model="qwen3-test", temperature=0.1, max_tokens=64)
                assert BODIES[-1]["max_tokens"] == 700
            embedding_instance = SimpleNamespace(
                model="embedding-model", extra_params={"nested": {"a": 1, "b": 2},
                                                         "input": "override-me"})
            seen_embedding = {}

            def embedding_transport(request):
                seen_embedding["url"] = str(request.url)
                seen_embedding["auth"] = request.headers.get("authorization")
                seen_embedding["body"] = json.loads(request.content)
                return httpx.Response(200, json={"data": [{"embedding": [1, 2]}]})

            def embedding_post(url, **kwargs):
                with httpx.Client(transport=httpx.MockTransport(embedding_transport)) as http:
                    return http.post(url, **kwargs)

            with patch.object(embedding, "_resolve_external",
                              return_value=(embedding_instance, provider)), patch(
                              "app.models.world.get_world_setting", return_value="prefix:"), patch(
                              "httpx.post", side_effect=embedding_post):
                assert embedding._embed_external("text") == [1.0, 2.0]
                assert seen_embedding == {
                    "url": "https://mock.test/v1/embeddings",
                    "auth": "Bearer not-a-real-key",
                    "body": {"model": "embedding-model", "input": "override-me",
                             "nested": {"a": 1, "b": 2}}}
                assert embedding_instance.extra_params["input"] == "override-me"
        for invalid in ('{bad', '[]', '1', [], 1):
            assert "extra_params" in _validate_llm_routing([{"extra_params": invalid}])
            try:
                _llm_suitability_test_start_sync(None, {"provider": "P", "model": "test",
                                                       "extra_params": invalid})
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError(f"Accepted invalid extra_params: {invalid!r}")
        assert "extra_params" in _validate_llm_routing([{"extra_params": '{"temperature":0}'}])
        assert not _validate_llm_routing([{"extra_params": {"temperature": 0}}])
        # The full save path must reject the prepared candidate before persistence.
        with patch("app.core.config_admin.prepare_layer", return_value=(
                {"llm_routing": [{"extra_params": '{"temperature":0}'}]}, {})), patch(
                "app.core.config_admin._persist_layer") as persist:
            try:
                _settings_save_sync({}, [], [], "revision")
            except HTTPException as exc:
                assert exc.status_code == 400 and "extra_params" in exc.detail
            else:
                raise AssertionError("Saved routing accepted string extra_params")
            persist.assert_not_called()
        # The test POST accepts textarea JSON independently of saved settings.
        with patch("app.core.model_suitability.start_test", return_value={"status": "running"}):
            assert _llm_suitability_test_start_sync(None, {
                "provider": "P", "model": "test", "extra_params": '{"temperature":0}'
            }) == {"status": "running"}
        with patch("app.core.model_suitability.start_test", return_value={"status": "running"}) as start:
            assert _llm_suitability_test_start_sync(None, {
                "provider": "P", "model": "test", "extra_params": {}
            }) == {"status": "running"}
            start.assert_called_once_with("P::test", extra_params={},
                                          routing_entry=None, entry_index=None)
    rejecting_wire = httpx.MockTransport(rejecting_stream_options)
    with patch.object(openai, "AsyncOpenAI", side_effect=lambda **kw: real_async_openai(
            **kw, http_client=httpx.AsyncClient(transport=rejecting_wire))):
        llm_client._NO_STREAM_USAGE.clear()
        default = llm_client.LLMClient("default", "key", "https://mock.test/v1")
        before = len(BODIES)
        assert asyncio.run(stream_body(default))["stream"] is True
        assert len(BODIES) == before + 2  # Reject then retry without stream_options.
        assert "stream_options" not in BODIES[-1]
        assert asyncio.run(stream_body(default))["stream"] is True
        assert "stream_options" not in BODIES[-1]
        explicit = llm_client.LLMClient("explicit", "key", "https://mock.test/v1",
                                        extra_params={"stream_options": {"probe": True}})
        before = len(BODIES)
        try:
            asyncio.run(stream_body(explicit))
        except openai.BadRequestError:
            pass
        else:
            raise AssertionError("Explicit stream_options rejection was hidden")
        assert len(BODIES) == before + 1
        assert BODIES[-1]["stream_options"]["probe"] is True
        assert ("https://mock.test/v1", "explicit") not in llm_client._NO_STREAM_USAGE
        llm_client._NO_STREAM_USAGE.clear()
    print("LLM extra_params: routed sync/stream, fallback, direct, suitability, Anthropic, validation OK")


if __name__ == "__main__":
    main()
