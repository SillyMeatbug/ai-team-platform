from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Agent, PaperTrade
from app.services.market_data import fetch_live_context

_TS_RE = re.compile(r"Сигнал сгенерирован:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})\s*UTC", re.I)
_CONF_RE = re.compile(r"Уверенность:\s*([0-9]{1,3})(?:[.,][0-9]+)?\s*%", re.I)
_STOP_RE = re.compile(r"Стоп-лосс:\s*([0-9]+(?:[.,][0-9]+)?)", re.I)
_TP_RE = re.compile(r"Тейк-профит:\s*([0-9]+(?:[.,][0-9]+)?)", re.I)


def _to_float(match: re.Match[str] | None) -> float | None:
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except Exception:
        return None


def _parse_signal(content: str) -> str:
    txt = (content or "").lower()
    if "бычий" in txt:
        return "long"
    if "медвеж" in txt:
        return "short"
    return "neutral"


def _parse_signal_timestamp(content: str) -> datetime:
    m = _TS_RE.search(content or "")
    if not m:
        return datetime.now(UTC)
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except Exception:
        return datetime.now(UTC)


async def record_trade_from_signal(
    session: AsyncSession,
    *,
    project_id: str,
    agent: Agent,
    content: str,
    asset: str,
    timeframe: str,
    market_context: dict[str, Any] | None = None,
) -> PaperTrade | None:
    if agent.role not in {"technical_analyst", "onchain_analyst", "sentiment_analyst", "risk_manager"}:
        return None
    signal = _parse_signal(content)
    if signal == "neutral":
        return None

    price = None
    if market_context:
        price = market_context.get("price")
    if price is None:
        ctx = await fetch_live_context(asset=asset, timeframe=timeframe)
        price = ctx.get("price")
    if price is None:
        return None

    conf_match = _CONF_RE.search(content or "")
    confidence = float(conf_match.group(1)) if conf_match else 0.0
    stop_loss = _to_float(_STOP_RE.search(content or ""))
    take_profit = _to_float(_TP_RE.search(content or ""))
    signal_ts = _parse_signal_timestamp(content or "")
    rationale = (content or "").strip()
    if len(rationale) > 500:
        rationale = rationale[:500] + "…"

    trade = PaperTrade(
        project_id=project_id,
        agent_id=agent.id,
        asset=asset.upper(),
        timeframe=timeframe.upper(),
        signal=signal,
        entry_price=float(price),
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=max(0.0, min(100.0, confidence)),
        rationale=rationale,
        signal_timestamp=signal_ts,
        opened_at=datetime.now(UTC),
        status="open",
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade)
    return trade


def _calc_pnl_pct(signal: str, entry: float, exit_price: float) -> float:
    if entry == 0:
        return 0.0
    if signal == "long":
        return ((exit_price - entry) / entry) * 100.0
    if signal == "short":
        return ((entry - exit_price) / entry) * 100.0
    return 0.0


async def reconcile_open_trades(
    session: AsyncSession,
    *,
    project_id: str,
    asset: str | None = None,
    timeframe: str | None = None,
) -> int:
    stmt = select(PaperTrade).where(PaperTrade.project_id == project_id, PaperTrade.status == "open")
    if asset:
        stmt = stmt.where(PaperTrade.asset == asset.upper())
    if timeframe:
        stmt = stmt.where(PaperTrade.timeframe == timeframe.upper())
    open_trades = (await session.execute(stmt)).scalars().all()
    updated = 0
    for tr in open_trades:
        ctx = await fetch_live_context(asset=tr.asset, timeframe=tr.timeframe)
        px = ctx.get("price")
        if px is None:
            continue
        exit_status = None
        if tr.signal == "long":
            if tr.stop_loss is not None and px <= tr.stop_loss:
                exit_status = "stopped"
            elif tr.take_profit is not None and px >= tr.take_profit:
                exit_status = "closed"
        elif tr.signal == "short":
            if tr.stop_loss is not None and px >= tr.stop_loss:
                exit_status = "stopped"
            elif tr.take_profit is not None and px <= tr.take_profit:
                exit_status = "closed"
        if exit_status:
            tr.exit_price = float(px)
            tr.closed_at = datetime.now(UTC)
            tr.pnl_pct = _calc_pnl_pct(tr.signal, tr.entry_price, tr.exit_price)
            tr.status = exit_status
            updated += 1
    if updated:
        await session.commit()
    return updated
