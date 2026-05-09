"""Стратегии агрегации ответов (raw / vote / synthesize)."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config.loader import RouteEntry, RoutesConfig
from app.core.logging_config import log_payload
from app.models.schemas import ResultItem, SynthesisStrategy as StrategyEnum
from app.services.dispatcher import complete_chat_messages, compute_route_cost_usd

logger = logging.getLogger(__name__)

_MAX_LOG_PREVIEW = 120
_MAX_SYNTH_BODY_PER_ROUTE = 1200


def record_aggregate_synthesis_attempt(*, strategy: str, status: str) -> None:
    """Событие-метрика: aggregate_synthesis_attempts_total {{strategy,status}}."""
    log_payload(
        logger,
        logging.INFO,
        "aggregate_synthesis_attempts_total",
        strategy=strategy,
        status=status,
    )


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    content: str | None
    confidence: float | None
    meta: dict[str, Any]


@runtime_checkable
class AggregationStrategy(Protocol):
    async def aggregate(
        self,
        *,
        query: str,
        results: list[ResultItem],
        route_order: list[str],
        request_id: str,
        base_timeout_ms: int,
        temperature: float,
    ) -> SynthesisResult:
        ...


def _query_log_token(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _truncate_for_log(text: str | None, limit: int = _MAX_LOG_PREVIEW) -> str:
    if text is None:
        return ""
    t = text.replace("\n", " ").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "…"


class RawStrategy:
    async def aggregate(
        self,
        *,
        query: str,
        results: list[ResultItem],
        route_order: list[str],
        request_id: str,
        base_timeout_ms: int,
        temperature: float,
    ) -> SynthesisResult:
        ok = [r for r in results if r.error is None and r.content is not None]
        parts = [r.content or "" for r in ok]
        merged = "\n\n---\n\n".join(parts) if parts else None
        record_aggregate_synthesis_attempt(strategy="raw", status="success" if merged else "empty")
        qtok = _query_log_token(query)
        log_payload(
            logger,
            logging.INFO,
            "synthesis_raw_complete",
            request_id=request_id,
            query_sha256_short=qtok,
            sources=len(ok),
            merged_chars=len(merged or ""),
        )
        return SynthesisResult(
            content=merged if merged else None,
            confidence=1.0 if merged else None,
            meta={
                "strategy": "raw",
                "source_route_ids": [r.route_id for r in ok],
            },
        )


class VoteStrategy:
    async def aggregate(
        self,
        *,
        query: str,
        results: list[ResultItem],
        route_order: list[str],
        request_id: str,
        base_timeout_ms: int,
        temperature: float,
    ) -> SynthesisResult:
        candidates = [r for r in results if r.error is None and r.content is not None]
        if not candidates:
            record_aggregate_synthesis_attempt(strategy="vote", status="empty")
            return SynthesisResult(
                content=None,
                confidence=None,
                meta={"strategy": "vote", "vote_reason": "no_successful_results"},
            )

        def route_idx(rid: str) -> int:
            try:
                return route_order.index(rid)
            except ValueError:
                return 10**9

        candidates.sort(
            key=lambda r: (
                r.latency_ms,
                compute_route_cost_usd(r.provider, r.tokens_used),
                route_idx(r.route_id),
            ),
        )
        winner = candidates[0]
        record_aggregate_synthesis_attempt(strategy="vote", status="success")
        qtok = _query_log_token(query)
        log_payload(
            logger,
            logging.INFO,
            "synthesis_vote_complete",
            request_id=request_id,
            query_sha256_short=qtok,
            winner_route_id=winner.route_id,
            winner_content_chars=len(winner.content or ""),
        )
        return SynthesisResult(
            content=winner.content,
            confidence=0.85,
            meta={
                "strategy": "vote",
                "winner_route_id": winner.route_id,
                "vote_reason": "min_latency_then_cost_then_route_order",
            },
        )


class SynthesizeStrategy:
    __slots__ = ("_routes_cfg", "_http_client", "_aggregate_mock")

    def __init__(
        self,
        *,
        routes_cfg: RoutesConfig,
        http_client: httpx.AsyncClient | None,
        aggregate_mock: bool,
    ) -> None:
        self._routes_cfg = routes_cfg
        self._http_client = http_client
        self._aggregate_mock = aggregate_mock

    def _find_arbiter_route(self) -> RouteEntry | None:
        for r in self._routes_cfg.routes:
            if r.is_arbiter and r.role == "arbiter":
                return r
        return None

    async def aggregate(
        self,
        *,
        query: str,
        results: list[ResultItem],
        route_order: list[str],
        request_id: str,
        base_timeout_ms: int,
        temperature: float,
    ) -> SynthesisResult:
        successful = [r for r in results if r.error is None and r.content is not None]
        vote = VoteStrategy()

        if len(successful) < 2:
            record_aggregate_synthesis_attempt(strategy="synthesize", status="skipped_insufficient_success")
            log_payload(
                logger,
                logging.INFO,
                "synthesis_synthesize_skipped",
                request_id=request_id,
                reason="need_at_least_two_successful",
                successful=len(successful),
            )
            return await vote.aggregate(
                query=query,
                results=results,
                route_order=route_order,
                request_id=request_id,
                base_timeout_ms=base_timeout_ms,
                temperature=temperature,
            )

        arbiter = self._find_arbiter_route()
        if arbiter is None:
            record_aggregate_synthesis_attempt(strategy="synthesize", status="error_no_arbiter_route")
            log_payload(logger, logging.ERROR, "synthesis_arbiter_missing", request_id=request_id)
            return await vote.aggregate(
                query=query,
                results=results,
                route_order=route_order,
                request_id=request_id,
                base_timeout_ms=base_timeout_ms,
                temperature=temperature,
            )

        if self._aggregate_mock or self._http_client is None:
            record_aggregate_synthesis_attempt(strategy="synthesize", status="mock_stub")
            merged_preview = " | ".join(_truncate_for_log(r.content, 200) for r in successful)
            log_payload(
                logger,
                logging.WARNING,
                "synthesis_synthesize_mock_shortcircuit",
                request_id=request_id,
                query_sha256_short=_query_log_token(query),
                previews_count=len(successful),
            )
            return SynthesisResult(
                content=f"[MOCK-SYNTH] {merged_preview}",
                confidence=1.0,
                meta={
                    "strategy": "synthesize",
                    "note": "AGGREGATE_MOCK или нет http_client — локальный stub",
                    "arbiter_route_id": arbiter.route_id,
                },
            )

        formatted_parts: list[str] = []
        for r in successful:
            body = r.content or ""
            if len(body) > _MAX_SYNTH_BODY_PER_ROUTE:
                body = body[:_MAX_SYNTH_BODY_PER_ROUTE] + "…"
            formatted_parts.append(f"[{r.route_id}] ({r.provider}/{r.model})\n{body}")
        formatted_results = "\n\n".join(formatted_parts)

        user_prompt = (
            "Ты арбитр. Запрос пользователя: "
            f"{query}\n\nОтветы моделей:\n{formatted_results}\n\n"
            "Синтезируй итоговый ответ, устраняя противоречия. "
            "Если ответы противоречат друг другу — укажи это."
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": arbiter.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        arb_timeout = max(1, int(base_timeout_ms * 1.5))
        log_payload(
            logger,
            logging.INFO,
            "synthesis_arbiter_request",
            request_id=request_id,
            query_sha256_short=_query_log_token(query),
            query_len=len(query),
            arbiter_route_id=arbiter.route_id,
            successful_routes=len(successful),
            formatted_body_chars=min(len(formatted_results), 65536),
        )

        content, err = await complete_chat_messages(
            self._http_client,
            route=arbiter,
            messages=messages,
            temperature=temperature,
            timeout_ms=arb_timeout,
            request_id=request_id,
        )

        if content is None or err:
            record_aggregate_synthesis_attempt(strategy="synthesize", status="fallback_vote")
            log_payload(
                logger,
                logging.WARNING,
                "synthesis_arbiter_failed_fallback_vote",
                request_id=request_id,
                arbiter_route_id=arbiter.route_id,
                error_preview=_truncate_for_log(err, 200),
            )
            return await vote.aggregate(
                query=query,
                results=results,
                route_order=route_order,
                request_id=request_id,
                base_timeout_ms=base_timeout_ms,
                temperature=temperature,
            )

        record_aggregate_synthesis_attempt(strategy="synthesize", status="success")
        log_payload(
            logger,
            logging.INFO,
            "synthesis_arbiter_success",
            request_id=request_id,
            arbiter_route_id=arbiter.route_id,
            output_chars=len(content),
        )
        return SynthesisResult(
            content=content,
            confidence=0.78,
            meta={
                "strategy": "synthesize",
                "arbiter_route_id": arbiter.route_id,
                "arbiter_provider": arbiter.provider,
                "arbiter_model": arbiter.model,
            },
        )


def create_strategy(
    kind: StrategyEnum,
    *,
    routes_cfg: RoutesConfig,
    http_client: httpx.AsyncClient | None,
    aggregate_mock: bool,
) -> AggregationStrategy:
    if kind == StrategyEnum.RAW:
        return RawStrategy()
    if kind == StrategyEnum.VOTE:
        return VoteStrategy()
    if kind == StrategyEnum.SYNTHESIZE:
        return SynthesizeStrategy(
            routes_cfg=routes_cfg,
            http_client=http_client,
            aggregate_mock=aggregate_mock,
        )
    return RawStrategy()
