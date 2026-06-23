"""
Supabase Storage abstraction for media files.

Handles uploading, downloading, and generating URLs for:
- Face photos
- Voice samples
- Voice output (generated audio)
- Avatar videos
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.logging import logger

try:
    import httpx
    from supabase import Client, create_client
except ImportError:
    httpx = None
    Client = None
    create_client = None


class StorageService:
    """Manages file uploads/downloads to Supabase Storage."""

    def __init__(self) -> None:
        self._client: Optional[Client] = None
        self._initialized = False

    def _ensure_client(self) -> Client:
        """Lazy-load Supabase client."""
        if not self._initialized:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
                raise RuntimeError("Supabase credentials not configured")
            try:
                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
                self._initialized = True
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                raise
        if self._client is None:
            raise RuntimeError("Failed to create Supabase client")
        return self._client

    async def upload_file(
        self,
        bucket_name: str,
        object_path: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload a file to Supabase Storage.
        
        Args:
            bucket_name: Bucket name (e.g., "face-photos")
            object_path: Path within bucket (e.g., "user_123/photo.jpg")
            file_data: File content as bytes
            content_type: MIME type
            
        Returns:
            Full object path in storage
        """
        try:
            client = self._ensure_client()
            loop = asyncio.get_event_loop()

            def _upload() -> str:
                response = client.storage.from_(bucket_name).upload(
                    object_path, file_data, {"content-type": content_type}
                )
                logger.info(f"Uploaded {object_path} to {bucket_name}")
                return object_path

            result = await loop.run_in_executor(None, _upload)
            return result
        except Exception as e:
            logger.error(f"Failed to upload {object_path}: {e}")
            raise

    async def download_file(
        self,
        bucket_name: str,
        object_path: str,
        local_path: Optional[str] = None,
    ) -> bytes | str:
        """
        Download a file from Supabase Storage.
        
        Args:
            bucket_name: Bucket name
            object_path: Path within bucket
            local_path: Optional path to save locally (for processing)
            
        Returns:
            File bytes if local_path is None, else path to downloaded file
        """
        try:
            client = self._ensure_client()
            loop = asyncio.get_event_loop()

            def _download() -> bytes:
                response = client.storage.from_(bucket_name).download(object_path)
                return response

            file_data = await loop.run_in_executor(None, _download)

            if local_path:
                Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(file_data)
                logger.info(f"Downloaded {object_path} to {local_path}")
                return local_path
            return file_data
        except Exception as e:
            logger.error(f"Failed to download {object_path}: {e}")
            raise

    async def delete_file(
        self,
        bucket_name: str,
        object_path: str,
    ) -> None:
        """Delete a file from Supabase Storage."""
        try:
            client = self._ensure_client()
            loop = asyncio.get_event_loop()

            def _delete() -> None:
                client.storage.from_(bucket_name).remove([object_path])
                logger.info(f"Deleted {object_path} from {bucket_name}")

            await loop.run_in_executor(None, _delete)
        except Exception as e:
            logger.error(f"Failed to delete {object_path}: {e}")
            raise

    async def get_public_url(
        self,
        bucket_name: str,
        object_path: str,
    ) -> str:
        """Get a public URL for a file (only works if bucket is public)."""
        try:
            client = self._ensure_client()
            loop = asyncio.get_event_loop()

            def _get_url() -> str:
                response = client.storage.from_(bucket_name).get_public_url(object_path)
                return response

            url = await loop.run_in_executor(None, _get_url)
            return url
        except Exception as e:
            logger.error(f"Failed to get public URL for {object_path}: {e}")
            raise

    async def get_signed_url(
        self,
        bucket_name: str,
        object_path: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """
        Get a signed URL for a private file.
        
        Args:
            bucket_name: Bucket name
            object_path: Path within bucket
            expires_in_seconds: How long the URL is valid (default 1 hour)
            
        Returns:
            Signed URL valid for the specified duration
        """
        try:
            client = self._ensure_client()
            loop = asyncio.get_event_loop()

            def _get_signed_url() -> str:
                response = client.storage.from_(bucket_name).create_signed_url(
                    object_path, expires_in_seconds
                )
                return response["signedURL"]

            url = await loop.run_in_executor(None, _get_signed_url)
            return url
        except Exception as e:
            logger.error(f"Failed to get signed URL for {object_path}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────
    # Specialized methods for common patterns
    # ─────────────────────────────────────────────────────────────────────

    async def upload_face_photo(
        self,
        user_id: int,
        file_data: bytes,
        filename: str = "photo.jpg",
    ) -> str:
        """Upload and return object path for a face photo."""
        object_path = f"user_{user_id}/{filename}"
        return await self.upload_file(
            bucket_name="face-photos",
            object_path=object_path,
            file_data=file_data,
            content_type="image/jpeg",
        )

    async def upload_voice_sample(
        self,
        user_id: int,
        file_data: bytes,
        filename: str = "sample.wav",
    ) -> str:
        """Upload and return object path for a voice sample."""
        object_path = f"user_{user_id}/{filename}"
        return await self.upload_file(
            bucket_name="voice-samples",
            object_path=object_path,
            file_data=file_data,
            content_type="audio/wav",
        )

    async def upload_voice_output(
        self,
        user_id: int,
        file_data: bytes,
        filename: str = "output.wav",
    ) -> str:
        """Upload and return object path for generated audio."""
        object_path = f"user_{user_id}/{filename}"
        return await self.upload_file(
            bucket_name="voice-output",
            object_path=object_path,
            file_data=file_data,
            content_type="audio/wav",
        )

    async def upload_avatar_video(
        self,
        user_id: int,
        file_data: bytes,
        filename: str = "avatar.mp4",
    ) -> str:
        """Upload and return object path for an avatar video."""
        object_path = f"user_{user_id}/{filename}"
        return await self.upload_file(
            bucket_name="avatars",
            object_path=object_path,
            file_data=file_data,
            content_type="video/mp4",
        )

    async def download_for_processing(
        self,
        bucket_name: str,
        object_path: str,
    ) -> str:
        """Download a file to /tmp for processing. Returns local path."""
        local_path = f"/tmp/{uuid4().hex}_{Path(object_path).name}"
        await self.download_file(bucket_name, object_path, local_path)
        return local_path

    async def get_voice_sample_url(
        self,
        user_id: int,
        voice_id: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Get a signed URL for a voice sample (private bucket)."""
        object_path = f"user_{user_id}/{voice_id}.wav"
        return await self.get_signed_url("voice-samples", object_path, expires_in_seconds)

    async def get_face_photo_url(
        self,
        user_id: int,
        filename: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Get a signed URL for a face photo (private bucket)."""
        object_path = f"user_{user_id}/{filename}"
        return await self.get_signed_url("face-photos", object_path, expires_in_seconds)

    async def get_voice_output_url(
        self,
        user_id: int,
        filename: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Get a signed URL for generated voice output."""
        object_path = f"user_{user_id}/{filename}"
        return await self.get_signed_url("voice-output", object_path, expires_in_seconds)

    async def get_avatar_url(
        self,
        user_id: int,
        filename: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Get a URL for an avatar video (may be public or signed)."""
        object_path = f"user_{user_id}/{filename}"
        # For now, use signed URLs; could switch to public after user makes twin public
        return await self.get_signed_url("avatars", object_path, expires_in_seconds)


storage_service = StorageService()
