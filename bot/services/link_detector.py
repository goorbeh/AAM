"""Detects which platform a URL belongs to (YouTube, Spotify, SoundCloud, Instagram)."""

import re
from enum import Enum
from typing import Optional


class Platform(Enum):
    YOUTUBE = "youtube"
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"
    INSTAGRAM = "instagram"
    UNKNOWN = "unknown"


# Order matters only in that each pattern must be specific enough not to
# collide with another platform's domain.
_PATTERNS = {
    Platform.YOUTUBE: re.compile(r"(?:youtube\.com|youtu\.be)", re.IGNORECASE),
    Platform.SPOTIFY: re.compile(r"open\.spotify\.com", re.IGNORECASE),
    Platform.SOUNDCLOUD: re.compile(r"soundcloud\.com", re.IGNORECASE),
    Platform.INSTAGRAM: re.compile(r"instagram\.com", re.IGNORECASE),
}

_URL_REGEX = re.compile(r"https?://\S+")


def extract_url(text: str) -> Optional[str]:
    """Finds the first http(s) URL inside a block of text, or None."""
    if not text:
        return None
    match = _URL_REGEX.search(text)
    return match.group(0) if match else None


def detect_platform(url: str) -> Platform:
    for platform, pattern in _PATTERNS.items():
        if pattern.search(url):
            return platform
    return Platform.UNKNOWN
