"""Библиотека файлов по умолчанию для агента (рулбуки и т.п.)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.logging_config import log_payload
from app.core.storage import (
    FileStorage,
    FileTooLargeError,
    FileTypeNotAllowedError,
    StorageError,
)
from app.models.database import Agent, AgentLibraryFile
from app.models.platform_schemas import AgentLibraryFileOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-library"])

_AGENT_LIBRARY_CATEGORIES = {"reference", "rules", "brief", "other"}


async def _ensure_agent(session: AsyncSession, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _get_storage(request: Request) -> FileStorage:
    storage = getattr(request.app.state, "file_storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="File storage not initialized")
    return storage


async def _stream_chunks(upload: UploadFile, chunk_size: int = 64 * 1024):
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        yield chunk


@router.post(
    "/agents/{agent_id}/library",
    response_model=AgentLibraryFileOut,
    status_code=201,
)
async def upload_agent_library_file(
    agent_id: str,
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("reference"),
    session: AsyncSession = Depends(get_db_session),
) -> AgentLibraryFileOut:
    agent = await _ensure_agent(session, agent_id)
    if category not in _AGENT_LIBRARY_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")

    storage = _get_storage(request)
    try:
        stored = await storage.save_agent_library(
            agent_id=agent.id,
            original_filename=file.filename or "file",
            content_type=file.content_type or "application/octet-stream",
            data_iter=_stream_chunks(file),
        )
    except FileTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileTypeNotAllowedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await file.close()

    record = AgentLibraryFile(
        id=stored.file_id,
        agent_id=agent.id,
        filename=stored.filename,
        filepath=stored.filepath,
        file_size=stored.file_size,
        content_type=stored.content_type,
        category=category,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    log_payload(
        logger,
        logging.INFO,
        "agent_library_uploaded",
        agent_id=agent.id,
        file_id=record.id,
        size=record.file_size,
        category=category,
    )
    return AgentLibraryFileOut.model_validate(record)


@router.get(
    "/agents/{agent_id}/library",
    response_model=list[AgentLibraryFileOut],
)
async def list_agent_library_files(
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentLibraryFileOut]:
    await _ensure_agent(session, agent_id)
    rows = (
        await session.execute(
            select(AgentLibraryFile)
            .where(AgentLibraryFile.agent_id == agent_id)
            .order_by(AgentLibraryFile.uploaded_at.desc())
        )
    ).scalars().all()
    return [AgentLibraryFileOut.model_validate(r) for r in rows]


@router.delete(
    "/agents/{agent_id}/library/{file_id}",
    status_code=204,
)
async def delete_agent_library_file(
    agent_id: str,
    file_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await _ensure_agent(session, agent_id)
    record = await session.get(AgentLibraryFile, file_id)
    if record is None or record.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="File not found")

    storage = _get_storage(request)
    storage.delete_path(record.filepath)

    await session.delete(record)
    await session.commit()
    log_payload(
        logger,
        logging.INFO,
        "agent_library_deleted",
        agent_id=agent_id,
        file_id=file_id,
    )


@router.get("/agents/{agent_id}/library/{file_id}/download")
async def download_agent_library_file(
    agent_id: str,
    file_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    await _ensure_agent(session, agent_id)
    record = await session.get(AgentLibraryFile, file_id)
    if record is None or record.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="File not found")

    storage = _get_storage(request)
    try:
        path = storage.open_for_read(record.filepath)
    except StorageError:
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        path=str(path),
        media_type=record.content_type,
        filename=record.filename,
    )
