from __future__ import annotations

from datetime import UTC, datetime
import time

import httpx
from fastapi import APIRouter, Query

from app.services.market_data import (
    compute_data_freshness_status,
    fetch_live_context,
    get_ohlcv_cache_info,
)

router = APIRouter(tags=["market"])


@router.get("/context")
async def get_market_context(
    asset: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="4H"),
    refresh: bool = Query(default=False),
) -> dict:
    try:
        ctx = await fetch_live_context(asset=asset, timeframe=timeframe, force_refresh=refresh)
    except Exception as e:
        return {
            "status": "unavailable",
            "data_freshness_status": "UNAVAILABLE",
            "source": "unavailable",
            "timestamp": datetime.now(UTC).isoformat(),
            "asset": asset,
            "timeframe": timeframe,
            "price_snapshot": {
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": None,
                "candles_count": 0,
            },
            "indicators": {
                "rsi_14": None,
                "macd_signal": None,
                "ema_20_50_cross": None,
                "atr": None,
                "bb_upper": None,
                "bb_lower": None,
            },
            "market_metrics": {
                "funding_rate_pct": None,
                "open_interest_usd": None,
                "long_short_ratio": None,
            },
            "sentiment_brief": "Нет данных",
            "cache_info": {"hit": False, "ttl_remaining_sec": 0},
            "error_detail": f"{type(e).__name__}",
        }

    ind = ctx.get("indicators") or {}
    mm = ctx.get("market_metrics") or {}
    news = ctx.get("news_sentiment") or []
    cache_info = await get_ohlcv_cache_info(asset.upper(), timeframe.lower())

    brief = "Нет данных"
    if news:
        titles = [str(n.get("title") or "").strip() for n in news[:2] if n.get("title")]
        if titles:
            brief = " | ".join(titles)

    dfs = ctx.get("data_freshness_status") or compute_data_freshness_status(ctx)
    return {
        "status": ctx.get("data_freshness", "unavailable"),
        "data_freshness_status": dfs,
        "source": ctx.get("source", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
        "asset": ctx.get("asset", asset),
        "timeframe": ctx.get("timeframe", timeframe),
        "price_snapshot": {
            "open": ctx.get("open"),
            "high": ctx.get("high"),
            "low": ctx.get("low"),
            "close": ctx.get("price"),
            "volume": ctx.get("volume"),
            "candles_count": ctx.get("candles_count", 0),
        },
        "indicators": {
            "rsi_14": ind.get("rsi_14"),
            "macd_signal": ind.get("macd_signal"),
            "ema_20_50_cross": ind.get("ema_cross"),
            "atr": ind.get("atr_14"),
            "bb_upper": ind.get("bb_upper"),
            "bb_lower": ind.get("bb_lower"),
        },
        "market_metrics": {
            "funding_rate_pct": mm.get("funding_rate"),
            "open_interest_usd": mm.get("open_interest"),
            "long_short_ratio": mm.get("long_short_ratio"),
        },
        "sentiment_brief": brief,
        "cache_info": {
            "hit": bool(cache_info.get("hit")),
            "ttl_remaining_sec": int(cache_info.get("ttl_remaining_sec") or 0),
        },
        "error_detail": None if ctx.get("data_freshness") != "unavailable" else "source_unavailable",
    }


@router.get("/health")
async def get_market_health() -> dict:
    checks = {
        "binance": "https://api.binance.com/api/v3/ping",
        "bybit": "https://api.bybit.com/v5/market/time",
        "coingecko": "https://api.coingecko.com/api/v3/ping",
    }
    sources: dict[str, bool] = {}
    latency_ms: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in checks.items():
            started = time.perf_counter()
            ok = False
            try:
                resp = await client.get(url)
                ok = 200 <= resp.status_code < 300
            except Exception:
                ok = False
            elapsed = int((time.perf_counter() - started) * 1000)
            sources[name] = ok
            latency_ms[name] = elapsed
    # Binance ping часто падает с EU/hosting (451); для бейджа достаточно любой крипто-REST.
    crypto_ok = bool(sources.get("binance") or sources.get("bybit"))
    status = "healthy" if crypto_ok else "degraded"
    return {
        "status": status,
        "sources": sources,
        "latency_ms": latency_ms,
        "timestamp": datetime.now(UTC).isoformat(),
    }

