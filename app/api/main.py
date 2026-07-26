from __future__ import annotations

import logging

import uvicorn
from arq import create_pool
from fastapi import FastAPI
from redis.asyncio import from_url

from app.api.oauth_state import OAuthStateStore
from app.api.routes_health import router as health_router
from app.api.routes_oauth import router as oauth_router
from app.config import get_settings
from app.db.session import init_engine
from app.workers.settings import redis_settings

logger = logging.getLogger("vault.api")


def create_app() -> FastAPI:
    app = FastAPI(title="LLM Vault", version="0.2.0")
    app.include_router(health_router)
    app.include_router(oauth_router)

    @app.on_event("startup")
    async def _startup() -> None:
        settings = get_settings()
        init_engine(settings.database_url)
        app.state.settings = settings
        app.state.redis = from_url(settings.redis_url, decode_responses=False)
        app.state.arq = await create_pool(redis_settings())
        app.state.oauth_state_store = OAuthStateStore(app.state.redis)
        logger.info("API started")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await app.state.redis.aclose()
        await app.state.arq.aclose()

    return app


app = create_app()


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
    )
    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
