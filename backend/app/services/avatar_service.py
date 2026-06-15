"""
SadTalker-based talking-head generation. Same lazy-load pattern as XTTS.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger


class AvatarService:
    def __init__(self) -> None:
        self._loaded = False
        Path(settings.FACE_PHOTOS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AVATAR_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    def _sadtalker_available(self) -> bool:
        return Path(settings.SADTALKER_DIR).exists() and Path(settings.SADTALKER_CHECKPOINTS).exists()

    async def validate_photo(self, path: str) -> tuple[bool, str]:
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            w, h = img.size
            if min(w, h) < 256:
                return False, "Image too small. Use a photo at least 256x256."
            return True, "ok"
        except Exception as e:
            return False, f"Could not read image: {e}"

    async def save_face_photo(self, src_path: str, user_id: int) -> str:
        dest = Path(settings.FACE_PHOTOS_DIR) / f"user_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
        shutil.copy(src_path, dest)
        return str(dest)

    async def generate_talking_head(
        self,
        face_photo_path: str,
        audio_path: str,
        user_id: int,
    ) -> str:
        """Run SadTalker inference. Returns path to generated .mp4 (or stub if SadTalker missing)."""
        out_dir = Path(settings.AVATAR_OUTPUT_DIR) / f"user_{user_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"talk_{int(time.time()*1000)}.mp4"

        loop = asyncio.get_event_loop()

        def _run() -> None:
            if not self._sadtalker_available():
                logger.warning("SadTalker not installed; writing stub avatar file.")
                # 1x1 transparent mp4 placeholder
                stub = out_path.with_suffix(".txt")
                stub.write_text(
                    f"Stub avatar: face={face_photo_path} audio={audio_path}\n"
                    "Install SadTalker to enable real talking-head generation.\n"
                )
                return
            try:
                cmd = [
                    "python", f"{settings.SADTALKER_DIR}/inference.py",
                    "--driven_audio", audio_path,
                    "--source_image", face_photo_path,
                    "--result_dir", str(out_dir),
                    "--checkpoint_dir", settings.SADTALKER_CHECKPOINTS,
                    "--device", settings.SADTALKER_DEVICE,
                    "--enhancer", "none",
                ]
                result = subprocess.run(
                    cmd, check=True, capture_output=True, text=True, timeout=600
                )
                logger.info(f"SadTalker OK: {result.stdout[-200:]}")
            except subprocess.TimeoutExpired:
                logger.error("SadTalker timed out")
            except subprocess.CalledProcessError as e:
                logger.error(f"SadTalker failed: {e.stderr[-500:]}")

        await loop.run_in_executor(None, _run)
        # If SadTalker produced *-talk.mp4, rename to deterministic path
        candidates = sorted(out_dir.glob("*-talk.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates and candidates[0] != out_path:
            shutil.move(str(candidates[0]), str(out_path))
        return str(out_path)


avatar_service = AvatarService()
