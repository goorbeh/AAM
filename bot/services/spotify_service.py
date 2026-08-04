"""Spotify integration.

Spotify's own API only ever exposes track METADATA (title, artist, album,
cover art, duration) plus an optional 30-second preview clip - it never
exposes full track audio, because playback streams are DRM-protected.

The realistic approach used here (and by virtually every "Spotify
downloader" that actually works): read the real metadata from Spotify,
then find the closest-matching upload on YouTube by title/artist and
duration, and download THAT as the audio source. The track is tagged with
the genuine Spotify metadata (title/artist/album/cover) regardless of
where the audio bytes came from.
"""

import asyncio
import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import spotipy
import yt_dlp
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
from mutagen.mp3 import MP3
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger(__name__)

_SPOTIFY_TRACK_URL_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?track/([a-zA-Z0-9]+)")

# How many seconds of difference between the Spotify track duration and a
# YouTube candidate's duration we're willing to accept as "the same song".
_DURATION_TOLERANCE_SECONDS = 6

_AUDIO_BITRATE = "192"  # kbps - see README for why this value was chosen


class SpotifyServiceError(Exception):
    """User-facing error message (already in Persian) about a Spotify lookup/download failure."""


@dataclass
class SpotifyTrackInfo:
    title: str
    artist: str
    album: str
    duration_ms: int
    cover_url: Optional[str]


class SpotifyService:
    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise SpotifyServiceError("Spotify client id/secret تنظیم نشده است.")
        auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        self._client = spotipy.Spotify(auth_manager=auth_manager)

    @staticmethod
    def extract_track_id(url: str) -> Optional[str]:
        match = _SPOTIFY_TRACK_URL_RE.search(url)
        return match.group(1) if match else None

    async def get_track_info(self, url: str) -> SpotifyTrackInfo:
        track_id = self.extract_track_id(url)
        if not track_id:
            raise SpotifyServiceError(
                "این لینک اسپاتیفای مربوط به یک ترک تکی نیست "
                "(پلی‌لیست/آلبوم فعلاً پشتیبانی نمی‌شود، فقط لینک یک آهنگ تکی)."
            )

        def _fetch():
            return self._client.track(track_id)

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception as e:  # noqa: BLE001
            logger.exception("Spotify API error while fetching track %s", track_id)
            raise SpotifyServiceError("دریافت اطلاعات از اسپاتیفای ممکن نشد.") from e

        if not data:
            raise SpotifyServiceError("ترک موردنظر در اسپاتیفای پیدا نشد.")

        artists = ", ".join(a["name"] for a in data.get("artists", []) if a.get("name"))
        images = data.get("album", {}).get("images") or []
        cover_url = images[0]["url"] if images else None

        return SpotifyTrackInfo(
            title=data.get("name") or "Unknown",
            artist=artists or "Unknown",
            album=(data.get("album") or {}).get("name") or "Unknown",
            duration_ms=data.get("duration_ms") or 0,
            cover_url=cover_url,
        )


def _search_youtube_candidates(query: str, ffmpeg_location: Optional[str], limit: int = 5) -> List[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "default_search": f"ytsearch{limit}",
        "skip_download": True,
    }
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location

    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(query, download=False)
        if not result:
            return []
        entries = result.get("entries") or []
        return [e for e in entries if e]


def _pick_best_match(candidates: List[dict], target_duration_ms: int) -> Optional[dict]:
    if not candidates:
        return None

    target_seconds = target_duration_ms / 1000
    best = None
    best_diff = float("inf")

    for entry in candidates:
        duration = entry.get("duration")
        if duration is None:
            continue
        diff = abs(duration - target_seconds)
        if diff < best_diff:
            best_diff = diff
            best = entry

    if best is not None and best_diff <= _DURATION_TOLERANCE_SECONDS:
        return best

    # Nothing matched closely enough by duration; fall back to the top
    # search result rather than silently returning a wrong-length track.
    return candidates[0]


async def download_spotify_track(
    track_info: SpotifyTrackInfo,
    download_dir: Path,
    ffmpeg_location: Optional[str] = None,
) -> str:
    """Finds the closest-matching YouTube upload and downloads it as a
    192kbps MP3, then tags it with the real Spotify metadata."""
    download_dir.mkdir(parents=True, exist_ok=True)
    query = f"{track_info.artist} - {track_info.title} audio"

    candidates = await asyncio.to_thread(_search_youtube_candidates, query, ffmpeg_location)
    match = _pick_best_match(candidates, track_info.duration_ms)
    if match is None:
        raise SpotifyServiceError("معادل مناسبی برای این آهنگ در یوتیوب پیدا نشد.")

    video_id = match.get("id")
    video_url = match.get("url") or match.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", track_info.title).strip("_")[:50] or "track"
    output_template = str(download_dir / f"{safe_name}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": _AUDIO_BITRATE,
        }],
    }
    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    def _download() -> str:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            raw_path = ydl.prepare_filename(info)
            return str(Path(raw_path).with_suffix(".mp3"))

    mp3_path = await asyncio.to_thread(_download)
    await _tag_mp3(mp3_path, track_info)
    return mp3_path


async def _tag_mp3(mp3_path: str, track_info: SpotifyTrackInfo) -> None:
    def _tag() -> None:
        audio = MP3(mp3_path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()

        audio.tags.add(TIT2(encoding=3, text=track_info.title))
        audio.tags.add(TPE1(encoding=3, text=track_info.artist))
        audio.tags.add(TALB(encoding=3, text=track_info.album))
        audio.save()

    try:
        await asyncio.to_thread(_tag)
    except Exception:
        # Tagging failure should never break the whole download - the user
        # still gets a playable file, just possibly without full metadata.
        logger.exception("Failed to tag mp3 file: %s", mp3_path)

    if track_info.cover_url:
        await _embed_cover(mp3_path, track_info.cover_url)


async def _embed_cover(mp3_path: str, cover_url: str) -> None:
    def _fetch_and_embed() -> None:
        with urllib.request.urlopen(cover_url, timeout=15) as resp:  # noqa: S310 - fixed Spotify CDN URL
            image_data = resp.read()

        audio = MP3(mp3_path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=image_data))
        audio.save()

    try:
        await asyncio.to_thread(_fetch_and_embed)
    except Exception:
        logger.exception("Failed to embed cover art for %s", mp3_path)
