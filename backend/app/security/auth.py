from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from ..core.config import Settings


class RateLimiter:
    """Simple in-memory sliding-window limiter for a single local user."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = max(1, limit_per_minute)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Espera un momento.",
            )
        window.append(now)


def is_loopback(host: str | None) -> bool:
    if host in {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}:
        return True
    return bool(host and (host.startswith("127.") or host == "::ffff:127.0.0.1"))


def extract_token(request: Request) -> str | None:
    header = request.headers.get("x-ingenia-token")
    if header:
        return header
    cookie = request.cookies.get("ingenia_token")
    if cookie:
        return cookie
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


class LocalGuard:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.limiter = RateLimiter(settings.rate_limit_per_minute)

    async def __call__(self, request: Request) -> None:
        client_host = request.client.host if request.client else None
        local = is_loopback(client_host)

        if not local and not self.settings.allow_remote:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ingenia AI solo acepta conexiones locales.",
            )

        expected = self.settings.auth_token
        if not local and not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El despliegue remoto requiere INGENIA_AUTH_TOKEN configurado.",
            )
        if expected:
            token = extract_token(request)
            if token != expected:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token local inválido o ausente.",
                )
        self.limiter.check(client_host or "local")


async def require_local(request: Request) -> None:
    """FastAPI dependency that validates the local token and rate limit."""
    guard: LocalGuard | None = getattr(request.app.state, "guard", None)
    if guard is None:
        guard = LocalGuard(request.app.state.settings)
        request.app.state.guard = guard
    await guard(request)
