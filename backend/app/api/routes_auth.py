from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..models.schemas import LoginRequest, RegisterRequest
from ..security.auth import (
    SESSION_COOKIE,
    current_user,
    require_user,
    session_token,
)
from ..security.passwords import (
    hash_password,
    hash_token,
    new_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        max_age=settings.session_days * 86400,
        path="/",
    )


def _issue_session(request: Request, response: Response, user_id: str) -> str:
    token = new_token()
    expires = (
        datetime.now(timezone.utc) + timedelta(days=request.app.state.settings.session_days)
    ).isoformat(timespec="seconds")
    request.app.state.store.create_auth_session(hash_token(token), user_id, expires)
    _set_session_cookie(response, request, token)
    return token


@router.get("/mode")
async def auth_mode(request: Request) -> dict:
    settings = request.app.state.settings
    user = current_user(request)
    return {
        "accounts": settings.accounts_enabled,
        "registration_open": settings.accounts_enabled,
        "user": user,
    }


@router.post("/register")
async def register(
    payload: RegisterRequest, request: Request, response: Response
) -> dict:
    settings = request.app.state.settings
    if not settings.accounts_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El registro no está disponible en modo local.",
        )
    client = request.client.host if request.client else "unknown"
    request.app.state.registration_limiter.check(client)
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Correo electrónico inválido.")
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=422, detail="La contraseña debe tener al menos 8 caracteres."
        )
    store = request.app.state.store
    if store.get_user_auth(email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese correo.",
        )
    try:
        user = store.create_user(
            email, payload.name or email.split("@")[0], hash_password(payload.password)
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese correo.",
        ) from exc
    _issue_session(request, response, user["id"])
    return {"user": user}


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    settings = request.app.state.settings
    if not settings.accounts_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El inicio de sesión no está disponible en modo local.",
        )
    client = request.client.host if request.client else "unknown"
    request.app.state.login_limiter.check(client)

    email = payload.email.strip().lower()
    store = request.app.state.store
    row = store.get_user_auth(email)
    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
        )
    _issue_session(request, response, row["id"])
    return {
        "user": {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "created_at": row["created_at"],
        }
    }


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    token = session_token(request)
    if token:
        request.app.state.store.delete_auth_session(hash_token(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_user)) -> dict:
    return {"user": user}
