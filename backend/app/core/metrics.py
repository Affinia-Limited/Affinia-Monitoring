"""Minimal in-process metrics for monitoring the platform itself.

Exposed in Prometheus text format at ``/metrics`` so Azure Monitor managed
Prometheus, Grafana or any scraper can collect them. Deliberately dependency-free;
counters are per-process (each API/worker replica reports its own).
"""

from __future__ import annotations

import threading
from collections import defaultdict

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Counter:
    def __init__(self, name: str, help_text: str, label: str):
        self.name, self.help, self.label = name, help_text, label
        self._values: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def inc(self, label_value: str, amount: int = 1) -> None:
        with self._lock:
            self._values[label_value] += amount

    def value(self, label_value: str) -> int:
        return self._values.get(label_value, 0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, val in sorted(self._values.items()):
            lines.append(f'{self.name}{{{self.label}="{_escape(key)}"}} {val}')
        return lines


def _escape(value: str) -> str:
    """Prometheus label value escaping (backslash, double quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Histogram:
    def __init__(self, name: str, help_text: str, label: str):
        self.name, self.help, self.label = name, help_text, label
        self._buckets: dict[str, list[int]] = defaultdict(lambda: [0] * (len(_LATENCY_BUCKETS) + 1))
        self._sum: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def observe(self, label_value: str, seconds: float) -> None:
        with self._lock:
            buckets = self._buckets[label_value]
            for i, bound in enumerate(_LATENCY_BUCKETS):
                if seconds <= bound:
                    buckets[i] += 1
            buckets[-1] += 1
            self._sum[label_value] += seconds

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for raw, buckets in sorted(self._buckets.items()):
            key = _escape(raw)
            for i, bound in enumerate(_LATENCY_BUCKETS):
                lines.append(f'{self.name}_bucket{{{self.label}="{key}",le="{bound}"}} {buckets[i]}')
            lines.append(f'{self.name}_bucket{{{self.label}="{key}",le="+Inf"}} {buckets[-1]}')
            lines.append(f'{self.name}_sum{{{self.label}="{key}"}} {self._sum[raw]:.6f}')
            lines.append(f'{self.name}_count{{{self.label}="{key}"}} {buckets[-1]}')
        return lines


HTTP_REQUESTS = Counter("amp_http_requests_total", "HTTP requests by status class", "status")
HTTP_LATENCY = Histogram("amp_http_request_duration_seconds", "HTTP request latency by route", "route")
AZURE_CALLS = Counter("amp_azure_calls_total", "Azure API calls by operation", "operation")
AZURE_FAILURES = Counter("amp_azure_failures_total", "Failed Azure API calls by operation", "operation")
JOB_RUNS = Counter("amp_job_runs_total", "Background job executions by job", "job")
JOB_FAILURES = Counter("amp_job_failures_total", "Failed background jobs by job", "job")
SYNC_FAILURES = Counter("amp_sync_failures_total", "Failed synchronisations by error code", "code")

_ALL: list[Counter | Histogram] = [
    HTTP_REQUESTS,
    HTTP_LATENCY,
    AZURE_CALLS,
    AZURE_FAILURES,
    JOB_RUNS,
    JOB_FAILURES,
    SYNC_FAILURES,
]


def render_prometheus() -> str:
    lines: list[str] = []
    for metric in _ALL:
        lines.extend(metric.render())
    return "\n".join(lines) + "\n"
