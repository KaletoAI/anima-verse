#!/usr/bin/env python3
"""Embeddings under load: the model never switches, the wait is bounded.

Usage:
    ./.venv/bin/python scripts/smoke_embedding_under_load.py

Review 11 (embedding part of #1): with ``embedding.backend = auto`` the
external-vs-internal choice went through ``resolve_llm``, which skips a
provider whose request quota is full. A busy provider therefore turned
``current_model_id()`` into ``internal:<model>`` and ``embed()`` answered with
the built-in model's vector. A failed external call (an HTTP 429, say) also
fell back to the internal model inside ``embed()``, while the caller had
already stamped the vector with the external id. Vectors of two models were
compared and stored under the wrong stamp.

Now the routing lookup for embeddings ignores the quota
(``resolve_llm(..., consult_quota=False)``). A request looks at the quota but
books no slot (as before), a full window or a 429 waits up to
``embedding.max_wait_seconds``, and a call that gives up returns ``None``. A caller that stamps can pin ``embed`` to its
stamp (``model_id=`` / ``embedder_for``).

Runs without the server, a world or a network: ``httpx.post`` is a fake,
``time.sleep`` inside ``embedding`` only advances the quota's fake clock, and
the internal model is a stub that answers ``[9.0]`` so that any use of it is
visible.

EXPECTATIONS, DERIVED BY HAND (provider E: capacity 1 per 60 s, budget 5 s,
external vector [1.0, 0.0])

[1] Idle, t=0: model id ``external:emb-model``. embed() posts once and
    answers [1.0, 0.0]. used=0: embeddings book nothing.
[2] Another caller sends at t=0 and fills the window. The send frees at 60,
    a wait of 60 > 5.
    Model id stays ``external:emb-model`` and the effective backend stays
    ``external``. embed() answers None with no post and no internal call, and
    nothing is slept. embed_many(["a", "b"]) answers [None, None], also
    without the internal model.
    Old code: ``internal:BAAI/bge-small-en-v1.5`` and [9.0].
[3] t=56: the wait is 60-56 = 4 <= 5. embed() sleeps 4 (clock -> 60), posts
    and answers [1.0, 0.0]. Slept [4.0], used=0 (the send at 0 expired at 60,
    the embedding booked nothing).
[4] A provider without a local quota (capacity 0), t=200.
    a) The first post gets 429 with Retry-After 3. The key is blocked until
       203, 3 <= 5: sleep 3, the second post answers. Two posts, slept [3.0].
    b) The clock is at 203 after the [4a] sleep. Retry-After 7 blocks the key
       until 210, and 7 > 5: one post, nothing slept, None, and the internal
       model is not used.
[5] On an event loop the budget is 0. With E's window full (t=0 send
    pattern repeated at t=1000: send at 1000, embed at 1056, wait 4) the
    call answers None at once and sleeps nothing.
[6] Pinning. With E routed, embed("x", model_id="external:other") answers
    None without a post. embedder_for("external:emb-model") answers the
    vector. embedder_for(<id>, double) returns the double itself, and
    embed_map(["a"], model_id="internal:x") is {}.
[7] Router flag. With E's window full: resolve_llm(reserve=False) is None
    (the old lookup), consult_quota=False picks E, used is unchanged by both,
    and consult_quota=False together with reserve=True raises ValueError.
[8] Health is not load: E unavailable makes auto fall back to the built-in
    model id, as before (an outage, not a busy provider).

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import asyncio
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ["STORAGE_DIR"] = _tmp.name
os.environ["INSTANCE_DIR"] = _tmp.name
from app.core import paths  # noqa: E402

paths.init(_tmp.name)

import httpx  # noqa: E402

from app.core import config, embedding  # noqa: E402
from app.core import llm_router as router  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_quota import ProviderQuota  # noqa: E402
from app.models import world as world_model  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


now = [0.0]
slept = []
posts = []
internal_calls = []
plan = []          # queued fake answers: ("ok",) or ("429", retry_after)
EXT = [1.0, 0.0]


def fake_sleep(seconds):
    slept.append(seconds)
    now[0] += seconds


def fake_post(url, json=None, headers=None, timeout=None):
    posts.append(json)
    req = httpx.Request("POST", url)
    step = plan.pop(0) if plan else ("ok",)
    if step[0] == "429":
        return httpx.Response(429, headers={"Retry-After": str(step[1])}, request=req)
    inputs = json["input"]
    data = ([{"index": i, "embedding": EXT} for i in range(len(inputs))]
            if isinstance(inputs, list) else [{"index": 0, "embedding": EXT}])
    return httpx.Response(200, json={"data": data}, request=req)


def internal_many(texts):
    internal_calls.append(list(texts))
    return [[9.0] for _ in texts]


E = Provider("E", "openai", "http://emb/v1", "demo", available=True,
             rate_limit_requests=1, quota=ProviderQuota(1, 60, clock=lambda: now[0]))
F = Provider("F", "openai", "http://emb-free/v1", "demo", available=True,
             rate_limit_requests=0, quota=ProviderQuota(0, 60, clock=lambda: now[0]))
providers = {"E": E, "F": F}
routing = [{"provider": "E", "model": "emb-model",
            "tasks": [{"task": "pose_embedding", "order": 1}]}]
settings = {"backend": "auto", "max_wait_seconds": 5}


def live_config(key, default=None):
    return settings if key == "embedding" else default


def reset():
    slept.clear()
    posts.clear()
    internal_calls.clear()
    plan.clear()


with ExitStack() as stack:
    stack.enter_context(patch.object(router, "_load_routing", side_effect=lambda: routing))
    stack.enter_context(patch.object(router, "get_provider_manager",
                                     return_value=NS(get_provider=providers.get)))
    stack.enter_context(patch.object(router, "disabled_providers", return_value=set()))
    stack.enter_context(patch.object(router, "_model_cooled_down", return_value=False))
    stack.enter_context(patch("app.core.llm_task_state.is_enabled", return_value=True))
    stack.enter_context(patch.object(config, "get", side_effect=live_config))
    stack.enter_context(patch.object(world_model, "get_world_setting",
                                     side_effect=lambda key, default="": ""))
    stack.enter_context(patch.object(httpx, "post", fake_post))
    stack.enter_context(patch.object(embedding.time, "sleep", fake_sleep))
    stack.enter_context(patch.object(embedding, "_embed_internal_many", internal_many))

    print("[1] idle provider")
    now[0] = 0.0
    reset()
    check("model id", embedding.current_model_id(), "external:emb-model")
    check("vector", embedding.embed("x"), EXT)
    check("one post", len(posts), 1)
    check("used = 0 (books nothing)", E.quota.used, 0)

    print("\n[2] full window, wait 60 > budget 5")
    reset()
    E.quota.send()
    check("model id unchanged", embedding.current_model_id(), "external:emb-model")
    check("effective backend", embedding.effective_backend(), "external")
    check("embed -> None", embedding.embed("x"), None)
    check("embed_many -> all None", embedding.embed_many(["a", "b"]), [None, None])
    check("no post", len(posts), 0)
    check("internal model never used", internal_calls, [])
    check("nothing slept", slept, [])

    print("\n[3] wait 4 <= budget 5")
    now[0] = 56.0
    reset()
    check("vector after the wait", embedding.embed("x"), EXT)
    check("slept", slept, [4.0])
    check("clock", now[0], 60.0)
    check("one post", len(posts), 1)
    check("used = 0 at t=60", E.quota.used, 0)

    print("\n[4] HTTP 429 on a provider without a local quota")
    routing[0]["provider"] = "F"
    now[0] = 200.0
    reset()
    plan.extend([("429", 3), ("ok",)])
    check("a) vector after Retry-After 3", embedding.embed("x"), EXT)
    check("a) two posts", len(posts), 2)
    check("a) slept", slept, [3.0])
    reset()
    plan.extend([("429", 7)])
    check("b) Retry-After 7 > 5 -> None", embedding.embed("x"), None)
    check("b) one post", len(posts), 1)
    check("b) nothing slept", slept, [])
    check("b) internal model never used", internal_calls, [])
    routing[0]["provider"] = "E"

    print("\n[5] on an event loop nothing waits")
    now[0] = 1000.0
    E.quota.send()
    now[0] = 1056.0
    reset()

    async def on_loop():
        return embedding.embed("x")

    check("None at once", asyncio.run(on_loop()), None)
    check("nothing slept", slept, [])
    check("no post", len(posts), 0)

    print("\n[6] pinning to the caller's model id")
    now[0] = 2000.0
    reset()
    check("other id -> None", embedding.embed("x", model_id="external:other"), None)
    check("no post for it", len(posts), 0)
    check("pinned to the routed id", embedding.embedder_for("external:emb-model")("x"), EXT)
    double = lambda text: [7.0]  # noqa: E731
    check("a double stays itself", embedding.embedder_for("external:emb-model", double) is double, True)
    check("embed_map under another id", embedding.embed_map(["a"], model_id="internal:x"), {})

    print("\n[7] router flag consult_quota")
    now[0] = 3000.0
    E.quota.send()
    used = E.quota.used
    check("old lookup skips the full provider",
          router.resolve_llm("pose_embedding", reserve=False), None)
    inst = router.resolve_llm("pose_embedding", reserve=False, consult_quota=False)
    check("consult_quota=False picks E", getattr(inst, "provider_name", None), "E")
    check("lookups book nothing", E.quota.used, used)
    try:
        router.resolve_llm("pose_embedding", consult_quota=False)
        raised = False
    except ValueError:
        raised = True
    check("reserve + consult_quota=False raises", raised, True)

    print("\n[8] an unavailable provider is an outage, not load")
    E.available = False
    check("auto -> built-in id", embedding.current_model_id(),
          "internal:" + embedding.DEFAULT_INTERNAL_MODEL)
    E.available = True

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("PASS: embeddings keep their model under load and wait within the budget")
