"""CRUD проектов, состав агентов проекта, результаты работы агентов."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.seed import seed_agents
from app.core.logging_config import log_payload
from app.models.database import (
    Agent,
    ChatMessage,
    GeneratedResult,
    PaperTrade,
    Project,
    ProjectAgent,
    ProjectFile,
)
from app.models.platform_schemas import (
    AgentOut,
    GeneratedResultCreate,
    GeneratedResultOut,
    PaperTradeCloseRequest,
    PaperTradeCreate,
    ProjectAgentAdd,
    ProjectAgentOut,
    ProjectCreate,
    ProjectOut,
    PaperTradeOut,
    ProjectUpdate,
)
from app.services.paper_trading import reconcile_open_trades

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


async def _get_project_or_404(session: AsyncSession, project_id: str) -> Project:
    proj = await session.get(Project, project_id)
    if proj is None or not proj.is_active:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


async def _project_counts(
    session: AsyncSession, project_id: str
) -> tuple[int, int]:
    files_count = (
        await session.execute(
            select(func.count(ProjectFile.id)).where(ProjectFile.project_id == project_id)
        )
    ).scalar_one()
    messages_count = (
        await session.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.project_id == project_id)
        )
    ).scalar_one()
    return int(files_count or 0), int(messages_count or 0)


@router.get("/agents", response_model=list[AgentOut])
async def list_available_agents(
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentOut]:
    rows = (
        await session.execute(
            select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.name.asc())
        )
    ).scalars().all()
    if not rows:
        await seed_agents()
        rows = (
            await session.execute(
                select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.name.asc())
            )
        ).scalars().all()
    return [AgentOut.model_validate(a) for a in rows]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectOut:
    project = Project(
        name=payload.name,
        description=payload.description,
        is_crypto_enabled=payload.is_crypto_enabled,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    log_payload(
        logger, logging.INFO, "project_created", project_id=project.id
    )
    return ProjectOut.model_validate(
        project,
    ).model_copy(update={"file_count": 0, "message_count": 0})


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectOut]:
    rows = (
        await session.execute(
            select(Project)
            .where(Project.is_active.is_(True))
            .order_by(Project.updated_at.desc())
        )
    ).scalars().all()
    project_ids = [p.id for p in rows]
    file_counts_rows = (
        await session.execute(
            select(ProjectFile.project_id, func.count(ProjectFile.id))
            .where(ProjectFile.project_id.in_(project_ids))
            .group_by(ProjectFile.project_id)
        )
    ).all() if project_ids else []
    msg_counts_rows = (
        await session.execute(
            select(ChatMessage.project_id, func.count(ChatMessage.id))
            .where(ChatMessage.project_id.in_(project_ids))
            .group_by(ChatMessage.project_id)
        )
    ).all() if project_ids else []
    file_counts = {pid: int(cnt) for pid, cnt in file_counts_rows}
    msg_counts = {pid: int(cnt) for pid, cnt in msg_counts_rows}

    out: list[ProjectOut] = []
    for r in rows:
        out.append(
            ProjectOut.model_validate(r).model_copy(
                update={
                    "file_count": file_counts.get(r.id, 0),
                    "message_count": msg_counts.get(r.id, 0),
                }
            )
        )
    return out


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectOut:
    proj = await _get_project_or_404(session, project_id)
    file_count, message_count = await _project_counts(session, project_id)
    return ProjectOut.model_validate(proj).model_copy(
        update={"file_count": file_count, "message_count": message_count}
    )


@router.put("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectOut:
    proj = await _get_project_or_404(session, project_id)
    if payload.name is not None:
        proj.name = payload.name
    if payload.description is not None:
        proj.description = payload.description
    if payload.is_active is not None:
        proj.is_active = payload.is_active
    if payload.is_crypto_enabled is not None:
        proj.is_crypto_enabled = payload.is_crypto_enabled
    proj.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(proj)
    file_count, message_count = await _project_counts(session, project_id)
    return ProjectOut.model_validate(proj).model_copy(
        update={"file_count": file_count, "message_count": message_count}
    )


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    proj = await _get_project_or_404(session, project_id)
    proj.is_active = False
    proj.updated_at = datetime.now(UTC)
    await session.commit()
    log_payload(logger, logging.INFO, "project_soft_deleted", project_id=proj.id)


@router.get(
    "/projects/{project_id}/agents",
    response_model=list[ProjectAgentOut],
)
async def list_project_agents(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectAgentOut]:
    await _get_project_or_404(session, project_id)
    rows = (
        await session.execute(
            select(ProjectAgent, Agent)
            .join(Agent, Agent.id == ProjectAgent.agent_id)
            .where(
                ProjectAgent.project_id == project_id,
                ProjectAgent.is_active.is_(True),
            )
            .order_by(ProjectAgent.joined_at.asc())
        )
    ).all()

    out: list[ProjectAgentOut] = []
    for link, agent in rows:
        out.append(
            ProjectAgentOut(
                project_id=link.project_id,
                agent_id=link.agent_id,
                joined_at=link.joined_at,
                is_active=link.is_active,
                agent=AgentOut.model_validate(agent),
            )
        )
    return out


@router.post(
    "/projects/{project_id}/agents",
    response_model=ProjectAgentOut,
    status_code=201,
)
async def add_project_agent(
    project_id: str,
    payload: ProjectAgentAdd,
    session: AsyncSession = Depends(get_db_session),
) -> ProjectAgentOut:
    project = await _get_project_or_404(session, project_id)
    agent = await session.get(Agent, payload.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = (
        await session.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="Agent already in project")
        existing.is_active = True
        link = existing
    else:
        link = ProjectAgent(project_id=project.id, agent_id=agent.id, is_active=True)
        session.add(link)

    await session.commit()
    await session.refresh(link)
    log_payload(
        logger,
        logging.INFO,
        "project_agent_added",
        project_id=project.id,
        agent_id=agent.id,
    )
    return ProjectAgentOut(
        project_id=link.project_id,
        agent_id=link.agent_id,
        joined_at=link.joined_at,
        is_active=link.is_active,
        agent=AgentOut.model_validate(agent),
    )


@router.delete(
    "/projects/{project_id}/agents/{agent_id}",
    status_code=204,
)
async def remove_project_agent(
    project_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    project = await _get_project_or_404(session, project_id)
    link = (
        await session.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    if link is None or not link.is_active:
        raise HTTPException(status_code=404, detail="Agent not in project")
    link.is_active = False
    await session.commit()
    log_payload(
        logger,
        logging.INFO,
        "project_agent_removed",
        project_id=project.id,
        agent_id=agent_id,
    )


@router.get(
    "/projects/{project_id}/results",
    response_model=list[GeneratedResultOut],
)
async def list_project_results(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[GeneratedResultOut]:
    await _get_project_or_404(session, project_id)
    rows = (
        await session.execute(
            select(GeneratedResult)
            .where(GeneratedResult.project_id == project_id)
            .order_by(GeneratedResult.created_at.desc())
        )
    ).scalars().all()
    return [GeneratedResultOut.model_validate(r) for r in rows]


@router.post(
    "/projects/{project_id}/results",
    response_model=GeneratedResultOut,
    status_code=201,
)
async def create_project_result(
    project_id: str,
    payload: GeneratedResultCreate,
    session: AsyncSession = Depends(get_db_session),
) -> GeneratedResultOut:
    project = await _get_project_or_404(session, project_id)
    agent = await session.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    record = GeneratedResult(
        project_id=project.id,
        agent_id=agent.id,
        category=payload.category,
        title=payload.title,
        content=payload.content,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    log_payload(
        logger,
        logging.INFO,
        "project_result_saved",
        project_id=project.id,
        agent_id=agent.id,
        result_id=record.id,
    )
    return GeneratedResultOut.model_validate(record)


@router.get(
    "/projects/{project_id}/paper-trades",
    response_model=list[PaperTradeOut],
)
async def list_project_paper_trades(
    project_id: str,
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[PaperTradeOut]:
    await _get_project_or_404(session, project_id)
    stmt = (
        select(PaperTrade)
        .where(PaperTrade.project_id == project_id)
        .order_by(PaperTrade.opened_at.desc())
    )
    if status:
        stmt = stmt.where(PaperTrade.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [PaperTradeOut.model_validate(r) for r in rows]


@router.post(
    "/projects/{project_id}/paper-trades",
    response_model=PaperTradeOut,
    status_code=201,
)
async def create_project_paper_trade(
    project_id: str,
    payload: PaperTradeCreate,
    session: AsyncSession = Depends(get_db_session),
) -> PaperTradeOut:
    project = await _get_project_or_404(session, project_id)
    agent = await session.get(Agent, payload.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if payload.message_id:
        msg = await session.get(ChatMessage, payload.message_id)
        if msg is None or msg.project_id != project.id:
            raise HTTPException(status_code=404, detail="Message not found in this project")
    trade = PaperTrade(
        project_id=project.id,
        agent_id=payload.agent_id,
        message_id=payload.message_id,
        asset=payload.asset.upper(),
        timeframe=payload.timeframe.upper(),
        signal=payload.signal,
        entry_price=payload.entry_price,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        confidence=payload.confidence,
        rationale=payload.rationale,
        signal_timestamp=payload.signal_timestamp,
        opened_at=datetime.now(UTC),
        status="open",
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade)
    return PaperTradeOut.model_validate(trade)


@router.post(
    "/projects/{project_id}/paper-trades/{trade_id}/close",
    response_model=PaperTradeOut,
)
async def close_project_paper_trade(
    project_id: str,
    trade_id: str,
    payload: PaperTradeCloseRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PaperTradeOut:
    await _get_project_or_404(session, project_id)
    trade = await session.get(PaperTrade, trade_id)
    if trade is None or trade.project_id != project_id:
        raise HTTPException(status_code=404, detail="Paper trade not found")
    trade.exit_price = payload.exit_price
    trade.closed_at = datetime.now(UTC)
    if trade.entry_price > 0:
        if trade.signal == "short":
            trade.pnl_pct = ((trade.entry_price - payload.exit_price) / trade.entry_price) * 100.0
        else:
            trade.pnl_pct = ((payload.exit_price - trade.entry_price) / trade.entry_price) * 100.0
    else:
        trade.pnl_pct = 0.0
    trade.status = "closed"
    await session.commit()
    await session.refresh(trade)
    return PaperTradeOut.model_validate(trade)


@router.post(
    "/projects/{project_id}/paper-trades/reconcile",
    response_model=dict[str, int],
)
async def reconcile_project_paper_trades(
    project_id: str,
    asset: str | None = None,
    timeframe: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    await _get_project_or_404(session, project_id)
    updated = await reconcile_open_trades(
        session,
        project_id=project_id,
        asset=asset,
        timeframe=timeframe,
    )
    return {"updated": updated}
