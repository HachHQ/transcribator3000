from __future__ import annotations

from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.domain.models import TaskDraft


class GoogleTasksClient:
    def __init__(self, credentials: Credentials) -> None:
        self._service = build("tasks", "v1", credentials=credentials, cache_discovery=False)

    @classmethod
    def from_token(
        cls,
        *,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        token_uri: str = "https://oauth2.googleapis.com/token",
    ) -> GoogleTasksClient:
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
        return cls(creds)

    def create_task(self, draft: TaskDraft, tasklist_id: str = "@default") -> dict[str, Any]:
        body: dict[str, Any] = {"title": draft.title}
        if draft.notes:
            body["notes"] = draft.notes
        if draft.due:
            body["due"] = draft.due.isoformat()
        return self._service.tasks().insert(tasklist=tasklist_id, body=body).execute()

    def list_open_tasks(self, tasklist_id: str = "@default") -> list[dict[str, Any]]:
        result = (
            self._service.tasks()
            .list(tasklist=tasklist_id, showCompleted=False, showHidden=False)
            .execute()
        )
        return result.get("items", [])
