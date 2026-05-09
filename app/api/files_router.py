"""Файлы проектов: загрузка, список, удаление, скачивание."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

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
from app.models.database import Project, ProjectFile
from app.models.platform_schemas import ProjectFileOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["files"])


_ALLOWED_CATEGORIES = {"brief", "mockup", "reference", "generated"}
_EXT_BY_CONTENT_TYPE = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "application/json": "json",
    "text/csv": "csv",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


async def _ensure_project(session: AsyncSession, project_id: str) -> Project:
    proj = await session.get(Project, project_id)
    if proj is None or not proj.is_active:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _get_storage(request: Request) -> FileStorage:
    storage = getattr(request.app.state, "file_storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="File storage not initialized")
    return storage


def _normalize_upload_filename(filename: str | None, content_type: str | None) -> str:
    raw = (filename or "").strip()
    ct = (content_type or "").strip().lower()
    inferred_ext = _EXT_BY_CONTENT_TYPE.get(ct)

    if not raw:
        return f"file.{inferred_ext}" if inferred_ext else "file"

    name = Path(raw).name.strip() or "file"
    suffix = Path(name).suffix.lower().lstrip(".")

    # Частый кейс: браузер/источник прислал просто "pdf"/"docx" без базового имени.
    if inferred_ext and name.lower() == inferred_ext and not suffix:
        return f"file.{inferred_ext}"

    if inferred_ext and not suffix:
        return f"{name}.{inferred_ext}"

    return name


async def _stream_chunks(upload: UploadFile, chunk_size: int = 64 * 1024):
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        yield chunk


@router.post(
    "/projects/{project_id}/files",
    response_model=ProjectFileOut,
    status_code=201,
)
async def upload_project_file(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("brief"),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectFileOut:
    project = await _ensure_project(session, project_id)
    if category not in _ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail="invalid category")

    storage = _get_storage(request)
    original_filename = _normalize_upload_filename(file.filename, file.content_type)

    try:
        stored = await storage.save(
            project_id=project.id,
            original_filename=original_filename,
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

    record = ProjectFile(
        id=stored.file_id,
        project_id=project.id,
        filename=stored.filename,
        filepath=stored.filepath,
        file_size=stored.file_size,
        content_type=stored.content_type,
        category=category,
    )
    session.add(record)
    project.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(record)

    log_payload(
        logger,
        logging.INFO,
        "project_file_uploaded",
        project_id=project.id,
        file_id=record.id,
        size=record.file_size,
        category=category,
    )
    return ProjectFileOut.model_validate(record)


@router.get(
    "/projects/{project_id}/files",
    response_model=list[ProjectFileOut],
)
async def list_project_files(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[ProjectFileOut]:
    await _ensure_project(session, project_id)
    rows = (
        await session.execute(
            select(ProjectFile)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.uploaded_at.desc())
        )
    ).scalars().all()
    return [ProjectFileOut.model_validate(r) for r in rows]


@router.delete(
    "/projects/{project_id}/files/{file_id}",
    status_code=204,
)
async def delete_project_file(
    project_id: str,
    file_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    project = await _ensure_project(session, project_id)
    record = await session.get(ProjectFile, file_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="File not found")

    storage = _get_storage(request)
    storage.delete_path(record.filepath)

    await session.delete(record)
    project.updated_at = datetime.now(UTC)
    await session.commit()
    log_payload(
        logger,
        logging.INFO,
        "project_file_deleted",
        project_id=project_id,
        file_id=file_id,
    )


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    record = await session.get(ProjectFile, file_id)
    if record is None:
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
