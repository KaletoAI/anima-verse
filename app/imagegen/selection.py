"""Backend pool for image generation: selection, matching, fallback.

Extracted from ``ImageGenerationSkill`` (Abschnitt 2, Phase 2). The skill keeps
thin delegators to a ``BackendPool`` instance for the external public API; the
pool owns the round-robin state and all backend selection logic. Per-agent
enabled overrides come via an injected ``agent_instances_provider`` so this
module stays free of ``app.models`` / ``app.skills`` imports.
"""
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.core.log import get_logger
from app.imagegen.base import ImageBackend

logger = get_logger("image_gen")

# Detects 4xx status codes in exception strings (e.g. "400 Client Error",
# "HTTP 422", "Bad Request"). 4xx = service reachable, payload broken —
# do NOT mark the backend as unavailable.
_re_4xx = re.compile(r"\b(?:HTTP\s*)?4(?:00|01|03|04|05|22)\b|Bad Request|Unprocessable", re.IGNORECASE)
# Cooldown after a non-payload error (5xx / connection / empty result).
# Mirrors the LLM provider cooldown: a failed backend is removed from the
# match selection for this duration and retried automatically afterwards.
_BACKEND_COOLDOWN_SECONDS = 300.0


class BackendPool:
    """Backend pool: cost-based selection, glob matching and fallback chain.

    Owns the round-robin state + lock. Per-agent enabled overrides come via an
    injected ``agent_instances_provider(character_name) -> dict`` (the instances
    dict) so this module needs no ``app.models`` / ``app.skills`` import. The
    cooldown/availability logic stays on the backend instances (``b.available``,
    ``b.mark_unhealthy``).
    """

    def __init__(self, backends: List[ImageBackend],
                 agent_instances_provider: Callable[[str], dict]):
        self.backends: List[ImageBackend] = backends
        # Round-robin counter per rotation key. Spreads tasks across
        # equal-cost backends (e.g. two local backends with cost=0).
        # Replaces the old LOAD_COST_PENALTY approach.
        self._round_robin_counter: Dict[str, int] = {}
        self._round_robin_lock = threading.Lock()
        self._agent_instances_provider = agent_instances_provider

    def pick_lowest_cost(
        self,
        candidates: List[ImageBackend],
        rotation_key: str = "default",
    ) -> Optional[ImageBackend]:
        """Picks the cheapest available backend from the candidates.

        With several equal-cost backends (e.g. two local backends with
        cost=0) it distributes via round-robin — prevents all tasks always
        going to the same backend without a LOAD_COST_PENALTY.
        The counter is per ``rotation_key`` (typically: workflow_name).
        """
        if not candidates:
            return None
        # Sort by cost and group equal-cost together
        sorted_c = sorted(candidates, key=lambda b: b.effective_cost)
        cheapest_cost = sorted_c[0].effective_cost
        tier = [b for b in sorted_c if b.effective_cost == cheapest_cost]
        if len(tier) == 1:
            return tier[0]
        # Several equal-cost -> round-robin per rotation_key
        with self._round_robin_lock:
            idx = self._round_robin_counter.get(rotation_key, 0)
            self._round_robin_counter[rotation_key] = idx + 1
        return tier[idx % len(tier)]

    @staticmethod
    def _is_inpaint_backend(b: ImageBackend) -> bool:
        """Inpaint backends (category=="inpaint") are ONLY for the inpaint
        dialogs (Map-Fit/Match-Edges, explicitly via an exact backend:<name>) —
        never for normal render matching, auto-select or fallback."""
        return getattr(b, "category", "") == "inpaint"

    def _select_backend(self) -> Optional[ImageBackend]:
        """Picks the cheapest available and globally enabled backend."""
        available = [b for b in self.backends if b.available and b.instance_enabled
                     and not self._is_inpaint_backend(b)]
        return self.pick_lowest_cost(available, rotation_key="_select_backend")

    def _select_backend_for_agent(self, character_name: str) -> Optional[ImageBackend]:
        """Picks the cheapest instance taking the per-agent enabled flags into account."""
        agent_instances = self._agent_instances_provider(character_name)

        available = []
        for b in self.backends:
            if not b.available:
                continue
            # Per-agent override takes precedence, otherwise the .env default
            agent_inst = agent_instances.get(b.name, {})
            if "enabled" in agent_inst:
                is_enabled = bool(agent_inst["enabled"])
            else:
                is_enabled = b.instance_enabled
            if is_enabled:
                # Inpaint backends never enter the normal agent render matching
                if self._is_inpaint_backend(b):
                    continue
                available.append(b)

        return self.pick_lowest_cost(
            available, rotation_key=f"agent:{character_name}")

    def resolve_imagegen_target(self, spec: str,
                                preferred_backend: str = ""
                                ) -> Optional[ImageBackend]:
        """Resolves a config/explicit backend spec via the match concept.

        A spec is one of:
          - ``"<glob>"`` (bare)  → ``match_backend`` (glob over backend names,
            cheapest available; an exact name matches itself). This is the
            canonical form since ComfyUI was removed.
          - ``"backend:<glob>"`` → legacy prefix, tolerated and stripped
            (behaves like the bare glob).
          - ``"workflow:<glob>"`` → legacy ComfyUI spec; logs a warning and
            resolves to None so callers fall back to their defaults.

        ``preferred_backend``: exact instance name that overrides the match —
        must be available and enabled, otherwise ``None`` (no silent fallback
        to another instance).
        """
        s = (spec or "").strip()
        if not s:
            return None
        if s.startswith("workflow:"):
            logger.warning(
                "Legacy workflow spec '%s' ignoriert (ComfyUI entfernt) — "
                "bitte einen Backend-Glob verwenden", s)
            return None
        pat = s[len("backend:"):].strip() if s.startswith("backend:") else s
        pref = (preferred_backend or "").strip()
        if pref:
            forced = next(
                (b for b in self.backends
                 if b.name == pref and b.available and b.instance_enabled),
                None)
            if not forced:
                logger.warning(
                    "Explizites Backend '%s' nicht verfuegbar/aktiviert", pref)
            return forced
        return self.match_backend(pat)

    def match_backend(self, pattern: str) -> Optional[ImageBackend]:
        """Resolves a backend glob (e.g. ``"ComfyUI*"``, ``"Together*"``, ``"*"``)
        to a concrete, available backend — selection among several matches by
        cost. An exact name matches itself. ``None`` if empty / no available
        match. This way the backend default is also a match instead of a fixed
        instance.
        """
        import fnmatch
        pat = (pattern or "").strip()
        if not pat:
            return None
        pl = pat.lower()
        matches = [b for b in self.backends
                   if fnmatch.fnmatch(b.name.lower(), pl)
                   and b.available and b.instance_enabled]
        # Globs skip inpaint backends so "*"/"Flux*" never lands a normal
        # render there — UNLESS the pattern matches ONLY inpaint backends
        # (e.g. "Qwen Inpaint*"): then the caller explicitly aimed at them
        # and excluding everything would silently fall back elsewhere.
        has_wildcard = any(ch in pat for ch in "*?[")
        if has_wildcard:
            non_inpaint = [b for b in matches
                           if not self._is_inpaint_backend(b)]
            if non_inpaint:
                matches = non_inpaint
        if not matches:
            return None
        return self.pick_lowest_cost(matches, rotation_key=f"backend_match:{pat}")

    def list_available_backends(
        self,
        character_name: str = "",
    ) -> List[ImageBackend]:
        """List of all available backends for helper API + engine.

        Filters:
        - b.available (live status; channel_health may set this False)
        - b.instance_enabled (.env flag)
        - per-agent override (agent_config.instances[name].enabled)

        Sorted ascending by effective_cost. NO round-robin here — the
        selector (or UI) takes care of distribution. This list is meant
        for display and engine use.
        """
        agent_instances: Dict[str, Any] = {}
        if character_name:
            agent_instances = self._agent_instances_provider(character_name) or {}

        out: List[ImageBackend] = []
        for b in self.backends:
            if not b.available:
                continue
            agent_inst = agent_instances.get(b.name, {})
            if "enabled" in agent_inst:
                if not bool(agent_inst["enabled"]):
                    continue
            elif not b.instance_enabled:
                continue
            out.append(b)

        out.sort(key=lambda x: x.effective_cost)
        return out

    # ------------------------------------------------------------------
    # Backend fallback engine
    # ------------------------------------------------------------------

    def _pick_fallback_backend(
        self,
        failed: ImageBackend,
        character_name: str,
        exclude: Set[str],
    ) -> Optional[ImageBackend]:
        """Next available backend — the match/availability logic IS the
        fallback (no static fallback_mode/fallback_specific anymore).
        """
        candidates = self.list_available_backends(character_name=character_name)
        candidates = [b for b in candidates if b.name not in exclude]
        # Inpaint backends are no fallback for normal renders. Only if the
        # failed backend itself was inpaint, the chain stays on inpaint.
        if not self._is_inpaint_backend(failed):
            candidates = [b for b in candidates if not self._is_inpaint_backend(b)]
        return candidates[0] if candidates else None

    def run_with_fallback(
        self,
        primary_backend: ImageBackend,
        op: Callable[[ImageBackend], Any],
        character_name: str = "",
        max_attempts: int = 3,
    ) -> Tuple[Any, ImageBackend]:
        """Runs op(backend), falling back to the next backend on failure.

        Strategy:
        - Try primary_backend
        - On exception OR empty list: set backend.available=False, dynamically
          pick the next available (compatible) backend (_pick_fallback_backend)
          — the availability logic IS the fallback
        - Repeat until success, max_attempts reached, or the chain is exhausted

        op(backend) -> List[bytes] | [] | None
        The caller is responsible for adapting params per backend.

        Returns (result, used_backend) on success.
        Raises RuntimeError once exhausted.
        """
        if not primary_backend:
            raise RuntimeError("run_with_fallback: no primary_backend provided")

        tried: Set[str] = set()
        last_error: Optional[Exception] = None
        current = primary_backend

        for attempt in range(max_attempts):
            if not current or current.name in tried:
                break
            tried.add(current.name)

            logger.info("Fallback-Engine Versuch %d/%d: backend=%s (cost=%s)",
                        attempt + 1, max_attempts, current.name, current.cost)

            try:
                result = op(current)
            except Exception as e:
                last_error = e
                # Distinguish connection/server problems vs. payload errors.
                # 4xx errors (HTTP 400/422 like workflow validation) mean the
                # service is reachable — only the sent JSON is broken. In that
                # case do NOT mark it unavailable, otherwise the backend is
                # removed from the pool and downstream steps wrongly find no
                # ComfyUI anymore.
                _err_str = str(e)
                _is_payload_err = bool(_re_4xx.search(_err_str))
                if _is_payload_err:
                    logger.warning(
                        "Fallback-Engine: %s warf Payload-Fehler (%s: %s) — Backend bleibt verfuegbar, "
                        "versuche anderen Backend (Workflow/Prompt vermutlich inkompatibel)",
                        current.name, type(e).__name__, _err_str[:200])
                else:
                    logger.warning(
                        "Fallback-Engine: %s warf Exception (%s: %s) — Backend in Cooldown, versuche Fallback",
                        current.name, type(e).__name__, _err_str[:200])
                    current.mark_unhealthy(
                        f"generate failed: {type(e).__name__}: {_err_str[:120]}",
                        _BACKEND_COOLDOWN_SECONDS)
                current = self._pick_fallback_backend(
                    current, character_name, tried)
                continue

            # List of bytes -> success
            if result:
                return result, current

            # Empty result = fail, try the next one
            logger.warning("Fallback-Engine: %s lieferte leeres Ergebnis — Cooldown, versuche Fallback",
                           current.name)
            current.mark_unhealthy("generate returned empty result",
                                   _BACKEND_COOLDOWN_SECONDS)
            current = self._pick_fallback_backend(
                current, character_name, tried)

        _err_suffix = f" (letzter Fehler: {type(last_error).__name__}: {last_error})" if last_error else ""
        raise RuntimeError(
            f"Fallback-Engine: alle {len(tried)} probierten Backends fehlgeschlagen "
            f"({', '.join(sorted(tried))}){_err_suffix}")

    def _wait_for_backend(self, character_name):
        """Picks an available backend for this agent.

        Fail-fast: if NO backend is instance_enabled at all (i.e. structurally
        not configured rather than "currently unavailable"), abort immediately —
        otherwise background threads (e.g. expression_regen) would each stall
        at a permanently impossible condition.
        """
        agent_instances: Dict[str, Any] = {}
        if character_name:
            try:
                agent_instances = self._agent_instances_provider(character_name) or {}
            except Exception:
                agent_instances = {}
        plausible = []
        for b in self.backends:
            if not b.instance_enabled:
                continue
            agent_inst = agent_instances.get(b.name, {})
            if "enabled" in agent_inst and not agent_inst["enabled"]:
                continue
            plausible.append(b)
        if not plausible:
            logger.warning(
                "_wait_for_backend: kein konfiguriertes Backend kann diesen "
                "Agent jemals erfuellen (agent=%s) — fail-fast",
                character_name or "n/a")
            return None

        # One single check round — no 120s polling. The background poller
        # (channel_health) detects recovery every 30s; the next generate
        # call sees the fresh status.
        for b in plausible:
            b.check_availability()
        backend = self._select_backend_for_agent(character_name)
        if backend:
            return backend
        logger.warning(
            "_wait_for_backend: kein Backend verfuegbar — fail-fast "
            "(channel_health pollt im Hintergrund weiter)")
        return None

    def _wait_for_explicit_backend(self, backend_name):
        """Resolves a backend glob (e.g. "ComfyUI*", "Together*") via the match
        concept to a concrete, available backend. An exact name matches itself.
        Fail-fast: no polling — recovery is detected by the background poller
        (channel_health) every 30s.
        """
        import fnmatch
        pl = (backend_name or "").strip().lower()
        # Probe fresh availability of the matching candidates, then match.
        for b in self.backends:
            if b.instance_enabled and fnmatch.fnmatch(b.name.lower(), pl):
                b.check_availability()
        target = self.match_backend(backend_name)
        if not target:
            logger.warning("Backend '%s' nicht verfuegbar/kein Treffer — fail-fast", backend_name)
        return target
