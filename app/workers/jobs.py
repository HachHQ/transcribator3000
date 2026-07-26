from __future__ import annotations

import hashlib
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from arq import create_pool, cron
from arq.connections import ArqRedis
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Job, Note, User
from app.db.session import get_session_factory, init_engine
from app.domain.enums import NoteStatus
from app.integrations.llm.factory import build_llm_provider, build_transcription_provider
from app.integrations.storage.dropbox import DropboxVault
from app.integrations.storage.note_cache import NoteCache
from app.pipelines.status import transition_note
from app.services.classify import (
    apply_classification as apply_classification_service,
    format_proposal_text,
    propose_classification,
)
from app.services.credentials import build_dropbox_vault, build_google_clients, get_credential
from app.services.daily_brief import build_daily_brief
from app.services import postprocess as postprocess_service
from app.domain.enums import OAuthProvider
from app.services.users import get_telegram_id, list_users_with_telegram
from app.services.templates import get_system_prompt
from app.workers.settings import redis_settings

logger = logging.getLogger("vault.worker")


async def _send_telegram(token: str, chat_id: str | int, text: str, reply_markup=None) -> None:
    from telegram import Bot

    bot = Bot(token=token)
    await bot.send_message(
        chat_id=int(chat_id),
        text=text[:4000],
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def _mark_job(
    session,
    *,
    note_id: uuid.UUID,
    job_type: str,
    status: str,
    error: str | None = None,
) -> None:
    result = await session.execute(
        select(Job)
        .where(Job.note_id == note_id, Job.job_type == job_type)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job:
        job.status = status
        job.attempts = (job.attempts or 0) + 1
        job.error_message = error
        await session.commit()


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    from redis.asyncio import from_url

    ctx["settings"] = settings
    ctx["redis_raw"] = from_url(settings.redis_url, decode_responses=False)
    ctx["arq"] = await create_pool(redis_settings())
    ctx["cache"] = NoteCache(ctx["redis_raw"], default_ttl=settings.note_body_ttl_seconds)
    ctx["llm"] = build_llm_provider(settings)
    ctx["transcription"] = build_transcription_provider(settings)
    logger.info("Worker started")


async def shutdown(ctx: dict) -> None:
    redis_raw = ctx.get("redis_raw")
    if redis_raw is not None:
        await redis_raw.aclose()
    arq: ArqRedis | None = ctx.get("arq")
    if arq is not None:
        await arq.aclose()
    logger.info("Worker stopped")


async def transcribe_note(ctx: dict, note_id: str) -> None:
    settings = ctx["settings"]
    cache: NoteCache = ctx["cache"]
    transcription = ctx["transcription"]
    arq: ArqRedis = ctx["arq"]
    note_uuid = uuid.UUID(note_id)
    factory = get_session_factory()

    async with factory() as session:
        note = await session.get(Note, note_uuid)
        if note is None:
            logger.error("Note %s missing", note_id)
            return
        try:
            transition_note(note, NoteStatus.TRANSCRIBING)
            await session.commit()

            audio = await cache.get_audio(note_uuid)
            if not audio:
                raise RuntimeError("Audio missing from Redis cache")

            suffix = (note.meta or {}).get("audio_suffix", ".ogg")
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                temp_path = Path(tmp.name)
                temp_path.write_bytes(audio)

            try:
                text = await transcription.transcribe(temp_path, settings.whisper_language)
            finally:
                temp_path.unlink(missing_ok=True)

            await cache.set_body(note_uuid, text, ttl=settings.note_body_ttl_seconds)
            await cache.delete_audio(note_uuid)
            note.content_checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
            transition_note(note, NoteStatus.CACHED)
            await _mark_job(session, note_id=note_uuid, job_type="transcribe", status="done")
            session.add(
                Job(
                    user_id=note.user_id,
                    note_id=note.id,
                    job_type="upload_note",
                    status="queued",
                    payload={"note_id": note_id},
                )
            )
            await session.commit()
        except Exception as exc:
            logger.exception("transcribe failed for %s", note_id)
            transition_note(note, NoteStatus.FAILED, error=str(exc))
            await _mark_job(
                session,
                note_id=note_uuid,
                job_type="transcribe",
                status="failed",
                error=str(exc),
            )
            await session.commit()
            raise

    await arq.enqueue_job("upload_note", note_id)


async def upload_note(ctx: dict, note_id: str) -> None:
    settings = ctx["settings"]
    cache: NoteCache = ctx["cache"]
    arq: ArqRedis = ctx["arq"]
    note_uuid = uuid.UUID(note_id)
    factory = get_session_factory()

    async with factory() as session:
        note = await session.get(Note, note_uuid)
        if note is None:
            return
        try:
            body = await cache.get_body(note_uuid)
            if not body:
                raise RuntimeError("Body missing from Redis")

            vault = await build_dropbox_vault(session, note.user_id, settings)
            user = await session.get(User, note.user_id)
            tz = ZoneInfo(user.timezone if user else settings.timezone)
            moment = datetime.now(tz)
            path = vault.note_path(moment)
            heading = moment.strftime("%H:%M:%S")
            content = DropboxVault.format_note_markdown(
                heading=heading, body=body, note_id=note.id
            )
            vault.upload_markdown(path, content)
            note.dropbox_path = path
            transition_note(note, NoteStatus.UPLOADED)
            await cache.expire_body(note_uuid, settings.note_body_expire_after_upload_seconds)
            await _mark_job(session, note_id=note_uuid, job_type="upload_note", status="done")
            session.add(
                Job(
                    user_id=note.user_id,
                    note_id=note.id,
                    job_type="postprocess",
                    status="queued",
                    payload={"note_id": note_id},
                )
            )
            await session.commit()
        except Exception as exc:
            logger.exception("upload failed for %s", note_id)
            transition_note(note, NoteStatus.FAILED, error=str(exc))
            await _mark_job(
                session,
                note_id=note_uuid,
                job_type="upload_note",
                status="failed",
                error=str(exc),
            )
            await session.commit()
            raise

    await arq.enqueue_job("postprocess_note", note_id)


async def postprocess_note(ctx: dict, note_id: str) -> None:
    settings = ctx["settings"]
    cache: NoteCache = ctx["cache"]
    llm = ctx["llm"]
    arq: ArqRedis = ctx["arq"]
    note_uuid = uuid.UUID(note_id)
    factory = get_session_factory()

    async with factory() as session:
        note = await session.get(Note, note_uuid)
        if note is None:
            return
        try:
            vault = await build_dropbox_vault(session, note.user_id, settings)
            await postprocess_service.postprocess_note(
                session, cache, vault, llm, note_uuid, settings
            )
            await _mark_job(session, note_id=note_uuid, job_type="postprocess", status="done")
            session.add(
                Job(
                    user_id=note.user_id,
                    note_id=note.id,
                    job_type="classify_task",
                    status="queued",
                    payload={"note_id": note_id},
                )
            )
            await session.commit()
        except Exception as exc:
            logger.exception("postprocess failed for %s", note_id)
            if note:
                transition_note(note, NoteStatus.FAILED, error=str(exc))
            await _mark_job(
                session,
                note_id=note_uuid,
                job_type="postprocess",
                status="failed",
                error=str(exc),
            )
            await session.commit()
            raise

    await arq.enqueue_job("classify_task", note_id)


async def classify_task(ctx: dict, note_id: str) -> None:
    settings = ctx["settings"]
    cache: NoteCache = ctx["cache"]
    llm = ctx["llm"]
    note_uuid = uuid.UUID(note_id)
    factory = get_session_factory()

    async with factory() as session:
        note = await session.get(Note, note_uuid)
        if note is None:
            return
        try:
            google_connected = (
                await get_credential(session, note.user_id, OAuthProvider.GOOGLE)
            ) is not None

            fallback = None
            if not await cache.get_body(note_uuid) and note.dropbox_path:
                try:
                    vault = await build_dropbox_vault(session, note.user_id, settings)
                    raw = vault.download_text(note.dropbox_path)
                    lines = raw.splitlines()
                    if lines and lines[0].startswith("# "):
                        fallback = "\n".join(lines[2:]).strip() if len(lines) > 2 else raw
                    else:
                        fallback = raw
                except Exception:
                    logger.warning("Dropbox fallback read failed for %s", note_id)

            proposed = await propose_classification(
                session,
                cache,
                llm,
                note_uuid,
                google_connected=google_connected,
                dropbox_body_fallback=fallback,
            )
            await cache.expire_body(note_uuid, settings.note_body_expire_after_upload_seconds)
            await _mark_job(session, note_id=note_uuid, job_type="classify_task", status="done")

            telegram_id = await get_telegram_id(session, note.user_id)
            if not telegram_id or not settings.telegram_bot_token:
                return

            if proposed.awaiting_confirmation:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                text = format_proposal_text(note_uuid, proposed.classification)
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Подтвердить",
                                callback_data=f"cls:ok:{note_uuid}",
                            ),
                            InlineKeyboardButton(
                                "Пропустить",
                                callback_data=f"cls:no:{note_uuid}",
                            ),
                        ]
                    ]
                )
                await _send_telegram(
                    settings.telegram_bot_token,
                    telegram_id,
                    text,
                    reply_markup=keyboard,
                )
                note = await session.get(Note, note_uuid)
                if note:
                    note.meta = {**(note.meta or {}), "proposal_notified": True}
                    await session.commit()
            elif proposed.needs_google:
                await _send_telegram(
                    settings.telegram_bot_token,
                    telegram_id,
                    "Заметка обработана. Похоже на задачу/событие, но Google не подключён.\n"
                    "Подключите: /connections",
                )
            else:
                await _send_telegram(
                    settings.telegram_bot_token,
                    telegram_id,
                    f"Заметка `{note_uuid}` обработана (задач/событий не найдено).",
                )
        except Exception as exc:
            logger.exception("classify failed for %s", note_id)
            if note:
                transition_note(note, NoteStatus.FAILED, error=str(exc))
            await _mark_job(
                session,
                note_id=note_uuid,
                job_type="classify_task",
                status="failed",
                error=str(exc),
            )
            await session.commit()
            raise


async def apply_classification(ctx: dict, note_id: str) -> None:
    settings = ctx["settings"]
    note_uuid = uuid.UUID(note_id)
    factory = get_session_factory()

    async with factory() as session:
        note = await session.get(Note, note_uuid)
        if note is None:
            return
        try:
            calendar, tasks_client = await build_google_clients(session, note.user_id, settings)
            result = await apply_classification_service(
                session, calendar, tasks_client, note_uuid
            )
            session.add(
                Job(
                    user_id=note.user_id,
                    note_id=note.id,
                    job_type="apply_classification",
                    status="done",
                    payload={"note_id": note_id},
                )
            )
            await session.commit()

            telegram_id = await get_telegram_id(session, note.user_id)
            if telegram_id and settings.telegram_bot_token:
                links = []
                from sqlalchemy import select
                from app.db.models import TaskLink

                rows = await session.execute(select(TaskLink).where(TaskLink.note_id == note_uuid))
                for link in rows.scalars().all():
                    if link.external_url:
                        links.append(f"• {link.kind}: {link.external_url}")
                extra = "\n".join(links) if links else f"• {result.title or 'ok'}"
                await _send_telegram(
                    settings.telegram_bot_token,
                    telegram_id,
                    f"Создано в Google для `{note_uuid}`:\n{extra}",
                )
        except Exception as exc:
            logger.exception("apply_classification failed for %s", note_id)
            if note:
                transition_note(note, NoteStatus.FAILED, error=str(exc))
            session.add(
                Job(
                    user_id=note.user_id if note else None,
                    note_id=note_uuid,
                    job_type="apply_classification",
                    status="failed",
                    error_message=str(exc),
                    payload={"note_id": note_id},
                )
            )
            await session.commit()
            raise


async def daily_brief_user(ctx: dict, user_id: str) -> None:
    settings = ctx["settings"]
    llm = ctx["llm"]
    factory = get_session_factory()
    uid = uuid.UUID(user_id)

    async with factory() as session:
        user = await session.get(User, uid)
        if user is None:
            return
        telegram_id = await get_telegram_id(session, uid)
        if not telegram_id or not settings.telegram_bot_token:
            return
        try:
            calendar, tasks_client = await build_google_clients(session, uid, settings)
            brief_prompt = await get_system_prompt(session, uid, "brief")
            brief = await build_daily_brief(
                calendar=calendar,
                tasks=tasks_client,
                llm=llm,
                timezone_name=user.timezone or settings.timezone,
                system_prompt=brief_prompt,
                task_max_age_days=user.brief_task_max_age_days
                if user.brief_task_max_age_days is not None
                else 7,
            )
            await _send_telegram(settings.telegram_bot_token, telegram_id, brief.summary_text)
            session.add(
                Job(
                    user_id=uid,
                    note_id=None,
                    job_type="daily_brief_user",
                    status="done",
                    payload={"telegram_id": telegram_id},
                )
            )
            await session.commit()
        except Exception as exc:
            logger.exception("daily_brief_user failed for %s", user_id)
            await _send_telegram(
                settings.telegram_bot_token,
                telegram_id,
                f"Не удалось собрать сводку: {exc}",
            )
            raise


async def daily_manager(ctx: dict) -> None:
    """Hourly cron: send brief at user's local brief_hour with Redis daily dedupe."""
    settings = ctx["settings"]
    llm = ctx["llm"]
    redis_raw = ctx["redis_raw"]
    factory = get_session_factory()

    async with factory() as session:
        users = await list_users_with_telegram(session)
        for user, telegram_id in users:
            try:
                tz = ZoneInfo(user.timezone or settings.timezone)
            except Exception:
                tz = ZoneInfo(settings.timezone)
            now_local = datetime.now(tz)
            target_hour = user.brief_hour if user.brief_hour is not None else 7
            if now_local.hour != target_hour:
                continue
            day_key = now_local.date().isoformat()
            dedupe_key = f"brief:sent:{user.id}:{day_key}"
            if await redis_raw.get(dedupe_key):
                continue
            try:
                calendar, tasks_client = await build_google_clients(session, user.id, settings)
            except RuntimeError:
                continue
            try:
                brief_prompt = await get_system_prompt(session, user.id, "brief")
                brief = await build_daily_brief(
                    calendar=calendar,
                    tasks=tasks_client,
                    llm=llm,
                    timezone_name=user.timezone or settings.timezone,
                    system_prompt=brief_prompt,
                    task_max_age_days=user.brief_task_max_age_days
                    if user.brief_task_max_age_days is not None
                    else 7,
                )
                if settings.telegram_bot_token:
                    await _send_telegram(
                        settings.telegram_bot_token,
                        telegram_id,
                        brief.summary_text,
                    )
                await redis_raw.set(dedupe_key, b"1", ex=36 * 3600)
                session.add(
                    Job(
                        user_id=user.id,
                        note_id=None,
                        job_type="daily_manager",
                        status="done",
                        payload={
                            "telegram_id": telegram_id,
                            "day": day_key,
                            "brief_hour": target_hour,
                        },
                    )
                )
                await session.commit()
            except Exception:
                logger.exception("daily_manager failed for user %s", user.id)


class WorkerSettings:
    functions = [
        transcribe_note,
        upload_note,
        postprocess_note,
        classify_task,
        apply_classification,
        daily_brief_user,
        daily_manager,
    ]
    cron_jobs = [
        cron(daily_manager, minute={5}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = 5
    job_timeout = 600
    retry_jobs = True
