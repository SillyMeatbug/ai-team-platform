"""Эндпоинт Prometheus text exposition."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def prometheus_metrics(request: Request) -> PlainTextResponse:
    body = request.app.state.metrics.render()
    return PlainTextResponse(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
