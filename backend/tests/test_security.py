from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.security.auth import LocalGuard


class FakeRequest:
    def __init__(self, host: str, token: str | None = None) -> None:
        self.client = SimpleNamespace(host=host)
        self.headers = {"x-ingenia-token": token} if token else {}
        self.cookies: dict[str, str] = {}


@pytest.mark.asyncio
async def test_remote_blocked_by_default():
    guard = LocalGuard(Settings(_env_file=None, auth_token="secret"))
    with pytest.raises(HTTPException) as exc:
        await guard(FakeRequest("8.8.8.8", "secret"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_remote_requires_configured_token():
    guard = LocalGuard(Settings(_env_file=None, auth_token="", allow_remote=True))
    with pytest.raises(HTTPException) as exc:
        await guard(FakeRequest("8.8.8.8"))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_remote_allowed_with_token():
    guard = LocalGuard(Settings(_env_file=None, auth_token="secret", allow_remote=True))
    await guard(FakeRequest("8.8.8.8", "secret"))


@pytest.mark.asyncio
async def test_remote_rejects_wrong_token():
    guard = LocalGuard(Settings(_env_file=None, auth_token="secret", allow_remote=True))
    with pytest.raises(HTTPException) as exc:
        await guard(FakeRequest("8.8.8.8", "otro"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_loopback_allowed():
    guard = LocalGuard(Settings(_env_file=None, auth_token="secret"))
    await guard(FakeRequest("127.0.0.1", "secret"))

