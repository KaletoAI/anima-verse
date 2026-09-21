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
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from .provider import Provider
from .provider_queue import ProviderQueue

from app.core.log import get_logger
logger = get_logger("provider_mgr")

# gpu_type values that mean "any LLM channel" in find_channel()
_LLM_GPU_TYPES = {"ollama", "openai", "llm"}

# Headroom on top of a backend's own job budget before the queue watchdog
# declares the task dead. The backend has to give up FIRST — its own timeout
# (or its max_wait/max_queue_wait polling budget) is what knows whether the
# job is lost, and it answers typed (BackendBusyError = load, no cooldown).
_WATCHDOG_HEADROOM_S = 60


class NoBackendChannelError(RuntimeError):
    """A job names an image/video/mesh backend that has no queue channel.

    A backend without a channel is a backend the config disabled (or one whose
    URL is missing). Its job must NOT be routed onto the channel of another
    backend of the same api_type: that channel belongs to a different
    URL/GPU, so the job would occupy a foreign GPU slot while running against
    an endpoint that channel never serializes (IMG-5). Failing here names the
    real cause instead.
    """


class ProviderManager:
    """Orchestrates all providers and their queues."""

    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        # One channel per provider (key = provider name) plus one per image
        # backend (key = "backend:<name>").
        self.channels: Dict[str, ProviderQueue] = {}
        # Synthetic Provider objects backing per-backend image channels
        self._backend_providers: Dict[str, Provider] = {}
        # Every CONFIGURED image/video/mesh backend name — including the ones
        # that got no channel (disabled, no URL, unknown type). submit_gpu_task
        # uses it to tell "this is a backend of ours without a channel" apart
        # from "this name is not a backend at all".
        self._known_backend_names: set = set()
        # Serialize-group gates: keyed by serialize_group name. Channels
        # (LLM providers + image backends) with the same group share one
        # Semaphore(1) -> only ONE call at a time within the group (e.g. an
        # LLM and an image backend on the same physical GPU). Empty group =
        # no gate.
        self._serialize_gates: Dict[str, threading.Semaphore] = {}
        # Every queue object ever built, keyed by channel key. A reload (and
        # check_all_availability, which drops channels of unreachable
        # providers) must never orphan a queue that still runs tasks — the
        # replacement would start with all its concurrency slots free. Busy
        # queues are therefore kept here and re-adopted; idle ones of channels
        # that no longer exist are pruned.
        self._queues: Dict[str, ProviderQueue] = {}
        self._round_robin: int = 0  # Tiebreaker for equal-load channel selection

    def _serialize_gate(self, group: str) -> Optional[threading.Semaphore]:
        """Returns the shared Semaphore(1) for a serialize group ("" = None)."""
        group = (group or "").strip()
        if not group:
            return None
        return self._serialize_gates.setdefault(group, threading.Semaphore(1))

    def load_providers(self) -> None:
        """Scans the env for PROVIDER_N_* blocks. Stops when PROVIDER_N_NAME is missing.

        Channels whose key survives the reload are ADOPTED, not rebuilt: a
        fresh ProviderQueue starts with zero active slots while the old object
        still runs its in-flight tasks — an admin save mid-job then admits a
        second task onto a busy ``concurrent=1`` backend (observed 2026-08-03,
        double mesh run ending in gateway timeouts). See
        :meth:`ProviderQueue.reconfigure`.

        The maps are built LOCALLY and rebound in ONE step at the end: readers
        (worker threads, the event loop) iterate them without a lock, and a
        ``clear()`` + refill lets them see an empty or half-filled map — a chat
        registration looked up in that moment is simply not found and its lane
        leaks (LLM-15). A rebind is atomic for those readers.
        """
        new_providers: Dict[str, Provider] = {}
        new_channels: Dict[str, ProviderQueue] = {}

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

            new_providers[name] = provider

            # One channel per provider, keyed by the provider name.
            # chat_pause makes sense exactly when the provider shares local
            # GPU contention with something else — which is what a
            # serialize_group expresses. Cloud providers without a group
            # never pause their background tasks for streaming chats.
            self._channel(name, provider, new_channels,
                          max_concurrent=max_concurrent,
                          chat_pause_enabled=bool(serialize_group),
                          serialize_group=serialize_group)

            timeout_info = f", timeout={timeout}s" if timeout else ""
            group_info = f", serialize_group={serialize_group}" if serialize_group else ""
            logger.info("Loaded PROVIDER_%d '%s': type=%s, concurrent=%d%s%s",
                       n, name, ptype, max_concurrent, timeout_info, group_info)
            n += 1

        if not new_providers:
            logger.warning("No providers configured (PROVIDER_1_NAME not found in config)")

        # Channels for image backends — every backend gets its own channel
        # for serialization (one queue per URL/endpoint).
        new_backend_providers, known_backend_names = self._load_backend_channels(
            new_channels)

        self.providers = new_providers
        self.channels = new_channels
        self._backend_providers = new_backend_providers
        self._known_backend_names = known_backend_names
        self._prune_queues()

    def _channel(self, key: str, provider: Provider,
                 channels: Dict[str, ProviderQueue], *,
                 max_concurrent: int, chat_pause_enabled: bool,
                 serialize_group: str) -> ProviderQueue:
        """One channel for ``key`` — reusing a surviving queue object so
        in-flight tasks keep holding their concurrency slots across a config
        reload; only a genuinely new key gets a fresh queue."""
        gate = self._serialize_gate(serialize_group)
        pq = self._queues.get(key)
        if pq is not None:
            pq.reconfigure(provider, max_concurrent=max_concurrent,
                           chat_pause_enabled=chat_pause_enabled,
                           serialize_group=serialize_group,
                           serialize_gate=gate)
        else:
            pq = ProviderQueue(provider, queue_name=key,
                               max_concurrent=max_concurrent,
                               chat_pause_enabled=chat_pause_enabled,
                               serialize_group=serialize_group)
            pq._serialize_gate = gate
        self._queues[key] = pq
        channels[key] = pq
        return pq

    def _prune_queues(self) -> None:
        """Forgets remembered queues of channels that no longer exist AND are
        idle. A busy one stays: it must be re-adopted if its channel comes
        back, so its running task keeps holding the concurrency slot."""
        for key in [k for k in self._queues if k not in self.channels]:
            if self._queues[key].is_busy():
                continue
            self._queues.pop(key, None)

    def _load_backend_channels(
            self, channels: Dict[str, ProviderQueue]
    ) -> Tuple[Dict[str, Provider], set]:
        """Creates one channel per enabled image backend.

        Reads SKILL_IMAGEGEN_N_* envs (written by app.core.config.update_env_from_config).
        Each enabled backend gets a synthetic Provider + ProviderQueue, keyed
        as ``backend:<name>`` in ``channels``.

        Returns ``(backend_providers, known_backend_names)`` — the second set
        holds EVERY configured backend name, channel or not, so
        :meth:`submit_gpu_task` can tell a channel-less backend of ours apart
        from a name that is no backend at all.
        """
        backend_providers: Dict[str, Provider] = {}
        known_names: set = set()
        # Same upper bound the image service loads backends up to — otherwise a
        # backend past the bound loads but never gets a queue channel.
        from app.core.config import MAX_IMAGE_BACKENDS
        for i in range(1, MAX_IMAGE_BACKENDS + 1):
            prefix = f"SKILL_IMAGEGEN_{i}_"
            name = os.environ.get(f"{prefix}NAME", "").strip()
            if not name:
                break
            known_names.add(name)
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
            # budget runs out FIRST and the queue doesn't kill the task early.
            # Unset = None -> queue default 300 (backend uses its own
            # default 120).
            _to_str = os.environ.get(f"{prefix}TIMEOUT", "").strip()
            try:
                _backend_timeout = int(_to_str) if _to_str else None
            except ValueError:
                _backend_timeout = None
            synth_timeout = self._watchdog_timeout(api_type, prefix,
                                                   _backend_timeout)
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

            backend_providers[name] = synth

            channel_key = f"backend:{name}"
            # Serialize-group gate: a backend with the same group as an LLM
            # provider (or another backend) shares its Semaphore(1) -> image
            # and chat calls serialize (e.g. one physical GPU).
            self._channel(channel_key, synth, channels,
                          max_concurrent=max_concurrent,
                          chat_pause_enabled=False,
                          serialize_group=serialize_group)
            group_info = f", serialize_group={serialize_group}" if serialize_group else ""
            logger.info("  -> Backend-Channel %s: %s (%s, concurrent=%d%s, watchdog=%s)",
                        channel_key, api_url, api_type, max_concurrent, group_info,
                        f"{synth_timeout}s" if synth_timeout else "queue default")

        return backend_providers, known_names

    @staticmethod
    def _watchdog_timeout(api_type: str, env_prefix: str,
                          backend_timeout: Optional[int]) -> Optional[int]:
        """The queue watchdog for ONE backend channel, from the job budget.

        The HTTP ``timeout`` only bounds a single request. A polling backend
        (mesh/video/civitai) sends its request in seconds and then POLLS for
        the result: its real budget is ``max_queue_wait`` (time allowed to sit
        in the gateway's queue) plus ``max_wait`` (time allowed to render).
        Measuring such a job against ``timeout + 30`` declared a legitimate
        600-s video dead after 90 s, threw the finished MP4 away and cooled a
        perfectly healthy backend down for 5 minutes (IMG-2).

        So: ``max(timeout, max_queue_wait + max_wait) + headroom``. The
        numbers are read off a throwaway backend INSTANCE, because the
        defaults differ per backend class (600 / 900 / 300) and only the class
        knows them — the constructors parse env and nothing else, no network,
        no state. A backend type without those attributes keeps the plain
        HTTP-timeout rule.
        """
        from app.imagegen.registry import BACKEND_REGISTRY
        max_wait = 0
        max_queue_wait = 0
        backend_class = BACKEND_REGISTRY.get(api_type)
        if backend_class is not None:
            try:
                probe = backend_class(name="_budget_probe", api_url="",
                                      cost=0.0, env_prefix=env_prefix)
                max_wait = int(getattr(probe, "max_wait", 0) or 0)
                max_queue_wait = int(getattr(probe, "max_queue_wait", 0) or 0)
            except Exception as e:
                logger.debug("watchdog budget probe for %s failed: %s", api_type, e)
        job_budget = max_queue_wait + max_wait
        if job_budget <= 0:
            return (backend_timeout + 30) if backend_timeout else None
        return max(backend_timeout or 0, job_budget) + _WATCHDOG_HEADROOM_S

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
        from app.core.config import MAX_IMAGE_BACKENDS
        for i in range(1, MAX_IMAGE_BACKENDS + 1):
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
        # Remove channels for unavailable providers (channel key = provider
        # name). Rebound in one step, not popped one by one: readers iterate
        # this dict without a lock (LLM-15). The queue objects themselves stay
        # in self._queues, which is where a running registration is found.
        unavailable = {name for name, p in self.providers.items() if not p.available}
        if unavailable:
            self.channels = {key: pq for key, pq in self.channels.items()
                             if key not in unavailable}
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

    def provider_name_for(self, llm: Any) -> str:
        """The provider a resolved LLM belongs to — the ONE place that answers
        it, for an ``LLMInstance`` and for a bare ``LLMClient`` alike.

        An ``LLMInstance`` carries ``provider_name``, and so does every client
        ``LLMInstance.create_llm()`` hands out — the router stamps it there,
        because a client knows only its endpoint and its provider is the one
        thing it cannot work out for itself.

        The endpoint match below is therefore the FALLBACK, for an object that
        did not come from the router. Its limit is in its nature: it returns
        the FIRST provider that uses that base URL, and several providers on
        one AI-Hub URL (one per alias or key) are indistinguishable by
        endpoint — nothing in the object says which of them it was built from.
        That is the reason the stamp exists rather than a smarter match. The
        lane pool a call lands on is derived from this name, so the answer has
        to come from ONE place, which is this one. Returns "" when nothing
        matches.
        """
        name = (getattr(llm, "provider_name", "") or "").strip()
        if name:
            return name
        api_base = (getattr(llm, "openai_api_base", "")
                    or getattr(llm, "base_url", "")
                    or "").strip().rstrip("/")
        if not api_base:
            return ""
        for provider_name, provider in self.providers.items():
            if (provider.api_base or "").rstrip("/") == api_base:
                return provider_name
        return ""

    def get_queue_for_instance(self, instance: Any) -> Optional[ProviderQueue]:
        """Returns the channel for the provider that an LLM instance belongs to.

        Resolves through ``provider_name_for``, so a bare ``LLMClient`` finds
        its channel by endpoint instead of falling through to the first one.
        """
        provider_name = self.provider_name_for(instance)
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
        """Finds which provider queue owns this task_id and marks done.

        Searches ``_queues``, not ``channels``: a handle must go back exactly
        where it was taken. ``channels`` is the ROUTING view and a provider
        that failed its health probe during a reload loses its entry there
        (:meth:`check_all_availability`) while its queue keeps running — the
        registration made on it would then never be found, its cache lane
        would stay busy for the lifetime of the process and the queue would
        stay paused (LLM-1). ``_queues`` is the LIFECYCLE view and holds every
        queue ever built.
        """
        for pq in self._queues.values():
            if task_id in pq._chat_tasks:
                pq.register_chat_done(task_id)
                return
        logger.warning("chat task %s not found in any channel", task_id)

    def chat_lane_info(self, task_id: str) -> Tuple[Optional[int], str]:
        """``(lane number, cache key)`` of a streaming registration.

        The streaming path bypasses the queue and writes its own log lines, so
        it has to ask for the lane its registration took. Unknown task id or a
        registration that runs unlaned gives ``(None, "")``.
        """
        for pq in self._queues.values():
            task = pq._chat_tasks.get(task_id)
            if task is None:
                continue
            handle = task._lane_handle
            return ((handle.lane_id if handle is not None else None),
                    getattr(task, "_cache_key", "") or "")
        return (None, "")

    @contextmanager
    def nested_call_lane(self, chat_task_id: str, llm_instance: Any,
                         cache_key: str, label: str = ""):
        """A lane for an LLM call made from INSIDE a running chat turn
        (plan-cache-lanes.md § 6, item 7a — R6 is its precondition).

        The rp_first tool decision calls its LLM directly, past the queue. On
        a one-model host that is a second prompt beginning on exactly the pool
        whose cache the turn is building, so it needs a lane of its own.

        WHICH POOL IT LANDS ON DECIDES EVERYTHING, so it is resolved FIRST —
        and it is resolved from the LLM this call really uses. That is an
        ``LLMClient`` (``StreamingAgent.tool_llm``), which carries the
        provider name the router stamped on it; ``provider_name_for`` reads
        that name, and falls back to the endpoint for anything the router did
        not build. Taking the first channel instead — what a missing name used
        to fall through to — would put every nested call on a channel that, in
        a world with more than one provider, serves neither the tool alias nor
        the chat model: the same-pool test below would be answered against a
        phantom and the suspend would never happen.

        No channel at all for that endpoint = **unknown pool**. The lane is
        still taken (on the fallback channel, because something has to run the
        wait), but under a pool key that names no provider: naming the
        fallback channel would invent a ``provider/model`` pair no channel
        serves and show it to the admin in ``snapshot()``. An unknown pool is
        never "the same pool", so nothing is suspended either.

        The two real cases:

        * **Another pool** (the normal topology — the chat model is
          `for-her-darkside-12b`, the tool alias is `tool`, different hosts):
          the turn KEEPS its lane and the nested call takes one over there.
          Suspending here would be pure loss — the conversation's lane goes to
          whoever is waiting on that pool, its cache is evicted, and the turn
          then waits for that stranger to finish. Nothing is won: the two
          calls do not share a pool and never contend.
        * **The same pool**: R6, in this order —
            1. the chat registration hands its lane back — without this a
               one-lane pool would wait for itself,
            2. the nested call takes a lane for ITS key, carrying the turn's
               lane id (R1's first step then hands that very lane back to it —
               anything else stalls a 2-lane pool whose other lane is busy, or
               evicts the second conversation) and the turn's arrival stamp
               (or the call would be the youngest waiter at every suspend and
               lose every pass),
            3. it gives that lane back,
            4. the registration takes a lane again, with the same two values —
               and only then does the turn go on.
          Step 4 waits: whoever took the lane in between now holds it. That is
          the same trade the tool executor in routes/chat.py has always made
          with the queue, and it is the point — on one pool the nested prompt
          does not run next to the conversation, it runs instead of it, for
          its duration.

        **The nested call inherits the OWNER's lane priority**, exactly as the
        resume does. A fixed ``Priority.CHAT`` would let a THOUGHT turn's tool
        call ignore R3 and rank level with — in R2 even ahead of — a user's
        parked conversation, which is the one thing the lane priority exists
        to keep apart (``llm_lanes.lane_priority_for``). Nothing stalls by
        inheriting: R1's first step gives the call its own lane back at once,
        whatever its class. Without an owner (no registration found) it is an
        ordinary background call, ``Priority.NORMAL``.
        """
        from .llm_lanes import pool_key_for
        from .llm_queue import Priority

        model = getattr(llm_instance, "model", "") or ""
        target = self.get_queue_for_instance(llm_instance)
        if target is not None:
            pool_key = pool_key_for(target.provider.name, model)
        else:
            logger.debug(
                "nested call for %r: no channel serves %r — running it as an "
                "unknown pool (no suspend)", cache_key,
                getattr(llm_instance, "openai_api_base", "")
                or getattr(llm_instance, "base_url", "") or "?")
            # No provider name goes into the key: "?/model" is visibly not a
            # pool any channel serves, and it can never equal the owner's.
            pool_key = pool_key_for("", model)
            target = self.get_first_queue()

        owner = None
        if chat_task_id:
            for pq in self._queues.values():
                if chat_task_id in pq._chat_tasks:
                    owner = pq
                    break
        owner_pool, owner_priority = ("", int(Priority.NORMAL))
        if owner is not None:
            owner_pool, owner_priority = owner.chat_lane_context(chat_task_id)
        same_pool = bool(owner_pool) and owner_pool == pool_key
        suspended = owner.suspend_chat_lane(chat_task_id) if same_pool else None
        own_lane, arrived = suspended if suspended else (None, None)
        handle = None
        try:
            if target is not None:
                handle = target.acquire_nested_lane(
                    pool_key, cache_key, owner_priority, label=label,
                    arrived=arrived, own_lane=own_lane)
            yield handle
        finally:
            if handle is not None:
                handle.release()
            if suspended is not None and owner is not None:
                owner.resume_chat_lane(chat_task_id, own_lane=own_lane,
                                       arrived=arrived)

    def register_chat_iteration(self, task_id: str,
                                 iteration: int, max_iterations: int) -> None:
        """Find owning channel and update iteration progress."""
        for pq in self._queues.values():
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

        A named backend NEVER falls through to steps 2/3: ``gpu_type`` is the
        api_type, so find_channel() would hand the job the channel of a
        DIFFERENT backend of the same type — another URL, another GPU. It
        would then block that backend's slot while running unserialized
        against its own endpoint (IMG-5). A backend of ours without a channel
        is disabled or has no URL, and that is what the caller hears.
        """
        # 1. ImageBackend channel lookup: backend name → ``backend:<name>``
        if provider_name and provider_name in self._backend_providers:
            pq = self.channels.get(f"backend:{provider_name}")
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)
        if provider_name and provider_name in self._known_backend_names:
            raise NoBackendChannelError(
                f"Backend '{provider_name}' has no queue channel "
                f"(disabled or without API URL) — no job runs on it")

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

    def force_resume_all_chats(self) -> List[Dict[str, Any]]:
        """Emergency exit: releases EVERY chat registration on EVERY queue.

        The one entry point behind ``POST /queue/force-resume``. It walks
        ``_queues`` (not ``channels``): a registration can sit on a queue whose
        channel a reload dropped, and that is exactly the state the emergency
        exit exists for. Each queue releases its own registrations under its
        own lock, in the order of the stale cleanup — cache lane first, then
        the serialize gate — so nothing is left holding either (LLM-2).

        Returns one dict per released registration:
        ``{"provider": <channel key>, "chat_task": <id>, "agent": <name>}``.
        """
        released: List[Dict[str, Any]] = []
        for key, pq in list(self._queues.items()):
            entries = pq.force_release_chats()
            for entry in entries:
                released.append({"provider": key, **entry})
            if entries:
                logger.warning("Force-resume: %s — %d chat(s) cleared",
                               key, len(entries))
        return released

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
