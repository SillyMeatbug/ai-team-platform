"""Локальные ответы без вызова платных API (режим AGGREGATE_MOCK)."""

from __future__ import annotations

import asyncio
import time

from app.config.loader import RouteEntry
from app.models.schemas import ResultItem, TokensUsed


async def mock_dispatch_routes(
    *,
    routes: list[RouteEntry],
    temperature: float,
) -> list[ResultItem]:
    tasks = [_mock_one_route(route=r, temperature=temperature) for r in routes]
    return list(await asyncio.gather(*tasks))


async def _mock_one_route(*, route: RouteEntry, temperature: float) -> ResultItem:
    delay_s = 0.05 + (abs(hash(route.route_id)) % 120) / 1000.0
    t0 = time.perf_counter()
    await asyncio.sleep(delay_s)
    latency_ms = max(1, int((time.perf_counter() - t0) * 1000))

    prompt = max(16, 40 + int(temperature * 10) + (hash(route.provider) % 20))
    completion = 96 + (hash(route.role) % 140)
    tokens = TokensUsed(prompt=prompt, completion=completion)

    content = (
        f"[MOCK] route_id={route.route_id} provider={route.provider} "
        f"model={route.model} role={route.role}"
    )

    return ResultItem(
        route_id=route.route_id,
        provider=route.provider,
        model=route.model,
        role=route.role,
        content=content,
        latency_ms=latency_ms,
        tokens_used=tokens,
        error=None,
    )
