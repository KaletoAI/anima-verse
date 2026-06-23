"""Provider Manager - orchestrates all LLM providers and their queues.

Loads PROVIDER_N_* blocks from .env, creates a ProviderQueue per provider,
and routes LLM calls to the correct queue based on the LLM instance's provider.

Usage:
    from app.core.provider_manager import get_provider_manager

    pm = get_provider_manager()
    provider = pm.get_provider("OllamaLocal")
    vram = pm.poll_all_vram()
"""
import os
import threading
from typing import Any, Dict, List, Optional

from .provider import GpuConfig, Provider
from .provider_queue import ProviderQueue

from app.core.log import get_logger
logger = get_logger("provider_mgr")


class ProviderManager:
    """Orchestrates all providers and their queues."""

    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        self.channels: Dict[str, ProviderQueue] = {}  # keyed by "Provider:gpuN" or "backend:<name>"
        # Backwards-compat aliases (point to same objects in channels)
        self.queues: Dict[str, ProviderQueue] = {}
        self.gpu_queues: Dict[str, ProviderQueue] = {}
        # Synthetic Provider objects backing per-backend ComfyUI/A1111 channels
        self._backend_providers: Dict[str, Provider] = {}
        # GPU-Gruppen-Gates: keyed by GpuConfig.label. Channels (LLM-Provider +
        # Image-Backends) mit gleichem label teilen ein Semaphore(1) → nur EIN
        # Call gleichzeitig auf der physischen GPU. Leeres label = kein Gate.
        self._gpu_gates: Dict[str, threading.Semaphore] = {}
        self._round_robin: int = 0  # Tiebreaker for equal-load channel selection

    def load_providers(self) -> None:
        """Scans .env for PROVIDER_N_* blocks. Stops when PROVIDER_N_NAME is missing."""
        self.providers.clear()
        self.channels.clear()
        self.queues.clear()
        self.gpu_queues.clear()
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

            beszel_system_id = os.environ.get(f"{prefix}BESZEL_SYSTEM_ID", "").strip()

            # Per-GPU config: PROVIDER_X_GPU0_VRAM, PROVIDER_X_GPU0_DEVICE, PROVIDER_X_GPU0_TYPE
            gpu_configs = []
            gi = 0
            while True:
                gpu_vram_str = os.environ.get(f"{prefix}GPU{gi}_VRAM", "").strip()
                if not gpu_vram_str:
                    break
                gpu_vram = int(float(gpu_vram_str) * 1024)
                gpu_device = os.environ.get(f"{prefix}GPU{gi}_DEVICE", "").strip()
                gpu_types_str = os.environ.get(f"{prefix}GPU{gi}_TYPE", "").strip().lower()
                gpu_types = [t.strip() for t in gpu_types_str.split(",") if t.strip()] if gpu_types_str else []
                gpu_label = os.environ.get(f"{prefix}GPU{gi}_LABEL", "").strip()
                gpu_match_name = os.environ.get(f"{prefix}GPU{gi}_MATCH_NAME", "").strip()
                gpu_mc_str = os.environ.get(f"{prefix}GPU{gi}_MAX_CONCURRENT", "1").strip()
                gpu_max_concurrent = max(1, int(gpu_mc_str))
                gpu_configs.append(GpuConfig(
                    index=gi,
                    vram_mb=gpu_vram,
                    device=gpu_device,
                    types=gpu_types,
                    label=gpu_label,
                    match_name=gpu_match_name,
                    max_concurrent=gpu_max_concurrent))
                gi += 1

            # Compute LLM VRAM budget from GPU configs (GPUs with LLM-related types)
            llm_types = {"ollama", "openai", "llm"}
            # GPU-Tracking ist nur fuer ``ollama`` zwingend (Unload-Logik
            # bei VRAM-Knappheit). Alle anderen Provider-Typen — Cloud
            # (anthropic/google/mistral/together) ebenso wie OpenAI-kompatible
            # Gateways/Proxies (LiteLLM, llama-swap, vLLM) — laufen auch ohne
            # GPU-Eintrag sauber.
            if gpu_configs:
                vram_mb = sum(g.vram_mb for g in gpu_configs if set(g.types) & llm_types)
            elif ptype == "ollama":
                logger.warning("PROVIDER_%d '%s' has no GPU config (PROVIDER_%d_GPU0_VRAM missing) — VRAM-Unload deaktiviert",
                              n, name, n)
                vram_mb = None
            else:
                vram_mb = None

            # Auto-derive specs from GPU configs (e.g. "16 GB + 32 GB")
            system_specs = ""
            if gpu_configs:
                parts = [f"{g.vram_mb // 1024} GB" for g in gpu_configs]
                system_specs = " + ".join(parts) if len(parts) > 1 else parts[0]

            provider = Provider(
                name=name,
                type=ptype,
                api_base=api_base,
                api_key=api_key,
                vram_mb=vram_mb or None,
                max_concurrent=max_concurrent,
                timeout=timeout,
                beszel_system_id=beszel_system_id,
                gpu_configs=gpu_configs,
                system=name,
                system_specs=system_specs)

            self.providers[name] = provider

            # Create one channel per GPU
            if gpu_configs:
                for g in gpu_configs:
                    channel_key = f"{name}:gpu{g.index}"
                    has_llm = bool(set(g.types) & llm_types)
                    pq = ProviderQueue(
                        provider, queue_name=channel_key,
                        max_concurrent=g.max_concurrent,
                        chat_pause_enabled=has_llm,
                        gpu_indices=[g.index])
                    self.channels[channel_key] = pq
                    # GPU-Gruppen-Gate: gleicher label (auch ueber einen
                    # Image-Backend hinweg) → gemeinsames Semaphore(1).
                    _lbl = (g.label or "").strip()
                    if _lbl:
                        pq._gpu_gate = self._gpu_gates.setdefault(_lbl, threading.Semaphore(1))
                    # Backwards-compat: first LLM GPU → queues[name], first comfyui GPU → gpu_queues[name]
                    if has_llm and name not in self.queues:
                        self.queues[name] = pq
                    if "comfyui" in g.types and name not in self.gpu_queues:
                        self.gpu_queues[name] = pq
                    g_label = g.label or f"GPU {g.index}"
                    logger.info("  -> Channel %s: %s (%s, %dMB, concurrent=%d, chat_pause=%s)",
                               channel_key, g_label, ",".join(g.types), g.vram_mb, g.max_concurrent, has_llm)
            else:
                # Kein GPU-Eintrag konfiguriert → ein virtueller Channel.
                # chat_pause bleibt aus, weil ohne lokale GPU-Kontention nichts
                # zu pausieren ist. Wer ueber einen Gateway/Proxy auf eine
                # lokale GPU geht, traegt die GPU-Slots explizit ein und
                # bekommt den Normalpfad oben mit chat_pause_enabled=has_llm.
                pq = ProviderQueue(
                    provider, queue_name=name,
                    max_concurrent=max_concurrent,
                    chat_pause_enabled=False,
                    gpu_indices=[0])
                self.channels[name] = pq
                self.queues[name] = pq

            vram_info = f", vram={vram_mb}MB" if vram_mb else ""
            timeout_info = f", timeout={timeout}s" if timeout else ""
            beszel_info = f", beszel={beszel_system_id}" if beszel_system_id else ""
            gpus_info = ""
            if gpu_configs:
                gpu_parts = [f"GPU{g.index}:{g.vram_mb}MB({','.join(g.types)},mc={g.max_concurrent})" for g in gpu_configs]
                gpus_info = f", gpus=[{', '.join(gpu_parts)}]"
            logger.info("Loaded PROVIDER_%d '%s': type=%s%s%s%s%s",
                       n, name, ptype, vram_info, timeout_info,
                       beszel_info, gpus_info)
            n += 1

        if not self.providers:
            logger.warning("No providers configured (PROVIDER_1_NAME not found in .env)")

        # Channels fuer ComfyUI/A1111 Backends — jedes Backend bekommt seinen
        # eigenen Channel zur Serialisierung (Queue pro URL/Endpoint).
        self._load_backend_channels()

    def _load_backend_channels(self) -> None:
        """Creates one channel per enabled ComfyUI/A1111 image backend.

        Reads SKILL_IMAGEGEN_N_* envs (written by app.core.config.update_env_from_config).
        Each enabled local backend gets a synthetic Provider + ProviderQueue, keyed
        as ``backend:<name>`` in self.channels. Optional per-backend GPU metadata
        (vram/label/device/match_name from SKILL_IMAGEGEN_N_GPUi_*) populates
        gpu_configs for VRAM-display and Beszel mapping only — the channel count
        stays 1 per backend.
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
            # ALLE Image-Backend-Typen bekommen einen Channel — auch Cloud
            # (civitai/together/mammouth), sonst sind sie im Queue-Panel
            # unsichtbar UND die Channel-Auswahl (find_channel) faellt fuer
            # einen Cloud-Backend-Job faelschlich auf einen ComfyUI-Channel.
            if api_type not in ("comfyui", "a1111", "civitai", "together", "openai_chat", "openai_diffusion"):
                continue
            api_url = os.environ.get(f"{prefix}API_URL", "").strip()
            if not api_url:
                continue

            mc_str = os.environ.get(f"{prefix}MAX_CONCURRENT", "1").strip()
            try:
                max_concurrent = max(1, int(mc_str))
            except ValueError:
                max_concurrent = 1
            beszel_id = os.environ.get(f"{prefix}BESZEL_SYSTEM_ID", "").strip()

            gpu_configs: List[GpuConfig] = []
            gi = 0
            while True:
                gv = os.environ.get(f"{prefix}GPU{gi}_VRAM", "").strip()
                if not gv:
                    break
                try:
                    vmb = int(float(gv) * 1024)
                except ValueError:
                    break
                gpu_configs.append(GpuConfig(
                    index=gi,
                    vram_mb=vmb,
                    device=os.environ.get(f"{prefix}GPU{gi}_DEVICE", "").strip(),
                    types=[api_type],
                    label=os.environ.get(f"{prefix}GPU{gi}_LABEL", "").strip(),
                    match_name=os.environ.get(f"{prefix}GPU{gi}_MATCH_NAME", "").strip(),
                    max_concurrent=max_concurrent))
                gi += 1
            if not gpu_configs:
                # Implicit single-GPU placeholder so find_channel() matches
                # the backend channel for gpu_type='comfyui'/'a1111'. VRAM 0
                # disables VRAM-capacity filtering — the backend itself decides.
                gpu_configs.append(GpuConfig(
                    index=0, vram_mb=0, device="", types=[api_type],
                    label="", match_name="", max_concurrent=max_concurrent))

            vram_total = sum(g.vram_mb for g in gpu_configs) or None
            system_specs = ""
            if any(g.vram_mb for g in gpu_configs):
                parts = [f"{g.vram_mb // 1024} GB" for g in gpu_configs if g.vram_mb]
                system_specs = " + ".join(parts) if len(parts) > 1 else parts[0]

            synth = Provider(
                name=name,
                type=api_type,
                api_base=api_url,
                api_key="",
                vram_mb=vram_total,
                max_concurrent=max_concurrent,
                beszel_system_id=beszel_id,
                gpu_configs=gpu_configs,
                system=name,
                system_specs=system_specs)
            # Real availability is tracked on the ImageBackend instance; we
            # default to True so find_channel() lists this channel. ChannelHealth
            # then enforces 'backend reachable' independently.
            synth.available = True

            self._backend_providers[name] = synth

            channel_key = f"backend:{name}"
            pq = ProviderQueue(
                synth, queue_name=channel_key,
                max_concurrent=max_concurrent,
                chat_pause_enabled=False,
                gpu_indices=[g.index for g in gpu_configs])
            self.channels[channel_key] = pq
            # GPU-Gruppen-Gate: hat eine der Backend-GPUs ein label, teilt sich
            # dieses Backend das Semaphore(1) mit allen Channels (LLM + Image)
            # desselben labels → Bild + Chat serialisieren auf der GPU.
            _lbl = next(((gc.label or "").strip() for gc in gpu_configs if (gc.label or "").strip()), "")
            if _lbl:
                pq._gpu_gate = self._gpu_gates.setdefault(_lbl, threading.Semaphore(1))
            logger.info("  -> Backend-Channel %s: %s (%s, concurrent=%d)",
                        channel_key, api_url, api_type, max_concurrent)

    def get_systems_config(self) -> List[Dict[str, Any]]:
        """Builds systems list for dashboard grouping.

        Each LLM provider is one system. Each enabled ComfyUI/A1111 backend is
        its own system (own channel/queue). Cloud image backends without a
        local channel are listed as standalone.

        Returns list of dicts: {name, specs, providers, image_backends}.
        """
        systems: Dict[str, Dict[str, Any]] = {}
        for prov in self.providers.values():
            systems[prov.name] = {
                "name": prov.name,
                "specs": prov.system_specs,
                "providers": [prov.name],
                "image_backends": [],
            }
        # Each local image backend = its own system (channel-owner)
        for be_name, synth in self._backend_providers.items():
            systems[be_name] = {
                "name": be_name,
                "specs": synth.system_specs or synth.type,
                "providers": [],
                "image_backends": [be_name],
            }
        # Cloud backends (not covered above)
        for i in range(1, 20):
            be_name = os.environ.get(f"SKILL_IMAGEGEN_{i}_NAME", "").strip()
            if not be_name:
                continue
            enabled = os.environ.get(f"SKILL_IMAGEGEN_{i}_ENABLED", "true").strip().lower() in ("true", "1", "yes")
            if not enabled:
                continue
            if be_name in systems:
                continue
            systems[be_name] = {"name": be_name, "specs": "Cloud",
                                "providers": [], "image_backends": [be_name]}

        return list(systems.values())

    def check_all_availability(self) -> int:
        """Checks availability of all providers. Returns count of available."""
        logger.info("Checking %d provider(s)...", len(self.providers))
        available_count = 0
        for provider in self.providers.values():
            if provider.check_availability():
                available_count += 1
        # Remove channels for unavailable providers
        unavailable = {name for name, p in self.providers.items() if not p.available}
        for key in list(self.channels.keys()):
            prov_name = key.split(":")[0] if ":" in key else key
            if prov_name in unavailable:
                self.channels.pop(key, None)
        for name in unavailable:
            self.queues.pop(name, None)
            self.gpu_queues.pop(name, None)
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
        """Find the best LLM channel for a named provider.

        Looks for a channel belonging to this provider with LLM types (ollama/openai).
        Falls back to any channel of this provider.
        """
        llm_types = {"ollama", "openai", "llm"}
        # First pass: LLM-typed channel for this provider
        for key, pq in self.channels.items():
            if pq.provider.name != provider_name:
                continue
            gpu_configs = [g for g in pq.provider.gpu_configs if g.index in (pq._gpu_indices or [])]
            if gpu_configs and any(set(g.types) & llm_types for g in gpu_configs):
                return pq
        # Second pass: any channel for this provider (cloud providers have no GPU types)
        for key, pq in self.channels.items():
            if pq.provider.name == provider_name:
                return pq
        return None

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
        """Returns the first available LLM channel (fallback)."""
        llm_types = {"ollama", "openai", "llm"}
        for pq in self.channels.values():
            if not pq.provider.available:
                continue
            gpu_configs = [g for g in pq.provider.gpu_configs if g.index in (pq._gpu_indices or [])]
            if gpu_configs and any(set(g.types) & llm_types for g in gpu_configs):
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
        """Find the best channel for a task by GPU type and load.

        Args:
            gpu_type: Required GPU type (e.g. "comfyui", "openai", "ollama")

        Returns:
            Best matching ProviderQueue, or None if no match.
        """
        from app.core.channel_health import is_healthy
        llm_types = {"ollama", "openai", "llm"}
        candidates = []
        for key, pq in self.channels.items():
            if not pq.provider.available:
                continue
            gpu_indices = pq._gpu_indices or []
            gpu_configs = [g for g in pq.provider.gpu_configs if g.index in gpu_indices]
            if gpu_configs:
                # Local provider: match GPU type exactly
                if not any(gpu_type in g.types for g in gpu_configs):
                    continue
            else:
                # Channel ohne GPU-Eintrag: kann nur LLM-Tasks bedienen, niemals
                # ComfyUI/A1111 (die brauchen einen Backend-Channel).
                if gpu_type not in llm_types:
                    continue
            # Backend-Health-Check: Channel ueberspringen wenn alle zugeordneten
            # ComfyUI-Backends down sind (auto-detected via channel_health).
            if not is_healthy(key, gpu_type):
                continue
            # Score: fewer pending tasks = better
            with pq._lock:
                pending = len(pq._pending_tasks) + len(pq._current_tasks)
            candidates.append((pending, key, pq))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        # Round-Robin bei gleicher Last: bei mehreren Channels mit gleicher
        # Auslastung abwechselnd verteilen statt immer den ersten zu nehmen
        min_load = candidates[0][0]
        equal = [c for c in candidates if c[0] == min_load]
        if len(equal) > 1:
            self._round_robin += 1
            chosen = equal[self._round_robin % len(equal)]
            logger.debug("find_channel(%s): %d Kandidaten mit Last=%d, Round-Robin -> %s",
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
        2. Explicit Provider GPU: provider_name="Provider:gpuIndex" → direct lookup
        3. Dynamic routing: gpu_type set → find_channel() by type/load
        4. Legacy fallback: provider_name="Provider" → backwards-compat LLM-channel lookup
        """
        # 1. ImageBackend channel lookup: backend name → ``backend:<name>``
        if provider_name and provider_name in self._backend_providers:
            pq = self.channels.get(f"backend:{provider_name}")
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        # 2. Direct channel lookup: "Provider:N" → "Provider:gpuN"
        if provider_name and ":" in provider_name:
            parts = provider_name.split(":", 1)
            channel_key = f"{parts[0]}:gpu{parts[1]}"
            pq = self.channels.get(channel_key)
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        # 3. Dynamic routing by GPU type
        if gpu_type:
            pq = self.find_channel(gpu_type)
            if pq:
                return pq.submit_gpu_task(task_type, priority, callable_fn,
                                          agent_name, label)

        # 4. Legacy fallback by provider name
        if provider_name:
            prov_name = provider_name.split(":")[0] if ":" in provider_name else provider_name
            pq = self.gpu_queues.get(prov_name) or self.queues.get(prov_name)
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

    def _get_beszel_gpu_stats(self, provider: "Provider") -> Optional[Dict]:
        """Fetches Beszel GPU stats (cached per poll cycle)."""
        if not provider.beszel_system_id:
            return None
        try:
            from app.core.beszel import get_gpu_stats
            return get_gpu_stats(provider.beszel_system_id, provider.gpu_vram_overrides)
        except Exception as exc:
            logger.debug("Beszel GPU query failed for %s: %s", provider.name, exc)
            return None

    def _filter_gpu_vram(self, gpu_stats: Dict, provider: "Provider",
                         gpu_indices: Optional[List[int]]) -> Dict:
        """Filters Beszel GPU stats to only the GPUs this queue serves.

        Wenn ein konfiguriertes GPU-Device in Beszel nicht existiert (z.B. weil
        Beszel das Device nicht meldet — AMD unter /dev/dri o.ae.), wird KEIN
        Fallback auf "alle GPUs" gemacht (das mischt Channels). Stattdessen
        leere gpus-Liste + 0-Stats + Label aus der config.
        """
        all_gpus = gpu_stats.get("gpus", [])
        if not gpu_indices or not provider.gpu_configs:
            return gpu_stats

        target_configs = [g for g in provider.gpu_configs if g.index in gpu_indices]

        # Zuordnung GpuConfig -> Beszel-GPU: Priorität match_name (stabil ueber
        # Reboots), Fallback device-id. Beszel meldet Namen teils inkorrekt
        # (z.B. Sample-Fall: 4070 wurde als "RTX 3090" gemeldet) — falls der
        # match_name nicht greift, bleibt der Device-Index als letzter Anker.
        used_ids: set = set()
        matched_pairs: List[tuple] = []  # (GpuConfig, beszel_gpu)
        # 1) Zuerst per match_name matchen
        for cfg in target_configs:
            if not cfg.match_name:
                continue
            needle = cfg.match_name.strip().lower()
            if not needle:
                continue
            for bg in all_gpus:
                bid = bg.get("id")
                if bid in used_ids:
                    continue
                beszel_name = (bg.get("name") or "").strip().lower()
                if needle in beszel_name:
                    matched_pairs.append((cfg, bg))
                    used_ids.add(bid)
                    break
        # 2) Unzugeordnete Configs per device-id matchen
        for cfg in target_configs:
            if any(cfg is pair[0] for pair in matched_pairs):
                continue
            for bg in all_gpus:
                bid = bg.get("id")
                if bid in used_ids:
                    continue
                if bid == cfg.device:
                    matched_pairs.append((cfg, bg))
                    used_ids.add(bid)
                    break

        filtered = [bg for _cfg, bg in matched_pairs]
        # Config-Label ueberschreibt den von Beszel gemeldeten Namen
        for cfg, bg in matched_pairs:
            bg["name"] = cfg.label or f"GPU {cfg.index}"

        if not filtered:
            # Keine Beszel-Daten fuer dieses Device — zeige Config-Werte ohne Live-Stats
            fallback_gpus = [
                {
                    "id": g.device,
                    "name": g.label or f"GPU {g.index}",
                    "used_mb": 0,
                    "total_mb": g.vram_mb,
                    "util_pct": 0,
                    "power_w": 0,
                }
                for g in target_configs
            ]
            total_mem = sum(g["total_mb"] for g in fallback_gpus)
            return {
                "gpu_used_mb": 0,
                "gpu_total_mb": total_mem,
                "gpu_free_mb": total_mem,
                "gpu_util_pct": 0,
                "gpus": fallback_gpus,
            }

        total_used = sum(g.get("used_mb", 0) for g in filtered)
        total_mem = sum(g.get("total_mb", 0) for g in filtered)
        total_util = sum(g.get("util_pct", 0) for g in filtered)
        return {
            "gpu_used_mb": total_used,
            "gpu_total_mb": total_mem,
            "gpu_free_mb": total_mem - total_used,
            "gpu_util_pct": round(total_util / len(filtered), 1) if filtered else 0,
            "gpus": filtered,
        }

    def get_combined_status(self) -> Dict[str, Any]:
        """Aggregated status across all providers."""
        from app.core.channel_health import is_healthy as _channel_is_healthy
        providers_status = {}
        all_chat = None
        all_recent = []

        # Cache Beszel results per provider (avoid duplicate API calls)
        beszel_cache: Dict[str, Optional[Dict]] = {}

        for channel_key, pq in self.channels.items():
            status = pq.get_status()
            provider = self.providers.get(pq.provider.name)
            gpu_indices = pq._gpu_indices

            # Channel-Health: Provider-Endpoint UND (bei comfyui) das gebundene
            # Backend muessen erreichbar sein. is_healthy returns True fuer
            # Nicht-comfyui-Channels (LLM laeuft direkt am Provider-Endpoint).
            _is_comfyui = bool(pq._gpu_indices) and any(
                "comfyui" in (g.types or []) for g in pq.provider.gpu_configs
                if g.index in pq._gpu_indices
            )
            _gpu_type = "comfyui" if _is_comfyui else ""
            status["healthy"] = bool(pq.provider.available) and _channel_is_healthy(
                channel_key, _gpu_type)

            if provider:
                if provider.type == "comfyui":
                    vram = provider.poll_vram_usage(cache_ttl=10.0)
                    status["vram"] = vram if vram else {
                        "vram_total_mb": provider.vram_mb,
                        "vram_used_mb": 0,
                        "vram_free_mb": provider.vram_mb,
                        "loaded_models": [],
                        "source": "comfyui",
                    }
                elif provider.type == "ollama":
                    vram = provider.poll_vram_usage(cache_ttl=10.0)
                    status["vram"] = vram if vram else {
                        "vram_total_mb": provider.vram_mb,
                        "vram_used_mb": 0,
                        "vram_free_mb": provider.vram_mb,
                        "loaded_models": [],
                    }
                elif provider.beszel_system_id:
                    # Beszel: fetch once per provider, filter per queue's GPUs
                    if provider.name not in beszel_cache:
                        beszel_cache[provider.name] = self._get_beszel_gpu_stats(provider)
                    gpu = beszel_cache[provider.name]
                    if gpu and (gpu.get("gpu_total_mb", 0) > 0 or gpu.get("gpus")):
                        filtered = self._filter_gpu_vram(gpu, provider, gpu_indices)
                        status["vram"] = {
                            "vram_total_mb": filtered["gpu_total_mb"],
                            "vram_used_mb": filtered["gpu_used_mb"],
                            "vram_free_mb": filtered["gpu_free_mb"],
                            "gpu_util_pct": filtered.get("gpu_util_pct", 0),
                            "loaded_models": [],
                            "source": "beszel",
                            "gpus": filtered.get("gpus", []),
                        }

                # Per-GPU config (filtered to this queue's GPUs)
                if provider.gpu_configs:
                    if gpu_indices:
                        configs = [g for g in provider.gpu_configs if g.index in gpu_indices]
                    else:
                        configs = provider.gpu_configs
                    status["gpu_configs"] = [
                        {"index": g.index, "vram_mb": g.vram_mb, "device": g.device,
                         "types": g.types, "label": g.label, "max_concurrent": g.max_concurrent}
                        for g in configs
                    ]

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

    def poll_all_vram(self) -> Dict[str, Any]:
        """Polls VRAM usage from all Ollama providers."""
        result = {}
        for name, provider in self.providers.items():
            if provider.type == "ollama":
                vram = provider.poll_vram_usage()
                if vram:
                    result[name] = vram
        return result

    def reload(self) -> Dict[str, Any]:
        """Reloads providers from .env and recreates queues."""
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
    """Reloads providers from .env."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager.reload()
