# MirrorSelf backend image.
# Built on a slim Python base with the heavy ML deps (torch, TTS, opencv) installed
# so the same image works in dev and prod. For a leaner prod build, split this
# into a separate "ai" image and have the API image call it via HTTP.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for audio (libsndfile), image (libgl/libglib), and torch runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ffmpeg \
        libsndfile1 \
        libgl1 \
        libglib2.0-0 \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only torch first so the larger TTS deps can resolve quickly.
# Switch to cu118 wheels if you have an NVIDIA GPU and matching drivers.
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Copy source
COPY . .

# Create storage directories the app writes to
RUN mkdir -p /app/storage/voice_samples /app/storage/voice_output \
    /app/storage/face_photos /app/storage/avatars /app/logs

EXPOSE 8000

# Default: run uvicorn. Override CMD for worker / gunicorn deployments.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
