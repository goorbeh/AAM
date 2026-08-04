import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import ConfigError, load_config
from bot.handlers.image_handler import handle_photo, handle_upscale_callback
from bot.handlers.link_handler import handle_link
from bot.handlers.start import start_command
from bot.services.spotify_service import SpotifyService
from bot.utils.task_queue import TaskQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _resolve_ffmpeg_location() -> str:
    """Uses the static ffmpeg binary bundled by imageio-ffmpeg, so the bot
    works even on hosts (like Render) that don't have ffmpeg installed
    system-wide - no apt/Dockerfile step required."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


async def _post_init(application: Application) -> None:
    task_queue: TaskQueue = application.bot_data["task_queue"]
    task_queue.start()
    logger.info("Bot started successfully.")


async def _post_shutdown(application: Application) -> None:
    task_queue: TaskQueue = application.bot_data.get("task_queue")
    if task_queue is not None:
        await task_queue.stop()


def main() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        logger.error("Configuration error: %s", e)
        raise SystemExit(1) from e

    config.download_dir.mkdir(parents=True, exist_ok=True)
    config.weights_dir.mkdir(parents=True, exist_ok=True)

    application = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    application.bot_data["config"] = config
    application.bot_data["task_queue"] = TaskQueue(max_concurrency=config.max_concurrent_upscales)
    application.bot_data["ffmpeg_location"] = _resolve_ffmpeg_location()

    if config.spotify_client_id and config.spotify_client_secret:
        application.bot_data["spotify_service"] = SpotifyService(
            config.spotify_client_id, config.spotify_client_secret
        )
    else:
        application.bot_data["spotify_service"] = None
        logger.warning("Spotify credentials not set; Spotify links will be rejected at runtime.")

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_upscale_callback, pattern=r"^upscale:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # "channel_post" is required for the bot to receive messages posted
    # directly in a channel (as opposed to a private chat or group, where
    # "message" is enough). Without it, the bot would silently receive
    # nothing at all when added to a channel.
    application.run_polling(allowed_updates=["message", "channel_post", "callback_query"])


if __name__ == "__main__":
    main()
