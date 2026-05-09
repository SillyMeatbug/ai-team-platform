"""In-memory LRU-кэш ответов агрегации (asyncio.Lock).

При изменении routes.yaml по mtime/size кэш полностью сбрасывается.
# TODO: Redis для прода (общий кэш между инстансами).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.loader import RouteEntry


@dataclass(frozen=True)
class CacheLookupResult:
    payload: dict[str, Any]
    ttl_remaining_s: float


@dataclass
class _CachedEntry:
    payload: dict[str, Any]
    expires_at: float


def effective_cache_ttl_seconds(global_ttl: int, routes: list[RouteEntry]) -> int:
    """TTL записи: min(global, минимальный положительный cache_override_ttl по маршрутам)."""
    t = global_ttl
    for r in routes:
        co = r.cache_override_ttl
        if co is not None and co > 0:
            t = min(t, co)
    return max(1, t)


class AggregationCache:
    """LRU по ключу; проверка изменения файла маршрутов через stat."""

    __slots__ = ("_routes_path", "_max_entries", "_lock", "_data", "_routes_revision")

    def __init__(self, routes_path: Path, *, max_entries: int) -> None:
        self._routes_path = routes_path
        self._max_entries = max_entries
        self._lock = asyncio.Lock()
        self._data: OrderedDict[str, _CachedEntry] = OrderedDict()
        self._routes_revision: tuple[int, int] | None = None

    def _current_routes_revision(self) -> tuple[int, int]:
        st = self._routes_path.stat()
        return st.st_mtime_ns, st.st_size

    def _invalidate_if_routes_changed_unlocked(self) -> None:
        try:
            rev = self._current_routes_revision()
        except OSError:
            return
        if self._routes_revision is None:
            self._routes_revision = rev
            return
        if rev != self._routes_revision:
            self._data.clear()
            self._routes_revision = rev

    async def get(self, cache_key: str) -> CacheLookupResult | None:
        async with self._lock:
            self._invalidate_if_routes_changed_unlocked()
            entry = self._data.get(cache_key)
            if entry is None:
                return None
            now = time.time()
            if now >= entry.expires_at:
                del self._data[cache_key]
                return None
            self._data.move_to_end(cache_key)
            ttl_rem = max(0.0, entry.expires_at - now)
            return CacheLookupResult(payload=entry.payload, ttl_remaining_s=ttl_rem)

    async def set(self, cache_key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
        async with self._lock:
            self._invalidate_if_routes_changed_unlocked()
            expires_at = time.time() + max(1, ttl_seconds)
            self._data[cache_key] = _CachedEntry(payload=payload, expires_at=expires_at)
            self._data.move_to_end(cache_key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)


def build_aggregate_cache_key(
    *,
    query: str,
    roles: list[str] | None,
    temperature: float,
    synthesis_strategy: str,
    aggregate_mock: bool,
) -> str:
    """SHA-256 от query + sorted(roles) + temperature + synthesis_strategy (+ режим мока)."""
    roles_sorted = ",".join(sorted(roles)) if roles else ""
    raw = (
        f"{query}|{roles_sorted}|{temperature:.6f}|{synthesis_strategy}|"
        f"{str(aggregate_mock).lower()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
