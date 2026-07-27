"""
Helpers to turn ORM models that store storage object keys into API models that
contain browser-usable media URLs.
"""
from __future__ import annotations

from app.models.conversation import Message
from app.models.user import User
from app.schemas.chat import MessageOut
from app.schemas.user import UserPrivate, UserPublic
from app.services.storage_service import storage_service


async def map_user_private(user: User) -> UserPrivate:
    payload = UserPrivate.model_validate(user)
    payload.face_photo_path = await storage_service.get_download_url(user.face_photo_path)
    payload.avatar_video_path = await storage_service.get_download_url(user.avatar_video_path)
    return payload


async def map_user_public(user: User) -> UserPublic:
    payload = UserPublic.model_validate(user)
    payload.avatar_video_path = await storage_service.get_download_url(user.avatar_video_path)
    return payload


async def map_message(message: Message) -> MessageOut:
    payload = MessageOut.model_validate(message)
    payload.audio_url = await storage_service.get_download_url(message.audio_path)
    payload.video_url = await storage_service.get_download_url(message.video_path)
    return payload
