"""
Firebase Storage / Google Cloud Storage abstraction for media files.

This service uses the Google Cloud Storage API against the Firebase project's
bucket. It stores object keys in Postgres and returns browser-friendly media
URLs for the frontend.
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

from app.core.config import settings
from app.core.logging import logger

try:
    from google.cloud import storage
except ImportError:  # pragma: no cover - dependency validated in runtime/CI
    storage = None


class StorageService:
    """Manages uploads, downloads, and browser-facing URLs for media files."""

    def __init__(self) -> None:
        self._client: Optional["storage.Client"] = None
        self._bucket = None

    def _ensure_client(self) -> "storage.Client":
        if storage is None:
            raise RuntimeError("google-cloud-storage is not installed")
        if self._client is None:
            self._client = storage.Client(project=settings.GCP_PROJECT_ID or None)
        return self._client

    def _ensure_bucket(self):
        if not settings.FIREBASE_STORAGE_BUCKET:
            raise RuntimeError("FIREBASE_STORAGE_BUCKET is not configured")
        if self._bucket is None:
            self._bucket = self._ensure_client().bucket(settings.FIREBASE_STORAGE_BUCKET)
        return self._bucket

    def _build_object_name(self, prefix: str, user_id: int, filename: str) -> str:
        safe_name = Path(filename).name or "file.bin"
        return f"{prefix}/user_{user_id}/{safe_name}"

    def _firebase_download_url(self, object_name: str, token: str) -> str:
        encoded_object_name = quote(object_name, safe="")
        return (
            f"https://firebasestorage.googleapis.com/v0/b/{settings.FIREBASE_STORAGE_BUCKET}"
            f"/o/{encoded_object_name}?alt=media&token={token}"
        )

    def _public_url(self, object_name: str) -> str:
        encoded = quote(object_name, safe="/")
        return f"https://storage.googleapis.com/{settings.FIREBASE_STORAGE_BUCKET}/{encoded}"

    def _ensure_download_token(self, blob) -> str:
        metadata = dict(blob.metadata or {})
        token_value = metadata.get("firebaseStorageDownloadTokens")
        if token_value:
            return token_value.split(",")[0]

        token_value = uuid4().hex
        metadata["firebaseStorageDownloadTokens"] = token_value
        blob.metadata = metadata
        blob.patch()
        return token_value

    async def upload_file(
        self,
        object_name: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
        cache_control: Optional[str] = None,
    ) -> str:
        try:
            bucket = self._ensure_bucket()
            loop = asyncio.get_event_loop()

            def _upload() -> str:
                blob = bucket.blob(object_name)
                blob.content_type = content_type
                blob.cache_control = cache_control
                blob.metadata = {"firebaseStorageDownloadTokens": uuid4().hex}
                blob.upload_from_string(file_data, content_type=content_type)
                logger.info(f"Uploaded {object_name} to bucket {settings.FIREBASE_STORAGE_BUCKET}")
                return object_name

            return await loop.run_in_executor(None, _upload)
        except Exception as e:
            logger.error(f"Failed to upload {object_name}: {e}")
            raise

    async def download_file(
        self,
        object_name: str,
        local_path: Optional[str] = None,
    ) -> bytes | str:
        try:
            bucket = self._ensure_bucket()
            loop = asyncio.get_event_loop()

            def _download() -> bytes:
                blob = bucket.blob(object_name)
                return blob.download_as_bytes()

            file_data = await loop.run_in_executor(None, _download)

            if local_path:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(file_data)
                logger.info(f"Downloaded {object_name} to {local_path}")
                return local_path

            return file_data
        except Exception as e:
            logger.error(f"Failed to download {object_name}: {e}")
            raise

    async def delete_file(self, object_name: str) -> None:
        try:
            bucket = self._ensure_bucket()
            loop = asyncio.get_event_loop()

            def _delete() -> None:
                bucket.blob(object_name).delete()
                logger.info(f"Deleted {object_name} from bucket {settings.FIREBASE_STORAGE_BUCKET}")

            await loop.run_in_executor(None, _delete)
        except Exception as e:
            logger.error(f"Failed to delete {object_name}: {e}")
            raise

    async def get_download_url(self, object_name: Optional[str]) -> Optional[str]:
        if not object_name:
            return None

        try:
            bucket = self._ensure_bucket()
            loop = asyncio.get_event_loop()

            def _resolve() -> str:
                blob = bucket.blob(object_name)
                mode = settings.FIREBASE_STORAGE_URL_MODE.strip().lower()
                if mode == "public_url":
                    return self._public_url(object_name)
                if mode == "signed_url":
                    return blob.generate_signed_url(
                        version="v4",
                        expiration=timedelta(seconds=settings.STORAGE_URL_TTL_SECONDS),
                        method="GET",
                    )

                blob.reload()
                token = self._ensure_download_token(blob)
                return self._firebase_download_url(object_name, token)

            return await loop.run_in_executor(None, _resolve)
        except Exception as e:
            logger.error(f"Failed to build download URL for {object_name}: {e}")
            if settings.FIREBASE_STORAGE_URL_MODE.strip().lower() == "public_url":
                return self._public_url(object_name)
            return None

    async def download_for_processing(self, object_name: str) -> str:
        local_path = str(Path(tempfile.gettempdir()) / f"{uuid4().hex}_{Path(object_name).name}")
        await self.download_file(object_name, local_path)
        return local_path

    async def upload_face_photo(self, user_id: int, file_data: bytes, filename: str = "photo.jpg") -> str:
        return await self.upload_file(
            object_name=self._build_object_name(settings.STORAGE_FACE_PREFIX, user_id, filename),
            file_data=file_data,
            content_type="image/jpeg",
            cache_control="private, max-age=3600",
        )

    async def upload_voice_sample(self, user_id: int, file_data: bytes, filename: str = "sample.wav") -> str:
        return await self.upload_file(
            object_name=self._build_object_name(settings.STORAGE_VOICE_SAMPLES_PREFIX, user_id, filename),
            file_data=file_data,
            content_type="audio/wav",
            cache_control="private, max-age=3600",
        )

    async def upload_voice_output(self, user_id: int, file_data: bytes, filename: str = "output.wav") -> str:
        return await self.upload_file(
            object_name=self._build_object_name(settings.STORAGE_VOICE_OUTPUT_PREFIX, user_id, filename),
            file_data=file_data,
            content_type="audio/wav",
            cache_control="private, max-age=3600",
        )

    async def upload_avatar_video(self, user_id: int, file_data: bytes, filename: str = "avatar.mp4") -> str:
        return await self.upload_file(
            object_name=self._build_object_name(settings.STORAGE_AVATARS_PREFIX, user_id, filename),
            file_data=file_data,
            content_type="video/mp4",
            cache_control="public, max-age=3600",
        )


storage_service = StorageService()
