"""ORM-модели платформы (SQLAlchemy 2.0).

UUID хранится как строка (UUID4 hex+dashes, длина 36) — совместимо с SQLite.
Все datetime — UTC (timezone-aware).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Корневой класс ORM."""


class Agent(Base):
    """Предустановленный агент-роль (общая библиотека)."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#3b82f6")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    project_links: Mapped[list["ProjectAgent"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    library_files: Mapped[list["AgentLibraryFile"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentLibraryFile(Base):
    """Файлы по умолчанию для агента (рулбуки, референсы) — подмешиваются в промпт при его ответах."""

    __tablename__ = "agent_library_files"
    __table_args__ = (Index("ix_agent_library_files_agent", "agent_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")

    agent: Mapped["Agent"] = relationship(back_populates="library_files")


class Project(Base):
    """Проект — пространство коллаборации с набором агентов."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_crypto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    agent_links: Mapped[list["ProjectAgent"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    files: Mapped[list["ProjectFile"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    debate_threads: Mapped[list["DebateThread"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    results: Mapped[list["GeneratedResult"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    paper_trades: Mapped[list["PaperTrade"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectAgent(Base):
    """Связь проект ↔ агент."""

    __tablename__ = "project_agents"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", name="uq_project_agent"),
        Index("ix_project_agents_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    project: Mapped[Project] = relationship(back_populates="agent_links")
    agent: Mapped[Agent] = relationship(back_populates="project_links")


class ProjectFile(Base):
    """Файл проекта (метаданные; контент — на диске UPLOAD_DIR)."""

    __tablename__ = "project_files"
    __table_args__ = (Index("ix_project_files_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="brief")

    project: Mapped[Project] = relationship(back_populates="files")


class ChatMessage(Base):
    """Сообщение в чате проекта (от пользователя или агента)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_project_ts", "project_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    is_discussion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_file_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    project: Mapped[Project] = relationship(back_populates="messages")


class DebateThread(Base):
    """Внутренний тред многораундовой дискуссии агентов для одного пользовательского сообщения."""

    __tablename__ = "debate_threads"
    __table_args__ = (
        Index("ix_debate_threads_project_started", "project_id", "started_at"),
        Index("ix_debate_threads_user_message", "user_message_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="off")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    disagreements: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project: Mapped[Project] = relationship(back_populates="debate_threads")
    rounds: Mapped[list["DebateRound"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class DebateRound(Base):
    """Один раунд обсуждения внутри DebateThread."""

    __tablename__ = "debate_rounds"
    __table_args__ = (
        Index("ix_debate_rounds_thread_round", "thread_id", "round_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("debate_threads.id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    round_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    thread: Mapped["DebateThread"] = relationship(back_populates="rounds")
    turns: Mapped[list["DebateTurn"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class DebateTurn(Base):
    """Реплика конкретного агента в определённом раунде дискуссии."""

    __tablename__ = "debate_turns"
    __table_args__ = (
        Index("ix_debate_turns_thread_round", "thread_id", "round_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("debate_threads.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("debate_rounds.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    turn_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    round: Mapped[DebateRound] = relationship(back_populates="turns")


class GeneratedResult(Base):
    """Сгенерированный артефакт от агента в проекте."""

    __tablename__ = "generated_results"
    __table_args__ = (Index("ix_generated_results_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    project: Mapped[Project] = relationship(back_populates="results")


class PaperTrade(Base):
    """Бумажная сделка по сигналу агента (без реального исполнения)."""

    __tablename__ = "paper_trades"
    __table_args__ = (
        Index("ix_paper_trades_project_opened", "project_id", "opened_at"),
        Index("ix_paper_trades_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    asset: Mapped[str] = mapped_column(String(40), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    signal: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    entry_price: Mapped[float] = mapped_column(nullable=False, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(nullable=True)
    take_profit: Mapped[float | None] = mapped_column(nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signal_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    project: Mapped[Project] = relationship(back_populates="paper_trades")
