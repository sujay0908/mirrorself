"""
Onboarding endpoints: face photo upload, voice sample upload, personality quiz.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.models.user import User
from app.schemas.user import PersonalityProfile, UserPrivate
from app.services.avatar_service import avatar_service
from app.services.response_mapper import map_user_private
from app.services.voice_service import voice_service
from app.services.storage_service import storage_service
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

    # Read file into memory
    file_data = await photo.read()
    if len(file_data) > settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, "File too large")

    # Save to temporary local path for validation
    tmp_path = Path(settings.FACE_PHOTOS_DIR) / f"tmp_{current_user.id}_{photo.filename}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("wb") as f:
        f.write(file_data)

    try:
        ok, msg = await avatar_service.validate_photo(str(tmp_path))
        if not ok:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(400, msg)

        # Upload to Supabase Storage
        object_path = await storage_service.upload_face_photo(
            current_user.id, file_data, photo.filename or "photo.jpg"
        )

        # Store object path (not full URL) in database
        current_user.face_photo_path = object_path
        await db.commit()
        await db.refresh(current_user)
        return await map_user_private(current_user)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/voice", response_model=UserPrivate)
async def upload_voice(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    if audio.content_type not in settings.ALLOWED_AUDIO_TYPES:
        raise HTTPException(400, f"Unsupported audio type: {audio.content_type}")

    # Read file into memory
    file_data = await audio.read()
    if len(file_data) > settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, "File too large")

    # Save to temporary local path for validation and processing
    tmp_path = Path(settings.VOICE_SAMPLES_DIR) / f"tmp_{current_user.id}_{audio.filename or 'sample.wav'}"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("wb") as f:
        f.write(file_data)

    try:
        ok, msg = await voice_service.validate_sample(str(tmp_path))
        if not ok:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(400, msg)

        # Voice cloning - keeps normalized voice in local storage
        voice_id = await voice_service.clone_voice(str(tmp_path), current_user.id)

        # Upload original voice sample to Supabase Storage
        object_path = await storage_service.upload_voice_sample(
            current_user.id, file_data, audio.filename or f"{voice_id}.wav"
        )

        current_user.voice_id = voice_id
        current_user.voice_sample_path = object_path
        await db.commit()
        await db.refresh(current_user)
        return await map_user_private(current_user)
    finally:
        tmp_path.unlink(missing_ok=True)


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
    return await map_user_private(current_user)


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
        return await map_user_private(current_user)
    current_user.twin_status = "processing"
    await db.commit()

    try:
        # Download face photo from storage for processing
        face_photo_local = await storage_service.download_for_processing(current_user.face_photo_path)
        
        # Use the user's normalized voice sample from local storage for generation
        voice_sample = Path(settings.VOICE_SAMPLES_DIR) / f"{current_user.voice_id}.wav"
        if not voice_sample.exists():
            raise HTTPException(400, "Voice sample not found")

        # Generate the talking head
        video = await avatar_service.generate_talking_head(
            face_photo_local, str(voice_sample), current_user.id
        )

        # Upload generated video to Supabase Storage
        with open(video, "rb") as f:
            video_data = f.read()
        object_path = await storage_service.upload_avatar_video(
            current_user.id, video_data, Path(video).name
        )

        current_user.avatar_video_path = object_path
        current_user.twin_status = "ready"
        await db.commit()
        await db.refresh(current_user)
        return await map_user_private(current_user)
    except Exception as e:
        logger.error(f"Avatar generation failed for user {current_user.id}: {e}")
        current_user.twin_status = "failed"
        await db.commit()
        raise HTTPException(500, f"Avatar generation failed: {e}")
