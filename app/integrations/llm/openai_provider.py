from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.domain.models import CompletionRequest, CompletionResult, StructuredRequest

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    """OpenAI chat completions; also works with OpenAI-compatible local servers via base_url."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ) -> None:
        kwargs: dict = {"api_key": api_key or "not-needed"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = model

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        model = req.model or self._model
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.user})
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=req.temperature,
        )
        text = (response.choices[0].message.content or "").strip()
        return CompletionResult(text=text, model=model, raw=response.model_dump())

    async def structured(self, req: StructuredRequest, schema: type[T]) -> T:
        model = req.model or self._model
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        user = (
            f"{req.user}\n\n"
            f"Respond with JSON matching this schema only, no markdown:\n{schema_json}"
        )
        messages.append({"role": "user", "content": user})
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=req.temperature,
            response_format={"type": "json_object"},
        )
        text = (response.choices[0].message.content or "{}").strip()
        return schema.model_validate_json(text)


class OpenAITranscriptionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "whisper-1",
        base_url: str | None = None,
    ) -> None:
        kwargs: dict = {"api_key": api_key or "not-needed"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = model

    async def transcribe(self, audio_path: Path, language: str) -> str:
        with audio_path.open("rb") as audio_file:
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=audio_file,
                language=language,
            )
        return result.text.strip()
