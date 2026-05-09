"""JSON-логирование без чувствительных полей (stdlib)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Одна запись лога — один JSON-объект в stdout.

    Для событий агрегации полезные необязательные поля из log_payload:
    budget_remaining (остаток суточного бюджета USD),
    cache_ttl_remaining (оставшийся TTL кэша в секундах, если применимо).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        merged = getattr(record, "log_payload", None)
        if isinstance(merged, dict):
            payload.update(merged)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_payload(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Залогировать событие с дополнительными полями (не передавать query/ключи)."""
    logger.log(level, event, extra={"log_payload": fields})
