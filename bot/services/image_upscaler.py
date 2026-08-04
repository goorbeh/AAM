"""Image super-resolution (x2 / x4) using Real-ESRGAN, CPU-only.

IMPORTANT COLOR-SPACE NOTE:
RealESRGANer.enhance() internally assumes the array you pass it is in BGR
channel order (it was designed around cv2.imread, which returns BGR) and
converts BGR->RGB internally before running the network, then converts
back RGB->BGR before returning. If you feed it a normal RGB array (e.g.
straight from PIL) without converting first, the model still "works" but
the red and blue channels end up swapped in the output - a silent color
bug. This module explicitly converts RGB -> BGR before calling enhance()
and BGR -> RGB after, so colors/brightness are preserved exactly as they
should be. The model itself only reconstructs detail/resolution; it does
not perform any color grading.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict

import numpy as np
import torch
from PIL import Image

logger = logging.getLogger(__name__)

# Caps the longest side of an input image. Protects a small, CPU-only,
# limited-RAM server (like a basic Render instance) from running out of
# memory or taking an unreasonably long time on huge images.
MAX_INPUT_DIMENSION = 2000

_MODEL_SPECS = {
    2: {"filename": "RealESRGAN_x2plus.pth", "num_block": 23},
    4: {"filename": "RealESRGAN_x4plus.pth", "num_block": 23},
}

# Populated lazily; keyed by scale (2 or 4).
_upsampler_cache: Dict[int, "RealESRGANer"] = {}  # type: ignore[name-defined]
_cache_lock = asyncio.Lock()


class ImageUpscaleError(Exception):
    """User-facing error message (already in Persian)."""


def _load_upsampler(scale: int, weights_dir: Path):
    # Imported lazily so that importing this module doesn't require torch/
    # basicsr/realesrgan to be installed unless upscaling is actually used.
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    spec = _MODEL_SPECS[scale]
    weights_path = weights_dir / spec["filename"]
    if not weights_path.exists():
        raise ImageUpscaleError(
            f"فایل مدل {spec['filename']} پیدا نشد. باید از قبل با "
            f"scripts/download_models.py در {weights_dir} دانلود شده باشد."
        )

    model = RRDBNet(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_block=spec["num_block"],
        num_grow_ch=32,
        scale=scale,
    )

    return RealESRGANer(
        scale=scale,
        model_path=str(weights_path),
        model=model,
        tile=200,     # bounds peak memory usage on CPU by processing in tiles
        tile_pad=10,
        pre_pad=0,
        half=False,   # fp16 ("half precision") is not supported on CPU
        device=torch.device("cpu"),
    )


async def _get_upsampler(scale: int, weights_dir: Path):
    if scale not in _MODEL_SPECS:
        raise ImageUpscaleError("مقیاس آپسکیل فقط ۲ یا ۴ پشتیبانی می‌شود.")

    async with _cache_lock:
        if scale not in _upsampler_cache:
            _upsampler_cache[scale] = await asyncio.to_thread(_load_upsampler, scale, weights_dir)
        return _upsampler_cache[scale]


async def upscale_image(input_path: str, output_path: str, scale: int, weights_dir: Path) -> str:
    """Upscales an image by `scale` (2 or 4), preserving colors/brightness.
    Returns the output_path on success, raises ImageUpscaleError on failure.
    """
    upsampler = await _get_upsampler(scale, weights_dir)

    def _process() -> str:
        img = Image.open(input_path)
        # Flatten to plain RGB: drops alpha channel if present (transparent
        # PNGs) and normalizes any other mode (palette, grayscale, etc).
        img = img.convert("RGB")

        if max(img.size) > MAX_INPUT_DIMENSION:
            raise ImageUpscaleError(
                f"ابعاد تصویر بیش از حد بزرگ است "
                f"(حداکثر {MAX_INPUT_DIMENSION}px در طولانی‌ترین ضلع)."
            )

        rgb_array = np.array(img)
        bgr_array = rgb_array[:, :, ::-1].copy()  # RGB -> BGR, see module docstring

        try:
            output_bgr, _ = upsampler.enhance(bgr_array, outscale=scale)
        except RuntimeError as e:
            logger.exception("Real-ESRGAN runtime error while processing %s", input_path)
            raise ImageUpscaleError(
                "پردازش تصویر با خطا مواجه شد (احتمالاً حافظه کافی روی سرور نبود)."
            ) from e

        # BGR -> RGB before saving with PIL. .copy() forces a contiguous,
        # positive-stride array - a reversed-channel view can otherwise
        # confuse PIL's buffer handling on some platforms.
        output_rgb = output_bgr[:, :, ::-1].copy()
        result_img = Image.fromarray(output_rgb)
        result_img.save(output_path, quality=95)
        return output_path

    return await asyncio.to_thread(_process)
