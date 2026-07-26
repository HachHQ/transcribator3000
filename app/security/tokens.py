from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings


class TokenCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
        # Accept raw Fernet key or derive from arbitrary secret
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, Exception):
            digest = hashlib.sha256(key.encode("utf-8")).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt token") from exc


_cipher: TokenCipher | None = None


def get_token_cipher(settings: Settings | None = None) -> TokenCipher:
    global _cipher
    if _cipher is None:
        settings = settings or get_settings()
        _cipher = TokenCipher(settings.token_encryption_key)
    return _cipher
