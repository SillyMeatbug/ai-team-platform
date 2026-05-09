"""Лимиты стоимости запросов и суточный бюджет (in-memory).

# TODO: Redis для прода (согласованное состояние между воркерами).
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime


class BudgetLimiter:
    """Проверка оценочной стоимости до диспатча и учёт фактической после ответа."""

    __slots__ = ("_max_per_request", "_max_daily", "_lock", "_day", "_spent_today")

    def __init__(self, *, max_cost_per_request: float, max_daily_cost: float) -> None:
        self._max_per_request = max_cost_per_request
        self._max_daily = max_daily_cost
        self._lock = threading.Lock()
        self._day: date | None = None
        self._spent_today = 0.0

    def _rollover_if_needed_unlocked(self) -> None:
        today = datetime.now(UTC).date()
        if self._day != today:
            self._day = today
            self._spent_today = 0.0

    def check_request_cost(self, estimated_cost: float) -> bool:
        if estimated_cost < 0:
            estimated_cost = 0.0
        with self._lock:
            self._rollover_if_needed_unlocked()
            if estimated_cost > self._max_per_request:
                return False
            if self._spent_today + estimated_cost > self._max_daily:
                return False
            return True

    def record_actual_cost(self, actual_cost: float) -> None:
        with self._lock:
            self._rollover_if_needed_unlocked()
            self._spent_today += max(0.0, actual_cost)

    def get_remaining_daily(self) -> float:
        with self._lock:
            self._rollover_if_needed_unlocked()
            return max(0.0, self._max_daily - self._spent_today)
