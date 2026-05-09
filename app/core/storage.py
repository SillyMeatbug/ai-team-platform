"""Файловое хранилище на локальном диске.

Проекты: {UPLOAD_DIR}/{project_id}/{file_id}_{safe_name}.
Библиотека агента: {UPLOAD_DIR}/agent_library/{agent_id}/{file_id}_{safe_name}.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import aiofiles


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    base = Path(name).name.strip() or "file"
    p = Path(base)
    ext = p.suffix.lower()
    stem = p.stem
    cleaned_stem = _SAFE_CHARS.sub("_", stem).strip("._")
    if not cleaned_stem:
        cleaned_stem = "file"
    if ext:
        ext_clean = _SAFE_CHARS.sub("", ext).lower()
        if not ext_clean.startswith("."):
            ext_clean = f".{ext_clean}"
        if ext_clean == ".":
            ext_clean = ""
    else:
        ext_clean = ""
    return f"{cleaned_stem}{ext_clean}"[:200]


class StorageError(Exception):
    """Базовая ошибка файлового слоя."""


class FileTooLargeError(StorageError):
    pass


class FileTypeNotAllowedError(StorageError):
    pass


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    filename: str
    filepath: str
    file_size: int
    content_type: str


class FileStorage:
    """Дисковое хранилище с лимитом размера и whitelist расширений."""

    __slots__ = ("_root", "_max_size", "_allowed")

    def __init__(
        self,
        *,
        root: Path,
        max_file_size_bytes: int,
        allowed_extensions: set[str],
    ) -> None:
        self._root = root
        self._max_size = max_file_size_bytes
        self._allowed = {ext.lower().lstrip(".") for ext in allowed_extensions}

    @property
    def root(self) -> Path:
        return self._root

    def _project_dir(self, project_id: str) -> Path:
        d = self._root / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _agent_library_dir(self, agent_id: str) -> Path:
        d = self._root / "agent_library" / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _validate(self, filename: str, size_hint: int | None) -> None:
        ext = Path(filename).suffix.lower().lstrip(".")
        if not ext or ext not in self._allowed:
            raise FileTypeNotAllowedError(
                f"file type '{ext or 'unknown'}' is not allowed"
            )
        if size_hint is not None and size_hint > self._max_size:
            raise FileTooLargeError("file exceeds max allowed size")

    async def save(
        self,
        *,
        project_id: str,
        original_filename: str,
        content_type: str,
        data_iter,
        size_hint: int | None = None,
    ) -> StoredFile:
        """Сохранить файл из итератора чанков. Контролируем размер на лету."""
        self._validate(original_filename, size_hint)
        file_id = str(uuid.uuid4())
        safe_name = _sanitize_filename(original_filename)
        target = self._project_dir(project_id) / f"{file_id}_{safe_name}"

        written = 0
        try:
            async with aiofiles.open(target, "wb") as f:
                async for chunk in data_iter:
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self._max_size:
                        await f.close()
                        target.unlink(missing_ok=True)
                        raise FileTooLargeError("file exceeds max allowed size")
                    await f.write(chunk)
        except StorageError:
            raise
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return StoredFile(
            file_id=file_id,
            filename=safe_name,
            filepath=str(target),
            file_size=written,
            content_type=content_type or "application/octet-stream",
        )

    async def save_agent_library(
        self,
        *,
        agent_id: str,
        original_filename: str,
        content_type: str,
        data_iter,
        size_hint: int | None = None,
    ) -> StoredFile:
        """Сохранить файл библиотеки агента (рулбук по умолчанию и т.п.)."""
        self._validate(original_filename, size_hint)
        file_id = str(uuid.uuid4())
        safe_name = _sanitize_filename(original_filename)
        target = self._agent_library_dir(agent_id) / f"{file_id}_{safe_name}"

        written = 0
        try:
            async with aiofiles.open(target, "wb") as f:
                async for chunk in data_iter:
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self._max_size:
                        await f.close()
                        target.unlink(missing_ok=True)
                        raise FileTooLargeError("file exceeds max allowed size")
                    await f.write(chunk)
        except StorageError:
            raise
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return StoredFile(
            file_id=file_id,
            filename=safe_name,
            filepath=str(target),
            file_size=written,
            content_type=content_type or "application/octet-stream",
        )

    def delete_path(self, filepath: str) -> bool:
        try:
            p = Path(filepath)
            if not p.is_file():
                return False
            p.unlink()
            return True
        except OSError:
            return False

    def open_for_read(self, filepath: str) -> Path:
        p = Path(filepath)
        if not p.is_file():
            raise StorageError(f"file not found on disk: {filepath}")
        return p
