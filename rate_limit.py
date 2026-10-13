"""
In-memory sliding-window rate limiter.

Design:
- Single-instance (Render Free) → memory is enough.
- Thread-safe via Lock.
- Keyed by api_key_id (UUID), never by raw API key.
- Sliding window: keeps timestamps of last N requests.
- Opportunistic cleanup on each check.

Upgrade path: replace with Redis when scaling to multiple instances.
"""
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Tuple

logger = logging.getLogger("rate_limit")


class RateLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key_id: str, limit_per_min: int) -> Tuple[bool, int]:
        """
        Returns (allowed, current_count).

        allowed=True  → request permitted, counter incremented.
        allowed=False → request denied, counter NOT incremented.
        current_count = number of requests in the last window
                       (including this one if allowed).
        """
        if limit_per_min <= 0:
            # Misconfigured → fail-open (never block due to bad data)
            logger.warning("rate_limit_per_min=%s for key=%s → fail-open",
                           limit_per_min, key_id)
            return True, 0

        now = time.time()
        cutoff = now - self.window

        with self._lock:
            bucket = self._buckets[key_id]

            # Drop expired timestamps
            bucket[:] = [t for t in bucket if t > cutoff]

            current = len(bucket)
            if current >= limit_per_min:
                return False, current

            bucket.append(now)
            return True, current + 1

    def reset(self, key_id: str) -> None:
        """For testing."""
        with self._lock:
            self._buckets.pop(key_id, None)

    def size(self) -> int:
        """Number of tracked keys (for monitoring)."""
        with self._lock:
            return len(self._buckets)


# Singleton
limiter = RateLimiter(window_seconds=60)
