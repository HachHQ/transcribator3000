from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_oauth_state_store, get_settings_dep
from app.api.oauth_state import OAuthStateStore
from app.config import Settings
from app.db.session import get_session
from app.domain.enums import OAuthProvider
from app.integrations.google.oauth import GoogleOAuth
from app.services.credentials import (
    dropbox_oauth_helper,
    google_oauth_helper,
    upsert_oauth_credential,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])


async def _resolve_user_id(
    *,
    store: OAuthStateStore,
    provider: str,
    token: str | None,
    user_id: uuid.UUID | None,
) -> uuid.UUID:
    if token:
        payload = await store.consume_connect_token(token)
        if not payload or payload.get("provider") != provider:
            raise HTTPException(400, "Invalid or expired connect token. Request a new link via /start")
        return uuid.UUID(payload["user_id"])
    if user_id is not None:
        return user_id
    raise HTTPException(400, "Provide token (preferred) or user_id")


@router.get("/google/start")
async def google_start(
    token: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    settings: Settings = Depends(get_settings_dep),
    store: OAuthStateStore = Depends(get_oauth_state_store),
) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(500, "GOOGLE_CLIENT_ID not configured")
    resolved = await _resolve_user_id(store=store, provider="google", token=token, user_id=user_id)
    state = await store.issue(user_id=resolved, provider="google")
    url = google_oauth_helper(settings).authorization_url(state)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    store: OAuthStateStore = Depends(get_oauth_state_store),
) -> HTMLResponse:
    payload = await store.consume(state)
    if not payload or payload.get("provider") != "google":
        raise HTTPException(400, "Invalid OAuth state")
    resolved = uuid.UUID(payload["user_id"])
    oauth = google_oauth_helper(settings)
    token_data = await oauth.exchange_code(code)
    refresh = token_data.get("refresh_token")
    if not refresh:
        raise HTTPException(400, "No refresh_token returned; revoke app access and retry")
    access = token_data.get("access_token")
    email = await oauth.fetch_email(access) if access else None
    await upsert_oauth_credential(
        session,
        user_id=resolved,
        provider=OAuthProvider.GOOGLE,
        refresh_token=refresh,
        access_token=access,
        scopes=" ".join(oauth.scopes),
        expires_at=GoogleOAuth.expires_at_from_token(token_data),
        account_email=email,
    )
    return HTMLResponse(
        "<html><body><h1>Google connected</h1><p>You can close this window.</p></body></html>"
    )


@router.get("/dropbox/start")
async def dropbox_start(
    token: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    settings: Settings = Depends(get_settings_dep),
    store: OAuthStateStore = Depends(get_oauth_state_store),
) -> RedirectResponse:
    if not settings.dropbox_app_key:
        raise HTTPException(500, "DROPBOX_APP_KEY not configured")
    resolved = await _resolve_user_id(store=store, provider="dropbox", token=token, user_id=user_id)
    state = await store.issue(user_id=resolved, provider="dropbox")
    url = dropbox_oauth_helper(settings).authorization_url(state)
    return RedirectResponse(url)


@router.get("/dropbox/callback")
async def dropbox_callback(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    store: OAuthStateStore = Depends(get_oauth_state_store),
) -> HTMLResponse:
    payload = await store.consume(state)
    if not payload or payload.get("provider") != "dropbox":
        raise HTTPException(400, "Invalid OAuth state")
    resolved = uuid.UUID(payload["user_id"])
    oauth = dropbox_oauth_helper(settings)
    token_data = await oauth.exchange_code(code)
    refresh = token_data.get("refresh_token")
    if not refresh:
        raise HTTPException(400, "No refresh_token from Dropbox")
    await upsert_oauth_credential(
        session,
        user_id=resolved,
        provider=OAuthProvider.DROPBOX,
        refresh_token=refresh,
        access_token=token_data.get("access_token"),
        scopes="files.content.write files.content.read",
    )
    return HTMLResponse(
        "<html><body><h1>Dropbox connected</h1><p>You can close this window.</p></body></html>"
    )
