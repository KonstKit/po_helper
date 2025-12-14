from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, Tuple, Iterable


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self.gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self.histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], list] = defaultdict(list)

    def _key(self, name: str, labels: Dict[str, str] | None) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        items: Tuple[Tuple[str, str], ...] = tuple(sorted((labels or {}).items()))
        return (name, items)

    def inc(self, name: str, value: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            self.counters[self._key(name, labels)] += value

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            self.gauges[self._key(name, labels)] = value

    def observe(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        with self._lock:
            self.histograms[self._key(name, labels)].append(value)

    def export_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in self.counters.items():
                lbl = "{" + ",".join([f"{k}=\"{v}\"" for k, v in labels]) + "}" if labels else ""
                lines.append(f"{name}_total{lbl} {value}")
            for (name, labels), value in self.gauges.items():
                lbl = "{" + ",".join([f"{k}=\"{v}\"" for k, v in labels]) + "}" if labels else ""
                lines.append(f"{name}{lbl} {value}")
            for (name, labels), values in self.histograms.items():
                # export simple sum/count; buckets can be added later
                lbl = "{" + ",".join([f"{k}=\"{v}\"" for k, v in labels]) + "}" if labels else ""
                if values:
                    lines.append(f"{name}_sum{lbl} {sum(values)}")
                    lines.append(f"{name}_count{lbl} {len(values)}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()

