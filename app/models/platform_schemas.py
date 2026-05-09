"""Pydantic v2 схемы платформы (проекты/агенты/файлы/чат/результаты).

Не пересекается с app/models/schemas.py — там контракты `/v1/aggregate`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SenderType = Literal["user", "agent"]
FileCategory = Literal["brief", "mockup", "reference", "generated"]
ResultCategory = Literal["architecture", "design", "code", "content", "other"]
DebateMode = Literal["auto", "off", "fast", "standard", "deep"]
PaperTradeSignal = Literal["long", "short", "neutral"]
PaperTradeStatus = Literal["open", "closed", "stopped", "expired"]
DebateStatus = Literal[
    "running",
    "agents_discussing",
    "synthesizing",
    "cancelled",
    "completed",
    "timed_out",
    "failed",
]


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    model: str
    role: str
    system_prompt: str
    color: str
    is_active: bool


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_crypto_enabled: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    is_crypto_enabled: bool | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    is_active: bool
    is_crypto_enabled: bool = False
    file_count: int = 0
    message_count: int = 0


class ProjectAgentAdd(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)


class ProjectAgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    agent_id: str
    joined_at: datetime
    is_active: bool
    agent: AgentOut


class ProjectFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    filename: str
    file_size: int
    content_type: str
    uploaded_at: datetime
    category: str


class AgentLibraryFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    filename: str
    file_size: int
    content_type: str
    uploaded_at: datetime
    category: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    sender_type: SenderType
    sender_id: str | None
    content: str
    timestamp: datetime
    is_discussion: bool
    parent_message_id: str | None
    error: str | None = None
    attachment_file_ids: list[str] | None = None
    attachments: list[ProjectFileOut] | None = None
    agent: AgentOut | None = None


class ChatSendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    is_discussion: bool | None = Field(
        default=None,
        description=(
            "Принудительно групповой режим. Если null — определяется автоматически: "
            "true при двух и более @упоминаниях."
        ),
    )
    mentioned_agent_ids: list[str] | None = Field(
        default=None,
        description="Явный список agent.id для адресации; имеет приоритет над @упоминаниями в тексте.",
    )
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    debate_mode: DebateMode | None = Field(
        default=None,
        description="Режим: auto (Router выбирает), off/fast/standard/deep.",
    )
    locale: Literal["en", "ru"] | None = Field(
        default=None,
        description="Локаль пользователя для человекочитаемых системных сообщений.",
    )
    file_ids: list[str] | None = Field(
        default=None,
        description="Опциональные project_files.id, привязываемые к сообщению пользователя.",
    )
    asset: str | None = Field(
        default=None,
        description="Опциональный актив для LIVE DATA CONTEXT (например BTC/USDT).",
    )
    timeframe: str | None = Field(
        default=None,
        description="Опциональный таймфрейм для LIVE DATA CONTEXT (например 4H).",
    )


class ChatSendResponse(BaseModel):
    user_message: ChatMessageOut
    agent_responses: list[ChatMessageOut]
    is_discussion: bool


class ChatAcceptedResponse(BaseModel):
    """Ответ сразу после сохранения сообщения пользователя; ответы агентов — через polling GET /chat."""

    user_message: ChatMessageOut
    pending_agent_ids: list[str]
    selected_agents: list[str] | None = None
    response_order: list[str] | None = None
    is_discussion: bool
    debate_mode: DebateMode = "off"
    debate_thread_id: str | None = None
    router_reason: str | None = Field(
        default=None,
        description="Обоснование Router при debate_mode=auto (для UI).",
    )
    router_flow: Literal["off", "sequential", "debate"] | None = Field(
        default=None,
        description="Выбранный Router поток: off (параллельно), sequential, debate.",
    )
    data_freshness: Literal["live", "cached", "unavailable"] | None = Field(
        default=None,
        description="Свежесть рыночных данных для крипто-контекста.",
    )
    source: str | None = Field(
        default=None,
        description="Источник рыночных данных (например binance).",
    )


class DebateRoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    thread_id: str
    round_number: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    round_summary: str | None


class DebateTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    thread_id: str
    round_id: str
    agent_id: str
    turn_order: int
    content: str
    error: str | None
    created_at: datetime
    agent: AgentOut | None = None


class DebateThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    user_message_id: str
    mode: DebateMode
    status: DebateStatus
    total_rounds: int
    current_round: int
    started_at: datetime
    finished_at: datetime | None
    timeout_at: datetime | None
    final_summary: str | None
    confidence: str | None
    disagreements: str | None
    final_message_id: str | None
    meta: dict | None = None


class DebateLogOut(BaseModel):
    thread: DebateThreadOut
    rounds: list[DebateRoundOut]
    turns: list[DebateTurnOut]


class GeneratedResultCreate(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    category: ResultCategory
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)


class GeneratedResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    agent_id: str
    category: str
    title: str
    content: str
    created_at: datetime


class PaperTradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    agent_id: str
    message_id: str | None = None
    asset: str
    timeframe: str
    signal: PaperTradeSignal
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    confidence: float
    rationale: str
    signal_timestamp: datetime
    opened_at: datetime
    closed_at: datetime | None
    exit_price: float | None
    pnl_pct: float | None
    status: PaperTradeStatus


class PaperTradeCreate(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    message_id: str | None = Field(default=None, min_length=1, max_length=64)
    asset: str = Field(..., min_length=3, max_length=40)
    timeframe: str = Field(..., min_length=1, max_length=16)
    signal: PaperTradeSignal
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=100.0)
    rationale: str = Field(default="", max_length=8000)
    signal_timestamp: datetime


class PaperTradeCloseRequest(BaseModel):
    exit_price: float = Field(..., gt=0.0)
