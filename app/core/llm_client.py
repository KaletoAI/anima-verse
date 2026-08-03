"""LLM client — replaces LangChain ChatOpenAI with the OpenAI Python SDK.

Provides:
- LLMClient: holds the config (model, api_key, …) and offers invoke() + astream()
- AnthropicLLMClient: client for Anthropic Claude models (native SDK)
- LLMResponse: answer wrapper with .content, .usage and .finish_reason
- LLMChunk: streaming chunk with .content
- to_openai_messages(): converts dicts/legacy objects into the OpenAI format
"""
import asyncio
import time
import openai
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
    usage: Optional[Dict[str, int]] = None  # {"prompt_tokens": N, "completion_tokens": N}
    # Why the provider stopped generating, in the OpenAI vocabulary
    # ("stop" = finished on its own, "length" = completion budget hit and the
    # text is cut off mid-sentence, "content_filter", …). ``None`` means the
    # provider sent no reason — NOT that the answer is complete. Never guess a
    # value here: a fabricated "stop" would claim a completeness nobody checked.
    finish_reason: Optional[str] = None


@dataclass
class LLMChunk:
    """A single streaming chunk.

    A chunk carries EITHER text or the terminal ``finish_reason`` — never both.
    ``astream`` appends exactly ONE contentless terminal chunk when the provider
    named a reason, because the reason is only known after the last token. Every
    consumer already skips chunks without content, so the marker adds no
    character to any assembled answer and never reaches the browser; consumers
    that want the reason read ``finish_reason`` before that skip.
    """
    content: str
    finish_reason: Optional[str] = None


def _is_qwen3_model(model_name: str) -> bool:
    """Check if a model is Qwen3-based (has native thinking that should be disabled by default)."""
    lower = model_name.lower()
    return "qwen3" in lower


def _is_gemma_model(model_name: str) -> bool:
    """Check if a model is Gemma-based (has reasoning that should be disabled for tool tasks)."""
    lower = model_name.lower()
    return "gemma" in lower


class LLMClient:
    """Ersetzt ChatOpenAI — haelt Config und bietet invoke() + astream().

    Attribute bleiben kompatibel mit bestehenden getattr()-Zugriffen:
    - model_name, model (Model-Name)
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
        top_p: Optional[float] = None):
        self.model = model
        self.model_name = model
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
        # Disable thinking/reasoning for models with native thinking
        _disable_thinking = thinking is False or (thinking is None and (
            _is_qwen3_model(self.model) or _is_gemma_model(self.model)
        ))
        if _disable_thinking:
            if _is_gemma_model(self.model):
                extra_body["thinking"] = {"type": "disabled"}
            else:
                extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        if self.chat_template:
            extra_body["chat_template"] = self.chat_template
        if extra_body:
            kwargs["extra_body"] = extra_body
        return kwargs

    def invoke(self, messages: List) -> LLMResponse:
        """Synchroner LLM-Call (fuer provider_queue.py Worker-Threads)."""
        openai_msgs = to_openai_messages(messages)
        kwargs = self._build_kwargs()
        max_attempts, base = _busy_retry_policy()
        attempt = 0
        while True:
            try:
                resp = self._sync.chat.completions.create(
                    messages=openai_msgs, **kwargs)
                break
            except Exception as e:
                if not _is_busy_error(e) or attempt >= max_attempts:
                    raise
                attempt += 1
                delay = _busy_delay(base, attempt)
                logger.warning(
                    "LLM busy (503) on %s — retry %d/%d after %.0fs",
                    self.model, attempt, max_attempts, delay)
                time.sleep(delay)
        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        choice = resp.choices[0]
        finish = getattr(choice, "finish_reason", None) or None
        _warn_if_cut_off("Call", self.model, finish)
        return LLMResponse(
            content=choice.message.content or "",
            usage=usage,
            finish_reason=finish)

    async def astream(self, messages: List) -> AsyncGenerator[LLMChunk, None]:
        """Async Streaming Generator (fuer streaming.py Agent-Loop).

        Thinking/Reasoning wird per Default disabled (Tool-LLM im Dual-Modus).
        Das Chat-LLM ist ein separates grosses Modell das kein Gemma/Qwen3 ist.
        """
        openai_msgs = to_openai_messages(messages)
        kwargs = self._build_kwargs()
        max_attempts, base = _busy_retry_policy()
        attempt = 0
        # Busy-retry only around connection setup — once chunks start flowing a
        # restart would duplicate output, so a mid-stream error is never retried.
        while True:
            try:
                stream = await self._async.chat.completions.create(
                    messages=openai_msgs, stream=True, **kwargs)
                break
            except Exception as e:
                if not _is_busy_error(e) or attempt >= max_attempts:
                    raise
                attempt += 1
                delay = _busy_delay(base, attempt)
                logger.warning(
                    "LLM busy (503, stream) on %s — retry %d/%d after %.0fs",
                    self.model, attempt, max_attempts, delay)
                await asyncio.sleep(delay)
        finish = ""
        async for chunk in stream:
            if chunk.choices:
                _c = chunk.choices[0]
                if _c.delta and _c.delta.content:
                    yield LLMChunk(content=_c.delta.content)
                if getattr(_c, "finish_reason", None):
                    finish = _c.finish_reason
        _warn_if_cut_off("Stream", self.model, finish)
        if finish:
            # Terminal marker — contentless, see LLMChunk. The streaming path
            # bypasses the queue, so this is the ONLY way the reason reaches
            # the caller's log line.
            yield LLMChunk(content="", finish_reason=finish)

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"


def to_openai_messages(messages) -> List[Dict[str, Any]]:
    """Konvertiert Message-Dicts oder Legacy-Objekte in OpenAI-Format.

    Akzeptiert:
    - Einzelner String: wird als einzelne user-Message behandelt
    - Liste von Dicts: {"role": "user", "content": "..."}
    - Liste von Legacy-Objekten mit .type/.content Attributen
    - Liste von Strings: jeder String wird als user-Message behandelt
    """
    # String als Ganzes behandeln (nicht zeichenweise iterieren!)
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]

    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        elif isinstance(m, str):
            result.append({"role": "user", "content": m})
        elif hasattr(m, "content"):
            # Legacy-Objekt (z.B. noch existierende LangChain-Messages)
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
    """Konvertiert OpenAI content-Blocks in Anthropic-Format.

    OpenAI image_url -> Anthropic image (base64 oder URL).
    Strings bleiben Strings.
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
    """Trennt Messages in (system_prompt, conversation) fuer die Anthropic API.

    - System-Messages werden extrahiert und zusammengefuegt
    - Aufeinanderfolgende Messages gleicher Rolle werden gemerged
    - Erste Message muss role=user sein (Anthropic-Anforderung)
    """
    openai_msgs = to_openai_messages(messages)

    system_parts: List[str] = []
    conversation: List[Dict[str, Any]] = []

    for msg in openai_msgs:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            # System-Content immer als Text extrahieren
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

    # Aufeinanderfolgende gleiche Rollen mergen (Anthropic erfordert Alternierung)
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

    # Erste Message muss user sein
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "[Start]"})

    if not merged:
        merged = [{"role": "user", "content": ""}]

    system = "\n\n".join(system_parts) if system_parts else ""
    return system, merged


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
    """LLM Client fuer Anthropic Claude-Modelle (native SDK).

    Gleiche Schnittstelle wie LLMClient: invoke() + astream().
    Attribute bleiben kompatibel fuer getattr()-Zugriffe.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str = "https://api.anthropic.com/v1",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        request_timeout: int = 120):
        import anthropic

        self.model = model
        self.model_name = model
        self.openai_api_key = api_key
        self.openai_api_base = api_base
        self.base_url = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens or 4096  # Anthropic erfordert max_tokens
        self.request_timeout = request_timeout

        # SDK erwartet Base-URL ohne /v1
        base = api_base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]

        self._sync = anthropic.Anthropic(
            api_key=api_key, base_url=base, timeout=float(request_timeout))
        self._async = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base, timeout=float(request_timeout))

    def _build_kwargs(self, system: str, msgs: List[Dict]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if system:
            kwargs["system"] = system
        return kwargs

    def invoke(self, messages: List) -> LLMResponse:
        """Synchroner LLM-Call."""
        system_msg, msgs = _split_anthropic_messages(messages)
        resp = self._sync.messages.create(**self._build_kwargs(system_msg, msgs))

        content = ""
        for block in resp.content:
            if hasattr(block, "text"):
                content += block.text

        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            }
        finish = _anthropic_finish_reason(getattr(resp, "stop_reason", None))
        _warn_if_cut_off("Call", self.model, finish)
        return LLMResponse(content=content, usage=usage, finish_reason=finish)

    async def astream(self, messages: List) -> AsyncGenerator[LLMChunk, None]:
        """Async Streaming Generator."""
        system_msg, msgs = _split_anthropic_messages(messages)
        async with self._async.messages.stream(
            **self._build_kwargs(system_msg, msgs)
        ) as stream:
            async for text in stream.text_stream:
                yield LLMChunk(content=text)
            # Same terminal marker as the OpenAI stream. The reason only exists
            # on the assembled final message, and asking for it must never break
            # a stream that already delivered its text.
            finish = None
            try:
                final = await stream.get_final_message()
                finish = _anthropic_finish_reason(
                    getattr(final, "stop_reason", None))
            except Exception as e:
                logger.debug("Anthropic stream finish_reason unavailable: %s", e)
            _warn_if_cut_off("Stream", self.model, finish)
            if finish:
                yield LLMChunk(content="", finish_reason=finish)

    def __repr__(self) -> str:
        return f"AnthropicLLMClient(model={self.model!r}, base_url={self.base_url!r})"
