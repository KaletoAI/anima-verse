"""Central LLM call function with task-based routing.

The `llm_call()` function is the single entry point for all non-streaming
LLM calls. From the task type the resolver reads the matching LLM
(provider+model+settings) out of the `llm_routing` config, with a fallback
chain when a provider is unavailable.

Also living here:
- `LLMInstance`: dataclass that bundles provider+model+settings and creates an
  LLMClient on demand.
- `create_llm_instance()`: factory for the dev routes (world_dev, story_dev)
  that pick a concrete model explicitly.
- `get_llm_instance_by_name()`: parsing helper for character overrides
  ("Provider::Model" or "Model").

Streaming runs separately but uses the same resolver.
"""
import json
import os
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core import config
from app.core.llm_client import AnthropicLLMClient, LLMClient, merge_extra_params
from app.core.llm_queue import get_llm_queue
from app.core.log import get_logger
from app.core.provider import Provider
from app.core.provider_manager import get_provider_manager
from app.core.provider_queue import caller_handles_failure

logger = get_logger("llm_router")


# ---------------------------------------------------------------------------
# LLMInstance + factories
# ---------------------------------------------------------------------------

@dataclass
class LLMInstance:
    """Represents a resolved LLM instance ready for use.

    Connection details (type, api_base, api_key) are delegated to the Provider.
    """
    provider_name: str
    model: str
    tasks: list = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    chat_template: Optional[str] = None
    # The entry's repetition_penalty; None = not sent (see LLMClient).
    repetition_penalty: Optional[float] = None
    extra_params: Dict[str, Any] = field(default_factory=dict, repr=False)
    _provider: Optional[Provider] = field(default=None, repr=False)
    pinned: bool = False

    @property
    def type(self) -> str:
        return self._provider.type if self._provider else ""

    @property
    def api_base(self) -> str:
        return self._provider.api_base if self._provider else ""

    @property
    def api_key(self) -> str:
        return self._provider.api_key if self._provider else ""

    @property
    def available(self) -> bool:
        return self._provider.available if self._provider else False

    @property
    def name(self) -> str:
        tasks_str = ",".join(self.tasks) if self.tasks else "unknown"
        return f"{self.provider_name}/{self.model} ({tasks_str})"

    def create_llm(self, **overrides):
        """Creates an LLMClient (or AnthropicLLMClient) with optional per-agent
        overrides.

        The client is STAMPED with this instance's ``provider_name``. The
        client itself knows only its endpoint, and matching an endpoint back
        to a provider can only ever return the first provider that uses it
        (``ProviderManager.provider_name_for``) — two entries on the same
        AI-Hub URL are indistinguishable that way. Everything the router hands
        out therefore answers the question itself, and the endpoint match
        stays what it was meant to be: a fallback for objects that come from
        somewhere else. The name decides which lane pool the call lands on, so
        a wrong answer is a wrong pool.
        """
        model = overrides.get("model") or self.model
        api_key = overrides.get("api_key") or self.api_key
        api_base = overrides.get("api_base") or self.api_base
        temperature = float(overrides["temperature"]) if overrides.get("temperature") is not None else self.temperature
        max_tok = overrides["max_tokens"] if "max_tokens" in overrides else self.max_tokens
        max_tokens = int(max_tok) if max_tok else None
        provider_timeout = self._provider.timeout if self._provider else None
        timeout = (overrides.get("request_timeout") or provider_timeout
                   or int(os.environ.get("LLM_REQUEST_TIMEOUT", "120")))
        frequency_penalty = overrides.get("frequency_penalty")
        top_p = overrides.get("top_p")
        repetition_penalty = overrides.get("repetition_penalty",
                                           self.repetition_penalty)
        extra_params = merge_extra_params(self.extra_params, overrides.get("extra_params") or {})

        if self._provider and self._provider.type == "anthropic":
            client = AnthropicLLMClient(
                model=model,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
                request_timeout=timeout,
                extra_params=extra_params)
        else:
            client = LLMClient(
                model=model,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
                request_timeout=timeout,
                chat_template=(overrides.get("chat_template")
                               or self.chat_template),
                frequency_penalty=frequency_penalty,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
                extra_params=extra_params)
        client.provider_name = self.provider_name
        return client


def get_llm_instance_by_name(model_name: str) -> Optional[LLMInstance]:
    """Creates an LLMInstance from a model name (the provider is resolved).

    Accepts "Provider::Model" or "Model".
    """
    pm = get_provider_manager()

    provider_name = ""
    if model_name and "::" in model_name:
        provider_name, model_name = model_name.split("::", 1)

    provider = None
    if provider_name:
        provider = pm.get_provider(provider_name)
    if not provider:
        provider = pm.find_provider_for_model(model_name)
    if not provider:
        logger.warning("get_llm_instance_by_name: No provider found for '%s'", model_name)
        return None
    return _named_instance(provider, model_name)


def create_llm_instance(
    task: str,
    model: str,
    provider_name: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    routing_entry: Optional[dict] = None) -> Optional[LLMInstance]:
    """Creates an LLMInstance for a concrete model (for the dev routes)."""
    pm = get_provider_manager()

    if model and "::" in model and not provider_name:
        provider_name, model = model.split("::", 1)

    provider = None
    if provider_name:
        provider = pm.get_provider(provider_name)
    if not provider and routing_entry is None:
        provider = pm.find_provider_for_model(model)

    if not provider:
        logger.warning("No provider found for model '%s' (task=%s)", model, task)
        return None

    instance = (_instance_for(task, routing_entry, provider) if routing_entry is not None
                else _named_instance(provider, model))
    instance.tasks = [task]
    instance.temperature = temperature if temperature is not None else instance.temperature
    instance.max_tokens = max_tokens if max_tokens is not None else instance.max_tokens
    return instance


def parse_extra_params(raw: Any) -> Dict[str, Any]:
    """Accept a JSON object (or editor JSON text); reject non-finite numbers."""
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            raw = json.loads(raw, parse_constant=lambda _: _reject_non_finite())
        except ValueError as exc:
            if str(exc) == "extra_params must contain only finite numbers":
                raise
            raise ValueError("extra_params must be a valid JSON object") from exc
    if not isinstance(raw, dict):
        raise ValueError("extra_params must be a JSON object")
    _check_finite(raw)
    return raw


def _reject_non_finite():
    raise ValueError("extra_params must contain only finite numbers")


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _reject_non_finite()
    if isinstance(value, dict):
        for nested in value.values():
            _check_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _check_finite(nested)


def _named_instance(provider: Provider, model: str) -> LLMInstance:
    """Use the first enabled entry for this provider/model, if one is saved."""
    for entry in _load_routing():
        if (isinstance(entry, dict) and entry.get("enabled") is not False
                and entry.get("provider") == provider.name and entry.get("model") == model):
            return _instance_for("", entry, provider)
    return LLMInstance(provider_name=provider.name, model=model, _provider=provider)


def _entry_extra_params(entry: dict) -> Dict[str, Any]:
    try:
        return parse_extra_params(entry.get("extra_params", {}))
    except ValueError:
        logger.warning("Invalid extra_params on routing entry %s/%s; ignored",
                       entry.get("provider"), entry.get("model"))
        return {}


# ---------------------------------------------------------------------------
# Routing + llm_call
# ---------------------------------------------------------------------------

def _load_routing() -> List[dict]:
    """Reads llm_routing from the config."""
    routing = config.get("llm_routing", [])
    return routing if isinstance(routing, list) else []


def disabled_providers(cfg: Optional[dict] = None) -> set:
    """Names of the providers switched off in the admin (``enabled: false``).

    Such a provider is not loaded by the provider manager at all, and every
    routing entry on it is skipped as if the entry itself were disabled.
    """
    provs = cfg.get("providers") if cfg is not None else config.get("providers", [])
    return {str(p.get("name") or "") for p in (provs or [])
            if isinstance(p, dict) and p.get("enabled") is False}


async def _warmup_one(entry: dict) -> None:
    """Sends a 1-token ping to a routing entry so the backend (e.g.
    llama-swap, vLLM) loads the model into memory. Errors are logged but
    never raised — a preload must not disturb the startup.
    """
    provider_name = (entry.get("provider") or "").strip()
    model = (entry.get("model") or "").strip()
    if not provider_name or not model:
        return
    # Entries that ONLY serve pose_embedding are embedding models — a chat
    # completion ping would hit a non-chat model. Skip them.
    _tasks = [t.get("task") for t in (entry.get("tasks") or []) if isinstance(t, dict)]
    if _tasks and all(t == "pose_embedding" for t in _tasks):
        logger.info("Preload skip: %s/%s — embedding-only entry (pose_embedding)",
                    provider_name, model)
        return
    pm = get_provider_manager()
    provider = pm.get_provider(provider_name)
    if not provider:
        logger.warning("Preload skip: provider '%s' nicht gefunden", provider_name)
        return
    if not provider.available:
        logger.info("Preload skip: provider '%s' nicht verfuegbar", provider_name)
        return
    instance = LLMInstance(
        provider_name=provider_name,
        model=model,
        temperature=0.0,
        max_tokens=1,
        extra_params=_entry_extra_params(entry),
        _provider=provider,
    )
    try:
        client = instance.create_llm(max_tokens=1, temperature=0.0)
    except Exception as e:
        logger.warning("Preload %s/%s: client-init fehlgeschlagen: %s",
                       provider_name, model, e)
        return
    try:
        logger.info("Preload start: %s/%s", provider_name, model)
        # The Anthropic and OpenAI clients both have astream(); a 1-token ping
        # over streaming is entirely enough to load the model.
        async for _ in client.astream([{"role": "user", "content": "ping"}]):
            break
        logger.info("Preload OK:    %s/%s", provider_name, model)
    except Exception as e:
        logger.warning("Preload FAIL:  %s/%s: %s", provider_name, model, e)


async def preload_models() -> None:
    """Loads every routing entry with ``preload_on_startup=True`` in parallel.
    Fired in the FastAPI lifespan via ``asyncio.create_task`` so the server
    start does not block.
    """
    routing = _load_routing()
    targets = [
        e for e in routing
        if isinstance(e, dict)
        and e.get("preload_on_startup") is True
        and e.get("enabled") is not False
    ]
    off = disabled_providers()
    targets = [e for e in targets if (e.get("provider") or "").strip() not in off]
    if not targets:
        return
    import asyncio
    logger.info("Preload: %d Modelle werden im Hintergrund geladen", len(targets))
    await asyncio.gather(*(_warmup_one(e) for e in targets), return_exceptions=True)
    logger.info("Preload: alle Warmup-Requests abgeschlossen")


def _resolve_character_override(task: str, agent_name: str) -> Optional[LLMInstance]:
    """Reads `llm_routing_overrides[task]` from character_config.

    Supported value formats:
    - "Provider::Model"   — a concrete provider + model
    - "Model"             — the model alone; the provider is found automatically

    Returns an LLMInstance when an override exists AND the provider is
    available, otherwise None (falls back to the global routing).
    """
    try:
        from app.models.character import get_character_config
        cfg = get_character_config(agent_name) or {}
    except Exception:
        return None

    overrides = cfg.get("llm_routing_overrides") or {}
    if not isinstance(overrides, dict):
        return None
    raw = overrides.get(task)
    if not raw or not isinstance(raw, str):
        return None

    instance = get_llm_instance_by_name(raw.strip())
    if not instance:
        logger.warning("Character-Override '%s' fuer task=%s (agent=%s): Provider/Model nicht aufloesbar",
                       raw, task, agent_name)
        return None
    if not instance.available:
        logger.info("Character-Override '%s' fuer task=%s (agent=%s): Provider unavailable — Fallback auf globales Routing",
                    raw, task, agent_name)
        return None
    instance.tasks = [task]
    instance.pinned = True
    logger.info("Character-Override greift: task=%s agent=%s -> %s/%s",
                task, agent_name, instance.provider_name, instance.model)
    return instance


def fallback_parent(task: str) -> Optional[str]:
    """The task an UNROUTED task borrows its LLM from, or None.

    Pure rule, no config access — the admin routing UI and the effective-
    routing endpoint show the same rule resolve_llm applies:
      * "<parent>_<sub>" → parent for intent / thought / extraction
      * building_layout, furnish, prop_mount_classify, room_description_sync, pose_animation_prompt
        → "intent"
        (strict-JSON tool work; the tool-class anchor)
      * npc_* → "chat_stream" (character writing; the chat anchor)
    """
    from app.core.llm_tasks import plugin_task_fallback
    declared_parent = plugin_task_fallback(task)
    if declared_parent:
        return declared_parent
    for parent in ("intent", "thought", "extraction"):
        if task.startswith(parent + "_") and task != parent:
            return parent
    if task in ("building_layout", "furnish", "prop_mount_classify", "room_description_sync", "pose_animation_prompt"):
        return "intent"
    if task.startswith("npc_"):
        return "chat_stream"
    return None


def _candidates(task: str, routing: list) -> List[Tuple[int, dict]]:
    """(order, entry) for every ENABLED routing entry that lists ``task``."""
    out: List[Tuple[int, dict]] = []
    for entry in routing:
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        for t in (entry.get("tasks") or []):
            if isinstance(t, dict) and t.get("task") == task:
                out.append((int(t.get("order", 999)), entry))
                break
    return out


def _usable(entry: dict, task: str = "", *, quiet: bool = False) -> Optional[Provider]:
    """The provider of a routing entry if the entry can serve a call right
    now, else None — the one availability rule of ``resolve_llm`` and
    ``overflow_target``.

    ``quiet`` drops the "not found / unavailable / cooldown" lines: the
    overflow check walks the whole chain on every pass of a waiting call
    (up to once per second per queued task), and repeating the resolver's
    lines there would only flood the log with what it already said."""
    pm = get_provider_manager()
    off = disabled_providers()
    provider_name = (entry.get("provider") or "").strip()
    model = (entry.get("model") or "").strip()
    if not provider_name or not model:
        return None
    if provider_name in off:
        # Switched off in the admin — not loaded, skipped without a warning.
        return None
    provider = pm.get_provider(provider_name)
    if not provider:
        if not quiet:
            logger.warning("resolve_llm(%s): provider '%s' not found", task, provider_name)
        return None
    if not provider.available:
        if not quiet:
            logger.info("resolve_llm(%s): provider '%s' unavailable, trying next", task, provider_name)
        return None
    if _model_cooled_down(provider_name, model):
        if not quiet:
            logger.info("resolve_llm(%s): %s/%s in model-cooldown (no servable backend), trying next",
                        task, provider_name, model)
        return None

    return provider


def _instance_for(task: str, entry: dict, provider: Provider) -> LLMInstance:
    """The LLMInstance of a routing entry — the same settings whether the
    entry is the regular choice or an overflow target."""
    provider_name = (entry.get("provider") or "").strip()
    model = (entry.get("model") or "").strip()
    temperature = float(entry.get("temperature") or 0.7)
    max_tokens = entry.get("max_tokens")
    if max_tokens in ("", None, 0):
        max_tokens = None
    else:
        max_tokens = int(max_tokens)
    # Empty / 0 = the entry sends no repetition_penalty at all.
    try:
        repetition_penalty = float(entry.get("repetition_penalty") or 0) or None
    except (TypeError, ValueError):
        repetition_penalty = None

    return LLMInstance(
        provider_name=provider_name,
        model=model,
        tasks=[task],
        temperature=temperature,
        max_tokens=max_tokens,
        chat_template=(entry.get("chat_template") or "") or None,
        repetition_penalty=repetition_penalty,
        extra_params=_entry_extra_params(entry),
        _provider=provider)


# (task, pool) -> SYSTEM monotonic time of the last "saturated" overflow line,
# so a busy pool logs its resolve-time skips once a minute, not per call.
_OVERFLOW_LOGGED: Dict[Tuple[str, str], float] = {}


def overflow_target(task: str, agent_name: str = "", *,
                    exclude_pools: frozenset = frozenset()) -> Optional[LLMInstance]:
    """Where a BACKGROUND call may move when its pool is full, or None
    (development_instructions/plan-lane-overflow.md § 4/§ 5).

    Walks the task's chain in order (the ``fallback_parent`` chain when the
    task has no route of its own) and returns the first entry that is
    usable, not in ``exclude_pools`` (pools this call already waited on and
    left), does not have ``accepts_overflow`` switched off, and whose pool
    has a lane free FOR THIS CALLER — ``free_lanes`` with the caller's key
    and class, so R4's conversation hold counts: a lane a chat just left is
    not free for a thought, and moving there would only start another wait.
    Chats never get a target, and ``overflow_after_seconds = 0`` switches
    the whole mechanism off."""
    from app.core.llm_lanes import (is_background, configured_lane_rules,
        get_lane_manager, pool_key_for, cache_key_for, lane_priority_for)
    from app.core.llm_task_state import is_enabled

    if not is_background(task) or configured_lane_rules().overflow_after <= 0:
        return None
    routing = _load_routing()
    chain_task = task
    candidates = _candidates(chain_task, routing)
    while not candidates:
        parent = fallback_parent(chain_task)
        if not parent:
            return None
        chain_task = parent
        candidates = _candidates(chain_task, routing)
    if not is_enabled(task) or not is_enabled(chain_task):
        return None
    manager = get_lane_manager()
    for _, entry in sorted(candidates, key=lambda item: item[0]):
        pool = pool_key_for((entry.get("provider") or "").strip(),
                            (entry.get("model") or "").strip())
        if pool in exclude_pools or entry.get("accepts_overflow") is False:
            continue
        provider = _usable(entry, chain_task, quiet=True)
        if provider is not None and manager.free_lanes(
                pool, cache_key_for(task, agent_name), lane_priority_for(task)) > 0:
            return _instance_for(chain_task, entry, provider)
    return None


def resolve_llm(task: str, agent_name: str = "", *, overflow: bool = False) -> Optional[LLMInstance]:
    """Determines the LLM for a task from the llm_routing config.

    Order:
    1. Character override from `character_config.llm_routing_overrides[task]`
       (format: "Provider::Model") — when the provider is available
    2. The global llm_routing chain (sorted by order, first available provider)
    3. None when nothing applies

    Args:
        task: task id from TASK_TYPES
        user_id, agent_name: optional — when both are set, the character
            override from character_config.json is taken into account.

    Opting into overflow lets background calls skip a saturated pool only
    when an accepting alternative has a free lane. Character overrides stay
    pinned, and callers without the flag keep the regular routing choice.

    The task disable (llm_task_state) is always the first check.
    """
    # Task disabled? → no LLM (callers drop into their existing fallback paths)
    from app.core.llm_task_state import is_enabled
    if not is_enabled(task):
        logger.debug("resolve_llm(%s): Task deaktiviert", task)
        return None

    # 1. Character override
    if agent_name:
        override_inst = _resolve_character_override(task, agent_name)
        if override_inst is not None:
            return override_inst

    routing = _load_routing()
    if not routing:
        return None

    candidates = _candidates(task, routing)

    if not candidates:
        parent = fallback_parent(task)
        if parent:
            logger.debug("resolve_llm(%s): no routing, falling back to '%s'", task, parent)
            return resolve_llm(parent, agent_name=agent_name, overflow=overflow)
        return None

    candidates.sort(key=lambda x: x[0])
    for order, entry in candidates:
        provider = _usable(entry, task)
        if provider is None:
            continue
        instance = _instance_for(task, entry, provider)
        if overflow:
            from app.core.llm_lanes import (is_background, configured_lane_rules,
                                           get_lane_manager, pool_key_for)
            if is_background(task) and configured_lane_rules().overflow_after > 0:
                pool = pool_key_for(instance.provider_name, instance.model)
                if get_lane_manager().pool_saturated(pool):
                    alt = overflow_target(task, agent_name, exclude_pools={pool})
                    if alt is not None:
                        now = time.monotonic()
                        key = (task, pool)
                        last = _OVERFLOW_LOGGED.get(key)
                        if last is None or now - last >= 60:
                            _OVERFLOW_LOGGED[key] = now
                            logger.info("[lanes] overflow %s %s: %s → %s (saturated)",
                                        task, agent_name, pool,
                                        pool_key_for(alt.provider_name, alt.model))
                        return alt
        return instance

    logger.warning("resolve_llm(%s): kein verfuegbares LLM in der Kette", task)
    return None


def explain_routing(cfg: dict, *, provider_lookup, cooled_down,
                    disabled: set, runtime_disabled: set) -> dict:
    """Read-only walk of the routing table for the admin Overview page.

    Mirrors resolve_llm's global chain (character overrides are NOT applied)
    and says per task what would be picked right now and why. ``provider_lookup``
    and ``cooled_down`` are injected so the rule can be tested without a
    provider manager; the route passes the real ones. Nothing here mutates
    cooldown state.
    """
    from app.core.llm_lanes import lane_count_in
    from app.core.llm_tasks import TASK_TYPES, CATEGORY_LABELS, is_task_gated_off

    routing = [e for e in (cfg.get("llm_routing") or []) if isinstance(e, dict)]
    provider_rows = []
    for p in (cfg.get("providers") or []):
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "")
        live = provider_lookup(name)
        provider_rows.append({"name": name, "type": p.get("type") or "",
                              "enabled": p.get("enabled") is not False,
                              "available": bool(live and getattr(live, "available", False))})
    known = {r["name"] for r in provider_rows}
    off = {r["name"] for r in provider_rows if not r["enabled"]}

    def _entry_status(entry):
        prov = (entry.get("provider") or "").strip()
        model = (entry.get("model") or "").strip()
        live = provider_lookup(prov) if prov else None
        return {
            "provider_exists": prov in known,
            "provider_enabled": prov not in off,
            "provider_available": bool(live and getattr(live, "available", False)),
            "model_cooldown_s": cooled_down(prov, model) if prov and model else None,
        }

    entries = []
    for idx, e in enumerate(routing):
        st = _entry_status(e)
        entries.append({"index": idx, "name": e.get("name") or "",
                        "provider": e.get("provider") or "", "model": e.get("model") or "",
                        "enabled": e.get("enabled") is not False, **st,
                        # Lanes of the entry's provider+model POOL (shared by
                        # every entry on that model), not the entry's own field.
                        "lanes": lane_count_in(routing, e.get("provider") or "", e.get("model") or ""),
                        "tasks": [{"task": t.get("task"), "order": t.get("order")}
                                  for t in (e.get("tasks") or []) if isinstance(t, dict) and t.get("task")]})

    def _index_of(entry) -> int:
        """Position of ``entry`` in ``routing`` — by identity, not by value.

        Two routing rows may be equal dicts; list.index() would then report the
        first one for both.
        """
        for i, cand in enumerate(routing):
            if cand is entry:
                return i
        return -1

    def _walk(task):
        """(chain rows, resolved-or-None, reason) over the ENABLED candidates of ``task``."""
        cands = sorted(_candidates(task, routing), key=lambda x: x[0])
        chain, resolved, skipped_notes = [], None, []
        for order, entry in cands:
            idx = _index_of(entry)
            st = _entry_status(entry)
            if not st["provider_exists"]:
                skip = "provider missing"
            elif not st["provider_enabled"]:
                skip = "provider disabled"
            elif not st["provider_available"]:
                skip = "provider unavailable"
            elif st["model_cooldown_s"] is not None:
                skip = "model cooldown"
            else:
                skip = None
            chain.append({"index": idx, "order": order, "provider": entry.get("provider") or "",
                          "model": entry.get("model") or "", "skipped": skip,
                          "accepts_overflow": entry.get("accepts_overflow") is not False})
            if skip is None and resolved is None:
                resolved = {"index": idx, "provider": entry.get("provider") or "",
                            "model": entry.get("model") or "", "order": order, "via_task": task}
            elif skip is not None and resolved is None:
                skipped_notes.append(f"order {order} skipped: {skip}")
        if resolved is None:
            return chain, None, ("no LLM in chain" if cands else "")
        reason = f"order {resolved['order']}"
        if skipped_notes:
            reason += " — " + "; ".join(skipped_notes)
        return chain, resolved, reason

    emb = cfg.get("embedding") or {}
    tasks_out = []
    for tid, meta in TASK_TYPES.items():
        row = {"task": tid, "label": meta.get("label", tid), "category": meta.get("category", ""),
               "category_label": CATEGORY_LABELS.get(str(meta.get("category", "")), ""),
               "gated_off": is_task_gated_off(tid, cfg), "disabled": tid in disabled,
               "runtime_disabled": tid in runtime_disabled, "fallback": fallback_parent(tid),
               "chain": [], "resolved": None, "via": "none", "reason": ""}
        if row["disabled"] or row["runtime_disabled"]:
            row["via"] = "disabled"
            row["reason"] = "task disabled (" + ("runtime preset" if row["runtime_disabled"] else "persistent") + ")"
        elif row["gated_off"]:
            row["via"] = "gated_off"
            row["reason"] = f"feature gate {meta.get('gate')} is off"
        elif tid == "pose_embedding" and (emb.get("backend") or "auto") != "external":
            row["via"] = "direct"
            row["reason"] = f"built-in embedding ({emb.get('internal_model') or 'default model'})"
        else:
            chain, resolved, reason = _walk(tid)
            if chain:
                row.update(chain=chain, resolved=resolved, via="direct" if resolved else "none", reason=reason)
            else:
                parent = fallback_parent(tid)
                if parent:
                    pchain, presolved, preason = _walk(parent)
                    row.update(chain=pchain, resolved=presolved,
                               via="fallback" if presolved else "none",
                               reason=f"no routing, parent '{parent}'" + (f" — {preason}" if preason else ""))
                    if not presolved:
                        row["reason"] = f"no routing, parent '{parent}' has no LLM in chain"
                else:
                    row["reason"] = "no LLM assigned"
        tasks_out.append(row)
    return {"providers": provider_rows, "entries": entries, "tasks": tasks_out}


# Substrings in error messages that indicate an upstream backend problem
# (5xx, process crash, connection drop) — NOT a user-input error like
# bad-request, content-policy or auth. When seen, we cooldown the provider
# and retry through the routing fallback chain.
_UPSTREAM_FAIL_MARKERS = (
    "InternalServerError",
    "upstream command",
    "ConnectionError",
    "ReadTimeout",
    "BadGateway",
    "Bad gateway",
    "ConnectionRefused",
    "Connection refused",
    "Remote end closed",
    " 500",
    " 502",
    " 504",
)
# NOTE: a plain 503 / "Service Unavailable" is deliberately NOT here. It means
# the provider is momentarily busy (gateway at its parallel-call limit), so the
# LLMClient retries the SAME model with backoff (config: llm_retry.*). If those
# retries are exhausted the call fails fast — we do NOT cool the provider down
# for 5 minutes, since it is busy, not broken.
# EXCEPTION: a 503 whose body says "No healthy backend for model X" is NOT
# busy-ness — the model has no servable backend on this provider, so
# _is_upstream_failure() treats it (via _is_no_backend_error) as a
# cooldown+fallback case so the routing chain switches to the next provider.

_UPSTREAM_COOLDOWN_SECONDS = 300.0  # 5 min — survives ~1-2 health probes
_LLM_CALL_MAX_ATTEMPTS = 3


def _is_upstream_failure(err: BaseException) -> bool:
    # Single source of truth for the "no servable backend" 503 lives in
    # llm_client so the busy-retry layer and this fallback layer always agree.
    from app.core.llm_client import _is_no_backend_error
    if _is_no_backend_error(err):
        return True
    msg = str(err)
    return any(marker in msg for marker in _UPSTREAM_FAIL_MARKERS)


def _cooldown_provider(provider_name: str, reason: str) -> None:
    if not provider_name:
        return
    try:
        from app.core.provider_manager import get_provider_manager
        provider = get_provider_manager().get_provider(provider_name)
        if provider:
            provider.mark_unhealthy(reason, _UPSTREAM_COOLDOWN_SECONDS)
    except Exception as e:
        logger.debug("Cooldown set failed for %s: %s", provider_name, e)


# Per-(provider, model) cooldown for MODEL-SPECIFIC failures, e.g. a gateway
# returning 503 "No healthy backend for model X". Unlike _cooldown_provider this
# leaves the provider available for its OTHER models — a gateway that can't serve
# one model can still serve the rest (the user's "tools" model stays reachable
# while "fallen-command" is down). resolve_llm skips cooled-down (provider, model)
# pairs so the routing chain moves to the next provider for that task only.
_MODEL_COOLDOWN: Dict[Tuple[str, str], float] = {}


def _model_cooled_down(provider_name: str, model: str) -> bool:
    key = (provider_name, model)
    until = _MODEL_COOLDOWN.get(key)
    if not until:
        return False
    if time.monotonic() < until:
        return True
    _MODEL_COOLDOWN.pop(key, None)  # expired — allow retry
    return False


def mark_model_unhealthy(provider_name: str, model: str,
                         cooldown_seconds: float = _UPSTREAM_COOLDOWN_SECONDS) -> None:
    """Marks a single (provider, model) pair unhealthy without touching the
    provider's overall availability. Used for "no servable backend for model X"
    so other models on the same provider keep routing normally.

    ONE warning per outage: the same 503 reaches this function twice (the
    queue worker on the failed task, llm_call on the re-raised exception).
    A repeat inside a running cooldown only pushes the deadline out and logs
    DEBUG."""
    if not provider_name or not model:
        return
    already_cooling = _model_cooled_down(provider_name, model)
    _MODEL_COOLDOWN[(provider_name, model)] = time.monotonic() + max(0.0, cooldown_seconds)
    if already_cooling:
        logger.debug("Model %s/%s stays in cooldown for another %ds (no servable backend)",
                     provider_name, model, int(cooldown_seconds))
    else:
        logger.warning("Model %s/%s in cooldown for %ds (no servable backend)",
                       provider_name, model, int(cooldown_seconds))


def llm_call(
    task: str,
    system_prompt: str,
    user_prompt: str,
    *,
    agent_name: str = "", priority: Optional[int] = None,
    label: str = "", max_tokens: Optional[int] = None) -> Any:
    """Central LLM entry point for non-streaming calls.

    Resolves provider+model per task and submits through the queue; the queue
    worker does the logging. On an upstream failure (5xx / connection reset /
    backend crash) the provider goes into cooldown and the call moves on
    through the routing chain (at most ``_LLM_CALL_MAX_ATTEMPTS`` attempts).

    This function OWNS the failure report for its attempts: it submits inside
    ``caller_handles_failure()``, so the worker keeps a recoverable failure at
    WARNING, and the ERROR with the full traceback is written here — once,
    when the chain is exhausted.

    ``max_tokens`` caps the completion budget for THIS call (instead of the
    routing entry) — the anti-hallucination bound for tightly limited output
    such as the prompt composer.

    Returns:
        The queue's response object (compatible with the existing call sites:
        `.content` yields the text).

    Raises:
        RuntimeError: when no LLM is available for the task, or every
        fallback provider failed.
    """
    if priority is None:
        from app.core.llm_tasks import get_default_priority
        priority = get_default_priority(task)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    from app.core.llm_lanes import LaneOverflow, Overflow

    hop_limit = len(_load_routing()) + 1
    last_err: Optional[BaseException] = None
    for attempt in range(1, _LLM_CALL_MAX_ATTEMPTS + 1):
        instance = resolve_llm(task, agent_name=agent_name, overflow=True)
        if instance is None:
            if last_err is not None:
                # Nothing caught this one — the traceback the worker held back
                # belongs in the log now: the queue chains its original
                # exception as __cause__, so this record carries the upstream
                # stack, not just the queue wrapper.
                logger.error("llm_call: no provider left for '%s' after %d attempt(s)",
                             task, attempt - 1, exc_info=last_err)
                raise RuntimeError(
                    f"llm_call: every provider for '{task}' failed — "
                    f"last error: {last_err}")
            raise RuntimeError(f"llm_call: no LLM available for task '{task}'")

        overflow = None if instance.pinned else Overflow()
        try:
            # A hop is lane contention, so it stays inside the upstream attempt.
            for hop in range(hop_limit):
                llm = (instance.create_llm(max_tokens=max_tokens) if max_tokens
                       else instance.create_llm())
                logger.info("llm_call task=%s provider=%s model=%s agent=%s attempt=%d/%d",
                            task, instance.provider_name, instance.model,
                            agent_name or "-", attempt, _LLM_CALL_MAX_ATTEMPTS)
                try:
                    with caller_handles_failure():
                        return get_llm_queue().submit(
                            task_type=task,
                            priority=priority,
                            llm=llm,
                            messages_or_prompt=messages,
                            agent_name=agent_name,
                            label=label,
                            overflow=overflow)
                except LaneOverflow as ov:
                    if hop + 1 == hop_limit:
                        raise RuntimeError("llm_call: overflow hop limit exceeded") from ov
                    instance = ov.target
                    overflow = ov.overflow
        except Exception as e:
            last_err = e
            if not _is_upstream_failure(e):
                # User error / non-retryable — fail fast, don't cooldown.
                raise
            from app.core.llm_client import _is_no_backend_error
            if _is_no_backend_error(e):
                # Model-specific: cool down ONLY this model on this provider so
                # the provider keeps serving its other models. resolve_llm picks
                # the next provider in the chain for this task.
                logger.warning(
                    "llm_call no-backend on %s (%s): %s — model-cooldown + Fallback",
                    instance.provider_name, instance.model, str(e)[:200])
                mark_model_unhealthy(instance.provider_name, instance.model)
            else:
                # Provider genuinely broken (connection/5xx) — cool it down whole.
                logger.warning(
                    "llm_call upstream-fail on %s (%s): %s — cooldown + Fallback",
                    instance.provider_name, instance.model, str(e)[:200])
                _cooldown_provider(instance.provider_name, f"upstream-fail: {str(e)[:120]}")
            # Loop continues; resolve_llm now skips the cooled-down model/provider.

    # The fallback chain is used up — this failure is final, so it is logged
    # here with the traceback the queue worker left to the caller (the upstream
    # stack rides along as the wrapper's __cause__).
    logger.error("llm_call: every provider for '%s' failed after %d attempts",
                 task, _LLM_CALL_MAX_ATTEMPTS, exc_info=last_err)
    raise RuntimeError(
        f"llm_call: every provider for '{task}' failed after "
        f"{_LLM_CALL_MAX_ATTEMPTS} attempts — last error: {last_err}")
