from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import WriteMode
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError, Timeout

logger = logging.getLogger("vault.dropbox")

_RETRYABLE = (SSLError, RequestsConnectionError, Timeout, ConnectionError, TimeoutError, OSError)


class DropboxVault:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        refresh_token: str,
        vault_path: str,
        timezone: str = "Asia/Bangkok",
        max_attempts: int = 5,
    ) -> None:
        self._dbx = dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )
        self._vault_path = vault_path.rstrip("/")
        self._timezone = ZoneInfo(timezone)
        self._max_attempts = max_attempts

    def note_path(self, moment: datetime | None = None) -> str:
        """Vault layout: {vault}/{YYYY-MM}/{DD}/{HH-MM-SS}.md (no per-user folder)."""
        moment = moment or datetime.now(self._timezone)
        month = moment.strftime("%Y-%m")
        day = moment.strftime("%d")
        filename = f"{moment.strftime('%H-%M-%S')}.md"
        return f"{self._vault_path}/{month}/{day}/{filename}"

    @staticmethod
    def format_note_markdown(*, heading: str, body: str, note_id) -> str:
        return f"# {heading}\n\n{body.strip()}\n\n---\nnote_id: `{note_id}`\n"

    def _with_retry(self, action: str, fn):
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return fn()
            except _RETRYABLE as exc:
                last_exc = exc
                logger.warning(
                    "Dropbox %s failed attempt %s/%s: %s",
                    action,
                    attempt,
                    self._max_attempts,
                    exc,
                )
                if attempt >= self._max_attempts:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
        assert last_exc is not None
        raise last_exc

    def upload_markdown(self, path: str, content: str, *, overwrite: bool = False) -> str:
        mode = WriteMode.overwrite if overwrite else WriteMode.add
        data = content.encode("utf-8")

        def _do() -> None:
            self._dbx.files_upload(data, path, mode=mode)

        self._with_retry(f"upload:{path}", _do)
        return path

    def download_text(self, path: str) -> str:
        def _do() -> str:
            _, response = self._dbx.files_download(path)
            return response.content.decode("utf-8")

        return self._with_retry(f"download:{path}", _do)

    def exists(self, path: str) -> bool:
        try:
            self._dbx.files_get_metadata(path)
            return True
        except ApiError:
            return False
