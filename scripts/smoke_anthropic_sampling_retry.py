"""Smoke: the Anthropic client drops removed sampling parameters after one 400.

Usage:
    ./.venv/bin/python scripts/smoke_anthropic_sampling_retry.py

No network, no world. Current Claude models answer a request that carries
`temperature` with 400 "`temperature` is deprecated for this model." (Anthropic
docs, "Model deprecations" -> "API parameter deprecations"); older models still
accept it. Expected by hand from that rule:

  A  model that rejects sampling, invoke():  2 sends — first with temperature
     (rejected), second without; the reply text arrives.
  B  same model again:                       1 send, without temperature.
  C  model that accepts sampling:             1 send, WITH temperature 0.7.
  D  astream() on a rejecting model:          2 opens, text yielded once.
  E  a 400 that is NOT about sampling:        raised, 1 send, nothing learned.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import llm_client  # noqa: E402
from app.core.llm_client import AnthropicLLMClient  # noqa: E402


class FakeBadRequest(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.status_code = 400
        self.message = message


class Block:
    def __init__(self, text):
        self.text = text


class Resp:
    def __init__(self, text):
        self.content = [Block(text)]
        self.usage = None
        self.stop_reason = "end_turn"


def install(client, rejects, sends, other_error=None):
    def create(**kw):
        sends.append(dict(kw.get("extra_body") or {}))
        if other_error:
            raise FakeBadRequest(other_error)
        if rejects and "temperature" in (kw.get("extra_body") or {}):
            raise FakeBadRequest("`temperature` is deprecated for this model.")
        return Resp("hello")

    class Stream:
        def __init__(self, kw):
            self.kw = kw

        async def __aenter__(self):
            sends.append(dict(self.kw.get("extra_body") or {}))
            if rejects and "temperature" in (self.kw.get("extra_body") or {}):
                raise FakeBadRequest("`temperature` is deprecated for this model.")
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield "hel"
                yield "lo"
            return gen()

        async def get_final_message(self):
            return Resp("hello")

    client._sync.messages.create = create
    client._async.messages.stream = lambda **kw: Stream(kw)


def make(model):
    return AnthropicLLMClient(model=model, api_key="x", temperature=0.7)


failures = []


def check(name, cond, detail):
    print(("OK  " if cond else "FAIL"), name, detail)
    if not cond:
        failures.append(name)


llm_client._anthropic_no_sampling.clear()
msgs = [{"role": "user", "content": "hi"}]

# A
sends = []
c = make("rejecting-model")
install(c, True, sends)
r = c.invoke(msgs)
check("A", len(sends) == 2 and "temperature" in sends[0] and "temperature" not in sends[1]
      and r.content == "hello", sends)

# B
sends = []
c = make("rejecting-model")
install(c, True, sends)
r = c.invoke(msgs)
check("B", len(sends) == 1 and "temperature" not in sends[0] and r.content == "hello", sends)

# C
sends = []
c = make("accepting-model")
install(c, False, sends)
c.invoke(msgs)
check("C", len(sends) == 1 and sends[0].get("temperature") == 0.7, sends)

# D
sends = []
c = make("rejecting-stream-model")
install(c, True, sends)


async def collect():
    return "".join([ch.content async for ch in c.astream(msgs)])


text = asyncio.run(collect())
check("D", len(sends) == 2 and text == "hello", (sends, text))

# E
sends = []
c = make("other-error-model")
install(c, False, sends, other_error="max_tokens: too large")
try:
    c.invoke(msgs)
    raised = False
except FakeBadRequest:
    raised = True
check("E", raised and len(sends) == 1
      and (c.base_url, "other-error-model") not in llm_client._anthropic_no_sampling, sends)

print("FAILED:" if failures else "ALL OK", failures or "")
sys.exit(1 if failures else 0)
