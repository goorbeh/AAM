"""Loads and validates all runtime configuration from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    telegram_token: str
    spotify_client_id: str
    spotify_client_secret: str
    download_dir: Path
    weights_dir: Path
    max_concurrent_upscales: int


def load_config() -> Config:
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_token:
        raise ConfigError("متغیر محیطی TELEGRAM_BOT_TOKEN تنظیم نشده است.")

    # Spotify is optional: if not set, Spotify links are simply rejected
    # gracefully at runtime instead of crashing the whole bot at startup.
    spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

    download_dir = Path(os.getenv("DOWNLOAD_DIR", "./downloads")).resolve()
    weights_dir = Path(os.getenv("WEIGHTS_DIR", "./weights")).resolve()

    raw_concurrency = os.getenv("MAX_CONCURRENT_UPSCALES", "1").strip()
    try:
        max_concurrent_upscales = int(raw_concurrency)
    except ValueError as e:
        raise ConfigError(
            f"MAX_CONCURRENT_UPSCALES باید یک عدد صحیح باشد، مقدار فعلی: '{raw_concurrency}'"
        ) from e

    if max_concurrent_upscales < 1:
        raise ConfigError("MAX_CONCURRENT_UPSCALES باید حداقل ۱ باشد.")

    return Config(
        telegram_token=telegram_token,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        download_dir=download_dir,
        weights_dir=weights_dir,
        max_concurrent_upscales=max_concurrent_upscales,
    )
