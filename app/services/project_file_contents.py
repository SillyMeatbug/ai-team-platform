"""Извлечение текста и подготовка изображений из файлов проекта для промпта чата."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config.loader import Settings
from app.core.storage import FileStorage

if TYPE_CHECKING:
    from app.models.database import AgentLibraryFile, ProjectFile

    _ChatAttachmentRecord = ProjectFile | AgentLibraryFile
else:
    _ChatAttachmentRecord = Any

logger = logging.getLogger(__name__)

# Расширения, которые читаем как текст (UTF-8 / fallback).
_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        "txt",
        "md",
        "markdown",
        "csv",
        "tsv",
        "json",
        "jsonl",
        "xml",
        "html",
        "htm",
        "css",
        "scss",
        "less",
        "js",
        "mjs",
        "cjs",
        "ts",
        "tsx",
        "jsx",
        "vue",
        "svelte",
        "py",
        "rb",
        "php",
        "java",
        "kt",
        "kts",
        "swift",
        "go",
        "rs",
        "c",
        "h",
        "cpp",
        "hpp",
        "cs",
        "sql",
        "sh",
        "bash",
        "zsh",
        "ps1",
        "bat",
        "cmd",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "env",
        "properties",
        "log",
        "rst",
        "adoc",
        "tex",
        "dockerfile",
        "pod",
        "http",
    }
)

_IMAGE_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
_PDF_EXTENSIONS: frozenset[str] = frozenset({"pdf"})
_DOCX_EXTENSIONS: frozenset[str] = frozenset({"docx"})
_SKIP_BINARY_NOTE: frozenset[str] = frozenset({"fig"})
_DOC_LEGACY: frozenset[str] = frozenset({"doc"})

_MIME_FOR_EXT: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _truncate(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    head = max_len - 40
    return s[: max(0, head)] + "\n...[truncated]...\n"


def _path_under_storage_root(storage: FileStorage, path: Path) -> bool:
    root = storage.root.resolve()
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _decode_text_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_plain_text(path: Path, max_chars: int) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[: min(len(raw), 16_384)]:
        return ""
    text = _decode_text_bytes(raw)
    return _truncate(text.strip(), max_chars)


def _extract_pdf(path: Path, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning(
            "chat_pdf_extract_skipped",
            extra={"log_payload": {"reason": "pypdf_missing"}},
        )
        return ""

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            if total >= max_chars:
                break
            chunk = page.extract_text() or ""
            parts.append(chunk)
            total += len(chunk)
        return _truncate("\n".join(parts).strip(), max_chars)
    except Exception as e:
        logger.warning(
            "chat_pdf_extract_failed",
            extra={"log_payload": {"error_type": type(e).__name__}},
        )
        return ""


def _extract_docx(path: Path, max_chars: int) -> str:
    try:
        from docx import Document
    except ImportError:
        logger.warning(
            "chat_docx_extract_skipped",
            extra={"log_payload": {"reason": "python_docx_missing"}},
        )
        return ""

    try:
        doc = Document(str(path))
        paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        return _truncate("\n".join(paras).strip(), max_chars)
    except Exception as e:
        logger.warning(
            "chat_docx_extract_failed",
            extra={"log_payload": {"error_type": type(e).__name__}},
        )
        return ""


def _encode_image_for_vision(
    path: Path,
    ext: str,
    *,
    max_side: int,
    max_bytes: int,
) -> tuple[str, str] | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None

    mime_fallback = _MIME_FOR_EXT.get(ext, "image/jpeg")

    try:
        from PIL import Image

        with Image.open(path) as img:
            if getattr(img, "n_frames", 1) > 1:
                img.seek(0)
            if img.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88, optimize=True)
            out = buf.getvalue()
            if len(out) > max_bytes:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=72, optimize=True)
                out = buf.getvalue()
            if len(out) > max_bytes:
                return None
            return ("image/jpeg", base64.standard_b64encode(out).decode("ascii"))
    except Exception as e:
        logger.warning(
            "chat_image_preprocess_failed",
            extra={"log_payload": {"error_type": type(e).__name__, "ext": ext}},
        )

    # Fallback: маленькие PNG/JPEG/WebP без перекодирования
    if ext in {"png", "jpg", "jpeg", "webp"} and size <= min(max_bytes, 1_500_000):
        try:
            raw = path.read_bytes()
            return mime_fallback, base64.standard_b64encode(raw).decode("ascii")
        except OSError:
            return None
    return None


def _extract_text_body(
    pf: _ChatAttachmentRecord,
    path: Path,
    max_chars: int,
) -> tuple[str, str]:
    """(body, note). note — предупреждение без тела."""
    ext = path.suffix.lower().lstrip(".")
    ct = (pf.content_type or "").lower()
    is_pdf = ext in _PDF_EXTENSIONS or ct == "application/pdf" or ct.endswith("/pdf")
    is_docx = ext in _DOCX_EXTENSIONS or (
        "officedocument.wordprocessingml.document" in ct
    )
    is_image = ext in _IMAGE_EXTENSIONS or ct.startswith("image/")

    if ext in _DOC_LEGACY:
        return "", "Формат .doc не поддерживается — экспортируйте в .docx или PDF."
    if ext in _SKIP_BINARY_NOTE:
        return "", "Бинарный черновик Figma (.fig) — извлечение текста недоступно."
    if is_image:
        return "", ""
    if is_pdf:
        t = _extract_pdf(path, max_chars)
        if not t:
            return "", "Не удалось извлечь текст из PDF."
        return t, ""
    if is_docx:
        t = _extract_docx(path, max_chars)
        if not t:
            return "", "Не удалось извлечь текст из DOCX."
        return t, ""
    if ext in _TEXT_EXTENSIONS or (not ext and ct.startswith("text/")) or ct.startswith("text/"):
        t = _extract_plain_text(path, max_chars)
        if not t:
            return "", "Файл похож на бинарный или пустой."
        return t, ""

    # Неизвестное расширение: пробуем как UTF-текст (без NUL в начале файла).
    t_fallback = _extract_plain_text(path, max_chars)
    if t_fallback:
        return t_fallback, "(расширение не из списка; прочитано как текст UTF-8)"

    return "", f"Расширение «.{ext or '?'}» — содержимое не извлечено."


def prepare_chat_attachment_sections(
    storage: FileStorage,
    sections: list[tuple[str | None, list[_ChatAttachmentRecord]]],
    settings: Settings,
) -> tuple[str, list[tuple[str, str]]]:
    """
    Несколько блоков файлов (библиотека агента, файлы проекта, …) с общими лимитами.

    Не логирует содержимое файлов и base64.
    """
    text_sections: list[str] = []
    images_out: list[tuple[str, str]] = []
    total_text_len = 0
    budget_total = settings.chat_file_total_text_max_chars
    per_file_cap = settings.chat_file_text_max_chars
    max_images = settings.chat_file_max_images

    for section_title, file_list in sections:
        if not file_list:
            continue
        sorted_files = sorted(file_list, key=lambda f: f.uploaded_at)
        if section_title:
            header = f"## {section_title}"
            text_sections.append(header)
            total_text_len += len(header) + 2

        for pf in sorted_files:
            path = Path(pf.filepath)
            if not path.is_file():
                text_sections.append(f"### {pf.filename}\n(файл отсутствует на диске)")
                total_text_len += 80
                continue

            if not _path_under_storage_root(storage, path):
                logger.warning(
                    "chat_file_path_rejected",
                    extra={"log_payload": {"file_id": pf.id}},
                )
                continue

            ext = path.suffix.lower().lstrip(".")
            ct = (pf.content_type or "").lower()
            is_image = ext in _IMAGE_EXTENSIONS or ct.startswith("image/")

            if is_image:
                if len(images_out) >= max_images:
                    continue
                pair = _encode_image_for_vision(
                    path,
                    ext,
                    max_side=settings.chat_image_max_side_px,
                    max_bytes=settings.chat_image_max_bytes,
                )
                if pair:
                    images_out.append(pair)
                continue

            remaining = budget_total - total_text_len
            if remaining <= 200:
                text_sections.append(
                    f"### {pf.filename}\n_(пропущено: достигнут лимит объёма текста вложений)_"
                )
                total_text_len += 60
                continue

            cap = min(per_file_cap, remaining)
            body, note = _extract_text_body(pf, path, cap)
            block_lines = [f"### {pf.filename}"]
            if note:
                block_lines.append(note)
            if body:
                block_lines.append(body)
            elif not note:
                block_lines.append("(пусто)")
            section = "\n".join(block_lines)
            text_sections.append(section)
            total_text_len += len(section)

    combined = "\n\n".join(text_sections).strip()
    combined = _truncate(combined, budget_total)
    return combined, images_out


def prepare_chat_file_attachments(
    storage: FileStorage,
    files: list[_ChatAttachmentRecord],
    settings: Settings,
) -> tuple[str, list[tuple[str, str]]]:
    """Обратная совместимость: только список файлов без секций."""
    if not files:
        return "", []
    return prepare_chat_attachment_sections(storage, [(None, files)], settings)
