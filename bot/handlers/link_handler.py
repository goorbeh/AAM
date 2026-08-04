import logging
import os
import uuid
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.services.link_detector import Platform, detect_platform, extract_url
from bot.services.media_downloader import MAX_FILESIZE_BYTES, download_media
from bot.services.spotify_service import (
    SpotifyService,
    SpotifyServiceError,
    download_spotify_track,
)

logger = logging.getLogger(__name__)


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # update.effective_message resolves to whichever of message /
    # edited_message / channel_post / edited_channel_post is actually set.
    # Using update.message directly here would silently do nothing for
    # channel posts, since Telegram delivers those in update.channel_post,
    # not update.message.
    message = update.effective_message
    if message is None or not message.text:
        return

    # Ignore anything the bot itself posted (e.g. its own future messages),
    # to avoid any risk of a feedback loop. Channel posts have no from_user
    # at all, so this check simply doesn't apply to them.
    if message.from_user is not None and message.from_user.id == context.bot.id:
        return

    url = extract_url(message.text)
    if not url:
        # Not a link at all - ignore silently instead of spamming errors
        # on every normal text message the bot receives in a group/channel.
        return

    platform = detect_platform(url)
    if platform == Platform.UNKNOWN:
        await message.reply_text(
            "این لینک رو نشناختم. فعلاً فقط از یوتیوب، ساندکلود، اسپاتیفای و اینستاگرام پشتیبانی می‌کنم."
        )
        return

    config = context.bot_data["config"]
    download_dir: Path = config.download_dir / uuid.uuid4().hex

    status_message = await message.reply_text("⏳ در حال دریافت محتوا...")
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
    except TelegramError:
        pass  # chat action failing is never worth interrupting the flow for

    try:
        if platform == Platform.SPOTIFY:
            await _handle_spotify(context, message, url, download_dir, status_message)
        elif platform == Platform.SOUNDCLOUD:
            await _handle_generic_audio(context, message, url, download_dir, status_message)
        else:  # YOUTUBE or INSTAGRAM
            await _handle_generic_video(context, message, url, download_dir, status_message)
    finally:
        _cleanup_dir(download_dir)


async def _handle_generic_video(context, message, url, download_dir, status_message) -> None:
    ffmpeg_location = context.bot_data.get("ffmpeg_location")
    result = await download_media(url, download_dir, audio_only=False, ffmpeg_location=ffmpeg_location)

    if not result.success or not result.file_path:
        await status_message.edit_text(f"❌ {result.error or 'دانلود ناموفق بود.'}")
        return

    await status_message.edit_text("📤 در حال ارسال...")
    with open(result.file_path, "rb") as f:
        # reply_video quotes the original link message automatically in
        # groups/channels, so the uploaded content stays tied to its link.
        await message.reply_video(video=f, caption=result.title, supports_streaming=True)
    await status_message.delete()


async def _handle_generic_audio(context, message, url, download_dir, status_message) -> None:
    ffmpeg_location = context.bot_data.get("ffmpeg_location")
    result = await download_media(url, download_dir, audio_only=True, ffmpeg_location=ffmpeg_location)

    if not result.success or not result.file_path:
        await status_message.edit_text(f"❌ {result.error or 'دانلود ناموفق بود.'}")
        return

    await status_message.edit_text("📤 در حال ارسال...")
    with open(result.file_path, "rb") as f:
        await message.reply_audio(audio=f, title=result.title)
    await status_message.delete()


async def _handle_spotify(context, message, url, download_dir, status_message) -> None:
    spotify_service: SpotifyService = context.bot_data.get("spotify_service")
    if spotify_service is None:
        await status_message.edit_text(
            "❌ قابلیت اسپاتیفای فعال نیست (SPOTIFY_CLIENT_ID/SECRET روی سرور تنظیم نشده)."
        )
        return

    ffmpeg_location = context.bot_data.get("ffmpeg_location")

    try:
        track_info = await spotify_service.get_track_info(url)
        await status_message.edit_text(
            f"🔎 در حال جستجوی «{track_info.title} - {track_info.artist}» ..."
        )
        mp3_path = await download_spotify_track(track_info, download_dir, ffmpeg_location=ffmpeg_location)
    except SpotifyServiceError as e:
        await status_message.edit_text(f"❌ {e}")
        return

    size = os.path.getsize(mp3_path)
    if size > MAX_FILESIZE_BYTES:
        await status_message.edit_text("❌ حجم فایل نهایی بیشتر از محدودیت تلگرام است.")
        return

    await status_message.edit_text("📤 در حال ارسال...")
    with open(mp3_path, "rb") as f:
        await message.reply_audio(audio=f, title=track_info.title, performer=track_info.artist)
    await status_message.delete()


def _cleanup_dir(download_dir: Path) -> None:
    try:
        if download_dir.exists():
            for child in download_dir.iterdir():
                child.unlink(missing_ok=True)
            download_dir.rmdir()
    except OSError:
        logger.exception("Failed to clean up download dir: %s", download_dir)
