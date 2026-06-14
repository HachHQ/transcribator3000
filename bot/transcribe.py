from pathlib import Path

from openai import OpenAI


def transcribe_audio(client: OpenAI, audio_path: Path, language: str) -> str:
    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,
        )
    return result.text.strip()
