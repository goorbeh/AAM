"""Downloads the Real-ESRGAN model weight files needed for image upscaling.

Usage:
    python scripts/download_models.py [target_dir]

target_dir defaults to ./weights (or the WEIGHTS_DIR env var if set).
Run this once during deployment/build, BEFORE the bot starts - the bot
itself never downloads models at runtime, so a slow/failed download here
never surprises a user mid-conversation.
"""

import os
import sys
import urllib.request
from pathlib import Path

# Official URLs from the xinntao/Real-ESRGAN GitHub releases.
MODELS = {
    "RealESRGAN_x4plus.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
    ),
    "RealESRGAN_x2plus.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
    ),
}


def download_models(weights_dir: Path) -> None:
    weights_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in MODELS.items():
        dest = weights_dir / filename
        if dest.exists() and dest.stat().st_size > 0:
            print(f"[skip] {filename} already exists at {dest}")
            continue

        print(f"[download] {filename} ...")
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            # Clean up a partial/corrupt file so a retry doesn't think it's done.
            if dest.exists():
                dest.unlink()
            print(f"[error] failed to download {filename}: {e}", file=sys.stderr)
            raise
        print(f"[done] {filename} -> {dest}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1])
    else:
        target_dir = Path(os.getenv("WEIGHTS_DIR", "./weights"))

    download_models(target_dir)
