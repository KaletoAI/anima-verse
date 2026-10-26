"""Replay recorded LLM requests without invoking chat or world-side effects."""
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any


class ReplayUnavailable(ValueError):
    """The old log did not retain enough information for an exact replay."""


class ReplayError(ValueError):
    """An actionable replay error for the HTTP adapter."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_UI_FIELDS = {"entry_id", "replay_available", "replay_unavailable_reason", "comparisons"}
_ROLE_LINE = re.compile(r"(?:^|\n)\[[^\]\n]+\] ")
_LEGACY_VISION_TASKS = {"image_analysis", "image_recognition"}


def entry_id(entry: dict) -> str:
    """Hash the raw record, independent of fields added by the viewer."""
    raw = {key: value for key, value in entry.items() if key not in _UI_FIELDS}
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_messages(messages: Any, *, text_only: bool = False) -> list[dict]:
    if not isinstance(messages, list) or not messages:
        raise ReplayUnavailable("The log contains no complete request messages.")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {
                "system", "developer", "user", "assistant", "tool", "function"}:
            raise ReplayUnavailable("The log contains an invalid or missing message role.")
        content = message.get("content")
        if text_only and not isinstance(content, str):
            raise ReplayUnavailable("This legacy log did not retain a complete multimodal request.")
        if not isinstance(content, (str, list)) and not (
                content is None and message.get("role") == "assistant"
                and (message.get("tool_calls") or message.get("function_call"))):
            raise ReplayUnavailable("The log contains missing or invalid message content.")
    return messages


def request_messages(entry: dict) -> list[dict]:
    """Read exact new requests or reconstruct only unambiguous legacy text logs."""
    prompt = entry.get("prompt")
    if not isinstance(prompt, dict):
        raise ReplayUnavailable("The log contains no recorded prompt.")
    if "request_messages" in prompt:
        return _validate_messages(prompt["request_messages"])

    system = prompt.get("system", "")
    user = prompt.get("user")
    if not isinstance(system, str) or not isinstance(user, str):
        raise ReplayUnavailable("The log is missing its system or user input.")
    if entry.get("task") in _LEGACY_VISION_TASKS:
        raise ReplayUnavailable("This legacy vision log did not retain the image input.")

    # Streaming stored HISTORY in messages, not the full provider request. Its
    # user field already includes the moment suffix; never append it again.
    if "messages" in prompt or entry.get("llm_role") in {"Chat-LLM", "Tool-LLM", "LLM"}:
        history = prompt.get("messages", [])
        if not isinstance(history, list):
            raise ReplayUnavailable("The legacy log contains invalid conversation history.")
        if history:
            _validate_messages(history, text_only=True)
        from app.core.streaming import compose_messages
        return _validate_messages(compose_messages(system, history, user), text_only=True)

    # Queued logs flattened roles and multimodal blocks. Only one plain user
    # message can be recovered; a literal role-looking line is ambiguous too.
    if not user.startswith("[user] "):
        raise ReplayUnavailable("This legacy log did not retain the exact ordered request messages.")
    content = user[len("[user] "):]
    if _ROLE_LINE.search(content):
        raise ReplayUnavailable("This legacy log has ambiguous flattened message roles.")
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": content})
    return messages


def read_entries(path: Path) -> list[dict]:
    """Read complete JSONL records, ignoring malformed or partially written lines."""
    entries = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except FileNotFoundError:
        pass
    return entries


def group_entries(entries: list[dict]) -> list[dict]:
    """Attach persisted comparisons before the caller filters or pages originals."""
    comparisons: dict[str, list[dict]] = {}
    for entry in entries:
        if entry.get("replay_of"):
            comparisons.setdefault(entry["replay_of"], []).append(entry)
    originals = []
    for entry in entries:
        if entry.get("replay_of"):
            continue
        identifier = entry_id(entry)
        try:
            request_messages(entry)
            reason = ""
        except ReplayUnavailable as exc:
            reason = str(exc)
        originals.append({**entry, "entry_id": identifier,
                          "replay_available": not reason,
                          "replay_unavailable_reason": reason,
                          "comparisons": comparisons.get(identifier, [])})
    return originals


def _find_source(path: Path, identifier: str) -> dict:
    for entry in read_entries(path):
        if not entry.get("replay_of") and entry_id(entry) == identifier:
            return entry
    raise ReplayError(404, "The original log entry was not found (it may have been archived).")


def replay_entry(path: Path, *, entry_id: str, provider: str, model: str,
                 temperature: float, max_tokens: int, top_p: float | None = None,
                 frequency_penalty: float | None = None) -> dict:
    """Send the recorded messages once through the explicitly selected queue.

    A selected routing entry's extra_params keep their normal SDK precedence
    over positive form values. The one exception is max_tokens=0: the form
    explicitly requests no client output limit, so its saved body limit is
    removed from this temporary instance only.
    """
    source = _find_source(path, entry_id)
    try:
        messages = request_messages(source)
    except ReplayUnavailable as exc:
        raise ReplayError(409, str(exc)) from exc

    from app.core.llm_router import create_llm_instance
    from app.core.provider_manager import get_provider_manager
    from app.core.llm_queue import Priority

    pm = get_provider_manager()
    selected = pm.get_provider(provider)
    if selected is None:
        raise ReplayError(400, "Unknown provider. Choose an explicitly configured provider.")
    channel = pm.get_queue_for_provider(provider)
    if not selected.available or channel is None:
        raise ReplayError(503, f"Provider '{provider}' is unavailable or has no LLM queue.")
    if selected.type == "anthropic":
        if top_p is not None or frequency_penalty is not None:
            raise ReplayError(400, "This Anthropic client does not support top_p or frequency_penalty.")
        if max_tokens == 0:
            raise ReplayError(400, "Anthropic requires a positive max_tokens limit; unlimited is not supported.")
        if temperature > 1:
            raise ReplayError(400, "Anthropic temperature must be between 0 and 1.")

    instance = create_llm_instance("llm_replay", model, provider_name=provider,
                                   temperature=temperature, max_tokens=max_tokens)
    if instance is None or instance.provider_name != provider:
        raise ReplayError(503, "The selected provider could not be resolved without fallback.")
    try:
        # A zero in the replay form means no output limit on OpenAI-compatible
        # calls, including when the routing entry carries a saved body limit.
        if max_tokens == 0:
            instance.extra_params = {
                k: v for k, v in instance.extra_params.items()
                if k not in ("max_tokens", "max_completion_tokens")}
        client = instance.create_llm(max_tokens=max_tokens, top_p=top_p,
                                     frequency_penalty=frequency_penalty)
    except Exception as exc:
        raise ReplayError(503, f"The selected provider client could not be created: {exc}") from exc
    client.replay_of = entry_id
    client.replay_id = uuid.uuid4().hex
    failure = None
    try:
        channel.submit(task_type="llm_replay", priority=Priority.NORMAL, llm=client,
                       messages_or_prompt=messages, agent_name="",
                       label=f"Replay of {entry_id}")
    except Exception as exc:
        # The queue owns the success AND error log. Never append a second line.
        failure = exc
    comparison = next((entry for entry in read_entries(path)
                       if entry.get("replay_id") == client.replay_id
                       and entry.get("replay_of") == entry_id), None)
    if comparison is None:
        raise ReplayError(500, "The replay did not produce a persisted log record.") from failure
    return comparison
