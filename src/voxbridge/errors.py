from __future__ import annotations

from typing import Any


class VoxBridgeError(Exception):
    """Base for all voxbridge errors."""


class ProviderError(VoxBridgeError):
    """A provider call failed or returned something unusable.

    Attributes:
        status_code: HTTP status code, if the failure was an HTTP response.
        provider: Name of the provider involved.
        body: Decoded response body, if any.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None,
        provider: str | None = None, body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.body = body


class AuthError(ProviderError):
    """401/403 from a provider."""


class RateLimited(ProviderError):
    """429 from a provider.

    Attributes:
        retry_after: Seconds the provider asked you to wait, if it said.
    """

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class NotSupported(VoxBridgeError):
    """Requested capability is not available on the selected provider."""


class SignatureError(VoxBridgeError):
    """Webhook signature verification failed."""
