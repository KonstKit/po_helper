from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict


class WebhookRateLimiter:
    """Simple in-memory sliding window limiter per source key.

    check_rate(source) -> True if allowed, False if rate-limited.
    """

    def __init__(self, max_per_minute: int = 60) -> None:
        self.max_per_minute = max_per_minute
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def check_rate(self, source: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        dq = self._events[source]
        # prune old
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= self.max_per_minute:
            return False
        dq.append(now)
        return True


@dataclass
class _BreakerState:
    failures: int = 0
    opened: bool = False
    next_allowed_at: float = 0.0
    backoff: float = 0.0


class CircuitBreaker:
    """In-memory circuit breaker with exponential backoff per source key.

    On failure, increases failure count; when threshold reached, opens circuit.
    While open, rejects calls until next_allowed_at; backoff doubles up to max.
    On success, resets to closed.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        base_backoff_seconds: float = 5.0,
        max_backoff_seconds: float = 300.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._states: Dict[str, _BreakerState] = defaultdict(_BreakerState)

    def _state(self, source: str) -> _BreakerState:
        return self._states[source]

    def allow(self, source: str) -> bool:
        st = self._state(source)
        if not st.opened:
            return True
        now = time.time()
        return now >= st.next_allowed_at

    def on_success(self, source: str) -> None:
        st = self._state(source)
        st.failures = 0
        st.opened = False
        st.backoff = 0.0
        st.next_allowed_at = 0.0

    def on_failure(self, source: str) -> None:
        st = self._state(source)
        st.failures += 1
        if st.failures >= self.failure_threshold:
            # open and schedule next allowed time
            now = time.time()
            st.opened = True
            st.backoff = st.backoff * 2.0 if st.backoff > 0 else self.base_backoff_seconds
            if st.backoff > self.max_backoff_seconds:
                st.backoff = self.max_backoff_seconds
            st.next_allowed_at = now + st.backoff

    def call(self, source: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Decorator to guard a function with breaker logic for a source.

        If open and not allowed yet, raises RuntimeError('circuit_open').
        """

        def decorator(func: Callable[..., object]) -> Callable[..., object]:
            def wrapper(*args, **kwargs):
                if not self.allow(source):
                    raise RuntimeError("circuit_open")
                try:
                    res = func(*args, **kwargs)
                except Exception:
                    self.on_failure(source)
                    raise
                else:
                    self.on_success(source)
                    return res

            return wrapper

        return decorator
