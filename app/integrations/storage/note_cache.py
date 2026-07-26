from __future__ import annotations

import uuid

from redis.asyncio import Redis


class NoteCache:
    """Transient note body / audio cache in Redis. Bodies are never persisted in Postgres."""

    def __init__(self, redis: Redis, default_ttl: int = 72 * 3600) -> None:
        self._redis = redis
        self._default_ttl = default_ttl

    def _body_key(self, note_id: uuid.UUID) -> str:
        return f"note:{note_id}:body"

    def _audio_key(self, note_id: uuid.UUID) -> str:
        return f"note:{note_id}:audio"

    async def set_body(self, note_id: uuid.UUID, body: str, ttl: int | None = None) -> None:
        await self._redis.set(self._body_key(note_id), body, ex=ttl or self._default_ttl)

    async def get_body(self, note_id: uuid.UUID) -> str | None:
        value = await self._redis.get(self._body_key(note_id))
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def expire_body(self, note_id: uuid.UUID, ttl: int) -> None:
        await self._redis.expire(self._body_key(note_id), ttl)

    async def delete_body(self, note_id: uuid.UUID) -> None:
        await self._redis.delete(self._body_key(note_id))

    async def set_audio(self, note_id: uuid.UUID, data: bytes, ttl: int = 3600) -> None:
        await self._redis.set(self._audio_key(note_id), data, ex=ttl)

    async def get_audio(self, note_id: uuid.UUID) -> bytes | None:
        value = await self._redis.get(self._audio_key(note_id))
        if value is None:
            return None
        return value if isinstance(value, bytes) else bytes(value)

    async def delete_audio(self, note_id: uuid.UUID) -> None:
        await self._redis.delete(self._audio_key(note_id))
