from __future__ import annotations

from datetime import datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.domain.models import CalendarEventDraft


class GoogleCalendarClient:
    def __init__(self, credentials: Credentials) -> None:
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    @classmethod
    def from_token(
        cls,
        *,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        token_uri: str = "https://oauth2.googleapis.com/token",
    ) -> GoogleCalendarClient:
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
        return cls(creds)

    def create_event(self, draft: CalendarEventDraft, calendar_id: str = "primary") -> dict[str, Any]:
        body = {
            "summary": draft.title,
            "description": draft.description or "",
            "start": {"dateTime": draft.start.isoformat()},
            "end": {"dateTime": draft.end.isoformat()},
        }
        return self._service.events().insert(calendarId=calendar_id, body=body).execute()

    def list_events(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        result = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])

    def freebusy(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[dict[str, str]]:
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": calendar_id}],
        }
        result = self._service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {})
        return calendars.get(calendar_id, {}).get("busy", [])
