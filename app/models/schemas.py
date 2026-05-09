"""Строгие контракты API агрегации (Pydantic v2)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SynthesisStrategy(str, Enum):
    """Стратегия объединения ответов (полная логика — STEP 3)."""

    RAW = "raw"
    VOTE = "vote"
    SYNTHESIZE = "synthesize"


class AggregateRequest(BaseModel):
    """Тело POST /v1/aggregate."""

    query: str = Field(..., min_length=1, max_length=4000)
    roles: list[str] | None = Field(
        default=None,
        description="Фильтр по role из маршрутов; None — все активные маршруты.",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    synthesis_strategy: SynthesisStrategy = SynthesisStrategy.RAW
    timeout_override_ms: int | None = Field(
        default=None,
        gt=0,
        description="Переопределение таймаута; применение — # TODO: STEP 2",
    )


class TokensUsed(BaseModel):
    prompt: int = Field(..., ge=0)
    completion: int = Field(..., ge=0)


class ResultItem(BaseModel):
    route_id: str
    provider: str
    model: str
    role: str
    content: str | None
    latency_ms: int = Field(..., ge=0)
    tokens_used: TokensUsed
    error: str | None


class ResponseMetadata(BaseModel):
    total_cost_usd: float = Field(..., ge=0.0)
    total_time_ms: int = Field(..., ge=0)
    cache_hit: bool = False
    strategy_exec_time_ms: int | None = Field(
        default=None,
        description="Время выполнения стратегии синтеза (мс).",
    )


class AggregateResponse(BaseModel):
    request_id: str
    status: Literal["success", "partial", "failed"]
    results: list[ResultItem]
    synthesis: str | None
    metadata: ResponseMetadata
    synthesis_confidence: float | None = Field(
        default=None,
        description="Уверенность стратегии 0..1 (если применимо).",
    )
    strategy_meta: dict[str, Any] | None = Field(
        default=None,
        description="Доп. метаданные стратегии (winner_route_id и т.п.).",
    )
