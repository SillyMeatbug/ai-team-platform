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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

try:
    import ccxt.async_support as ccxt_async
except Exception:  # pragma: no cover
    ccxt_async = None

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
    tf = (timeframe or "").lower()
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


def _to_binance_symbol(symbol: str) -> str:
    s = (symbol or "").upper().replace("-", "/")
    return s.replace("/", "")


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
)
async def _fetch_ohlcv_remote(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    if ccxt_async is None:
        raise RuntimeError("ccxt async backend unavailable")
    exchange = ccxt_async.binance({"enableRateLimit": True})
    try:
        rows = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    finally:
        await exchange.close()
    if not rows:
        raise RuntimeError("empty ohlcv payload")
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


async def _new_binance_exchange() -> Any:
    if ccxt_async is None:
        raise RuntimeError("ccxt async backend unavailable")
    return ccxt_async.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    key = _cache_key("ohlcv", symbol=symbol, timeframe=timeframe, limit=limit)
    ttl_s = _ttl_for_timeframe(timeframe)
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        return cached.value.copy()
    try:
        df = await _fetch_ohlcv_remote(symbol, timeframe, limit)
        await _set_cache(key, df, ttl_s)
        return df.copy()
    except Exception as e:
        if cached is not None:
            logger.warning("market_ohlcv_stale_fallback", extra={"error": str(e), "key": key})
            return cached.value.copy()
        raise


async def get_ohlcv_cache_info(symbol: str, timeframe: str, limit: int = 200) -> dict[str, Any]:
    key = _cache_key("ohlcv", symbol=symbol, timeframe=timeframe, limit=limit)
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


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(Exception),
)
async def _fetch_market_metrics_remote(symbol: str) -> dict[str, Any]:
    exchange = await _new_binance_exchange()
    try:
        funding = await exchange.fetch_funding_rate(symbol)
        ticker = await exchange.fetch_ticker(symbol)
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


async def fetch_market_metrics(symbol: str) -> dict[str, Any]:
    key = _cache_key("metrics", symbol=symbol)
    ttl_s = 300
    cached = await _get_cache(key)
    if cached and not _is_expired(cached):
        out = dict(cached.value)
        out["stale_data"] = False
        return out
    try:
        payload = await _fetch_market_metrics_remote(symbol)
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
    symbol = (asset or "BTC/USDT").upper()
    tf = (timeframe or "4h").lower()
    ohlcv_key = _cache_key("ohlcv", symbol=symbol, timeframe=tf, limit=limit)
    cached_ohlcv = await _get_cache(ohlcv_key)

    freshness = "live"
    source = "binance"
    stale = False
    try:
        if force_refresh and ccxt_async is not None:
            # Принудительно обновляем источник, затем используем как новое live-состояние.
            df = await _fetch_ohlcv_remote(symbol, tf, limit)
            await _set_cache(ohlcv_key, df, _ttl_for_timeframe(tf))
        else:
            df = await fetch_ohlcv(symbol, tf, limit)
    except Exception:
        if cached_ohlcv is None:
            return {
                "asset": symbol,
                "timeframe": tf,
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
                "data_freshness": "unavailable",
                "source": "unavailable",
                "stale_data": True,
            }
        df = cached_ohlcv.value.copy()
        stale = True

    if cached_ohlcv is not None and _is_expired(cached_ohlcv):
        stale = True
    if stale:
        freshness = "cached"

    indicators = calculate_indicators(df)
    market = await fetch_market_metrics(symbol)
    fear_greed = await fetch_fear_greed()
    news = await fetch_news_sentiment(symbol)

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

    return {
        "asset": symbol,
        "timeframe": tf.upper(),
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
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
        "stale_data": stale,
    }


def format_live_context_markdown(ctx: dict[str, Any]) -> str:
    if not ctx or ctx.get("data_freshness") == "unavailable":
        return (
            "📊 LIVE DATA CONTEXT (Updated: Нет данных)\n"
            "Asset: Нет данных | Timeframe: Нет данных\n"
            "Price: Нет данных | 24h Δ: Нет данных\n"
            "📈 Indicators: RSI(14)=Нет данных, MACD=Нет данных, EMA(20/50)=Нет данных, ATR=Нет данных\n"
            "📉 Market: Funding=Нет данных, Volume(USDT)=Нет данных, OI=Нет данных, Fear&Greed=Нет данных\n"
            "📰 News/Sentiment: Нет данных\n"
            "Data Freshness: unavailable | Source: unavailable"
        )
    ind = ctx.get("indicators") or {}
    market = ctx.get("market_metrics") or {}
    fg = ctx.get("fear_greed") or {}
    news = ctx.get("news_sentiment") or []
    news_summary = " | ".join(
        f"{n.get('title', 'Нет данных')} ({n.get('tone', 'neutral')})" for n in news[:2]
    ) or "Нет данных"
    return (
        f"📊 LIVE DATA CONTEXT (Updated: {ctx.get('updated_at')} UTC)\n"
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
        f"Data Freshness: {ctx.get('data_freshness', 'cached')} | Source: {ctx.get('source', 'unknown')}"
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

