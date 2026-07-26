from __future__ import annotations

from fastapi import Request

from app.api.oauth_state import OAuthStateStore
from app.config import Settings, get_settings


def get_settings_dep() -> Settings:
    return get_settings()


def get_oauth_state_store(request: Request) -> OAuthStateStore:
    return request.app.state.oauth_state_store
