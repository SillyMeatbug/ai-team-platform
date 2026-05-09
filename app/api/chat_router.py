"""Чат проекта: история и отправка сообщений с оркестрацией ответа агентов."""

from __future__ import annotations

import json
import logging
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.loader import Settings
from app.core.database import get_db_session, get_session_factory
from app.core.storage import FileStorage
from app.core.logging_config import log_payload
from app.models.database import Agent, ChatMessage, Project, ProjectFile
from app.models.platform_schemas import (
    AgentOut,
    ChatAcceptedResponse,
    DebateLogOut,
    DebateRoundOut,
    DebateThreadOut,
    DebateTurnOut,
    ChatMessageOut,
    ProjectFileOut,
    ChatSendRequest,
)
from app.services.discussion_orchestrator import DiscussionOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _sse_event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chat_accepted_payload(prep: object) -> dict[str, object]:
    return {
        "user_message": ChatMessageOut.model_validate(prep.user_msg).model_dump(mode="json"),
        "pending_agent_ids": prep.pending_agent_ids,
        "selected_agents": prep.selected_agents,
        "response_order": prep.response_order,
        "is_discussion": prep.is_discussion,
        "debate_mode": prep.debate_mode,
        "debate_thread_id": prep.debate_thread_id,
        "router_reason": prep.router_reason,
        "router_flow": prep.router_flow,
        "data_freshness": prep.data_freshness,
        "source": prep.source,
    }


async def _ensure_project(session: AsyncSession, project_id: str) -> Project:
    proj = await session.get(Project, project_id)
    if proj is None or not proj.is_active:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _attach_agents(
    messages: list[ChatMessage], agents_by_id: dict[str, Agent], files_by_id: dict[str, ProjectFile]
) -> list[ChatMessageOut]:
    out: list[ChatMessageOut] = []
    for m in messages:
        view = ChatMessageOut.model_validate(m)
        if m.sender_type == "agent" and m.sender_id and m.sender_id in agents_by_id:
            from app.models.platform_schemas import AgentOut

            view = view.model_copy(
                update={"agent": AgentOut.model_validate(agents_by_id[m.sender_id])}
            )
        attachment_ids = list(m.attachment_file_ids or [])
        attachment_items = [
            files_by_id[fid] for fid in attachment_ids if fid in files_by_id
        ]
        if attachment_ids or attachment_items:
            view = view.model_copy(
                update={
                    "attachment_file_ids": attachment_ids,
                    "attachments": [ProjectFileOut.model_validate(f) for f in attachment_items],
                }
            )
        out.append(view)
    return out


@router.get(
    "/projects/{project_id}/chat",
    response_model=list[ChatMessageOut],
)
async def get_chat_history(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[ChatMessageOut]:
    await _ensure_project(session, project_id)
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.project_id == project_id)
            .order_by(ChatMessage.timestamp.asc())
            .limit(limit)
        )
    ).scalars().all()

    sender_ids = {m.sender_id for m in rows if m.sender_id}
    agents_by_id: dict[str, Agent] = {}
    if sender_ids:
        ag_rows = (
            await session.execute(select(Agent).where(Agent.id.in_(sender_ids)))
        ).scalars().all()
        agents_by_id = {a.id: a for a in ag_rows}

    file_ids = {
        fid
        for m in rows
        for fid in (m.attachment_file_ids or [])
        if isinstance(fid, str) and fid
    }
    files_by_id: dict[str, ProjectFile] = {}
    if file_ids:
        f_rows = (
            await session.execute(
                select(ProjectFile).where(
                    ProjectFile.project_id == project_id,
                    ProjectFile.id.in_(file_ids),
                )
            )
        ).scalars().all()
        files_by_id = {f.id: f for f in f_rows}

    return _attach_agents(list(rows), agents_by_id, files_by_id)


async def _run_chat_completion(
    *,
    project_id: str,
    user_message_id: str,
    user_content: str,
    target_agent_ids: list[str],
    is_discussion: bool,
    temperature: float,
    debate_mode: str,
    debate_thread_id: str | None,
    locale: str | None,
    off_chain_style: str | None,
    market_asset: str | None,
    market_timeframe: str | None,
    settings: Settings,
    http_client: httpx.AsyncClient | None,
    file_storage: FileStorage | None,
) -> None:
    factory = get_session_factory()
    async with factory() as bg_session:
        orch = DiscussionOrchestrator(
            session=bg_session,
            settings=settings,
            http_client=http_client,
            file_storage=file_storage,
        )
        try:
            await orch.complete_agent_replies(
                project_id=project_id,
                user_message_id=user_message_id,
                user_content=user_content,
                target_agent_ids=target_agent_ids,
                is_discussion=is_discussion,
                temperature=temperature,
                request_id=str(uuid.uuid4()),
                debate_mode=debate_mode,
                debate_thread_id=debate_thread_id,
                locale=locale,
                off_chain_style=off_chain_style,
                market_asset=market_asset,
                market_timeframe=market_timeframe,
            )
        except Exception:
            logger.exception(
                "chat_background_failed",
                extra={"log_payload": {"project_id": project_id, "user_message_id": user_message_id}},
            )


@router.post(
    "/projects/{project_id}/chat",
    response_model=ChatAcceptedResponse,
    status_code=202,
)
async def send_chat_message(
    project_id: str,
    payload: ChatSendRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> ChatAcceptedResponse:
    project = await _ensure_project(session, project_id)
    settings: Settings = request.app.state.settings
    http_client = getattr(request.app.state, "http_client", None)
    file_storage = getattr(request.app.state, "file_storage", None)

    orchestrator = DiscussionOrchestrator(
        session=session,
        settings=settings,
        http_client=http_client,
        file_storage=file_storage,
    )
    try:
        prep = await orchestrator.prepare_user_message(
            project_id=project.id,
            user_message=payload.content,
            explicit_agent_ids=payload.mentioned_agent_ids,
            force_discussion=payload.is_discussion,
            temperature=payload.temperature,
            debate_mode=payload.debate_mode,
            locale=payload.locale,
            file_ids=payload.file_ids,
            market_asset=payload.asset,
            market_timeframe=payload.timeframe,
        )
    except LookupError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "chat_send_failed",
            extra={"log_payload": {"project_id": project.id}},
        )
        raise HTTPException(status_code=500, detail="Internal chat error")

    background_tasks.add_task(
        _run_chat_completion,
        project_id=project.id,
        user_message_id=prep.user_msg.id,
        user_content=payload.content,
        target_agent_ids=prep.pending_agent_ids,
        is_discussion=prep.is_discussion,
        temperature=prep.temperature,
        debate_mode=prep.debate_mode,
        debate_thread_id=prep.debate_thread_id,
        locale=payload.locale,
        off_chain_style=prep.off_chain_style,
        market_asset=prep.market_asset,
        market_timeframe=prep.market_timeframe,
        settings=settings,
        http_client=http_client,
        file_storage=file_storage,
    )

    log_payload(
        logger,
        logging.INFO,
        "chat_accepted",
        project_id=project.id,
        user_message_id=prep.user_msg.id,
        pending=len(prep.pending_agent_ids),
        is_discussion=prep.is_discussion,
    )

    return ChatAcceptedResponse(
        user_message=ChatMessageOut.model_validate(prep.user_msg),
        pending_agent_ids=prep.pending_agent_ids,
        selected_agents=prep.selected_agents,
        response_order=prep.response_order,
        is_discussion=prep.is_discussion,
        debate_mode=prep.debate_mode,
        debate_thread_id=prep.debate_thread_id,
        router_reason=prep.router_reason,
        router_flow=prep.router_flow,
        data_freshness=prep.data_freshness,
        source=prep.source,
    )


@router.post("/projects/{project_id}/chat/stream", response_model=None)
async def send_chat_message_stream(
    project_id: str,
    payload: ChatSendRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> object:
    project = await _ensure_project(session, project_id)
    settings: Settings = request.app.state.settings
    http_client = getattr(request.app.state, "http_client", None)
    file_storage = getattr(request.app.state, "file_storage", None)
    orchestrator = DiscussionOrchestrator(
        session=session,
        settings=settings,
        http_client=http_client,
        file_storage=file_storage,
    )

    try:
        prep = await orchestrator.prepare_user_message(
            project_id=project.id,
            user_message=payload.content,
            explicit_agent_ids=payload.mentioned_agent_ids,
            force_discussion=payload.is_discussion,
            temperature=payload.temperature,
            debate_mode=payload.debate_mode,
            locale=payload.locale,
            file_ids=payload.file_ids,
            market_asset=payload.asset,
            market_timeframe=payload.timeframe,
        )
    except LookupError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(
            "chat_stream_prepare_failed",
            extra={"log_payload": {"project_id": project.id}},
        )
        raise HTTPException(status_code=500, detail="Internal chat stream error")

    streaming_enabled = prep.debate_mode == "off" and len(prep.pending_agent_ids) <= 2
    if not streaming_enabled:
        background_tasks.add_task(
            _run_chat_completion,
            project_id=project.id,
            user_message_id=prep.user_msg.id,
            user_content=payload.content,
            target_agent_ids=prep.pending_agent_ids,
            is_discussion=prep.is_discussion,
            temperature=prep.temperature,
            debate_mode=prep.debate_mode,
            debate_thread_id=prep.debate_thread_id,
            locale=payload.locale,
            off_chain_style=prep.off_chain_style,
            market_asset=prep.market_asset,
            market_timeframe=prep.market_timeframe,
            settings=settings,
            http_client=http_client,
            file_storage=file_storage,
        )

        async def disabled_event_gen():
            yield _sse_event(
                {
                    "type": "accepted",
                    **_chat_accepted_payload(prep),
                    "streaming_enabled": False,
                }
            )
            yield _sse_event(
                {
                    "type": "streaming_disabled",
                    "reason": "debate_or_many_agents",
                    "streaming_enabled": False,
                }
            )

        return StreamingResponse(
            disabled_event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def event_gen():
        try:
            yield _sse_event(
                {
                    "type": "accepted",
                    **_chat_accepted_payload(prep),
                    "streaming_enabled": True,
                }
            )
            async for event in orchestrator.stream_chat_replies(
                project_id=project.id,
                user_message_id=prep.user_msg.id,
                user_content=payload.content,
                target_agent_ids=prep.pending_agent_ids,
                is_discussion=prep.is_discussion,
                temperature=prep.temperature,
                request_id=str(uuid.uuid4()),
                debate_mode=prep.debate_mode,
                debate_thread_id=prep.debate_thread_id,
                locale=payload.locale,
                market_asset=prep.market_asset,
                market_timeframe=prep.market_timeframe,
            ):
                yield _sse_event(event)
        except Exception as e:
            logger.exception(
                "chat_stream_failed",
                extra={"log_payload": {"project_id": project.id}},
            )
            yield _sse_event({"type": "error", "detail": f"stream failed: {type(e).__name__}"})
            yield _sse_event({"type": "complete"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/projects/{project_id}/debates/{thread_id}",
    response_model=DebateThreadOut,
)
async def get_debate_thread_status(
    project_id: str,
    thread_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DebateThreadOut:
    await _ensure_project(session, project_id)
    settings: Settings = request.app.state.settings
    http_client = getattr(request.app.state, "http_client", None)
    file_storage = getattr(request.app.state, "file_storage", None)
    orch = DiscussionOrchestrator(
        session=session, settings=settings, http_client=http_client, file_storage=file_storage
    )
    try:
        thread = await orch.get_debate_thread(project_id=project_id, thread_id=thread_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DebateThreadOut.model_validate(thread)


@router.get(
    "/projects/{project_id}/debates/{thread_id}/log",
    response_model=DebateLogOut,
)
async def get_debate_log(
    project_id: str,
    thread_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DebateLogOut:
    await _ensure_project(session, project_id)
    settings: Settings = request.app.state.settings
    http_client = getattr(request.app.state, "http_client", None)
    file_storage = getattr(request.app.state, "file_storage", None)
    orch = DiscussionOrchestrator(
        session=session, settings=settings, http_client=http_client, file_storage=file_storage
    )
    try:
        thread, rounds, turns, agents = await orch.get_debate_log(
            project_id=project_id,
            thread_id=thread_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DebateLogOut(
        thread=DebateThreadOut.model_validate(thread),
        rounds=[DebateRoundOut.model_validate(r) for r in rounds],
        turns=[
            DebateTurnOut.model_validate(t).model_copy(
                update={
                    "agent": AgentOut.model_validate(agents[t.agent_id]) if t.agent_id in agents else None
                }
            )
            for t in turns
        ],
    )


@router.post(
    "/projects/{project_id}/debates/{thread_id}/cancel",
    response_model=DebateThreadOut,
)
async def cancel_debate_thread(
    project_id: str,
    thread_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> DebateThreadOut:
    await _ensure_project(session, project_id)
    settings: Settings = request.app.state.settings
    http_client = getattr(request.app.state, "http_client", None)
    file_storage = getattr(request.app.state, "file_storage", None)
    orch = DiscussionOrchestrator(
        session=session, settings=settings, http_client=http_client, file_storage=file_storage
    )
    try:
        thread = await orch.cancel_debate_thread(project_id=project_id, thread_id=thread_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DebateThreadOut.model_validate(thread)
