"""
Auth endpoints: bootstrap local profile and fetch current user.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_identity, get_current_user
from app.core.database import get_db
from app.core.security import SupabaseIdentity
from app.models.user import User
from app.schemas.user import TokenResponse, UserBootstrap, UserCreate, UserLogin, UserPrivate
from app.services.response_mapper import map_user_private

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    raise HTTPException(
        status.HTTP_410_GONE,
        "Registration now happens through Supabase Auth on the frontend.",
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    raise HTTPException(
        status.HTTP_410_GONE,
        "Login now happens through Supabase Auth on the frontend.",
    )


@router.post("/bootstrap", response_model=UserPrivate)
async def bootstrap(
    payload: UserBootstrap,
    identity: SupabaseIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    existing = (
        await db.execute(select(User).where(User.supabase_user_id == identity.user_id))
    ).scalar_one_or_none()
    if existing:
        return await map_user_private(existing)

    if not identity.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Supabase user is missing an email")

    username = payload.username or identity.user_metadata.get("username")
    display_name = payload.display_name or identity.user_metadata.get("display_name") or username or identity.email

    by_email = (
        await db.execute(select(User).where(User.email == identity.email))
    ).scalar_one_or_none()
    if by_email:
        if by_email.supabase_user_id and by_email.supabase_user_id != identity.user_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email is already linked to another account")
        by_email.supabase_user_id = identity.user_id
        if payload.display_name and not by_email.display_name:
            by_email.display_name = payload.display_name
        await db.commit()
        await db.refresh(by_email)
        return await map_user_private(by_email)

    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username is required to create your profile")

    username_conflict = (
        await db.execute(
            select(User).where(or_(User.username == username, User.email == identity.email))
        )
    ).scalar_one_or_none()
    if username_conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already in use")

    user = User(
        supabase_user_id=identity.user_id,
        email=identity.email,
        username=username,
        hashed_password=None,
        display_name=display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await map_user_private(user)


@router.get("/me", response_model=UserPrivate)
async def me(current_user: User = Depends(get_current_user)) -> UserPrivate:
    return await map_user_private(current_user)
