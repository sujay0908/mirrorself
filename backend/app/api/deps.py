"""
Auth dependency: extracts current user from JWT.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user_id = int(payload["sub"])
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    return (
        await db.execute(select(User).where(User.id == int(payload["sub"])))
    ).scalar_one_or_none()
