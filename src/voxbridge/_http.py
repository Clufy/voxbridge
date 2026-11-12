from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, NoReturn

import httpx

from .errors import AuthError, ProviderError, RateLimited

_sleep: Callable[[float], None] = time.sleep
_asleep: Callable[[float], Awaitable[None]] = asyncio.sleep

_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"}
_IDEMPOTENT_STATUS = {500, 502, 503, 504}
_DEFAULT_BACKOFF = 0.5
_MAX_RETRY_AFTER = 10.0
_MAX_ATTEMPTS = 2


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _is_idempotent(method: str, idempotent: bool | None) -> bool:
    if idempotent is not None:
        return idempotent
    return method.upper() in _IDEMPOTENT_METHODS


def _should_retry(outcome: httpx.Response | Exception, idempotent: bool) -> float | None:
    """Return the delay before retrying, or None when the outcome must not be retried."""
    if isinstance(outcome, httpx.Response):
        status = outcome.status_code
        if status == 429 or (status in _IDEMPOTENT_STATUS and idempotent):
            ra = _parse_retry_after(outcome.headers.get("Retry-After"))
            if ra is not None and status in (429, 503):
                return min(ra, _MAX_RETRY_AFTER)
            return _DEFAULT_BACKOFF
        return None
    if isinstance(outcome, (httpx.ConnectError, httpx.ConnectTimeout)):
        return _DEFAULT_BACKOFF
    if isinstance(outcome, httpx.TransportError) and idempotent:
        return _DEFAULT_BACKOFF
    return None


class HttpCore:
    def __init__(
        self, base_url: str, api_key: str, provider: str, *, timeout: float = 30.0
    ) -> None:
        self.provider = provider
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout
            )
        return self._sync_client

    def _aclient(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout
            )
        return self._async_client

    def _raise(self, resp: httpx.Response) -> NoReturn:
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        msg = f"{self.provider} {resp.status_code}"
        if resp.status_code in (401, 403):
            raise AuthError(msg, status_code=resp.status_code, provider=self.provider, body=body)
        if resp.status_code == 429:
            raise RateLimited(msg, status_code=429, provider=self.provider, body=body,
                              retry_after=_parse_retry_after(resp.headers.get("Retry-After")))
        raise ProviderError(msg, status_code=resp.status_code, provider=self.provider, body=body)

    def _conn_error(self, exc: Exception) -> ProviderError:
        return ProviderError(f"{self.provider} connection error: {exc}", provider=self.provider)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def request(
        self, method: str, path: str, *, json: Any = None, params: Any = None,
        idempotent: bool | None = None,
    ) -> Any:
        safe = _is_idempotent(method, idempotent)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            last = attempt == _MAX_ATTEMPTS
            try:
                resp = self._client().request(method, path, json=json, params=params)
            except httpx.TransportError as exc:
                delay = _should_retry(exc, safe)
                if delay is None or last:
                    raise self._conn_error(exc) from exc
                _sleep(delay)
                continue
            if resp.status_code < 400:
                return self._parse(resp)
            delay = _should_retry(resp, safe)
            if delay is None or last:
                self._raise(resp)
            _sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def arequest(
        self, method: str, path: str, *, json: Any = None, params: Any = None,
        idempotent: bool | None = None,
    ) -> Any:
        safe = _is_idempotent(method, idempotent)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            last = attempt == _MAX_ATTEMPTS
            try:
                resp = await self._aclient().request(method, path, json=json, params=params)
            except httpx.TransportError as exc:
                delay = _should_retry(exc, safe)
                if delay is None or last:
                    raise self._conn_error(exc) from exc
                await _asleep(delay)
                continue
            if resp.status_code < 400:
                return self._parse(resp)
            delay = _should_retry(resp, safe)
            if delay is None or last:
                self._raise(resp)
            await _asleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        if self._sync_client is not None:
            self._sync_client.close()

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
