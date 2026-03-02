"""Request rate limiter using the token bucket algorithm."""

import threading
import time
from typing import Dict

_limiter_instance: "RateLimiter | None" = None
_limiter_lock = threading.Lock()


class TokenBucket:
    """Token bucket rate limiter.

    Tokens are added at a fixed *rate* (tokens per second) up to *capacity*.
    Callers acquire tokens before making a request; if the bucket is empty the
    caller blocks until enough tokens have accumulated.
    """

    def __init__(self, rate: float, capacity: float) -> None:
        """Initialise the bucket.

        Args:
            rate: Tokens added per second.
            capacity: Maximum number of tokens the bucket can hold (burst size).
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add tokens accrued since the last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until *tokens* are available and consume them.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            The total time (in seconds) the caller spent waiting.
        """
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                sleep_time = deficit / self._rate
            time.sleep(sleep_time)
            waited += sleep_time


class RateLimiter:
    """Per-platform rate limiter.

    Each platform is backed by its own :class:`TokenBucket`, configured via
    :meth:`configure`.
    """

    def __init__(self) -> None:
        """Initialise with an empty set of platform buckets."""
        self._buckets: Dict[str, TokenBucket] = {}

    def configure(self, platform: str, interval: float) -> None:
        """Create or replace the bucket for *platform*.

        Args:
            platform: Platform identifier (e.g. ``"github"``).
            interval: Minimum seconds between requests (rate = 1 / interval).
        """
        rate = 1.0 / interval
        self._buckets[platform] = TokenBucket(rate=rate, capacity=rate)

    def wait(self, platform: str) -> None:
        """Acquire one token for *platform*, blocking if necessary.

        Args:
            platform: Platform identifier previously passed to :meth:`configure`.

        Raises:
            KeyError: If *platform* has not been configured.
        """
        self._buckets[platform].acquire()

    def get_wait_time(self, platform: str) -> float:
        """Return the estimated wait time without blocking.

        Args:
            platform: Platform identifier previously passed to :meth:`configure`.

        Returns:
            Seconds until a token would be available (``0.0`` if one is
            available now).

        Raises:
            KeyError: If *platform* has not been configured.
        """
        bucket = self._buckets[platform]
        with bucket._lock:
            bucket._refill()
            if bucket._tokens >= 1.0:
                return 0.0
            return (1.0 - bucket._tokens) / bucket._rate


def get_rate_limiter() -> RateLimiter:
    """Return the global :class:`RateLimiter` singleton.

    Returns:
        The shared *RateLimiter* instance (created on first call).
    """
    global _limiter_instance
    if _limiter_instance is None:
        with _limiter_lock:
            if _limiter_instance is None:
                _limiter_instance = RateLimiter()
    return _limiter_instance
