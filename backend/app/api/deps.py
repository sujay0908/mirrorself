"""
Auth dependency: extracts current user from Supabase access tokens.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import SupabaseIdentity, verify_supabase_token
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/bootstrap", auto_error=False)


async def get_current_identity(
    token: str | None = Depends(oauth2_scheme),
) -> SupabaseIdentity:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    identity = await verify_supabase_token(token)
    if not identity:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return identity


async def get_current_user(
    identity: SupabaseIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = (
        await db.execute(select(User).where(User.supabase_user_id == identity.user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None
    identity = await verify_supabase_token(token)
    if not identity:
        return None
    return (
        await db.execute(select(User).where(User.supabase_user_id == identity.user_id))
    ).scalar_one_or_none()
