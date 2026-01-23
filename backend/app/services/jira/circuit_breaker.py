"""Circuit breaker pattern implementation for Jira API resilience."""

import logging
import time
from typing import Optional

from app.core.config import settings
from app.core.metrics import metrics

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Implements circuit breaker pattern for API resilience.

    When failures reach threshold, the circuit "opens" and blocks requests
    for a configurable sleep period, allowing the service to recover.

    Handles:
    - Failure counting and threshold detection
    - Automatic circuit opening
    - Recovery after sleep period
    - Metrics reporting
    """

    DEFAULT_THRESHOLD = 5
    DEFAULT_SLEEP_SECONDS = 60

    def __init__(
        self,
        threshold: Optional[int] = None,
        sleep_seconds: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            threshold: Number of failures before opening circuit
            sleep_seconds: How long to sleep when circuit opens
            enabled: Whether circuit breaker is enabled (default from settings)
        """
        self.threshold = (
            threshold
            or getattr(settings, "JIRA_CB_THRESHOLD", self.DEFAULT_THRESHOLD)
            or self.DEFAULT_THRESHOLD
        )

        self.sleep_seconds = (
            sleep_seconds
            or getattr(settings, "JIRA_CB_SLEEP_SECONDS", self.DEFAULT_SLEEP_SECONDS)
            or self.DEFAULT_SLEEP_SECONDS
        )

        self.enabled = (
            enabled if enabled is not None else getattr(settings, "JIRA_CB_ENABLED", False)
        )

        # State
        self._failures = 0
        self._disabled_until: float = 0.0
        self._open_count = 0

        logger.debug(
            "CircuitBreaker initialized: enabled=%s threshold=%d sleep=%.1fs",
            self.enabled,
            self.threshold,
            self.sleep_seconds,
        )

    def is_open(self) -> bool:
        """
        Check if circuit is open (should block requests).

        Returns:
            True if circuit is open, False if closed
        """
        if not self.enabled:
            return False

        now = time.time()

        if self._disabled_until > 0 and now < self._disabled_until:
            return True

        # Circuit has recovered
        if self._disabled_until > 0:
            logger.info(
                "Circuit breaker recovered (was open for %.1fs)",
                now - (self._disabled_until - self.sleep_seconds),
            )
            self._failures = 0
            self._disabled_until = 0.0
            self._update_metrics_closed()

        return False

    def record_success(self) -> None:
        """Reset failure count on successful request."""
        if not self.enabled:
            return

        if self._failures > 0:
            logger.debug("Circuit breaker: success recorded, resetting failures")
            self._failures = 0
            self._update_metrics_closed()

    def record_failure(self) -> None:
        """
        Increment failure count and open circuit if threshold reached.
        """
        if not self.enabled:
            return

        self._failures += 1

        logger.debug("Circuit breaker: failure recorded (%d/%d)", self._failures, self.threshold)

        if self._failures >= self.threshold:
            self._open()

    def _open(self) -> None:
        """Open the circuit breaker."""
        self._disabled_until = time.time() + self.sleep_seconds
        self._open_count += 1

        logger.warning(
            "Circuit breaker OPEN: failures=%d sleep=%.1fs (total_opens=%d)",
            self._failures,
            self.sleep_seconds,
            self._open_count,
        )

        self._failures = 0
        self._update_metrics_open()

    def _update_metrics_open(self) -> None:
        """Update metrics to reflect open state."""
        try:
            metrics.inc("jira_cb_open_total")
            metrics.set_gauge("jira_cb_open", 1)
            metrics.set_gauge("jira_cb_sleep_seconds", self.sleep_seconds)
        except Exception as e:
            logger.debug("Failed to update circuit breaker metrics: %s", e)

    def _update_metrics_closed(self) -> None:
        """Update metrics to reflect closed state."""
        try:
            metrics.set_gauge("jira_cb_open", 0)
        except Exception as e:
            logger.debug("Failed to update circuit breaker metrics: %s", e)

    @property
    def stats(self) -> dict:
        """
        Get circuit breaker statistics.

        Returns:
            Dict with current state and statistics
        """
        return {
            "enabled": self.enabled,
            "is_open": self.is_open(),
            "failures": self._failures,
            "threshold": self.threshold,
            "total_opens": self._open_count,
            "disabled_until": self._disabled_until,
            "sleep_seconds": self.sleep_seconds,
        }
