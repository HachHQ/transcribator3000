from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Identity, User
from app.domain.enums import IdentityProvider
from app.services.templates import ensure_default_template


async def get_or_create_telegram_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str | None = None,
    timezone: str = "Asia/Bangkok",
) -> User:
    external_id = str(telegram_user_id)
    result = await session.execute(
        select(Identity)
        .options(selectinload(Identity.user))
        .where(
            Identity.provider == IdentityProvider.TELEGRAM.value,
            Identity.external_id == external_id,
        )
    )
    identity = result.scalar_one_or_none()
    if identity:
        return identity.user

    user = User(display_name=display_name, timezone=timezone)
    session.add(user)
    await session.flush()
    session.add(
        Identity(
            user_id=user.id,
            provider=IdentityProvider.TELEGRAM.value,
            external_id=external_id,
            meta={"display_name": display_name},
        )
    )
    await session.commit()
    await session.refresh(user)
    await ensure_default_template(session, user.id)
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_telegram_id(session: AsyncSession, telegram_user_id: int) -> User | None:
    result = await session.execute(
        select(Identity)
        .options(selectinload(Identity.user))
        .where(
            Identity.provider == IdentityProvider.TELEGRAM.value,
            Identity.external_id == str(telegram_user_id),
        )
    )
    identity = result.scalar_one_or_none()
    return identity.user if identity else None


async def list_users_with_telegram(session: AsyncSession) -> list[tuple[User, str]]:
    result = await session.execute(
        select(User, Identity.external_id)
        .join(Identity, Identity.user_id == User.id)
        .where(Identity.provider == IdentityProvider.TELEGRAM.value)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_telegram_id(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    result = await session.execute(
        select(Identity.external_id).where(
            Identity.user_id == user_id,
            Identity.provider == IdentityProvider.TELEGRAM.value,
        )
    )
    return result.scalar_one_or_none()


async def set_brief_hour(session: AsyncSession, user_id: uuid.UUID, hour: int) -> User:
    if hour < 0 or hour > 23:
        raise ValueError("Час должен быть от 0 до 23")
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("User not found")
    user.brief_hour = hour
    await session.commit()
    await session.refresh(user)
    return user


async def set_brief_task_max_age_days(
    session: AsyncSession,
    user_id: uuid.UUID,
    days: int,
) -> User:
    if days < 0 or days > 3650:
        raise ValueError("Число дней должно быть от 0 до 3650 (0 = без фильтра)")
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("User not found")
    user.brief_task_max_age_days = days
    await session.commit()
    await session.refresh(user)
    return user


async def set_timezone(session: AsyncSession, user_id: uuid.UUID, timezone_name: str) -> User:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"Неизвестная таймзона: {timezone_name}") from exc
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("User not found")
    user.timezone = timezone_name
    await session.commit()
    await session.refresh(user)
    return user
