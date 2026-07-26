from __future__ import annotations

import json
import secrets
import uuid

from redis.asyncio import Redis


class OAuthStateStore:
    def __init__(self, redis: Redis, ttl: int = 600, connect_ttl: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl
        self._connect_ttl = connect_ttl

    async def issue(self, *, user_id: uuid.UUID, provider: str) -> str:
        state = secrets.token_urlsafe(24)
        payload = json.dumps({"user_id": str(user_id), "provider": provider})
        await self._redis.set(f"oauth:state:{state}", payload, ex=self._ttl)
        return state

    async def consume(self, state: str) -> dict | None:
        return await self._consume_key(f"oauth:state:{state}")

    async def issue_connect_token(self, *, user_id: uuid.UUID, provider: str) -> str:
        """Short opaque token for Telegram links (avoids UUID truncation in clients)."""
        token = secrets.token_urlsafe(16)
        payload = json.dumps({"user_id": str(user_id), "provider": provider})
        await self._redis.set(f"oauth:connect:{token}", payload, ex=self._connect_ttl)
        return token

    async def consume_connect_token(self, token: str) -> dict | None:
        return await self._consume_key(f"oauth:connect:{token}")

    async def _consume_key(self, key: str) -> dict | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
