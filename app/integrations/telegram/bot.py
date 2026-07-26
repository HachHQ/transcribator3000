from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from arq import create_pool
from redis.asyncio import from_url
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.api.oauth_state import OAuthStateStore
from app.config import get_settings
from app.db.session import get_session_factory, init_engine
from app.domain.enums import OAuthProvider
from app.integrations.storage.note_cache import NoteCache
from app.services.classify import skip_classification
from app.services.credentials import get_credential
from app.services.ingest import create_note_ingest
from app.services.templates import (
    DEFAULT_PROMPTS,
    PROMPT_KINDS,
    ensure_prompt_templates,
    get_system_prompt,
    parse_prompt_kind,
    preview_prompt,
    reset_system_prompt,
    set_system_prompt,
)
from app.services.users import (
    get_or_create_telegram_user,
    get_user_by_telegram_id,
    set_brief_hour,
    set_brief_task_max_age_days,
    set_timezone,
)
from app.workers.settings import redis_settings

logger = logging.getLogger("vault.telegram")

SET_PROMPT = 1

BOT_COMMANDS = [
    BotCommand("start", "Старт и статус подключений"),
    BotCommand("connections", "Dropbox / Google OAuth"),
    BotCommand("brief", "Сводка на сегодня"),
    BotCommand("settings", "Час сводки, TZ, фильтр задач"),
    BotCommand("prompts", "Промпты агента"),
    BotCommand("setprompt", "Изменить промпт notes|brief|classify"),
    BotCommand("resetprompt", "Сбросить промпт к дефолту"),
    BotCommand("setbriefhour", "Час ежедневной сводки (0–23)"),
    BotCommand("settimezone", "Таймзона, напр. Asia/Bangkok"),
    BotCommand("setbrieftaskage", "Макс. возраст задач в сводке (дни)"),
    BotCommand("status", "Последние заметки"),
    BotCommand("retry", "Повторить failed note_id"),
    BotCommand("cancel", "Отменить ввод промпта"),
]


def _telegram_url_buttons_allowed(base_url: str) -> bool:
    """Telegram rejects localhost / private hosts in inline keyboard URL buttons."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return False
    if host.endswith(".local"):
        return False
    return bool(host)


async def _oauth_links(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: UUID,
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    settings = context.bot_data["settings"]
    store: OAuthStateStore = context.bot_data["oauth_state_store"]
    base = settings.public_base_url.rstrip("/")
    dropbox_token = await store.issue_connect_token(user_id=user_id, provider="dropbox")
    google_token = await store.issue_connect_token(user_id=user_id, provider="google")
    dropbox_url = f"{base}/oauth/dropbox/start?token={dropbox_token}"
    google_url = f"{base}/oauth/google/start?token={google_token}"
    keyboard = None
    if _telegram_url_buttons_allowed(base):
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Подключить Dropbox", url=dropbox_url)],
                [InlineKeyboardButton("Подключить Google", url=google_url)],
            ]
        )
    return dropbox_url, google_url, keyboard


async def _connection_status_lines(session, user_id: UUID) -> list[str]:
    dropbox = await get_credential(session, user_id, OAuthProvider.DROPBOX)
    google = await get_credential(session, user_id, OAuthProvider.GOOGLE)
    dbx = "подключён" if dropbox else "нет"
    if dropbox and dropbox.account_email:
        dbx = f"подключён ({dropbox.account_email})"
    ggl = "подключён" if google else "нет"
    if google and google.account_email:
        ggl = f"подключён ({google.account_email})"
    return [f"Dropbox: {dbx}", f"Google: {ggl}"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    settings = context.bot_data["settings"]
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            timezone=settings.timezone,
        )
        status_lines = await _connection_status_lines(session, user.id)
    dropbox_url, google_url, keyboard = await _oauth_links(context, user.id)
    status_block = "\n".join(status_lines)
    if keyboard is None:
        text = (
            "Пришлите голосовое или аудио — сохраню в облако и прогоню через пайплайн.\n\n"
            f"Связи:\n{status_block}\n\n"
            "Команды: /connections /brief /prompts /settings /status /retry\n\n"
            "Telegram не принимает localhost в кнопках. Откройте ссылки в браузере "
            "на этой же машине (живут ~1 час):\n\n"
            f"Dropbox:\n{dropbox_url}\n\n"
            f"Google:\n{google_url}"
        )
    else:
        text = (
            "Пришлите голосовое или аудио — сохраню в облако и прогоню через пайплайн.\n\n"
            f"Связи:\n{status_block}\n\n"
            "Команды: /connections /brief /prompts /settings /status /retry\n\n"
            "Подключить или обновить облака — кнопками ниже."
        )
    await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)


async def connections_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    settings = context.bot_data["settings"]
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            timezone=settings.timezone,
        )
        status_lines = await _connection_status_lines(session, user.id)
    dropbox_url, google_url, keyboard = await _oauth_links(context, user.id)
    text = "Подключения:\n" + "\n".join(status_lines)
    if keyboard is None:
        text += f"\n\nDropbox:\n{dropbox_url}\n\nGoogle:\n{google_url}"
    await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)


async def prompts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    settings = context.bot_data["settings"]
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            timezone=settings.timezone,
        )
        await ensure_prompt_templates(session, user.id)
        lines = ["Ваши system-промпты агента:\n"]
        labels = {
            "notes": "notes — постобработка заметок",
            "brief": "brief — ежедневная сводка",
            "classify": "classify — задачи/события",
        }
        for kind in PROMPT_KINDS:
            prompt = await get_system_prompt(session, user.id, kind)
            lines.append(f"[{labels[kind]}]")
            lines.append(preview_prompt(prompt, 350))
            lines.append("")
        lines.append(
            "Изменить: /setprompt notes | /setprompt brief | /setprompt classify\n"
            "Сброс: /resetprompt notes (или brief / classify)"
        )
    await update.message.reply_text("\n".join(lines))


async def setprompt_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    kind = parse_prompt_kind(context.args[0] if context.args else None)
    if kind is None:
        await update.message.reply_text(
            "Использование: /setprompt notes | brief | classify",
        )
        return ConversationHandler.END
    context.user_data["prompt_kind"] = kind
    factory = get_session_factory()
    async with factory() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала /start")
            return ConversationHandler.END
        current = await get_system_prompt(session, user.id, kind)
    await update.message.reply_text(
        f"Пришлите новый system prompt для «{kind}» одним сообщением.\n\n"
        f"Сейчас:\n{preview_prompt(current, 500)}\n\n"
        "Отмена: /cancel",
    )
    return SET_PROMPT


async def setprompt_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None or not update.message.text:
        return SET_PROMPT
    kind = context.user_data.get("prompt_kind")
    if kind not in PROMPT_KINDS:
        await update.message.reply_text("Сессия сброшена. Снова: /setprompt notes")
        return ConversationHandler.END
    factory = get_session_factory()
    try:
        async with factory() as session:
            user = await get_user_by_telegram_id(session, update.effective_user.id)
            if not user:
                await update.message.reply_text("Сначала /start")
                return ConversationHandler.END
            await set_system_prompt(session, user.id, kind, update.message.text)
        await update.message.reply_text(f"Промпт «{kind}» сохранён.")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return SET_PROMPT
    except Exception as exc:
        logger.exception("setprompt failed")
        await update.message.reply_text(f"Ошибка: {exc}")
    context.user_data.pop("prompt_kind", None)
    return ConversationHandler.END


async def setprompt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Отменено.")
    context.user_data.pop("prompt_kind", None)
    return ConversationHandler.END


async def resetprompt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    kind = parse_prompt_kind(context.args[0] if context.args else None)
    if kind is None:
        await update.message.reply_text(
            "Использование: /resetprompt notes | brief | classify",
        )
        return
    factory = get_session_factory()
    async with factory() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала /start")
            return
        await reset_system_prompt(session, user.id, kind)
    await update.message.reply_text(
        f"Промпт «{kind}» сброшен к значению по умолчанию.\n\n"
        f"{preview_prompt(DEFAULT_PROMPTS[kind], 400)}"
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    settings = context.bot_data["settings"]
    factory = get_session_factory()
    async with factory() as session:
        user = await get_or_create_telegram_user(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            timezone=settings.timezone,
        )
        hour = user.brief_hour if user.brief_hour is not None else 7
        tz = user.timezone or settings.timezone
        age = user.brief_task_max_age_days if user.brief_task_max_age_days is not None else 7
    age_line = "без фильтра" if age <= 0 else f"не старше {age} дн. (по due/updated)"
    await update.message.reply_text(
        "Настройки сводки:\n"
        f"• таймзона: {tz}\n"
        f"• час ежедневной сводки: {hour:02d}:00 (локальное время)\n"
        f"• задачи в сводке: {age_line}\n\n"
        "Изменить:\n"
        "/setbriefhour 8\n"
        "/settimezone Asia/Bangkok\n"
        "/setbrieftaskage 7   (0 = показывать все открытые)\n"
        "Сейчас вручную: /brief"
    )


async def setbriefhour_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if not context.args:
        await update.message.reply_text("Использование: /setbriefhour 7  (0–23, локальное время)")
        return
    try:
        hour = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Час должен быть числом 0–23")
        return
    factory = get_session_factory()
    try:
        async with factory() as session:
            user = await get_user_by_telegram_id(session, update.effective_user.id)
            if not user:
                await update.message.reply_text("Сначала /start")
                return
            user = await set_brief_hour(session, user.id, hour)
        await update.message.reply_text(
            f"Ежедневная сводка будет приходить около {user.brief_hour:02d}:05 "
            f"по {user.timezone}."
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def setbrieftaskage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /setbrieftaskage 7\n"
            "Только задачи с due/updated за последние N дней. 0 = без фильтра."
        )
        return
    try:
        days = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Нужно целое число дней (0–3650)")
        return
    factory = get_session_factory()
    try:
        async with factory() as session:
            user = await get_user_by_telegram_id(session, update.effective_user.id)
            if not user:
                await update.message.reply_text("Сначала /start")
                return
            user = await set_brief_task_max_age_days(session, user.id, days)
        if user.brief_task_max_age_days <= 0:
            await update.message.reply_text("Фильтр возраста задач выключен — в сводку попадут все открытые.")
        else:
            await update.message.reply_text(
                f"В сводку попадут задачи не старше {user.brief_task_max_age_days} дн."
            )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def settimezone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /settimezone Asia/Bangkok\n"
            "Примеры: Europe/Moscow, Asia/Bangkok, UTC"
        )
        return
    tz_name = context.args[0]
    factory = get_session_factory()
    try:
        async with factory() as session:
            user = await get_user_by_telegram_id(session, update.effective_user.id)
            if not user:
                await update.message.reply_text("Сначала /start")
                return
            user = await set_timezone(session, user.id, tz_name)
        await update.message.reply_text(
            f"Таймзона: {user.timezone}. Сводка около {user.brief_hour:02d}:05 локального времени."
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def brief_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    factory = get_session_factory()
    arq = context.bot_data["arq"]
    async with factory() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала /start")
            return
        google = await get_credential(session, user.id, OAuthProvider.GOOGLE)
        if google is None:
            await update.message.reply_text(
                "Для сводки нужен Google Calendar/Tasks. Подключите: /connections"
            )
            return
        user_id = user.id
    await arq.enqueue_job("daily_brief_user", str(user_id))
    await update.message.reply_text("Собираю сводку на сегодня…")


async def retry_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if not context.args:
        await update.message.reply_text("Использование: /retry <note_id>")
        return
    try:
        note_id = UUID(context.args[0])
    except ValueError:
        await update.message.reply_text("note_id должен быть UUID")
        return

    from app.services.retry import retry_failed_note

    factory = get_session_factory()
    arq = context.bot_data["arq"]
    try:
        async with factory() as session:
            user = await get_user_by_telegram_id(session, update.effective_user.id)
            if not user:
                await update.message.reply_text("Сначала /start")
                return
            note = await retry_failed_note(session, arq, note_id=note_id, user_id=user.id)
        await update.message.reply_text(f"Повторно в очереди: `{note.id}` → {note.status}")
    except Exception as exc:
        await update.message.reply_text(f"Не удалось повторить: {exc}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    from sqlalchemy import select

    from app.db.models import Note

    factory = get_session_factory()
    async with factory() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала /start")
            return
        result = await session.execute(
            select(Note).where(Note.user_id == user.id).order_by(Note.created_at.desc()).limit(5)
        )
        notes = result.scalars().all()
    if not notes:
        await update.message.reply_text("Заметок пока нет.")
        return
    lines = [
        f"• {n.id} — {n.status}" + (f" (`{n.dropbox_path}`)" if n.dropbox_path else "") for n in notes
    ]
    await update.message.reply_text("Последние заметки:\n" + "\n".join(lines))


async def classification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    match = re.fullmatch(r"cls:(ok|no):([0-9a-fA-F-]{36})", query.data)
    if not match:
        await query.edit_message_text("Некорректная кнопка.")
        return
    action, note_id_raw = match.group(1), match.group(2)
    note_id = UUID(note_id_raw)
    factory = get_session_factory()
    arq = context.bot_data["arq"]

    async with factory() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if not user:
            await query.edit_message_text("Сначала /start")
            return
        from app.db.models import Note

        note = await session.get(Note, note_id)
        if note is None or note.user_id != user.id:
            await query.edit_message_text("Заметка не найдена.")
            return

        if action == "no":
            try:
                await skip_classification(session, note_id)
            except Exception as exc:
                await query.edit_message_text(f"Не удалось пропустить: {exc}")
                return
            await query.edit_message_text(f"Пропущено. Заметка `{note_id}` без Google.")
            return

        # ok
        await arq.enqueue_job("apply_classification", str(note_id))
        await query.edit_message_text(f"Принято. Создаю в Google для `{note_id}`…")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or update.effective_user is None:
        return

    settings = context.bot_data["settings"]
    cache: NoteCache = context.bot_data["cache"]
    arq = context.bot_data["arq"]

    if message.voice:
        telegram_file = await message.voice.get_file()
        suffix = ".ogg"
    elif message.audio:
        telegram_file = await message.audio.get_file()
        suffix = Path(message.audio.file_name or "audio.mp3").suffix or ".mp3"
    else:
        await message.reply_text("Пришлите голосовое сообщение или аудиофайл.")
        return

    status = await message.reply_text("Принято, ставлю в очередь…")

    try:
        raw = await telegram_file.download_as_bytearray()
        factory = get_session_factory()
        async with factory() as session:
            user = await get_or_create_telegram_user(
                session,
                telegram_user_id=update.effective_user.id,
                display_name=update.effective_user.full_name,
                timezone=settings.timezone,
            )
            dropbox = await get_credential(session, user.id, OAuthProvider.DROPBOX)
            if dropbox is None:
                dropbox_url, _, keyboard = await _oauth_links(context, user.id)
                if keyboard is None:
                    await status.edit_text(
                        "Сначала подключите Dropbox (откройте в браузере на этой машине):\n"
                        f"{dropbox_url}",
                        disable_web_page_preview=True,
                    )
                else:
                    await status.edit_text(
                        "Сначала подключите Dropbox кнопкой ниже.",
                        reply_markup=keyboard,
                    )
                return
            note = await create_note_ingest(
                session,
                cache,
                arq,
                user_id=user.id,
                audio_bytes=bytes(raw),
                audio_suffix=suffix,
                settings=settings,
            )
            google = await get_credential(session, user.id, OAuthProvider.GOOGLE)
        hint = "" if google else "\nGoogle не подключён — задачи в Calendar/Tasks не создадутся (/connections)."
        await status.edit_text(f"В очереди. note_id=`{note.id}`{hint}")
    except Exception:
        logger.exception("Failed to enqueue audio")
        await status.edit_text("Ошибка при постановке в очередь. Проверьте логи.")


async def _post_init(application: Application) -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    redis = from_url(settings.redis_url, decode_responses=False)
    arq = await create_pool(redis_settings())
    application.bot_data["settings"] = settings
    application.bot_data["redis"] = redis
    application.bot_data["arq"] = arq
    application.bot_data["cache"] = NoteCache(redis, default_ttl=settings.note_body_ttl_seconds)
    application.bot_data["oauth_state_store"] = OAuthStateStore(redis)
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Registered %s bot menu commands", len(BOT_COMMANDS))


async def _post_shutdown(application: Application) -> None:
    redis = application.bot_data.get("redis")
    arq = application.bot_data.get("arq")
    if redis is not None:
        await redis.aclose()
    if arq is not None:
        await arq.aclose()


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("connections", connections_cmd))
    application.add_handler(CommandHandler("prompts", prompts_cmd))
    application.add_handler(CommandHandler("resetprompt", resetprompt_cmd))
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("setprompt", setprompt_entry)],
            states={
                SET_PROMPT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, setprompt_receive),
                ],
            },
            fallbacks=[CommandHandler("cancel", setprompt_cancel)],
            allow_reentry=True,
        )
    )
    application.add_handler(CommandHandler("brief", brief_cmd))
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(CommandHandler("setbriefhour", setbriefhour_cmd))
    application.add_handler(CommandHandler("setbrieftaskage", setbrieftaskage_cmd))
    application.add_handler(CommandHandler("settimezone", settimezone_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("retry", retry_cmd))
    application.add_handler(CallbackQueryHandler(classification_callback, pattern=r"^cls:(ok|no):"))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    return application


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
    )
    app = build_application()
    logger.info("Telegram bot started (polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
