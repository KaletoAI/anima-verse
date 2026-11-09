#!/usr/bin/env python3
"""Smoke: a provider's "Parameters when thinking is off" reach every call
without thinking, and a judge answer cut off at the token limit says so.

Usage: ./.venv/bin/python scripts/smoke_thinking_off_params.py

No server, no network, no world DB (storage and instance point at temp dirs).

Why (measured 2026-11-10): Venice rejects chat_template_kwargs with a 400,
LLMClient retries without it, and nothing switched the reasoning of
deepseek-v4-1-flash-uncensored off — 1256..1500 of the RP judge's 1500
tokens were reasoning, the JSON never arrived. With
venice_parameters.disable_thinking the same request took ~300 tokens.

Expectations, from LLMClient._build_kwargs (thinking_off_params merged after
the default switch, the entry's extra_params merged last):
[1] thinking off + provider params {"venice_parameters": {"disable_thinking":
    true}} -> extra_body has them AND chat_template_kwargs.enable_thinking=false.
[2] thinking on -> no venice_parameters in extra_body.
[3] the entry's extra_params {"venice_parameters": {"disable_thinking": false}}
    win over the provider's value (false).
[4] once the endpoint rejected chat_template_kwargs, that key is gone and the
    provider's params stay.
[5] LLMInstance.create_llm stamps the provider's params on the client.
[6] ProviderManager.provider_for_test reads the field from the config entry; a
    malformed value ("[1]", not an object) becomes {}.
[7] the settings save rejects a malformed value and names the provider.
[8] rp_test.ask_judge: an unparseable answer with finish_reason "length" and
    1256 reasoning tokens raises "cut off at the token limit (1256 of 1500
    tokens were reasoning ...)"; without "length" the old message stays.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths
paths.init(tempfile.mkdtemp(prefix="smoke_thinking_off_world_"))
paths.init_instance(tempfile.mkdtemp(prefix="smoke_thinking_off_instance_"))

from app.core import config, llm_client
from app.core.llm_client import LLMClient
from app.core.llm_router import LLMInstance
from app.core.provider import Provider

VENICE = {"venice_parameters": {"disable_thinking": True}}


def body(client, thinking=None):
    return client._build_kwargs(thinking=thinking).get("extra_body", {})


def make(**kw):
    client = LLMClient(model="m1", api_key="k", api_base="http://smoke.invalid/v1", **kw)
    client.thinking_off_params = dict(VENICE)
    return client


extra = body(make(thinking=False))
assert extra.get("venice_parameters") == {"disable_thinking": True}, extra
assert extra.get("chat_template_kwargs") == {"enable_thinking": False}, extra
print("[1] thinking off sends the provider's parameters — PASS")

assert "venice_parameters" not in body(make(thinking=True)), "[2]"
print("[2] thinking on leaves them out — PASS")

extra = body(make(thinking=False, extra_params={"venice_parameters": {"disable_thinking": False}}))
assert extra["venice_parameters"] == {"disable_thinking": False}, extra
print("[3] the entry's extra parameters win — PASS")

llm_client._NO_CHAT_TEMPLATE_KWARGS.add(("http://smoke.invalid/v1", "m1"))
extra = body(make(thinking=False))
assert "chat_template_kwargs" not in extra and extra["venice_parameters"] == {"disable_thinking": True}, extra
print("[4] a rejected chat_template_kwargs does not take them along — PASS")

provider = Provider(name="Ven", type="openai", api_base="http://smoke2.invalid/v1", api_key="k",
                    thinking_off_params=dict(VENICE))
client = LLMInstance(provider_name="Ven", model="m2", _provider=provider).create_llm(thinking=False)
assert client.thinking_off_params == VENICE, client.thinking_off_params
assert body(client)["venice_parameters"] == {"disable_thinking": True}
print("[5] create_llm hands them to the client — PASS")

from app.core.provider_manager import ProviderManager
ENTRIES = [
    {"name": "Ven", "type": "openai", "api_base": "http://127.0.0.1:9/v1", "thinking_off_params": VENICE},
    {"name": "Bad", "type": "openai", "api_base": "http://127.0.0.1:9/v1", "thinking_off_params": "[1]"},
]
real_get = config.get
config.get = lambda key, *a: ENTRIES if key == "providers" else real_get(key, *a)
pm = ProviderManager.__new__(ProviderManager)
pm.providers = {}
pm._configure_quota = lambda provider: None
assert pm.provider_for_test("Ven").thinking_off_params == VENICE, "[6] Ven"
assert pm.provider_for_test("Bad").thinking_off_params == {}, "[6] Bad"
print("[6] the provider reads the field; a malformed value is dropped — PASS")

from app.routes.admin_settings import _validate_provider_json
assert _validate_provider_json([{"name": "Ven", "thinking_off_params": VENICE}]) == ""
err = _validate_provider_json([{"name": "Bad", "thinking_off_params": "[1]"}])
assert err.startswith("LLM Providers: Bad: thinking_off_params"), err
print("[7] the settings save rejects a malformed value — PASS")

from app.core import rp_test


def judge_call(finish, reasoning):
    return lambda messages: {"content": '{"answers": {"q1": {"answer": "ye', "finish_reason": finish,
                             "reasoning_tokens": reasoning, "completion_tokens": 1500}


try:
    rp_test.ask_judge(judge_call("length", 1256), "s", "u", ["q1"])
    raise AssertionError("[8] no error")
except rp_test.JudgeError as exc:
    assert "cut off at the token limit (1256 of 1500 tokens were reasoning" in str(exc), exc
try:
    rp_test.ask_judge(judge_call("stop", None), "s", "u", ["q1"])
    raise AssertionError("[8] no error")
except rp_test.JudgeError as exc:
    assert str(exc) == "judge answer is not the expected JSON", exc
print("[8] a judge answer cut off at the limit names the reasoning — PASS")
print("ALL OK")
