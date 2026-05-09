"""Lifecycle FastAPI: пул httpx и загрузка маршрутов."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config.loader import (
    RoutesConfig,
    Settings,
    apply_openrouter_env,
    load_routes_config,
    load_settings,
    project_dotenv_path,
    resolved_routes_yaml_path,
)
from app.core.budget import BudgetLimiter
from app.core.cache import AggregationCache
from app.core.database import configure_from_settings, dispose_engine, init_db
from app.core.metrics import get_metrics
from app.core.seed import seed_agents
from app.core.storage import FileStorage
from app.core.logging_config import log_payload

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Инициализация на старте, очистка при shutdown.
    Один AsyncClient на приложение — без глобальных синглтонов модулей.
    """
    _dotenv = project_dotenv_path()
    settings: Settings = load_settings()
    apply_openrouter_env(settings)
    routes_path = resolved_routes_yaml_path(settings)
    try:
        routes_config: RoutesConfig = load_routes_config(routes_path)
    except Exception:
        logger.exception(
            "routes_config_load_failed",
            extra={
                "log_payload": {
                    "path": str(routes_path),
                }
            },
        )
        raise

    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    timeout = httpx.Timeout(30.0)
    client = httpx.AsyncClient(limits=limits, timeout=timeout)

    configure_from_settings(settings)
    await init_db()
    seeded = await seed_agents()

    upload_root = settings.resolved_upload_dir()
    upload_root.mkdir(parents=True, exist_ok=True)

    app.state.settings = settings
    app.state.routes_config = routes_config
    app.state.http_client = client
    app.state.routes_yaml_resolved_path = routes_path
    app.state.metrics = get_metrics()
    app.state.budget_limiter = BudgetLimiter(
        max_cost_per_request=settings.max_cost_per_request,
        max_daily_cost=settings.max_daily_cost,
    )
    app.state.response_cache = AggregationCache(
        routes_path,
        max_entries=settings.cache_max_entries,
    )
    app.state.file_storage = FileStorage(
        root=upload_root,
        max_file_size_bytes=settings.max_file_size_mb * 1024 * 1024,
        allowed_extensions=settings.allowed_file_extensions(),
    )

    log_payload(
        logger,
        logging.INFO,
        "lifespan_startup_complete",
        routes_count=len(routes_config.routes),
        routes_file=str(routes_path),
        dotenv_path=str(_dotenv),
        dotenv_exists=_dotenv.is_file(),
        openrouter_key_configured=bool(os.getenv("OPENROUTER_API_KEY")),
        aggregate_mock_providers=settings.aggregate_mock_providers,
        database_url_scheme=settings.database_url.split(":", 1)[0],
        upload_dir=str(upload_root),
        agents_seeded=seeded,
    )

    yield

    await client.aclose()
    await dispose_engine()
    log_payload(logger, logging.INFO, "lifespan_shutdown_complete")
