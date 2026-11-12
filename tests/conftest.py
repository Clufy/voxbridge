import pytest

from voxbridge import _http


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry backoff must never really sleep in the suite."""

    def _sleep(_: float) -> None:
        return None

    async def _asleep(_: float) -> None:
        return None

    monkeypatch.setattr(_http, "_sleep", _sleep)
    monkeypatch.setattr(_http, "_asleep", _asleep)
