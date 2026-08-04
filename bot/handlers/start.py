from telegram import Update
from telegram.ext import ContextTypes

WELCOME_TEXT = (
    "سلام! 👋\n\n"
    "می‌تونی یکی از این کارها رو انجام بدی:\n\n"
    "🔗 یه لینک از یوتیوب، ساندکلود، اسپاتیفای یا اینستاگرام برام بفرست تا محتواشو دانلود کنم.\n"
    "🖼 یه عکس برام بفرست تا کیفیتشو با x2 یا x4 بهبود بدم.\n\n"
    "توجه: برای آهنگ‌های اسپاتیفای، فایل صوتی از یوتیوب پیدا و دانلود می‌شه "
    "(چون خود اسپاتیفای اجازه‌ی دانلود مستقیم نمی‌ده)، ولی اسم آهنگ/خواننده/کاور "
    "از اطلاعات واقعی اسپاتیفای گرفته می‌شه."
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(WELCOME_TEXT)
