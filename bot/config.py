import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openai_api_key: str
    dropbox_vault_path: str
    whisper_language: str
    timezone: str
    dropbox_token: str | None = None
    dropbox_app_key: str | None = None
    dropbox_app_secret: str | None = None
    dropbox_refresh_token: str | None = None


def load_settings() -> Settings:
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    dropbox_vault_path = os.environ.get("DROPBOX_VAULT_PATH", "")

    missing = [
        name
        for name, value in {
            "TELEGRAM_BOT_TOKEN": telegram_token,
            "OPENAI_API_KEY": openai_api_key,
            "DROPBOX_VAULT_PATH": dropbox_vault_path,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    dropbox_token = os.environ.get("DROPBOX_TOKEN") or None
    dropbox_app_key = os.environ.get("DROPBOX_APP_KEY") or None
    dropbox_app_secret = os.environ.get("DROPBOX_APP_SECRET") or None
    dropbox_refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN") or None

    has_refresh = all([dropbox_app_key, dropbox_app_secret, dropbox_refresh_token])
    if not dropbox_token and not has_refresh:
        raise RuntimeError(
            "Set DROPBOX_TOKEN or DROPBOX_APP_KEY + DROPBOX_APP_SECRET + DROPBOX_REFRESH_TOKEN"
        )

    return Settings(
        telegram_token=telegram_token,
        openai_api_key=openai_api_key,
        dropbox_vault_path=dropbox_vault_path.rstrip("/"),
        whisper_language=os.environ.get("WHISPER_LANGUAGE", "ru"),
        timezone=os.environ.get("TIMEZONE", "Asia/Bangkok"),
        dropbox_token=dropbox_token,
        dropbox_app_key=dropbox_app_key,
        dropbox_app_secret=dropbox_app_secret,
        dropbox_refresh_token=dropbox_refresh_token,
    )
