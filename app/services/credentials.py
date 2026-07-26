from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import OAuthCredential
from app.domain.enums import OAuthProvider
from app.integrations.dropbox_oauth import DropboxOAuth
from app.integrations.google.oauth import GoogleOAuth
from app.integrations.storage.dropbox import DropboxVault
from app.integrations.google.calendar import GoogleCalendarClient
from app.integrations.google.tasks import GoogleTasksClient
from app.security.tokens import TokenCipher, get_token_cipher


async def upsert_oauth_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: OAuthProvider,
    refresh_token: str,
    access_token: str | None = None,
    scopes: str = "",
    expires_at: datetime | None = None,
    account_email: str | None = None,
    cipher: TokenCipher | None = None,
) -> OAuthCredential:
    cipher = cipher or get_token_cipher()
    result = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user_id,
            OAuthCredential.provider == provider.value,
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        cred = OAuthCredential(
            user_id=user_id,
            provider=provider.value,
            refresh_token_enc=cipher.encrypt(refresh_token),
            access_token_enc=cipher.encrypt(access_token) if access_token else None,
            scopes=scopes,
            expires_at=expires_at,
            account_email=account_email,
        )
        session.add(cred)
    else:
        if refresh_token:
            cred.refresh_token_enc = cipher.encrypt(refresh_token)
        if access_token:
            cred.access_token_enc = cipher.encrypt(access_token)
        cred.scopes = scopes or cred.scopes
        cred.expires_at = expires_at
        if account_email:
            cred.account_email = account_email
    await session.commit()
    await session.refresh(cred)
    return cred


async def get_credential(
    session: AsyncSession,
    user_id: uuid.UUID,
    provider: OAuthProvider,
) -> OAuthCredential | None:
    result = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user_id,
            OAuthCredential.provider == provider.value,
        )
    )
    return result.scalar_one_or_none()


async def ensure_google_access_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings | None = None,
) -> tuple[str, str]:
    """Return (access_token, refresh_token), refreshing if needed."""
    settings = settings or get_settings()
    cipher = get_token_cipher(settings)
    cred = await get_credential(session, user_id, OAuthProvider.GOOGLE)
    if cred is None:
        raise RuntimeError("Google OAuth not connected for user")

    refresh_token = cipher.decrypt(cred.refresh_token_enc)
    access_token = cipher.decrypt(cred.access_token_enc) if cred.access_token_enc else None
    now = datetime.now(timezone.utc)
    needs_refresh = (
        not access_token
        or cred.expires_at is None
        or cred.expires_at <= now
    )
    if needs_refresh:
        oauth = GoogleOAuth(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
        )
        token = await oauth.refresh_access_token(refresh_token)
        access_token = token["access_token"]
        cred.access_token_enc = cipher.encrypt(access_token)
        cred.expires_at = GoogleOAuth.expires_at_from_token(token)
        await session.commit()
    assert access_token
    return access_token, refresh_token


async def build_dropbox_vault(
    session: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings | None = None,
) -> DropboxVault:
    settings = settings or get_settings()
    cipher = get_token_cipher(settings)
    cred = await get_credential(session, user_id, OAuthProvider.DROPBOX)
    if cred is None:
        raise RuntimeError("Dropbox OAuth not connected for user")
    from app.db.models import User

    user = await session.get(User, user_id)
    vault_path = (user.dropbox_vault_path if user else None) or settings.dropbox_vault_path_default
    refresh_token = cipher.decrypt(cred.refresh_token_enc)
    return DropboxVault(
        app_key=settings.dropbox_app_key,
        app_secret=settings.dropbox_app_secret,
        refresh_token=refresh_token,
        vault_path=vault_path,
        timezone=user.timezone if user else settings.timezone,
    )


async def build_google_clients(
    session: AsyncSession,
    user_id: uuid.UUID,
    settings: Settings | None = None,
) -> tuple[GoogleCalendarClient, GoogleTasksClient]:
    settings = settings or get_settings()
    access_token, refresh_token = await ensure_google_access_token(session, user_id, settings)
    calendar = GoogleCalendarClient.from_token(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    tasks = GoogleTasksClient.from_token(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    return calendar, tasks


def google_oauth_helper(settings: Settings | None = None) -> GoogleOAuth:
    settings = settings or get_settings()
    return GoogleOAuth(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )


def dropbox_oauth_helper(settings: Settings | None = None) -> DropboxOAuth:
    settings = settings or get_settings()
    return DropboxOAuth(
        app_key=settings.dropbox_app_key,
        app_secret=settings.dropbox_app_secret,
        redirect_uri=settings.dropbox_redirect_uri,
    )
