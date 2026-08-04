# syntax=docker/dockerfile:1
FROM python:3.11-slim

# --- System deps ---
# build-essential: some pinned wheels (basicsr/facexlib/gfpgan deps) need a
#   compiler for a couple of small extensions.
# libgl1 / libglib2.0-0: opencv-python-headless still dlopen()s these at
#   import time on Debian slim even though it's the "headless" build.
# ffmpeg is intentionally NOT installed here - imageio-ffmpeg ships its own
#   static binary and bot/main.py points python-telegram-bot at that, so we
#   don't need a system package for it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOWNLOAD_DIR=/app/downloads \
    WEIGHTS_DIR=/app/weights

COPY requirements.txt .

# CPU-only torch/torchvision FIRST (see requirements.txt) - otherwise pip
# resolves a CUDA build that's ~2GB and irrelevant on Render.
RUN pip install --no-cache-dir \
        torch==2.0.1+cpu torchvision==0.15.2+cpu \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the Real-ESRGAN weights into the image at build time so they don't
# need to be re-downloaded (and the bot doesn't stall on first upscale
# request) every time Render spins up a fresh container.
RUN python scripts/download_models.py "$WEIGHTS_DIR"

RUN mkdir -p "$DOWNLOAD_DIR"

# This bot runs on long-polling (application.run_polling in bot/main.py),
# not a webhook/HTTP server - deploy it on Render as a "Background Worker",
# not a "Web Service" (there's no port to bind to).
CMD ["python", "run.py"]
