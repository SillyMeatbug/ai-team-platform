"""Отладочные маршруты (диагностика контекста без логирования query)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.market_data import (
    fetch_live_context,
    fetch_ohlcv_raw_debug,
    format_live_context_markdown,
    has_actionable_onchain_proxy,
)

router = APIRouter(tags=["debug"])


@router.get("/debug/ohlcv")
async def debug_ohlcv(
    asset: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="4H"),
    limit: int = Query(default=120, ge=1, le=1000),
) -> dict[str, Any]:
    """Сырые свечи CCXT без pandas и без TTL-кэша приложения."""
    return await fetch_ohlcv_raw_debug(asset, timeframe, limit)


@router.get("/debug/onchain-proxy")
async def debug_onchain_proxy(
    asset: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="4h"),
) -> dict[str, Any]:
    ctx = await fetch_live_context(asset=asset, timeframe=timeframe)
    detail = ctx.get("onchain_proxy_detail") or {}
    premium = detail.get("premium_index") if isinstance(detail.get("premium_index"), dict) else {}
    spot = detail.get("spot_24h") if isinstance(detail.get("spot_24h"), dict) else {}
    return {
        "funding_rate": {
            "display": ctx.get("funding_rate"),
            "premium_index_raw": premium,
        },
        "fear_greed": ctx.get("fear_greed"),
        "exchange_volumes": spot,
        "onchain_proxy_ok": ctx.get("onchain_proxy_ok"),
        "has_actionable_onchain_proxy": has_actionable_onchain_proxy(ctx),
        "data_freshness_status": ctx.get("data_freshness_status"),
        "context_sent_to_agent": format_live_context_markdown(ctx),
    }
