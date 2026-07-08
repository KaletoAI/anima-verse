"""Channel health monitor: polls backend reachability per queue channel.

``backend:<name>`` channels map 1:1 to an image-generation backend
instance. The monitor periodically re-checks each enabled backend via its
own ``check_availability()`` (protocol-specific per backend class) so that
``find_channel`` skips channels whose backend is down and the queue panel
can show per-channel health. Cooldowns set via ``mark_unhealthy`` stay
authoritative — the ``available`` property enforces them regardless of
what a probe returns.

LLM channels are not polled per-channel here — they are governed by
``provider.available``, refreshed once per poll round via
``pm.refresh_availability()``.

``is_healthy(channel_key)`` is read synchronously from the find_channel
hot path (mutex-guarded, very cheap).
"""
import threading
import time
from typing import Dict, Tuple

from app.core.log import get_logger

logger = get_logger("channel_health")

POLL_INTERVAL_S = 30
STARTUP_DELAY_S = 5


class ChannelHealthMonitor:
    """Background poller for channel health status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # channel_key -> (is_healthy, last_check_ts)
        self._status: Dict[str, Tuple[bool, float]] = {}
        self._started = False
        self._thread = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="channel-health")
        self._thread.start()
        logger.info("ChannelHealthMonitor started (poll every %ds)", POLL_INTERVAL_S)

    def is_healthy(self, channel_key: str) -> bool:
        """True when the channel is usable.

        ``backend:<name>`` channels report the cached reachability of their
        backend. All other channels (LLM providers): always True — the
        provider-level availability check covers them.
        """
        if not channel_key.startswith("backend:"):
            return True
        with self._lock:
            entry = self._status.get(channel_key)
        if entry is None:
            # Never polled yet — optimistic True. After the startup delay
            # every channel has been measured.
            return True
        return entry[0]

    def force_poll(self) -> None:
        """Explicitly re-poll all channels. Used by admin endpoints."""
        self._poll_all()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _backend_for_channel(channel_key: str):
        """Resolves a ``backend:<name>`` channel to its backend instance."""
        target = channel_key.split(":", 1)[1]
        try:
            from app.imagegen.service import get_image_service
            skill = get_image_service()
        except Exception:
            return None
        for b in skill.backends:
            if b.name == target and b.instance_enabled:
                return b
        return None

    def _poll_channel(self, channel_key: str) -> None:
        if not channel_key.startswith("backend:"):
            return
        backend = self._backend_for_channel(channel_key)
        if backend is None:
            # No (enabled) backend behind this channel — not our concern;
            # report True so the channel stays selectable.
            with self._lock:
                self._status[channel_key] = (True, time.time())
            return

        # Delegate to the backend's own protocol check; this also refreshes
        # backend.available for the selection logic.
        try:
            healthy = bool(backend.check_availability())
        except Exception as e:
            logger.debug("Health check %s failed: %s", channel_key, e)
            healthy = False

        with self._lock:
            prev_entry = self._status.get(channel_key)
            prev_healthy = prev_entry[0] if prev_entry else None
            self._status[channel_key] = (healthy, time.time())

        if prev_healthy is None:
            if not healthy:
                logger.warning("Channel %s initially unhealthy (%s down)",
                               channel_key, backend.api_url)
            else:
                logger.debug("Channel %s initially healthy", channel_key)
        elif prev_healthy != healthy:
            if healthy:
                logger.info("Channel %s recovered (backend reachable)", channel_key)
            else:
                logger.warning("Channel %s now unhealthy (%s down)",
                               channel_key, backend.api_url)

    def _poll_all(self) -> None:
        try:
            from app.core.provider_manager import get_provider_manager
            pm = get_provider_manager()
            channel_keys = list(pm.channels.keys())
        except Exception as e:
            logger.debug("ChannelHealth: channel list unavailable: %s", e)
            return
        # Re-probe LLM providers: provider.available is only set once at
        # startup — a host switched off later would otherwise stay
        # "available" forever.
        try:
            pm.refresh_availability()
        except Exception as e:
            logger.debug("ChannelHealth: refresh_availability failed: %s", e)
        for key in channel_keys:
            self._poll_channel(key)

    def _loop(self) -> None:
        time.sleep(STARTUP_DELAY_S)
        while True:
            try:
                self._poll_all()
            except Exception as e:
                logger.warning("ChannelHealth loop error: %s", e)
            time.sleep(POLL_INTERVAL_S)


# ----------------------------------------------------------------------
# Singleton + public API
# ----------------------------------------------------------------------
_monitor: ChannelHealthMonitor | None = None


def get_monitor() -> ChannelHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = ChannelHealthMonitor()
    return _monitor


def is_healthy(channel_key: str) -> bool:
    """Public API for find_channel (and tests)."""
    return get_monitor().is_healthy(channel_key)


def start() -> None:
    """Public API for the server lifespan. Idempotent."""
    get_monitor().start()
