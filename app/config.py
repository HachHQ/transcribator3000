from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    database_url: str = Field(
        default="postgresql+asyncpg://vault:vault@localhost:5432/vault",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    token_encryption_key: str = Field(default="", alias="TOKEN_ENCRYPTION_KEY")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    timezone: str = Field(default="Asia/Bangkok", alias="TIMEZONE")

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # OpenAI / LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    whisper_model: str = Field(default="whisper-1", alias="WHISPER_MODEL")
    whisper_language: str = Field(default="ru", alias="WHISPER_LANGUAGE")

    # Dropbox app
    dropbox_app_key: str = Field(default="", alias="DROPBOX_APP_KEY")
    dropbox_app_secret: str = Field(default="", alias="DROPBOX_APP_SECRET")
    # Empty → derived from PUBLIC_BASE_URL + /oauth/dropbox/callback
    dropbox_redirect_uri: str = Field(default="", alias="DROPBOX_REDIRECT_URI")
    dropbox_vault_path_default: str = Field(
        default="/Obsidian/MyVault",
        alias="DROPBOX_VAULT_PATH",
    )

    # Google app
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    # Empty → derived from PUBLIC_BASE_URL + /oauth/google/callback
    google_redirect_uri: str = Field(default="", alias="GOOGLE_REDIRECT_URI")

    # Cache / pipeline
    note_body_ttl_seconds: int = Field(default=72 * 3600, alias="NOTE_BODY_TTL_SECONDS")
    audio_cache_ttl_seconds: int = Field(default=3600, alias="AUDIO_CACHE_TTL_SECONDS")
    note_body_expire_after_upload_seconds: int = Field(
        default=3600,
        alias="NOTE_BODY_EXPIRE_AFTER_UPLOAD_SECONDS",
    )

    @model_validator(mode="after")
    def derive_oauth_redirects(self) -> "Settings":
        base = self.public_base_url.rstrip("/")

        def _is_stale_localhost(redirect: str) -> bool:
            if not redirect:
                return True
            # Footgun: PUBLIC_BASE_URL is public, but redirect still points at localhost
            local_markers = ("://localhost", "://127.0.0.1", "://0.0.0.0")
            public_is_local = any(m in base for m in local_markers)
            redirect_is_local = any(m in redirect for m in local_markers)
            return redirect_is_local and not public_is_local

        if _is_stale_localhost(self.dropbox_redirect_uri):
            self.dropbox_redirect_uri = f"{base}/oauth/dropbox/callback"
        if _is_stale_localhost(self.google_redirect_uri):
            self.google_redirect_uri = f"{base}/oauth/google/callback"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

