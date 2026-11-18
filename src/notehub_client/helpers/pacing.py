"""Optional shared request pacing for Notehub clients."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import timezone
from email.utils import parsedate_to_datetime


class RequestPacer:
    """Reserve a bounded number of requests in a sliding time window.

    Share one instance among clients using the same Notehub billing account.
    Pacing does not retry requests or coordinate with other processes.
    """

    def __init__(self, *, limit: int = 6, period: float = 60.0) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not math.isfinite(period) or period <= 0:
            raise ValueError("period must be a positive finite number")
        self.limit = limit
        self.period = period
        self._recent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for one available request slot."""
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._recent and now - self._recent[0] >= self.period:
                    self._recent.popleft()
                ready_at = max(
                    self._blocked_until,
                    self._recent[0] + self.period if len(self._recent) >= self.limit else now,
                )
                if ready_at <= now:
                    self._recent.append(now)
                    return
                delay = ready_at - now
            await asyncio.sleep(delay)

    async def defer(self, retry_after: str | None) -> None:
        """Share a 429 cooldown from a delay in seconds or an HTTP-date.

        Missing or malformed headers use the configured period. Cooldowns last
        at least one second and never shorten an existing deferral. Date values
        are converted once to a monotonic deadline, so later wall-clock changes
        do not alter an active cooldown.
        """
        try:
            seconds = float(retry_after) if retry_after is not None else self.period
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after or "")
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = retry_at.timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                seconds = self.period
        if not math.isfinite(seconds):
            seconds = self.period
        async with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + max(1.0, seconds))


__all__ = ["RequestPacer"]
