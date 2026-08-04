import logging
import uuid
from pathlib import Path
from typing import Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.services.image_upscaler import ImageUpscaleError, upscale_image

logger = logging.getLogger(__name__)

# Maps a short task id -> local file path of the original photo the user
# sent. Kept in memory only. We can't embed the full path in Telegram's
# callback_data because it has a strict ~64 byte size limit.
_pending_photos: Dict[str, Path] = {}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # See the comment in link_handler.handle_link: effective_message covers
    # channel posts too, whereas update.message would always be None there.
    message = update.effective_message
    if message is None:
        return

    if message.from_user is not None and message.from_user.id == context.bot.id:
        return

    photo = message.photo[-1] if message.photo else None
    document = message.document
    is_image_document = document is not None and (document.mime_type or "").startswith("image/")

    if photo is None and not is_image_document:
        return

    config = context.bot_data["config"]
    task_id = uuid.uuid4().hex[:12]
    save_dir = config.download_dir / "images"
    save_dir.mkdir(parents=True, exist_ok=True)

    if photo is not None:
        file_obj = await photo.get_file()
        extension = ".jpg"
    else:
        file_obj = await document.get_file()
        extension = Path(document.file_name or "image.jpg").suffix or ".jpg"

    local_path = save_dir / f"{task_id}{extension}"
    await file_obj.download_to_drive(custom_path=str(local_path))

    _pending_photos[task_id] = local_path

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("x2", callback_data=f"upscale:{task_id}:2"),
        InlineKeyboardButton("x4", callback_data=f"upscale:{task_id}:4"),
    ]])
    await message.reply_text("چقدر بزرگ‌تر و باکیفیت‌ترش کنم؟", reply_markup=keyboard)


async def handle_upscale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("❌ درخواست نامعتبر بود.")
        return

    _, task_id, scale_str = parts
    try:
        scale = int(scale_str)
    except ValueError:
        await query.edit_message_text("❌ درخواست نامعتبر بود.")
        return

    input_path = _pending_photos.pop(task_id, None)
    if input_path is None or not input_path.exists():
        await query.edit_message_text("❌ عکس اصلی دیگر در دسترس نیست، لطفاً دوباره ارسال کنید.")
        return

    await query.edit_message_text(f"⏳ در صف پردازش (x{scale})... ممکن است چند دقیقه طول بکشد.")

    config = context.bot_data["config"]
    task_queue = context.bot_data["task_queue"]
    chat_id = query.message.chat_id if query.message else None

    if chat_id is None:
        logger.error("Could not resolve chat_id for upscale task %s", task_id)
        return

    async def _job() -> None:
        output_path = input_path.with_name(f"{input_path.stem}_x{scale}{input_path.suffix}")
        try:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            except TelegramError:
                pass

            await upscale_image(str(input_path), str(output_path), scale, config.weights_dir)

            # Sent as a document (not a photo) on purpose: Telegram
            # re-compresses photos sent via send_photo, which would throw
            # away exactly the quality gain we just produced.
            with open(output_path, "rb") as f:
                await context.bot.send_document(chat_id=chat_id, document=f, filename=output_path.name)

        except ImageUpscaleError as e:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ {e}")
        except Exception:
            logger.exception("Unexpected error during upscale job for task %s", task_id)
            await context.bot.send_message(chat_id=chat_id, text="❌ خطای غیرمنتظره در پردازش تصویر.")
        finally:
            input_path.unlink(missing_ok=True)
            if output_path.exists():
                output_path.unlink(missing_ok=True)

    await task_queue.submit(lambda: _job())
