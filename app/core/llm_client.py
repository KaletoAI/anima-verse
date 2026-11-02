"""LLM client — replaces LangChain ChatOpenAI with the OpenAI Python SDK.

Provides:
- LLMClient: holds the config (model, api_key, …) and offers invoke() + astream()
- AnthropicLLMClient: client for Anthropic Claude models (native SDK)
- LLMResponse: answer wrapper with .content, .usage and .finish_reason
- LLMChunk: streaming chunk with .content (the terminal one carries
  .finish_reason and .usage)
- usage_from_openai(): normalises a provider's usage report, prompt-cache
  hits included, into one dict shape
- to_openai_messages(): converts dicts/legacy objects into the OpenAI format
"""
from contextlib import contextmanager
import asyncio
import time
import openai
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("llm_client")

# --- 503 "busy" retry (gateway at its parallel-call limit) -------------------
# A 503 means the backend is momentarily busy, not broken — so we wait and retry
# the SAME model (config: llm_retry.*) instead of cooling the provider down and
# switching the routing fallback. Other 5xx / connection errors are NOT busy and
# keep the existing cooldown+fallback path in llm_router.
_BUSY_TEXT_MARKERS = ("503", "service unavailable", "overloaded")

# A 503 normally means "busy" → retry the SAME model. But some gateways return
# 503 with a body like {'detail': "No healthy backend for model 'X'"} when the
# model has no servable backend on this provider at all — retrying the same
# model is pointless. These are NOT busy: they must fall through to the routing
# fallback (cooldown + next provider), see llm_router._is_upstream_failure.
_NO_BACKEND_MARKERS = (
    "no healthy backend",
    "no healthy upstream",
    "no available backend",
    "no backend available",
)


def _is_no_backend_error(err: BaseException) -> bool:
    """True for gateway errors meaning 'this model has no servable backend'.

    Distinct from a transient 'busy' 503: the provider cannot serve the model at
    all, so the only useful reaction is to cool it down and try the next provider
    in the routing chain — never retry the same model.
    """
    msg = str(err).lower()
    return any(m in msg for m in _NO_BACKEND_MARKERS)


def _is_busy_error(err: BaseException) -> bool:
    """True only for a real 'busy' signal (HTTP 503 / Service Unavailable).

    A 503 whose body says there is no healthy backend for the model is NOT busy
    (see _is_no_backend_error) — we let it fall through to the routing fallback
    instead of retrying the same dead model with backoff.
    """
    if _is_no_backend_error(err):
        return False
    if getattr(err, "status_code", None) == 503:
        return True
    msg = str(err).lower()
    return any(m in msg for m in _BUSY_TEXT_MARKERS)


def _busy_retry_policy() -> Tuple[int, float]:
    """(max_attempts, base_delay_seconds) from config, with safe defaults."""
    try:
        from app.core import config
        attempts = int(config.get("llm_retry.busy_max_attempts", 3))
        base = float(config.get("llm_retry.busy_base_delay_seconds", 10))
        return max(0, attempts), max(0.0, base)
    except Exception:
        return 3, 10.0


def _busy_delay(base: float, attempt: int) -> float:
    """Exponential backoff, 1-based attempt (1→base, 2→2·base, …), capped 120s."""
    return min(base * (2 ** (attempt - 1)), 120.0)


def _warn_if_cut_off(mode: str, model: str, finish: Optional[str]) -> None:
    """Warns about a non-"stop" finish reason — the one wording both paths use.

    Streaming and non-streaming calls must produce the SAME message shape, so a
    grep for ``finish_reason=`` in main.log finds every truncated answer no
    matter which path produced it. ``mode`` labels the path ("Call" / "Stream").

    An unknown reason (``None``) stays silent: the provider said nothing, which
    is not evidence of truncation. "length" = the completion budget was hit
    (thinking models burn hidden reasoning tokens from the same budget; some
    providers silently CLAMP an oversized max_tokens first).
    """
    if not finish or finish == "stop":
        return
    logger.warning("%s on %s ended with finish_reason=%r — output likely "
                   "truncated (length = max_tokens/budget hit)",
                   mode, model, finish)


@dataclass
class LLMResponse:
    """Wrapper for LLM answers (replacement for the LangChain AIMessage)."""
    content: str
    # {"prompt_tokens": N, "completion_tokens": N[, "cached_tokens": N]} —
    # see usage_from_openai for what an absent "cached_tokens" means.
    usage: Optional[Dict[str, int]] = None
    # Why the provider stopped generating, in the OpenAI vocabulary
    # ("stop" = finished on its own, "length" = completion budget hit and the
    # text is cut off mid-sentence, "content_filter", …). ``None`` means the
    # provider sent no reason — NOT that the answer is complete. Never guess a
    # value here: a fabricated "stop" would claim a completeness nobody checked.
    finish_reason: Optional[str] = None
    reasoning: Optional[str] = None
    budget_hit: bool = False
    budget_unenforceable: bool = False
    # A budgeted call whose continuation wrote on to the token limit.
    budget_overrun: bool = False


@dataclass
class LLMChunk:
    """A single streaming chunk.

    A chunk carries EITHER text or the terminal markers — never both.
    ``astream`` appends exactly ONE contentless terminal chunk when the provider
    named a reason or reported usage, because both are only known after the
    last token. Every consumer already skips chunks without content, so the
    marker adds no character to any assembled answer and never reaches the
    browser; consumers that want the reason or the usage read them before that
    skip. ``usage`` has the shape of ``LLMResponse.usage``.
    """
    content: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


def _field(obj: Any, name: str) -> Any:
    """Reads ``name`` from an SDK model or a plain dict alike.

    The OpenAI SDK keeps fields the schema does not know (llama.cpp's
    ``timings``, a gateway's ``cache_read_input_tokens``) as extra attributes,
    while nested extras arrive as plain dicts — one accessor for both.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _as_count(value: Any) -> Optional[int]:
    """A token count as int, or None when the value is missing or not a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def usage_from_openai(usage: Any, timings: Any = None) -> Optional[Dict[str, int]]:
    """Normalises an OpenAI-compatible usage report into the LLMResponse shape.

    ``cached_tokens`` (prompt tokens the backend served from its prefix/KV
    cache) is read from whichever field the backend fills, first match wins:

    1. ``usage.prompt_tokens_details.cached_tokens`` — OpenAI, vLLM (with
       prompt-token details on), LiteLLM, current llama.cpp
    2. ``usage.cache_read_input_tokens`` — Anthropic vocabulary passed through
       by a gateway
    3. ``timings.cache_n`` — llama.cpp's own timing block

    The key is left OUT when none of them is present. That is not "0 cached":
    the backend behind the gateway is not ours to choose, and one that reports
    nothing must stay distinguishable from one that reports a cold cache.
    Reasoning tokens come from completion_tokens_details.reasoning_tokens;
    the key is left OUT when absent, just like cached_tokens.
    Returns None when there is no usage and no timings at all.
    """
    if usage is None and timings is None:
        return None
    out: Dict[str, int] = {
        "prompt_tokens": _as_count(_field(usage, "prompt_tokens")) or 0,
        "completion_tokens": _as_count(_field(usage, "completion_tokens")) or 0,
    }
    cached = _as_count(_field(_field(usage, "prompt_tokens_details"), "cached_tokens"))
    if cached is None:
        cached = _as_count(_field(usage, "cache_read_input_tokens"))
    if cached is None:
        cached = _as_count(_field(timings, "cache_n"))
    if cached is not None:
        out["cached_tokens"] = cached
    reasoning = _as_count(_field(_field(usage, "completion_tokens_details"), "reasoning_tokens"))
    if reasoning is not None:
        out["reasoning_tokens"] = reasoning
    return out


# Thought tags of the budget forcing in LLMClient.invoke: Qwen-family,
# SenseNova, Nanbeige, Groot and DeepSeek think in these; a model with a
# different thought format (Gemma 4) uses its channel markers.
THINK_OPEN = "<think>\n"
THINK_CLOSE = "\n</think>\n\n"
# (base_url, model) pairs that could not continue a capped thought (400/422
# or an empty answer); budgeted calls then run without thinking. A continuation
# that writes on to the token limit is NOT such a failure: measured on Gemma 4
# (llama.cpp) and Qwen3.5 (vLLM), a model sometimes answers and then keeps
# thinking aloud in the answer — that one call is cut off (finish "length",
# ``budget_overrun``), the next may be fine.
_NO_CONTINUE: set = set()
# (base_url, model) pairs whose server refused ``stream_options``. The OpenAI
# SDK only sends the final usage chunk on request, and a strict or older
# OpenAI-compatible server may answer that field with a 400 — such a server
# then streams without usage instead of not streaming at all.
_NO_STREAM_USAGE: set = set()
# (base_url, model) pairs whose server refused ``chat_template_kwargs``.
_NO_CHAT_TEMPLATE_KWARGS: set = set()


def _rejects_stream_options(err: BaseException) -> bool:
    """True when a 400/422 names ``stream_options`` as the unaccepted field."""
    status = getattr(err, "status_code", None)
    return status in (400, 422) and "stream_options" in str(err).lower()


def _is_gemma_model(model_name: str) -> bool:
    """Check if a model is Gemma-based (has reasoning that should be disabled for tool tasks)."""
    lower = model_name.lower()
    return "gemma" in lower


def merge_extra_params(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge JSON bodies, with override values winning and neither input mutated."""
    if not base:
        return deepcopy(overrides)
    result = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_extra_params(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result

def _merge_sdk_dict_fields(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Keep SDK-provided nested fields when extra_body overrides their parent."""
    extra_body = kwargs.get("extra_body")
    if extra_body:
        for key, value in extra_body.items():
            if isinstance(value, dict) and isinstance(kwargs.get(key), dict):
                extra_body[key] = merge_extra_params(kwargs[key], value)
    return kwargs


@contextmanager
def _quota_attempt(client, *, count=True):
    """One counted HTTP send, including retries, streaming and continuations."""
    quota = getattr(client, "provider_quota", None)
    if count and quota is not None:
        quota.send(getattr(client, "quota_reservation", None))
    try:
        yield
    except Exception as exc:
        if quota is not None:
            quota.exhaust(exc)
        raise


class LLMClient:
    """Replaces ChatOpenAI — holds the config and offers invoke() + astream().

    Attributes stay compatible with existing getattr() accesses:
    - model_name, model (model name)
    - openai_api_base, base_url (API URL)
    - max_tokens, temperature, request_timeout
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        request_timeout: int = 120,
        chat_template: Optional[str] = None,
        frequency_penalty: Optional[float] = None,
        top_p: Optional[float] = None,
        repetition_penalty: Optional[float] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        thinking: bool = False,
        thinking_budget: Optional[int] = None):
        self.model = model
        self.model_name = model
        # Whether the task this client serves may think (llm_tasks "thinking"
        # flag). False switches a template-thinking model's reasoning off.
        self.thinking_budget = thinking_budget
        self.thinking = bool(thinking)
        self.openai_api_key = api_key
        self.openai_api_base = api_base
        self.base_url = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        # Optional Jinja chat_template — passed through extra_body when the
        # provider's tokenizer has no default template (e.g. some Infermatic
        # finetunes that error with "no chat template" since transformers v4.44).
        self.chat_template = chat_template or None
        # Token frequency penalty (anti-repetition). None = do not send it,
        # the server default applies. E.g. 0.3 for a light, 0.6 for a strong
        # penalty.
        self.frequency_penalty = frequency_penalty
        # Nucleus sampling cut-off. None = do not send it, so the provider
        # default (usually 1.0 = the whole distribution) stays untouched.
        # Without it every temperature increase lifts the least likely tokens
        # the most — that is how a raised temperature turns into script salad.
        self.top_p = top_p
        # vLLM-style repetition penalty (1.0 = neutral), sent via extra_body
        # because it is not an OpenAI parameter. Unlike frequency_penalty it
        # also counts the PROMPT tokens, so it is what reaches a reply copied
        # from the history. None = do not send it (the routing entry has none).
        self.repetition_penalty = repetition_penalty
        self.extra_params = deepcopy(extra_params) if extra_params else {}

        client_kwargs = {
            "api_key": api_key,
            "base_url": api_base,
            "timeout": float(request_timeout),
            # The OpenAI SDK retries 2× internally by default — on a hung/slow
            # backend that silently turns one request_timeout into THREE
            # (e.g. 3×120s = 6min for a tiny call), and it fights our own
            # busy-retry / routing-fallback layers. We do all retrying
            # explicitly, so disable the SDK's hidden retries.
            "max_retries": 0,
        }
        self._sync = openai.OpenAI(**client_kwargs)
        self._async = openai.AsyncOpenAI(**client_kwargs)

    def _build_kwargs(self, thinking: Optional[bool] = None) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
        }
        if self.frequency_penalty is not None:
            kwargs["frequency_penalty"] = float(self.frequency_penalty)
        if self.top_p is not None:
            kwargs["top_p"] = float(self.top_p)
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        extra_body: Dict[str, Any] = {}
        # Measured on SGLang, vLLM and llama.cpp: all honour
        # chat_template_kwargs.enable_thinking, regardless of model family.
        thinks = self.thinking if thinking is None else thinking
        if not thinks:
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
            if _is_gemma_model(self.model):
                extra_body["thinking"] = {"type": "disabled"}
        if self.chat_template:
            extra_body["chat_template"] = self.chat_template
        if self.repetition_penalty is not None:
            extra_body["repetition_penalty"] = float(self.repetition_penalty)
        # The SDK overlays extra_body onto these top-level kwargs when it
        # serializes the request; log metadata must use that same precedence.
        if self.extra_params:
            extra_body = merge_extra_params(extra_body, self.extra_params)
        if (self.base_url, self.model) in _NO_CHAT_TEMPLATE_KWARGS:
            extra_body.pop("chat_template_kwargs", None)
        if extra_body:
            kwargs["extra_body"] = extra_body
        return _merge_sdk_dict_fields(kwargs)

    def _retry_without_chat_template_kwargs(self, err, kwargs) -> bool:
        """Remember strict servers and remove only the rejected template field."""
        body = kwargs.get("extra_body", {})
        if (getattr(err, "status_code", None) not in (400, 422)
                or "chat_template_kwargs" not in str(err).lower()
                or "chat_template_kwargs" not in body):
            return False
        key = (self.base_url, self.model)
        if key not in _NO_CHAT_TEMPLATE_KWARGS:
            logger.warning("%s @ %s refuses chat_template_kwargs — omitting it from now on",
                           self.model, self.base_url)
            _NO_CHAT_TEMPLATE_KWARGS.add(key)
        body.pop("chat_template_kwargs")
        return True

    def _request(self, openai_msgs, kwargs, *, warn_cutoff=True) -> LLMResponse:
        """One request with the existing per-request retry policy."""
        max_attempts, base = _busy_retry_policy()
        attempt = 0
        while True:
            try:
                with _quota_attempt(self):
                    resp = self._sync.chat.completions.create(
                        messages=openai_msgs, **kwargs)
                break
            except Exception as e:
                from app.core.provider_quota import is_rate_limit_error
                if is_rate_limit_error(e):
                    raise
                if self._retry_without_chat_template_kwargs(e, kwargs):
                    continue
                if not _is_busy_error(e) or attempt >= max_attempts:
                    raise
                attempt += 1
                delay = _busy_delay(base, attempt)
                logger.warning(
                    "LLM busy (503) on %s — retry %d/%d after %.0fs",
                    self.model, attempt, max_attempts, delay)
                time.sleep(delay)
        usage = usage_from_openai(resp.usage, _field(resp, "timings"))
        choice = resp.choices[0]
        finish = getattr(choice, "finish_reason", None) or None
        if warn_cutoff or finish != "length":
            _warn_if_cut_off("Call", self.model, finish)
        return LLMResponse(
            content=choice.message.content or "",
            usage=usage,
            finish_reason=finish,
            reasoning=_field(choice.message, "reasoning_content") or _field(choice.message, "reasoning"))

    def invoke(self, messages: List) -> LLMResponse:
        """Synchronous call; optionally force a thought budget before the answer."""
        msgs = to_openai_messages(messages)
        budget = self.thinking_budget
        if not (self.thinking and type(budget) is int and budget > 0):
            return self._request(msgs, self._build_kwargs())
        key = (self.base_url, self.model)

        def plain():
            kwargs = self._build_kwargs(thinking=False)
            # Fallback overrides explicit extra_params enabling thinking.
            if key not in _NO_CHAT_TEMPLATE_KWARGS:
                kwargs.setdefault("extra_body", {}).setdefault("chat_template_kwargs", {})["enable_thinking"] = False
            response = self._request(msgs, kwargs)
            response.budget_unenforceable = True
            return response

        if key in _NO_CONTINUE:
            return plain()
        kwargs = self._build_kwargs()
        kwargs["max_tokens"] = budget
        if "max_tokens" in kwargs.get("extra_body", {}):
            kwargs["extra_body"]["max_tokens"] = budget
        first = self._request(msgs, kwargs, warn_cutoff=False)
        if first.finish_reason != "length":
            return first
        thought_open, thought_close = (("<|channel>thought\n", "<channel|>")
                                      if _is_gemma_model(self.model) else (THINK_OPEN, THINK_CLOSE))
        close_marker = thought_close.strip()
        partial = first.content
        if not first.reasoning and partial.startswith(thought_open) and close_marker not in partial:
            prefill = partial.rstrip() + thought_close
            first.reasoning = partial[len(thought_open):].strip()
            partial = ""
        else:
            prefill = thought_open + (first.reasoning or "").strip() + thought_close + partial
        kwargs = self._build_kwargs()
        kwargs.setdefault("extra_body", {}).update(continue_final_message=True, add_generation_prompt=False)
        try:
            final = self._request(msgs + [{"role": "assistant", "content": prefill}], kwargs, warn_cutoff=False)
            answer = final.content or final.reasoning or ""
            if close_marker in answer:
                answer = answer.rsplit(close_marker, 1)[1]
            answer = answer.lstrip()
            if not answer.strip():
                final = None
            elif partial and not answer.startswith(partial):
                answer = partial + answer
        except Exception as exc:
            if getattr(exc, "status_code", None) not in (400, 422):
                raise
            final = None
        if final is None:
            if key not in _NO_CONTINUE:
                _NO_CONTINUE.add(key)
                logger.warning("%s @ %s cannot continue a capped thought — disabling thinking for budgeted calls",
                               self.model, self.base_url)
            final = plain()
            answer = final.content
        usage = None
        if first.usage is not None or final.usage is not None:
            usage = dict(first.usage or {})
            for name, count in (final.usage or {}).items():
                usage[name] = usage.get(name, 0) + count
        return LLMResponse(content=answer, usage=usage, finish_reason=final.finish_reason,
                           reasoning=first.reasoning, budget_hit=True,
                           budget_unenforceable=final.budget_unenforceable,
                           budget_overrun=final.finish_reason == "length")

    async def astream(self, messages: List) -> AsyncGenerator[LLMChunk, None]:
        """Async streaming generator (for the streaming.py agent loop).

        Budget forcing does not apply here; streaming callers are RP chat paths.
        Thinking/reasoning is disabled by default (tool LLM in dual mode).
        Template thinking is switched off for every model unless requested.
        """
        openai_msgs = to_openai_messages(messages)
        kwargs = self._build_kwargs()
        _usage_key = (self.base_url, self.model)
        explicit_stream_options = "stream_options" in self.extra_params
        if not explicit_stream_options and _usage_key not in _NO_STREAM_USAGE:
            kwargs["stream_options"] = {"include_usage": True}
        _merge_sdk_dict_fields(kwargs)
        max_attempts, base = _busy_retry_policy()
        attempt = 0
        # Busy-retry only around connection setup — once chunks start flowing a
        # restart would duplicate output, so a mid-stream error is never retried.
        while True:
            try:
                with _quota_attempt(self):
                    stream = await self._async.chat.completions.create(
                        messages=openai_msgs, stream=True, **kwargs)
                break
            except Exception as e:
                from app.core.provider_quota import is_rate_limit_error
                if is_rate_limit_error(e):
                    raise
                if self._retry_without_chat_template_kwargs(e, kwargs):
                    continue
                if (not explicit_stream_options and "stream_options" in kwargs
                        and _rejects_stream_options(e)):
                    logger.info("%s @ %s refuses stream_options — streaming "
                                "without usage from now on", self.model, self.base_url)
                    _NO_STREAM_USAGE.add(_usage_key)
                    kwargs.pop("stream_options")
                    continue
                if not _is_busy_error(e) or attempt >= max_attempts:
                    raise
                attempt += 1
                delay = _busy_delay(base, attempt)
                logger.warning(
                    "LLM busy (503, stream) on %s — retry %d/%d after %.0fs",
                    self.model, attempt, max_attempts, delay)
                await asyncio.sleep(delay)
        finish = ""
        usage = None
        with _quota_attempt(self, count=False):
            async for chunk in stream:
                if chunk.choices:
                    _c = chunk.choices[0]
                    if _c.delta and _c.delta.content:
                        yield LLMChunk(content=_c.delta.content)
                    if getattr(_c, "finish_reason", None):
                        finish = _c.finish_reason
                # The usage arrives on the last chunk (choices empty with
                # include_usage; llama.cpp puts its timings on the finishing one).
                _chunk_usage = usage_from_openai(_field(chunk, "usage"),
                                                 _field(chunk, "timings"))
                if _chunk_usage:
                    # Merge, never replace: the timings and the usage block may
                    # come on different chunks, and a zero from the one that does
                    # not carry a field must not wipe the other's value.
                    usage = usage or {}
                    for _k, _v in _chunk_usage.items():
                        if _v or _k not in usage:
                            usage[_k] = _v
        _warn_if_cut_off("Stream", self.model, finish)
        if finish or usage:
            # Terminal marker — contentless, see LLMChunk. The streaming path
            # bypasses the queue, so this is the ONLY way the reason and the
            # usage reach the caller's log line.
            yield LLMChunk(content="", finish_reason=finish or None, usage=usage)

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"


def to_openai_messages(messages) -> List[Dict[str, Any]]:
    """Converts message dicts or legacy objects into the OpenAI format.

    Accepts:
    - a single string: treated as one user message
    - a list of dicts: {"role": "user", "content": "..."}
    - a list of legacy objects with .type/.content attributes
    - a list of strings: every string is treated as a user message
    """
    # Treat a string as a whole (do not iterate it character by character!)
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]

    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        elif isinstance(m, str):
            result.append({"role": "user", "content": m})
        elif hasattr(m, "content"):
            # Legacy object (e.g. LangChain messages that still exist)
            role_map = {"human": "user", "ai": "assistant", "system": "system"}
            msg_type = getattr(m, "type", "human")
            role = role_map.get(msg_type, "user")
            result.append({"role": role, "content": m.content})
        else:
            result.append({"role": "user", "content": str(m)})
    return result


# ---------------------------------------------------------------------------
# Anthropic Claude Client
# ---------------------------------------------------------------------------

def _convert_openai_content_to_anthropic(content: Any) -> Any:
    """Converts OpenAI content blocks into the Anthropic format.

    OpenAI image_url -> Anthropic image (base64 or URL).
    Strings stay strings.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    result = []
    for block in content:
        if not isinstance(block, dict):
            result.append({"type": "text", "text": str(block)})
            continue
        btype = block.get("type", "")
        if btype == "text":
            result.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image_url":
            url = block.get("image_url", {}).get("url", "")
            if url.startswith("data:"):
                # data:image/jpeg;base64,<data>
                header, data = url.split(",", 1)
                media_type = header.split(":")[1].split(";")[0]
                result.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                })
            else:
                result.append({
                    "type": "image",
                    "source": {"type": "url", "url": url},
                })
        else:
            result.append({"type": "text", "text": str(block)})
    return result


def _split_anthropic_messages(
    messages) -> Tuple[str, List[Dict[str, Any]]]:
    """Splits messages into (system_prompt, conversation) for the Anthropic API.

    - system messages are extracted and joined
    - consecutive messages of the same role are merged
    - the first message must be role=user (Anthropic requirement)
    """
    openai_msgs = to_openai_messages(messages)

    system_parts: List[str] = []
    conversation: List[Dict[str, Any]] = []

    for msg in openai_msgs:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            # Always extract system content as text
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        system_parts.append(block["text"])
                    elif isinstance(block, str):
                        system_parts.append(block)
            else:
                system_parts.append(str(content))
        else:
            if role not in ("user", "assistant"):
                role = "user"
            anthropic_content = _convert_openai_content_to_anthropic(content)
            conversation.append({"role": role, "content": anthropic_content})

    # Merge consecutive equal roles (Anthropic requires alternation)
    merged: List[Dict[str, Any]] = []
    for msg in conversation:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            curr = msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n\n" + curr
            elif isinstance(prev, list) and isinstance(curr, list):
                merged[-1]["content"] = prev + curr
            elif isinstance(prev, str) and isinstance(curr, list):
                merged[-1]["content"] = [{"type": "text", "text": prev}] + curr
            elif isinstance(prev, list) and isinstance(curr, str):
                merged[-1]["content"] = prev + [{"type": "text", "text": curr}]
        else:
            merged.append(msg.copy())

    # The first message must be user
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "[Start]"})

    if not merged:
        merged = [{"role": "user", "content": ""}]

    system = "\n\n".join(system_parts) if system_parts else ""
    return system, merged


def _anthropic_usage(usage: Any) -> Optional[Dict[str, int]]:
    """Anthropic usage in the LLMResponse shape.

    Anthropic's ``input_tokens`` counts only the tokens AFTER the last cache
    breakpoint; the whole prompt is that plus the cache read and the cache
    write. ``cached_tokens`` is always present here — this API reports the
    cache read on every answer, 0 included.
    """
    if usage is None:
        return None
    cached = _as_count(_field(usage, "cache_read_input_tokens")) or 0
    written = _as_count(_field(usage, "cache_creation_input_tokens")) or 0
    return {
        "prompt_tokens": (_as_count(_field(usage, "input_tokens")) or 0) + cached + written,
        "completion_tokens": _as_count(_field(usage, "output_tokens")) or 0,
        "cached_tokens": cached,
    }


def _anthropic_finish_reason(stop_reason: Optional[str]) -> Optional[str]:
    """Maps an Anthropic ``stop_reason`` to the OpenAI ``finish_reason`` words.

    The log field must carry ONE vocabulary, otherwise counting truncated
    answers means knowing which provider wrote each line. ``end_turn`` and
    ``stop_sequence`` are the same event as OpenAI's "stop", ``max_tokens`` the
    same as "length". Anything unmapped passes through verbatim — an unknown
    reason stays visible instead of being flattened into a known one.
    """
    if not stop_reason:
        return None
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(stop_reason, stop_reason)


class AnthropicLLMClient:
    """LLM client for Anthropic Claude models (native SDK).

    Same interface as LLMClient: invoke() + astream().
    Attributes stay compatible for getattr() accesses.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str = "https://api.anthropic.com/v1",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        request_timeout: int = 120,
        extra_params: Optional[Dict[str, Any]] = None):
        import anthropic

        self.model = model
        self.model_name = model
        self.openai_api_key = api_key
        self.openai_api_base = api_base
        self.base_url = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens or 4096  # Anthropic requires max_tokens
        self.request_timeout = request_timeout
        self.extra_params = deepcopy(extra_params) if extra_params else {}

        # The SDK expects the base URL without /v1
        base = api_base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]

        self._sync = anthropic.Anthropic(
            api_key=api_key, base_url=base, timeout=float(request_timeout), max_retries=0)
        self._async = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base, timeout=float(request_timeout), max_retries=0)

    def _build_kwargs(self, system: str, msgs: List[Dict]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": self.max_tokens,
        }
        if system:
            kwargs["system"] = system
        # This Anthropic SDK has no temperature kwarg; send it through the
        # supported extra_body channel, then let explicit params override it.
        # The SDK overlays extra_body onto max_tokens as well as temperature.
        kwargs["extra_body"] = merge_extra_params(
            {"temperature": self.temperature}, self.extra_params)
        return _merge_sdk_dict_fields(kwargs)

    def invoke(self, messages: List) -> LLMResponse:
        """Synchronous LLM call."""
        system_msg, msgs = _split_anthropic_messages(messages)
        with _quota_attempt(self):
            resp = self._sync.messages.create(**self._build_kwargs(system_msg, msgs))

        content = ""
        for block in resp.content:
            if hasattr(block, "text"):
                content += block.text

        usage = _anthropic_usage(resp.usage)
        finish = _anthropic_finish_reason(getattr(resp, "stop_reason", None))
        _warn_if_cut_off("Call", self.model, finish)
        return LLMResponse(content=content, usage=usage, finish_reason=finish)

    async def astream(self, messages: List) -> AsyncGenerator[LLMChunk, None]:
        """Async streaming generator."""
        system_msg, msgs = _split_anthropic_messages(messages)
        with _quota_attempt(self):
            async with self._async.messages.stream(
                **self._build_kwargs(system_msg, msgs)
            ) as stream:
                async for text in stream.text_stream:
                    yield LLMChunk(content=text)
                # Same terminal marker as the OpenAI stream. Reason and usage only
                # exist on the assembled final message, and asking for them must
                # never break a stream that already delivered its text.
                finish = None
                usage = None
                try:
                    final = await stream.get_final_message()
                    finish = _anthropic_finish_reason(
                        getattr(final, "stop_reason", None))
                    usage = _anthropic_usage(getattr(final, "usage", None))
                except Exception as e:
                    logger.debug("Anthropic stream finish_reason unavailable: %s", e)
                _warn_if_cut_off("Stream", self.model, finish)
                if finish or usage:
                    yield LLMChunk(content="", finish_reason=finish, usage=usage)

    def __repr__(self) -> str:
        return f"AnthropicLLMClient(model={self.model!r}, base_url={self.base_url!r})"
