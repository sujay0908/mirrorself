"""
Auth + user schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=120)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserBootstrap(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: Optional[str] = Field(default=None, max_length=120)


class PersonalityProfile(BaseModel):
    values: list[str] = []
    communication_style: Optional[str] = None
    humor: Optional[str] = None
    fears: list[str] = []
    dreams: list[str] = []


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    is_public: bool
    is_onboarded: bool
    twin_status: str
    avatar_video_path: Optional[str] = None
    created_at: datetime


class UserPrivate(UserPublic):
    email: EmailStr
    personality: Optional[PersonalityProfile] = None
    conversation_count: int
    voice_id: Optional[str] = None
    face_photo_path: Optional[str] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    bio: Optional[str] = Field(default=None, max_length=500)
    is_public: Optional[bool] = None
    personality: Optional[PersonalityProfile] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPrivate
