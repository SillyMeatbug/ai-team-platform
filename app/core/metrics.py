"""In-memory метрики в формате Prometheus text exposition (без prometheus-client)."""

from __future__ import annotations

import threading


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class PrometheusMetrics:
    """Счётчики/суммы с потокобезопасным инкрементом."""

    __slots__ = ("_lock", "_requests", "_cache_hits", "_budget_rejections", "_cost_by_provider")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str], int] = {}
        self._cache_hits = 0
        self._budget_rejections = 0
        self._cost_by_provider: dict[str, float] = {}

    def inc_request(self, status: str, strategy: str) -> None:
        key = (status, strategy)
        with self._lock:
            self._requests[key] = self._requests.get(key, 0) + 1

    def inc_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def inc_budget_rejection(self) -> None:
        with self._lock:
            self._budget_rejections += 1

    def add_provider_cost(self, provider: str, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        with self._lock:
            self._cost_by_provider[provider] = self._cost_by_provider.get(provider, 0.0) + cost_usd

    def render(self) -> str:
        lines: list[str] = []

        lines.append("# HELP aggregate_requests_total Total aggregate API requests.")
        lines.append("# TYPE aggregate_requests_total counter")
        with self._lock:
            reqs = sorted(self._requests.items())
            hits = self._cache_hits
            brej = self._budget_rejections
            costs = sorted(self._cost_by_provider.items())

        for (status, strategy), v in reqs:
            ls = f'status="{_escape_label_value(status)}",strategy="{_escape_label_value(strategy)}"'
            lines.append(f"aggregate_requests_total{{{ls}}} {v}")

        lines.append("# HELP aggregate_cache_hits_total Cache hits for aggregate endpoint.")
        lines.append("# TYPE aggregate_cache_hits_total counter")
        lines.append(f"aggregate_cache_hits_total {hits}")

        lines.append("# HELP aggregate_budget_rejections_total Rejected requests due to budget.")
        lines.append("# TYPE aggregate_budget_rejections_total counter")
        lines.append(f"aggregate_budget_rejections_total {brej}")

        lines.append("# HELP aggregate_cost_usd_total Accumulated estimated USD cost by provider.")
        lines.append("# TYPE aggregate_cost_usd_total counter")
        for provider, total in costs:
            lp = f'provider="{_escape_label_value(provider)}"'
            lines.append(f"aggregate_cost_usd_total{{{lp}}} {total}")

        return "\n".join(lines) + "\n"


_METRICS = PrometheusMetrics()


def get_metrics() -> PrometheusMetrics:
    return _METRICS
