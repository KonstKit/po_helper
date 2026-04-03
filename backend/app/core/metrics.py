from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from math import ceil, floor
from typing import Dict, Tuple


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self.gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self._histogram_max_samples = 2_048
        self.histograms: Dict[
            Tuple[str, Tuple[Tuple[str, str], ...]],
            deque[float],
        ] = defaultdict(lambda: deque(maxlen=self._histogram_max_samples))
        self._recent_events: deque[tuple[float, str, Tuple[str, Tuple[Tuple[str, str], ...]], float]] = deque(
            maxlen=100_000
        )

    def _key(
        self, name: str, labels: Dict[str, str] | None
    ) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        items: Tuple[Tuple[str, str], ...] = tuple(sorted((labels or {}).items()))
        return (name, items)

    @staticmethod
    def _format_labels(labels: Tuple[Tuple[str, str], ...]) -> str:
        return "{" + ",".join([f'{k}="{v}"' for k, v in labels]) + "}" if labels else ""

    @staticmethod
    def _quantile(values: list[float], quantile: float) -> float | None:
        if not values:
            return None
        if quantile <= 0:
            return min(values)
        if quantile >= 1:
            return max(values)

        ordered = sorted(values)
        position = (len(ordered) - 1) * quantile
        lower_index = floor(position)
        upper_index = ceil(position)
        if lower_index == upper_index:
            return ordered[lower_index]

        lower_value = ordered[lower_index]
        upper_value = ordered[upper_index]
        weight = position - lower_index
        return lower_value + (upper_value - lower_value) * weight

    def _record_event(
        self,
        kind: str,
        name: str,
        labels: Dict[str, str] | None,
        value: float,
    ) -> None:
        self._recent_events.append((time.time(), kind, self._key(name, labels), value))

    def inc(self, name: str, value: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            key = self._key(name, labels)
            self.counters[key] += value
            self._record_event("counter", name, labels, value)

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            self.gauges[self._key(name, labels)] = value

    def observe(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            self.histograms[self._key(name, labels)].append(value)

    def recent_counter_sum(
        self,
        name: str,
        since_seconds: int | float,
        labels: Dict[str, str] | None = None,
    ) -> float:
        cutoff = time.time() - max(0.0, float(since_seconds))
        target_key = self._key(name, labels) if labels is not None else None

        with self._lock:
            total = 0.0
            for event_time, kind, event_key, value in self._recent_events:
                if event_time < cutoff or kind != "counter" or event_key[0] != name:
                    continue
                if target_key is not None and event_key != target_key:
                    continue
                total += value
            return total

    def export_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in self.counters.items():
                lbl = self._format_labels(labels)
                lines.append(f"{name}_total{lbl} {value}")
            for (name, labels), value in self.gauges.items():
                lbl = self._format_labels(labels)
                lines.append(f"{name}{lbl} {value}")
            for (name, labels), values in self.histograms.items():
                # Export quantiles plus sum/count for summary-style consumers.
                lbl = self._format_labels(labels)
                if values:
                    sample_values = list(values)
                    for quantile in (0.5, 0.95, 0.99):
                        q_value = self._quantile(sample_values, quantile)
                        if q_value is None:
                            continue
                        quantile_labels = tuple(sorted((*labels, ("quantile", f"{quantile:g}"))))
                        q_lbl = self._format_labels(quantile_labels)
                        lines.append(f"{name}{q_lbl} {q_value}")
                    lines.append(f"{name}_sum{lbl} {sum(sample_values)}")
                    lines.append(f"{name}_count{lbl} {len(sample_values)}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
