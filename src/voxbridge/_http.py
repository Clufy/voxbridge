from __future__ import annotations
from typing import Any
import httpx
from .errors import AuthError, ProviderError, RateLimited

_RETRY_STATUS = {429, 500, 502, 503, 504}

class HttpCore:
    def __init__(self, base_url: str, api_key: str, provider: str, *, timeout: float = 30.0) -> None:
        self.provider = provider
        headers = {"Authorization": f"Bearer {api_key}"}
        self._sync = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        self._async = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)

    def _raise(self, resp: httpx.Response) -> None:
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        msg = f"{self.provider} {resp.status_code}"
        if resp.status_code in (401, 403):
            raise AuthError(msg, status_code=resp.status_code, provider=self.provider, body=body)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            raise RateLimited(msg, status_code=429, provider=self.provider, body=body,
                              retry_after=float(ra) if ra else None)
        raise ProviderError(msg, status_code=resp.status_code, provider=self.provider, body=body)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        for attempt in (1, 2):
            try:
                resp = self._sync.request(method, path, json=json, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                # ponytail: single retry, no backoff jitter; add tenacity if flakiness demands it
                if attempt == 1:
                    continue
                raise ProviderError(
                    f"{self.provider} connection error: {exc}", provider=self.provider
                ) from exc
            if resp.status_code < 400:
                return self._parse(resp)
            if resp.status_code in _RETRY_STATUS and attempt == 1:
                continue
            self._raise(resp)
        self._raise(resp)  # pragma: no cover

    async def arequest(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        for attempt in (1, 2):
            try:
                resp = await self._async.request(method, path, json=json, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                # ponytail: single retry, no backoff jitter; add tenacity if flakiness demands it
                if attempt == 1:
                    continue
                raise ProviderError(
                    f"{self.provider} connection error: {exc}", provider=self.provider
                ) from exc
            if resp.status_code < 400:
                return self._parse(resp)
            if resp.status_code in _RETRY_STATUS and attempt == 1:
                continue
            self._raise(resp)
        self._raise(resp)  # pragma: no cover

    def close(self) -> None:
        self._sync.close()

    async def aclose(self) -> None:
        await self._async.aclose()
