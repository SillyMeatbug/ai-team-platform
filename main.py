"""Точка входа: FastAPI + lifespan + JSON-логи."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_library_router import router as agent_library_router
from app.api.chat_router import router as chat_router
from app.api.files_router import router as files_router
from app.api.metrics_router import router as metrics_router
from app.api.market_router import router as market_router
from app.api.projects_router import router as projects_router
from app.api.router import router
from app.config.loader import apply_openrouter_env, load_settings
from app.core.lifespan import lifespan
from app.core.logging_config import configure_logging

settings = load_settings()
apply_openrouter_env(settings)
configure_logging(settings.log_level)

app = FastAPI(
    title="LLM Aggregator",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(projects_router, prefix="/v1")
app.include_router(files_router, prefix="/v1")
app.include_router(agent_library_router, prefix="/v1")
app.include_router(chat_router, prefix="/v1")
app.include_router(market_router, prefix="/v1/market")
app.include_router(metrics_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
