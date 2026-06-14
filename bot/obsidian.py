from datetime import datetime
from zoneinfo import ZoneInfo

import dropbox
from dropbox.files import WriteMode

from config import Settings


class ObsidianWriter:
    def __init__(self, settings: Settings) -> None:
        if settings.dropbox_refresh_token:
            self._dbx = dropbox.Dropbox(
                oauth2_refresh_token=settings.dropbox_refresh_token,
                app_key=settings.dropbox_app_key,
                app_secret=settings.dropbox_app_secret,
            )
        else:
            self._dbx = dropbox.Dropbox(settings.dropbox_token)

        self._vault_path = settings.dropbox_vault_path
        self._timezone = ZoneInfo(settings.timezone)

    def _note_path(self, moment: datetime) -> str:
        month = moment.strftime("%Y-%m")
        day = moment.strftime("%d")
        filename = f"{moment.strftime('%H-%M-%S')}.md"
        return f"{self._vault_path}/{month}/{day}/{filename}"

    def save_transcript(self, text: str, moment: datetime | None = None) -> str:
        moment = moment or datetime.now(self._timezone)
        note_path = self._note_path(moment)
        heading = moment.strftime("%H:%M:%S")
        content = f"# {heading}\n\n{text}\n"

        self._dbx.files_upload(
            content.encode("utf-8"),
            note_path,
            mode=WriteMode.add,
        )
        return note_path
