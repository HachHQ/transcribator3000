from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


class DropboxOAuth:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        redirect_uri: str,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.app_key,
            "response_type": "code",
            "token_access_type": "offline",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{DROPBOX_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                DROPBOX_TOKEN_URL,
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                auth=(self.app_key, self.app_secret),
            )
            response.raise_for_status()
            return response.json()
