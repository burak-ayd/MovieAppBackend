"""
Kimlik doğrulama sözleşmesi (Pydantic v2).

Sözleşme: SYNC_AUTH_PLAN.md §5.1.
`pydantic[email]` (email-validator) ek bağımlılığı GEREKMEZ; e-posta biçimi
küçük bir normalizatörle denetlenir.
"""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import Field, field_validator

from Core.Libs.SyncModels import DeviceSummary, JsonModel


# ── Girdi modelleri ──────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")

MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128


class SignupRequest(JsonModel):
    """POST /api/auth/signup gövdesi."""


    email       : str = Field(min_length=3, max_length=254)
    password    : str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    username    : str = Field(min_length=3, max_length=32)
    display_name: Optional[str] = Field(default=None, max_length=64)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value):
        if len(value.strip()) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Parola en az {MIN_PASSWORD_LENGTH} karakter olmalıdır.")
        return value

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("username")
    @classmethod
    def _check_username(cls, value):
        if not _USERNAME_RE.match(value):
            raise ValueError(
                "Kullanıcı adı 3-32 karakter olmalı; harf, rakam, nokta, alt çizgi "
                "ve tire kullanılabilir."
            )
        return value

    @field_validator("display_name", mode="before")
    @classmethod
    def _blank_display_name(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def _check_email(cls, value):
        if not _EMAIL_RE.match(value):
            raise ValueError("Geçerli bir e-posta adresi girin.")
        return value


class LoginRequest(JsonModel):
    """POST /api/auth/login gövdesi."""


    email   : str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class RefreshRequest(JsonModel):
    """POST /api/auth/refresh gövdesi."""


    refresh_token: str = Field(min_length=8, max_length=512)


# ── Çıktı modelleri ──────────────────────────────────────────────────────────


class AuthUser(JsonModel):
    """
    Kimlik doğrulanmış kullanıcının profil görünümü.

    Kimlik bilgisi `auth.users` tablosunda, uygulamaya özel alanlar
    `user_profiles` tablosunda tutulur; bu model ikisini birleştirir.
    """


    id          : str
    email       : Optional[str] = None
    username    : Optional[str] = None
    display_name: Optional[str] = None
    avatar_url  : Optional[str] = None
    bio         : Optional[str] = None
    language    : Optional[str] = "tr"
    is_private  : bool = False
    birth_date  : Optional[str] = None
    created_at  : Optional[str] = None
    updated_at  : Optional[str] = None


class AuthSessionResponse(JsonModel):
    """
    signup / login / refresh ortak yanıt gövdesi.

    Not: GoTrue "Confirm email" ayarı kapalı olduğu için oturum token'ları
    yanıtla birlikte döner; ayrı bir doğrulama adımı yoktur.
    """


    access_token : str
    refresh_token: str
    token_type   : str = "bearer"
    expires_in   : int = 3600
    user         : AuthUser


class MeResponse(JsonModel):
    """GET /api/auth/me — profil + bağlı cihaz listesi."""


    user   : AuthUser
    devices: List[DeviceSummary] = Field(default_factory=list)


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "SignupRequest",
    "LoginRequest",
    "RefreshRequest",
    "AuthUser",
    "AuthSessionResponse",
    "MeResponse",
]
