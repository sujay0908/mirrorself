"""
Auth endpoints: register, login, me.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserPrivate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    existing = (
        await db.execute(
            select(User).where(or_(User.email == payload.email, User.username == payload.username))
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already in use")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserPrivate.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserPrivate.model_validate(user))


@router.get("/me", response_model=UserPrivate)
async def me(current_user: User = Depends(get_current_user)) -> UserPrivate:
    return UserPrivate.model_validate(current_user)
