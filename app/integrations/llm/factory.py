from __future__ import annotations

from app.config import Settings, get_settings
from app.integrations.llm.local_provider import LocalOpenAICompatibleProvider
from app.integrations.llm.openai_provider import OpenAIProvider, OpenAITranscriptionProvider


def build_llm_provider(settings: Settings | None = None) -> OpenAIProvider:
    settings = settings or get_settings()
    if settings.openai_base_url and not settings.openai_api_key.startswith("sk-"):
        # Prefer local-compatible path when a custom base_url is set without a cloud key
        return LocalOpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            api_key=settings.openai_api_key or "not-needed",
        )
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        base_url=settings.openai_base_url,
    )


def build_transcription_provider(
    settings: Settings | None = None,
) -> OpenAITranscriptionProvider:
    settings = settings or get_settings()
    return OpenAITranscriptionProvider(
        api_key=settings.openai_api_key,
        model=settings.whisper_model,
        base_url=settings.openai_base_url,
    )
