"""
XTTS-v2 voice cloning wrapper. We do NOT import coqui-tts at module load time
(it's heavy and not always installed in dev). The class is a thin facade that
exposes `synthesize` and `validate_sample`.

If XTTS is unavailable, falls back to a placeholder tone generation so the
rest of the app can run.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.logging import logger


class VoiceCloningService:
    """Lazy-loads XTTS on first call."""

    def __init__(self) -> None:
        self._tts = None
        self._loaded = False
        Path(settings.VOICE_SAMPLES_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.VOICE_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    def _load_model(self) -> None:
        if self._loaded:
            return
        try:
            from TTS.api import TTS  # type: ignore

            logger.info(f"Loading XTTS-v2 from {settings.XTTS_MODEL_DIR} on {settings.XTTS_DEVICE}")
            self._tts = TTS(
                model_path=settings.XTTS_MODEL_DIR,
                progress_bar=False,
            ).to(settings.XTTS_DEVICE)
            self._loaded = True
            logger.info("XTTS-v2 loaded")
        except Exception as e:
            logger.error(f"Failed to load XTTS-v2: {e}. Falling back to stub.")
            self._tts = None
            self._loaded = True  # don't retry forever

    async def validate_sample(self, path: str) -> tuple[bool, str]:
        """Confirm file is a readable audio file of >= 6 seconds."""
        try:
            import soundfile as sf  # type: ignore

            data, sr = sf.read(path)
            duration = len(data) / sr
            if duration < 6:
                return False, f"Audio too short ({duration:.1f}s). Need at least 6 seconds."
            if duration > 120:
                return False, f"Audio too long ({duration:.1f}s). Cap at 2 minutes."
            return True, "ok"
        except Exception as e:
            return False, f"Could not read audio: {e}"

    async def clone_voice(self, sample_path: str, user_id: int) -> str:
        """Store the voice sample and return a voice_id usable for synthesis."""
        voice_id = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
        dest = Path(settings.VOICE_SAMPLES_DIR) / f"{voice_id}.wav"
        # Normalise: try to convert any input to mono 24kHz wav
        try:
            import soundfile as sf
            import librosa  # type: ignore

            y, _ = librosa.load(sample_path, sr=settings.XTTS_SAMPLE_RATE, mono=True)
            sf.write(str(dest), y, settings.XTTS_SAMPLE_RATE)
        except Exception as e:
            logger.warning(f"Audio normalisation failed ({e}); copying as-is.")
            import shutil
            shutil.copy(sample_path, dest)
        logger.info(f"Voice cloned: {voice_id}")
        return voice_id

    async def synthesize(
        self,
        voice_id: Optional[str],
        text: str,
        language: str = "en",
    ) -> str:
        """Synthesise `text` in the user's voice. Returns the path to a wav file."""
        Path(settings.VOICE_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        out_path = Path(settings.VOICE_OUTPUT_DIR) / f"{voice_id or 'anon'}_{int(time.time()*1000)}.wav"
        loop = asyncio.get_event_loop()

        def _run() -> None:
            self._load_model()
            if self._tts is None or not voice_id:
                self._fallback_tone(str(out_path), duration_s=max(1.0, len(text) * 0.06))
                return
            sample = Path(settings.VOICE_SAMPLES_DIR) / f"{voice_id}.wav"
            if not sample.exists():
                logger.warning(f"Voice sample missing for {voice_id}; using fallback tone.")
                self._fallback_tone(str(out_path), duration_s=max(1.0, len(text) * 0.06))
                return
            try:
                self._tts.tts_to_file(
                    text=text,
                    file_path=str(out_path),
                    speaker_wav=str(sample),
                    language=language,
                )
            except Exception as e:
                logger.error(f"XTTS synthesis failed: {e}; using fallback tone.")
                self._fallback_tone(str(out_path), duration_s=max(1.0, len(text) * 0.06))

        await loop.run_in_executor(None, _run)
        return str(out_path)

    def _fallback_tone(self, path: str, duration_s: float) -> None:
        """Stub: emit a low-amplitude sine so the pipeline still produces a wav."""
        sr = settings.XTTS_SAMPLE_RATE
        t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
        wave = 0.05 * np.sin(2 * np.pi * 220 * t).astype(np.float32)
        import soundfile as sf
        sf.write(path, wave, sr)


voice_service = VoiceCloningService()
