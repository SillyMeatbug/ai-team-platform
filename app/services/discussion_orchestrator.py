"""Оркестрация групповых дискуссий AI-агентов.

Не создаёт `httpx.AsyncClient`; использует переданный `app.state.http_client`
и существующий `complete_chat_messages` из dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.loader import RouteEntry, Settings
from app.core.logging_config import log_payload
from app.core.storage import FileStorage
from app.models.database import (
    Agent,
    AgentLibraryFile,
    ChatMessage,
    DebateRound,
    DebateThread,
    DebateTurn,
    Project,
    ProjectAgent,
    ProjectFile,
)
from app.services.dispatcher import complete_chat_messages
from app.services.market_data import (
    compute_data_freshness_status,
    fetch_live_context,
    format_live_context_markdown,
    has_actionable_onchain_proxy,
)
from app.services.paper_trading import record_trade_from_signal
from app.services.project_file_contents import prepare_chat_attachment_sections

logger = logging.getLogger(__name__)

# Кэш fetch_live_context по asset|timeframe внутри процесса (TTL короче TTL свечей — только чтобы не дублировать запросы в одном ходе чата).
_ORCH_MC_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ORCH_MC_CACHE_LOCK = asyncio.Lock()
_ORCH_MC_CACHE_TTL_S = 45.0

_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_\- ]{1,80})")
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.lower())


# Если в БД у агента пустое поле model — подставляем универсальную модель (Llama 3.3 70B: сильный общий reasoning).
_DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"
# Скрытый Router (JSON-план / выбор агентов): быстро и дёшево при стабильном следовании формату.
_ROUTER_MODEL = "openai/gpt-4o-mini"
# Финальный синтез multi-round debate: Llama 3.3 70B — тот же класс моделей, что у стабильных агентов (избегаем 402 на Anthropic).
_SYNTHESIZER_MODEL = "meta-llama/llama-3.3-70b-instruct"
_DEBATE_ROUNDS_BY_MODE: dict[str, int] = {
    "off": 0,
    "fast": 3,
    "standard": 4,
    "deep": 5,
}
# Router (auto): число раундов 3–5 → пресет для треда (соответствует fast / standard / deep)
_DEBATE_ROUND_COUNT_TO_MODE: dict[int, str] = {3: "fast", 4: "standard", 5: "deep"}
_REQUEST_DEBATE_MODES = frozenset({"auto", "off", "fast", "standard", "deep"})
# Ниже этого порога ordered_agent_ids от Router не применяем — fallback на prioritize_agents.
_ROUTER_ORDER_CONFIDENCE_MIN = 0.6

_ROUTER_SELECTION_STRATEGY = (
    "СТРАТЕГИЯ ВЫБОРА АГЕНТОВ:\n"
    "- Простой вопрос (факт, определение) -> 1 агент, режим \"off\".\n"
    "- Техническая реализация (код, дизайн) -> 2 агента, режим \"sequential\".\n"
    "- Сложная задача / Брейншторминг / Стратегия -> 3-4 агента, режим \"debate\".\n"
    "  * Плюрализм мнений важен: позволяй разным ролям высказаться.\n"
    "  * Цель: найти неочевидные решения и оценить риски с разных сторон.\n"
    "- Если не уверен -> выбери 2-3 агента и режим \"debate\".\n"
    "ВАЖНО: Если вопрос требует широкого обсуждения — вызывай всю команду."
)

_SYNTHESIZER_BRIEF_RULES = (
    "Формируй итог кратко, но полно:\n"
    "- 3-5 ключевых пунктов (решение, аргументы \"за\", аргументы \"против\", открытые вопросы).\n"
    "- Если мнений было много (3-4 агента) — выдели точки согласия и главные разногласия.\n"
    "- Без вводных слов, сразу к сути."
)

_CRYPTO_AGENT_ROLES = frozenset(
    {
        "technical_analyst",
        "onchain_analyst",
        "sentiment_analyst",
        "risk_manager",
        "crypto_interpreter",
    }
)
_CRYPTO_TECHNICAL_ROLES = frozenset(
    {"technical_analyst", "onchain_analyst", "sentiment_analyst", "risk_manager"}
)
_RISK_MANAGER_BLOCK_RE = re.compile(
    r"\b(быч\w*|медвеж\w*|нейтрал\w*|прогноз\w*|выраст\w*|упад\w*|купить|продать|long|short|bullish|bearish)\b",
    re.IGNORECASE,
)
_RISK_MANAGER_FALLBACK_TEXT = (
    "⚠️ Risk Manager: формат нарушен. Используйте SL/TP из Technical Analyst. "
    "Риск-расчёт временно недоступен."
)
_MAX_TARGET_AGENTS = 5

_PAIR_FROM_MESSAGE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]{1,14})/(USDT|USDC|USD|BUSD)\b",
)
_BASE_TICKER_FROM_MESSAGE_RE = re.compile(
    r"\b(BTC|ETH|SOL|XRP|BNB|DOGE|ADA|DOT|AVAX|LINK|TON|MATIC|POL|TRX|LTC|BCH|NEAR|ATOM|APT|SUI|OP|ARB)\b",
    re.I,
)
_TF_FROM_MESSAGE_RE = re.compile(
    r"\b(1m|3m|5m|15m|30m|1h|2h|4h|6h|12h|1d|3d|1w|1M)\b",
    re.I,
)


def resolve_market_params_for_chat(
    user_message: str,
    *,
    explicit_asset: str | None,
    explicit_timeframe: str | None,
    targets_include_crypto_agent: bool,
) -> tuple[str | None, str | None]:
    """Поля из API имеют приоритет; иначе вытаскиваем пару/ТФ из текста чата.

    Если в очереди есть крипто-роли, а актив не указан ни в API, ни в тексте — подставляем BTC/USDT,
    иначе `_resolve_market_context` получает asset=None и LIVE DATA не загружается (вечный PASS).
    """
    ea = (explicit_asset or "").strip() or None
    et = (explicit_timeframe or "").strip() or None
    msg = user_message or ""

    inferred_asset: str | None = None
    inferred_tf: str | None = None

    pair_m = _PAIR_FROM_MESSAGE_RE.search(msg)
    if pair_m:
        inferred_asset = f"{pair_m.group(1).upper()}/{pair_m.group(2).upper()}"
    else:
        bm = _BASE_TICKER_FROM_MESSAGE_RE.search(msg)
        if bm:
            inferred_asset = f"{bm.group(1).upper()}/USDT"

    tf_m = _TF_FROM_MESSAGE_RE.search(msg)
    if tf_m:
        inferred_tf = tf_m.group(1).lower()

    out_a = ea or inferred_asset
    out_t = et or inferred_tf
    if targets_include_crypto_agent and not out_a:
        out_a = "BTC/USDT"
    return out_a, out_t


def _parse_json_object_from_llm(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class RouterAutoPlan:
    targets: list[Agent]
    resolved_debate_mode: str
    flow: str
    reason: str
    confidence: float
    off_chain_style: str | None
    ordered_agent_ids: list[str] | None = None


@dataclass
class PrepareChatOutcome:
    user_msg: ChatMessage
    pending_agent_ids: list[str]
    is_discussion: bool
    temperature: float
    debate_mode: str
    debate_thread_id: str | None
    selected_agents: list[str] | None
    response_order: list[str] | None
    router_reason: str | None = None
    router_flow: str | None = None
    off_chain_style: str | None = None
    market_asset: str | None = None
    market_timeframe: str | None = None
    data_freshness: str | None = None
    source: str | None = None
    market_context: dict[str, Any] | None = None


def _model_supports_images(model_id: str) -> bool:
    """Грубая эвристика: не отправляем image_url в text-only модели."""
    m = (model_id or "").lower()
    if not m:
        return False
    vision_markers = (
        "gpt-4o",
        "gpt-4.1",
        "vision",
        "gemini",
        "claude-3",
        "claude-4",
    )
    return any(marker in m for marker in vision_markers)


def _openrouter_chat_url() -> str:
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    return f"{base}/chat/completions"


def _openrouter_headers() -> dict[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://127.0.0.1:8000").strip()
    title = os.getenv("OPENROUTER_APP_TITLE", "AI Team Platform").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": title,
    }


def _resolve_route_for_agent(agent: Agent) -> RouteEntry:
    """Маршрут чата: один шлюз OpenRouter, идентификатор модели из поля Agent.model."""
    model_id = (agent.model or "").strip() or _DEFAULT_OPENROUTER_MODEL
    return RouteEntry(
        route_id=f"agent-{agent.id}",
        provider="openrouter",
        model=model_id,
        role=agent.role,
        active=True,
        system_prompt=agent.system_prompt,
        is_arbiter=False,
        cache_override_ttl=None,
    )


@dataclass(frozen=True)
class _AgentTurnResult:
    agent: Agent
    content: str | None
    error: str | None


def _extract_mention_tokens(text: str) -> list[str]:
    return [m.group(1).strip() for m in _MENTION_RE.finditer(text or "")]


def _resolve_mentioned(agents: list[Agent], text: str) -> list[Agent]:
    """Порядок агентов = порядок @упоминаний в тексте (первое совпадение имени по каждому токену)."""
    tokens = _extract_mention_tokens(text)
    if not tokens:
        return []
    norm_tokens = [_normalize(t) for t in tokens if t]
    out: list[Agent] = []
    seen: set[str] = set()
    for tok in norm_tokens:
        if not tok:
            continue
        for agent in agents:
            if agent.id in seen:
                continue
            nname = _normalize(agent.name)
            if nname == tok or nname.startswith(tok) or tok in nname:
                out.append(agent)
                seen.add(agent.id)
                break
    return out


_CRYPTO_PASS_NO_DATA = (
    "⛔ PASS: Нет актуальных данных для анализа. Не используй исторические примеры."
)

_CRYPTO_FAIL_LOUD_ROLES = frozenset(
    {
        "technical_analyst",
        "onchain_analyst",
        "sentiment_analyst",
        "risk_manager",
        "crypto_interpreter",
    }
)


def _crypto_live_data_blocked(
    market_context: dict[str, Any] | None,
    *,
    agent_role: str | None = None,
) -> bool:
    # On-chain: не блокировать LLM, если в контексте есть флаг или любые рабочие строки прокси.
    if agent_role == "onchain_analyst":
        mc = market_context or {}
        if mc.get("onchain_proxy_ok") is True:
            return False
        if has_actionable_onchain_proxy(mc):
            return False
    if market_context is None:
        return True
    return compute_data_freshness_status(market_context) in ("STALE", "UNAVAILABLE")


def _is_pass_response(text: str | None) -> bool:
    raw = (text or "").strip()
    ls = raw.lower()
    if ls.startswith("⛔ pass") or "нет актуальных данных" in ls:
        return True
    return ls.startswith("pass: not my expertise") or ls.startswith("pass: не моя")


def _is_ui_question(text: str) -> bool:
    t = text.lower()
    keys = ("ui", "ux", "design", "дизайн", "интерфейс", "фронт", "frontend")
    return any(k in t for k in keys)


def _is_api_question(text: str) -> bool:
    t = text.lower()
    keys = ("api", "architecture", "архитект", "endpoint", "контракт", "schema", "бд", "database")
    return any(k in t for k in keys)


def _is_deploy_question(text: str) -> bool:
    t = text.lower()
    keys = ("deploy", "devops", "ci/cd", "pipeline", "infra", "хост", "сервер")
    return any(k in t for k in keys)


def _format_chat_history(history: list[ChatMessage], agents_by_id: dict[str, Agent]) -> str:
    if not history:
        return "(пусто)"
    lines: list[str] = []
    for m in history:
        if m.sender_type == "user":
            who = "User"
        else:
            agent = agents_by_id.get(m.sender_id or "")
            who = agent.name if agent else "Agent"
        ts = m.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
        snippet = (m.content or "").strip().replace("\n", " ")
        if len(snippet) > 600:
            snippet = snippet[:600] + "…"
        lines.append(f"[{ts}] {who}: {snippet}")
    return "\n".join(lines)


def _format_team_roster(team_agents: list[Agent]) -> str:
    if not team_agents:
        return "(нет активных участников)"
    lines: list[str] = []
    for a in team_agents:
        lines.append(f"- {a.name} — роль `{a.role}`, id `{a.id}`")
    return "\n".join(lines)


def _format_files(files: list[ProjectFile]) -> str:
    if not files:
        return "(файлов нет)"
    out: list[str] = []
    for f in files:
        size_kb = max(1, f.file_size // 1024)
        out.append(f"- {f.filename} ({f.category}, {size_kb} KB, type={f.content_type})")
    return "\n".join(out)


def _format_previous_responses(
    prev: list[tuple[Agent, str]],
    *,
    max_chars_per_agent: int = 1500,
) -> str:
    if not prev:
        return "(нет — ты отвечаешь первым)"
    out: list[str] = []
    cap = max(400, min(max_chars_per_agent, 8000))
    for agent, text in prev:
        snippet = text.strip()
        if len(snippet) > cap:
            snippet = snippet[:cap] + "…"
        out.append(f"## {agent.name} ({agent.role}):\n{snippet}")
    return "\n\n".join(out)


def _debate_turn_instruction_block(
    *,
    round_num: int,
    total_rounds: int,
    locale: str,
) -> str:
    """Жёсткие правила реплики во внутренней многораундовой дискуссии (не смешивать с обычным чатом)."""
    loc = (locale or "en").strip().lower()
    ru = loc.startswith("ru")
    tr = max(1, total_rounds)
    r = max(1, min(round_num, tr))

    if ru:
        base = (
            f"\n\n### Внутренняя дискуссия команды (раунд {r} из {tr})\n"
            "Это закрытое обсуждение между ролями до финального ответа пользователю.\n"
        )
        if r == 1:
            return (
                base
                + "- Дай позицию **по сути вопроса пользователя**: 3–7 коротких пунктов с точки зрения твоей роли.\n"
                + "- **Запрещено**: приветствия; фразы вроде «давайте начнём/приступим к мозговому штурму»; "
                "пустые вступления без новых фактов/решений/рисков.\n"
                + "- Первое предложение должно сразу нести содержание (например: «По контрактам API: …», «По UX каталога: …»).\n"
            )
        lines = [
            base,
            "- **Обязательно**: явно ссылайся минимум на **одну** конкретную мысль коллеги (укажи **имя роли** из блока выше) "
            "и ответь: согласен / частично / не согласен — с **коротким аргументом**.\n",
            "- **Запрещено**: повторять свои или чужие шаблонные вступления из раунда 1; снова открывать «мозговой штурм»; "
            "пересказывать всё с нуля теми же словами.\n",
            "- Структура: **(1)** реакция на коллегу **(2)** твой новый вклад (детали, риск, альтернатива) "
            "**(3)** один открытый вопрос или явное разногласие для следующего раунда.\n",
        ]
        if tr >= 3 and r == tr:
            lines.append(
                "- Финальный раунд: назови **одно** возможное разногласие в команде и предложи **компромисс** или критерий выбора.\n"
            )
        return "".join(lines)

    base = (
        f"\n\n### Internal team debate (round {r} of {tr})\n"
        "This is a closed multi-agent discussion before the user-facing summary.\n"
    )
    if r == 1:
        return (
            base
            + "- Give **substance-only** input from your role: 3–7 short bullets tied to the user's question.\n"
            + "- **Forbidden**: greetings; phrases like "
            '"let\'s brainstorm / let\'s start a brainstorming session"; '
            "generic openings with no new facts, decisions, or risks.\n"
            + '- Your **first sentence must carry content** (e.g. "On API contracts: …", "On checkout UX: …").\n'
        )
    lines = [
        base,
        "- **Required**: respond to **at least one** concrete point from a colleague (name their **role**) with "
        "**agree / partially agree / disagree** plus a brief rationale.\n",
        "- **Forbidden**: repeating boilerplate intros from round 1; restarting “brainstorm” framing; "
        "rewriting the same overview with different wording.\n",
        "- Structure: **(1)** reaction **(2)** new contribution **(3)** one open question or explicit disagreement for later rounds.\n",
    ]
    if tr >= 3 and r == tr:
        lines.append(
            "- Final round: surface **one** likely team disagreement and propose a **trade-off** or decision criterion.\n"
        )
    return "".join(lines)


def build_agent_prompt(
    *,
    agent: Agent,
    project: Project,
    files: list[ProjectFile],
    history: list[ChatMessage],
    agents_by_id: dict[str, Agent],
    team_agents: list[Agent],
    user_message: str,
    previous_responses: list[tuple[Agent, str]],
    file_attachments_text: str,
    file_attachments_images: list[tuple[str, str]],
    debate_round: int | None = None,
    debate_total_rounds: int | None = None,
    debate_locale: str | None = None,
    market_context_markdown: str | None = None,
) -> list[dict[str, Any]]:
    """Сформировать messages для chat completions (при наличии картинок — multimodal user)."""
    description = (project.description or "").strip() or "(не указано)"
    roster_block = _format_team_roster(team_agents)
    files_block = _format_files(files)
    history_block = _format_chat_history(history, agents_by_id)
    prev_cap = 820 if debate_round is not None else 1500
    prev_block = _format_previous_responses(previous_responses, max_chars_per_agent=prev_cap)

    system_prompt = agent.system_prompt.strip()
    if market_context_markdown and agent.role in _CRYPTO_AGENT_ROLES:
        system_prompt = f"{market_context_markdown}\n\n{system_prompt}"
    system_prompt += "\n\nIf the request is outside your expertise, reply exactly: Pass: not my expertise"
    if debate_round is not None and debate_total_rounds:
        system_prompt += (
            "\n\nYou are in a multi-round INTERNAL debate: react to colleagues, avoid repeating generic intros, "
            "and advance the discussion with new points or disagreements."
        )

    debate_block = ""
    if debate_round is not None and debate_total_rounds:
        debate_block = _debate_turn_instruction_block(
            round_num=debate_round,
            total_rounds=debate_total_rounds,
            locale=debate_locale or "en",
        )

    files_extracted = ""
    if file_attachments_text.strip():
        files_extracted = (
            "### Извлечённое содержимое файлов проекта\n"
            f"{file_attachments_text.strip()}\n\n"
        )

    user_payload_text = (
        f"Проект: {project.name}\n"
        f"Описание: {description}\n\n"
        f"Участники команды проекта (все подключённые агенты):\n{roster_block}\n\n"
        f"Список файлов (метаданные):\n{files_block}\n\n"
        f"{files_extracted}"
        f"История обсуждения (последние сообщения, сохранённые в проекте):\n{history_block}\n\n"
        f"Предыдущие ответы коллег в этом обсуждении:\n{prev_block}\n"
        f"{debate_block}\n"
        f"Сообщение пользователя:\n{user_message}\n\n"
        f"Ответь с позиции своей роли ({agent.role}). "
        f"Будь конкретен; не повторяй коллег, дополняй или конструктивно возражай."
    )

    if file_attachments_images:
        vision_intro = (
            "К этому сообщению приложены изображения из файлов проекта "
            "(ниже как отдельные части content). Учитывай их при ответе.\n\n"
        )
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": vision_intro + user_payload_text},
        ]
        for mime, b64 in file_attachments_images:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        user_msg: dict[str, Any] = {"role": "user", "content": parts}
    else:
        user_msg = {"role": "user", "content": user_payload_text}

    return [
        {"role": "system", "content": system_prompt},
        user_msg,
    ]


def _mock_agent_reply(
    *,
    agent: Agent,
    user_message: str,
    previous_responses: list[tuple[Agent, str]],
) -> str:
    excerpt = (user_message or "").strip().replace("\n", " ")
    if len(excerpt) > 200:
        excerpt = excerpt[:200] + "…"
    prev = (
        f" (учитываю мнения: {', '.join(a.name for a, _ in previous_responses)})"
        if previous_responses
        else ""
    )
    return (
        f"[MOCK · {agent.name}] Как {agent.role}, по запросу «{excerpt}»{prev} "
        f"я бы предложил трёхшаговый план: 1) уточнить цели, 2) подготовить артефакт "
        f"в моей зоне ответственности, 3) синхронизироваться с командой."
    )


def _safe_excerpt(text: str, *, limit: int = 280) -> str:
    s = (text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def _extract_between(text: str, start: str, end_markers: list[str]) -> str:
    idx = text.find(start)
    if idx < 0:
        return ""
    tail = text[idx + len(start) :]
    end = len(tail)
    for m in end_markers:
        j = tail.find(m)
        if j >= 0 and j < end:
            end = j
    return tail[:end].strip()


def _compact_argument_summary(text: str, *, limit: int = 240) -> str:
    """Сжать длинную реплику агента до короткого тезиса."""
    s = (text or "").strip().replace("\n", " ")
    if not s:
        return ""
    # Убираем частые префиксы и markdown-шум
    s = re.sub(r"\*\*[^*]+\*\*:\s*", "", s)
    s = re.sub(r"^(сообщение пользователя:|ответ [^:]+:)\s*", "", s, flags=re.I)
    s = re.sub(
        r"^(привет(,|\!)?\s*(коллеги|команда)?[!,.:\s-]*|"
        r"здравствуйте[!,.:\s-]*|"
        r"доброе утро[!,.:\s-]*|"
        r"hello[!,.:\s-]*|"
        r"hi[!,.:\s-]*|"
        r"good (morning|afternoon|evening)[!,.:\s-]*)",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"^(в качестве [^,.!?:]{3,60}\s+(я (думаю|считаю|предлагаю)|считаю|думаю)\s*,?\s*)",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip()

    # Берем первые 1-2 содержательных предложения, чтобы не терять смысл.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]
    kept: list[str] = []
    for p in parts:
        if re.match(r"^(спасибо|благодарю|thanks)\b", p, flags=re.I):
            continue
        kept.append(p)
        if len(" ".join(kept)) >= 160 or len(kept) >= 2:
            break
    if kept:
        s = " ".join(kept)

    if len(s) <= limit:
        return s
    return s[:limit].rstrip(" ,;:-") + "…"


def _build_debate_final_text(
    *,
    user_message: str,
    turns: list[tuple[Agent, str]],
    errors_count: int,
    timed_out: bool,
    locale: str,
) -> tuple[str, str, str]:
    """Собрать структурированный ответ пользователю + метаданные confidence/disagreements."""
    is_ru = locale == "ru"
    if not turns:
        if is_ru:
            summary = (
                "✅ Итог / Консенсус:\n"
                "Команда не смогла сформировать содержательный ответ в заданные лимиты.\n\n"
                "🧩 Ключевые аргументы:\n"
                "- Нет успешных реплик от агентов.\n\n"
                "⚠️ Открытые вопросы / Разногласия:\n"
                "- Требуется повторный запуск дискуссии или уточнение запроса.\n\n"
                "📈 Уровень уверенности: низкий\n"
            )
            return summary, "низкий", "Нет успешных реплик от агентов."
        summary = (
            "✅ Consensus:\n"
            "The team could not produce a meaningful answer within the limits.\n\n"
            "🧩 Key arguments:\n"
            "- No successful agent turns were produced.\n\n"
            "⚠️ Open questions / disagreements:\n"
            "- Retry the discussion or clarify the request.\n\n"
            "📈 Confidence level: low\n"
        )
        return summary, "low", "No successful agent turns."

    role_counts = Counter(a.role for a, _ in turns)
    top_roles = ", ".join(r for r, _ in role_counts.most_common(3))
    first = _safe_excerpt(turns[0][1], limit=380)
    if is_ru:
        consensus = (
            f"Команда согласилась с базовым вектором решения по запросу «{_safe_excerpt(user_message, limit=120)}». "
            f"Основной фокус: {first}"
        )
    else:
        consensus = (
            f"The team aligned on a baseline solution for “{_safe_excerpt(user_message, limit=120)}”. "
            f"Main focus: {first}"
        )

    # Выводим по одному краткому тезису на агента (последняя реплика),
    # чтобы блок "Ключевые аргументы" был читаемым summary, а не дампом.
    latest_by_agent: dict[str, tuple[Agent, str]] = {}
    for agent, content in turns:
        latest_by_agent[agent.id] = (agent, content)

    arg_lines: list[str] = []
    for _, (agent, content) in list(latest_by_agent.items())[:5]:
        thesis = _compact_argument_summary(content)
        if not thesis:
            continue
        arg_lines.append(f"- {agent.name} ({agent.role}): {thesis}")
    if not arg_lines:
        arg_lines.append(
            "- Нет кратких тезисов по репликам агентов."
            if is_ru
            else "- No concise theses could be extracted from agent turns."
        )

    disagreements_parts: list[str] = []
    if len(role_counts) > 1:
        disagreements_parts.append(
            f"Разные роли ( {top_roles} ) делают акцент на разных аспектах реализации."
            if is_ru
            else f"Different roles ({top_roles}) emphasize different implementation aspects."
        )
    if errors_count > 0:
        disagreements_parts.append(
            f"{errors_count} реплик завершились с ошибкой/пустым ответом."
            if is_ru
            else f"{errors_count} turns ended with an error or empty output."
        )
    if timed_out:
        disagreements_parts.append(
            "Дискуссия прервана по таймауту, итог собран по лучшему доступному контексту."
            if is_ru
            else "Discussion timed out; result is based on the best available context."
        )
    if not disagreements_parts:
        disagreements_parts.append(
            "Явных конфликтов позиций не выявлено."
            if is_ru
            else "No explicit conflicts were detected."
        )

    if timed_out or errors_count >= max(1, len(turns) // 2):
        confidence = "низкий" if is_ru else "low"
    elif errors_count > 0:
        confidence = "средний" if is_ru else "medium"
    else:
        confidence = "высокий" if is_ru else "high"

    if is_ru:
        text = (
            "✅ Итог / Консенсус:\n"
            f"{consensus}\n\n"
            "🧩 Ключевые аргументы:\n"
            f"{chr(10).join(arg_lines)}\n\n"
            "⚠️ Открытые вопросы / Разногласия:\n"
            f"- {chr(10).join(disagreements_parts)}\n\n"
            f"📈 Уровень уверенности: {confidence}\n"
            "🔍 Раскрыть детали дискуссии: используйте журнал дискуссии в интерфейсе проекта."
        )
    else:
        text = (
            "✅ Consensus:\n"
            f"{consensus}\n\n"
            "🧩 Key arguments:\n"
            f"{chr(10).join(arg_lines)}\n\n"
            "⚠️ Open questions / disagreements:\n"
            f"- {chr(10).join(disagreements_parts)}\n\n"
            f"📈 Confidence level: {confidence}\n"
            "🔍 Show discussion details in the project debate log."
        )
    return text, confidence, "\n".join(disagreements_parts)


def _is_deadline_exceeded(deadline: datetime | None) -> bool:
    if deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return datetime.now(UTC) > deadline


class DiscussionOrchestrator:
    """Координатор последовательной дискуссии агентов в проекте."""

    __slots__ = ("_session", "_settings", "_http_client", "_file_storage", "_session_lock")

    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        http_client: httpx.AsyncClient | None,
        file_storage: FileStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._http_client = http_client
        self._file_storage = file_storage
        self._session_lock = asyncio.Lock()

    async def _load_project(self, project_id: str) -> Project:
        proj = await self._session.get(Project, project_id)
        if proj is None or not proj.is_active:
            raise LookupError("Project not found")
        return proj

    async def _load_project_agents(self, project_id: str) -> list[Agent]:
        rows = (
            await self._session.execute(
                select(Agent)
                .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
                .where(
                    ProjectAgent.project_id == project_id,
                    ProjectAgent.is_active.is_(True),
                    Agent.is_active.is_(True),
                )
                .order_by(Agent.name.asc())
            )
        ).scalars().all()
        return list(rows)

    async def _load_recent_history(
        self, project_id: str, *, limit: int
    ) -> list[ChatMessage]:
        rows = (
            await self._session.execute(
                select(ChatMessage)
                .where(ChatMessage.project_id == project_id)
                .order_by(ChatMessage.timestamp.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(reversed(rows))

    async def _load_files(self, project_id: str) -> list[ProjectFile]:
        rows = (
            await self._session.execute(
                select(ProjectFile)
                .where(ProjectFile.project_id == project_id)
                .order_by(ProjectFile.uploaded_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def _load_agent_library_files(self, agent_id: str) -> list[AgentLibraryFile]:
        rows = (
            await self._session.execute(
                select(AgentLibraryFile)
                .where(AgentLibraryFile.agent_id == agent_id)
                .order_by(AgentLibraryFile.uploaded_at.asc())
            )
        ).scalars().all()
        return list(rows)

    async def _resolve_market_context(
        self,
        *,
        asset: str | None,
        timeframe: str | None,
        request_id: str,
    ) -> dict[str, Any] | None:
        if not asset:
            return None
        tf = (timeframe or "4H").strip().upper()
        sym = (asset or "").strip().upper()
        cache_key = f"{sym}|{tf}"
        loop_t = asyncio.get_running_loop().time()
        async with _ORCH_MC_CACHE_LOCK:
            hit = _ORCH_MC_CACHE.get(cache_key)
            if hit and loop_t - hit[0] < _ORCH_MC_CACHE_TTL_S:
                cached = hit[1]
                return dict(cached) if isinstance(cached, dict) else cached

        try:
            ctx = await fetch_live_context(asset=asset, timeframe=timeframe or "4H")
            log_payload(
                logger,
                logging.INFO,
                "market_context_loaded",
                request_id=request_id,
                asset=ctx.get("asset"),
                timeframe=ctx.get("timeframe"),
                data_freshness=ctx.get("data_freshness"),
                data_freshness_status=ctx.get("data_freshness_status"),
                source=ctx.get("source"),
            )
            stored_at = asyncio.get_running_loop().time()
            async with _ORCH_MC_CACHE_LOCK:
                _ORCH_MC_CACHE[cache_key] = (stored_at, dict(ctx))
            return ctx
        except Exception as e:
            log_payload(
                logger,
                logging.WARNING,
                "market_context_unavailable",
                request_id=request_id,
                asset=asset,
                timeframe=timeframe,
                error=f"{type(e).__name__}",
            )
            now_u = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
            return {
                "asset": asset,
                "timeframe": (timeframe or "4H").upper(),
                "updated_at": now_u,
                "current_system_time_utc": now_u,
                "last_ohlcv_candle_utc": None,
                "data_freshness": "unavailable",
                "source": "unavailable",
                "stale_data": True,
                "data_freshness_status": "UNAVAILABLE",
                "price": None,
            }

    async def _prepare_attachments_for_agent_turn(
        self,
        *,
        project_id: str,
        project_files: list[ProjectFile],
        agent: Agent,
        request_id: str | None = None,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Библиотека агента + файлы проекта для конкретного ответа."""
        if (
            self._file_storage is None
            or self._settings.aggregate_mock_providers
            or self._http_client is None
        ):
            return "", []

        lib_rows = await self._load_agent_library_files(agent.id)
        sections: list[tuple[str | None, list]] = []
        if lib_rows:
            sections.append((f"Библиотека агента «{agent.name}»", lib_rows))
        if project_files:
            sections.append(("Файлы проекта" if lib_rows else None, project_files))

        if not sections:
            return "", []

        text_b, imgs = await asyncio.to_thread(
            prepare_chat_attachment_sections,
            self._file_storage,
            sections,
            self._settings,
        )
        if text_b.strip() or imgs:
            log_payload(
                logger,
                logging.INFO,
                "chat_attachments_prepared",
                request_id=request_id or "-",
                project_id=project_id,
                agent_id=agent.id,
                text_chars=len(text_b),
                images=len(imgs),
            )
        return text_b, imgs

    async def _save_user_message(
        self,
        *,
        project_id: str,
        content: str,
        is_discussion: bool,
        attachment_file_ids: list[str] | None = None,
    ) -> ChatMessage:
        project = await self._session.get(Project, project_id)
        if project is not None:
            project.updated_at = datetime.now(UTC)
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            project_id=project_id,
            sender_type="user",
            sender_id=None,
            content=content,
            timestamp=datetime.now(UTC),
            is_discussion=is_discussion,
            parent_message_id=None,
            attachment_file_ids=attachment_file_ids or [],
        )
        self._session.add(msg)
        await self._session.commit()
        await self._session.refresh(msg)
        return msg

    async def _save_agent_message(
        self,
        *,
        project_id: str,
        agent: Agent | None,
        content: str | None,
        error: str | None,
        is_discussion: bool,
        parent_id: str,
    ) -> ChatMessage:
        async with self._session_lock:
            project = await self._session.get(Project, project_id)
            if project is not None:
                project.updated_at = datetime.now(UTC)
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                project_id=project_id,
                sender_type="agent",
                sender_id=agent.id if agent else None,
                content=content or "",
                timestamp=datetime.now(UTC),
                is_discussion=is_discussion,
                parent_message_id=parent_id,
                error=error,
                attachment_file_ids=[],
            )
            self._session.add(msg)
            await self._session.commit()
            await self._session.refresh(msg)
            return msg

    async def _maybe_record_paper_trade(
        self,
        *,
        project_id: str,
        agent: Agent | None,
        content: str | None,
        market_asset: str | None,
        market_timeframe: str | None,
        market_context: dict[str, Any] | None,
    ) -> None:
        if agent is None or not content:
            return
        asset = (market_asset or "").strip() or "BTC/USDT"
        timeframe = (market_timeframe or "").strip() or "4H"
        try:
            async with self._session_lock:
                await record_trade_from_signal(
                    self._session,
                    project_id=project_id,
                    agent=agent,
                    content=content,
                    asset=asset,
                    timeframe=timeframe,
                    market_context=market_context,
                )
        except Exception as e:
            log_payload(
                logger,
                logging.WARNING,
                "paper_trade_record_failed",
                project_id=project_id,
                agent_id=agent.id,
                error=type(e).__name__,
            )

    async def _create_debate_thread(
        self,
        *,
        project_id: str,
        user_message_id: str,
        mode: str,
        locale: str,
        agent_count: int = 1,
    ) -> DebateThread:
        rounds = _DEBATE_ROUNDS_BY_MODE.get(mode, 0)
        rounds = min(rounds, self._settings.chat_debate_max_rounds)
        agents = max(1, agent_count)
        # Один «полный» раунд — последовательные ответы всех агентов; базовый env под ~3 роли.
        agent_weight = max(1.0, agents / 3.0)
        synthesis_ms = min(
            180_000,
            max(45_000, int(self._settings.chat_response_timeout_ms * 2)),
        )
        timeout_ms = int(
            self._settings.chat_debate_timeout_ms * max(1, rounds) * agent_weight
            + synthesis_ms
        )
        timeout_ms = min(timeout_ms, self._settings.chat_debate_timeout_cap_ms)
        timeout_ms = max(timeout_ms, 60_000)
        now = datetime.now(UTC)
        thread = DebateThread(
            id=str(uuid.uuid4()),
            project_id=project_id,
            user_message_id=user_message_id,
            mode=mode,
            status="running",
            total_rounds=rounds,
            current_round=0,
            started_at=now,
            timeout_at=now + timedelta(milliseconds=timeout_ms),
            meta={"locale": locale},
        )
        self._session.add(thread)
        await self._session.commit()
        await self._session.refresh(thread)
        return thread

    async def _set_debate_status(
        self,
        thread: DebateThread,
        *,
        status: str,
        current_round: int | None = None,
        final_summary: str | None = None,
        confidence: str | None = None,
        disagreements: str | None = None,
        final_message_id: str | None = None,
        finished: bool = False,
    ) -> bool:
        current = await self._session.get(DebateThread, thread.id)
        if current is None:
            return False
        # cancelled — терминальный статус; запрещаем любые "обратные" переходы.
        if current.status == "cancelled" and status != "cancelled":
            return False

        thread = current
        thread.status = status
        if current_round is not None:
            thread.current_round = current_round
        if final_summary is not None:
            thread.final_summary = final_summary
        if confidence is not None:
            thread.confidence = confidence
        if disagreements is not None:
            thread.disagreements = disagreements
        if final_message_id is not None:
            thread.final_message_id = final_message_id
        if finished:
            thread.finished_at = datetime.now(UTC)
        await self._session.commit()
        return True

    async def _reload_debate_thread(self, thread_id: str) -> DebateThread | None:
        return await self._session.get(DebateThread, thread_id)

    def _resolve_debate_mode(
        self, *, debate_mode: str | None, is_discussion: bool
    ) -> str:
        mode = (debate_mode or "off").strip().lower()
        if mode not in _DEBATE_ROUNDS_BY_MODE:
            mode = "off"
        if mode != "off" and not is_discussion:
            # Для одного адресата debate не нужен — сохраняем обратную совместимость.
            return "off"
        return mode

    def _select_targets(
        self,
        *,
        all_agents: list[Agent],
        explicit_ids: list[str] | None,
        text: str,
    ) -> list[Agent]:
        if explicit_ids:
            id_set = set(explicit_ids)
            return [a for a in all_agents if a.id in id_set]
        mentioned = _resolve_mentioned(all_agents, text)
        if mentioned:
            return mentioned
        return list(all_agents)

    def prioritize_agents(self, agents: list[Agent], question_context: str) -> list[Agent]:
        """Приоритизация порядка ответов в sequential off-mode."""
        if not agents:
            return []
        role_to_agent: dict[str, Agent] = {a.role: a for a in agents}
        ordered: list[Agent] = []

        def take(role: str) -> None:
            a = role_to_agent.get(role)
            if a and a not in ordered:
                ordered.append(a)

        if _is_ui_question(question_context):
            take("designer")
            take("frontend_dev")
            take("frontend")
        elif _is_api_question(question_context):
            take("analyst")
            take("backend_dev")
            take("backend")
        elif _is_deploy_question(question_context):
            take("backend_dev")
            take("backend")
            take("devops")

        for a in agents:
            if a not in ordered:
                ordered.append(a)
        return ordered

    def _parse_ordered_agent_ids_field(
        self, parsed: dict[str, Any], *, confidence: float
    ) -> list[str] | None:
        """Из JSON Router; при низкой уверенности порядок не используем."""
        if confidence < _ROUTER_ORDER_CONFIDENCE_MIN:
            return None
        raw = parsed.get("ordered_agent_ids")
        if raw is None:
            return None
        if not isinstance(raw, list):
            return None
        out = [x for x in raw if isinstance(x, str)]
        return out if out else None

    def _coerce_router_execution_order(
        self,
        targets: list[Agent],
        *,
        router_ordered: list[str] | None,
        router_confidence: float,
        user_message: str,
    ) -> list[Agent]:
        """Для auto/off без лока: порядок из Router при высокой уверенности, иначе prioritize_agents."""
        if not targets:
            return targets
        agent_by_id = {a.id: a for a in targets}
        sel_set = set(agent_by_id.keys())

        def heuristic_order() -> list[Agent]:
            return self.prioritize_agents(targets, user_message)

        if (
            router_confidence < _ROUTER_ORDER_CONFIDENCE_MIN
            or not router_ordered
        ):
            return heuristic_order()

        seen: set[str] = set()
        ordered_agents: list[Agent] = []
        for oid in router_ordered:
            if oid not in sel_set or oid in seen:
                return heuristic_order()
            ordered_agents.append(agent_by_id[oid])
            seen.add(oid)

        for a in heuristic_order():
            if a.id in sel_set and a.id not in seen:
                ordered_agents.append(a)
                seen.add(a.id)

        return ordered_agents

    def _enforce_crypto_interpreter_last(
        self,
        targets: list[Agent],
        *,
        all_agents: list[Agent],
    ) -> list[Agent]:
        if not targets:
            return targets
        has_crypto_technical = any(a.role in _CRYPTO_TECHNICAL_ROLES for a in targets)
        if not has_crypto_technical:
            return targets
        interpreter = next(
            (a for a in all_agents if a.role == "crypto_interpreter" and a.is_active), None
        )
        if interpreter is None:
            return targets
        without_interpreter = [a for a in targets if a.id != interpreter.id]
        return [*without_interpreter, interpreter]

    async def route_question(
        self,
        *,
        user_message: str,
        all_agents: list[Agent],
        request_id: str,
    ) -> tuple[list[Agent], float, str, list[str] | None]:
        """Скрытый router agent: выбирает 1-3 релевантных агентов и опционально задаёт порядок."""
        if self._settings.aggregate_mock_providers or self._http_client is None:
            return list(all_agents), 0.0, "router_unavailable_mock", None
        roster = "\n".join(
            f"- id={a.id}; name={a.name}; role={a.role}" for a in all_agents
        )
        sys_prompt = (
            "Ты анализируешь вопрос пользователя и выбираешь агентов из списка.\n"
            "Верни строго JSON:\n"
            "{\n"
            '  "selected_agent_ids": ["uuid", ...],\n'
            '  "ordered_agent_ids": ["uuid", ...] | null,\n'
            '  "confidence": число 0..1,\n'
            '  "reason": "кратко"\n'
            "}\n"
            "Выбери 1–3 агента. Поле ordered_agent_ids — логическая цепочка вызова "
            "(аналитика / требования → дизайн → разработка → инфраструктура); "
            "те же id, что и в selected_agent_ids, без дубликатов. "
            "Если порядок неочевиден или ты не уверен — поставь ordered_agent_ids в null "
            "(оркестратор подставит эвристику).\n\n"
            f"{_ROUTER_SELECTION_STRATEGY}"
        )
        usr_prompt = (
            f"Вопрос пользователя:\n{user_message}\n\nДоступные агенты:\n{roster}\n\n"
            "Используй только id из списка. Ответ — только JSON."
        )
        route = RouteEntry(
            route_id="hidden-router-agent",
            provider="openrouter",
            model=_ROUTER_MODEL,
            role="router",
            active=True,
            system_prompt=sys_prompt,
            is_arbiter=True,
            cache_override_ttl=None,
        )
        try:
            content, err = await complete_chat_messages(
                self._http_client,
                route=route,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": usr_prompt},
                ],
                temperature=0.0,
                timeout_ms=min(self._settings.chat_response_timeout_ms, 25_000),
                request_id=request_id,
            )
            if err or not (content or "").strip():
                return list(all_agents), 0.0, "router_empty", None
            parsed = _parse_json_object_from_llm(content or "")
            if not parsed:
                return list(all_agents), 0.0, "router_bad_json", None
            ids = parsed.get("selected_agent_ids") or []
            confidence = float(parsed.get("confidence") or 0.0)
            reason = str(parsed.get("reason") or "").strip()
            ordered_raw = self._parse_ordered_agent_ids_field(parsed, confidence=confidence)
            id_set = {a.id for a in all_agents}
            selected_ids = [i for i in ids if isinstance(i, str) and i in id_set]
            selected: list[Agent] = [a for a in all_agents if a.id in selected_ids][:3]
            if confidence < 0.5 or not selected:
                return (
                    list(all_agents),
                    confidence,
                    reason or "low_confidence_fallback",
                    None,
                )
            return selected, confidence, reason, ordered_raw
        except Exception:
            return list(all_agents), 0.0, "router_exception", None

    async def route_and_plan(
        self,
        *,
        user_message: str,
        all_agents: list[Agent],
        request_id: str,
        locked_targets: list[Agent] | None = None,
    ) -> RouterAutoPlan:
        """Router для режима auto: flow off|sequential|debate, 1–5 агентов, 1–3 раунда дискуссии."""

        async def fallback(reason: str) -> RouterAutoPlan:
            ord_from_router: list[str] | None = None
            if locked_targets:
                picked = list(locked_targets)[:_MAX_TARGET_AGENTS]
                conf = 0.0
                rreason = "locked_roster"
            else:
                sel, conf, rreason, ord_from_router = await self.route_question(
                    user_message=user_message,
                    all_agents=all_agents,
                    request_id=request_id,
                )
                picked = sel[:_MAX_TARGET_AGENTS]
            if not picked:
                picked = list(all_agents)[:1]
            tail = f"{reason}; {rreason}".strip("; ")
            return RouterAutoPlan(
                targets=picked,
                resolved_debate_mode="off",
                flow="sequential",
                reason=tail[:500],
                confidence=float(conf or 0.0),
                off_chain_style="sequential",
                ordered_agent_ids=ord_from_router,
            )

        if self._settings.aggregate_mock_providers or self._http_client is None:
            lt = list(locked_targets) if locked_targets else list(all_agents)[:2]
            lt = lt[:_MAX_TARGET_AGENTS] or list(all_agents)[:1]
            return RouterAutoPlan(
                targets=lt,
                resolved_debate_mode="off",
                flow="sequential",
                reason="router_unavailable_mock",
                confidence=0.0,
                off_chain_style="sequential",
                ordered_agent_ids=None,
            )

        roster = "\n".join(
            f"- id={a.id}; name={a.name}; role={a.role}" for a in all_agents
        )
        locked_note = ""
        if locked_targets:
            ids = ", ".join(a.id for a in locked_targets)
            locked_note = (
                f"\nThe user explicitly addressed these agents (@mention). "
                f"You MUST use only these agent ids (in any order in JSON): {ids}. "
                f"Still choose flow and debate_rounds.\n"
            )

        sys_prompt = (
            "You are a discussion planner. Choose how the team should answer.\n"
            '- flow: \"off\" — quick independent replies in parallel (no peeking at colleagues);\n'
            '- flow: \"sequential\" — agents reply one by one, each sees previous answers;\n'
            '- flow: \"debate\" — multi-round structured discussion with synthesis (use for trade-offs, conflicts, architecture choices).\n'
            "If flow is \"debate\", set debate_rounds to integer 3, 4, or 5 "
            "(3=shorter debate, 4=standard depth, 5=deepest when controversy or architecture trade-offs). "
            "Otherwise debate_rounds must be 1.\n"
            "Pick selected_agent_ids: 1–5 ids from the roster (all must exist).\n"
            "Also set ordered_agent_ids: same ids in logical call order "
            "(requirements/analysis → design → implementation → infra), or null if unsure.\n"
            "Return strict JSON: "
            '{"flow":"off"|"sequential"|"debate","debate_rounds":number,'
            '"selected_agent_ids":string[],"ordered_agent_ids":string[]|null,'
            '"confidence":number,"reason":string}. '
            "confidence in [0,1]. Be concise in reason.\n\n"
            f"{_ROUTER_SELECTION_STRATEGY}"
        )
        usr_prompt = (
            f"User query:\n{user_message}\n\nAvailable agents:\n{roster}\n"
            f"{locked_note}\nRespond with JSON only."
        )
        route = RouteEntry(
            route_id="hidden-router-auto-plan",
            provider="openrouter",
            model=_ROUTER_MODEL,
            role="router",
            active=True,
            system_prompt=sys_prompt,
            is_arbiter=True,
            cache_override_ttl=None,
        )
        try:
            content, err = await complete_chat_messages(
                self._http_client,
                route=route,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": usr_prompt},
                ],
                temperature=0.0,
                timeout_ms=min(self._settings.chat_response_timeout_ms, 25_000),
                request_id=request_id,
            )
            if err or not (content or "").strip():
                return await fallback("router_empty")
            parsed = _parse_json_object_from_llm(content or "")
            if not parsed:
                return await fallback("router_bad_json")

            flow_raw = str(parsed.get("flow") or "").strip().lower()
            if flow_raw not in ("off", "sequential", "debate"):
                flow_raw = "sequential"

            rounds = int(parsed.get("debate_rounds") or 3)
            max_router_rounds = min(5, self._settings.chat_debate_max_rounds)
            rounds = max(3, min(max_router_rounds, rounds))

            confidence = float(parsed.get("confidence") or 0.0)
            reason = str(parsed.get("reason") or "").strip()

            id_set = {a.id for a in all_agents}
            ids_in = parsed.get("selected_agent_ids") or []
            selected_ids = [i for i in ids_in if isinstance(i, str) and i in id_set]

            if locked_targets:
                allowed = {a.id for a in locked_targets}
                selected_ids = [i for i in selected_ids if i in allowed]
                if not selected_ids:
                    selected_ids = [a.id for a in locked_targets]

            selected: list[Agent] = [a for a in all_agents if a.id in selected_ids][
                :_MAX_TARGET_AGENTS
            ]

            ordered_raw = self._parse_ordered_agent_ids_field(
                parsed, confidence=confidence
            )

            if not locked_targets:
                if confidence < 0.35 or not selected:
                    return await fallback(reason or "low_confidence")

            if not selected:
                return await fallback(reason or "no_agents")

            if len(selected) == 1 and flow_raw == "debate":
                flow_raw = "sequential"

            if flow_raw == "debate":
                max_r = max(
                    3,
                    min(rounds, self._settings.chat_debate_max_rounds),
                )
                debate_mode = _DEBATE_ROUND_COUNT_TO_MODE.get(
                    max_r,
                    "deep"
                    if max_r >= 5
                    else ("standard" if max_r >= 4 else "fast"),
                )
                return RouterAutoPlan(
                    targets=selected,
                    resolved_debate_mode=debate_mode,
                    flow="debate",
                    reason=reason or "debate",
                    confidence=confidence,
                    off_chain_style=None,
                    ordered_agent_ids=ordered_raw,
                )

            off_style = "parallel" if flow_raw == "off" else "sequential"
            return RouterAutoPlan(
                targets=selected,
                resolved_debate_mode="off",
                flow=flow_raw,
                reason=reason or flow_raw,
                confidence=confidence,
                off_chain_style=off_style,
                ordered_agent_ids=ordered_raw,
            )
        except Exception:
            return await fallback("router_exception")

    async def _save_debate_turn(
        self,
        *,
        thread_id: str,
        round_id: str,
        agent_id: str,
        turn_order: int,
        content: str | None,
        error: str | None,
    ) -> DebateTurn:
        turn = DebateTurn(
            id=str(uuid.uuid4()),
            thread_id=thread_id,
            round_id=round_id,
            agent_id=agent_id,
            turn_order=turn_order,
            content=content or "",
            error=error,
            created_at=datetime.now(UTC),
        )
        self._session.add(turn)
        await self._session.commit()
        await self._session.refresh(turn)
        return turn

    async def _run_multi_round_debate(
        self,
        *,
        project: Project,
        user_message_id: str,
        user_content: str,
        targets: list[Agent],
        all_agents: list[Agent],
        files: list[ProjectFile],
        history: list[ChatMessage],
        temperature: float,
        request_id: str,
        thread: DebateThread,
        is_discussion: bool,
        locale: str,
        market_context: dict[str, Any] | None = None,
    ) -> None:
        agents_by_id = {a.id: a for a in all_agents}
        all_successful_turns: list[tuple[Agent, str]] = []
        errors_count = 0
        timed_out = False

        for round_num in range(1, thread.total_rounds + 1):
            fresh_thread = await self._reload_debate_thread(thread.id)
            if fresh_thread is None:
                return
            thread = fresh_thread
            if thread.status == "cancelled":
                return
            if _is_deadline_exceeded(thread.timeout_at):
                timed_out = True
                break

            status_updated = await self._set_debate_status(
                thread,
                status="agents_discussing",
                current_round=round_num,
            )
            if not status_updated:
                return
            round_row = DebateRound(
                id=str(uuid.uuid4()),
                thread_id=thread.id,
                round_number=round_num,
                status="running",
                started_at=datetime.now(UTC),
            )
            self._session.add(round_row)
            await self._session.commit()
            await self._session.refresh(round_row)

            round_turns: list[tuple[Agent, str]] = []
            for order, agent in enumerate(targets, start=1):
                fresh_thread = await self._reload_debate_thread(thread.id)
                if fresh_thread is None:
                    return
                thread = fresh_thread
                if thread.status == "cancelled":
                    round_row.status = "cancelled"
                    round_row.finished_at = datetime.now(UTC)
                    round_row.round_summary = (
                        f"Раунд {round_num}: отменён пользователем"
                    )
                    await self._session.commit()
                    return
                if _is_deadline_exceeded(thread.timeout_at):
                    timed_out = True
                    break
                previous_responses = all_successful_turns + round_turns
                turn = await self._agent_turn(
                    agent=agent,
                    project=project,
                    files=files,
                    history=history,
                    agents_by_id=agents_by_id,
                    team_agents=all_agents,
                    user_message_text=user_content,
                    previous_responses=previous_responses,
                    temperature=temperature,
                    request_id=request_id,
                    debate_round=round_num,
                    debate_total_rounds=thread.total_rounds,
                    debate_locale=locale,
                    market_context=market_context,
                )
                fresh_thread = await self._reload_debate_thread(thread.id)
                if fresh_thread is None:
                    return
                thread = fresh_thread
                if thread.status == "cancelled":
                    round_row.status = "cancelled"
                    round_row.finished_at = datetime.now(UTC)
                    round_row.round_summary = (
                        f"Раунд {round_num}: отменён пользователем"
                    )
                    await self._session.commit()
                    return
                await self._save_debate_turn(
                    thread_id=thread.id,
                    round_id=round_row.id,
                    agent_id=agent.id,
                    turn_order=order,
                    content=turn.content,
                    error=turn.error,
                )
                if turn.content:
                    round_turns.append((agent, turn.content))
                else:
                    errors_count += 1
                if turn.error:
                    errors_count += 1

            round_row.status = "completed"
            round_row.finished_at = datetime.now(UTC)
            round_row.round_summary = (
                f"Раунд {round_num}: успешных реплик {len(round_turns)}/{len(targets)}"
            )
            await self._session.commit()
            all_successful_turns.extend(round_turns)

            if timed_out:
                break

        fresh_thread = await self._reload_debate_thread(thread.id)
        if fresh_thread is None:
            return
        thread = fresh_thread
        if thread.status == "cancelled":
            return

        status_updated = await self._set_debate_status(thread, status="synthesizing")
        if not status_updated:
            return
        fresh_thread = await self._reload_debate_thread(thread.id)
        if fresh_thread is None:
            return
        thread = fresh_thread
        if thread.status == "cancelled":
            return
        final_text, confidence, disagreements = _build_debate_final_text(
            user_message=user_content,
            turns=all_successful_turns,
            errors_count=errors_count,
            timed_out=timed_out,
            locale=locale,
        )
        synthesized = await self._synthesize_debate_with_hidden_agent(
            user_message=user_content,
            turns=all_successful_turns,
            errors_count=errors_count,
            timed_out=timed_out,
            locale=locale,
            request_id=request_id,
        )
        if synthesized is not None:
            final_text, confidence, disagreements = synthesized
        fresh_thread = await self._reload_debate_thread(thread.id)
        if fresh_thread is None:
            return
        thread = fresh_thread
        if thread.status == "cancelled":
            return
        final_msg = await self._save_agent_message(
            project_id=project.id,
            agent=None,
            content=final_text,
            error=None if not timed_out else "debate_timed_out",
            is_discussion=is_discussion,
            parent_id=user_message_id,
        )
        final_status = "timed_out" if timed_out else "completed"
        await self._set_debate_status(
            thread,
            status=final_status,
            final_summary=final_text,
            confidence=confidence,
            disagreements=disagreements,
            final_message_id=final_msg.id,
            finished=True,
        )

    async def _synthesize_debate_with_hidden_agent(
        self,
        *,
        user_message: str,
        turns: list[tuple[Agent, str]],
        errors_count: int,
        timed_out: bool,
        locale: str,
        request_id: str,
    ) -> tuple[str, str, str] | None:
        """Собрать финал через скрытого синтезирующего агента."""
        if self._settings.aggregate_mock_providers or self._http_client is None:
            return None

        is_ru = locale == "ru"
        turns_block_lines: list[str] = []
        for i, (agent, content) in enumerate(turns, start=1):
            turns_block_lines.append(
                f"{i}. {agent.name} ({agent.role}): {_safe_excerpt(content, limit=420)}"
            )
        turns_block = "\n".join(turns_block_lines) or (
            "(нет успешных реплик)" if is_ru else "(no successful turns)"
        )

        if is_ru:
            system_prompt = (
                "Ты скрытый агент-синтезатор командной дискуссии. "
                "Верни только итог в СТРОГОМ формате ниже, без префиксов и комментариев. "
                "Блок 'Ключевые аргументы' должен быть краткой выжимкой (4-6 пунктов), "
                "без приветствий и воды.\n"
                f"{_SYNTHESIZER_BRIEF_RULES}"
            )
            user_prompt = (
                "Синтезируй обсуждение.\n\n"
                f"Запрос пользователя:\n{user_message}\n\n"
                f"Реплики агентов:\n{turns_block}\n\n"
                f"Ошибок/пустых реплик: {errors_count}\n"
                f"Таймаут: {'да' if timed_out else 'нет'}\n\n"
                "Формат ответа:\n"
                "✅ Итог / Консенсус:\n"
                "<1-3 предложения>\n\n"
                "🧩 Ключевые аргументы:\n"
                "- <краткий тезис 1>\n"
                "- <краткий тезис 2>\n"
                "- ...\n\n"
                "⚠️ Открытые вопросы / Разногласия:\n"
                "- <если есть>\n\n"
                "📈 Уровень уверенности: низкий|средний|высокий\n"
                "🔍 Раскрыть детали дискуссии: используйте журнал дискуссии в интерфейсе проекта."
            )
        else:
            system_prompt = (
                "You are a hidden synthesis agent for a team discussion. "
                "Return only the final output in the EXACT template below, no extra commentary. "
                "Keep 'Key arguments' concise (4-6 bullets), no greetings or filler.\n"
                "Summarize in 3-5 key points: decision, pros, cons, open questions; "
                "if there are many opinions, explicitly mark consensus and disagreements."
            )
            user_prompt = (
                "Synthesize the discussion.\n\n"
                f"User request:\n{user_message}\n\n"
                f"Agent turns:\n{turns_block}\n\n"
                f"Errors/empty turns: {errors_count}\n"
                f"Timed out: {'yes' if timed_out else 'no'}\n\n"
                "Response template:\n"
                "✅ Consensus:\n"
                "<1-3 sentences>\n\n"
                "🧩 Key arguments:\n"
                "- <concise thesis 1>\n"
                "- <concise thesis 2>\n"
                "- ...\n\n"
                "⚠️ Open questions / disagreements:\n"
                "- <if any>\n\n"
                "📈 Confidence level: low|medium|high\n"
                "🔍 Show discussion details in the project debate log."
            )

        route = RouteEntry(
            route_id="hidden-debate-synthesizer",
            provider="openrouter",
            model=_SYNTHESIZER_MODEL,
            role="synthesizer",
            active=True,
            system_prompt=system_prompt,
            is_arbiter=True,
            cache_override_ttl=None,
        )
        try:
            content, err = await complete_chat_messages(
                self._http_client,
                route=route,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                timeout_ms=min(self._settings.chat_response_timeout_ms, 45_000),
                request_id=request_id,
            )
        except Exception:
            return None
        if err or not (content or "").strip():
            return None

        text = content.strip()
        if is_ru:
            confidence = (
                _extract_between(text, "📈 Уровень уверенности:", ["\n"]).lower() or "средний"
            )
            disagreements = _extract_between(
                text,
                "⚠️ Открытые вопросы / Разногласия:",
                ["📈 Уровень уверенности:", "🔍"],
            )
        else:
            confidence = (
                _extract_between(text, "📈 Confidence level:", ["\n"]).lower() or "medium"
            )
            disagreements = _extract_between(
                text,
                "⚠️ Open questions / disagreements:",
                ["📈 Confidence level:", "🔍"],
            )
        return text, confidence, disagreements

    async def cancel_debate_thread(
        self,
        *,
        project_id: str,
        thread_id: str,
    ) -> DebateThread:
        thread = await self.get_debate_thread(project_id=project_id, thread_id=thread_id)
        if thread.status in ("completed", "timed_out", "failed", "cancelled"):
            return thread

        thread_locale = (thread.meta or {}).get("locale") if isinstance(thread.meta, dict) else None
        locale = thread_locale if thread_locale in ("en", "ru") else "en"
        cancelled_text = (
            "Дискуссия отменена пользователем."
            if locale == "ru"
            else "Discussion was cancelled by the user."
        )
        cancel_message = await self._save_agent_message(
            project_id=project_id,
            agent=None,
            content=cancelled_text,
            error=None,
            is_discussion=True,
            parent_id=thread.user_message_id,
        )
        await self._set_debate_status(
            thread,
            status="cancelled",
            disagreements=cancelled_text,
            final_message_id=cancel_message.id,
            finished=True,
        )
        return thread

    def _validate_risk_manager_response(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        return _RISK_MANAGER_BLOCK_RE.search(text) is None

    async def _auto_fix_risk_response(
        self, agent: Agent, original_prompt: list[dict[str, Any]], current_text: str
    ) -> str:
        if self._http_client is None:
            return current_text
        route = _resolve_route_for_agent(agent)
        corrective = (
            "ВНИМАНИЕ: Ты нарушил формат. Вердикт направления запрещён.\n"
            "Верни ответ СТРОГО по шаблону:\n"
            "Вход: [цена] | Стоп: [цена] | Тейк: [цена] | R:R: [число] | Позиция: [%] | ATR: [число] | Триггер отмены: [условие]\n"
            "Никаких слов 'бычий/медвежий', никаких прогнозов."
        )
        prompt_tail = ""
        if original_prompt:
            prompt_tail = str(original_prompt[-1].get("content") or "")[:1200]
        content, err = await complete_chat_messages(
            self._http_client,
            route=route,
            messages=[
                {"role": "system", "content": str(route.system_prompt or "")},
                {
                    "role": "user",
                    "content": (
                        f"{corrective}\n\n"
                        f"Исходный запрос:\n{prompt_tail}\n\n"
                        f"Текущий (некорректный) ответ:\n{current_text}"
                    ),
                },
            ],
            temperature=0.0,
            timeout_ms=min(self._settings.chat_response_timeout_ms, 20_000),
            request_id=str(uuid.uuid4()),
        )
        if err or not (content or "").strip():
            return current_text
        return content or current_text

    async def _agent_turn(
        self,
        *,
        agent: Agent,
        project: Project,
        files: list[ProjectFile],
        history: list[ChatMessage],
        agents_by_id: dict[str, Agent],
        team_agents: list[Agent],
        user_message_text: str,
        previous_responses: list[tuple[Agent, str]],
        temperature: float,
        request_id: str,
        debate_round: int | None = None,
        debate_total_rounds: int | None = None,
        debate_locale: str | None = None,
        market_context: dict[str, Any] | None = None,
    ) -> _AgentTurnResult:
        if agent.role in _CRYPTO_AGENT_ROLES:
            _st = compute_data_freshness_status(market_context)
            _ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            logger.info("Context for %s: freshness=%s, time=%s", agent.role, _st, _ts)
        if agent.role in _CRYPTO_FAIL_LOUD_ROLES and _crypto_live_data_blocked(
            market_context, agent_role=agent.role
        ):
            return _AgentTurnResult(agent=agent, content=_CRYPTO_PASS_NO_DATA, error=None)

        if self._settings.aggregate_mock_providers or self._http_client is None:
            content = _mock_agent_reply(
                agent=agent,
                user_message=user_message_text,
                previous_responses=previous_responses,
            )
            return _AgentTurnResult(agent=agent, content=content, error=None)

        async with self._session_lock:
            attach_text, attach_images = await self._prepare_attachments_for_agent_turn(
                project_id=project.id,
                project_files=files,
                agent=agent,
                request_id=request_id,
            )
            model_id = (agent.model or "").strip() or _DEFAULT_OPENROUTER_MODEL
            include_images = attach_images if _model_supports_images(model_id) else []
            if attach_images and not include_images:
                log_payload(
                    logger,
                    logging.INFO,
                    "chat_attachments_images_skipped",
                    request_id=request_id,
                    project_id=project.id,
                    agent_id=agent.id,
                    model=model_id,
                    skipped_images=len(attach_images),
                )

            messages = build_agent_prompt(
                agent=agent,
                project=project,
                files=files,
                history=history,
                agents_by_id=agents_by_id,
                team_agents=team_agents,
                user_message=user_message_text,
                previous_responses=previous_responses,
                file_attachments_text=attach_text,
                file_attachments_images=include_images,
                debate_round=debate_round,
                debate_total_rounds=debate_total_rounds,
                debate_locale=debate_locale,
                market_context_markdown=format_live_context_markdown(market_context)
                if market_context
                else None,
            )
        route = _resolve_route_for_agent(agent)
        try:
            content, err = await complete_chat_messages(
                self._http_client,
                route=route,
                messages=messages,
                temperature=temperature,
                timeout_ms=self._settings.chat_response_timeout_ms,
                request_id=request_id,
            )
        except Exception as e:
            return _AgentTurnResult(
                agent=agent,
                content=None,
                error=f"orchestrator error: {type(e).__name__}",
            )
        if (
            self._settings.chat_risk_guard_enabled
            and agent.role == "risk_manager"
            and content
            and not self._validate_risk_manager_response(content)
        ):
            fixed = await self._auto_fix_risk_response(agent, messages, content)
            if self._validate_risk_manager_response(fixed):
                logger.info("Risk Manager auto-corrected")
                content = fixed
            else:
                logger.warning("Risk Manager validation failed, using fallback")
                log_payload(
                    logger,
                    logging.WARNING,
                    "agent_validation_failed",
                    request_id=request_id,
                    project_id=project.id,
                    agent_id=agent.id,
                    agent_role=agent.role,
                )
                content = _RISK_MANAGER_FALLBACK_TEXT
                err = None
        return _AgentTurnResult(agent=agent, content=content, error=err)

    async def iter_agent_completion_chunks(
        self,
        *,
        agent: Agent,
        project: Project,
        files: list[ProjectFile],
        history: list[ChatMessage],
        agents_by_id: dict[str, Agent],
        team_agents: list[Agent],
        user_message_text: str,
        previous_responses: list[tuple[Agent, str]],
        temperature: float,
        request_id: str,
        debate_round: int | None = None,
        debate_total_rounds: int | None = None,
        debate_locale: str | None = None,
        market_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Дельты текста из OpenRouter stream=True (yield сразу по приходу SSE)."""
        if agent.role in _CRYPTO_AGENT_ROLES:
            _st = compute_data_freshness_status(market_context)
            _ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            logger.info("Context for %s: freshness=%s, time=%s", agent.role, _st, _ts)
        if agent.role in _CRYPTO_FAIL_LOUD_ROLES and _crypto_live_data_blocked(
            market_context, agent_role=agent.role
        ):
            yield _CRYPTO_PASS_NO_DATA
            return

        if self._settings.aggregate_mock_providers or self._http_client is None:
            content = _mock_agent_reply(
                agent=agent,
                user_message=user_message_text,
                previous_responses=previous_responses,
            )
            if content:
                yield content
            return

        async with self._session_lock:
            attach_text, attach_images = await self._prepare_attachments_for_agent_turn(
                project_id=project.id,
                project_files=files,
                agent=agent,
                request_id=request_id,
            )
            model_id = (agent.model or "").strip() or _DEFAULT_OPENROUTER_MODEL
            include_images = attach_images if _model_supports_images(model_id) else []
            messages = build_agent_prompt(
                agent=agent,
                project=project,
                files=files,
                history=history,
                agents_by_id=agents_by_id,
                team_agents=team_agents,
                user_message=user_message_text,
                previous_responses=previous_responses,
                file_attachments_text=attach_text,
                file_attachments_images=include_images,
                debate_round=debate_round,
                debate_total_rounds=debate_total_rounds,
                debate_locale=debate_locale,
                market_context_markdown=format_live_context_markdown(market_context)
                if market_context
                else None,
            )

        async def _iter_stream_for_model(model_to_use: str) -> AsyncIterator[str]:
            payload: dict[str, Any] = {
                "model": model_to_use,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }
            assert self._http_client is not None
            timeout_s = max(self._settings.chat_response_timeout_ms, 1) / 1000.0
            async with self._http_client.stream(
                "POST",
                _openrouter_chat_url(),
                headers=_openrouter_headers(),
                json=payload,
                timeout=httpx.Timeout(timeout_s),
            ) as resp:
                if resp.status_code < 200 or resp.status_code >= 300:
                    raw = (await resp.aread()).decode("utf-8", errors="ignore")
                    detail = _safe_excerpt(raw, limit=240) or "no_error_body"
                    raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_part = line[5:].strip()
                    if data_part == "[DONE]":
                        break
                    try:
                        evt = json.loads(data_part)
                    except json.JSONDecodeError:
                        continue
                    choices = evt.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first = choices[0] if isinstance(choices[0], dict) else {}
                    delta = first.get("delta") if isinstance(first, dict) else {}
                    content_piece = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(content_piece, str) and content_piece:
                        yield content_piece

        try:
            async for piece in _iter_stream_for_model(model_id):
                yield piece
        except Exception as e:
            # Для отказов конкретной модели (402/404/400) делаем один fallback на стабильную default.
            should_fallback = model_id != _DEFAULT_OPENROUTER_MODEL
            if not should_fallback:
                raise
            log_payload(
                logger,
                logging.WARNING,
                "chat_stream_model_fallback",
                request_id=request_id,
                project_id=project.id,
                agent_id=agent.id,
                model_primary=model_id,
                model_fallback=_DEFAULT_OPENROUTER_MODEL,
                error=str(e),
            )
            async for piece in _iter_stream_for_model(_DEFAULT_OPENROUTER_MODEL):
                yield piece

    async def stream_chat_replies(
        self,
        *,
        project_id: str,
        user_message_id: str,
        user_content: str,
        target_agent_ids: list[str],
        is_discussion: bool,
        temperature: float,
        request_id: str,
        debate_mode: str = "off",
        debate_thread_id: str | None = None,
        locale: str | None = None,
        market_asset: str | None = None,
        market_timeframe: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE-friendly поток событий генерации (token/agent_done/complete)."""
        project = await self._load_project(project_id)
        rows = (
            await self._session.execute(select(Agent).where(Agent.id.in_(target_agent_ids)))
        ).scalars().all()
        by_id = {a.id: a for a in rows}
        targets = [by_id[i] for i in target_agent_ids if i in by_id]
        if not targets:
            yield {"type": "complete"}
            return

        all_agents = await self._load_project_agents(project_id)
        history = await self._load_recent_history(project.id, limit=self._settings.chat_history_limit)
        files = await self._load_files(project.id)
        agents_by_id = {a.id: a for a in all_agents}
        resolved_locale = (locale or "en").strip().lower()
        if resolved_locale not in ("en", "ru"):
            resolved_locale = "en"
        previous_responses: list[tuple[Agent, str]] = []
        targets_need_crypto = any(a.role in _CRYPTO_AGENT_ROLES for a in targets)
        eff_asset, eff_tf = resolve_market_params_for_chat(
            user_content,
            explicit_asset=market_asset,
            explicit_timeframe=market_timeframe,
            targets_include_crypto_agent=targets_need_crypto,
        )
        market_context = await self._resolve_market_context(
            asset=eff_asset,
            timeframe=eff_tf,
            request_id=request_id,
        )

        async def run_turn(
            *, agent: Agent, round_num: int | None = None, total_rounds: int | None = None
        ) -> AsyncIterator[dict[str, Any]]:
            parts: list[str] = []
            stream_err: str | None = None
            stream_risk_buffer = (
                self._settings.chat_risk_guard_enabled and agent.role == "risk_manager"
            )
            try:
                async for piece in self.iter_agent_completion_chunks(
                    agent=agent,
                    project=project,
                    files=files,
                    history=history,
                    agents_by_id=agents_by_id,
                    team_agents=all_agents,
                    user_message_text=user_content,
                    previous_responses=previous_responses,
                    temperature=temperature,
                    request_id=request_id,
                    debate_round=round_num,
                    debate_total_rounds=total_rounds,
                    debate_locale=resolved_locale,
                    market_context=market_context,
                ):
                    parts.append(piece)
                    if not stream_risk_buffer:
                        yield {"type": "token", "agent_id": agent.id, "content": piece}
                    await asyncio.sleep(0)
            except Exception as e:
                stream_err = f"stream_error: {type(e).__name__}"

            full_text = "".join(parts)
            if (
                stream_risk_buffer
                and full_text
                and not self._validate_risk_manager_response(full_text)
            ):
                fixed = await self._auto_fix_risk_response(agent, [], full_text)
                if self._validate_risk_manager_response(fixed):
                    logger.info("Risk Manager auto-corrected")
                    full_text = fixed
                else:
                    logger.warning("Risk Manager validation failed, using fallback")
                    log_payload(
                        logger,
                        logging.WARNING,
                        "agent_validation_failed",
                        request_id=request_id,
                        project_id=project.id,
                        agent_id=agent.id,
                        agent_role=agent.role,
                    )
                    full_text = _RISK_MANAGER_FALLBACK_TEXT
            if stream_risk_buffer and full_text.strip():
                yield {"type": "token", "agent_id": agent.id, "content": full_text}
            if stream_err and full_text.strip():
                full_text = f"{full_text}\n\n[stream interrupted: {stream_err}]"
            saved = await self._save_agent_message(
                project_id=project.id,
                agent=agent,
                content=full_text.strip() or None,
                error=stream_err,
                is_discussion=is_discussion,
                parent_id=user_message_id,
            )
            history.append(saved)
            if saved.content:
                previous_responses.append((agent, saved.content))
                await self._maybe_record_paper_trade(
                    project_id=project.id,
                    agent=agent,
                    content=saved.content,
                    market_asset=eff_asset,
                    market_timeframe=eff_tf,
                    market_context=market_context,
                )
            yield {"type": "agent_done", "agent_id": agent.id, "error": stream_err}

        if debate_mode != "off" and debate_thread_id:
            rounds = max(1, _DEBATE_ROUNDS_BY_MODE.get(debate_mode, 0))
            thread = await self._session.get(DebateThread, debate_thread_id)
            for round_num in range(1, rounds + 1):
                if thread is not None:
                    await self._set_debate_status(thread, status="agents_discussing", current_round=round_num)
                yield {"type": "round_start", "round": round_num, "total_rounds": rounds}
                for agent in targets:
                    async for ev in run_turn(agent=agent, round_num=round_num, total_rounds=rounds):
                        yield ev
            if thread is not None:
                await self._set_debate_status(thread, status="synthesizing")
                synth = await self._synthesize_debate_with_hidden_agent(
                    user_message=user_content,
                    turns=previous_responses,
                    errors_count=0,
                    timed_out=False,
                    request_id=request_id,
                    locale=resolved_locale,
                )
                if synth is not None:
                    text, confidence, disagreements = synth
                    saved = await self._save_agent_message(
                        project_id=project.id,
                        agent=None,
                        content=text,
                        error=None,
                        is_discussion=True,
                        parent_id=user_message_id,
                    )
                    await self._set_debate_status(
                        thread,
                        status="completed",
                        final_summary=text,
                        confidence=confidence,
                        disagreements=disagreements,
                        final_message_id=saved.id,
                        finished=True,
                    )
        else:
            for agent in targets[:_MAX_TARGET_AGENTS]:
                async for ev in run_turn(agent=agent):
                    yield ev

        yield {"type": "complete"}

    async def process_user_message(
        self,
        *,
        project_id: str,
        user_message: str,
        explicit_agent_ids: list[str] | None = None,
        force_discussion: bool | None = None,
        temperature: float | None = None,
    ) -> tuple[ChatMessage, list[ChatMessage], bool]:
        request_id = str(uuid.uuid4())
        project = await self._load_project(project_id)
        all_agents = await self._load_project_agents(project_id)

        if not all_agents:
            raise LookupError("Project has no active agents")

        targets = self._select_targets(
            all_agents=all_agents,
            explicit_ids=explicit_agent_ids,
            text=user_message,
        )
        targets = self._enforce_crypto_interpreter_last(
            targets,
            all_agents=all_agents,
        )
        if not targets:
            raise LookupError("No matching agents for this message")

        is_discussion = (
            force_discussion if force_discussion is not None else len(targets) >= 2
        )

        user_msg = await self._save_user_message(
            project_id=project.id,
            content=user_message,
            is_discussion=is_discussion,
        )

        history = await self._load_recent_history(
            project.id, limit=self._settings.chat_history_limit
        )
        files = await self._load_files(project.id)
        agents_by_id = {a.id: a for a in all_agents}

        temp = (
            temperature
            if temperature is not None
            else self._settings.chat_default_temperature
        )

        previous_responses: list[tuple[Agent, str]] = []
        agent_messages: list[ChatMessage] = []

        log_payload(
            logger,
            logging.INFO,
            "chat_orchestration_started",
            request_id=request_id,
            project_id=project.id,
            targets=len(targets),
            is_discussion=is_discussion,
            mock=self._settings.aggregate_mock_providers,
        )

        for agent in targets:
            turn = await self._agent_turn(
                agent=agent,
                project=project,
                files=files,
                history=history,
                agents_by_id=agents_by_id,
                team_agents=all_agents,
                user_message_text=user_message,
                previous_responses=previous_responses,
                temperature=temp,
                request_id=request_id,
            )
            if _is_pass_response(turn.content):
                continue
            saved = await self._save_agent_message(
                project_id=project.id,
                agent=agent,
                content=turn.content,
                error=turn.error,
                is_discussion=is_discussion,
                parent_id=user_msg.id,
            )
            agent_messages.append(saved)
            if turn.content:
                previous_responses.append((agent, turn.content))
                history.append(saved)

            log_payload(
                logger,
                logging.INFO,
                "chat_agent_turn",
                request_id=request_id,
                project_id=project.id,
                agent_id=agent.id,
                agent_role=agent.role,
                ok=turn.error is None,
                error=turn.error,
            )

        log_payload(
            logger,
            logging.INFO,
            "chat_orchestration_finished",
            request_id=request_id,
            project_id=project.id,
            replies=len(agent_messages),
            is_discussion=is_discussion,
        )
        return user_msg, agent_messages, is_discussion

    async def run_sequential_discussion(
        self,
        *,
        project: Project,
        user_message_id: str,
        user_content: str,
        targets: list[Agent],
        all_agents: list[Agent],
        files: list[ProjectFile],
        history: list[ChatMessage],
        temperature: float,
        request_id: str,
        is_discussion: bool,
        market_context: dict[str, Any] | None = None,
        market_asset: str | None = None,
        market_timeframe: str | None = None,
    ) -> tuple[int, list[str]]:
        """Ответы агентов: цепочка с видимостью предыдущих реплик; Risk Manager — параллельно остальным."""
        agents_by_id = {a.id: a for a in all_agents}
        ordered = list(targets)[:_MAX_TARGET_AGENTS]
        response_order = [a.id for a in ordered]
        deadline = datetime.now(UTC) + timedelta(
            milliseconds=min(self._settings.chat_response_timeout_ms * 4, 120_000)
        )
        non_risk = [a for a in ordered if a.role != "risk_manager"]
        risk_only = [a for a in ordered if a.role == "risk_manager"]

        async def _one_turn(
            *,
            agent: Agent,
            prev_chain: list[tuple[Agent, str]],
            per_agent_timeout_s: float,
        ) -> _AgentTurnResult:
            try:
                return await asyncio.wait_for(
                    self._agent_turn(
                        agent=agent,
                        project=project,
                        files=files,
                        history=history,
                        agents_by_id=agents_by_id,
                        team_agents=all_agents,
                        user_message_text=user_content,
                        previous_responses=prev_chain,
                        temperature=temperature,
                        request_id=request_id,
                        market_context=market_context,
                    ),
                    timeout=per_agent_timeout_s,
                )
            except TimeoutError:
                return _AgentTurnResult(
                    agent=agent,
                    content=None,
                    error="sequential_timeout",
                )

        async def _persist_turn(turn: _AgentTurnResult) -> ChatMessage | None:
            if _is_pass_response(turn.content):
                return None
            saved = await self._save_agent_message(
                project_id=project.id,
                agent=turn.agent,
                content=turn.content,
                error=turn.error,
                is_discussion=is_discussion,
                parent_id=user_message_id,
            )
            if turn.content:
                await self._maybe_record_paper_trade(
                    project_id=project.id,
                    agent=turn.agent,
                    content=turn.content,
                    market_asset=market_asset,
                    market_timeframe=market_timeframe,
                    market_context=market_context,
                )
            log_payload(
                logger,
                logging.INFO,
                "chat_agent_turn",
                request_id=request_id,
                project_id=project.id,
                agent_id=turn.agent.id,
                agent_role=turn.agent.role,
                ok=turn.error is None,
                error=turn.error,
            )
            return saved

        if not risk_only:
            previous_responses: list[tuple[Agent, str]] = []
            saved_count = 0
            pass_turns: list[_AgentTurnResult] = []

            for agent in ordered:
                now = datetime.now(UTC)
                if now >= deadline:
                    break
                remaining_s = max(1.0, (deadline - now).total_seconds())
                per_agent_timeout_s = min(
                    remaining_s,
                    max(8.0, min(25.0, self._settings.chat_response_timeout_ms / 1000)),
                )
                turn = await _one_turn(
                    agent=agent,
                    prev_chain=previous_responses,
                    per_agent_timeout_s=per_agent_timeout_s,
                )
                if _is_pass_response(turn.content):
                    pass_turns.append(turn)
                    continue
                saved = await _persist_turn(turn)
                if saved is not None:
                    saved_count += 1
                    previous_responses.append((agent, turn.content or ""))
                    history.append(saved)

            if saved_count == 0 and pass_turns:
                first = pass_turns[0]
                await self._save_agent_message(
                    project_id=project.id,
                    agent=first.agent,
                    content=first.content,
                    error=first.error,
                    is_discussion=is_discussion,
                    parent_id=user_message_id,
                )
                saved_count = 1

            return saved_count, response_order

        previous_responses_nr: list[tuple[Agent, str]] = []
        pass_turns: list[_AgentTurnResult] = []
        saved_nr = 0
        saved_rm = 0

        async def non_risk_worker() -> None:
            nonlocal saved_nr
            for agent in non_risk:
                now = datetime.now(UTC)
                if now >= deadline:
                    break
                remaining_s = max(1.0, (deadline - now).total_seconds())
                per_agent_timeout_s = min(
                    remaining_s,
                    max(8.0, min(25.0, self._settings.chat_response_timeout_ms / 1000)),
                )
                turn = await _one_turn(
                    agent=agent,
                    prev_chain=previous_responses_nr,
                    per_agent_timeout_s=per_agent_timeout_s,
                )
                if _is_pass_response(turn.content):
                    pass_turns.append(turn)
                    continue
                saved = await _persist_turn(turn)
                if saved is not None:
                    saved_nr += 1
                    previous_responses_nr.append((agent, turn.content or ""))
                    history.append(saved)

        async def risk_worker() -> None:
            nonlocal saved_rm
            for agent in risk_only:
                now = datetime.now(UTC)
                if now >= deadline:
                    break
                remaining_s = max(1.0, (deadline - now).total_seconds())
                per_agent_timeout_s = min(
                    remaining_s,
                    max(8.0, min(25.0, self._settings.chat_response_timeout_ms / 1000)),
                )
                turn = await _one_turn(
                    agent=agent,
                    prev_chain=[],
                    per_agent_timeout_s=per_agent_timeout_s,
                )
                if _is_pass_response(turn.content):
                    pass_turns.append(turn)
                    continue
                saved = await _persist_turn(turn)
                if saved is not None:
                    saved_rm += 1
                    history.append(saved)

        await asyncio.gather(non_risk_worker(), risk_worker())

        saved_count = saved_nr + saved_rm
        if saved_count == 0 and pass_turns:
            first = pass_turns[0]
            await self._save_agent_message(
                project_id=project.id,
                agent=first.agent,
                content=first.content,
                error=first.error,
                is_discussion=is_discussion,
                parent_id=user_message_id,
            )
            saved_count = 1

        return saved_count, response_order

    async def prepare_user_message(
        self,
        *,
        project_id: str,
        user_message: str,
        explicit_agent_ids: list[str] | None = None,
        force_discussion: bool | None = None,
        temperature: float | None = None,
        debate_mode: str | None = None,
        locale: str | None = None,
        file_ids: list[str] | None = None,
        market_asset: str | None = None,
        market_timeframe: str | None = None,
    ) -> PrepareChatOutcome:
        """Сохранить сообщение пользователя и вернуть очередь agent.id без вызова моделей."""
        project = await self._load_project(project_id)
        all_agents = await self._load_project_agents(project_id)

        if not all_agents:
            raise LookupError("Project has no active agents")

        client_mode = (debate_mode or "off").strip().lower()
        if client_mode not in _REQUEST_DEBATE_MODES:
            client_mode = "off"

        router_selected_ids: list[str] | None = None
        router_ordered_ids: list[str] | None = None
        router_order_confidence = 0.0
        router_reason: str | None = None
        router_flow: str | None = None
        off_chain_style: str | None = None
        pipeline_mode = client_mode

        mentioned = _resolve_mentioned(all_agents, user_message)
        locked_targets: list[Agent] | None = None
        if explicit_agent_ids:
            id_order = list(dict.fromkeys([x for x in explicit_agent_ids if x]))
            by_id = {a.id: a for a in all_agents}
            targets = [by_id[i] for i in id_order if i in by_id]
            locked_targets = targets if targets else None
        elif mentioned:
            targets = mentioned
            locked_targets = targets
        elif client_mode == "auto":
            plan = await self.route_and_plan(
                user_message=user_message,
                all_agents=all_agents,
                request_id=str(uuid.uuid4()),
                locked_targets=None,
            )
            targets = plan.targets
            router_reason = plan.reason
            router_flow = plan.flow
            off_chain_style = plan.off_chain_style
            router_selected_ids = [a.id for a in targets]
            router_ordered_ids = plan.ordered_agent_ids
            router_order_confidence = plan.confidence
            pipeline_mode = plan.resolved_debate_mode
            log_payload(
                logger,
                logging.INFO,
                "chat_auto_plan",
                project_id=project.id,
                flow=plan.flow,
                debate_mode=plan.resolved_debate_mode,
                agents=len(targets),
                confidence=plan.confidence,
            )
        elif client_mode == "off":
            selected, confidence, reason, od = await self.route_question(
                user_message=user_message,
                all_agents=all_agents,
                request_id=str(uuid.uuid4()),
            )
            targets = selected
            router_selected_ids = [a.id for a in selected]
            router_ordered_ids = od
            router_order_confidence = confidence
            pipeline_mode = "off"
            log_payload(
                logger,
                logging.INFO,
                "chat_router_selected_agents",
                project_id=project.id,
                selected=len(router_selected_ids),
                confidence=confidence,
                reason=reason,
            )
        else:
            targets = list(all_agents)

        if locked_targets is not None and client_mode == "auto":
            plan = await self.route_and_plan(
                user_message=user_message,
                all_agents=all_agents,
                request_id=str(uuid.uuid4()),
                locked_targets=locked_targets,
            )
            router_reason = plan.reason
            router_flow = plan.flow
            off_chain_style = plan.off_chain_style
            router_selected_ids = [a.id for a in locked_targets]
            targets = list(locked_targets)
            router_ordered_ids = plan.ordered_agent_ids
            router_order_confidence = plan.confidence
            pipeline_mode = plan.resolved_debate_mode
            log_payload(
                logger,
                logging.INFO,
                "chat_auto_plan_locked",
                project_id=project.id,
                flow=plan.flow,
                debate_mode=plan.resolved_debate_mode,
                agents=len(targets),
            )

        if locked_targets is not None:
            targets = list(targets)
        elif client_mode in ("auto", "off"):
            targets = self._coerce_router_execution_order(
                targets,
                router_ordered=router_ordered_ids,
                router_confidence=router_order_confidence,
                user_message=user_message,
            )
        else:
            targets = self.prioritize_agents(targets, user_message)

        targets = self._enforce_crypto_interpreter_last(
            targets,
            all_agents=all_agents,
        )

        if not targets:
            raise LookupError("No matching agents for this message")

        is_discussion = (
            force_discussion if force_discussion is not None else len(targets) >= 2
        )
        resolved_debate_mode = self._resolve_debate_mode(
            debate_mode=pipeline_mode,
            is_discussion=is_discussion,
        )
        resolved_locale = (locale or "en").strip().lower()
        if resolved_locale not in ("en", "ru"):
            resolved_locale = "en"
        targets_need_crypto = any(a.role in _CRYPTO_AGENT_ROLES for a in targets)
        eff_asset, eff_tf = resolve_market_params_for_chat(
            user_message,
            explicit_asset=market_asset,
            explicit_timeframe=market_timeframe,
            targets_include_crypto_agent=targets_need_crypto,
        )
        if targets_need_crypto:
            log_payload(
                logger,
                logging.INFO,
                "chat_market_inference",
                project_id=project.id,
                resolved_asset=eff_asset,
                resolved_timeframe=eff_tf,
                explicit_asset=(market_asset or "").strip() or None,
            )
        market_context = await self._resolve_market_context(
            asset=eff_asset,
            timeframe=eff_tf,
            request_id=str(uuid.uuid4()),
        )

        attachment_ids: list[str] = []
        if file_ids:
            unique_ids = list(dict.fromkeys([f for f in file_ids if f]))
            if unique_ids:
                rows = (
                    await self._session.execute(
                        select(ProjectFile.id).where(
                            ProjectFile.project_id == project.id,
                            ProjectFile.id.in_(unique_ids),
                        )
                    )
                ).scalars().all()
                found_ids = set(rows)
                missing = [fid for fid in unique_ids if fid not in found_ids]
                if missing:
                    raise LookupError("Some attached files were not found in this project")
                attachment_ids = unique_ids

        user_msg = await self._save_user_message(
            project_id=project.id,
            content=user_message,
            is_discussion=is_discussion,
            attachment_file_ids=attachment_ids,
        )

        temp = (
            temperature
            if temperature is not None
            else self._settings.chat_default_temperature
        )

        pending_ids = [a.id for a in targets]
        response_order: list[str] | None = None
        if resolved_debate_mode == "off":
            response_order = pending_ids[:_MAX_TARGET_AGENTS]
            if off_chain_style == "parallel":
                response_order = None
        debate_thread_id: str | None = None
        if resolved_debate_mode != "off":
            thread = await self._create_debate_thread(
                project_id=project.id,
                user_message_id=user_msg.id,
                mode=resolved_debate_mode,
                locale=resolved_locale,
                agent_count=len(targets),
            )
            debate_thread_id = thread.id

        log_payload(
            logger,
            logging.INFO,
            "chat_prepare_accepted",
            project_id=project.id,
            user_message_id=user_msg.id,
            pending=len(pending_ids),
            is_discussion=is_discussion,
            debate_mode=resolved_debate_mode,
            debate_thread_id=debate_thread_id,
        )

        return PrepareChatOutcome(
            user_msg=user_msg,
            pending_agent_ids=pending_ids,
            is_discussion=is_discussion,
            temperature=temp,
            debate_mode=resolved_debate_mode,
            debate_thread_id=debate_thread_id,
            selected_agents=router_selected_ids,
            response_order=response_order,
            router_reason=router_reason,
            router_flow=router_flow,
            off_chain_style=off_chain_style,
            market_asset=eff_asset,
            market_timeframe=eff_tf,
            data_freshness=(market_context or {}).get("data_freshness"),
            source=(market_context or {}).get("source"),
            market_context=market_context,
        )

    async def complete_agent_replies(
        self,
        *,
        project_id: str,
        user_message_id: str,
        user_content: str,
        target_agent_ids: list[str],
        is_discussion: bool,
        temperature: float,
        request_id: str,
        debate_mode: str = "off",
        debate_thread_id: str | None = None,
        locale: str | None = None,
        off_chain_style: str | None = None,
        market_asset: str | None = None,
        market_timeframe: str | None = None,
    ) -> None:
        """Последовательно сгенерировать и сохранить ответы агентов (после ответа HTTP)."""
        project = await self._load_project(project_id)
        if not target_agent_ids:
            return

        rows = (
            await self._session.execute(select(Agent).where(Agent.id.in_(target_agent_ids)))
        ).scalars().all()
        id_to_agent = {a.id: a for a in rows}
        targets = [id_to_agent[i] for i in target_agent_ids if i in id_to_agent]

        if not targets:
            logger.warning(
                "chat_complete_no_targets",
                extra={"log_payload": {"project_id": project_id, "user_message_id": user_message_id}},
            )
            return

        all_agents = await self._load_project_agents(project_id)
        history = await self._load_recent_history(
            project.id, limit=self._settings.chat_history_limit
        )
        files = await self._load_files(project.id)
        agents_by_id = {a.id: a for a in all_agents}

        log_payload(
            logger,
            logging.INFO,
            "chat_orchestration_started",
            request_id=request_id,
            project_id=project.id,
            targets=len(targets),
            is_discussion=is_discussion,
            mock=self._settings.aggregate_mock_providers,
        )

        resolved_locale = (locale or "en").strip().lower()
        if resolved_locale not in ("en", "ru"):
            resolved_locale = "en"
        targets_need_crypto = any(a.role in _CRYPTO_AGENT_ROLES for a in targets)
        eff_asset, eff_tf = resolve_market_params_for_chat(
            user_content,
            explicit_asset=market_asset,
            explicit_timeframe=market_timeframe,
            targets_include_crypto_agent=targets_need_crypto,
        )
        market_context = await self._resolve_market_context(
            asset=eff_asset,
            timeframe=eff_tf,
            request_id=request_id,
        )

        if debate_mode != "off" and debate_thread_id:
            thread = await self._session.get(DebateThread, debate_thread_id)
            if thread is not None:
                thread_locale = (
                    (thread.meta or {}).get("locale")
                    if isinstance(thread.meta, dict)
                    else None
                )
                if isinstance(thread_locale, str) and thread_locale in ("en", "ru"):
                    resolved_locale = thread_locale
                try:
                    await self._run_multi_round_debate(
                        project=project,
                        user_message_id=user_message_id,
                        user_content=user_content,
                        targets=targets,
                        all_agents=all_agents,
                        files=files,
                        history=history,
                        temperature=temperature,
                        request_id=request_id,
                        thread=thread,
                        is_discussion=is_discussion,
                        locale=resolved_locale,
                        market_context=market_context,
                    )
                except Exception as e:
                    updated = await self._set_debate_status(
                        thread,
                        status="failed",
                        disagreements=f"Debate failed: {type(e).__name__}",
                        finished=True,
                    )
                    if updated:
                        raise
                    return
            return

        use_parallel = False
        if off_chain_style == "parallel":
            use_parallel = len(targets) >= 2
        elif off_chain_style == "sequential":
            use_parallel = False
        else:
            use_parallel = len(targets) > 3

        # debate=off: последовательная цепочка или узкая выборка без явного parallel.
        if not use_parallel:
            saved_count, response_order = await self.run_sequential_discussion(
                project=project,
                user_message_id=user_message_id,
                user_content=user_content,
                targets=targets,
                all_agents=all_agents,
                files=files,
                history=history,
                temperature=temperature,
                request_id=request_id,
                is_discussion=is_discussion,
                market_context=market_context,
                market_asset=eff_asset,
                market_timeframe=eff_tf,
            )
            log_payload(
                logger,
                logging.INFO,
                "chat_orchestration_finished",
                request_id=request_id,
                project_id=project.id,
                replies=saved_count,
                is_discussion=is_discussion,
                response_order=response_order,
            )
            return

        # Fallback для широких выборок: параллельный режим как прежде.
        tasks = [
            asyncio.create_task(
                self._agent_turn(
                    agent=agent,
                    project=project,
                    files=files,
                    history=history,
                    agents_by_id=agents_by_id,
                    team_agents=all_agents,
                    user_message_text=user_content,
                    previous_responses=[],
                    temperature=temperature,
                    request_id=request_id,
                    market_context=market_context,
                )
            )
            for agent in targets
        ]
        saved_count = 0
        pass_turns: list[_AgentTurnResult] = []
        for done in asyncio.as_completed(tasks):
            turn = await done
            if _is_pass_response(turn.content):
                pass_turns.append(turn)
                continue
            await self._save_agent_message(
                project_id=project.id,
                agent=turn.agent,
                content=turn.content,
                error=turn.error,
                is_discussion=is_discussion,
                parent_id=user_message_id,
            )
            await self._maybe_record_paper_trade(
                project_id=project.id,
                agent=turn.agent,
                content=turn.content,
                market_asset=eff_asset,
                market_timeframe=eff_tf,
                market_context=market_context,
            )
            saved_count += 1

            log_payload(
                logger,
                logging.INFO,
                "chat_agent_turn",
                request_id=request_id,
                project_id=project.id,
                agent_id=turn.agent.id,
                agent_role=turn.agent.role,
                ok=turn.error is None,
                error=turn.error,
            )

        if saved_count == 0 and pass_turns:
            first = pass_turns[0]
            await self._save_agent_message(
                project_id=project.id,
                agent=first.agent,
                content=first.content,
                error=first.error,
                is_discussion=is_discussion,
                parent_id=user_message_id,
            )
            saved_count = 1

        log_payload(
            logger,
            logging.INFO,
            "chat_orchestration_finished",
            request_id=request_id,
            project_id=project.id,
            replies=saved_count,
            is_discussion=is_discussion,
        )

    async def get_debate_thread(
        self, *, project_id: str, thread_id: str
    ) -> DebateThread:
        thread = await self._session.get(DebateThread, thread_id)
        if thread is None or thread.project_id != project_id:
            raise LookupError("Debate thread not found")
        return thread

    async def get_debate_log(
        self, *, project_id: str, thread_id: str
    ) -> tuple[DebateThread, list[DebateRound], list[DebateTurn], dict[str, Agent]]:
        thread = await self.get_debate_thread(project_id=project_id, thread_id=thread_id)
        rounds = (
            await self._session.execute(
                select(DebateRound)
                .where(DebateRound.thread_id == thread.id)
                .order_by(DebateRound.round_number.asc())
            )
        ).scalars().all()
        turns = (
            await self._session.execute(
                select(DebateTurn)
                .where(DebateTurn.thread_id == thread.id)
                .order_by(DebateTurn.created_at.asc())
            )
        ).scalars().all()
        agent_ids = {t.agent_id for t in turns}
        agents = {}
        if agent_ids:
            rows = (
                await self._session.execute(select(Agent).where(Agent.id.in_(agent_ids)))
            ).scalars().all()
            agents = {a.id: a for a in rows}
        return thread, list(rounds), list(turns), agents
