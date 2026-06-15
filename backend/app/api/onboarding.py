"""
Onboarding endpoints: face photo upload, voice sample upload, personality quiz.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.models.user import User
from app.schemas.user import PersonalityProfile, UserPrivate
from app.services.avatar_service import avatar_service
from app.services.voice_service import voice_service
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/face", response_model=UserPrivate)
async def upload_face(
    photo: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    if photo.content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Unsupported image type: {photo.content_type}")

    tmp_path = Path(settings.FACE_PHOTOS_DIR) / f"tmp_{current_user.id}_{photo.filename}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with tmp_path.open("wb") as f:
        while chunk := await photo.read(1024 * 1024):
            size += len(chunk)
            if size > settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024:
                f.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, "File too large")
            f.write(chunk)

    ok, msg = await avatar_service.validate_photo(str(tmp_path))
    if not ok:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, msg)

    saved = await avatar_service.save_face_photo(str(tmp_path), current_user.id)
    tmp_path.unlink(missing_ok=True)
    current_user.face_photo_path = saved
    await db.commit()
    await db.refresh(current_user)
    return UserPrivate.model_validate(current_user)


@router.post("/voice", response_model=UserPrivate)
async def upload_voice(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    if audio.content_type not in settings.ALLOWED_AUDIO_TYPES:
        raise HTTPException(400, f"Unsupported audio type: {audio.content_type}")

    tmp_path = Path(settings.VOICE_SAMPLES_DIR) / f"tmp_{current_user.id}_{audio.filename or 'sample.wav'}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with tmp_path.open("wb") as f:
        while chunk := await audio.read(1024 * 1024):
            size += len(chunk)
            if size > settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024:
                f.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, "File too large")
            f.write(chunk)

    ok, msg = await voice_service.validate_sample(str(tmp_path))
    if not ok:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, msg)

    voice_id = await voice_service.clone_voice(str(tmp_path), current_user.id)
    tmp_path.unlink(missing_ok=True)
    current_user.voice_id = voice_id
    current_user.voice_sample_path = str(Path(settings.VOICE_SAMPLES_DIR) / f"{voice_id}.wav")
    await db.commit()
    await db.refresh(current_user)
    return UserPrivate.model_validate(current_user)


@router.post("/quiz", response_model=UserPrivate)
async def submit_quiz(
    personality: PersonalityProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    current_user.personality = personality.model_dump()
    current_user.is_onboarded = True
    current_user.twin_status = "processing"
    await db.commit()
    await db.refresh(current_user)
    logger.info(f"User {current_user.id} completed onboarding; twin processing started.")
    return UserPrivate.model_validate(current_user)


@router.post("/generate-avatar", response_model=UserPrivate)
async def generate_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    if not current_user.face_photo_path or not current_user.voice_id:
        raise HTTPException(
            400,
            "Need both a face photo and a voice sample before generating your avatar.",
        )
    if current_user.twin_status == "ready":
        return UserPrivate.model_validate(current_user)
    current_user.twin_status = "processing"
    await db.commit()

    # Use the user's existing voice sample as a stand-in audio for a "hello" preview
    sample_audio = current_user.voice_sample_path
    if sample_audio:
        video = await avatar_service.generate_talking_head(
            current_user.face_photo_path, sample_audio, current_user.id
        )
        current_user.avatar_video_path = video
    current_user.twin_status = "ready"
    await db.commit()
    await db.refresh(current_user)
    return UserPrivate.model_validate(current_user)
