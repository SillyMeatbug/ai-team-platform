"""Сбор и предобработка рыночных данных для крипто-агентов.

Async-first модуль:
- OHLCV (ccxt)
- Индикаторы (pandas/pandas-ta + fallback)
- Метрики деривативов и сентимента (funding/volume/fear&greed)
- Новостной фон и базовый sentiment
- TTL-кэш + graceful fallback на stale данные
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

try:
    import ccxt.async_support as ccxt_async
except Exception:  # pragma: no cover
    ccxt_async = None

if ccxt_async is None:
    logger.warning("ccxt_async unavailable: OHLCV via CCXT disabled until package installs")
else:
    logger.info("ccxt async_support loaded for Binance OHLCV")

# Binance api.binance.com часто отдаёт 451 из облака (EU/US — restricted location). Fallback OHLCV без ключей.
_OHLCV_EXCHANGE_FALLBACK_CHAIN: tuple[str, ...] = ("binance", "bybit", "okx")

_TF_MONTH_RE = re.compile(r"^(\d+)M$")

try:
    import pandas_ta as ta  # type: ignore
except Exception:  # pragma: no cover
    ta = None


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    updated_at: datetime


_CACHE: dict[str, _CacheEntry] = {}
_CACHE_LOCK = asyncio.Lock()


def _ttl_for_timeframe(timeframe: str) -> int:
    raw = (timeframe or "").strip()
    if _TF_MONTH_RE.fullmatch(raw):
        return 86_400
    tf = raw.lower()
    if tf in {"1m", "3m", "5m", "15m"}:
        return 300
    if tf in {"30m", "1h", "2h"}:
        return 600
    return 900


def _cache_key(prefix: str, **parts: object) -> str:
    tail = "|".join(f"{k}={parts[k]}" for k in sorted(parts.keys()))
    return f"{prefix}|{tail}"


async def _get_cache(key: str) -> _CacheEntry | None:
    async with _CACHE_LOCK:
        return _CACHE.get(key)


async def _set_cache(key: str, value: Any, ttl_s: int) -> None:
    now = datetime.now(UTC)
    async with _CACHE_LOCK:
        _CACHE[key] = _CacheEntry(
            value=value,
            expires_at=asyncio.get_event_loop().time() + max(1, ttl_s),
            updated_at=now,
        )


def _is_expired(entry: _CacheEntry) -> bool:
    return asyncio.get_event_loop().time() > entry.expires_at


def normalize_ccxt_symbol(symbol: str | None) -> str:
    """Формат пары для CCXT Spot Binance: BTC/USDT (не BTCUSDT)."""
    s = (symbol or "").strip().upper().replace("-", "/")
    if not s:
        return "BTC/USDT"
    if "/" in s:
        parts = s.split("/", 1)
        return f"{parts[0].strip()}/{parts[1].strip()}"
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "BNB"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[: -len(quote)]}/{quote}"
    return f"{s}/USDT"


def normalize_ohlcv_timeframe(timeframe: str | None) -> str:
    """Binance/CCXT: минуты/часы в нижнем регистре (4H → 4h); месяц — только «NM» с большой M (1m ≠ 1M)."""
    if timeframe is None or not str(timeframe).strip():
        return "4h"
    t = str(timeframe).strip()
    if _TF_MONTH_RE.fullmatch(t):
        return t
    return t.lower()


def _to_binance_symbol(symbol: str) -> str:
    s = (symbol or "").upper().replace("-", "/")
    return s.replace("/", "")


def _to_okx_inst_id(symbol: str) -> str:
    """BTC/USDT → BTC-USDT для OKX public REST."""
    s = (symbol or "").strip().upper().replace("-", "/")
    if "/" in s:
        a, b = s.split("/", 1)
        return f"{a}-{b}"
    return "BTC-USDT"


async def _http_get_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params or {})
        resp.raise_for_status()
        return resp.json()


async def _fetch_funding_rate_bybit_rest(symbol_ccxt: str) -> dict[str, Any]:
    sym = _to_binance_symbol(symbol_ccxt)
    if not sym:
        return {}
    js = await _http_get_json(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "linear", "symbol": sym},
    )
    lst = ((js.get("result") or {}).get("list") or []) if isinstance(js, dict) else []
    if not lst or not isinstance(lst[0], dict):
        return {}
    row = lst[0]
    fr = row.get("fundingRate")
    if fr is None:
        return {}
    return {"lastFundingRate": str(fr), "symbol": sym, "source": "bybit_linear"}


async def _fetch_exchange_volumes_bybit_spot_rest(symbol_ccxt: str) -> dict[str, Any]:
    sym = _to_binance_symbol(symbol_ccxt)
    if not sym:
        return {}
    js = await _http_get_json(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "spot", "symbol": sym},
    )
    lst = ((js.get("result") or {}).get("list") or []) if isinstance(js, dict) else []
    if not lst or not isinstance(lst[0], dict):
        return {}
    row = lst[0]
    turnover = float(row.get("turnover24h") or 0)
    if turnover <= 0:
        return {}
    buy_ratio = row.get("buyRatio")
    ratio = None
    if buy_ratio is not None:
        try:
            ratio = float(buy_ratio)
        except (TypeError, ValueError):
            ratio = None
    return {
        "quote_volume_24h": turnover,
        "taker_buy_quote_share": ratio,
        "symbol": sym,
        "source": "bybit_spot_24hr",
    }


async def _fetch_exchange_volumes_okx_rest(symbol_ccxt: str) -> dict[str, Any]:
    inst = _to_okx_inst_id(symbol_ccxt)
    js = await _http_get_json(
        "https://www.okx.com/api/v5/market/ticker",
        params={"instId": inst},
    )
    data = (js.get("data") or []) if isinstance(js, dict) else []
    if not data or not isinstance(data[0], dict):
        return {}
    row = data[0]
    qv = float(row.get("volCcy24h") or 0)
    if qv <= 0:
        return {}
    return {
        "quote_volume_24h": qv,
        "taker_buy_quote_volume_24h": None,
        "taker_buy_quote_share": None,
        "symbol": inst.replace("-", ""),
        "source": "okx_spot_24hr",
    }


async def _bybit_linear_metrics_rest(symbol_ccxt: str) -> dict[str, Any]:
    """Фьючерсный тикер Bybit (обход блокировок Binance с EU IP)."""
    sym = _to_binance_symbol(symbol_ccxt)
    if not sym:
        raise ValueError("empty_symbol")
    js = await _http_get_json(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "linear", "symbol": sym},
    )
    lst = ((js.get("result") or {}).get("list") or []) if isinstance(js, dict) else []
    if not lst or not isinstance(lst[0], dict):
        raise ValueError("bybit_linear_empty")
    row = lst[0]
    fr_raw = row.get("fundingRate")
    fr_dec = float(fr_raw or 0.0)
    turnover = float(row.get("turnover24h") or 0.0)
    base_vol = float(row.get("volume24h") or 0.0)
    oi = row.get("openInterestValue") or row.get("openInterest") or 0
    try:
        oi_f = float(oi or 0.0)
    except (TypeError, ValueError):
        oi_f = 0.0
    return {
        "funding_rate": fr_dec * 100.0,
        "quote_volume": turnover,
        "base_volume": base_vol,
        "open_interest": oi_f,
        "long_short_ratio": None,
        "liquidations_proxy_ratio": None,
        "source": "bybit_linear_rest",
    }


def _normalize_fear_greed_from_index_payload(payload: Any) -> dict[str, Any]:
    """Разбор ответа Alternative.me FNG (сырой JSON)."""
    if not isinstance(payload, dict):
        return {"value": None, "classification": "No Data", "source": "unavailable"}
    row = (payload.get("data") or [{}])[0]
    if not isinstance(row, dict):
        return {"value": None, "classification": "No Data", "source": "unavailable"}
    raw_v = row.get("value")
    val: int | None = None
    if raw_v is not None and raw_v != "":
        try:
            val = int(float(str(raw_v).strip()))
        except (TypeError, ValueError):
            val = None
    return {
        "value": val,
        "classification": str(row.get("value_classification") or "unknown"),
        "source": "alternative_me",
    }


async def fetch_funding_rate(symbol: str) -> dict[str, Any]:
    """Ставка фандинга: Binance USDT-M, при 451/geo — Bybit linear REST."""
    sym = normalize_ccxt_symbol(symbol)
    bsym = _to_binance_symbol(sym)
    if not bsym:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": bsym},
            )
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            data.setdefault("source", "binance_usdm")
            return data
    except Exception as e:
        logger.warning(
            "fetch_funding_rate_binance_failed", extra={"symbol": bsym, "error": type(e).__name__}
        )
    try:
        fb = await _fetch_funding_rate_bybit_rest(sym)
        return fb
    except Exception as e:
        logger.warning(
            "fetch_funding_rate_bybit_failed", extra={"symbol": bsym, "error": type(e).__name__}
        )
        return {}


async def fetch_fear_greed_index() -> dict[str, Any]:
    """Сырой JSON Alternative.me Fear & Greed (`limit=1`)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.alternative.me/fng/", params={"limit": 1})
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("fetch_fear_greed_index_failed", extra={"error": type(e).__name__})
        return {}


async def fetch_exchange_volumes(symbol: str) -> dict[str, Any]:
    """Спот 24h: Binance, при недоступности — Bybit spot, затем OKX."""
    sym_ccxt = normalize_ccxt_symbol(symbol)
    bsym = _to_binance_symbol(sym_ccxt)
    if not bsym:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                params={"symbol": bsym},
            )
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            qv = float(data.get("quoteVolume") or 0)
            tbqv = float(data.get("takerBuyQuoteAssetVolume") or 0)
            ratio = (tbqv / qv) if qv > 0 else None
            return {
                "quote_volume_24h": qv,
                "taker_buy_quote_volume_24h": tbqv,
                "taker_buy_quote_share": ratio,
                "symbol": bsym,
                "source": "binance_spot_24hr",
            }
    except Exception as e:
        logger.warning(
            "fetch_exchange_volumes_binance_failed",
            extra={"symbol": bsym, "error": type(e).__name__},
        )
    try:
        out = await _fetch_exchange_volumes_bybit_spot_rest(sym_ccxt)
        if out:
            return out
    except Exception as e:
        logger.warning(
            "fetch_exchange_volumes_bybit_failed",
            extra={"symbol": bsym, "error": type(e).__name__},
        )
    try:
        return await _fetch_exchange_volumes_okx_rest(sym_ccxt)
    except Exception as e:
        logger.warning(
            "fetch_exchange_volumes_okx_failed",
            extra={"symbol": bsym, "error": type(e).__name__},
        )
        return {}


def _onchain_proxy_strings_usable(ctx: dict[str, Any]) -> bool:
    """True, если в строках прокси есть хоть одно содержательное значение (не заглушка)."""
    for key in ("funding_rate", "fear_greed_index", "approx_exchange_flow"):
        v = ctx.get(key)
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s or s == "Нет данных":
            continue
        return True
    return False


def _pack_onchain_proxy_fields(
    *,
    market: dict[str, Any],
    fear_greed: dict[str, Any],
    funding_rest: dict[str, Any],
    exchange_vol: dict[str, Any],
) -> dict[str, Any]:
    """Строки для промпта + флаг достаточности прокси для On-chain Analyst."""
    fr_pct: float | None = None
    if funding_rest.get("lastFundingRate") is not None:
        try:
            fr_pct = float(funding_rest["lastFundingRate"]) * 100.0
        except (TypeError, ValueError):
            fr_pct = None
    if fr_pct is None and market.get("funding_rate") is not None:
        try:
            fr_pct = float(market["funding_rate"])
        except (TypeError, ValueError):
            fr_pct = None
    fr_src = funding_rest.get("source") if isinstance(funding_rest.get("source"), str) else ""
    m_src = market.get("source") if isinstance(market.get("source"), str) else ""
    fr_label = "деривативный funding (REST)"
    if fr_src == "bybit_linear" or m_src == "bybit_linear_rest":
        fr_label = "Bybit linear perpetual"
    elif fr_src in ("", "binance_usdm") and m_src in ("", "binance_futures_ccxt"):
        fr_label = "Binance USDT-M premiumIndex"
    funding_rate_str = f"{fr_pct:.6f}% ({fr_label})" if fr_pct is not None else "Нет данных"

    fg_val = fear_greed.get("value")
    fg_cls = fear_greed.get("classification", "")
    fear_greed_index_str = (
        f"{fg_val} ({fg_cls}) [alternative.me]" if fg_val is not None else "Нет данных"
    )

    qv = exchange_vol.get("quote_volume_24h")
    ratio = exchange_vol.get("taker_buy_quote_share")
    vol_src = exchange_vol.get("source") if isinstance(exchange_vol.get("source"), str) else ""
    vol_venue = (
        "OKX spot 24h"
        if vol_src == "okx_spot_24hr"
        else "Bybit spot 24h"
        if vol_src == "bybit_spot_24hr"
        else "Binance spot 24h"
    )
    approx_flow_str = "Нет данных"
    if isinstance(qv, (int, float)) and qv > 0:
        if ratio is not None:
            approx_flow_str = (
                f"Quote vol 24h: {float(qv):,.0f} USDT | "
                f"taker/buy proxy share: {float(ratio) * 100:.2f}% ({vol_venue}, прокси давления)"
            )
        else:
            approx_flow_str = f"Quote vol 24h: {float(qv):,.0f} USDT ({vol_venue})"

    onchain_proxy_ok = bool(
        fr_pct is not None
        or fg_val is not None
        or (isinstance(qv, (int, float)) and float(qv) > 0)
    )
    if not onchain_proxy_ok:
        onchain_proxy_ok = _onchain_proxy_strings_usable(
            {
                "funding_rate": funding_rate_str,
                "fear_greed_index": fear_greed_index_str,
                "approx_exchange_flow": approx_flow_str,
            }
        )

    return {
        "funding_rate": funding_rate_str,
        "fear_greed_index": fear_greed_index_str,
        "approx_exchange_flow": approx_flow_str,
        "onchain_proxy_ok": onchain_proxy_ok,
        "onchain_proxy_detail": {
            "premium_index": funding_rest,
            "spot_24h": exchange_vol,
        },
    }


def has_actionable_onchain_proxy(ctx: dict[str, Any] | None) -> bool:
    """Есть ли бесплатные прокси-метрики для ончейн-роли (обход жёсткого PASS в оркестраторе)."""
    if not ctx:
        return False
    if ctx.get("onchain_proxy_ok") is True:
        return True
    return _onchain_proxy_strings_usable(ctx)


def _log_onchain_proxy_pack(proxy_pack: dict[str, Any]) -> None:
    logger.info(
        "On-chain proxy: funding=%s fg=%s flow=%s",
        proxy_pack.get("funding_rate"),
        proxy_pack.get("fear_greed_index"),
        proxy_pack.get("approx_exchange_flow"),
    )
    logger.info("onchain_proxy_ok=%s", proxy_pack.get("onchain_proxy_ok"))


async def _gather_parallel_market_extras(symbol: str) -> tuple[dict[str, Any], list[Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Параллельно: деривативные метрики (ccxt), новости, REST funding, спот 24h, F&G."""
    market_r, news_r, funding_r, exchange_r, fg_raw_r = await asyncio.gather(
        fetch_market_metrics(symbol),
        fetch_news_sentiment(symbol),
        fetch_funding_rate(symbol),
        fetch_exchange_volumes(symbol),
        fetch_fear_greed_index(),
        return_exceptions=True,
    )
    market: dict[str, Any] = (
        market_r if isinstance(market_r, dict) else {"stale_data": True, "source": "unavailable"}
    )
    news: list[Any] = news_r if isinstance(news_r, list) else []
    funding_rest = funding_r if isinstance(funding_r, dict) else {}
    exchange_vol = exchange_r if isinstance(exchange_r, dict) else {}
    fg_raw = fg_raw_r if isinstance(fg_raw_r, dict) else {}
    if isinstance(market_r, Exception):
        logger.warning("gather_market_metrics_failed", extra={"error": type(market_r).__name__})
    if isinstance(news_r, Exception):
        logger.warning("gather_news_failed", extra={"error": type(news_r).__name__})
    if isinstance(funding_r, Exception):
        logger.warning("gather_funding_failed", extra={"error": type(funding_r).__name__})
    if isinstance(exchange_r, Exception):
        logger.warning("gather_exchange_vol_failed", extra={"error": type(exchange_r).__name__})
    if isinstance(fg_raw_r, Exception):
        logger.warning("gather_fear_greed_failed", extra={"error": type(fg_raw_r).__name__})
    fear_greed = _normalize_fear_greed_from_index_payload(fg_raw)
    return market, news, funding_rest, exchange_vol, fear_greed


def _ohlcv_exchange_config(exchange_id: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {"enableRateLimit": True}
    if exchange_id in ("bybit", "okx"):
        cfg["options"] = {"defaultType": "spot"}
    return cfg


async def _fetch_ohlcv_one_exchange(exchange_id: str, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Одна попытка OHLCV; в df.attrs кладётся ohlcv_exchange."""
    if ccxt_async is None:
        raise RuntimeError("ccxt async backend unavailable")
    klass = getattr(ccxt_async, exchange_id, None)
    if klass is None:
        raise RuntimeError(f"ccxt has no exchange class: {exchange_id}")
    exchange = klass(_ohlcv_exchange_config(exchange_id))
    try:
        rows = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    finally:
        await exchange.close()
    if not rows:
        raise RuntimeError("empty ohlcv payload")
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.attrs["ohlcv_exchange"] = exchange_id
    return df


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
)
async def _fetch_ohlcv_remote(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Сначала Binance, затем Bybit/OKX spot (обход HTTP 451 restricted location)."""
    if ccxt_async is None:
        raise RuntimeError("ccxt async backend unavailable")
    errs: list[str] = []
    for ex_id in _OHLCV_EXCHANGE_FALLBACK_CHAIN:
        try:
            df = await _fetch_ohlcv_one_exchange(ex_id, symbol, timeframe, limit)
            logger.info(
                "ohlcv_exchange_selected",
                extra={"exchange": ex_id, "symbol": symbol, "timeframe": timeframe},
            )
            return df
        except Exception as e:
            errs.append(f"{ex_id}:{type(e).__name__}")
            logger.warning(
                "ohlcv_exchange_failed",
                extra={
                    "exchange": ex_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "error": type(e).__name__,
                },
            )
            continue
    raise RuntimeError("OHLCV failed on all exchanges: " + ", ".join(errs))


async def fetch_ohlcv_raw_debug(
    symbol: str,
    timeframe: str,
    limit: int = 120,
) -> dict[str, Any]:
    """Сырые списки свечей CCXT [[ts_ms, o,h,l,c,v], ...] без кэша и без pandas."""
    sym = normalize_ccxt_symbol(symbol)
    tf = normalize_ohlcv_timeframe(timeframe)
    lim = max(1, min(int(limit), 1000))
    if ccxt_async is None:
        return {
            "ok": False,
            "error": "ccxt_async_unavailable",
            "symbol": sym,
            "timeframe": tf,
            "candles": [],
        }
    logger.info("Fetching OHLCV (debug raw): %s %s (limit=%s)", sym, tf, lim)
    attempts: list[dict[str, str]] = []
    last_detail = ""
    for ex_id in _OHLCV_EXCHANGE_FALLBACK_CHAIN:
        klass = getattr(ccxt_async, ex_id, None)
        if klass is None:
            attempts.append({"exchange": ex_id, "error": "class_missing"})
            continue
        ex = klass(_ohlcv_exchange_config(ex_id))
        try:
            rows = await ex.fetch_ohlcv(sym, timeframe=tf, limit=lim)
            if not rows:
                attempts.append({"exchange": ex_id, "error": "empty_ohlcv"})
                continue
            last_raw = rows[-1][0]
            last_iso = datetime.fromtimestamp(last_raw / 1000.0, tz=UTC).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            logger.info(
                "OHLCV raw result: exchange=%s candles=%s last=%s",
                ex_id,
                len(rows),
                last_iso,
            )
            return {
                "ok": True,
                "exchange_id": ex_id,
                "symbol": sym,
                "timeframe": tf,
                "limit": lim,
                "count": len(rows),
                "last_open_time_ms": last_raw,
                "last_open_time_utc": last_iso,
                "candles": rows,
                "fallback_attempts": attempts,
            }
        except Exception as e:
            last_detail = str(e)[:800]
            attempts.append({"exchange": ex_id, "error": f"{type(e).__name__}:{last_detail[:200]}"})
            logger.warning(
                "fetch_ohlcv_raw_debug_try_failed",
                extra={"exchange": ex_id, "error": type(e).__name__},
            )
        finally:
            await ex.close()
    return {
        "ok": False,
        "error": "all_exchanges_failed",
        "detail": last_detail,
        "symbol": sym,
        "timeframe": tf,
        "candles": [],
        "fallback_attempts": attempts,
        "note": "Binance часто отвечает 451 из облака EU; используйте fallback Bybit/OKX в ответе или см. логи.",
    }


async def _new_binance_exchange() -> Any:
    if ccxt_async is None:
        raise RuntimeError("ccxt async backend unavailable")
    return ccxt_async.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    sym = normalize_ccxt_symbol(symbol)
    tf = normalize_ohlcv_timeframe(timeframe)
    lim = max(1, min(int(limit), 1000))
    logger.info("Fetching OHLCV: %s %s (limit=%s)", sym, tf, lim)
    key = _cache_key("ohlcv", symbol=sym, timeframe=tf, limit=lim)
    ttl_s = _ttl_for_timeframe(tf)
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        df_hit = cached.value.copy()
        try:
            last_ts = df_hit["timestamp"].iloc[-1]
            last_str = pd.Timestamp(last_ts).strftime("%Y-%m-%d %H:%M UTC") if len(df_hit) else None
        except Exception:
            last_str = None
        logger.info("OHLCV cache hit: %s candles, last=%s", len(df_hit), last_str)
        return df_hit
    try:
        df = await _fetch_ohlcv_remote(sym, tf, lim)
        await _set_cache(key, df, ttl_s)
        try:
            last_ts = df["timestamp"].iloc[-1]
            last_str = pd.Timestamp(last_ts).strftime("%Y-%m-%d %H:%M UTC") if len(df) else None
        except Exception:
            last_str = None
        logger.info("OHLCV result: %s candles, last=%s", len(df), last_str)
        return df.copy()
    except Exception as e:
        if cached is not None:
            logger.warning("market_ohlcv_stale_fallback", extra={"error": str(e), "key": key})
            return cached.value.copy()
        raise


async def get_ohlcv_cache_info(symbol: str, timeframe: str, limit: int = 200) -> dict[str, Any]:
    sym = normalize_ccxt_symbol(symbol)
    tf = normalize_ohlcv_timeframe(timeframe)
    lim = max(1, min(int(limit), 1000))
    key = _cache_key("ohlcv", symbol=sym, timeframe=tf, limit=lim)
    entry = await _get_cache(key)
    if entry is None:
        return {"hit": False, "ttl_remaining_sec": 0}
    ttl_remaining = max(0, int(entry.expires_at - asyncio.get_event_loop().time()))
    return {"hit": True, "ttl_remaining_sec": ttl_remaining, "updated_at": entry.updated_at.isoformat()}


def _series_last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _ema_manual(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def calculate_indicators(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"stale_data": True}

    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")

    ema20 = _ema_manual(close, 20)
    ema50 = _ema_manual(close, 50)

    use_fallback = ta is None
    if not use_fallback:
        try:
            rsi = ta.rsi(close, length=14)
            macd = ta.macd(close, fast=12, slow=26, signal=9)
            atr = ta.atr(high, low, close, length=14)
            bb = ta.bbands(close, length=20, std=2)
        except Exception:
            use_fallback = True
    if use_fallback:
        # Fallback расчеты, если pandas-ta недоступен.
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, math.nan)
        rsi = 100 - (100 / (1 + rs))
        ema12 = _ema_manual(close, 12)
        ema26 = _ema_manual(close, 26)
        macd_line = ema12 - ema26
        signal = _ema_manual(macd_line, 9)
        macd = pd.DataFrame({"MACD_12_26_9": macd_line, "MACDs_12_26_9": signal})
        tr = pd.concat(
            [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean()
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        bb = pd.DataFrame(
            {
                "BBL_20_2.0": mid - 2 * std,
                "BBM_20_2.0": mid,
                "BBU_20_2.0": mid + 2 * std,
            }
        )

    if isinstance(macd, pd.DataFrame):
        macd_line = _series_last(macd.get("MACD_12_26_9", pd.Series(dtype=float)))
        macd_signal = _series_last(macd.get("MACDs_12_26_9", pd.Series(dtype=float)))
    else:
        macd_line = None
        macd_signal = None

    if isinstance(bb, pd.DataFrame):
        bb_low = _series_last(bb.get("BBL_20_2.0", pd.Series(dtype=float)))
        bb_mid = _series_last(bb.get("BBM_20_2.0", pd.Series(dtype=float)))
        bb_high = _series_last(bb.get("BBU_20_2.0", pd.Series(dtype=float)))
    else:
        bb_low = bb_mid = bb_high = None

    # Упрощенный POC: price-bin с максимальным накопленным volume.
    poc = None
    try:
        bins = pd.cut(close, bins=20)
        vol_by_bin = volume.groupby(bins).sum()
        top_bin = vol_by_bin.idxmax()
        poc = float((top_bin.left + top_bin.right) / 2)  # type: ignore[union-attr]
    except Exception:
        poc = None

    return {
        "price": _series_last(close),
        "rsi_14": _series_last(rsi if isinstance(rsi, pd.Series) else pd.Series(dtype=float)),
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "ema_20": _series_last(ema20),
        "ema_50": _series_last(ema50),
        "ema_cross": (
            "bullish"
            if (_series_last(ema20) or 0) > (_series_last(ema50) or 0)
            else "bearish"
        ),
        "atr_14": _series_last(atr if isinstance(atr, pd.Series) else pd.Series(dtype=float)),
        "bb_lower": bb_low,
        "bb_mid": bb_mid,
        "bb_upper": bb_high,
        "poc": poc,
    }


async def _fetch_market_metrics_remote(symbol: str) -> dict[str, Any]:
    sym = normalize_ccxt_symbol(symbol)
    exchange = await _new_binance_exchange()
    try:
        funding = await exchange.fetch_funding_rate(sym)
        ticker = await exchange.fetch_ticker(sym)
    finally:
        await exchange.close()
    return {
        "funding_rate": float(funding.get("fundingRate") or 0.0) * 100.0,
        "quote_volume": float(ticker.get("quoteVolume") or 0.0),
        "base_volume": float(ticker.get("baseVolume") or 0.0),
        "open_interest": float((funding.get("info") or {}).get("openInterest") or 0.0),
        "long_short_ratio": None,
        "liquidations_proxy_ratio": None,
        "source": "binance_futures_ccxt",
    }


async def _fetch_market_metrics_remote_with_fallback(symbol: str) -> dict[str, Any]:
    """Сначала Binance futures (ccxt), при ошибке — Bybit linear REST (EU/hosting)."""
    sym = normalize_ccxt_symbol(symbol)
    try:
        return await _fetch_market_metrics_remote(sym)
    except Exception as e:
        logger.warning(
            "market_metrics_binance_remote_failed",
            extra={"symbol": sym, "error": type(e).__name__},
        )
    return await _bybit_linear_metrics_rest(sym)


async def fetch_market_metrics(symbol: str) -> dict[str, Any]:
    key = _cache_key("metrics", symbol=symbol)
    ttl_s = 300
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        out = dict(cached.value)
        out["stale_data"] = False
        return out
    try:
        payload = await _fetch_market_metrics_remote_with_fallback(symbol)
        payload["stale_data"] = False
        await _set_cache(key, payload, ttl_s)
        return dict(payload)
    except Exception as e:
        if cached is not None:
            out = dict(cached.value)
            out["stale_data"] = True
            logger.warning("market_metrics_stale_fallback", extra={"error": str(e), "key": key})
            return out
        return {"stale_data": True, "source": "unavailable"}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
)
async def _fetch_fear_greed_remote() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get("https://api.alternative.me/fng/", params={"limit": 1})
        resp.raise_for_status()
    payload = resp.json()
    row = (payload.get("data") or [{}])[0]
    return {
        "value": int(row.get("value") or 0),
        "classification": str(row.get("value_classification") or "unknown"),
        "source": "alternative_me",
    }


async def fetch_fear_greed() -> dict[str, Any]:
    key = _cache_key("fear_greed")
    ttl_s = 900
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        return dict(cached.value)
    try:
        payload = await _fetch_fear_greed_remote()
        await _set_cache(key, payload, ttl_s)
        return dict(payload)
    except Exception as e:
        if cached is not None:
            logger.warning("fear_greed_stale_fallback", extra={"error": str(e)})
            return dict(cached.value)
        return {"value": None, "classification": "No Data", "source": "unavailable"}


def _simple_tone(title: str) -> str:
    t = (title or "").lower()
    pos = ("surge", "rally", "growth", "bull", "adoption", "approval", "inflow")
    neg = ("hack", "drop", "ban", "outflow", "bear", "lawsuit", "risk")
    if any(k in t for k in pos):
        return "positive"
    if any(k in t for k in neg):
        return "negative"
    return "neutral"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
)
async def _fetch_news_remote(symbol: str) -> list[dict[str, Any]]:
    token = (symbol or "BTC/USDT").split("/")[0].upper()
    url = "https://min-api.cryptocompare.com/data/v2/news/"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={"lang": "EN", "categories": token})
        resp.raise_for_status()
    payload = resp.json()
    data = payload.get("Data") or []
    out: list[dict[str, Any]] = []
    for item in data[:5]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        ts = item.get("published_on")
        published = datetime.fromtimestamp(int(ts), tz=UTC).isoformat() if ts else None
        out.append(
            {
                "title": title,
                "tone": _simple_tone(title),
                "timestamp": published,
                "source": item.get("source_info", {}).get("name") or "cryptocompare",
            }
        )
    return out


async def fetch_news_sentiment(symbol: str) -> list[dict[str, Any]]:
    key = _cache_key("news", symbol=symbol)
    ttl_s = 600
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        return list(cached.value)
    try:
        rows = await _fetch_news_remote(symbol)
        await _set_cache(key, rows, ttl_s)
        return list(rows)
    except Exception as e:
        if cached is not None:
            logger.warning("market_news_stale_fallback", extra={"error": str(e), "key": key})
            return list(cached.value)
        return []


async def fetch_live_context(
    asset: str, timeframe: str = "4h", limit: int = 200, *, force_refresh: bool = False
) -> dict[str, Any]:
    symbol = normalize_ccxt_symbol(asset)
    tf = normalize_ohlcv_timeframe(timeframe)
    lim = max(1, min(int(limit), 1000))
    ohlcv_key = _cache_key("ohlcv", symbol=symbol, timeframe=tf, limit=lim)
    cached_ohlcv = await _get_cache(ohlcv_key)

    freshness = "live"
    source = "binance"
    stale = False
    try:
        if force_refresh and ccxt_async is not None:
            # Принудительно обновляем источник, затем используем как новое live-состояние.
            df = await _fetch_ohlcv_remote(symbol, tf, lim)
            await _set_cache(ohlcv_key, df, _ttl_for_timeframe(tf))
        else:
            df = await fetch_ohlcv(symbol, tf, lim)
    except Exception:
        if cached_ohlcv is None:
            market_e, news_e, funding_e, exchange_e, fear_e = await _gather_parallel_market_extras(symbol)
            proxy_e = _pack_onchain_proxy_fields(
                market=market_e,
                fear_greed=fear_e,
                funding_rest=funding_e,
                exchange_vol=exchange_e,
            )
            _log_onchain_proxy_pack(proxy_e)
            now_u = datetime.now(UTC)
            out_fail: dict[str, Any] = {
                "asset": symbol,
                "timeframe": tf.upper(),
                "updated_at": now_u.strftime("%Y-%m-%d %H:%M"),
                "current_system_time_utc": now_u.strftime("%Y-%m-%d %H:%M"),
                "last_ohlcv_candle_utc": None,
                "data_freshness": "unavailable",
                "source": market_e.get("source") or "unavailable",
                "stale_data": True,
                "price": None,
                "open": None,
                "high": None,
                "low": None,
                "volume": None,
                "candles_count": 0,
                "change_24h_pct": None,
                "indicators": {},
                "market_metrics": market_e,
                "fear_greed": fear_e,
                "news_sentiment": news_e,
                **proxy_e,
            }
            out_fail["data_freshness_status"] = compute_data_freshness_status(out_fail)
            return out_fail
        df = cached_ohlcv.value.copy()
        stale = True

    if cached_ohlcv is not None and _is_expired(cached_ohlcv):
        stale = True
    if stale:
        freshness = "cached"

    indicators = calculate_indicators(df)
    market, news, funding_rest, exchange_vol, fear_greed = await _gather_parallel_market_extras(symbol)
    proxy_pack = _pack_onchain_proxy_fields(
        market=market,
        fear_greed=fear_greed,
        funding_rest=funding_rest,
        exchange_vol=exchange_vol,
    )
    _log_onchain_proxy_pack(proxy_pack)

    if market.get("stale_data") is True:
        freshness = "cached" if freshness == "live" else freshness
    if freshness == "cached":
        stale = True

    close = pd.to_numeric(df["close"], errors="coerce")
    price = float(close.iloc[-1]) if not close.empty else None
    day_change = None
    if len(close) > 24:
        prev = float(close.iloc[-24]) if float(close.iloc[-24]) != 0 else 0.0
        if prev:
            day_change = ((price - prev) / prev) * 100.0 if price is not None else None

    now_utc = datetime.now(UTC)
    last_ohlcv_candle_utc: str | None = None
    if not df.empty and "timestamp" in df.columns:
        ts = df["timestamp"].iloc[-1]
        if pd.notna(ts):
            ts_pd = pd.Timestamp(ts)
            if ts_pd.tzinfo is None:
                ts_pd = ts_pd.tz_localize("UTC")
            else:
                ts_pd = ts_pd.tz_convert("UTC")
            last_ohlcv_candle_utc = ts_pd.strftime("%Y-%m-%d %H:%M UTC")

    base: dict[str, Any] = {
        "asset": symbol,
        "timeframe": tf.upper(),
        "updated_at": now_utc.strftime("%Y-%m-%d %H:%M"),
        "current_system_time_utc": now_utc.strftime("%Y-%m-%d %H:%M"),
        "last_ohlcv_candle_utc": last_ohlcv_candle_utc,
        "open": float(pd.to_numeric(df["open"], errors="coerce").iloc[-1]) if not df.empty else None,
        "high": float(pd.to_numeric(df["high"], errors="coerce").iloc[-1]) if not df.empty else None,
        "low": float(pd.to_numeric(df["low"], errors="coerce").iloc[-1]) if not df.empty else None,
        "volume": float(pd.to_numeric(df["volume"], errors="coerce").iloc[-1]) if not df.empty else None,
        "candles_count": int(len(df)),
        "price": price,
        "change_24h_pct": day_change,
        "indicators": indicators,
        "market_metrics": market,
        "fear_greed": fear_greed,
        "news_sentiment": news,
        "data_freshness": freshness,
        "source": market.get("source") or source,
        "ohlcv_exchange": str(df.attrs.get("ohlcv_exchange", "unknown")),
        "stale_data": stale,
        **proxy_pack,
    }
    base["data_freshness_status"] = compute_data_freshness_status(base)
    return base


def _timeframe_to_timedelta(tf: str | None) -> timedelta:
    """Длительность одной свечи (грубо, для порога свежести OHLCV)."""
    if not tf:
        return timedelta(hours=4)
    raw = str(tf).strip()
    if _TF_MONTH_RE.fullmatch(raw):
        try:
            n = max(1, int(raw[:-1]))
        except ValueError:
            n = 1
        return timedelta(days=30 * n)
    t = raw.lower()
    if len(t) < 2:
        return timedelta(hours=4)
    unit = t[-1]
    try:
        n = int(t[:-1])
    except ValueError:
        return timedelta(hours=4)
    if unit == "m":
        return timedelta(minutes=max(1, n))
    if unit == "h":
        return timedelta(hours=max(1, n))
    if unit == "d":
        return timedelta(days=max(1, n))
    if unit == "w":
        return timedelta(weeks=max(1, n))
    return timedelta(hours=4)


def _ohlcv_last_open_max_age(tf: str | None) -> timedelta:
    """Допустимый возраст timestamp последней свечи (у Binance это время ОТКРЫТИЯ бара).

    Раньше использовался фиксированный 1h — из‑за этого 4H/1D всегда были STALE после первого часа бара,
    и Technical Analyst получал жёсткий PASS при живых данных.
    """
    bar = _timeframe_to_timedelta(tf)
    slack = timedelta(minutes=45)
    # Нижняя граница 90s — для 1m не раздуваем окно до часа
    return max(bar + slack, timedelta(seconds=90))


def compute_data_freshness_status(ctx: dict[str, Any] | None) -> str:
    """Агрегированный статус для промптов: LIVE | CACHED | STALE | UNAVAILABLE."""
    if not ctx:
        return "UNAVAILABLE"
    preset = ctx.get("data_freshness_status")
    if preset in ("LIVE", "CACHED", "STALE", "UNAVAILABLE"):
        return str(preset)
    if ctx.get("data_freshness") == "unavailable":
        return "UNAVAILABLE"
    if ctx.get("price") is None:
        return "UNAVAILABLE"
    raw_lc = ctx.get("last_ohlcv_candle_utc")
    if not raw_lc or not isinstance(raw_lc, str):
        return "UNAVAILABLE"
    try:
        parsed = datetime.strptime(raw_lc.replace(" UTC", "").strip(), "%Y-%m-%d %H:%M").replace(
            tzinfo=UTC
        )
    except ValueError:
        return "UNAVAILABLE"
    tf_ctx = ctx.get("timeframe")
    tf_key = tf_ctx if isinstance(tf_ctx, str) else None
    max_age = _ohlcv_last_open_max_age(normalize_ohlcv_timeframe(tf_key) if tf_key else None)
    if datetime.now(UTC) - parsed > max_age:
        return "STALE"
    if ctx.get("stale_data") is True:
        return "STALE"
    if ctx.get("data_freshness") == "live":
        return "LIVE"
    return "CACHED"


def _onchain_proxy_markdown_block(ctx: dict[str, Any]) -> str:
    """Секция прокси для On-chain Analyst (Binance REST + F&G + спот 24h)."""
    fr = ctx.get("funding_rate")
    fg = ctx.get("fear_greed_index")
    fl = ctx.get("approx_exchange_flow")
    if not any(isinstance(x, str) and x and x != "Нет данных" for x in (fr, fg, fl)):
        return ""
    return (
        "\n🔬 ONCHAIN_PROXY (бесплатные источники; прокси ликвидности/настроения, не Glassnode):\n"
        f"- funding_rate: {fr}\n"
        f"- fear_greed_index: {fg}\n"
        f"- approx_exchange_flow: {fl}\n"
    )


def format_live_context_markdown(ctx: dict[str, Any] | None) -> str:
    now_ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    status = compute_data_freshness_status(ctx)
    header = (
        f"CURRENT_UTC_TIMESTAMP: {now_ts} UTC\n"
        f"CURRENT_SYSTEM_TIME: {now_ts} UTC\n"
        f"DATA_FRESHNESS_STATUS: {status}\n"
    )

    if status in ("STALE", "UNAVAILABLE"):
        c = ctx or {}
        asset = c.get("asset") or "Нет данных"
        tf = c.get("timeframe") or "Нет данных"
        raw_f = c.get("data_freshness", "unavailable")
        src = c.get("source", "unknown")
        last_c = c.get("last_ohlcv_candle_utc") or "Нет данных"
        updated = c.get("updated_at") or "Нет данных"
        proxy_block = _onchain_proxy_markdown_block(c)
        proxy_note = ""
        if has_actionable_onchain_proxy(c):
            proxy_note = (
                "\n(On-chain Analyst при наличии ONCHAIN_PROXY ниже не возвращает PASS из-за статуса свечей; "
                "остальные роли по-прежнему обязаны следовать DATA_FRESHNESS_STATUS.)\n"
            )
        return (
            header
            + f"LAST_OHLCV_CANDLE_CLOSE_TIME: {last_c}\n"
            + f"📊 LIVE DATA CONTEXT — вывод по рынку ЗАПРЕЩЁН (DATA_FRESHNESS_STATUS={status})\n"
            f"Asset: {asset} | Timeframe: {tf}\n"
            "Price: Нет данных | 24h Δ: Нет данных\n"
            "📈 Indicators: RSI(14)=Нет данных, MACD=Нет данных, EMA(20/50)=Нет данных, ATR=Нет данных\n"
            "📉 Market: Funding=Нет данных, Volume(USDT)=Нет данных, OI=Нет данных, Fear&Greed=Нет данных\n"
            "📰 News/Sentiment: Нет данных\n"
            f"Context snapshot updated_at: {updated} | Data Freshness (raw): {raw_f} | Source: {src}\n"
            + proxy_note
            + proxy_block
            + "(При STALE/UNAVAILABLE технический/сентимент/риск — только PASS; см. ONCHAIN_PROXY для исключения on-chain.)\n"
        )

    ind = ctx.get("indicators") or {}
    market = ctx.get("market_metrics") or {}
    fg = ctx.get("fear_greed") or {}
    news = ctx.get("news_sentiment") or []
    news_summary = " | ".join(
        f"{n.get('title', 'Нет данных')} ({n.get('tone', 'neutral')})" for n in news[:2]
    ) or "Нет данных"
    last_candle = ctx.get("last_ohlcv_candle_utc") or "Нет данных"

    return (
        header
        + f"LAST_OHLCV_CANDLE_CLOSE_TIME: {last_candle}\n"
        + f"📊 LIVE DATA CONTEXT (Updated: {ctx.get('updated_at')} UTC)\n"
        f"Asset: {ctx.get('asset')} | Timeframe: {ctx.get('timeframe')}\n"
        f"Price: {ctx.get('price', 'Нет данных')} | 24h Δ: {ctx.get('change_24h_pct', 'Нет данных')}%\n"
        f"📈 Indicators: RSI(14)={ind.get('rsi_14', 'Нет данных')}, "
        f"MACD={ind.get('macd_signal', 'Нет данных')}, EMA(20/50)={ind.get('ema_cross', 'Нет данных')}, "
        f"ATR={ind.get('atr_14', 'Нет данных')}\n"
        f"📉 Market: Funding={market.get('funding_rate', 'Нет данных')}%, "
        f"Volume(USDT)={market.get('quote_volume', 'Нет данных')}, "
        f"OI={market.get('open_interest', 'Нет данных')} USD\n"
        f"🧠 Fear & Greed: {fg.get('value', 'Нет данных')} ({fg.get('classification', 'No Data')})\n"
        f"📰 News/Sentiment: {news_summary}\n"
        f"{_onchain_proxy_markdown_block(ctx)}"
        f"Data Freshness (raw): {ctx.get('data_freshness', 'cached')} | Source: {ctx.get('source', 'unknown')}"
    )


async def _main() -> None:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ctx = await fetch_live_context(asset="BTC/USDT", timeframe="4h")
    print(format_live_context_markdown(ctx))
    df = await fetch_ohlcv("BTC/USDT", "4h", 120)
    print("OHLCV rows:", len(df))
    print("Indicators keys:", sorted(calculate_indicators(df).keys()))


if __name__ == "__main__":
    asyncio.run(_main())

