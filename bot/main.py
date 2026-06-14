import logging
import tempfile
from pathlib import Path

from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import load_settings
from obsidian import ObsidianWriter
from transcribe import transcribe_audio

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("voice-to-obsidian")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Отправьте голосовое или аудиофайл — я транскрибирую его и сохраню отдельной заметкой в Dropbox."
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    settings = context.bot_data["settings"]
    openai_client: OpenAI = context.bot_data["openai_client"]
    writer: ObsidianWriter = context.bot_data["writer"]

    if message.voice:
        telegram_file = await message.voice.get_file()
        suffix = ".ogg"
    elif message.audio:
        telegram_file = await message.audio.get_file()
        suffix = Path(message.audio.file_name or "audio.mp3").suffix or ".mp3"
    else:
        await message.reply_text("Пришлите голосовое сообщение или аудиофайл.")
        return

    status = await message.reply_text("Слушаю и транскрибирую...")

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)

        await telegram_file.download_to_drive(custom_path=str(temp_path))
        text = transcribe_audio(openai_client, temp_path, settings.whisper_language)
        note_path = writer.save_transcript(text)

        preview = text if len(text) <= 500 else f"{text[:500]}..."
        await status.edit_text(f"Готово. Записано в `{note_path}`\n\n{preview}")
    except Exception:
        logger.exception("Failed to process audio message")
        await status.edit_text("Ошибка при обработке. Проверьте логи на сервере.")
    finally:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def main() -> None:
    settings = load_settings()
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .build()
    )

    application.bot_data["settings"] = settings
    application.bot_data["openai_client"] = OpenAI(api_key=settings.openai_api_key)
    application.bot_data["writer"] = ObsidianWriter(settings)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))

    logger.info("Bot started in polling mode")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
