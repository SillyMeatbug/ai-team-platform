"""

Реальный асинхронный диспетчер LLM через httpx.



Единый шлюз OpenRouter (OpenAI-совместимый POST /chat/completions).

Базовый URL и ключ — OPENROUTER_BASE_URL, OPENROUTER_API_KEY.

Обязательные для статистики заголовки: HTTP-Referer, X-Title.

"""



from __future__ import annotations



import asyncio

import logging

import os

import time

from typing import Any



import httpx

from tenacity import retry_if_exception, stop_after_attempt, wait_exponential

from tenacity.asyncio import AsyncRetrying



from app.config.loader import RouteEntry

from app.core.logging_config import log_payload

from app.models.schemas import ResultItem, TokensUsed



logger = logging.getLogger(__name__)



_OPENROUTER_PROVIDER = "openrouter"

# Упрощённая оценка USD за 1000 токенов (промежуточная метрика; фактическая цена зависит от модели на OpenRouter).

_OPENROUTER_BLEND_COST_PER_1K = 0.00012





class _RetryableHTTPStatus(Exception):

    """429 или 5xx — повторяемый статус для tenacity."""



    __slots__ = ("status_code",)



    def __init__(self, status_code: int) -> None:

        self.status_code = status_code

        super().__init__(str(status_code))





def compute_route_cost_usd(provider: str, tokens: TokensUsed) -> float:

    """cost_per_1k_tokens * (prompt + completion) / 1000."""

    rate = _OPENROUTER_BLEND_COST_PER_1K if provider == _OPENROUTER_PROVIDER else 0.0

    total_tokens = tokens.prompt + tokens.completion

    return round(rate * (total_tokens / 1000.0), 6)





def _timeout_obj(timeout_ms: int) -> httpx.Timeout:

    sec = max(timeout_ms, 1) / 1000.0

    return httpx.Timeout(sec)





def _resolve_chat_completions_url(route: RouteEntry) -> tuple[str | None, str | None]:

    """(url, error_reason_if_any)."""

    if route.provider != _OPENROUTER_PROVIDER:

        return (

            None,

            f"unsupported provider (expected {_OPENROUTER_PROVIDER}): {route.provider}",

        )

    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")

    return f"{base}/chat/completions", None





def _openrouter_headers(api_key: str) -> dict[str, str]:

    referer = os.getenv("OPENROUTER_HTTP_REFERER", "http://127.0.0.1:8000").strip()

    title = os.getenv("OPENROUTER_APP_TITLE", "AI Team Platform").strip()

    return {

        "Authorization": f"Bearer {api_key}",

        "Content-Type": "application/json",

        "HTTP-Referer": referer,

        "X-Title": title,

    }





def _openrouter_api_key() -> str:

    return os.getenv("OPENROUTER_API_KEY", "").strip()





def _extract_usage_tokens(data: dict[str, Any], *, route_id: str) -> TokensUsed:

    usage = data.get("usage")

    if not isinstance(usage, dict):

        log_payload(

            logger,

            logging.WARNING,

            "llm_usage_missing_or_invalid",

            route_id=route_id,

        )

        return TokensUsed(prompt=0, completion=0)

    pt = usage.get("prompt_tokens")

    ct = usage.get("completion_tokens")

    if pt is None or ct is None:

        log_payload(

            logger,

            logging.WARNING,

            "llm_usage_partial_fields",

            route_id=route_id,

            has_prompt_tokens=pt is not None,

            has_completion_tokens=ct is not None,

        )

    try:

        pi = int(pt) if pt is not None else 0

        ci = int(ct) if ct is not None else 0

    except (TypeError, ValueError):

        log_payload(logger, logging.WARNING, "llm_usage_parse_failed", route_id=route_id)

        return TokensUsed(prompt=0, completion=0)

    return TokensUsed(prompt=max(pi, 0), completion=max(ci, 0))





def _extract_content(data: dict[str, Any]) -> tuple[str | None, str | None]:

    """(content, error_message)."""

    choices = data.get("choices")

    if not isinstance(choices, list) or not choices:

        return None, "invalid response: missing or empty choices"

    first = choices[0]

    if not isinstance(first, dict):

        return None, "invalid response: choice item is not an object"

    msg = first.get("message")

    if not isinstance(msg, dict):

        return None, "invalid response: missing message object"

    content = msg.get("content")

    if content is None:

        return None, "invalid response: missing message.content"

    if not isinstance(content, str):

        return None, "invalid response: message.content is not a string"

    return content, None





async def complete_chat_messages(

    client: httpx.AsyncClient,

    *,

    route: RouteEntry,

    messages: list[dict[str, Any]],

    temperature: float,

    timeout_ms: int,

    request_id: str,

) -> tuple[str | None, str | None]:

    """

    Один запрос chat completions без ретраев (арбитр / спец-вызовы).

    Возвращает (content, error_reason).

    """

    wall0 = time.perf_counter()

    url, cfg_err = _resolve_chat_completions_url(route)

    if cfg_err or not url:

        return None, cfg_err



    api_key = _openrouter_api_key()

    if not api_key:

        return None, "missing API key in environment: OPENROUTER_API_KEY"



    payload: dict[str, Any] = {

        "model": route.model,

        "messages": messages,

        "temperature": temperature,

    }

    headers = _openrouter_headers(api_key)



    try:

        resp = await client.post(

            url,

            headers=headers,

            json=payload,

            timeout=_timeout_obj(timeout_ms),

        )

    except httpx.TimeoutException:

        return None, "request timeout"

    except httpx.ConnectError as e:

        return None, f"connect error: {type(e).__name__}"

    except httpx.HTTPError as e:

        return None, f"http error: {type(e).__name__}"



    latency_ms = max(1, int((time.perf_counter() - wall0) * 1000))



    if resp.status_code < 200 or resp.status_code >= 300:

        log_payload(

            logger,

            logging.WARNING,

            "arbiter_dispatch_non_success",

            request_id=request_id,

            route_id=route.route_id,

            status_code=resp.status_code,

            latency_ms=latency_ms,

        )

        return None, f"HTTP {resp.status_code}"



    try:

        data = resp.json()

    except ValueError:

        return None, "invalid JSON body"



    if not isinstance(data, dict):

        return None, "invalid response: root JSON is not an object"



    content, parse_err = _extract_content(data)

    if parse_err:

        log_payload(

            logger,

            logging.WARNING,

            "arbiter_dispatch_schema_error",

            request_id=request_id,

            route_id=route.route_id,

            latency_ms=latency_ms,

            error=parse_err,

        )

        return None, parse_err



    log_payload(

        logger,

        logging.INFO,

        "arbiter_dispatch_success",

        request_id=request_id,

        route_id=route.route_id,

        latency_ms=latency_ms,

    )

    return content, None





class HttpAggregationDispatcher:

    """Параллельные OpenAI-совместимые вызовы через OpenRouter."""



    __slots__ = ("_client",)



    def __init__(self, client: httpx.AsyncClient) -> None:

        self._client = client



    async def run(

        self,

        *,

        query: str,

        routes: list[RouteEntry],

        temperature: float,

        timeout_ms: int,

        request_id: str,

    ) -> list[ResultItem]:

        tasks = [

            self._dispatch_one_route(

                route=r,

                query=query,

                temperature=temperature,

                timeout_ms=timeout_ms,

                request_id=request_id,

            )

            for r in routes

        ]

        return list(await asyncio.gather(*tasks))



    async def _dispatch_one_route(

        self,

        *,

        route: RouteEntry,

        query: str,

        temperature: float,

        timeout_ms: int,

        request_id: str,

    ) -> ResultItem:

        wall0 = time.perf_counter()

        url, cfg_err = _resolve_chat_completions_url(route)

        if cfg_err or not url:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_config_error",

                request_id=request_id,

                route_id=route.route_id,

                error=cfg_err or "unknown",

                latency_ms=lat,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=cfg_err,

            )



        api_key = _openrouter_api_key()

        if not api_key:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            err = "missing API key in environment: OPENROUTER_API_KEY"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_missing_api_key",

                request_id=request_id,

                route_id=route.route_id,

                latency_ms=lat,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )



        payload: dict[str, Any] = {

            "model": route.model,

            "messages": [

                {"role": "system", "content": route.system_prompt},

                {"role": "user", "content": query},

            ],

            "temperature": temperature,

        }

        headers = _openrouter_headers(api_key)



        try:

            resp = await self._post_with_retries(

                url=url,

                headers=headers,

                payload=payload,

                timeout=_timeout_obj(timeout_ms),

                route_id=route.route_id,

                request_id=request_id,

            )

        except _RetryableHTTPStatus as e:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            err = f"HTTP {e.status_code} after retries exhausted"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_retry_exhausted",

                request_id=request_id,

                route_id=route.route_id,

                status_code=e.status_code,

                latency_ms=lat,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )

        except httpx.TimeoutException:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            err = "request timeout"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_timeout",

                request_id=request_id,

                route_id=route.route_id,

                latency_ms=lat,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )

        except httpx.ConnectError as e:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            err = f"connect error: {type(e).__name__}"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_connect_error",

                request_id=request_id,

                route_id=route.route_id,

                latency_ms=lat,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )

        except httpx.HTTPError as e:

            lat = max(1, int((time.perf_counter() - wall0) * 1000))

            err = f"http error: {type(e).__name__}"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_http_error",

                request_id=request_id,

                route_id=route.route_id,

                latency_ms=lat,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=lat,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )



        latency_ms = max(1, int((time.perf_counter() - wall0) * 1000))

        status_code = resp.status_code



        if status_code < 200 or status_code >= 300:

            err = f"HTTP {status_code}"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_non_success_status",

                request_id=request_id,

                route_id=route.route_id,

                status_code=status_code,

                latency_ms=latency_ms,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=latency_ms,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )



        try:

            data = resp.json()

        except ValueError:

            err = "invalid JSON body"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_invalid_json",

                request_id=request_id,

                route_id=route.route_id,

                status_code=status_code,

                latency_ms=latency_ms,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=latency_ms,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )



        if not isinstance(data, dict):

            err = "invalid response: root JSON is not an object"

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_invalid_shape",

                request_id=request_id,

                route_id=route.route_id,

                status_code=status_code,

                latency_ms=latency_ms,

                error=err,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=latency_ms,

                tokens_used=TokensUsed(prompt=0, completion=0),

                error=err,

            )



        tokens = _extract_usage_tokens(data, route_id=route.route_id)

        content, parse_err = _extract_content(data)

        if parse_err:

            log_payload(

                logger,

                logging.WARNING,

                "route_dispatch_schema_error",

                request_id=request_id,

                route_id=route.route_id,

                status_code=status_code,

                latency_ms=latency_ms,

                error=parse_err,

                tokens_prompt=tokens.prompt,

                tokens_completion=tokens.completion,

            )

            return ResultItem(

                route_id=route.route_id,

                provider=route.provider,

                model=route.model,

                role=route.role,

                content=None,

                latency_ms=latency_ms,

                tokens_used=tokens,

                error=parse_err,

            )



        log_payload(

            logger,

            logging.INFO,

            "route_dispatch_success",

            request_id=request_id,

            route_id=route.route_id,

            status_code=status_code,

            latency_ms=latency_ms,

            tokens_prompt=tokens.prompt,

            tokens_completion=tokens.completion,

        )



        return ResultItem(

            route_id=route.route_id,

            provider=route.provider,

            model=route.model,

            role=route.role,

            content=content,

            latency_ms=latency_ms,

            tokens_used=tokens,

            error=None,

        )



    async def _post_with_retries(

        self,

        *,

        url: str,

        headers: dict[str, str],

        payload: dict[str, Any],

        timeout: httpx.Timeout,

        route_id: str,

        request_id: str,

    ) -> httpx.Response:

        async def _attempt() -> httpx.Response:

            resp = await self._client.post(

                url, headers=headers, json=payload, timeout=timeout

            )

            if resp.status_code == 429 or resp.status_code >= 500:

                log_payload(

                    logger,

                    logging.WARNING,

                    "llm_retryable_response",

                    request_id=request_id,

                    route_id=route_id,

                    status_code=resp.status_code,

                )

                raise _RetryableHTTPStatus(resp.status_code)

            return resp



        retrying = AsyncRetrying(

            stop=stop_after_attempt(3),

            wait=wait_exponential(multiplier=1, min=1, max=8),

            retry=retry_if_exception(lambda exc: isinstance(exc, _RetryableHTTPStatus)),

            reraise=True,

        )

        return await retrying(_attempt)


