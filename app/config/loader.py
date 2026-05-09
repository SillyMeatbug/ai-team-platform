"""Загрузка и валидация routes.yaml через Pydantic."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень репозитория (app/config/loader.py → три уровня вверх).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def project_dotenv_path() -> Path:
    """Путь к `.env` в корне проекта (рядом с main.py)."""
    return _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Переменные окружения приложения."""

    model_config = SettingsConfigDict(
        env_file=project_dotenv_path(),
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    routes_yaml_path: Path = Field(default=Path("routes.yaml"))
    log_level: str = Field(default="INFO")
    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "openrouter_api_key"),
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices("OPENROUTER_BASE_URL", "openrouter_base_url"),
    )
    openrouter_http_referer: str = Field(
        default="http://127.0.0.1:8000",
        description="Заголовок HTTP-Referer для статистики OpenRouter.",
        validation_alias=AliasChoices(
            "OPENROUTER_HTTP_REFERER",
            "openrouter_http_referer",
        ),
    )
    openrouter_app_title: str = Field(
        default="AI Team Platform",
        description="Заголовок X-Title для OpenRouter.",
        validation_alias=AliasChoices("OPENROUTER_APP_TITLE", "openrouter_app_title"),
    )
    aggregate_mock_providers: bool = Field(
        default=True,
        description=(
            "Если True — агрегация без реальных HTTP к OpenRouter (локальная проверка без оплаты)."
        ),
        validation_alias=AliasChoices("AGGREGATE_MOCK", "aggregate_mock_providers"),
    )
    cache_ttl_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias=AliasChoices("CACHE_TTL_SECONDS", "cache_ttl_seconds"),
    )
    cache_max_entries: int = Field(
        default=512,
        ge=1,
        validation_alias=AliasChoices("CACHE_MAX_ENTRIES", "cache_max_entries"),
    )
    max_cost_per_request: float = Field(
        default=0.10,
        ge=0.0,
        validation_alias=AliasChoices("MAX_COST_PER_REQUEST", "max_cost_per_request"),
    )
    max_daily_cost: float = Field(
        default=5.00,
        ge=0.0,
        validation_alias=AliasChoices("MAX_DAILY_COST", "max_daily_cost"),
    )
    estimated_cost_per_route_usd: float = Field(
        default=0.05,
        ge=0.0,
        description="Оценка USD на один параллельный маршрут до вызова провайдеров.",
        validation_alias=AliasChoices(
            "ESTIMATED_COST_PER_ROUTE_USD",
            "estimated_cost_per_route_usd",
        ),
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./ai_platform.db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    cors_allowed_origins: str = Field(
        default="",
        description=(
            "Дополнительные origins для CORS через запятую "
            "(например продакшен frontend на Railway)."
        ),
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "cors_allowed_origins"),
    )
    upload_dir: Path = Field(
        default=Path("./uploads"),
        validation_alias=AliasChoices("UPLOAD_DIR", "upload_dir"),
    )
    max_file_size_mb: int = Field(
        default=10,
        ge=1,
        le=1024,
        validation_alias=AliasChoices("MAX_FILE_SIZE_MB", "max_file_size_mb"),
    )
    allowed_file_types: str = Field(
        default="pdf,doc,docx,txt,png,jpg,jpeg,gif,webp,fig,md,csv,json,xml,html,yml,yaml",
        description="CSV-список разрешённых расширений (без точки), регистр игнорируется.",
        validation_alias=AliasChoices("ALLOWED_FILE_TYPES", "allowed_file_types"),
    )
    chat_history_limit: int = Field(
        default=20,
        ge=1,
        le=200,
        validation_alias=AliasChoices("CHAT_HISTORY_LIMIT", "chat_history_limit"),
    )
    chat_default_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("CHAT_DEFAULT_TEMPERATURE", "chat_default_temperature"),
    )
    chat_response_timeout_ms: int = Field(
        default=60_000,
        ge=1000,
        validation_alias=AliasChoices("CHAT_RESPONSE_TIMEOUT_MS", "chat_response_timeout_ms"),
    )
    chat_risk_guard_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("CHAT_RISK_GUARD_ENABLED", "chat_risk_guard_enabled"),
    )
    chat_debate_timeout_ms: int = Field(
        default=120_000,
        ge=5_000,
        le=600_000,
        description=(
            "Базовый бюджет (мс) на один раунд при ~3 агентах; итоговый лимит треда масштабируется "
            "по числу раундов и агентов, см. discussion_orchestrator._create_debate_thread."
        ),
        validation_alias=AliasChoices("CHAT_DEBATE_TIMEOUT_MS", "chat_debate_timeout_ms"),
    )
    chat_debate_timeout_cap_ms: int = Field(
        default=900_000,
        ge=60_000,
        le=3_600_000,
        description="Верхняя граница wall-clock таймаута всей дискуссии (мс), включая синтез.",
        validation_alias=AliasChoices(
            "CHAT_DEBATE_TIMEOUT_CAP_MS",
            "chat_debate_timeout_cap_ms",
        ),
    )
    chat_debate_max_rounds: int = Field(
        default=5,
        ge=1,
        le=5,
        validation_alias=AliasChoices("CHAT_DEBATE_MAX_ROUNDS", "chat_debate_max_rounds"),
    )
    chat_file_text_max_chars: int = Field(
        default=48_000,
        ge=500,
        le=400_000,
        validation_alias=AliasChoices("CHAT_FILE_TEXT_MAX_CHARS", "chat_file_text_max_chars"),
    )
    chat_file_total_text_max_chars: int = Field(
        default=120_000,
        ge=2_000,
        le=1_500_000,
        validation_alias=AliasChoices(
            "CHAT_FILE_TOTAL_TEXT_MAX_CHARS",
            "chat_file_total_text_max_chars",
        ),
    )
    chat_file_max_images: int = Field(
        default=6,
        ge=0,
        le=20,
        validation_alias=AliasChoices("CHAT_FILE_MAX_IMAGES", "chat_file_max_images"),
    )
    chat_image_max_side_px: int = Field(
        default=1536,
        ge=256,
        le=4096,
        validation_alias=AliasChoices("CHAT_IMAGE_MAX_SIDE_PX", "chat_image_max_side_px"),
    )
    chat_image_max_bytes: int = Field(
        default=12_000_000,
        ge=100_000,
        le=25_000_000,
        validation_alias=AliasChoices("CHAT_IMAGE_MAX_BYTES", "chat_image_max_bytes"),
    )

    def allowed_file_extensions(self) -> set[str]:
        return {
            e.strip().lower().lstrip(".")
            for e in self.allowed_file_types.split(",")
            if e.strip()
        }

    def resolved_upload_dir(self) -> Path:
        p = self.upload_dir
        return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


def resolved_routes_yaml_path(settings: Settings) -> Path:
    """Абсолютный путь к routes.yaml относительно корня проекта, если путь относительный."""
    p = settings.routes_yaml_path
    rp = p if p.is_absolute() else _PROJECT_ROOT / p
    return rp.resolve()


def apply_openrouter_env(settings: Settings) -> None:
    """
    Диспетчер LLM читает шлюз через os.getenv — пробрасываем значения из Settings.
    Ключ не логируем и не возвращаем.
    """
    os.environ["OPENROUTER_BASE_URL"] = settings.openrouter_base_url.rstrip("/")
    os.environ["OPENROUTER_HTTP_REFERER"] = settings.openrouter_http_referer.strip()
    os.environ["OPENROUTER_APP_TITLE"] = settings.openrouter_app_title.strip()
    if settings.openrouter_api_key and settings.openrouter_api_key.strip():
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key.strip()


class RouteEntry(BaseModel):
    """Один маршрут провайдера из YAML."""

    route_id: str = Field(..., min_length=1)
    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    active: bool = True
    system_prompt: str = Field(default="")
    is_arbiter: bool = Field(
        default=False,
        description="Исключается из параллельного диспатча; используется SynthesizeStrategy.",
    )
    cache_override_ttl: int | None = Field(
        default=None,
        description="Ужесточает TTL кэша для запросов с этим маршрутом (секунды); null — только глобальный TTL.",
    )

    @field_validator("cache_override_ttl")
    @classmethod
    def cache_override_ttl_positive(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v <= 0:
            raise ValueError("cache_override_ttl must be positive when set")
        return v


class RoutesConfig(BaseModel):
    """Корень файла маршрутов."""

    version: int = Field(..., ge=1)
    routes: list[RouteEntry] = Field(default_factory=list)

    @field_validator("routes")
    @classmethod
    def unique_route_ids(cls, routes: list[RouteEntry]) -> list[RouteEntry]:
        ids = [r.route_id for r in routes]
        if len(ids) != len(set(ids)):
            raise ValueError("route_id values must be unique")
        return routes


def load_routes_config(path: Path) -> RoutesConfig:
    """
    Прочитать YAML и вернуть провалидированную модель.
    При ошибке парсинга/валидации — исключение (падение старта приложения).
    """
    raw_text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        raise ValueError("routes.yaml root must be a mapping")
    return RoutesConfig.model_validate(data)


def load_settings() -> Settings:
    """Загрузить настройки из окружения и `.env` в корне проекта."""
    return Settings()
