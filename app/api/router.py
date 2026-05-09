"""Маршруты HTTP: агрегация (диспетчер httpx + кэш, бюджет, метрики)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from app.config.loader import RouteEntry, RoutesConfig, Settings
from app.core.budget import BudgetLimiter
from app.core.cache import (
    AggregationCache,
    build_aggregate_cache_key,
    effective_cache_ttl_seconds,
)
from app.core.logging_config import log_payload
from app.models.schemas import (
    AggregateRequest,
    AggregateResponse,
    ResponseMetadata,
    ResultItem,
)
from app.services.dispatcher import HttpAggregationDispatcher, compute_route_cost_usd
from app.services.mock_providers import mock_dispatch_routes
from app.services.strategies import create_strategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["aggregate"])

HEADER_FORCE_429 = "x-skeleton-force-429"

DEFAULT_AGGREGATE_TIMEOUT_MS = 120_000


def _resolve_routes(cfg: RoutesConfig, roles: list[str] | None) -> list[RouteEntry]:
    active = [r for r in cfg.routes if r.active and not r.is_arbiter]
    if roles is None:
        return active
    if not roles:
        return []
    allowed = set(roles)
    return [r for r in active if r.role in allowed]


def _compute_status(results: list[ResultItem]) -> Literal["success", "partial", "failed"]:
    if not results:
        return "failed"
    errors = sum(1 for r in results if r.error is not None)
    if errors == 0:
        return "success"
    if errors == len(results):
        return "failed"
    return "partial"


def _materialize_cached_aggregate(
    payload: dict[str, Any],
    *,
    new_request_id: str,
    total_time_ms: int,
) -> AggregateResponse:
    data = dict(payload)
    meta_raw = dict(data.get("metadata") or {})
    meta_raw["cache_hit"] = True
    meta_raw["total_time_ms"] = total_time_ms
    meta_raw["strategy_exec_time_ms"] = 0
    data["request_id"] = new_request_id
    data["metadata"] = meta_raw
    return AggregateResponse.model_validate(data)


@router.post("/aggregate", response_model=AggregateResponse)
async def aggregate(request: Request, body: AggregateRequest) -> AggregateResponse:
    """Агрегация ответов нескольких моделей и стратегия синтеза."""
    if request.headers.get(HEADER_FORCE_429, "").strip().lower() in ("1", "true", "yes"):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded (skeleton stub).",
            headers={"Retry-After": "60"},
        )

    cfg: RoutesConfig = request.app.state.routes_config
    routes = _resolve_routes(cfg, body.roles)

    req_id = str(uuid.uuid4())
    timeout_ms = body.timeout_override_ms or DEFAULT_AGGREGATE_TIMEOUT_MS
    settings: Settings = request.app.state.settings
    budget: BudgetLimiter = request.app.state.budget_limiter
    cache: AggregationCache = request.app.state.response_cache
    metrics = request.app.state.metrics

    strategy_label = body.synthesis_strategy.value

    log_payload(
        logger,
        logging.INFO,
        "aggregate_request_started",
        request_id=req_id,
        routes_selected=len(routes),
        synthesis_strategy=strategy_label,
        temperature=body.temperature,
        timeout_ms=timeout_ms,
        aggregate_mock=settings.aggregate_mock_providers,
    )

    estimated = float(len(routes)) * float(settings.estimated_cost_per_route_usd)
    if not budget.check_request_cost(estimated):
        metrics.inc_budget_rejection()
        metrics.inc_request("budget_rejected", strategy_label)
        log_payload(
            logger,
            logging.WARNING,
            "aggregate_request_finished",
            request_id=req_id,
            status="budget_rejected",
            budget_remaining=budget.get_remaining_daily(),
        )
        raise HTTPException(
            status_code=429,
            detail="Budget exceeded",
            headers={"Retry-After": "3600"},
        )

    cache_key = build_aggregate_cache_key(
        query=body.query,
        roles=body.roles,
        temperature=body.temperature,
        synthesis_strategy=strategy_label,
        aggregate_mock=settings.aggregate_mock_providers,
    )

    lookup_start = time.perf_counter()
    cached = await cache.get(cache_key)
    if cached is not None:
        out_req_id = str(uuid.uuid4())
        hit_ms = max(1, int((time.perf_counter() - lookup_start) * 1000))
        response = _materialize_cached_aggregate(
            cached.payload,
            new_request_id=out_req_id,
            total_time_ms=hit_ms,
        )
        metrics.inc_cache_hit()
        metrics.inc_request(response.status, strategy_label)
        ttl_rem = max(0, int(round(cached.ttl_remaining_s)))
        log_payload(
            logger,
            logging.INFO,
            "aggregate_request_finished",
            request_id=out_req_id,
            status=response.status,
            results=len(response.results),
            total_time_ms=response.metadata.total_time_ms,
            total_cost_usd=response.metadata.total_cost_usd,
            synthesis_strategy=strategy_label,
            strategy_exec_time_ms=response.metadata.strategy_exec_time_ms,
            cache_hit=True,
            budget_remaining=budget.get_remaining_daily(),
            cache_ttl_remaining=ttl_rem,
        )
        return response

    wall0 = time.perf_counter()

    try:
        if settings.aggregate_mock_providers:
            results = await mock_dispatch_routes(
                routes=routes,
                temperature=body.temperature,
            )
        else:
            http_client = request.app.state.http_client
            dispatcher = HttpAggregationDispatcher(http_client)
            results = await dispatcher.run(
                query=body.query,
                routes=routes,
                temperature=body.temperature,
                timeout_ms=timeout_ms,
                request_id=req_id,
            )
    except Exception:
        metrics.inc_request("error", strategy_label)
        logger.exception(
            "aggregate_dispatcher_critical",
            extra={
                "log_payload": {
                    "request_id": req_id,
                    "routes_selected": len(routes),
                    "aggregate_mock": settings.aggregate_mock_providers,
                    "budget_remaining": budget.get_remaining_daily(),
                }
            },
        )
        raise HTTPException(status_code=500, detail="Internal aggregation error")

    total_wall_ms = max(1, int((time.perf_counter() - wall0) * 1000))
    status = _compute_status(results)
    total_cost = sum(compute_route_cost_usd(r.provider, r.tokens_used) for r in results)

    route_order = [r.route_id for r in routes]
    http_client = None if settings.aggregate_mock_providers else request.app.state.http_client
    strategy_impl = create_strategy(
        body.synthesis_strategy,
        routes_cfg=cfg,
        http_client=http_client,
        aggregate_mock=settings.aggregate_mock_providers,
    )

    try:
        st0 = time.perf_counter()
        syn = await strategy_impl.aggregate(
            query=body.query,
            results=results,
            route_order=route_order,
            request_id=req_id,
            base_timeout_ms=timeout_ms,
            temperature=body.temperature,
        )
        strategy_exec_ms = max(0, int((time.perf_counter() - st0) * 1000))
    except Exception:
        metrics.inc_request("error", strategy_label)
        logger.exception(
            "aggregate_strategy_critical",
            extra={
                "log_payload": {
                    "request_id": req_id,
                    "routes_selected": len(routes),
                    "budget_remaining": budget.get_remaining_daily(),
                }
            },
        )
        raise HTTPException(status_code=500, detail="Internal aggregation error")

    meta = ResponseMetadata(
        total_cost_usd=round(total_cost, 6),
        total_time_ms=total_wall_ms,
        cache_hit=False,
        strategy_exec_time_ms=strategy_exec_ms,
    )

    response = AggregateResponse(
        request_id=req_id,
        status=status,
        results=results,
        synthesis=syn.content,
        synthesis_confidence=syn.confidence,
        strategy_meta=syn.meta,
        metadata=meta,
    )

    ttl_used = effective_cache_ttl_seconds(settings.cache_ttl_seconds, routes)
    await cache.set(cache_key, response.model_dump(mode="json"), ttl_seconds=ttl_used)
    budget.record_actual_cost(float(response.metadata.total_cost_usd))

    for r in results:
        metrics.add_provider_cost(
            r.provider,
            compute_route_cost_usd(r.provider, r.tokens_used),
        )

    metrics.inc_request(status, strategy_label)

    log_payload(
        logger,
        logging.INFO,
        "aggregate_request_finished",
        request_id=req_id,
        status=status,
        results=len(results),
        total_time_ms=meta.total_time_ms,
        total_cost_usd=meta.total_cost_usd,
        synthesis_strategy=strategy_label,
        strategy_exec_time_ms=meta.strategy_exec_time_ms,
        cache_hit=False,
        budget_remaining=budget.get_remaining_daily(),
        cache_ttl_remaining=ttl_used,
    )

    return response
