"""Provider Manager - orchestrates all LLM providers and their queues.

Loads PROVIDER_N_* blocks from the flattened config env, creates one
ProviderQueue (channel) per provider plus one per enabled image backend,
and routes LLM calls to the correct queue based on the LLM instance's provider.

Usage:
    from app.core.provider_manager import get_provider_manager

    pm = get_provider_manager()
    provider = pm.get_provider("OllamaLocal")
"""
import os
import threading
from typing import Any, Dict, List, Optional

from .provider import Provider
from .provider_queue import ProviderQueue

from app.core.log import get_logger
logger = get_logger("provider_mgr")

# gpu_type values that mean "any LLM channel" in find_channel()
_LLM_GPU_TYPES = {"ollama", "openai", "llm"}


class ProviderManager:
    """Orchestrates all providers and their queues."""

    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        # One channel per provider (key = provider name) plus one per image
        # backend (key = "backend:<name>").
        self.channels: Dict[str, ProviderQueue] = {}
        # Synthetic Provider objects backing per-backend image channels
        self._backend_providers: Dict[str, Provider] = {}
        # Serialize-group gates: keyed by serialize_group name. Channels
        # (LLM providers + image backends) with the same group share one
        # Semaphore(1) -> only ONE call at a time within the group (e.g. an
        # LLM and an image backend on the same physical GPU). Empty group =
        # no gate.
        self._serialize_gates: Dict[str, threading.Semaphore] = {}
        self._round_robin: int = 0  # Tiebreaker for equal-load channel selection

    def _serialize_gate(self, group: str) -> Optional[threading.Semaphore]:
        """Returns the shared Semaphore(1) for a serialize group ("" = None)."""
        group = (group or "").strip()
        if not group:
            return None
        return self._serialize_gates.setdefault(group, threading.Semaphore(1))

    def load_providers(self) -> None:
        """Scans the env for PROVIDER_N_* blocks. Stops when PROVIDER_N_NAME is missing."""
        self.providers.clear()
        self.channels.clear()
        self._backend_providers.clear()

        n = 1
        while True:
            prefix = f"PROVIDER_{n}_"
            name = os.environ.get(f"{prefix}NAME", "").strip()
            if not name:
                break

            ptype = os.environ.get(f"{prefix}TYPE", "").strip().lower()
            if not ptype:
                logger.warning("PROVIDER_%d '%s' has no TYPE, skipping", n, name)
                n += 1
                continue

            api_base = os.environ.get(f"{prefix}API_BASE", "").strip()
            api_key = os.environ.get(f"{prefix}API_KEY", "").strip()

            concurrent_str = os.environ.get(
                f"{prefix}MAX_CONCURRENT", "1").strip()
            max_concurrent = max(1, int(concurrent_str))

            timeout_str = os.environ.get(f"{prefix}TIMEOUT", "").strip()
            timeout = int(timeout_str) if timeout_str else None

            serialize_group = os.environ.get(f"{prefix}SERIALIZE_GROUP", "").strip()

            provider = Provider(
                name=name,
                type=ptype,
                api_base=api_base,
                api_key=api_key,
                max_concurrent=max_concurrent,
                timeout=timeout)

            self.providers[name] = provider

            # One channel per provider, keyed by the provider name.
            # chat_pause makes sense exactly when the provider shares local
            # GPU contention with something else — which is what a
            # serialize_group expresses. Cloud providers without a group
            # never pause their background tasks for streaming chats.
            pq = ProviderQueue(
                provider, queue_name=name,
                max_concurrent=max_concurrent,
                chat_pause_enabled=bool(serialize_group),
                serialize_group=serialize_group)
            pq._serialize_gate = self._serialize_gate(serialize_group)
            self.channels[name] = pq

            timeout_info = f", timeout={timeout}s" if timeout else ""
            group_info = f", serialize_group={serialize_group}" if serialize_group else ""
            logger.info("Loaded PROVIDER_%d '%s': type=%s, concurrent=%d%s%s",
                       n, name, ptype, max_concurrent, timeout_info, group_info)
            n += 1

        if not self.providers:
            logger.warning("No providers configured (PROVIDER_1_NAME not found in config)")

        # Channels for image backends — every backend gets its own channel
        # for serialization (one queue per URL/endpoint).
        self._load_backend_channels()

    def _load_backend_channels(self) -> None:
        """Creates one channel per enabled image backend.

        Reads SKILL_IMAGEGEN_N_* envs (written by app.core.config.update_env_from_config).
        Each enabled backend gets a synthetic Provider + ProviderQueue, keyed
        as ``backend:<name>`` in self.channels.
        """
        for i in range(1, 30):
            prefix = f"SKILL_IMAGEGEN_{i}_"
            name = os.environ.get(f"{prefix}NAME", "").strip()
            if not name:
                break
            enabled = os.environ.get(f"{prefix}ENABLED", "true").strip().lower() in ("true", "1", "yes")
            if not enabled:
                continue
            api_type = os.environ.get(f"{prefix}API_TYPE", "").strip().lower()
            # ALL registered backend types get a channel — cloud AND video
            # backends too, otherwise they are invisible in the queue panel
            # AND find_channel() could not route their jobs ("No channel for
            # gpu_type=..."). Derive from the registry instead of a hardcoded
            # list so new types can never fall out of sync again.
            from app.imagegen.registry import BACKEND_REGISTRY
            if api_type not in BACKEND_REGISTRY:
                continue
            api_url = os.environ.get(f"{prefix}API_URL", "").strip()
            if not api_url:
                continue

            mc_str = os.environ.get(f"{prefix}MAX_CONCURRENT", "1").strip()
            try:
                max_concurrent = max(1, int(mc_str))
            except ValueError:
                max_concurrent = 1
            # Backend HTTP timeout (configurable per backend). The queue task
            # timeout (synth.timeout) gets some headroom so the backend's own
            # HTTP timeout fires FIRST and the queue doesn't kill the task
            # early. Unset = None -> queue default 300 (backend uses its own
            # default 120).
            _to_str = os.environ.get(f"{prefix}TIMEOUT", "").strip()
            try:
                _backend_timeout = int(_to_str) if _to_str else None
            except ValueError:
                _backend_timeout = None
            synth_timeout = (_backend_timeout + 30) if _backend_timeout else None
            serialize_group = os.environ.get(f"{prefix}SERIALIZE_GROUP", "").strip()

            synth = Provider(
                name=name,
                type=api_type,
                api_base=api_url,
                api_key="",
                max_concurrent=max_concurrent,
                timeout=synth_timeout)
            # Real availability is tracked on the ImageBackend instance; we
            # default to True so find_channel() lists this channel. ChannelHealth
            # then enforces 'backend reachable' independently.
            synth.available = True

            self._backend_providers[name] = synth

            channel_key = f"backend:{name}"
            # Serialize-group gate: a backend with the same group as an LLM
            # provider (or another backend) shares its Semaphore(1) -> image
            # and chat calls serialize (e.g. one physical GPU).
            pq = ProviderQueue(
                synth, queue_name=channel_key,
                max_concurrent=max_concurrent,
                chat_pause_enabled=False,
                serialize_group=serialize_group)
            pq._serialize_gate = self._serialize_gate(serialize_group)
            self.channels[channel_key] = pq
            group_info = f", serialize_group={serialize_group}" if serialize_group else ""
            logger.info("  -> Backend-Channel %s: %s (%s, concurrent=%d%s)",
                        channel_key, api_url, api_type, max_concurrent, group_info)

    def get_systems_config(self) -> List[Dict[str, Any]]:
        """Builds systems list for dashboard grouping.

        Each LLM provider is one system. Each enabled image backend is its
        own system (own channel/queue). Backends without a channel (e.g.
        missing URL) are listed as standalone.

        Returns list of dicts: {name, providers, image_backends}.
        """
        systems: Dict[str, Dict[str, Any]] = {}
        for prov in self.providers.values():
            systems[prov.name] = {
                "name": prov.name,
                "providers": [prov.name],
                "image_backends": [],
            }
        # Each image backend = its own system (channel-owner)
        for be_name in self._backend_providers:
            systems[be_name] = {
                "name": be_name,
                "providers": [],
                "image_backends": [be_name],
            }
        # Enabled backends without a channel (not covered above)
        for i in range(1, 20):
            be_name = os.environ.get(f"SKILL_IMAGEGEN_{i}_NAME", "").strip()
            if not be_name:
                continue
            enabled = os.environ.get(f"SKILL_IMAGEGEN_{i}_ENABLED", "true").strip().lower() in ("true", "1", "yes")
            if not enabled:
                continue
            if be_name in systems:
                continue
            systems[be_name] = {"name": be_name,
                                "providers": [], "image_backends": [be_name]}

        return list(systems.values())

    def check_all_availability(self) -> int:
        """Checks availability of all providers. Returns count of available."""
        logger.info("Checking %d provider(s)...", len(self.providers))
        available_count = 0
        for provider in self.providers.values():
            if provider.check_availability():
                available_count += 1
        # Remove channels for unavailable providers (channel key = provider name)
        for name, p in self.providers.items():
            if not p.available:
                self.channels.pop(name, None)
        logger.info("%d/%d provider(s) available", available_count, len(self.providers))
        return available_count

    def refresh_availability(self) -> None:
        """Re-probt die Erreichbarkeit aller Provider und aktualisiert
        ``provider.available`` — OHNE Channels abzubauen (anders als
        :meth:`check_all_availability`). Wird periodisch vom Channel-Health-
        Poller aufgerufen, damit ein nach dem Start ausgeschalteter Host korrekt
        als nicht verfuegbar angezeigt wird (Queue-Panel) und vom Routing
        uebersprungen wird. Aktive Cooldowns werden respektiert."""
        for provider in list(self.providers.values()):
            try:
                prev = provider.available
                provider.check_availability()
                if prev != provider.available:
                    logger.info("Provider %s availability %s -> %s",
                                provider.name, prev, provider.available)
            except Exception as e:
                logger.debug("refresh_availability(%s) failed: %s", provider.name, e)

    def get_provider(self, name: str) -> Optional[Provider]:
        """Returns a provider by name."""
        return self.providers.get(name)

    def _find_channel_for_provider(self, provider_name: str) -> Optional[ProviderQueue]:
        """Returns the channel of a named LLM provider (channel key = name)."""
        return self.channels.get(provider_name)

    def get_queue_for_provider(self, provider_name: str) -> Optional[ProviderQueue]:
        """Returns the best LLM channel for a named provider."""
        return self._find_channel_for_provider(provider_name)

    def get_queue_for_instance(self, instance: Any) -> Optional[ProviderQueue]:
        """Returns the channel for the provider that an LLM instance belongs to."""
        provider_name = getattr(instance, "provider_name", "")
        if provider_name:
            return self._find_channel_for_provider(provider_name)
        return None

    def get_first_queue(self) -> Optional[ProviderQueue]:
        """Returns the first available channel of a real LLM provider (fallback)."""
        for pq in self.channels.values():
            if pq.provider.name in self.providers and pq.provider.available:
                return pq
        # Any available channel
        for pq in self.channels.values():
            if pq.provider.available:
                return pq
        # Anything at all
        if self.channels:
            return next(iter(self.channels.values()))
        return None

    def submit(
        self,
        task_type: str,
        priority: int,
        llm_instance: Any,
        llm: Any,
        messages_or_prompt: Any,
        agent_name: str = "") -> Any:
        """Routes an LLM task to the correct channel.

        Uses the provider from llm_instance to find the matching LLM channel.
        """
        pq = self.get_queue_for_instance(llm_instance)
        if not pq:
            # Dynamic fallback: find any LLM channel with least load
            provider = self.providers.get(getattr(llm_instance, "provider_name", ""))
            gpu_type = provider.type if provider else "openai"
            pq = self.find_channel(gpu_type)
        if not pq:
            pq = self.get_first_queue()
        if not pq:
            raise Exception("No channel available for LLM task")

        return pq.submit(task_type, priority, llm, messages_or_prompt,
                         agent_name)

    def register_chat_active(
        self,
        llm_instance: Any,
        agent_name: str, task_type: str = "chat_stream",
        label: str = "") -> str:
        """Registers chat active on the correct LLM channel.

        Returns task_id for register_chat_done().
        """
        pq = self.get_queue_for_instance(llm_instance)
        if not pq:
            pq = self.get_first_queue()
        if not pq:
            raise Exception("No channel available for chat registration")

        model = getattr(llm_instance, "model", "") if llm_instance else ""
        return pq.register_chat_active(agent_name, model=model,
                                        task_type=task_type, label=label)

    def register_chat_done(self, task_id: str) -> None:
        """Finds which provider queue owns this task_id and marks done."""
        for pq in self.channels.values():
            if task_id in pq._chat_tasks:
                pq.register_chat_done(task_id)
                return
        logger.warning("chat task %s not found in any channel", task_id)

    def register_chat_iteration(self, task_id: str,
                                 iteration: int, max_iterations: int) -> None:
        """Find owning channel and update iteration progress."""
        for pq in self.channels.values():
            if task_id in pq._chat_tasks:
                pq.register_chat_iteration(task_id, iteration, max_iterations)
                return

    def find_channel(self, gpu_type: str) -> Optional[ProviderQueue]:
        """Find the best channel for a task by backend/provider type and load.

        Args:
            gpu_type: Required channel type — an image-backend api_type
                (e.g. "a1111", "localai") or an LLM provider type
                ("ollama"/"openai"/"llm").

        Returns:
            Best matching ProviderQueue, or None if no match.

        Matching rules:
        - Exact type match: ``pq.provider.type == gpu_type`` (LLM provider
          type or the api_type of a backend channel's synthetic provider).
        - Cloud fallback: channels of real LLM providers whose type is NOT
          ollama/openai (anthropic/google/mistral/together/...) also match
          ANY LLM gpu_type ("ollama"/"openai"/"llm") — cloud providers can
          serve any LLM task.
        """
        from app.core.channel_health import is_healthy
        candidates = []
        for key, pq in self.channels.items():
            if not pq.provider.available:
                continue
            is_backend_channel = key.startswith("backend:")
            if pq.provider.type == gpu_type:
                pass  # exact type match
            elif (not is_backend_channel
                  and gpu_type in _LLM_GPU_TYPES
                  and pq.provider.type not in ("ollama", "openai")):
                pass  # cloud LLM provider serves any LLM gpu_type
            else:
                continue
            # Backend health check: skip channels whose backend is down
            # (auto-detected via channel_health).
            if not is_healthy(key):
                continue
            # Score: fewer pending tasks = better
            with pq._lock:
                pending = len(pq._pending_tasks) + len(pq._current_tasks)
            candidates.append((pending, key, pq))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        # Round-robin on equal load: alternate between channels with the same
        # load instead of always picking the first one.
        min_load = candidates[0][0]
        equal = [c for c in candidates if c[0] == min_load]
        if len(equal) > 1:
            self._round_robin += 1
            chosen = equal[self._round_robin % len(equal)]
            logger.debug("find_channel(%s): %d candidates with load=%d, round-robin -> %s",
                         gpu_type, len(equal), min_load, chosen[1])
            return chosen[2]
        return candidates[0][2]

    def submit_gpu_task(
        self,
        provider_name: str,
        task_type: str,
        priority: int,
        callable_fn,
        agent_name: str = "", label: str = "",
        gpu_type: str = "") -> Any:
        """Routes a GPU-slot task to the best available channel.

        Routing priority:
        1. ImageBackend channel: provider_name matches an image backend → ``backend:<name>``
        2. Dynamic routing: gpu_type set → find_channel() by type/load
        3. Fallback by provider name (channel key = provider name)
        """
        # 1. ImageBackend channel lookup: backend name → ``backend:<name>``
        if provider_name and provider_name in self._backend_providers:
            pq = self.channels.get(f"backend:{provider_name}")
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        # 2. Dynamic routing by channel type
        if gpu_type:
            pq = self.find_channel(gpu_type)
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        # 3. Fallback by provider name
        if provider_name:
            pq = self.channels.get(provider_name)
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        raise Exception(f"No channel for gpu_type='{gpu_type}', provider='{provider_name}'")

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a pending task across all channels."""
        for pq in self.channels.values():
            if pq.cancel_task(task_id):
                return True
        return False

    def has_pending_tasks(self) -> bool:
        """Returns True if any channel has pending tasks."""
        return any(pq.has_pending_tasks() for pq in self.channels.values())

    def get_combined_status(self) -> Dict[str, Any]:
        """Aggregated status across all channels."""
        from app.core.channel_health import is_healthy as _channel_is_healthy
        providers_status = {}
        all_chat = None
        all_recent = []

        for channel_key, pq in self.channels.items():
            status = pq.get_status()
            # Channel health: provider endpoint AND (for backend channels)
            # the bound backend must be reachable. is_healthy returns True
            # for non-backend channels (LLM runs directly on the provider
            # endpoint).
            status["healthy"] = bool(pq.provider.available) and _channel_is_healthy(
                channel_key)

            providers_status[pq._queue_name] = status

            if status["chat_active"]:
                all_chat = status["chat_active"]
            all_recent.extend(status["recent"])

        all_recent.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        all_recent = all_recent[:20]

        return {
            "providers": providers_status,
            "chat_active": all_chat,
            "recent": all_recent,
        }

    def list_all_models(self) -> Dict[str, Any]:
        """Lists available models from all providers.

        Returns:
            {"ProviderName": {"type": "ollama", "models": [...]}, ...}
        """
        result = {}
        for name, provider in self.providers.items():
            if provider.available:
                models = provider.list_models()
                result[name] = {
                    "type": provider.type,
                    "models": models,
                }
        return result

    def find_provider_for_model(self, model: str) -> Optional[Provider]:
        """Finds the first available provider that has the given model.

        Args:
            model: Model name (e.g. "mistral:7b")

        Returns:
            Provider if found, None otherwise
        """
        for provider in self.providers.values():
            if provider.available and provider.has_model(model):
                return provider
        # If no available provider has it, check unavailable ones too
        for provider in self.providers.values():
            if provider.has_model(model):
                return provider
        return None

    def reload(self) -> Dict[str, Any]:
        """Reloads providers from the flattened config env and recreates queues."""
        old_count = len(self.providers)
        self.load_providers()
        available = self.check_all_availability()
        return {
            "old_count": old_count,
            "new_count": len(self.providers),
            "available": available,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_provider_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Returns the global ProviderManager singleton."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager


def initialize_provider_manager() -> ProviderManager:
    """Initializes providers and checks availability. Called at startup."""
    global _provider_manager
    _provider_manager = ProviderManager()
    _provider_manager.load_providers()
    _provider_manager.check_all_availability()
    return _provider_manager


def reload_provider_manager() -> Dict[str, Any]:
    """Reloads providers from the flattened config env."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager.reload()
