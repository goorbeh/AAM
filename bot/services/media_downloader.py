"""Downloads video/audio from YouTube, SoundCloud, and Instagram via yt-dlp.

All blocking yt-dlp calls run inside asyncio.to_thread so the bot's event
loop is never blocked while a download is in progress.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)

# Telegram bots can only send files up to 50MB. We stay a little under that
# to leave room for caption/metadata overhead.
MAX_FILESIZE_BYTES = 49 * 1024 * 1024


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    is_audio: bool = False


def _build_ydl_opts(download_dir: Path, audio_only: bool, ffmpeg_location: Optional[str]) -> dict:
    output_template = str(download_dir / "%(id)s.%(ext)s")

    opts: dict = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "retries": 3,
        "socket_timeout": 30,
    }

    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location

    if audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        # Prefer a file that already fits Telegram's size limit; fall back
        # to the best available format if nothing under the limit exists.
        opts["format"] = (
            f"best[filesize<{MAX_FILESIZE_BYTES}][ext=mp4]/"
            f"best[filesize<{MAX_FILESIZE_BYTES}]/"
            "best[ext=mp4]/best"
        )

    return opts


async def download_media(
    url: str,
    download_dir: Path,
    audio_only: bool = False,
    ffmpeg_location: Optional[str] = None,
) -> DownloadResult:
    download_dir.mkdir(parents=True, exist_ok=True)
    opts = _build_ydl_opts(download_dir, audio_only, ffmpeg_location)

    def _run() -> DownloadResult:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    return DownloadResult(success=False, error="اطلاعاتی از این لینک پیدا نشد.")

                # extract_info can return a playlist-like dict in rare edge
                # cases even with noplaylist=True (e.g. single-item feeds).
                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        return DownloadResult(success=False, error="محتوایی برای دانلود پیدا نشد.")
                    info = entries[0]

                final_path = ydl.prepare_filename(info)
                if audio_only:
                    # The FFmpegExtractAudio postprocessor changes the
                    # extension to .mp3 after downloading the raw stream.
                    final_path = str(Path(final_path).with_suffix(".mp3"))

                if not os.path.exists(final_path):
                    return DownloadResult(success=False, error="فایل دانلودشده پیدا نشد.")

                size = os.path.getsize(final_path)
                if size > MAX_FILESIZE_BYTES:
                    os.remove(final_path)
                    return DownloadResult(
                        success=False,
                        error="حجم فایل بیشتر از محدودیت تلگرام (۵۰ مگابایت) است.",
                    )

                title = info.get("title") or "media"
                return DownloadResult(success=True, file_path=final_path, title=title, is_audio=audio_only)

        except yt_dlp.utils.DownloadError as e:
            logger.warning("yt-dlp download error for %s: %s", url, e)
            return DownloadResult(
                success=False,
                error="دانلود این لینک ممکن نشد (لینک خصوصی، حذف‌شده یا نامعتبر است).",
            )
        except Exception as e:  # noqa: BLE001 - convert ANY unexpected failure into a safe result
            logger.exception("Unexpected error downloading %s", url)
            return DownloadResult(success=False, error=f"خطای غیرمنتظره در دانلود: {e}")

    return await asyncio.to_thread(_run)
