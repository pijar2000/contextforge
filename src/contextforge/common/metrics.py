"""Tiny in-process metrics registry rendered in Prometheus text format."""

import threading
from collections import defaultdict


def _key(name: str, labels: dict) -> tuple:
    return (name, tuple(sorted(labels.items())))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple, float] = defaultdict(float)
        self._sums: dict[tuple, float] = defaultdict(float)
        self._counts: dict[tuple, int] = defaultdict(int)
        self._max: dict[tuple, float] = defaultdict(float)

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        with self._lock:
            self._counters[_key(name, labels)] += value

    def observe(self, name: str, value: float, **labels) -> None:
        with self._lock:
            k = _key(name, labels)
            self._sums[k] += value
            self._counts[k] += 1
            self._max[k] = max(self._max[k], value)

    def counter(self, name: str, **labels) -> float:
        return self._counters.get(_key(name, labels), 0.0)

    def summary(self, name: str, **labels) -> dict:
        k = _key(name, labels)
        return {
            "count": self._counts.get(k, 0),
            "sum": self._sums.get(k, 0.0),
            "max": self._max.get(k, 0.0),
        }

    @staticmethod
    def _fmt(name: str, labels: tuple, value: float) -> str:
        if labels:
            rendered = ",".join(f'{k}="{v}"' for k, v in labels)
            return f"{name}{{{rendered}}} {value}"
        return f"{name} {value}"

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(self._fmt(f"contextforge_{name}_total", labels, value))
            for (name, labels), total in sorted(self._sums.items()):
                count = self._counts[(name, labels)]
                lines.append(self._fmt(f"contextforge_{name}_sum", labels, total))
                lines.append(self._fmt(f"contextforge_{name}_count", labels, count))
                lines.append(self._fmt(f"contextforge_{name}_max", labels, self._max[(name, labels)]))
        return "\n".join(lines) + "\n"
