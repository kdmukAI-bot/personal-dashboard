from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from personal_dashboard.config import settings


async def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    provided = authorization[len("Bearer ") :].strip()
    expected = settings.notify_api_key
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
