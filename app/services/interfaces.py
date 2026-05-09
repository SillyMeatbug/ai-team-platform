"""
Контракт диспетчера параллельных вызовов провайдеров.

Реализация: app.services.dispatcher.HttpAggregationDispatcher
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.config.loader import RouteEntry
from app.models.schemas import ResultItem


@runtime_checkable
class AggregationDispatcher(Protocol):
    """Параллельная отправка запросов провайдерам (STEP 2)."""

    async def run(
        self,
        *,
        query: str,
        routes: list[RouteEntry],
        temperature: float,
        timeout_ms: int,
        request_id: str,
    ) -> list[ResultItem]:
        """Выполнить все маршруты параллельно; ошибки маршрутов — в ResultItem.error."""
        ...


class NoOpDispatcher:
    """Заглушка для DI/тестов."""

    async def run(
        self,
        *,
        query: str,
        routes: list[RouteEntry],
        temperature: float,
        timeout_ms: int,
        request_id: str,
    ) -> list[ResultItem]:
        raise NotImplementedError("NoOpDispatcher")
