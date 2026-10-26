#!/usr/bin/env python3
"""Check logged samplers and replay controls against serialized SDK requests.

Usage: ./.venv/bin/python scripts/smoke_llm_effective_metadata.py

MockTransport intercepts real SDK serialization; no provider or world DB is used.
Expected values below come from the top-level parameters and explicit body overrides.
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

from app.core import llm_log_replay, llm_router, provider_queue
from app.utils import llm_logger


MESSAGES = [{"role": "user", "content": "ping"}]
BODIES = []


def transport(request):
    body = json.loads(request.content)
    BODIES.append(body)
    if body.get("stream"):
        return httpx.Response(200, text='data: {"id":"test","choices":[{"index":0,'
                              '"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
                              'data: [DONE]\n\n', headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
                                     "model": "test", "choices": [{"index": 0,
                                     "finish_reason": "stop", "message": {"role": "assistant",
                                     "content": "ok"}}]})


def anthropic_transport(request):
    body = json.loads(request.content)
    BODIES.append(body)
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
        return httpx2.Response(200, text=payload, headers={"content-type": "text/event-stream"})
    return httpx2.Response(200, json={"id": "msg_test", "type": "message", "role": "assistant",
                                      "model": "test", "content": [{"type": "text", "text": "ok"}],
                                      "stop_reason": "end_turn", "stop_sequence": None,
                                      "usage": {"input_tokens": 1, "output_tokens": 1}})


def logged_queue_result(client):
    result = client.invoke(MESSAGES)
    task = SimpleNamespace(_llm=client, _messages=MESSAGES, task_type="smoke", agent_name="",
                           provider_name="P", duration_s=0, label="", trace_id="",
                           trace_kind="", _lane_handle=None, _cache_key="", _overflow=None)
    provider_queue._log_task_result(task, client.model, provider_queue._get_max_tokens_safe(client), result)
    return json.loads(llm_logger.LOG_FILE.read_text().splitlines()[-1])


async def logged_stream_result(client):
    async for _ in client.astream(MESSAGES):
        pass
    llm_logger.log_llm_call(task="smoke", model=client.model, llm=client,
                            max_tokens=llm_logger.get_max_tokens(client), request_messages=MESSAGES)
    return json.loads(llm_logger.LOG_FILE.read_text().splitlines()[-1])


def main():
    wire = httpx.MockTransport(transport)
    real_sync, real_async = openai.OpenAI, openai.AsyncOpenAI
    with TemporaryDirectory() as folder, patch.object(llm_logger, "LOG_DIR", Path(folder)), patch.object(
            llm_logger, "LOG_FILE", Path(folder) / "calls.jsonl"), patch.object(
            openai, "OpenAI", side_effect=lambda **kw: real_sync(
                **kw, http_client=httpx.Client(transport=wire))), patch.object(
            openai, "AsyncOpenAI", side_effect=lambda **kw: real_async(
                **kw, http_client=httpx.AsyncClient(transport=wire))):
        saved = {"temperature": 0, "frequency_penalty": 0.55, "top_p": 0,
                 "max_tokens": 257, "repetition_penalty": 1.35}
        entry = {"provider": "P", "model": "test", "temperature": 0.8,
                 "max_tokens": 91, "repetition_penalty": 1.1, "extra_params": saved}
        provider = SimpleNamespace(name="P", type="openai", api_base="https://mock.test/v1",
                                   api_key="test-key", timeout=10, available=True)
        manager = SimpleNamespace(get_provider=lambda name: provider if name == "P" else None,
                                  find_provider_for_model=lambda model: provider)
        with patch.object(llm_router, "get_provider_manager", return_value=manager), patch.object(
                llm_router, "_load_routing", return_value=[entry]):
            client = llm_router.create_llm_instance("smoke", "test", provider_name="P").create_llm(
                frequency_penalty=0.1, top_p=0.9)
            for log, body in ((logged_queue_result(client), BODIES[-1]),
                              (asyncio.run(logged_stream_result(client)), BODIES[-1])):
                assert {key: body[key] for key in saved} == saved
                assert log["sampler"] == {"temperature": 0.0, "frequency_penalty": 0.55,
                                          "top_p": 0.0, "repetition_penalty": 1.35}
                assert log["tokens"]["max"] == body["max_tokens"] == 257
            source = log
            assert entry["extra_params"] == saved

            # Explicit null suppresses a sampler; absent max_tokens keeps the unlimited sentinel.
            plain = llm_router.LLMInstance(provider_name="P", model="test", _provider=provider)
            client = plain.create_llm(temperature=0, frequency_penalty=0,
                                      extra_params={"top_p": None})
            log = logged_queue_result(client)
            body = BODIES[-1]
            assert body["temperature"] == 0 and body["frequency_penalty"] == 0
            assert body["top_p"] is None and "max_tokens" not in body
            assert log["sampler"] == {"temperature": 0.0, "frequency_penalty": 0.0}
            assert log["tokens"]["max"] == 0
            completion = plain.create_llm(
                extra_params={"max_completion_tokens": 256})
            completion_log = logged_queue_result(completion)
            assert BODIES[-1]["max_completion_tokens"] == 256
            assert completion_log["tokens"]["max"] == 256
            invalid_limit = plain.create_llm(extra_params={"max_tokens": ""})
            assert llm_logger.get_max_tokens(invalid_limit) == 0
            assert provider_queue._get_max_tokens_safe(invalid_limit) == 0

            # Positive replay values keep the selected entry's body overrides.
            # A zero output limit alone removes the saved body limit.
            assert source["sampler"]["temperature"] == 0.0
            identifier = llm_log_replay.entry_id(source)
            rows = [source]

            def replay_submit(**kwargs):
                rows.append(logged_queue_result(kwargs["llm"]))

            replay_manager = SimpleNamespace(get_provider=manager.get_provider,
                                             get_queue_for_provider=lambda name: SimpleNamespace(
                                                 submit=replay_submit))
            with patch("app.core.provider_manager.get_provider_manager",
                       return_value=replay_manager), patch.object(
                       llm_log_replay, "read_entries", side_effect=lambda path: rows):
                comparison = llm_log_replay.replay_entry(
                    Path(folder) / "unused", entry_id=identifier, provider="P", model="test",
                    temperature=0.3, max_tokens=32, top_p=0.4, frequency_penalty=0.2)
                assert {key: BODIES[-1][key] for key in saved} == saved
                assert comparison["sampler"] == source["sampler"]
                assert comparison["tokens"]["max"] == BODIES[-1]["max_tokens"] == 257
                unlimited = llm_log_replay.replay_entry(
                    Path(folder) / "unused", entry_id=identifier, provider="P", model="test",
                    temperature=0, max_tokens=0)
                assert "max_tokens" not in BODIES[-1]
                assert unlimited["tokens"]["max"] == 0
                assert unlimited["sampler"] == source["sampler"]
                assert {key: BODIES[-1][key] for key in (
                    "temperature", "top_p", "frequency_penalty", "repetition_penalty")} == {
                        key: saved[key] for key in (
                            "temperature", "top_p", "frequency_penalty", "repetition_penalty")}
                assert entry["extra_params"] == saved
                entry["extra_params"] = {"max_completion_tokens": 256}
                without_limit = llm_log_replay.replay_entry(
                    Path(folder) / "unused", entry_id=identifier, provider="P", model="test",
                    temperature=0, max_tokens=0)
                assert "max_completion_tokens" not in BODIES[-1]
                assert "max_tokens" not in BODIES[-1]
                assert without_limit["tokens"]["max"] == 0
                entry["extra_params"] = saved

        anth_wire = httpx2.MockTransport(anthropic_transport)
        anth_sync, anth_async = anthropic.Anthropic, anthropic.AsyncAnthropic
        with patch.object(anthropic, "Anthropic", side_effect=lambda **kw: anth_sync(
                **kw, http_client=httpx2.Client(transport=anth_wire))), patch.object(
                anthropic, "AsyncAnthropic", side_effect=lambda **kw: anth_async(
                    **kw, http_client=httpx2.AsyncClient(transport=anth_wire))):
            anthropic_client = llm_router.AnthropicLLMClient(
                "test", "test-key", "https://mock.test/v1", temperature=0.6,
                max_tokens=400, extra_params={"temperature": 0, "max_tokens": 80})
            for log, body in ((logged_queue_result(anthropic_client), BODIES[-1]),
                              (asyncio.run(logged_stream_result(anthropic_client)), BODIES[-1])):
                assert body["temperature"] == log["sampler"]["temperature"] == 0
                assert body["max_tokens"] == log["tokens"]["max"] == 80

    print("LLM metadata: serialized sync/stream, queue log and replay controls OK")


if __name__ == "__main__":
    main()
