"""In-memory sliding-window rate limits for hosted mode: per client IP and per user. No database or HTTP.

Each Cloud Run instance keeps its own counts, so the effective limit is the limit times the instance count
(at most 2). Uploads also have their own per-user limit in the database (`uploads.check_rate`).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    per_ip: int  # requests per window from one client address
    per_uid: int  # requests per window from one signed-in user (or API key owner)
    window: float = 60.0  # seconds


HOSTED_LIMITS = Limits(per_ip=300, per_uid=120)
SWEEP_EVERY = 1000  # hits between sweeps of idle keys


class RateLimiter:
    """At most `limit` hits per key within any `window` seconds. Rejected hits don't count."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._since_sweep = 0

    def hit(self, key: str) -> float | None:
        """Record a hit: None if allowed, else the seconds until the next one would be."""
        now = self._clock()
        with self._lock:
            self._since_sweep += 1
            if self._since_sweep >= SWEEP_EVERY:
                self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return hits[0] + self.window - now
            hits.append(now)
            return None

    def sweep(self) -> None:
        """Forget keys with no hits inside the window."""
        with self._lock:
            self._sweep(self._clock())

    def _sweep(self, now: float) -> None:
        self._since_sweep = 0
        idle = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]
        for k in idle:
            del self._hits[k]

    def __len__(self) -> int:
        return len(self._hits)


def client_ip(headers: Mapping[str, str], peer: str | None) -> str:
    """The client's address: the first `X-Forwarded-For` entry (Firebase Hosting and Cloud Run put the
    client there), else the connection's peer."""
    forwarded = headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or peer or "unknown"
