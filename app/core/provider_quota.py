"""Thread-safe provider-wide HTTP quotas, measured in SYSTEM monotonic time."""
from collections import deque
import math
import threading
import time


class QuotaUnavailable(RuntimeError):
    """No local request slot; the router should try another provider."""


def rate_limit_error(err):
    """Find a rate-limit error through queue wrappers, without classifying 503."""
    seen = set()
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        if isinstance(err, QuotaUnavailable):
            return err
        text = str(err).lower()
        if getattr(err, 'status_code', None) == 429 or 'rate limit' in text or 'too many requests' in text:
            return err
        err = err.__cause__ or err.__context__
    return None


def is_rate_limit_error(err):
    return rate_limit_error(err) is not None


class ProviderQuota:
    """A send window plus expiring reservations for calls still in the queue."""

    def __init__(self, capacity=0, window=60, *, clock=None):
        self.capacity = max(0, int(capacity))
        self.window = max(1, int(window))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._sends = deque()
        self._reservations = {}
        self._blocked_until = 0.0
        self._full_logged = False
        self._last_exhausted_error = None

    def reconfigure(self, capacity, window):
        """Keep live sends and reservations when admin settings are reloaded."""
        with self._lock:
            self.capacity = max(0, int(capacity))
            self.window = max(1, int(window))

    def _prune(self, now):
        while self._sends and self._sends[0] <= now - self.window:
            self._sends.popleft()
        self._reservations = {r: t for r, t in self._reservations.items()
                              if t > now - self.window}
        if not self._wait(now):
            self._full_logged = False

    def _wait(self, now):
        wait = max(0.0, self._blocked_until - now)
        if self.capacity and len(self._sends) + len(self._reservations) >= self.capacity:
            stamps = list(self._sends) + list(self._reservations.values())
            # If capacity was reduced, enough entries must expire to get below it.
            frees = sorted(stamps)[len(stamps) - self.capacity] + self.window
            wait = max(wait, frees - now)
        return wait

    @property
    def used(self):
        with self._lock:
            self._prune(self._clock())
            return len(self._sends) + len(self._reservations)

    def wait_seconds(self):
        with self._lock:
            now = self._clock()
            self._prune(now)
            return self._wait(now)

    def reserve(self):
        with self._lock:
            now = self._clock()
            self._prune(now)
            if self._wait(now):
                return None
            token = object()
            if self.capacity:
                self._reservations[token] = now
            return token

    def release(self, token):
        with self._lock:
            self._reservations.pop(token, None)
            self._prune(self._clock())

    def wait_for_send(self, reservation=None):
        """Queued work may use its own reservation, but respects a remote 429."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            if reservation in self._reservations:
                return max(0.0, self._blocked_until - now)
            return self._wait(now)

    def send(self, reservation=None):
        """Atomically consume the first-send reservation, or claim a fresh slot."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            reserved = reservation in self._reservations
            if self._blocked_until > now or (not reserved and self._wait(now)):
                raise QuotaUnavailable('Provider rate limit reached locally')
            self._reservations.pop(reservation, None)
            if self.capacity:
                self._sends.append(now)

    def exhaust(self, err):
        """429 is a key-level gate, independent of provider health/cooldowns."""
        cause = rate_limit_error(err)
        if cause is None or isinstance(cause, QuotaUnavailable):
            return
        response = getattr(cause, 'response', None)
        headers = getattr(response, 'headers', None) or getattr(cause, 'headers', {}) or {}
        retry = headers.get('retry-after', headers.get('Retry-After', getattr(cause, 'retry_after', None)))
        try:
            delay = float(retry)
            if not math.isfinite(delay):
                raise ValueError('Non-finite Retry-After')
        except (TypeError, ValueError):
            delay = None
            if retry:
                try:
                    from email.utils import parsedate_to_datetime
                    from app.core.timeutils import utc_now
                    delay = max(0.0, (parsedate_to_datetime(str(retry)) - utc_now()).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        with self._lock:
            if cause is self._last_exhausted_error:
                return
            self._last_exhausted_error = cause
            now = self._clock()
            self._prune(now)
            if delay is None:
                delay = max(0.0, self._sends[0] + self.window - now) if self._sends else self.window
            self._blocked_until = max(self._blocked_until, now + max(0.0, delay))

    def reason(self):
        return f'rate limit {self.used}/{self.capacity}, frees in {math.ceil(self.wait_seconds())} s'

    def log_full(self, logger, name):
        with self._lock:
            wait = self.wait_seconds()
            if wait and not self._full_logged:
                self._full_logged = True
                logger.info('Provider %s: rate limit %d/%ss reached, routing to next entries for %d s',
                            name, self.capacity, self.window, math.ceil(wait))
